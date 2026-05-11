"""
Carregador de datasets locais para enriquecimento OSINT.

Escopo atual:
- Referencia de modelos nacionais convertida de gpupo/brazilian-cars.
- Sumario do dataset BRCars (quando disponível localmente).

Design:
- Leitura lazy + cache em memória para não impactar latência de startup.
- Fail-safe: ausência de arquivos não quebra o pipeline.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List
import json
import unicodedata


BASE_DIR = Path(__file__).resolve().parents[1]
BRAZILIAN_CARS_JSON = BASE_DIR / "data" / "datasets" / "brazilian-cars-ref" / "models.json"
BRCARS_SUMMARY_JSON = BASE_DIR / "data" / "datasets" / "brcars" / "brcars_summary.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _norm_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


@lru_cache(maxsize=1)
def load_brazilian_cars_reference() -> Dict[str, Any]:
    payload = _read_json(BRAZILIAN_CARS_JSON, default={})
    if not isinstance(payload, dict):
        payload = {}

    models_map = payload.get("models", {})
    if not isinstance(models_map, dict):
        models_map = {}

    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for make_name, rows in models_map.items():
        make_key = _norm_text(make_name)
        if not make_key or not isinstance(rows, list):
            continue

        normalized_rows: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_name = str(row.get("nome", "") or "").strip()
            if not model_name:
                continue
            normalized_rows.append(
                {
                    "nome": model_name,
                    "nome_norm": _norm_text(model_name),
                    "anos": row.get("anos", []) if isinstance(row.get("anos"), list) else [],
                    "combustiveis": row.get("combustiveis", []) if isinstance(row.get("combustiveis"), list) else [],
                    "variantes": row.get("variantes", []) if isinstance(row.get("variantes"), list) else [],
                }
            )

        if normalized_rows:
            normalized[make_key] = normalized_rows

    return {
        "source": payload.get("source", ""),
        "generated_at": payload.get("generated_at", ""),
        "total_makes": int(payload.get("total_makes", 0) or 0),
        "total_models": int(payload.get("total_models", 0) or 0),
        "models": normalized,
    }


@lru_cache(maxsize=1)
def load_brcars_summary() -> Dict[str, Any]:
    payload = _read_json(BRCARS_SUMMARY_JSON, default={})
    return payload if isinstance(payload, dict) else {}


def match_brazilian_model(make: Any, model_candidate: Any) -> Dict[str, Any]:
    """
    Faz matching aproximado make/model contra referência nacional.
    Retorna metadados de match para scoring e trilha auditável.
    """
    ref = load_brazilian_cars_reference()
    model_map = ref.get("models", {}) if isinstance(ref, dict) else {}

    make_norm = _norm_text(make)
    model_norm = _norm_text(model_candidate)
    if not make_norm or not model_norm or not isinstance(model_map, dict):
        return {
            "matched": False,
            "make_norm": make_norm,
            "model_norm": model_norm,
            "match_type": "none",
        }

    rows = model_map.get(make_norm, [])
    if not isinstance(rows, list) or not rows:
        return {
            "matched": False,
            "make_norm": make_norm,
            "model_norm": model_norm,
            "match_type": "make_not_found",
        }

    exact = [row for row in rows if model_norm == str(row.get("nome_norm", ""))]
    if exact:
        row = exact[0]
        return {
            "matched": True,
            "match_type": "exact",
            "make_norm": make_norm,
            "model_norm": model_norm,
            "model_name": row.get("nome", ""),
            "anos": row.get("anos", []),
        }

    partial = []
    for row in rows:
        name_norm = str(row.get("nome_norm", ""))
        if not name_norm:
            continue
        if model_norm in name_norm or name_norm in model_norm:
            partial.append(row)

    if partial:
        row = partial[0]
        return {
            "matched": True,
            "match_type": "partial",
            "make_norm": make_norm,
            "model_norm": model_norm,
            "model_name": row.get("nome", ""),
            "anos": row.get("anos", []),
        }

    return {
        "matched": False,
        "match_type": "model_not_found",
        "make_norm": make_norm,
        "model_norm": model_norm,
    }


def datasets_status() -> Dict[str, Any]:
    ref = load_brazilian_cars_reference()
    brcars = load_brcars_summary()

    models = ref.get("models", {}) if isinstance(ref, dict) else {}
    has_ref = bool(models)
    has_brcars = bool(brcars)

    return {
        "brazilian_cars_ref": {
            "available": has_ref,
            "path": str(BRAZILIAN_CARS_JSON),
            "total_makes": int(ref.get("total_makes", 0) or 0) if has_ref else 0,
            "total_models": int(ref.get("total_models", 0) or 0) if has_ref else 0,
        },
        "brcars_summary": {
            "available": has_brcars,
            "path": str(BRCARS_SUMMARY_JSON),
            "keys": sorted(list(brcars.keys())) if has_brcars else [],
        },
    }
