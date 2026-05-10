# MATRIX TÉCNICA: Datasets ↔ Componentes GROM OCR

Mapeamento de como cada dataset se conecta aos componentes do sistema.

---

## CAMADAS DO GROM E SEUS INPUTS

```
┌─────────────────────────────────────────────────────────────────┐
│                    GROM OCR - Camadas Técnicas                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ [VIDEO/IMAGEM ENTRADA]                                           │
│         ↓                                                         │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │  LAYER 1: DETECTION (YOLO v8)                               │ │
│ │  INPUT: Imagem bruta                                         │ │
│ │  OUTPUT: Bbox de veículo + confiança                         │ │
│ │  DATASET USADO: UFPR-VeSV (fine-tuning)                      │ │
│ │  MELHORIA: Robustez em vigilância real                       │ │
│ └──────────────────────────────────────────────────────────────┘ │
│         ↓                                                         │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │  LAYER 2: OCR + PLACA VALIDATION                             │ │
│ │  INPUT: Crop de placa (de YOLO)                              │ │
│ │  OUTPUT: Placa texto + padrão                                │ │
│ │  DATASET USADO: Tesseract/EasyOCR (já integrado)             │ │
│ │  MELHORIA: (não muda nesta fase)                             │ │
│ └──────────────────────────────────────────────────────────────┘ │
│         ↓                                                         │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │  LAYER 3: VEHICLE ANALYSIS                                   │ │
│ │  INPUT: Imagem inteira do veículo                            │ │
│ │  OUTPUT: Color, class, make/model (CLIP candidates)          │ │
│ │  DATASET USADO: BRCars (database visual)                     │ │
│ │  MELHORIA: Candidates para OSINT                             │ │
│ └──────────────────────────────────────────────────────────────┘ │
│         ↓                                                         │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │  LAYER 4: OSINT (NOVO - vehicle_osint_v2.py)                │ │
│ │  INPUT: Color, class, plate_partial (se houver)              │ │
│ │  OUTPUT: Top 3-5 model candidates com scores                 │ │
│ │  DATASETS USADOS:                                             │ │
│ │    - BRCars (semantic matching)                               │ │
│ │    - brazilian-cars ref (validation)                          │ │
│ │    - OpenCLIP embeddings (semantic reranking)                 │ │
│ │  MELHORIA: ★★★★★ (core enhancement)                          │ │
│ └──────────────────────────────────────────────────────────────┘ │
│         ↓                                                         │
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │  LAYER 5: REPORT GENERATION (PDF Forense)                    │ │
│ │  INPUT: OSINT top_candidates                                 │ │
│ │  OUTPUT: PDF com seção de OSINT                              │ │
│ │  (pdf_forensic.py - já integrado)                            │ │
│ │  MELHORIA: (apenas display de dados OSINT v2)                │ │
│ └──────────────────────────────────────────────────────────────┘ │
│         ↓                                                         │
│   [SAÍDA: JSON + PDF]                                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## MATRIX DATASETS × CAMADAS

```
                      │ DETECTION │  OCR  │ VEHICLE │ OSINT │ REPORT │
                      │ (YOLO)    │       │ANALYSIS │       │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
BRCars Dataset        │     ○     │   ○   │    ◉    │  ◉◉◉  │    ◉   │
  (500k imagens)      │           │       │ CLIP    │ MAIN  │ display│
                      │           │       │ features│ DB    │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
UFPR-VeSV Dataset     │    ◉◉◉    │   ○   │    ◉    │   ○   │    ○   │
  (15k vigilância)    │   TRAIN   │       │ features│       │        │
                      │           │       │         │       │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
brazilian-cars ref    │     ○     │   ○   │    ◉    │  ◉◉   │    ○   │
  (JSON lookup)       │           │       │ classes │VALIDAT│        │
                      │           │       │         │OR     │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
VMMRdb (opcional)     │    ◉◉     │   ○   │    ◉◉   │   ◉   │    ○   │
  (pré-treinamento)   │   TRANSFER│       │ TRANSFER│ scores│        │
                      │ LEARNING  │       │ LEARNING│       │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
Car-Parts Segmentação │     ○     │   ○   │    ◉    │   ◉   │    ◉   │
  (opcional)          │           │       │ geometric│geometry│context│
                      │           │       │ features │        │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
Vehicle Lights Dataset│     ○     │   ○   │    ○    │   ◉   │    ◉   │
  (opcional)          │           │       │         │ context│context │
                      │           │       │         │        │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤
OpenCLIP Embeddings   │     ○     │   ○   │    ◉    │  ◉◉◉  │    ○   │
  (semantic search)   │           │       │ embeddings│ RERANK │       │
                      │           │       │         │        │        │
──────────────────────┼───────────┼───────┼─────────┼───────┼────────┤

Legenda:
◉◉◉ = Uso crítico/primário
◉◉  = Uso importante/secundário
◉   = Uso opcional/complementar
○   = Pode ter uso tangencial
```

---

## FLUXO TÉCNICO: Imagem → OSINT Candidates

```
ENTRADA: Imagem veículo (vigilância, rua, etc)
   │
   ↓
[YOLO Detector - com UFPR-VeSV fine-tuning]
   │
   ├─→ Bbox veículo (confidence > 0.5)
   │
   ↓
[Feature Extraction]
   │
   ├─→ Vehicle Class (car, truck, motorcycle)
   ├─→ Color Estimate (branco, preto, prata, etc)
   ├─→ Make/Model CLIP features (features, não labels)
   │
   ↓
