<!-- markdownlint-disable MD060 MD040 MD036 -->

# GUIA DE IMPLEMENTAÇÃO: Integrar Datasets + Tecnologias no GROM OCR

**Objetivo:** Traduzir análise de datasets em código executável
**Data:** 10 de maio de 2026
**Status:** Planning phase → Ready for execution

---

## PARTE I: ESTRUTURA DE DIRETÓRIOS (Setup)

```
c:\Grom_OCR\
├── data/
│   ├── datasets/                    # ← NOVO
│   │   ├── brcars/                  # BRCars Dataset
│   │   │   ├── images/              # 500k imagens
│   │   │   ├── metadata.json        # Marca/modelo/cor/ano
│   │   │   └── lookup_table.json    # Index para busca rápida
│   │   │
│   │   ├── ufpr-vesv/               # UFPR-VeSV Dataset
│   │   │   ├── train/
│   │   │   ├── test/
│   │   │   └── annotations_yolo/    # Formato YOLO
│   │   │
│   │   └── brazilian-cars-ref/      # gpupo/brazilian-cars
│   │       └── models.json          # Lookup de modelos nacionais
│   │
│   └── models/                      # Modelos treinados
│       ├── yolo_brcars_v1.pt        # ← Fine-tuned YOLOv8
│       └── openclip_embeddings/     # ← CLIP vectors
│
├── fastapi_backend/
│   ├── vehicle_osint.py             # ← Já existe
│   ├── vehicle_osint_v2.py          # ← NOVO (com OpenCLIP)
│   ├── datasets_loader.py           # ← NOVO
│   ├── osint_database.py            # ← NOVO (BRCars index)
│   └── semantic_search.py           # ← NOVO (OpenCLIP search)
│
└── tools/
    ├── prepare_brcars_dataset.py    # ← NOVO (Download/structure)
    ├── prepare_ufpr_dataset.py      # ← NOVO (YOLO format)
    ├── finetune_yolo.py             # ← NOVO (Training)
    ├── build_openclip_embeddings.py # ← NOVO (Precompute vectors)
    └── test_osint_v2.py             # ← NOVO (Validation)
```

---

## PARTE II: MÓDULO 1 - CARREGADOR DE DATASETS

**Arquivo:** `fastapi_backend/datasets_loader.py` (novo)

