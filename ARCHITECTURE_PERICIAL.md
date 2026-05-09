# Arquitetura Forense de Análise de Placas Veiculares (GROM OCR)

**Versão:** 1.0-Institucional
**Data:** 9 de maio de 2026
**Objetivo:** Revolucionar a análise pericial de placas no Brasil e servir como padrão nacional para instituições de segurança pública

---

## 🎯 Propósito Institucional

O GROM OCR foi redesenhado para ser **referência nacional** em:

1. **Confiabilidade Forense** - Análise com máxima acurácia e auditoria completa
2. **Conformidade Protocolar** - Alinhamento com procedimentos de instituições policiais
3. **Rastreabilidade Total** - Cadeia de custódia digital de cada análise
4. **Escalabilidade Institucional** - Pronto para adoção por múltiplos órgãos públicos
5. **Transparência Técnica** - Documentação clara para investigação criminal colaborativa

---

## 🏗️ Arquitetura de Orquestração Forense

### Conceito: Delegação Robusta em Cascata

A arquitetura implementa um **padrão de orquestração centralizado** que:

```
Entrada (imagem)
    ↓
[Orquestrador Forense]
    ├── Define hierarquia de tarefas com dependências
    ├── Tenta delegação ao pipeline pericial legado (mais confiável)
    ├── Em falha: executa fallback local com rastreamento
    └── Consolida resultados com auditoria
    ↓
Saída (análise + cadeia de custódia)
```

### Componentes Principais

#### 1. **ForensicOrchestrator** (`fastapi_backend/orchestrator.py`)

Classe central que coordena:

- **Criação de Contexto**: `create_analysis_context()` - instancia nova análise com ID único
- **Hierarquia de Tarefas**: `define_task_hierarchy()` - cria grafo acíclico de dependências
- **Execução Delegada**: `execute_task()` - executa com delegação + fallback
- **Consolidação**: `consolidate_results()` - agrupa resultados com auditoria
- **Rastreamento**: `_audit_log()` - registra cada evento para cadeia de custódia

#### 2. **Contexto Forense** (`ForensicAnalysisContext`)

Encapsula estado completo de uma análise:

```python
@dataclass
class ForensicAnalysisContext:
    analysis_id: str                      # ID único (UUID truncado)
    source_filename: Optional[str]        # Nome original do arquivo
    analysis_stage: str                   # 'preview', 'investigacao', 'final'

    tasks: Dict[str, TaskExecutionMetrics]     # Estado de cada tarefa
    task_dependencies: Dict[str, List[str]]    # Grafo de dependências
    task_order: List[str]                      # Ordem topológica

    delegated_results: Dict[str, Any]          # Resultados do pipeline legado
    fallback_results: Dict[str, Any]           # Resultados do fallback local
    enriched_payload: Dict[str, Any]           # Payload enriquecido final

    audit_trail: List[Dict[str, Any]]          # Cadeia de custódia digital
    quality_gates_passed: Dict[str, bool]      # Status de cada gate
```

#### 3. **Métricas de Execução** (`TaskExecutionMetrics`)

Rastreia cada tarefa com precisão:

```python
@dataclass
class TaskExecutionMetrics:
    task_id: str                    # ID único da instância da tarefa
    task_name: str                  # Nome da tarefa
    domain: TaskDomain              # Domínio: DETECTION, OCR, etc

    status: TaskStatus              # PENDING, RUNNING, DELEGATED, COMPLETED, FAILED, FALLBACK
    started_at_utc: Optional[str]   # Timestamp ISO de início
    finished_at_utc: Optional[str]  # Timestamp ISO de fim
    duration_ms: float              # Duração em milissegundos

    delegated: bool                 # Se foi delegada ao legado
    delegated_engine: Optional[str]  # Qual engine ("ocr_agent_flask", etc)
    fallback_used: bool             # Se usou fallback local
    fallback_reason: Optional[str]   # Motivo do fallback

    errors: List[str]               # Erros capturados
    warnings: List[str]             # Avisos (degradação graceful)
    result_preview: Dict[str, Any]  # Resumo do resultado
```

---

## 📊 Domínios de Análise Forense

Cada análise percorre domínios especializados:

