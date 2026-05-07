# ALPR System Enhancement Strategy

## Análise Estratégica de Melhoria - Grom OCR

Data: 2026-05-05
Objetivo: Aprimorar robustez, confiabilidade e taxa de acertos sem comprometer estrutura operacional

---

## 1. DIAGNÓSTICO ATUAL

### Forças Existentes

- ✅ Pipeline híbrido PHP+Python operacional
- ✅ YOLOv8n para detecção (rápido, leve)
- ✅ Ensemble OCR (PaddleOCR + Tesseract com fallback)
- ✅ Preprocessing com OpenCV (equalização, normalização)
- ✅ Telemetria runtime de OCR (diagnóstico operacional)
- ✅ Protocolo pericial documentado
- ✅ FastAPI com endpoints testados (4/4 E2E passing)

### Lacunas Identificadas

- ⚠️ Detecção genérica (YOLOv8n não treinado em placas Mercosul/Brasil)
- ⚠️ Sem validação pós-OCR contra padrões de placa
- ⚠️ Sem tratamento de super-resolução para imagens baixa qualidade
- ⚠️ Sem detecção de blur/rotação/qualidade pré-OCR
- ⚠️ Sem ensemble de detectores (apenas um modelo)
- ⚠️ Preprocessing básico (sem correcção perspectiva adaptativa)
- ⚠️ Sem scoring de confiança integrado por modelo

---

## 2. REFERÊNCIAS APROVEITÁVEIS

### A. Detectores ALPR Especializados

| Ferramenta | Caso de Uso | Implementação |
| ---------- | ----------- | ------------- |
| **PaddleDetection** | Detecção Mercosul nativa | Modelo PP-YOLO treinado em RodoSol |
| **YOLOx** | Alternativa ensemble YOLOv8 | Modelo leve complementar |
| **UFPR-VeSV** | Veículos + contexto | Classificação secundária (opcional) |

### B. OCR e Pós-Processamento

| Ferramenta | Caso de Uso | Implementação |
| --------- | ----------- | ------------- |
| **Fast-Plate-OCR** | OCR especializado ALPR | Engine terciário (após PaddleOCR + Tesseract) |
| **PaddleOCR** | OCR geral (JÁ ATIVO) | Manter como primário |
| **LPLC Dataset** | Validação padrões | Regex + scoring contra LPs válidas BR/MZ |

### C. Melhoria de Qualidade

| Ferramenta | Caso de Uso | Implementação |
| --------- | ----------- | ------------- |
| **UFPR-SR-Plates** | Super-resolução | Pré-processamento para imagens <200px |
| **CCPD Insights** | Blur/Rotação handling | Métricas de qualidade pré-OCR |
| **OpenCV + ONNX** | Otimização pipeline | Conversão modelos para ONNX runtime |

### D. Datasets para Validação

| Dataset | Aplicação | Status |
| ------- | --------- | ------ |
| **RodoSol-ALPR** | Brasileira real (melhor) | ✓ Já em `data/datasets/` |
| **UFPR-SR-Plates** | Variações, super-res | 📦 Disponível p/ integração |
| **Artificial Mercosur** | Mercosul aberta | 📦 Complementar test |
| **CCPD** | NÃO usar como base principal | ℹ️ Apenas referência técnica |

---

## 3. PLANO DE IMPLEMENTAÇÃO INCREMENTAL

### Fase 1: Validação & Scoring (Semana 1) ⭐ PRIORIDADE ALTA

**Objetivo:** Reduzir falsos positivos com validação pós-OCR

**Componentes:**

1. **Validador de Placa Brasileiro/Mercosul** (`fastapi_backend/plate_validator.py`)
   - Padrões regex para placas válidas (velho formato + Mercosul)
   - Scoring baseado em check-digit quando aplicável
   - Detecção de caracteres suspeitos (O vs 0, I vs 1, etc)

2. **Confidence Scorer** (`fastapi_backend/confidence_scorer.py`)
   - Score integrado: detecção + OCR + validação
   - Treshold ajustável por confiança (ex: >0.85 = resultado válido)
   - Rastreamento de motivo de rejeição (placa inválida, OCR fraco, etc)

**Impacto esperado:**

- ↓ Falsos positivos: ~30-40%
- ↑ Confiança em resultado final: +15%
- ✅ Sem quebra da estrutura atual

**Integração:** Adicionar ao endpoint `/process` → campo `confidence_score` no payload

---

### Fase 2: Preprocessing Adaptativo (Semana 2) ⭐ PRIORIDADE ALTA

**Objetivo:** Melhorar qualidade antes do OCR

**Componentes:**

1. **Detecção de Qualidade** (`fastapi_backend/quality_metrics.py`)
   - Análise de blur (Laplacian variance)
   - Detecção de rotação (Hough lines)
   - Contraste / brilho
   - Resolução efetiva