```python
"""
Carregador de datasets brasileiros para OSINT.
Responsabilidades:
  - Carregar BRCars metadata
  - Carregar lookup de modelos (gpupo/brazilian-cars)
  - Cache em memória para lookup rápido
"""

from pathlib import Path
import json
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class BRCarsDatabase:
    """Index em memória de BRCars: (marca, modelo, ano, cor) → imagens."""

    def __init__(self, brcars_path: str = "data/datasets/brcars"):
        self.base_path = Path(brcars_path)
        self.metadata = {}
        self.lookup_index = {}
        self._load()

    def _load(self):
        """Carrega metadata de BRCars e constrói lookup index."""
        metadata_file = self.base_path / "metadata.json"
        if not metadata_file.exists():
            logger.warning(f"BRCars metadata não encontrado: {metadata_file}")
            return

        with open(metadata_file, 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)

        # Constrói index: (marca, modelo, cor) → lista de anos/imagens
        for item in self.metadata:
            marca = item.get('marca', '').lower()
            modelo = item.get('modelo', '').lower()
            cor = item.get('cor', '').lower()

            key = (marca, modelo, cor)
            if key not in self.lookup_index:
                self.lookup_index[key] = []
            self.lookup_index[key].append(item)

    def search(self, marca: str, modelo: str, cor: str = None) -> List[Dict]:
        """
        Busca rápida por marca/modelo/cor.
        Se cor não especificada, retorna todos os matches (marca, modelo).
        """
        marca = marca.lower()
        modelo = modelo.lower()

        if cor:
            cor = cor.lower()
            key = (marca, modelo, cor)
            return self.lookup_index.get(key, [])
        else:
            # Retorna todos (marca, modelo, *cores)
            results = []
            for (m, mo, c), items in self.lookup_index.items():
                if m == marca and mo == modelo:
                    results.extend(items)
            return results


class BrazilianCarsReference:
    """Lookup de modelos vendidos no Brasil (gpupo/brazilian-cars)."""

    def __init__(self, ref_path: str = "data/datasets/brazilian-cars-ref/models.json"):
        self.models = {}
        self._load(ref_path)

    def _load(self, ref_path: str):
        """Carrega lista de modelos válidos no Brasil."""
        path = Path(ref_path)
        if not path.exists():
            logger.warning(f"Brazilian cars ref não encontrado: {ref_path}")
            return

        with open(path, 'r', encoding='utf-8') as f:
            self.models = json.load(f)

    def is_valid(self, marca: str, modelo: str, ano: int = None) -> bool:
        """Valida se marca/modelo existem no Brasil."""
        marca = marca.lower()
        modelo = modelo.lower()

        for m in self.models.get(marca, []):
            if m['nome'].lower() == modelo:
                if ano and m.get('anos'):
                    return ano in m['anos']
                return True
        return False

    def get_valid_years(self, marca: str, modelo: str) -> List[int]:
        """Retorna anos válidos de um modelo."""
        marca = marca.lower()
        modelo = modelo.lower()

        for m in self.models.get(marca, []):
            if m['nome'].lower() == modelo:
                return m.get('anos', [])
        return []


# Global cache
_brcars_db = None
_brazilian_cars_ref = None

def get_brcars_database() -> BRCarsDatabase:
    """Singleton de BRCars database."""
    global _brcars_db
    if _brcars_db is None:
        _brcars_db = BRCarsDatabase()
    return _brcars_db

def get_brazilian_cars_reference() -> BrazilianCarsReference:
    """Singleton de Brazilian cars reference."""
    global _brazilian_cars_ref
    if _brazilian_cars_ref is None:
        _brazilian_cars_ref = BrazilianCarsReference()
    return _brazilian_cars_ref
```

---

## PARTE II: MÓDULO 2 - OSINT DATABASE (BRCars Index)

**Arquivo:** `fastapi_backend/osint_database.py` (novo)

```python
"""
OSINT Database: Indexação de BRCars para busca semântica + embedding.
Responsabilidades:
  - Indexação de BRCars (marca, modelo, ano, cor)
  - Integração com OpenCLIP embeddings
  - Reranking de candidatos por score semântico
"""

from datasets_loader import get_brcars_database, get_brazilian_cars_reference
from typing import Dict, List, Tuple
import numpy as np
import json
from pathlib import Path

class OSINTVehicleDatabase:
    """Index principal de OSINT para matching de modelos."""

    def __init__(self):
        self.brcars = get_brcars_database()
        self.brazil_ref = get_brazilian_cars_reference()
        self.embeddings = {}  # {(marca, modelo): embedding_vector}
        self._load_embeddings()

    def _load_embeddings(self):
        """Carrega embeddings CLIP precomputados (gerado offline)."""
        embedding_path = Path("data/models/openclip_embeddings/brcars_embeddings.npy")
        if embedding_path.exists():
            data = np.load(embedding_path, allow_pickle=True).item()
            self.embeddings = data

    def search_by_attributes(self,
                            marca: str,
                            modelo: str,
                            cor: str = None,
                            ano: int = None,
                            limit: int = 10) -> List[Dict]:
        """
        Busca OSINT por atributos estruturados.
        Retorna: [{marca, modelo, ano, cor, score, fonte}, ...]
        """
        candidates = self.brcars.search(marca, modelo, cor)

        # Filtra por ano se especificado
        if ano:
            candidates = [c for c in candidates if c.get('ano') == ano or abs(c.get('ano', ano) - ano) <= 2]

        # Valida contra brazilian cars reference
        candidates = [c for c in candidates if self.brazil_ref.is_valid(c['marca'], c['modelo'])]

        # Score por relevância
        scored = []
        for c in candidates[:limit]:
            score = 1.0
            if c.get('cor', '').lower() == (cor or '').lower():
                score += 0.5
            if c.get('ano') == ano:
                score += 0.3

            scored.append({
                'marca': c['marca'],
                'modelo': c['modelo'],
                'ano': c.get('ano'),
                'cor': c.get('cor'),
                'score': score,
                'fonte': 'brcars'
            })

        return sorted(scored, key=lambda x: x['score'], reverse=True)

    def semantic_rerank(self,
                       candidates: List[Dict],
                       image_embedding: np.ndarray,
                       top_k: int = 3) -> List[Dict]:
        """
        Reranking semântico: compara image_embedding com embeddings de BRCars.
        Retorna: top_k candidatos com semantic_score adicionado.
        """
        for cand in candidates:
            key = (cand['marca'].lower(), cand['modelo'].lower())
            if key in self.embeddings:
                vec = self.embeddings[key]
                # Cosine similarity
                sim = np.dot(image_embedding, vec) / (np.linalg.norm(image_embedding) * np.linalg.norm(vec) + 1e-5)
                cand['semantic_score'] = float(sim)
            else:
                cand['semantic_score'] = 0.0

        # Sort by semantic_score
        candidates = sorted(candidates, key=lambda x: x.get('semantic_score', 0.0), reverse=True)
        return candidates[:top_k]

# Global cache
_osint_db = None

def get_osint_database() -> OSINTVehicleDatabase:
    """Singleton."""
    global _osint_db
    if _osint_db is None:
        _osint_db = OSINTVehicleDatabase()
    return _osint_db
```

