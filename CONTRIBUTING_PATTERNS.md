# Padrões de Desenvolvimento - GROM OCR

*Guia para contribuidores que desejam revolucionar a análise forense de placas veiculares*

## 🎯 Visão

GROM OCR é um **sistema de referência nacional** para análise forense de placas. Todos os código deve ser:

✅ **Confiável**: Máxima acurácia com auditoria completa
✅ **Rastreável**: Cadeia de custódia digital em cada operação
✅ **Escalável**: Preparado para múltiplas instituições
✅ **Claro**: Documentação técnica para colaboração

---

## 📋 Arquitetura de Orquestração

### Padrão: Delegação Robusta em Cascata

Toda tarefa crítica deve seguir este padrão:

```python
# 1. Inicializar contexto forense com orquestrador
orchestrator = get_global_orchestrator()
context = orchestrator.create_analysis_context(
    source_filename=upload.filename,
    analysis_stage='final',
)

# 2. Definir hierarquia de tarefas com dependências
tasks = {
    'detect': TaskDomain.PLATE_DETECTION,
    'ocr': TaskDomain.OCR_RECOGNITION,
    'validate': TaskDomain.QUALITY_VALIDATION,
}
dependencies = {
    'ocr': ['detect'],      # ocr depende de detect
    'validate': ['ocr'],    # validate depende de ocr
}
task_order = orchestrator.define_task_hierarchy(tasks, dependencies)

# 3. Executar cada tarefa com delegação automática
for task_name in task_order:
    success, result = orchestrator.execute_task(
        task_name,
        executor_function,  # função local que executa a tarefa
        *args,
        **kwargs,
    )

    if not success and orchestrator.context.tasks[task_name].critical:
        break  # Parar se tarefa crítica falhou

# 4. Consolidar resultados com auditoria
final_report = orchestrator.consolidate_results()
return JSONResponse(final_report)
```

### Implementação de Nova Rota

Quando adicionar novo endpoint, siga este template:

```python
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi_backend.orchestrator import (
    ForensicOrchestrator, TaskDomain,
    get_global_orchestrator,
)

@app.post("/novo-endpoint")
async def novo_endpoint(
    upload: UploadFile = File(...),
    analysis_stage: str = Form(default='final'),
):
    """
    Descrição clara da tarefa forense.

    Hierarquia de tarefas:
    1. task1 - descrição
    2. task2 - descrição (depende de task1)
    3. task3 - descrição (depende de task2)

    Suporta delegação robusta ao pipeline legado.
    """
    # Inicializar orquestrador
    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(
        source_filename=upload.filename or 'upload.jpg',
        analysis_stage=analysis_stage,
    )

    # Definir hierarquia
    tasks = {
        'task1': TaskDomain.PLATE_DETECTION,
        'task2': TaskDomain.OCR_RECOGNITION,
        'task3': TaskDomain.QUALITY_VALIDATION,
    }
    dependencies = {
        'task2': ['task1'],
        'task3': ['task2'],
    }
    task_order = orchestrator.define_task_hierarchy(tasks, dependencies)

    # Executar (se delegação habilitada, tentará pipeline legado)
    success1, result1 = orchestrator.execute_task(
        'task1',
        _execute_task1_locally,
        upload,
    )

    if not success1:
        return JSONResponse(
            status_code=503,
            content={'error': 'task1_failed'},
        )

    # Continuar com próximas tarefas...

    # Consolidar com auditoria
    report = orchestrator.consolidate_results()
    report['your_data'] = result1

    return JSONResponse(report)

def _execute_task1_locally(upload):
    """Executor local que será usado em fallback."""
    # Implementar lógica aqui
    return {...}
```

---

## 🔐 Domínios Forenses Disponíveis

Ao adicionar nova tarefa, use um dos domínios definidos:

```python
class TaskDomain(str, Enum):
    PLATE_DETECTION = "plate_detection"        # Detecção de placa
    OCR_RECOGNITION = "ocr_recognition"        # Reconhecimento de caracteres
    VEHICLE_ANALYSIS = "vehicle_analysis"      # Análise de veículo
    ENSEMBLE_DETECTION = "ensemble_detection"  # Detecção em ensemble
    CALIBRATION = "calibration"                # Calibração de modelos
    QUALITY_VALIDATION = "quality_validation"  # Validação de qualidade
    REPORT_GENERATION = "report_generation"    # Geração de relatório
    FORENSIC_CHAIN = "forensic_chain"          # Cadeia de custódia
```

Se precisar de novo domínio, adicione em `fastapi_backend/orchestrator.py`:

```python
class TaskDomain(str, Enum):
    # ... existentes ...
    MEU_NOVO_DOMINIO = "meu_novo_dominio"
```

---

## 📊 Métricas e Auditoria

Toda tarefa registra automaticamente:

```python
{
    "task_id": "12ab34cd56ef78_detect",
    "task_name": "detect",
    "domain": "plate_detection",

    "status": "completed",              # PENDING, RUNNING, DELEGATED, COMPLETED, FAILED, FALLBACK
    "started_at_utc": "2026-05-09T...",
    "finished_at_utc": "2026-05-09T...",
    "duration_ms": 234.5,

    "delegated": false,                 # Se foi delegada ao pipeline legado
    "delegated_engine": null,           # Qual engine
    "fallback_used": false,             # Se usou fallback local
    "fallback_reason": null,            # Por quê

    "errors": [],
    "warnings": [],
    "result_preview": {...}
}
```

**Sempre verifique**: Se tarefa foi delegada? Se usou fallback? Isso aparece automaticamente nos resultados.

---

## ✅ Checklist de Qualidade