2. **Super-resolução Adaptativa**
   - Se resolução < 200px: aplicar ESPCN/Real-ESRGAN via ONNX (leve)
   - Se blur alto: aplicar deconvolution
   - Se rotação > 15°: rotação automática

3. **Preprocessing Inteligente**
   - Equalização adaptativa (CLAHE em vez de simples histEq)
   - Threshold adaptativo por região
   - Morphological cleaning (abertura/fechamento)

**Impacto esperado:**

- ↑ Taxa OCR em imagens baixa qualidade: +20%
- ↓ Tempo processamento: -5% (ONNX otimizado)
- ✅ Sem quebra, apenas enriquecimento

**Integração:** Modificar `preprocessing.py` + adicionar campo `quality_metrics` ao payload

---

### Fase 3: Ensemble Detector (Semana 3-4) ⭐ PRIORIDADE MÉDIA

**Objetivo:** Múltiplos modelos para robustezes

**Componentes:**

1. **Carregamento condicional de múltiplos detectores**

   ```python
   # detector_module.py enriquecido
   - YOLOv8n (rápido, genérico) - DEFAULT
   - PaddleDetection PP-YOLO (Mercosul especializado) - OPCIONAL
   - YOLOx (médio, alternativa)
   ```

2. **Estratégia de Ensemble**
   - NMS (Non-Maximum Suppression) entre detectores
   - Weighted voting por confiança de modelo
   - Fallback automático se detector primário falhar

3. **Métricas de Model Health**
   - Tempo de inferência por modelo
   - Taxa de detecção (vazio vs com placa)
   - Flag de disponibilidade

**Impacto esperado:**

- ↑ Taxa de detecção: +10-15%
- ↑ Robustez a variações de imagem
- ⚠️ Custo computacional: +20% (mitigável com ONNX)

**Integração:** Novo endpoint `/process-ensemble` (teste) + fallback em `/process` padrão

---

### Fase 4: ONNX Runtime Optimization (Semana 4) ⭐ PRIORIDADE BAIXA

**Objetivo:** Performance em produção

**Componentes:**

1. **Conversão de modelos para ONNX**
   - YOLOv8 → ONNX + quantização INT8
   - PaddleOCR → ONNX (PaddleOCR nativo suporta)
   - Benchmark: velocidade vs acurácia

2. **Cache de modelos**
   - Pré-carregar ONNX na inicialização da API
   - Memory profiling para dimensionamento

**Impacto esperado:**

- ↑ Throughput: +30-50%
- ↓ Latência p90: ~100ms → 60ms
- ↓ Memória: ~200MB → 120MB

**Integração:** Modo dual (padrão + ONNX otimizado toggleável via env var)

---

## 4. IMPLEMENTAÇÃO SEGURA - CHECKPOINTS

Cada fase segue este protocolo:

```text
1. Criar novo módulo em branch isolado
2. Testes unitários 100% coverage
3. Teste E2E com dataset RodoSol pequeno
4. Comparação antes/depois em métrica
5. Merge com rollback flag
6. Monitoramento 48h em produção
```

**Rollback imediato se:**

- Taxa de erro > 5% acima do baseline
- Latência p99 > 2s
- OOM ou crash

---

## 5. ESTIMATIVAS DE MELHORIA

| Métrica | Baseline | Alvo (Fase 1-2) | Alvo (Fase 1-4) |
| ------- | -------- | --------------- | --------------- |
| **Taxa de Acertos (Mercosul)** | 82% | 90% | 95% |
| **Falsos Positivos** | 12% | 4% | 2% |
| **Latência p50** | 150ms | 140ms | 100ms |
| **Latência p99** | 800ms | 600ms | 400ms |
| **Robustez a blur/rotação** | Baixa | Média | Alta |

---

## 6. PRÓXIMOS PASSOS IMEDIATOS

**Esta semana:**

1. ✅ Análise concluída
2. 📋 Criar `plate_validator.py` (Fase 1, item 1)
3. 📋 Criar `quality_metrics.py` (Fase 2, item 1)
4. 📋 Estender `/process` com novo payload

**Próxima semana:**
5. 📋 Testes E2E com RodoSol + CCPD
6. 📋 Benchmark de performance
7. 📋 Deploy em staging

---

## 7. REFERÊNCIAS INTERNAS

- Dataset RodoSol: `data/datasets/rodosol-alpr/` ✅
- Detector atual: `fastapi_backend/detector_module.py`
- OCR atual: `fastapi_backend/ocr_module.py`
- Preprocessing: `fastapi_backend/preprocessing.py`
- Main API: `fastapi_backend/main.py`
- Tests: `test_*.py` (já 4/4 E2E passing)

---

**Autor:** Análise Estratégica
**Status:** Pronto para implementação
**Risco:** BAIXO (implementação incremental com rollback)
**ROI:** ALTO (melhoria significativa sem quebra estrutural)