---

## PARTE III: MÓDULO 3 - SEMANTIC SEARCH (OpenCLIP)

**Arquivo:** `fastapi_backend/semantic_search.py` (novo)

```python
"""
Semantic Search com OpenCLIP.
Traduz descrição textual em embeddings para busca em BRCars.
Exemplo:
  "Toyota branco 2020-2025" → busca em BRCars com semantic relevance
"""

import torch
import numpy as np
from typing import List, Dict
try:
    from open_clip import create_model_and_transforms, tokenize
except ImportError:
    # Fallback se não instalado
    create_model_and_transforms = None
    tokenize = None

class SemanticVehicleSearch:
    """Search semântico baseado em CLIP."""

    def __init__(self, model_name: str = "ViT-B-32", pretrained: str = "openai"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        if create_model_and_transforms is None:
            raise RuntimeError("open_clip não instalado. pip install open-clip-torch")

        self.model, self.preprocess, _ = create_model_and_transforms(
            model_name=model_name,
            pretrained=pretrained,
            device=self.device
        )
        self.model.eval()
        self.embedding_dim = 512  # ViT-B-32 output dim

    def embed_text(self, text: str) -> np.ndarray:
        """Converte texto em embedding."""
        with torch.no_grad():
            tokens = tokenize([text])
            text_features = self.model.encode_text(tokens.to(self.device))
            text_features /= text_features.norm(dim=-1, keepdim=True)
        return text_features.cpu().numpy()[0]

    def embed_image(self, image: np.ndarray) -> np.ndarray:
        """Converte imagem em embedding."""
        img_tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0).float()
        img_tensor = img_tensor.to(self.device) / 255.0

        with torch.no_grad():
            image_features = self.model.encode_image(img_tensor)
            image_features /= image_features.norm(dim=-1, keepdim=True)
        return image_features.cpu().numpy()[0]

    def search_query(self, query: str, candidates: List[Dict]) -> List[Dict]:
        """
        Dado query textual ("Toyota branco 2020"), score candidatos.
        query: string descritivo
        candidates: [{marca, modelo, ano, cor}, ...]
        Retorna: candidates com semantic_score adicionado
        """
        query_emb = self.embed_text(query)

        for cand in candidates:
            # Constrói texto descritivo do candidato
            desc = f"{cand['marca']} {cand['modelo']} {cand.get('ano', '')} {cand.get('cor', '')}"
            desc_emb = self.embed_text(desc)

            # Cosine similarity
            score = np.dot(query_emb, desc_emb)
            cand['semantic_score'] = float(score)

        return sorted(candidates, key=lambda x: x['semantic_score'], reverse=True)

# Global instance
_semantic_search = None

def get_semantic_search() -> SemanticVehicleSearch:
    """Lazy initialization."""
    global _semantic_search
    if _semantic_search is None:
        _semantic_search = SemanticVehicleSearch()
    return _semantic_search
```

