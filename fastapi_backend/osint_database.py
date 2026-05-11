"""
OSINT Database: índice estruturado de veículos brasileiros para lookup rápido.

Integra:
- BrazilianCarsReference (gpupo/brazilian-cars) — disponível agora
- BRCarsDatabase (BRCars dataset) — ativado quando ZIP autorizado chegar

Design:
- Lazy loading com singleton thread-safe
- Fail-safe: ausência de dados não quebra o pipeline
- Scoring estruturado + slot para reranking semântico (OpenCLIP)
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# OSINTVehicleDatabase
# ---------------------------------------------------------------------------

class OSINTVehicleDatabase:
    """
    Index principal de OSINT veicular.

    Fontes:
    1. BrazilianCarsReference (gpupo/brazilian-cars) — 89 marcas / 944 modelos
    2. BRCarsDatabase (BRCars dataset) — ativado via finalize_brcars_integration.py
    3. Embeddings OpenCLIP precomputados (optional, gerado offline)
    """

    def __init__(self) -> None:
        self._brazil_ref: Dict[str, Any] = {}
        self._brcars_metadata: List[Dict[str, Any]] = []
        self._brcars_index: Dict[tuple, List[Dict]] = {}
        self._embeddings: Dict[tuple, Any] = {}

        self._load_brazil_ref()
        self._load_brcars()
        self._load_embeddings()

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_brazil_ref(self) -> None:
        """Carrega referência nacional (gpupo/brazilian-cars)."""
        try:
            from fastapi_backend.datasets_loader import load_brazilian_cars_reference
            self._brazil_ref = load_brazilian_cars_reference()
            logger.info(
                "OSINTVehicleDatabase: referência nacional carregada — "
                "%d marcas / %d modelos",
                self._brazil_ref.get("total_makes", 0),
                self._brazil_ref.get("total_models", 0),
            )
        except Exception as exc:
            logger.warning("OSINTVehicleDatabase: falha ao carregar referência nacional: %s", exc)
            self._brazil_ref = {}

    def _load_brcars(self) -> None:
        """Carrega metadata BRCars quando disponível."""
        metadata_path = BASE_DIR / "data" / "datasets" / "brcars" / "metadata.json"
        if not metadata_path.exists():
            logger.debug("OSINTVehicleDatabase: BRCars metadata não encontrado (normal até ZIP chegar).")
            return
        try:
            import json
            with open(metadata_path, encoding="utf-8") as fh:
                self._brcars_metadata = json.load(fh)

            # Constrói índice (marca_norm, modelo_norm, cor_norm) → [items]
            for item in self._brcars_metadata:
                key = (
                    _norm(item.get("marca")),
                    _norm(item.get("modelo")),
                    _norm(item.get("cor", "")),
                )
                self._brcars_index.setdefault(key, []).append(item)

            logger.info(
                "OSINTVehicleDatabase: BRCars carregado — %d registros, %d chaves de índice.",
                len(self._brcars_metadata),
                len(self._brcars_index),
            )
        except Exception as exc:
            logger.warning("OSINTVehicleDatabase: falha ao carregar BRCars: %s", exc)

    def _load_embeddings(self) -> None:
        """Carrega embeddings OpenCLIP precomputados (opcional)."""
        emb_path = BASE_DIR / "data" / "models" / "openclip_embeddings" / "brcars_embeddings.npy"
        if not emb_path.exists():
            return
        try:
            data = np.load(str(emb_path), allow_pickle=True).item()
            self._embeddings = data
            logger.info(
                "OSINTVehicleDatabase: %d embeddings OpenCLIP carregados.", len(self._embeddings)
            )
        except Exception as exc:
            logger.warning("OSINTVehicleDatabase: falha ao carregar embeddings: %s", exc)

    # ------------------------------------------------------------------
    # Consulta estruturada
    # ------------------------------------------------------------------

    def is_valid_brazilian_model(self, make: str, model: str) -> bool:
        """Valida se marca/modelo consta na referência nacional."""
        models_map = self._brazil_ref.get("models", {})
        make_key = _norm(make)
        rows = models_map.get(make_key, [])
        model_key = _norm(model)
        return any(r.get("nome_norm") == model_key for r in rows)

    def get_models_for_make(self, make: str) -> List[Dict[str, Any]]:
        """Retorna modelos conhecidos de uma marca na referência nacional."""
        make_key = _norm(make)
        return self._brazil_ref.get("models", {}).get(make_key, [])

    def search_by_attributes(
        self,
        make: str = "",
        model: str = "",
        color: str = "",
        year: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Busca candidatos por atributos estruturados.

        Prioridade de fontes:
        1. BRCars (dataset real) — se disponível
        2. BrazilianCarsReference (fallback) — lista de modelos nacionais

        Retorna: [{make, model, year, color, score, source}, ...]
        """
        results: List[Dict[str, Any]] = []

        # --- Fonte 1: BRCars index ---
        if self._brcars_index:
            results = self._search_brcars(make, model, color, year, limit * 2)

        # --- Fonte 2: BrazilianCarsReference (fallback ou complemento) ---
        if len(results) < limit:
            results += self._search_brazil_ref(make, model, year, limit * 2)

        # Dedup por (make, model, year, color)
        seen: set = set()
        deduped: List[Dict[str, Any]] = []
        for r in results:
            key = (
                _norm(r.get("make", "")),
                _norm(r.get("model", "")),
                r.get("year"),
                _norm(r.get("color", "")),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        return sorted(deduped, key=lambda x: x.get("score", 0.0), reverse=True)[:limit]

    def _search_brcars(
        self,
        make: str,
        model: str,
        color: str,
        year: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        make_n = _norm(make)
        model_n = _norm(model)
        color_n = _norm(color)

        results: List[Dict[str, Any]] = []
        for (mk, mo, co), items in self._brcars_index.items():
            # Filtragem rápida
            if make_n and make_n not in mk and mk not in make_n:
                continue
            if model_n and model_n not in mo and mo not in model_n:
                continue

            for item in items:
                score = 1.0
                # Boost por cor exata
                if color_n and co == color_n:
                    score += 0.5
                elif color_n and color_n in co:
                    score += 0.2
                # Boost por ano
                item_year = item.get("ano")
                if year and item_year:
                    diff = abs(item_year - year)
                    if diff == 0:
                        score += 0.4
                    elif diff <= 2:
                        score += 0.2
                # Boost por match exato de modelo
                if model_n and mo == model_n:
                    score += 0.3

                results.append(
                    {
                        "make": item.get("marca", ""),
                        "model": item.get("modelo", ""),
                        "year": item_year,
                        "color": item.get("cor", ""),
                        "body_type": item.get("tipo", ""),
                        "score": score,
                        "source": "brcars_dataset",
                    }
                )
                if len(results) >= limit:
                    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

    def _search_brazil_ref(
        self,
        make: str,
        model: str,
        year: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Busca na referência nacional (sem imagens, sem cor)."""
        results: List[Dict[str, Any]] = []
        models_map = self._brazil_ref.get("models", {})
        make_n = _norm(make)
        model_n = _norm(model)

        # Determina marcas candidatas
        if make_n:
            candidate_makes = [
                mk for mk in models_map
                if make_n in mk or mk in make_n
            ]
        else:
            candidate_makes = list(models_map.keys())

        for mk in candidate_makes:
            rows = models_map[mk]
            for row in rows:
                nome_n = row.get("nome_norm", "")

                # Filtra por modelo se especificado
                if model_n and model_n not in nome_n and nome_n not in model_n:
                    continue

                score = 0.8  # Base ligeiramente menor que BRCars (sem imagem)
                if make_n and mk == make_n:
                    score += 0.2
                if model_n and nome_n == model_n:
                    score += 0.3

                anos = row.get("anos", [])
                if year and anos:
                    if year in anos:
                        score += 0.3
                    elif any(abs(a - year) <= 2 for a in anos):
                        score += 0.1

                # Expande por anos disponíveis
                years_to_emit = [year] if year else (anos[:3] if anos else [None])
                for yr in years_to_emit:
                    results.append(
                        {
                            "make": mk,
                            "model": row.get("nome", ""),
                            "year": yr,
                            "color": "",
                            "body_type": "",
                            "score": score,
                            "source": "brazilian_cars_ref",
                            "combustiveis": row.get("combustiveis", []),
                            "variantes": row.get("variantes", []),
                        }
                    )
                    if len(results) >= limit:
                        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

        return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Reranking semântico (OpenCLIP)
    # ------------------------------------------------------------------

    def semantic_rerank(
        self,
        candidates: List[Dict[str, Any]],
        image_embedding: Any,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Reranking semântico: cosine similarity entre image_embedding e
        embeddings precomputados de BRCars.

        Se embeddings não disponíveis, devolve candidatos sem alteração.
        """
        if not self._embeddings or image_embedding is None:
            return candidates[:top_k]

        try:
            img_vec = np.array(image_embedding, dtype=np.float32)
            img_norm = img_vec / (np.linalg.norm(img_vec) + 1e-8)

            for cand in candidates:
                key = (_norm(cand.get("make", "")), _norm(cand.get("model", "")))
                if key in self._embeddings:
                    vec = np.array(self._embeddings[key], dtype=np.float32)
                    vec_norm = vec / (np.linalg.norm(vec) + 1e-8)
                    sim = float(np.dot(img_norm, vec_norm))
                    cand["semantic_score"] = sim
                    # Eleva score combinado
                    cand["score"] = cand.get("score", 0.8) + sim * 0.5
                else:
                    cand.setdefault("semantic_score", 0.0)

            return sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)[:top_k]
        except Exception as exc:
            logger.warning("OSINTVehicleDatabase.semantic_rerank falhou: %s", exc)
            return candidates[:top_k]

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Retorna estado atual das fontes carregadas."""
        return {
            "brazil_ref": {
                "available": bool(self._brazil_ref.get("models")),
                "total_makes": self._brazil_ref.get("total_makes", 0),
                "total_models": self._brazil_ref.get("total_models", 0),
                "source": self._brazil_ref.get("source", ""),
            },
            "brcars_dataset": {
                "available": bool(self._brcars_metadata),
                "total_records": len(self._brcars_metadata),
                "index_keys": len(self._brcars_index),
            },
            "openclip_embeddings": {
                "available": bool(self._embeddings),
                "total_vectors": len(self._embeddings),
            },
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_osint_db: Optional[OSINTVehicleDatabase] = None


def get_osint_database() -> OSINTVehicleDatabase:
    """Lazy singleton thread-safe (GIL do Python protege em uso comum)."""
    global _osint_db
    if _osint_db is None:
        _osint_db = OSINTVehicleDatabase()
    return _osint_db