Antes de fazer commit, verifique:

- [ ] **Código compila sem erros**: `python -m py_compile seu_arquivo.py`
- [ ] **Segue padrão de delegação**: Usa orquestrador para tarefas críticas?
- [ ] **Incluir documentação**: Docstring clara explicando hierarquia
- [ ] **Auditoria integrada**: Métricas são registradas automaticamente?
- [ ] **Fallback graceful**: Em caso de erro, qual é o comportamento?
- [ ] **Testes passam**: Execute `pytest test_*.py -v`
- [ ] **Sem warnings Pylance**: `mcp_pylance_mcp_s_pylanceFileSyntaxErrors`
- [ ] **Commit descritivo**: Mensagem clara do que foi feito

---

## 🚀 Execução de Revalidação Automática

Para testar mudanças com revalidação completa:

```bash
# Modo completo: gates + integração + relatório
python tools/orchestrator_executor.py --mode full

# Apenas gates de qualidade
python tools/orchestrator_executor.py --mode gates-only

# Apenas calibração
python tools/orchestrator_executor.py --mode calibration

# Modo simulação (dry-run)
python tools/orchestrator_executor.py --mode full --dry-run
```

**Resultado**: JSON com métricas + Markdown com sumário

---

## 📝 Exemplo: Adicionando Novo Endpoint

### Scenario: Adicionar "/analyze-suspect-region"

1. **Definir tarefa**:

```python
@app.post("/analyze-suspect-region")
async def analyze_suspect_region(
    file: UploadFile = File(...),
    region_coords: str = Form(...),  # "x1,y1,x2,y2"
):
    """Análise forense em região suspeita da imagem."""

    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(
        source_filename=file.filename,
        analysis_stage='investigacao',
    )

    tasks = {
        'extract_region': TaskDomain.PLATE_DETECTION,
        'enhance': TaskDomain.QUALITY_VALIDATION,
        'ocr': TaskDomain.OCR_RECOGNITION,
    }
    dependencies = {
        'enhance': ['extract_region'],
        'ocr': ['enhance'],
    }
    orchestrator.define_task_hierarchy(tasks, dependencies)

    # Executar cada tarefa
    success, region = orchestrator.execute_task(
        'extract_region',
        _extract_region_locally,
        file,
        region_coords,
    )

    if not success:
        return JSONResponse({'error': 'region_extraction_failed'}, status_code=400)

    success, enhanced = orchestrator.execute_task(
        'enhance',
        _enhance_region_locally,
        region,
    )

    success, ocr_result = orchestrator.execute_task(
        'ocr',
        _recognize_text_locally,
        enhanced,
    )

    # Consolidar
    report = orchestrator.consolidate_results()
    report['region_analysis'] = {
        'original_coords': region_coords,
        'extracted_region_path': region,
        'enhancement_applied': bool(enhanced),
        'ocr_result': ocr_result,
    }

    return JSONResponse(report)

def _extract_region_locally(file, coords_str):
    # Implementar
    pass

def _enhance_region_locally(region_path):
    # Implementar
    pass

def _recognize_text_locally(enhanced_path):
    # Implementar
    pass
```

1. **Testar**:

```bash
# Manual
curl -X POST http://127.0.0.1:8000/analyze-suspect-region \
  -F "file=@test.jpg" \
  -F "region_coords=100,100,500,300"

# Com revalidação
python tools/orchestrator_executor.py --mode full
```

1. **Validar saída**:

```json
{
  "analysis_id": "...",
  "orchestration": {
    "task_order": ["extract_region", "enhance", "ocr"],
    "tasks": {
      "extract_region": {
        "status": "completed",
        "delegated": false,
        "duration_ms": 123
      },
      ...
    }
  },
  "region_analysis": { ... }
}
```

---

## 🔍 Debugging

### Ver logs de execução

```bash
# Abrir em VS Code
code logs/orchestrator_executor.log

# Ou tail em tempo real
Get-Content logs/orchestrator_executor.log -Tail 50 -Wait  # PowerShell
tail -f logs/orchestrator_executor.log                      # Linux
```

### Ativar debug mode

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Acessar métricas de tarefa

```python
# Dentro de endpoint
orchestrator = get_global_orchestrator()
if orchestrator.context:
    for task_id, metrics in orchestrator.context.tasks.items():
        print(f"{task_id}: {metrics.status} ({metrics.duration_ms}ms)")
```

---

## 🎯 Objetivos de Conformidade Institucional

Toda contribuição deve alinhar com:

✅ **Segurança**: Nenhum dado forense em plain text
✅ **Auditoria**: Cada operação é registrada
✅ **Conformidade**: Alinhado com padrões policiais
✅ **Rastreabilidade**: UUID único para cada análise
✅ **Replicabilidade**: Mesmos inputs → mesmos outputs

---

## 📚 Referências

- [ARCHITECTURE_PERICIAL.md](../ARCHITECTURE_PERICIAL.md) - Arquitetura completa
- [fastapi_backend/orchestrator.py](../fastapi_backend/orchestrator.py) - Código do orquestrador
- [fastapi_backend/main.py](../fastapi_backend/main.py) - Endpoints com orquestração
- [README.md](../README.md) - Documentação operacional

---

## 🤝 Contribuindo

Para contribuir:

1. **Fork** do repositório
2. **Crie branch** descritiva: `feature/analise-novo-dominio`
3. **Siga padrões** de orquestração
4. **Execute testes**: `python tools/orchestrator_executor.py --mode full`
5. **Pull Request** com descrição clara

---

**Juntos, vamos revolucionar a análise forense de placas no Brasil.**

*Versão: 1.0 | Data: 9 de maio de 2026*