---

## PARTE IV: INTEGRAÇÃO EM MAIN.PY

**Modificação:** `fastapi_backend/main.py`

Adicionar imports:

```python
from datasets_loader import get_brcars_database, get_brazilian_cars_reference
from osint_database import get_osint_database
from semantic_search import get_semantic_search
```

Modificar `build_vehicle_osint_report`:

```python
def build_vehicle_osint_report(
    vehicle_analysis: dict,
    top_candidates: list,
    vehicle_info: dict,
    analysis_id: str,
    source_filename: str,
) -> dict:
    """
    OSINT report com nova camada: BRCars database + semantic search.
    """
    osint_db = get_osint_database()
    semantic_search = get_semantic_search()

    # Busca por atributos estruturados
    detected_class = vehicle_analysis.get('vehicle_detections', [{}])[0].get('class_name')
    detected_color = vehicle_analysis.get('color_estimate')

    # Candidatos iniciais por estrutura
    candidates = osint_db.search_by_attributes(
        marca="",  # Será inferido
        modelo="",
        cor=detected_color,
        limit=20
    )

    # Reranking semântico
    if candidates and vehicle_analysis.get('image_embedding'):
        img_emb = np.array(vehicle_analysis['image_embedding'])
        candidates = osint_db.semantic_rerank(candidates, img_emb, top_k=5)

    # Query textual adicional
    if detected_color and detected_class:
        query = f"{detected_class} {detected_color} Brasil 2020-2025"
        candidates = semantic_search.search_query(query, candidates)

    return {
        'status': 'ok',
        'title': 'Inferencia OSINT de Modelo Veicular (v2 - com BRCars)',
        'analysis_id': analysis_id,
        'source_filename': source_filename,
        'generated_at_utc': datetime.utcnow().isoformat(),
        'method': 'visual_attributes_plus_brcars_semantic_search',
        'top_model_candidates': candidates,
        # ... resto do report anterior
    }
```

---

## PARTE V: FERRAMENTAS DE SETUP

### Tool 1: Preparar BRCars Dataset

**Arquivo:** `tools/prepare_brcars_dataset.py`

```python
#!/usr/bin/env python3
"""
Download/organiza BRCars dataset.
Cria metadata.json e lookup_table.json.
"""

import json
from pathlib import Path

def prepare_brcars():
    """
    1. Download BRCars (se repositório público)
    2. Organiza estrutura
    3. Constrói metadata + lookup
    """
    out_dir = Path("data/datasets/brcars")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Exemplo: ler imagens e metadados
    # (implementação depende da fonte exata do BRCars)

    metadata = []
    for item in get_brcars_items():  # Placeholder
        metadata.append({
            'marca': item['make'],
            'modelo': item['model'],
            'ano': item['year'],
            'cor': item['color'],
            'imagem': item['image_path'],
            'tipo': item['body_type']
        })

    # Salva
    with open(out_dir / 'metadata.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"✓ Preparado BRCars: {len(metadata)} registros")

if __name__ == '__main__':
    prepare_brcars()
```

### Tool 2: Fine-tune YOLOv8

**Arquivo:** `tools/finetune_yolo.py`

```python
#!/usr/bin/env python3
"""
Fine-tune YOLOv8 com UFPR-VeSV + BRCars.
"""

from ultralytics import YOLO

def finetune_yolo():
    """Treina YOLOv8 com datasets brasileiros."""

    model = YOLO('yolov8n.pt')  # Nano model

    results = model.train(
        data='data/datasets/ufpr-vesv/dataset.yaml',  # COCO format
        epochs=50,
        imgsz=640,
        batch=16,
        device=0,  # GPU 0
        patience=10,
        save=True,
        project='runs/detect',
        name='yolo_brcars_v1'
    )

    # Salva modelo final
    model.save('data/models/yolo_brcars_v1.pt')
    print("✓ YOLOv8 fine-tuned e salvo")

if __name__ == '__main__':
    finetune_yolo()
```

### Tool 3: Build OpenCLIP Embeddings

**Arquivo:** `tools/build_openclip_embeddings.py`