| Domínio | Descrição | Pipeline Legado | Fallback |
|---------|-----------|-----------------|----------|
| **PLATE_DETECTION** | Localizar placa na imagem | YOLOv8 + Heurísticas | Contour detection |
| **OCR_RECOGNITION** | Ler caracteres da placa | Ensemble (RapidOCR, Tesseract) | Tesseract simples |
| **VEHICLE_ANALYSIS** | Identificar marca/modelo | CLIP + Heurísticas | Análise visual local |
| **ENSEMBLE_DETECTION** | Detecção multi-modelo | YOLO + Fallback | Contours + NMS |
| **CALIBRATION** | Calibração de modelos | Bateria forense | Skipped |
| **QUALITY_VALIDATION** | Validação de qualidade | Pipeline pericial | Análise local |
| **REPORT_GENERATION** | Gerar relatório pericial | PDF + Cadeia de custódia | Texto simples |
| **FORENSIC_CHAIN** | Manter cadeia de custódia | Assinatura digital | Log textual |

---

## 🔄 Hierarquia de Tarefas e Dependências

### Exemplo: Pipeline de /process (Delegado)

```
┌─────────────────────────────────┐
│  Análise Pericial Completa      │
│  analysis_id: 12ab34cd56ef78gh  │
└─────────────────────────────────┘
              ↓
         [DELEGAÇÃO]
              ↓
         Flask ocr_agent.py
         /process endpoint
              ↓
    ┌────────────────────┐
    │ Retorna payload    │
    │ com todos os dados │
    │ periciaisrais      │
    └────────────────────┘
```

### Exemplo: Pipeline de /process-ensemble (Local + Orquestração)

```
┌──────────────────────────────────────┐
│  Análise Ensemble Orquestrada        │
│  analysis_id: 987654321abcdef        │
└──────────────────────────────────────┘
              ↓
    ┌─────────────────────┐
    │ TASK: detect        │ → Ensemble Detection (YOLO + Contours)
    │ DOMAIN: ENSEMBLE    │   Status: COMPLETED
    │ DELEGATED: false    │   Duration: 234ms
    └─────────────────────┘
              ↓ (depende de 'detect')
    ┌─────────────────────┐
    │ TASK: ocr           │ → OCR Recognition (Ensemble)
    │ DOMAIN: OCR         │   Status: COMPLETED
    │ DELEGATED: false    │   Duration: 156ms
    └─────────────────────┘
              ↓ (depende de 'ocr')
    ┌─────────────────────┐
    │ TASK: validate      │ → Quality Validation
    │ DOMAIN: QUALITY     │   Status: COMPLETED
    │ DELEGATED: false    │   Duration: 89ms
    └─────────────────────┘
              ↓
    ┌─────────────────────────────────────┐
    │ Consolidação de Resultados          │
    │ + Cadeia de Custódia Digital        │
    │ + Auditoria Forense                 │
    └─────────────────────────────────────┘
```

---

## 🔐 Cadeia de Custódia Digital (Audit Trail)

Cada análise mantém trilha completa de eventos:

```json
{
  "analysis_id": "12ab34cd56ef78",
  "created_at_utc": "2026-05-09T12:16:49.675Z",
  "audit_trail": [
    {
      "timestamp_utc": "2026-05-09T12:16:49.700Z",
      "event": "context_created",
      "details": {
        "source_filename": "20171119_154214_ch6-1024x576.jpg",
        "analysis_stage": "final"
      }
    },
    {
      "timestamp_utc": "2026-05-09T12:16:49.710Z",
      "event": "task_hierarchy_defined",
      "details": {
        "task_order": ["detect", "ocr", "validate"],
        "total_tasks": 3
      }
    },
    {
      "timestamp_utc": "2026-05-09T12:16:50.000Z",
      "event": "task_completed:detect",
      "details": {
        "task_id": "12ab34cd56ef78_detect",
        "status": "completed",
        "delegated": false,
        "duration_ms": 234
      }
    },
    {
      "timestamp_utc": "2026-05-09T12:16:50.200Z",
      "event": "task_completed:ocr",
      "details": {
        "task_id": "12ab34cd56ef78_ocr",
        "status": "completed",
        "delegated": false,
        "duration_ms": 156,
        "result_preview": {
          "text": "DFO8819",
          "confidence": 0.857
        }
      }
    },
    {
      "timestamp_utc": "2026-05-09T12:16:50.350Z",
      "event": "task_completed:validate",
      "details": {
        "task_id": "12ab34cd56ef78_validate",
        "status": "completed",
        "delegated": false,
        "duration_ms": 89,
        "quality_gates_passed": {
          "ocr_pattern": true,
          "confidence_score": true,
          "consensus": true
        }
      }
    },
    {
      "timestamp_utc": "2026-05-09T12:16:50.400Z",
      "event": "analysis_consolidated",
      "details": {
        "total_duration_ms": 550,
        "delegated_tasks": 0,
        "fallback_tasks": 0,
        "quality_passed": true
      }
    }
  ]
}
```

