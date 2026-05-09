"""
Spatial Brief Report - Grom OCR

Gera resumo técnico-pericial curto para análise geoespacial
com base no contexto espacial extraído da imagem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _build_findings(spatial_context: Dict[str, Any]) -> List[str]:
    findings: List[str] = []
    status = _safe_str(spatial_context.get("status"))
    gps_present = bool(spatial_context.get("gps_present", False))
    gps_extracted = bool(spatial_context.get("gps_extracted", False))

    if not gps_extracted:
        if gps_present or status == "gps_invalid":
            findings.append("Metadados GPS EXIF foram encontrados, mas os valores estao corrompidos, nulos ou invalidos.")
        else:
            findings.append("Nao foi identificado metadado GPS EXIF na evidencia analisada.")
        findings.append("Sem coordenadas validas, nao foi possivel correlacionar localizacao por reverse geocoding.")
        return findings

    lat = spatial_context.get("latitude")
    lon = spatial_context.get("longitude")
    alt = spatial_context.get("altitude_m")
    findings.append(f"Coordenadas EXIF identificadas: latitude={lat}, longitude={lon}.")
    if alt is not None:
        findings.append(f"Altitude registrada no EXIF: {alt} metros.")

    reverse = spatial_context.get("reverse_geocode", {}) if isinstance(spatial_context.get("reverse_geocode"), dict) else {}
    provider = _safe_str(reverse.get("provider"))
    display_name = _safe_str(reverse.get("display_name"))
    if provider:
        findings.append(f"Reverse geocoding processado via provedor: {provider}.")
    if display_name:
        findings.append(f"Endereco aproximado inferido: {display_name}.")

    if status == "gps_only":
        findings.append("Apenas coordenadas foram validadas; nao houve resolucao completa de endereco.")

    return findings


def build_spatial_brief_report(
    spatial_context: Dict[str, Any],
    filename: str = "",
    analysis_id: str = "",
) -> Dict[str, Any]:
    """Gera relatorio breve estruturado para uso investigativo."""
    spatial_context = spatial_context or {}
    status = _safe_str(spatial_context.get("status")) or "unknown"
    gps_extracted = bool(spatial_context.get("gps_extracted", False))

    if gps_extracted:
        evidence_level = "MEDIA"
        conclusion = "Ha evidencias geoespaciais extraidas da imagem (GPS EXIF)."
        if status == "spatial_context_ready":
            evidence_level = "ALTA"
            conclusion = "Ha evidencias geoespaciais consistentes com georreferenciamento e endereco inferido."
    else:
        evidence_level = "BAIXA"
        if spatial_context.get("gps_present") or status == "gps_invalid":
            conclusion = "Metadados GPS foram detectados, porem estao invalidos/corrompidos e nao permitem inferencia de local."
        else:
            conclusion = "Nao foram encontrados metadados geoespaciais suficientes para inferencia de local."

    findings = _build_findings(spatial_context)

    methodology = [
        "1) Coleta da evidencia digital e preservacao do arquivo submetido.",
        "2) Leitura de metadados EXIF com foco em tags GPS.",
        "3) Conversao de coordenadas DMS para decimal quando aplicavel.",
        "4) Reverse geocoding por provedores configurados (Mapbox/HERE/Nominatim).",
        "5) Consolidacao pericial dos achados geoespaciais e limitacoes.",
    ]

    legal_notes = [
        "A inferencia espacial depende da integridade dos metadados EXIF.",
        "Metadados podem ser ausentes ou alterados por aplicativos de edicao/compartilhamento.",
        "Recomenda-se correlacao com outras fontes de prova (CFTV, telecom, testemunhas).",
    ]

    return {
        "title": "Relatorio Breve de Analise Geoespacial",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_id": _safe_str(analysis_id),
        "filename": _safe_str(filename),
        "status": status,
        "evidence_level": evidence_level,
        "conclusion": conclusion,
        "findings": findings,
        "methodology": methodology,
        "legal_notes": legal_notes,
        "spatial_context": spatial_context,
    }