```python
#!/usr/bin/env python3
"""
Precomputa embeddings CLIP para BRCars (offline).
Executar uma vez, depois usar em runtime.
"""

import numpy as np
from pathlib import Path
import json

try:
    from semantic_search import get_semantic_search
except ImportError:
    import sys
    sys.path.insert(0, 'fastapi_backend')
    from semantic_search import get_semantic_search

def build_embeddings():
    """Gera e salva embeddings de todos modelos em BRCars."""

    search = get_semantic_search()

    # Carrega metadata de BRCars
    metadata_file = Path('data/datasets/brcars/metadata.json')
    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    # Dedup (marca, modelo)
    unique_models = {}
    for item in metadata:
        key = (item['marca'], item['modelo'])
        unique_models[key] = item

    embeddings = {}
    print(f"Gerando {len(unique_models)} embeddings...")

    for i, (key, item) in enumerate(unique_models.items()):
        marca, modelo = key
        desc = f"{marca} {modelo}"

        emb = search.embed_text(desc)
        embeddings[key] = emb.tolist()

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(unique_models)}")

    # Salva
    out_dir = Path('data/models/openclip_embeddings')
    out_dir.mkdir(parents=True, exist_ok=True)

    np.save(out_dir / 'brcars_embeddings.npy', embeddings)
    print(f"✓ Embeddings salvos: {out_dir / 'brcars_embeddings.npy'}")

if __name__ == '__main__':
    build_embeddings()
```

---

## PARTE VI: CHECKLIST DE EXECUÇÃO (Semana 1)

```
Dia 1-2: Setup de Datasets
☐ Pesquisar + download BRCars Dataset
☐ Download UFPR-VeSV (estruturar em YOLO format)
☐ Clone gpupo/brazilian-cars (models.json)

Dia 2-3: Código Base
☐ Criar datasets_loader.py
☐ Criar osint_database.py
☐ Criar semantic_search.py (com fallback se OpenCLIP não disponível)
☐ Atualizar requirements.txt com open-clip-torch

Dia 3-4: Tools de Preparação
☐ Criar prepare_brcars_dataset.py + executar
☐ Criar finetune_yolo.py (executar)
☐ Criar build_openclip_embeddings.py + executar

Dia 4-5: Integração
☐ Integrar módulos em main.py
☐ Atualizar build_vehicle_osint_report
☐ Teste E2E: POST /process + verificar OSINT com BRCars

Dia 5: Validação + Documentação
☐ Benchmark desempenho novo vs anterior
☐ Documentar em README
☐ Commit: "Integra datasets brasileiros + OpenCLIP para OSINT v2"
```

---

## PARTE VII: INSTALLATION COMMANDS

```bash
# 1. Install dependencies
pip install open-clip-torch pillow pytorch-gpu  # ajustar conforme seu setup

# 2. Prepare directories
mkdir -p data/datasets/brcars data/datasets/ufpr-vesv data/datasets/brazilian-cars-ref
mkdir -p data/models/openclip_embeddings

# 3. Download datasets (manual para BRCars, automated para UFPR-VeSV)
# BRCars: Buscar repositório ou solicitar acesso
# UFPR-VeSV: https://[link-oficial]/download
# brazilian-cars: git clone https://github.com/gpupo/brazilian-cars.git

# 4. Run setup scripts
python tools/prepare_brcars_dataset.py
python tools/finetune_yolo.py
python tools/build_openclip_embeddings.py

# 5. Restart FastAPI para carregar novos modelos
# (verifica se dados estão em place)
```

---

## PARTE VIII: ROLLBACK / CONTINGENCY

Se algo não funcionar:

1. **OpenCLIP não instala?** → Usar fallback de busca estruturada (sem semantic score)
2. **BRCars dataset não encontrado?** → Usar apenas UFPR-VeSV + lookup brasileiro-cars
3. **YOLO fine-tuning falha?** → Usar YOLOv8 pré-treinado (sem fine-tuning)

Código já inclui fallbacks para evitar falha completa.

---

**Conclusão:** Guia pronto para execução. Semana 1 é viável. Comece pelo Dia 1 checklist.