---

## 🔀 Delegação Robusta com Fallback Graceful

### Fluxo de Delegação

```python
# 1. Tentar delegação ao pipeline legado (mais confiável)
if enable_delegations and legacy_ocr_agent:
    try:
        result = delegate_to_legacy_engine(task)
        metrics.delegated = True
        metrics.delegated_engine = "ocr_agent_flask"
        return result

    except DelegationError as e:
        # 2. Em falha: executar fallback local
        logger.warning(f"Delegação falhou: {e}. Usando fallback...")
        metrics.fallback_used = True
        metrics.fallback_reason = str(e)
        metrics.warnings.append(f"delegacao_fallback:{e}")

        # 3. Executar executor local
        return executor(*args, **kwargs)
```

### Benefícios

✅ **Disponibilidade**: Se pipeline legado falhar, sistema continua funcionando
✅ **Qualidade Gradual**: Sempre obtém melhor resultado disponível
✅ **Rastreamento**: Saiba exatamente quando usou fallback
✅ **Auditoria**: Cada degradação é registrada

---

## 📈 Integração com Endpoints FastAPI

### /process (Principal)

**Antes**: Pipeline simplificado local → Baixa acurácia
**Depois**: Delegação direta ao pipeline forense legado → Alta acurácia + Auditoria

```python
@app.post("/process")
async def process_legacy_endpoint(image: UploadFile = File(None), ...):
    if _is_legacy_pipeline_enabled() and _legacy_pipeline_ok:
        # Tenta delegação (novo padrão)
        return _delegate_to_legacy_process(upload, analysis_stage)

    # Fallback: pipeline simplificado local
    ...
```

### /process-ensemble (Ensemble)

**Antes**: Sem orquestração
**Depois**: Orquestrada com hierarquia de tarefas

```python
@app.post("/process-ensemble")
async def process_ensemble_endpoint(...):
    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(...)

    # Define hierarquia
    tasks = {'detect': ENSEMBLE, 'ocr': OCR, 'validate': QUALITY}
    task_order = orchestrator.define_task_hierarchy(tasks, deps)

    # Executa com rastreamento
    for task_name in task_order:
        success, result = orchestrator.execute_task(task_name, executor)

    # Consolida com auditoria
    report = orchestrator.consolidate_results()
    return JSONResponse(report)
```

### /full-pipeline (Completo)

**Antes**: Sem orquestração
**Depois**: Orquestrado ponta a ponta

```python
@app.post("/full-pipeline/")
async def full_pipeline(file: UploadFile = File(...)):
    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(...)

    tasks = {
        'detect': PLATE_DETECTION,
        'ocr': OCR_RECOGNITION,
        'validate': QUALITY_VALIDATION,
    }
    task_order = orchestrator.define_task_hierarchy(tasks, {...})

    # Executa hierarquia
    for task in task_order:
        success, result = orchestrator.execute_task(task, ...)

    return JSONResponse(orchestrator.consolidate_results())
```

---

## 🎯 Revalidação Forense com Gates

Sistema de qualidade institucional:

```bash
# Executar revalidação completa
python tools/revalidate_forensic_quality.py \
    --policy-file data/phase1_quality_gate_policy.json \
    --skip-refresh-manifests

# Resultado
{
  "passed": true,
  "runs": [
    {
      "name": "image_calibration_battery",
      "ok": true,
      "gate": {
        "passed": true,
        "checks": [
          {
            "name": "ocr_text_confidence_min",
            "passed": true,
            "value": 0.857,
            "threshold": 0.75
          },
          ...
        ]
      }
    }
  ]
}
```

