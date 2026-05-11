"""
Camada complementar de OSINT veicular (fontes abertas) para inferencia probabilistica.

Objetivo:
- Agregar evidencias visuais (detecoes, CLIP, farois/lanternas, templates)
- Cruzar com fontes abertas whitelisted (sem scraping agressivo)
- Produzir top-candidatos com trilha auditavel para uso complementar pericial

Importante:
- Nao substitui identificacao por placa.
- Resultado deve ser tratado como inferencia probabilistica.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
import os

try:
    from fastapi_backend.datasets_loader import datasets_status, match_brazilian_model
    _datasets_loader_ok = True
except Exception:
    _datasets_loader_ok = False

    def datasets_status() -> Dict[str, Any]:
        return {
            "brazilian_cars_ref": {"available": False},
            "brcars_summary": {"available": False},
        }

    def match_brazilian_model(make: Any, model_candidate: Any) -> Dict[str, Any]:
        return {
            "matched": False,
            "match_type": "datasets_loader_unavailable",
            "make_norm": "",
            "model_norm": "",
        }

try:
    from fastapi_backend.osint_database import get_osint_database
    _osint_db_ok = True
except Exception:
    _osint_db_ok = False

    def get_osint_database():  # type: ignore
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_plate(value: Any) -> str:
    txt = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return txt.strip()


def _extract_partial_plate_hint(top_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(top_candidates, list):
        return {"text": "", "is_partial": False, "length": 0}
    for row in top_candidates:
        if not isinstance(row, dict):
            continue
        text = _normalize_plate(row.get("text"))
        if not text:
            continue
        return {
            "text": text,
            "is_partial": len(text) < 7,
            "length": len(text),
            "engine": _normalize_text(row.get("engine")),
            "score": _to_float(row.get("score", 0.0)),
        }
    return {"text": "", "is_partial": False, "length": 0}


def _vehicle_class_hint(vehicle_detections: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(vehicle_detections, list) or not vehicle_detections:
        return {"class_name": "indefinido", "confidence": 0.0}

    best = max(
        [row for row in vehicle_detections if isinstance(row, dict)],
        key=lambda r: _to_float(r.get("confidence", 0.0)),
        default={},
    )
    return {
        "class_name": _normalize_text(best.get("class_name")) or "indefinido",
        "confidence": _to_float(best.get("confidence", 0.0)),
    }


def _visual_features_summary(vehicle_analysis: Dict[str, Any]) -> Dict[str, Any]:
    va = vehicle_analysis if isinstance(vehicle_analysis, dict) else {}
    light_regions = va.get("light_regions") if isinstance(va.get("light_regions"), dict) else {}
    headlight_templates = va.get("headlight_templates") if isinstance(va.get("headlight_templates"), list) else []

    top_template = headlight_templates[0] if headlight_templates and isinstance(headlight_templates[0], dict) else {}

    return {
        "has_light_regions": bool(light_regions),
        "light_regions_reliable": bool(light_regions.get("reliable", False)) if light_regions else False,
        "top_headlight_template": {
            "template": _normalize_text(top_template.get("template")),
            "make": _normalize_text(top_template.get("make")),
            "score": _to_float(top_template.get("score", 0.0)),
        },
    }


def _clip_candidates(vehicle_analysis: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    va = vehicle_analysis if isinstance(vehicle_analysis, dict) else {}
    clip_rows = va.get("make_model_clip") if isinstance(va.get("make_model_clip"), list) else []

    out: List[Dict[str, Any]] = []
    for row in clip_rows:
        if not isinstance(row, dict):
            continue
        label = _normalize_text(row.get("label"))
        if not label:
            continue
        out.append({
            "label": label,
            "clip_score": _to_float(row.get("score", 0.0)),
        })
        if len(out) >= limit:
            break
    return out


def _whitelisted_sources() -> List[Dict[str, str]]:
    return [
        {
            "name": "FIPE Public API",
            "type": "public_api",
            "url": "https://fipe.parallelum.com.br/api/v2",
            "purpose": "normalizacao de nomenclatura e contexto de mercado",
        },
        {
            "name": "Catalogos publicos de montadoras",
            "type": "public_web",
            "url": "https://www.gov.br",
            "purpose": "referencia de design e geracoes comerciais",
        },
        {
            "name": "Base visual aberta interna",
            "type": "local_dataset",
            "url": "local://vehicle_analyzer_prompts",
            "purpose": "inferencias zero-shot por atributos visuais",
        },
        {
            "name": "Referencia de modelos brasileiros",
            "type": "local_dataset",
            "url": "local://data/datasets/brazilian-cars-ref/models.json",
            "purpose": "validacao de plausibilidade de make/model no mercado nacional",
        },
    ]


def _osint_db_candidates(
    make_hint: str,
    model_hint: str,
    color_hint: str,
    year_hint: Any,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Busca candidatos via OSINTVehicleDatabase (estruturada, nacional)."""
    if not _osint_db_ok:
        return []
    db = get_osint_database()
    if db is None:
        return []
    try:
        year = int(year_hint) if year_hint else None
    except (TypeError, ValueError):
        year = None
    try:
        return db.search_by_attributes(
            make=make_hint or "",
            model=model_hint or "",
            color=color_hint or "",
            year=year,
            limit=limit,
        )
    except Exception:
        return []


