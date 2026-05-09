"""
Scene Brief Report - Grom OCR

Gera uma análise preliminar da imagem para uso pericial.
Suporta:
- descrição manual da cena
- síntese automática a partir de image_quality, vehicle_analysis, spatial_context
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _derive_scene_type(scene_context: Dict[str, Any], vehicle_analysis: Dict[str, Any]) -> str:
    manual = _safe_str(scene_context.get("scene_type"))
    if manual:
        return manual

    vehicle_detections = vehicle_analysis.get("vehicle_detections", []) if isinstance(vehicle_analysis, dict) else []
    if len(vehicle_detections) >= 3:
        return "patio_operacional_multiplo"
    if len(vehicle_detections) >= 1:
        return "area_operacional_com_veiculo"
    return "cena_nao_classificada"


def _derive_capture_condition(scene_context: Dict[str, Any], image_quality: Dict[str, Any]) -> str:
    manual = _safe_str(scene_context.get("capture_condition"))
    if manual:
        return manual

    quality_status = _safe_str(image_quality.get("quality_status"))
    brightness_level = _safe_str(image_quality.get("brightness_level"))
    blur_level = _safe_str(image_quality.get("blur_level"))

    parts = []
    if quality_status:
        parts.append(f"qualidade={quality_status}")
    if brightness_level:
        parts.append(f"brilho={brightness_level}")
    if blur_level:
        parts.append(f"nitidez={blur_level}")

    return "; ".join(parts) if parts else "indisponivel"


def _derive_operational_context(
    scene_context: Dict[str, Any],
    vehicle_analysis: Dict[str, Any],
    spatial_context: Dict[str, Any],
    detections: List[Dict[str, Any]],
) -> str:
    manual = _safe_str(scene_context.get("operational_context"))
    if manual:
        return manual

    vehicle_count = len(vehicle_analysis.get("vehicle_detections", [])) if isinstance(vehicle_analysis, dict) else 0
    spatial_status = _safe_str(spatial_context.get("status"))

    fragments = []
    if vehicle_count:
        fragments.append(f"{vehicle_count} veiculo(s) identificado(s) no enquadramento")
    else:
        fragments.append("ausencia de classificacao automatica confiavel para veiculos")

    if detections:
        fragments.append(f"{len(detections)} regiao(oes) de placa detectada(s)")

    if spatial_status and spatial_status != "unknown":
        fragments.append(f"contexto espacial={spatial_status}")

    return "; ".join(fragments)


def _derive_relevant_elements(
    scene_context: Dict[str, Any],
    vehicle_analysis: Dict[str, Any],
    detections: List[Dict[str, Any]],
) -> List[str]:
    manual = _as_list(scene_context.get("relevant_elements"))
    if manual:
        return manual

    elements: List[str] = []
    detections = vehicle_analysis.get("vehicle_detections", []) if isinstance(vehicle_analysis, dict) else []
    for det in detections[:5]:
        cls = _safe_str(det.get("class_name"))
        bbox = det.get("bbox", [])
        conf = det.get("confidence", 0)
        elements.append(f"{cls or 'veiculo'} em bbox={bbox} (conf={conf:.2f})")

    if detections and len(elements) < 8:
        for det in detections[:8 - len(elements)]:
            bbox = det.get("bbox", [])
            conf = float(det.get("confidence", 0.0) or 0.0)
            rank = int(det.get("priority_rank", 0) or 0)
            rank_txt = f", rank={rank}" if rank > 0 else ""
            elements.append(f"placa candidata em bbox={bbox} (conf={conf:.2f}{rank_txt})")

    if not elements:
        elements.append("elementos relevantes nao parametrizados automaticamente")

    return elements


def _derive_forensic_potential(scene_context: Dict[str, Any], vehicle_analysis: Dict[str, Any], spatial_context: Dict[str, Any]) -> List[str]:
    manual = _as_list(scene_context.get("forensic_potential"))
    if manual:
        return manual

    potential = [
        "correlacao espacial e operacional da cena",
        "analise de posicionamento de veiculos e maquinario",
        "verificacao de padrao de circulacao/manobra",
    ]

    if spatial_context.get("gps_extracted"):
        potential.append("correlacao geoespacial por GPS EXIF")
    if vehicle_analysis.get("make_model_clip"):
        potential.append("sugestao de fabricante/modelo do veiculo")

    return potential


def _derive_limitations(scene_context: Dict[str, Any], image_quality: Dict[str, Any], spatial_context: Dict[str, Any]) -> List[str]:
    manual = _as_list(scene_context.get("limitations"))
    if manual:
        return manual

    limitations: List[str] = []
    if image_quality.get("overall_quality_score", 1.0) < 0.5:
        limitations.append("qualidade da imagem insuficiente para leitura fina de detalhes")
    if _safe_str(image_quality.get("brightness_level")) in {"too_dark", "too_bright"}:
        limitations.append("iluminacao desfavoravel impactando analise visual")
    if not spatial_context.get("gps_extracted"):
        limitations.append("ausencia de GPS EXIF valido para georreferenciamento")
    if not limitations:
        limitations.append("limites de analise dependem da resolucao original e do angulo de captura")
    return limitations


def build_scene_brief_report(
    scene_context: Dict[str, Any],
    *,
    filename: str = "",
    analysis_id: str = "",
    image_quality: Dict[str, Any] | None = None,
    vehicle_analysis: Dict[str, Any] | None = None,
    spatial_context: Dict[str, Any] | None = None,
    detections: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Gera relatorio breve da cena com foco pericial."""
    scene_context = scene_context or {}
    image_quality = image_quality or {}
    vehicle_analysis = vehicle_analysis or {}
    spatial_context = spatial_context or {}
    detections = detections or []

    scene_type = _derive_scene_type(scene_context, vehicle_analysis)
    capture_condition = _derive_capture_condition(scene_context, image_quality)
    operational_context = _derive_operational_context(scene_context, vehicle_analysis, spatial_context, detections)
    relevant_elements = _derive_relevant_elements(scene_context, vehicle_analysis, detections)
    forensic_potential = _derive_forensic_potential(scene_context, vehicle_analysis, spatial_context)
    limitations = _derive_limitations(scene_context, image_quality, spatial_context)

    if scene_context.get("scene_summary"):
        summary = _safe_str(scene_context.get("scene_summary"))
    else:
        summary = (
            f"Cena classificada como {scene_type}. "
            f"Captura descrita como {capture_condition}. "
            f"Contexto operacional: {operational_context}."
        )

    if scene_context.get("conclusion"):
        conclusion = _safe_str(scene_context.get("conclusion"))
    else:
        conclusion = (
            "A cena deve ser tratada como evidencia complementar de contexto, "
            "especialmente util para analise de posicao, dinamica e ambiente operacional."
        )

    methodology = [
        "1) Preservacao da evidencia original e leitura do arquivo submetido.",
        "2) Identificacao do contexto visual/operacional da cena a partir do material fornecido.",
        "3) Cruzamento com qualidade da imagem, analise veicular e contexto espacial quando disponiveis.",
        "4) Consolidacao dos elementos relevantes, potencial pericial e limitacoes tecnicas.",
        "5) Estruturacao do relatorio para uso investigativo e posterior correlacao com outras provas.",
    ]

    return {
        "title": "Analise Preliminar da Imagem",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_id": _safe_str(analysis_id),
        "filename": _safe_str(filename),
        "scene_type": scene_type,
        "capture_condition": capture_condition,
        "operational_context": operational_context,
        "summary": summary,
        "relevant_elements": relevant_elements,
        "forensic_potential": forensic_potential,
        "limitations": limitations,
        "methodology": methodology,
        "conclusion": conclusion,
        "scene_context": scene_context,
        "evidence_level": "MEDIA" if detections or vehicle_analysis else "BAIXA",
    }