---

## 📋 Conformidade Institucional

### Para Instituições Policiais Adotantes

Cada análise fornece:

1. **Cadeia de Custódia Completa**
   - Timestamp UTC de cada operação
   - Identificação de quem processou
   - Justificativa técnica de cada decisão

2. **Rastreabilidade Total**
   - Analysis ID único para auditoria
   - Logs estruturados em JSON
   - Possibilidade de reprocessamento idêntico

3. **Qualidade Mensurável**
   - Score de confiança por tarefa
   - Status de gates de qualidade
   - Indicação clara de fallback (se houve)

4. **Documentação Técnica**
   - Cada modelo e versão registrados
   - Parâmetros de execução capturados
   - Duração e recursos consumidos

### Exemplo de Saída Institucional

```json
{
  "forensic_analysis": {
    "analysis_id": "12ab34cd56ef78",
    "source_filename": "20171119_154214_ch6-1024x576.jpg",
    "analysis_stage": "final",
    "timestamp_utc": "2026-05-09T12:16:49.675Z",

    "ocr_result": {
      "text": "DFO8819",
      "confidence": 0.857,
      "pattern": "Antigo",
      "consensus_ratio": 1.0
    },

    "quality_gates": {
      "ocr_pattern_valid": true,
      "confidence_score_passed": true,
      "consensus_sufficient": true,
      "overall_passed": true
    },

    "execution": {
      "total_duration_ms": 550,
      "tasks_completed": 3,
      "delegated_tasks": 0,
      "fallback_used": false,
      "quality_level": "CONCLUSIVO"
    },

    "audit_trail": [/* eventos */ ],

    "institutional_notes": [
      "Análise executada conforme protocolos GROM_OCR v1.0",
      "Cadeia de custódia digital preservada",
      "Pronto para uso em investigação criminal"
    ]
  }
}
```

---

## 🚀 Adoção por Outras Instituições

### Pré-requisitos

- Python 3.11+
- FastAPI + Uvicorn
- Modelos YOLOv8, Tesseract, RapidOCR (ou Paddle como alternativa)
- PostgreSQL ou SQLite para auditoria (opcional)

### Instalação Rápida

```bash
# Clone do repositório
git clone https://github.com/seu-org/grom-ocr.git
cd grom_ocr

# Ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate  # Windows

# Dependências
pip install -r requirements.txt

# Bootstrap com serviços
powershell -ExecutionPolicy Bypass \
  -File tools/ensure_grom_ocr_services.ps1

# Abrir navegador
# http://127.0.0.1:8080
```

### Customização por Instituição

Cada instituição pode:

1. **Ajustar Gates de Qualidade**
   - Editar `data/phase1_quality_gate_policy.json`
   - Definir thresholds conforme padrões locais

2. **Adicionar Domínios Específicos**
   - Estender `TaskDomain` em `orchestrator.py`
   - Implementar executores customizados

3. **Integrar com Sistemas Legados**
   - APIs REST wrapper em `public/api.php`
   - Banco de dados local para casos
   - Integração com SIGPol/SPU/INFORMA

---

## 📚 Documentação Técnica Completa

- **Orquestrador**: [fastapi_backend/orchestrator.py](fastapi_backend/orchestrator.py)
- **Integração FastAPI**: [fastapi_backend/main.py](fastapi_backend/main.py#L24-L80)
- **Executor de Tasks**: [tools/orchestrator_executor.py](tools/orchestrator_executor.py)
- **Revalidação Forense**: [tools/revalidate_forensic_quality.py](tools/revalidate_forensic_quality.py)
- **README Operacional**: [README.md](README.md)

---

## 🎓 Conclusão

O GROM OCR v1.0 revoluciona análise forense de placas através de:

✅ **Orquestração centralizada** com hierarquia de tarefas
✅ **Delegação robusta** com fallback graceful
✅ **Cadeia de custódia digital** para auditoria completa
✅ **Conformidade institucional** para múltiplos órgãos públicos
✅ **Documentação clara** para adoção nacional

Vamos ser a **referência nacional** em análise pericial de placas e ajudar a desvendar crimes com exatidão absoluta.

---

*Criado para revolucionar segurança pública no Brasil e servir como exemplo para instituições policiais em todo o mundo.*