def _build_candidate_rows(
    vehicle_analysis: Dict[str, Any],
    top_candidates: List[Dict[str, Any]],
    vehicle_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    partial_plate = _extract_partial_plate_hint(top_candidates)
    class_hint = _vehicle_class_hint(vehicle_analysis.get("vehicle_detections", []))
    visual = _visual_features_summary(vehicle_analysis)
    clip = _clip_candidates(vehicle_analysis, limit=5)

    # Extrai dicas de cor/ano de vehicle_analysis
    color_hint = _normalize_text(vehicle_analysis.get("color_estimate", ""))
    year_hint = vehicle_analysis.get("year_estimate") or vehicle_info.get("ano")

    rows: List[Dict[str, Any]] = []
    for row in clip:
        label = row.get("label", "")
        make = label.split(" ")[0] if label else ""

        dataset_match = match_brazilian_model(make=make, model_candidate=label)

        # Score composto conservador: CLIP dominante + pequenos ajustes por contexto.
        score = (row.get("clip_score", 0.0) * 0.80)
        if class_hint.get("class_name") in ("car", "truck", "bus", "motorcycle"):
            score += 0.08
        if visual.get("has_light_regions"):
            score += 0.05
        if partial_plate.get("text"):
            score += 0.03

        if bool(dataset_match.get("matched", False)):
            if str(dataset_match.get("match_type", "")) == "exact":
                score += 0.12
            else:
                score += 0.07

        # Busca estruturada na OSINTVehicleDatabase para enriquecer
        osint_hits = _osint_db_candidates(
            make_hint=make,
            model_hint=label,
            color_hint=color_hint,
            year_hint=year_hint,
            limit=3,
        )
        osint_best = osint_hits[0] if osint_hits else {}
        if osint_best:
            # Valida que o CLIP candidato tem respaldo estrutural nacional
            osint_score_boost = min(0.15, osint_best.get("score", 0.0) * 0.1)
            score += osint_score_boost

        rows.append({
            "make": make,
            "model_candidate": label,
            "probability_score": round(min(1.0, max(0.0, score)), 4),
            "evidence": {
                "clip_score": round(row.get("clip_score", 0.0), 4),
                "vehicle_class_hint": class_hint,
                "partial_plate_hint": partial_plate,
                "visual_features": visual,
                "brazilian_model_match": dataset_match,
                "osint_db_best_match": {
                    "make": osint_best.get("make", ""),
                    "model": osint_best.get("model", ""),
                    "year": osint_best.get("year"),
                    "source": osint_best.get("source", ""),
                } if osint_best else None,
            },
            "notes": [
                "Inferencia probabilistica com base em atributos visuais e fonte aberta.",
                "Nao representa identificacao conclusiva do veiculo.",
            ],
        })

    # Fallback se CLIP nao retornou candidato.
    if not rows:
        fallback_make = _normalize_text(vehicle_info.get("fabricante"))
        fallback_model = _normalize_text(vehicle_info.get("modelo"))
        if fallback_make or fallback_model:
            fallback_dataset_match = match_brazilian_model(
                make=fallback_make,
                model_candidate=fallback_model or fallback_make,
            )
            fallback_score = 0.35
            if bool(fallback_dataset_match.get("matched", False)):
                fallback_score += 0.12 if str(fallback_dataset_match.get("match_type", "")) == "exact" else 0.07
            rows.append({
                "make": fallback_make,
                "model_candidate": fallback_model or fallback_make,
                "probability_score": round(min(1.0, max(0.0, fallback_score)), 4),
                "evidence": {
                    "vehicle_info_seed": {
                        "fabricante": fallback_make,
                        "modelo": fallback_model,
                    },
                    "partial_plate_hint": partial_plate,
                    "vehicle_class_hint": class_hint,
                    "brazilian_model_match": fallback_dataset_match,
                },
                "notes": ["Candidato derivado de metadados complementares do fluxo."],
            })

    rows.sort(key=lambda r: _to_float(r.get("probability_score", 0.0)), reverse=True)

    ranked = []
    for idx, row in enumerate(rows[:3], start=1):
        candidate = dict(row)
        candidate["rank"] = idx
        ranked.append(candidate)
    return ranked


def build_vehicle_osint_report(
    vehicle_analysis: Dict[str, Any] | None,
    top_candidates: List[Dict[str, Any]] | None,
    vehicle_info: Dict[str, Any] | None,
    analysis_id: str = "",
    source_filename: str = "",
) -> Dict[str, Any]:
    """
    Gera relatorio OSINT complementar com trilha auditavel.
    """
    va = vehicle_analysis or {}
    tc = top_candidates or []
    vi = vehicle_info or {}

    model_candidates = _build_candidate_rows(va, tc, vi)
    partial_plate = _extract_partial_plate_hint(tc)
    ds_status = datasets_status()

    # Status do OSINTVehicleDatabase
    osint_db_status: Dict[str, Any] = {"available": False}
    if _osint_db_ok:
        db = get_osint_database()
        if db is not None:
            try:
                osint_db_status = {"available": True, **db.status()}
            except Exception:
                osint_db_status = {"available": True}

    return {
        "status": "ok",
        "title": "Inferencia OSINT de Modelo Veicular (Complementar)",
        "analysis_id": _normalize_text(analysis_id),
        "source_filename": _normalize_text(source_filename),
        "generated_at_utc": _utc_now(),
        "method": "visual_attributes_plus_open_sources_v2",
        "compliance": {
            "probabilistic_only": True,
            "not_conclusive_identification": True,
            "requires_human_review": True,
            "lgpd_data_minimization": True,
        },
        "source_whitelist": _whitelisted_sources(),
        "query_trace": {
            "partial_plate_hint": partial_plate,
            "vehicle_class_hint": _vehicle_class_hint(va.get("vehicle_detections", [])),
            "clip_candidates_count": len(_clip_candidates(va, limit=10)),
            "datasets_status": ds_status,
            "datasets_loader_available": _datasets_loader_ok,
            "osint_db_status": osint_db_status,
        },
        "top_model_candidates": model_candidates,
        "summary": {
            "top_candidate": model_candidates[0].get("model_candidate", "") if model_candidates else "",
            "top_probability_score": model_candidates[0].get("probability_score", 0.0) if model_candidates else 0.0,
            "candidate_count": len(model_candidates),
            "used_brazilian_reference": bool(ds_status.get("brazilian_cars_ref", {}).get("available", False)),
            "used_osint_database": osint_db_status.get("available", False),
        },
        "legal_disclaimer": (
            "Resultado complementar OSINT com carater probabilistico. "
            "Nao substitui identificacao formal por placa completa, laudo pericial humano "
            "ou confirmacao em bases oficiais competentes."
        ),
    }