[OSINT Search - NOVO com datasets]
   │
   ├─→ Query BRCars Database por (classe, cor)
   │   usando: BRCars metadata index
   │
   ├─→ Initial candidates: ~50 modelos
   │
   ├─→ Semantic Reranking com OpenCLIP
   │   - Compara image embedding com BRCars embeddings
   │   - Score = cosine_similarity(image_emb, model_emb)
   │
   ├─→ Validation against brazilian-cars ref
   │   - Confirma: modelo existe + anos válidos + popular no Brasil
   │
   ├─→ Final Ranking
   │   - Top 5 candidates com scores:
   │     {marca, modelo, ano, cor, semantic_score, validation_score}
   │
   ↓
SAÍDA: JSON com top_model_candidates
   [
     {marca: "Toyota", modelo: "Corolla", semantic_score: 0.87},
     {marca: "Honda", modelo: "Civic", semantic_score: 0.82},
     {...}
   ]
```

---

## DADOS × FUNCIONALIDADES OSINT

### Qual dataset resolve qual problema?

| Problema | Dataset | Solução |
|----------|---------|---------|
| "Detectar veículo em vigilância com vários ângulos" | UFPR-VeSV | Fine-tuning YOLO em pose/ângulo variável |
| "Comparar visual do veículo com modelos conhecidos" | BRCars | Database 500k imagens para matching |
| "Validar se modelo existe no Brasil" | brazilian-cars | Lookup JSON: marca → modelos → anos |
| "Reranking semântico de candidatos" | OpenCLIP | Embeddings vetoriais para similarity |
| "Entender geometria do veículo para placa" | Car-Parts Seg | Detectar para-choque, capô (posição de placa) |
| "Análise de contexto (noite/dia)" | Vehicle Lights | Máscaras de luzes ligadas/desligadas |
| "Pre-training robusto cross-country" | VMMRdb | Transfer learning inicial |

---

## INTEGRAÇÃO NO CÓDIGO: Qual arquivo muda?

```
fastapi_backend/main.py (MODIFICAR)
   ├─ Import: from datasets_loader import get_brcars_database
   ├─ Import: from osint_database import get_osint_database
   ├─ Import: from semantic_search import get_semantic_search
   └─ Função: build_vehicle_osint_report()
        └─ Agora chama: osint_db.search_by_attributes()
        └─ Agora chama: semantic_search.search_query()
        └─ Resultado: BRCars candidates + semantic scores

fastapi_backend/datasets_loader.py (CRIAR)
   ├─ Class: BRCarsDatabase
   │   └─ load() → metadata.json
   │   └─ search(marca, modelo, cor) → candidates
   │
   └─ Class: BrazilianCarsReference
       └─ load() → models.json
       └─ is_valid(marca, modelo, ano) → bool

fastapi_backend/osint_database.py (CRIAR)
   └─ Class: OSINTVehicleDatabase
       ├─ search_by_attributes() → candidates
       └─ semantic_rerank() → top-K scored

fastapi_backend/semantic_search.py (CRIAR)
   └─ Class: SemanticVehicleSearch
       ├─ embed_text() → embedding
       ├─ embed_image() → embedding
       └─ search_query() → reranked candidates

data/datasets/ (CRIAR - estrutura)
   ├── brcars/
   │   ├── metadata.json
   │   └── lookup_table.json
   │
   ├── ufpr-vesv/
   │   ├── train/ (YOLO format)
   │   └── test/
   │
   └── brazilian-cars-ref/
       └── models.json

data/models/ (CRIAR - outputs)
   ├── yolo_brcars_v1.pt
   └── openclip_embeddings/
       └── brcars_embeddings.npy

tools/ (CRIAR - scripts de setup)
   ├── prepare_brcars_dataset.py
   ├── prepare_ufpr_dataset.py
   ├── finetune_yolo.py
   ├── build_openclip_embeddings.py
   └── test_osint_v2.py
```

---

## REQUIREMENTS.TXT (Adições)

```txt
# Existing
ultralytics>=8.0
fastapi>=0.95
pytorch>=2.0  # ou torch

# NEW - OpenCLIP para OSINT semântico
open-clip-torch>=2.20.0
timm>=0.9.0

# NEW - Dataset support
pillow>=10.0
numpy>=1.24

# Optional - Para fine-tuning avançado
transformers>=4.30
tensorboard>=2.14
```

---

## PERFORMANCE EXPECTATIONS

### Antes (OSINT v1):
- Modelo candidates: 0 (apenas placa)
- Tempo: 100ms
- Acurácia: N/A (sem candidates)

### Depois (OSINT v2 com datasets):
- Modelo candidates: 3-5 ranked
- Tempo: 150-300ms (+ embedding lookup)
- Acurácia: ~75-85% (top-1 correto em vigilância real)

### Overhead:
- Latência: +100-200ms (aceitável)
- Memória: +500MB (índices em RAM)
- Disk: +5-10GB (datasets + modelos)

---

## PRÓXIMOS PASSOS

1. **Semana 1:** Implementar estrutura de datasets + OSINT v2
2. **Semana 2:** Fine-tuning YOLO + build embeddings CLIP
3. **Semana 3:** Integração completa + benchmarking
4. **Semana 4+:** Produção + monitoramento

---

**Status:** Roadmap aprovado ✓
**Próxima ação:** Comece pelo `tools/prepare_brcars_dataset.py`
