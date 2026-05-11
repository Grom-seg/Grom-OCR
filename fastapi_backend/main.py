
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FastAPI Backend para GROM OCR com Orquestração Forense"""

# ⚠️  CRÍTICO: Carregar .env ANTES de qualquer outro import
import os
from pathlib import Path

_env_path = Path(__file__).parent.parent / '.env'
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if key not in os.environ:
                    os.environ[key] = value.strip()

# Agora importar resto
from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Dict, Any
import uvicorn
import io
import sys
import tempfile
import shutil
import re
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi_backend.preprocessing import preprocess_image
from fastapi_backend.detector_module import detect_plate
from fastapi_backend.ensemble_detector import detect_ensemble
from fastapi_backend.onnx_detector import get_onnx_detector
from fastapi_backend.pdf_forensic import generate_forensic_pdf
from fastapi_backend.onnx_exporter import export_to_onnx, get_export_info
from fastapi_backend.benchmark_onnx import run_benchmark, format_report
from fastapi_backend.ocr_module import run_ocr, get_last_ocr_runtime_info
from PIL import Image, ImageFilter, ImageStat
from fpdf import FPDF
from fastapi_backend.plate_validator import PlateValidator
from fastapi_backend.quality_metrics import ImageQualityAnalyzer
from fastapi_backend.confidence_scorer import ConfidenceScorer
from fastapi_backend.orchestrator import (
    ForensicOrchestrator, ForensicAnalysisContext, TaskDomain,
    init_global_orchestrator, get_global_orchestrator,
)
try:
    from fastapi_backend.plate_recognizer_v2 import recognize_plate_external
    _PLATE_RECOGNIZER_AVAILABLE = True
except ImportError:
    _PLATE_RECOGNIZER_AVAILABLE = False
    def recognize_plate_external(*args, **kwargs):
        return False, None, {}

try:
    from fastapi_backend.easyocr_wrapper import recognize_with_easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False
    def recognize_with_easyocr(*args, **kwargs):
        return []

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PYTHON_ROOT = os.path.join(PROJECT_ROOT, 'python')
if PYTHON_ROOT not in sys.path:
    sys.path.insert(0, PYTHON_ROOT)

try:
    import ocr_agent as legacy_ocr_agent  # type: ignore
    _legacy_pipeline_ok = True
except Exception:
    legacy_ocr_agent = None  # type: ignore
    _legacy_pipeline_ok = False

# Módulos adicionais (lazy — importados com try/except para não bloquear init)
try:
    from fastapi_backend.frame_selector import (
        select_best_frame, merge_hdr, load_frames_from_paths, lap_variance,
    )
    _frame_selector_ok = True
except Exception:
    _frame_selector_ok = False

try:
    from fastapi_backend.super_resolution import get_sr_info
    _sr_info_ok = True
except Exception:
    _sr_info_ok = False
    def get_sr_info():  # type: ignore[misc]
        return {'backend': 'unavailable'}

try:
    from fastapi_backend.lprnet_ocr import get_lprnet_info
    _lprnet_info_ok = True
except Exception:
    _lprnet_info_ok = False
    def get_lprnet_info():  # type: ignore[misc]
        return {'available': False}

try:
    from fastapi_backend.vehicle_analyzer import analyze_vehicle, get_vehicle_analyzer_info
    _va_ok = True
except Exception:
    _va_ok = False

try:
    from fastapi_backend.geo_context import analyze_spatial_context, get_geo_context_info
    _geo_ok = True
except Exception:
    _geo_ok = False
    def analyze_spatial_context(*args, **kwargs):
        return {'status': 'geo_context_unavailable', 'gps_extracted': False}
    def get_geo_context_info():
        return {'available': False}

try:
    from fastapi_backend.spatial_report import build_spatial_brief_report
    _spatial_report_ok = True
except Exception:
    _spatial_report_ok = False
    def build_spatial_brief_report(*args, **kwargs):
        return {
            'title': 'Relatorio Breve de Analise Geoespacial',
            'status': 'spatial_report_unavailable',
            'evidence_level': 'BAIXA',
            'conclusion': 'Modulo de relatorio espacial indisponivel.',
            'findings': [],
            'methodology': [],
            'legal_notes': [],
        }

try:
    from fastapi_backend.scene_report import build_scene_brief_report
    _scene_report_ok = True
except Exception:
    _scene_report_ok = False
    def build_scene_brief_report(*args, **kwargs):
        return {
            'title': 'Analise Preliminar da Imagem',
            'scene_type': 'cena_nao_classificada',
            'capture_condition': 'indisponivel',
            'operational_context': 'indisponivel',
            'summary': 'Modulo de analise de cena indisponivel.',
            'relevant_elements': [],
            'forensic_potential': [],
            'limitations': [],
            'methodology': [],
            'conclusion': 'Relatorio de cena nao disponivel.',
        }

try:
    from fastapi_backend.vehicle_osint import build_vehicle_osint_report
    _vehicle_osint_ok = True
except Exception:
    _vehicle_osint_ok = False

    def build_vehicle_osint_report(*args, **kwargs):
        return {
            'status': 'unavailable',
            'title': 'Inferencia OSINT de Modelo Veicular (Complementar)',
            'top_model_candidates': [],
            'summary': {
                'top_candidate': '',
                'top_probability_score': 0.0,
                'candidate_count': 0,
            },
            'legal_disclaimer': 'Modulo OSINT indisponivel no ambiente atual.',
        }

try:
    from fastapi_backend.datasets_loader import datasets_status
    _datasets_loader_ok = True
except Exception:
    _datasets_loader_ok = False

    def datasets_status():
        return {
            'brazilian_cars_ref': {'available': False},
            'brcars_summary': {'available': False},
        }

try:
    from fastapi_backend.osint_database import get_osint_database as _get_osint_db
    _osint_db_module_ok = True
except Exception:
    _osint_db_module_ok = False

    def _get_osint_db():  # type: ignore
        return None

try:
    from fastapi_backend.semantic_search import get_semantic_search as _get_semantic_search, is_semantic_search_available
    _semantic_search_module_ok = True
except Exception:
    _semantic_search_module_ok = False

    def _get_semantic_search():  # type: ignore
        return None

    def is_semantic_search_available() -> bool:  # type: ignore
        return False

try:
    from fastapi_backend.evidence_chain import sha256_file, compute_payload_hash, register_evidence_chain_entry
    _evidence_chain_ok = True
except Exception:
    _evidence_chain_ok = False

    def sha256_file(path):
        return ''

    def compute_payload_hash(payload):
        return ''

    def register_evidence_chain_entry(*args, **kwargs):
        return {}

def _is_legacy_pipeline_enabled() -> bool:
    """Verifica se o pipeline forense legado está habilitado."""
    # DESABILITADO: delegação bloqueante não funciona com FastAPI assíncrono
    return False


app = FastAPI(title="Grom OCR Backend", description="API para detecção e leitura de placas veiculares com IA pericial.")

UPLOAD_DIR = os.getenv('GROM_OCR_UPLOAD_DIR') or os.path.join(tempfile.gettempdir(), 'grom_ocr_uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Inicializar orquestrador forense global (SEM delegação bloqueante)
_orchestrator = init_global_orchestrator(
    legacy_ocr_agent=None,
    enable_delegations=False,
)


def _delegate_to_legacy_process(upload: UploadFile, analysis_stage: str) -> JSONResponse:
    if not _legacy_pipeline_ok or legacy_ocr_agent is None:
        return JSONResponse(status_code=503, content={'error': 'pipeline_forense_indisponivel'})

    upload_bytes = upload.file.read()
    safe_name = _sanitize_filename(upload.filename or 'upload.jpg')
    stage = str(analysis_stage or 'final').strip().lower()
    if stage not in ('preview', 'final'):
        stage = 'final'

    client = legacy_ocr_agent.app.test_client()
    response = client.post(
        '/process',
        data={
            'analysis_stage': stage,
            'image': (io.BytesIO(upload_bytes), safe_name),
        },
        content_type='multipart/form-data',
    )
    payload = response.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {'error': 'resposta_invalida_pipeline_forense'}
    return JSONResponse(status_code=int(response.status_code), content=payload)

@app.get("/")
def root():
    return {"status": "ok", "message": "Grom OCR FastAPI backend operacional"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "fastapi_backend", "timestamp_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/ocr/runtime")
def ocr_runtime():
    return {
        "status": "ok",
        "service": "fastapi_backend",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "ocr_runtime": get_last_ocr_runtime_info(),
    }


def _save_upload_to_temp(upload: UploadFile) -> str:
    suffix = os.path.splitext(upload.filename or 'upload.jpg')[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        tmp.write(upload.file.read())
    return tmp_path


def _upscale_crop_for_ocr(crop_path: str) -> None:
    """
    Upscaling de crop antes do OCR para melhorar legibilidade de placas pequenas.
    Aplica apenas quando a largura do crop está abaixo do limiar configurado.

    Perfis (inspirados em práticas ALPR robustas para cenas degradadas):
    - open: menor ampliação para reduzir artefatos em cenas bem iluminadas.
    - closed: maior ampliação para compensar baixa luz/baixo contraste.
    - auto (default): escolhe perfil com base em luminância/contraste do crop.
    """
    try:
        with Image.open(crop_path) as crop_img:
            profile = str(os.getenv('GROM_OCR_CROP_UPSCALE_PROFILE', 'auto') or 'auto').strip().lower()

            min_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MIN_WIDTH', '320'))
            scale_factor = float(os.getenv('GROM_OCR_CROP_UPSCALE_FACTOR', '2.5'))
            max_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MAX_WIDTH', '1400'))

            # Perfil automático aberto/fechado por luminância e contraste do crop.
            if profile == 'auto':
                gray = crop_img.convert('L')
                stats = ImageStat.Stat(gray)
                mean_luma = float(stats.mean[0]) if stats.mean else 0.0
                std_luma = float(stats.stddev[0]) if stats.stddev else 0.0

                if mean_luma < 118.0 or std_luma < 42.0:
                    profile = 'closed'
                else:
                    profile = 'open'

            if profile in ('closed', 'fechado', 'night'):
                min_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MIN_WIDTH_CLOSED', '420'))
                scale_factor = float(os.getenv('GROM_OCR_CROP_UPSCALE_FACTOR_CLOSED', '3.2'))
                max_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MAX_WIDTH_CLOSED', '1800'))
            elif profile in ('open', 'aberto', 'day'):
                min_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MIN_WIDTH_OPEN', '320'))
                scale_factor = float(os.getenv('GROM_OCR_CROP_UPSCALE_FACTOR_OPEN', '2.4'))
                max_width = int(os.getenv('GROM_OCR_CROP_UPSCALE_MAX_WIDTH_OPEN', '1400'))

            if min_width <= 0 or scale_factor <= 1.0:
                return

            w, h = crop_img.size
            if w <= 0 or h <= 0 or w >= min_width:
                return

            target_w = max(min_width, int(round(w * scale_factor)))
            target_w = min(max_width, target_w)
            if target_w <= w:
                return

            target_h = max(1, int(round(h * (target_w / float(w)))))
            resized = crop_img.convert('RGB').resize((target_w, target_h), Image.Resampling.LANCZOS)
            # Leve unsharp para ressaltar bordas de caracteres sem exagerar ruído.
            resized = resized.filter(ImageFilter.UnsharpMask(radius=1.4, percent=160, threshold=2))
            resized.save(crop_path, quality=95)
    except Exception:
        # Se o upscaling falhar, mantém fluxo de OCR original sem bloquear análise.
        return


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]', '_', str(name or '').strip())
    cleaned = cleaned.strip('._')
    return cleaned or 'upload.jpg'


def _normalize_plate_text(text: str) -> str:
    raw = str(text or '').strip().upper()
    # Mantem padrao juridico de exibicao sem separadores: ABC1234 / ABC1D23
    return re.sub(r'[^A-Z0-9]', '', raw)


def _normalize_confidence_value(value: Any) -> float:
    try:
        conf = float(value or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf > 1.0:
        conf = conf / 100.0
    return max(0.0, min(1.0, conf))


def _plate_pattern_quality(text: str) -> float:
    cleaned = _normalize_plate_text(text)
    if not cleaned:
        return 0.0

    # Padrões BR: AAA1234 (antigo) e AAA1A23 (Mercosul)
    if re.fullmatch(r'[A-Z]{3}[0-9]{4}', cleaned):
        return 1.0
    if re.fullmatch(r'[A-Z]{3}[0-9][A-Z][0-9]{2}', cleaned):
        return 1.0

    # Quase-padrão: comprimento 7 com mistura plausível
    if len(cleaned) == 7:
        letters = sum(1 for c in cleaned if 'A' <= c <= 'Z')
        digits = sum(1 for c in cleaned if '0' <= c <= '9')
        if letters >= 2 and digits >= 2:
            return 0.6
        return 0.35

    # Textos curtos/longos seguem com baixa prioridade para triagem manual
    if 5 <= len(cleaned) <= 8:
        return 0.2
    return 0.05


def _bbox_plate_likelihood(bbox: Any) -> float:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return 0.35
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return 0.35
    w = max(1.0, x2 - x1)
    h = max(1.0, y2 - y1)
    ratio = w / h
    if ratio < 1.2 or ratio > 10.0:
        return 0.05
    # Pico de similaridade em torno de 3.5, queda gradual para lados.
    return max(0.1, 1.0 - min(1.0, abs(ratio - 3.5) / 4.0))


def _score_detection_priority(det: Dict[str, Any], img_w: int, img_h: int) -> float:
    """
    Priorizacao da placa principal em cenarios multi-veiculo.
    Combina tamanho, confianca e centralidade da placa na cena.
    """
    bbox = det.get('bbox') or [0, 0, 0, 0]
    if len(bbox) != 4:
        return 0.0
    x1, y1, x2, y2 = bbox
    w = max(1.0, float(x2 - x1))
    h = max(1.0, float(y2 - y1))
    area = w * h
    area_ratio = area / max(1.0, float(img_w * img_h))

    cx = (float(x1) + float(x2)) / 2.0
    cy = (float(y1) + float(y2)) / 2.0
    dx = abs(cx - (img_w / 2.0)) / max(1.0, img_w / 2.0)
    dy = abs(cy - (img_h / 2.0)) / max(1.0, img_h / 2.0)
    centrality = 1.0 - min(1.0, (dx + dy) / 2.0)

    confidence = float(det.get('confidence', 0.0) or 0.0)
    # CRÍTICO: Área (tamanho visual) é indicador PRIMARY de proeminência
    # Reduz peso da confiança YOLO para evitar falsos positivos em segundo plano
    # Pesos: área 60% (tamanho visual), centralidade 25%, confiança 15%
    return (area_ratio * 0.60) + (centrality * 0.25) + (confidence * 0.15)


def _prioritize_detections(detections: List[dict], image_size: tuple) -> List[dict]:
    if not detections:
        return []
    img_w, img_h = image_size
    ranked = []
    for d in detections:
        dd = dict(d)
        dd['priority_score'] = round(_score_detection_priority(dd, img_w, img_h), 6)
        ranked.append(dd)
    ranked.sort(key=lambda item: float(item.get('priority_score', 0.0)), reverse=True)
    for idx, d in enumerate(ranked):
        d['priority_rank'] = idx + 1
        d['is_primary_candidate'] = idx == 0
    return ranked


def _build_unique_artifact_filename(original_filename: str, analysis_id: str, prefix: str = '', default_extension: str = '', force_extension: bool = False) -> str:
    safe_name = _sanitize_filename(original_filename)
    base_name, extension = os.path.splitext(safe_name)
    base_name = _sanitize_filename(base_name) or 'arquivo'
    token = _sanitize_filename(analysis_id)[:12]
    if force_extension or not extension:
        extension = default_extension or extension or ''
    if extension and not extension.startswith('.'):
        extension = f'.{extension}'

    artifact_name = f"{prefix}{base_name}"
    if token:
        artifact_name = f"{artifact_name}_{token}"
    if extension and not artifact_name.lower().endswith(extension.lower()):
        artifact_name = f"{artifact_name}{extension}"
    return _sanitize_filename(artifact_name)


def _resolve_upload_file(filename: str):
    raw_name = str(filename or '').strip()
    if not raw_name:
        return None

    # Aceita caminho absoluto quando o frontend repassa caminho local completo.
    if os.path.isabs(raw_name) and os.path.exists(raw_name):
        return raw_name

    safe_name = _sanitize_filename(raw_name)
    if not safe_name:
        return None

    path = os.path.join(UPLOAD_DIR, safe_name)
    if os.path.exists(path):
        return path

    # Fallback por basename para contextos que trazem subpastas no nome.
    base_safe = _sanitize_filename(os.path.basename(raw_name))
    if base_safe:
        alt_path = os.path.join(UPLOAD_DIR, base_safe)
        if os.path.exists(alt_path):
            return alt_path

    return None


def _parse_json_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _dedupe_text_lines(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for raw in items:
        text = str(raw or '').strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _latin1_safe_text(value: Any) -> str:
    text = str(value or '')
    return text.encode('latin-1', 'ignore').decode('latin-1')


def _latin1_safe_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _latin1_safe_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_latin1_safe_obj(v) for v in value]
    if isinstance(value, str):
        return _latin1_safe_text(value)
    return value


def _file_sha256(path: str) -> str:
    if not path or not os.path.exists(path):
        return ''
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _bbox_key(bbox: Any) -> str:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return ''
    vals = []
    for value in bbox:
        try:
            vals.append(str(int(round(float(value)))))
        except (TypeError, ValueError):
            vals.append('0')
    return ','.join(vals)


def _build_plate_analyses(detections: List[dict], ocr_results: List[dict]) -> List[dict]:
    analyses = []
    rows_by_bbox: Dict[str, List[dict]] = {}
    for row in ocr_results:
        if not isinstance(row, dict):
            continue
        key = _bbox_key(row.get('bbox'))
        rows_by_bbox.setdefault(key, []).append(row)

    for det in detections:
        if not isinstance(det, dict):
            continue
        bbox = det.get('bbox', [])
        key = _bbox_key(bbox)
        rows = rows_by_bbox.get(key, [])
        candidates = []
        for item in rows:
            text = _normalize_plate_text(item.get('text', ''))
            if not text:
                continue
            conf = _normalize_confidence_value(item.get('confidence', item.get('score', 0.0)))
            pattern_quality = _plate_pattern_quality(text)
            geometry_quality = _bbox_plate_likelihood(item.get('bbox', bbox))
            composite = (conf * 0.60) + (pattern_quality * 0.30) + (geometry_quality * 0.10)
            candidates.append({
                'text': text,
                'engine': str(item.get('engine', 'ocr')),
                'confidence': round(conf, 4),
                'pattern_quality': round(pattern_quality, 4),
                'composite_score': round(composite, 4),
            })
        candidates.sort(key=lambda c: float(c.get('composite_score', 0.0)), reverse=True)
        analyses.append({
            'priority_rank': int(det.get('priority_rank', 0) or 0),
            'priority_score': float(det.get('priority_score', 0.0) or 0.0),
            'is_primary_candidate': bool(det.get('is_primary_candidate', False)),
            'bbox': bbox,
            'detection_confidence': float(det.get('confidence', 0.0) or 0.0),
            'best_text': candidates[0]['text'] if candidates else '',
            'best_engine': candidates[0]['engine'] if candidates else '',
            'best_confidence': candidates[0]['confidence'] if candidates else 0.0,
            'best_composite_score': candidates[0].get('composite_score', 0.0) if candidates else 0.0,
            'candidates': candidates[:8],
        })

    analyses.sort(key=lambda x: (int(x.get('priority_rank', 999) or 999), -float(x.get('best_confidence', 0.0) or 0.0)))

    if analyses:
        return analyses

    # Fallback: quando detector nao retorna bbox, ainda preserva analise por candidatos OCR.
    grouped: Dict[str, List[dict]] = {}
    for row in ocr_results:
        if not isinstance(row, dict):
            continue
        text = _normalize_plate_text(row.get('text', ''))
        if not text:
            continue
        key = _bbox_key(row.get('bbox')) or 'full_image'
        grouped.setdefault(key, []).append(row)

    rank = 1
    for key, rows in grouped.items():
        candidates = []
        for item in rows:
            pattern_quality = _plate_pattern_quality(_normalize_plate_text(item.get('text', '')))
            geometry_quality = _bbox_plate_likelihood(item.get('bbox', []))
            conf = _normalize_confidence_value(item.get('confidence', item.get('score', 0.0)))
            composite = (conf * 0.60) + (pattern_quality * 0.30) + (geometry_quality * 0.10)
            candidates.append({
                'text': _normalize_plate_text(item.get('text', '')),
                'engine': str(item.get('engine', 'ocr')),
                'confidence': round(conf, 4),
                'pattern_quality': round(pattern_quality, 4),
                'composite_score': round(composite, 4),
            })
        candidates = [c for c in candidates if c.get('text')]
        candidates.sort(key=lambda c: float(c.get('composite_score', 0.0)), reverse=True)
        bbox = [] if key == 'full_image' else [int(v) for v in key.split(',')]
        analyses.append({
            'priority_rank': rank,
            'priority_score': 0.0,
            'is_primary_candidate': rank == 1,
            'bbox': bbox,
            'detection_confidence': 0.0,
            'best_text': candidates[0]['text'] if candidates else '',
            'best_engine': candidates[0]['engine'] if candidates else '',
            'best_confidence': candidates[0]['confidence'] if candidates else 0.0,
            'best_composite_score': candidates[0].get('composite_score', 0.0) if candidates else 0.0,
            'candidates': candidates[:8],
        })
        rank += 1

    return analyses


def _external_ocr_for_regions(photo_path: str, detections: List[dict], analysis_id: str, max_regions: int = 4) -> tuple[List[dict], Dict[str, Any]]:
    if not photo_path or not os.path.exists(photo_path):
        return [], {}

    rows: List[dict] = []
    best_metadata: Dict[str, Any] = {}
    best_conf = -1.0

    try:
        image = Image.open(photo_path)
    except Exception:
        return [], {}

    ordered = detections if isinstance(detections, list) else []
    if ordered:
        ordered = sorted(ordered, key=lambda d: int((d or {}).get('priority_rank', 999) or 999))
    else:
        ordered = [{'bbox': [0, 0, image.size[0], image.size[1]], 'priority_rank': 1}]

    for idx, det in enumerate(ordered[:max_regions]):
        if not isinstance(det, dict):
            continue
        bbox = det.get('bbox') if isinstance(det.get('bbox'), list) else [0, 0, image.size[0], image.size[1]]
        if len(bbox) != 4:
            bbox = [0, 0, image.size[0], image.size[1]]

        try:
            x1, y1, x2, y2 = [int(float(v)) for v in bbox]
        except (TypeError, ValueError):
            x1, y1, x2, y2 = 0, 0, image.size[0], image.size[1]
        x1 = max(0, min(x1, image.size[0] - 1))
        y1 = max(0, min(y1, image.size[1] - 1))
        x2 = max(x1 + 1, min(x2, image.size[0]))
        y2 = max(y1 + 1, min(y2, image.size[1]))

        crop = image.crop((x1, y1, x2, y2))
        crop_name = _build_unique_artifact_filename(
            f'plate_region_{idx + 1}.jpg',
            analysis_id,
            prefix='tmp_api_',
            default_extension='.jpg',
            force_extension=True,
        )
        crop_path = os.path.join(UPLOAD_DIR, crop_name)
        try:
            crop.save(crop_path)
            success, plate_text, metadata = recognize_plate_external(crop_path)
        except Exception:
            success, plate_text, metadata = False, None, {}
        finally:
            if os.path.exists(crop_path):
                try:
                    os.remove(crop_path)
                except (PermissionError, OSError):
                    pass

        if not success or not plate_text:
            continue

        confidence = float((metadata or {}).get('confidence', 0.0) or 0.0)
        rows.append({
            'text': _normalize_plate_text(plate_text),
            'confidence': confidence,
            'engine': 'plate_recognizer_api',
            'score': confidence,
            'bbox': [x1, y1, x2, y2],
            'detection_priority_rank': int(det.get('priority_rank', idx + 1) or (idx + 1)),
            'detection_priority_score': float(det.get('priority_score', 0.0) or 0.0),
        })

        if confidence > best_conf:
            best_conf = confidence
            best_metadata = metadata or {}

    return rows, best_metadata


def _detections_missing_valid_ocr(detections: List[dict], ocr_rows: List[dict]) -> List[dict]:
    """Retorna detecções priorizadas que ainda não possuem leitura OCR plausível."""
    if not isinstance(detections, list) or not detections:
        return []

    ranks_with_valid_ocr = set()
    for row in (ocr_rows or []):
        if not isinstance(row, dict):
            continue
        text = _normalize_plate_text(row.get('text', ''))
        if len(text) < 6:
            continue
        try:
            rank = int(row.get('detection_priority_rank', 0) or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank > 0:
            ranks_with_valid_ocr.add(rank)

    missing = []
    for det in detections:
        if not isinstance(det, dict):
            continue
        try:
            rank = int(det.get('priority_rank', 0) or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank <= 0 or rank in ranks_with_valid_ocr:
            continue
        missing.append(det)

    return missing


def _merge_ocr_rows_without_duplicates(existing_rows: List[dict], incoming_rows: List[dict]) -> List[dict]:
    """Mescla linhas OCR evitando duplicidade por (engine, rank, text, bbox)."""
    merged = list(existing_rows or [])
    seen = set()
    for row in merged:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get('engine', '') or ''),
            int(row.get('detection_priority_rank', 0) or 0),
            _normalize_plate_text(row.get('text', '')),
            tuple(row.get('bbox', []) if isinstance(row.get('bbox'), list) else []),
        )
        seen.add(key)

    for row in (incoming_rows or []):
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get('engine', '') or ''),
            int(row.get('detection_priority_rank', 0) or 0),
            _normalize_plate_text(row.get('text', '')),
            tuple(row.get('bbox', []) if isinstance(row.get('bbox'), list) else []),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)

    return merged


def _bbox_iou(a: List[float], b: List[float]) -> float:
    if len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
    union = area_a + area_b - inter_area
    if union <= 0.0:
        return 0.0
    return inter_area / union


def _merge_detections(primary: List[dict], secondary: List[dict], iou_threshold: float = 0.45, max_regions: int = 12) -> List[dict]:
    merged: List[dict] = []

    for src_name, source_rows in (('primary', primary or []), ('secondary', secondary or [])):
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            bbox = row.get('bbox')
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                candidate_bbox = [float(v) for v in bbox]
            except (TypeError, ValueError):
                continue

            candidate = dict(row)
            candidate['source'] = str(candidate.get('source') or candidate.get('detection_method') or src_name)
            candidate['confidence'] = float(candidate.get('confidence', 0.0) or 0.0)

            duplicate_idx = -1
            for idx, existing in enumerate(merged):
                existing_bbox = existing.get('bbox', [])
                if _bbox_iou(candidate_bbox, [float(v) for v in existing_bbox]) >= iou_threshold:
                    duplicate_idx = idx
                    break

            if duplicate_idx >= 0:
                if float(candidate.get('confidence', 0.0)) > float(merged[duplicate_idx].get('confidence', 0.0)):
                    merged[duplicate_idx] = candidate
            else:
                merged.append(candidate)

    merged.sort(key=lambda d: float(d.get('confidence', 0.0) or 0.0), reverse=True)
    return merged[:max_regions]


def _heuristic_plate_detections(image_path: str, max_regions: int = 8) -> List[dict]:
    """
    Fallback robusto para cenarios sem deteccao YOLO/ensemble.
    Propoe regioes retangulares com densidade de bordas compativel com placas.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    if not image_path or not os.path.exists(image_path):
        return []

    data = np.fromfile(image_path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size > 0 else None
    if image is None:
        return []

    img_h, img_w = image.shape[:2]
    if img_h < 40 or img_w < 40:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Realca caracteres e bordas horizontais para placas em baixa escala.
    blur = cv2.bilateralFilter(gray, 9, 75, 75)
    grad_x = cv2.Sobel(blur, cv2.CV_16S, 1, 0, ksize=3)
    abs_grad_x = cv2.convertScaleAbs(grad_x)
    edges = cv2.Canny(abs_grad_x, 40, 140)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    proposals = []
    image_area = float(img_w * img_h)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 46 or h < 14:
            continue
        area = float(w * h)
        area_ratio = area / max(1.0, image_area)
        if area_ratio < 0.00008 or area_ratio > 0.20:
            continue

        aspect = float(w) / max(1.0, float(h))
        if aspect < 1.8 or aspect > 8.0:
            continue

        roi_edges = edges[y:y + h, x:x + w]
        edge_density = float((roi_edges > 0).sum()) / max(1.0, area)
        if edge_density < 0.03 or edge_density > 0.65:
            continue

        cx = x + (w / 2.0)
        cy = y + (h / 2.0)
        dx = abs(cx - (img_w / 2.0)) / max(1.0, img_w / 2.0)
        dy = abs(cy - (img_h / 2.0)) / max(1.0, img_h / 2.0)
        centrality = 1.0 - min(1.0, (dx + dy) / 2.0)

        conf = (0.45 * min(1.0, edge_density * 2.0)) + (0.30 * centrality) + (0.25 * min(1.0, aspect / 6.0))
        proposals.append({
            'bbox': [int(x), int(y), int(x + w), int(y + h)],
            'confidence': round(float(conf), 4),
            'class_name': 'plate_candidate',
            'source': 'heuristic_contour',
        })

    proposals.sort(key=lambda d: float(d.get('confidence', 0.0)), reverse=True)

    selected = []
    for cand in proposals:
        bbox = cand.get('bbox', [])
        if any(_bbox_iou(bbox, s.get('bbox', [])) > 0.35 for s in selected):
            continue
        selected.append(cand)
        if len(selected) >= max_regions:
            break

    if selected:
        return selected

    # Fallback final: varredura por janelas horizontais para cenas distantes.
    windows = []
    scales = [(0.22, 0.065), (0.18, 0.055), (0.14, 0.045)]
    for w_ratio, h_ratio in scales:
        ww = max(36, int(img_w * w_ratio))
        hh = max(14, int(img_h * h_ratio))
        step_x = max(20, ww // 3)
        step_y = max(14, hh // 2)
        y = 0
        while y + hh <= img_h:
            x = 0
            while x + ww <= img_w:
                roi = gray[y:y + hh, x:x + ww]
                gx = cv2.Sobel(roi, cv2.CV_16S, 1, 0, ksize=3)
                gy = cv2.Sobel(roi, cv2.CV_16S, 0, 1, ksize=3)
                ax = cv2.convertScaleAbs(gx)
                ay = cv2.convertScaleAbs(gy)
                score_x = float(ax.mean())
                score_y = float(ay.mean())
                texture = score_x - (0.35 * score_y)
                if texture > 8.0:
                    cx = x + (ww / 2.0)
                    cy = y + (hh / 2.0)
                    dx = abs(cx - (img_w / 2.0)) / max(1.0, img_w / 2.0)
                    dy = abs(cy - (img_h / 2.0)) / max(1.0, img_h / 2.0)
                    centrality = 1.0 - min(1.0, (dx + dy) / 2.0)
                    conf = min(0.95, (texture / 42.0) * 0.7 + centrality * 0.3)
                    windows.append({
                        'bbox': [int(x), int(y), int(x + ww), int(y + hh)],
                        'confidence': round(float(max(0.05, conf)), 4),
                        'class_name': 'plate_candidate',
                        'source': 'heuristic_grid',
                    })
                x += step_x
            y += step_y

    windows.sort(key=lambda d: float(d.get('confidence', 0.0)), reverse=True)
    for cand in windows:
        bbox = cand.get('bbox', [])
        if any(_bbox_iou(bbox, s.get('bbox', [])) > 0.35 for s in selected):
            continue
        selected.append(cand)
        if len(selected) >= max_regions:
            break

    return selected


def _generate_pdf_report(photo_path: str, plate_path: str, recognized_text: str, analysis_id: str, report_context: dict, vehicle_info: dict, forensic: dict, consensus: dict, assessment: dict, pericial: dict, warnings: list):
    source_name = os.path.basename(photo_path or 'report.jpg')
    pdf_name = _build_unique_artifact_filename(source_name, analysis_id, prefix='relatorio_', default_extension='.pdf', force_extension=True)
    pdf_path = os.path.join(UPLOAD_DIR, pdf_name)

    report_context = _latin1_safe_obj(report_context if isinstance(report_context, dict) else {})
    vehicle_info = _latin1_safe_obj(vehicle_info if isinstance(vehicle_info, dict) else {})
    forensic = _latin1_safe_obj(forensic if isinstance(forensic, dict) else {})
    consensus = _latin1_safe_obj(consensus if isinstance(consensus, dict) else {})
    assessment = _latin1_safe_obj(assessment if isinstance(assessment, dict) else {})
    pericial = _latin1_safe_obj(pericial if isinstance(pericial, dict) else {})
    warnings = _latin1_safe_obj(warnings if isinstance(warnings, list) else [])
    recognized_text = _latin1_safe_text(recognized_text)
    analysis_id = _latin1_safe_text(analysis_id)
    scene_brief_report = report_context.get('scene_brief_report', {}) if isinstance(report_context.get('scene_brief_report', {}), dict) else {}
    spatial_context = report_context.get('spatial_context', {}) if isinstance(report_context.get('spatial_context', {}), dict) else {}
    process_trace = report_context.get('process_trace', []) if isinstance(report_context.get('process_trace', []), list) else []
    top_candidates = report_context.get('top_candidates', []) if isinstance(report_context.get('top_candidates', []), list) else []
    plate_analyses = report_context.get('plate_analyses', []) if isinstance(report_context.get('plate_analyses', []), list) else []
    ocr_engine_status = report_context.get('ocr_engine_status', {}) if isinstance(report_context.get('ocr_engine_status', {}), dict) else {}
    ocr_engine_summary = report_context.get('ocr_engine_summary', {}) if isinstance(report_context.get('ocr_engine_summary', {}), dict) else {}
    detection_count = int(report_context.get('detection_count', 0) or 0)

    pdf = FPDF()
    # FPDF2 2.7+ deixa cursor X no final do texto apos multi_cell.
    # Wrapper que sempre reseta X para margem esquerda antes de renderizar.
    def _mc(h: int, txt: str) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, _latin1_safe_text(str(txt or '')), new_x='LMARGIN', new_y='NEXT')

    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'RELATORIO TECNICO PERICIAL - GROM OCR', ln=True)

    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, f'Analise ID: {analysis_id or "-"}', ln=True)
    pdf.cell(0, 6, f'Gerado UTC: {datetime.now(timezone.utc).isoformat()}', ln=True)
    pdf.cell(0, 6, f'Arquivo fonte: {os.path.basename(photo_path)}', ln=True)
    consolidated_text = _normalize_plate_text(recognized_text)
    primary_info = report_context.get('primary_plate_reading', {}) if isinstance(report_context.get('primary_plate_reading'), dict) else {}
    primary_text = _normalize_plate_text(primary_info.get('text', ''))
    primary_status = str(primary_info.get('status', '') or '').strip() or ('plausible' if consolidated_text else 'inconclusive')

    pdf.cell(0, 6, f'Leitura primaria estimada: {primary_text or "INCONCLUSIVA"}', ln=True)
    pdf.cell(0, 6, f'Status leitura primaria: {primary_status}', ln=True)
    pdf.cell(0, 6, f'Placa principal consolidada: {consolidated_text or "NAO RECONHECIDA"}', ln=True)
    pdf.cell(0, 6, f'Total de placas detectadas: {detection_count}', ln=True)
    pdf.ln(1)

    photo_hash = _file_sha256(photo_path)
    plate_hash = _file_sha256(plate_path)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, 'Cadeia de custodia (hash SHA-256)', ln=True)
    pdf.set_font('Arial', '', 9)
    if photo_hash:
        _mc(5, f'Foto original: {photo_hash}')
    if plate_hash:
        _mc(5, f'Recorte principal: {plate_hash}')
    pdf.ln(1)

    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, 'Mecanismos executados nesta imagem', ln=True)
    pdf.set_font('Arial', '', 10)
    engines = ocr_engine_summary.get('engines_executed', []) if isinstance(ocr_engine_summary, dict) else []
    engines_text = ', '.join([str(e) for e in engines]) if engines else 'indisponivel'
    _mc(6, f'Motores OCR executados: {engines_text}')
    if isinstance(ocr_engine_summary, dict):
        pdf.cell(0, 6, f"Fallback acionado: {'sim' if ocr_engine_summary.get('fallback_used') else 'nao'}", ln=True)
    if isinstance(ocr_engine_status, dict):
        for engine_name, status_obj in ocr_engine_status.items():
            if not isinstance(status_obj, dict):
                continue
            status_txt = str(status_obj.get('status', 'unknown'))
            err_txt = str(status_obj.get('error', '') or '').strip()
            line = f'- {engine_name}: {status_txt}'
            if err_txt:
                line += f' (erro: {err_txt})'
            _mc(5, line)
    pdf.ln(1)

    if isinstance(process_trace, list) and process_trace:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Metodologia tecnica aplicada', ln=True)
        pdf.set_font('Arial', '', 10)
        for step in _dedupe_text_lines([str(x) for x in process_trace])[:12]:
            _mc(5, f'- {step}')
        pdf.ln(1)

    if os.path.exists(photo_path):
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Evidencia fotografica original', ln=True)
        try:
            y0 = pdf.get_y() + 1
            pdf.image(photo_path, x=10, y=y0, w=190)
            pdf.set_y(y0 + 82)
        except Exception:
            pdf.set_font('Arial', '', 10)
            pdf.cell(0, 6, 'Nao foi possivel incorporar foto original no PDF.', ln=True)
        pdf.ln(1)

    if isinstance(plate_analyses, list) and plate_analyses:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Analise multi-placa (todas as regioes detectadas)', ln=True)
        pdf.set_font('Arial', '', 10)
        for plate_row in plate_analyses[:15]:
            if not isinstance(plate_row, dict):
                continue
            rank = int(plate_row.get('priority_rank', 0) or 0)
            bbox = plate_row.get('bbox', [])
            best_text = str(plate_row.get('best_text', '') or '').strip()
            best_engine = str(plate_row.get('best_engine', '') or '').strip()
            best_conf = float(plate_row.get('best_confidence', 0.0) or 0.0)
            det_conf = float(plate_row.get('detection_confidence', 0.0) or 0.0)
            marker = ' [PRIMEIRO PLANO]' if bool(plate_row.get('is_primary_candidate')) else ''
            _mc(5, f'Rank {rank}{marker} | bbox={bbox} | conf_det={det_conf:.3f} | melhor OCR={best_text or "-"} ({best_engine or "-"}, {best_conf:.3f})')
        pdf.ln(1)

    if isinstance(top_candidates, list) and top_candidates:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Consolidacao de candidatos OCR', ln=True)
        pdf.set_font('Arial', '', 10)
        for row in top_candidates[:20]:
            if not isinstance(row, dict):
                continue
            txt = _normalize_plate_text(row.get('text', ''))
            eng = str(row.get('engine', '-') or '-')
            sc = float(row.get('score', 0.0) or 0.0)
            sup = int(row.get('support_count', 1) or 1)
            _mc(5, f'- {txt or "-"} | motor={eng} | score={sc:.3f} | suporte={sup}')
        pdf.ln(1)

    if isinstance(scene_brief_report, dict) and scene_brief_report:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Descricao preliminar da cena', ln=True)
        pdf.set_font('Arial', '', 10)
        for key, label in (
            ('scene_type', 'Tipo de cena'),
            ('capture_condition', 'Condicao de captura'),
            ('operational_context', 'Contexto operacional'),
            ('summary', 'Resumo'),
            ('conclusion', 'Conclusao pericial preliminar'),
        ):
            value = str(scene_brief_report.get(key, '') or '').strip()
            if value:
                _mc(5, f'{label}: {value}')

        for section_name, title in (
            ('relevant_elements', 'Elementos relevantes'),
            ('forensic_potential', 'Potencial pericial'),
            ('limitations', 'Limitacoes tecnicas'),
        ):
            rows = scene_brief_report.get(section_name, [])
            if isinstance(rows, list):
                rows = _dedupe_text_lines([str(x) for x in rows])
            else:
                rows = []
            if rows:
                pdf.cell(0, 6, f'{title}:', ln=True)
                for row in rows[:12]:
                    _mc(5, f'- {row}')
        pdf.ln(1)

    if isinstance(spatial_context, dict) and spatial_context:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Contexto geoespacial', ln=True)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, f"Status: {spatial_context.get('status', 'indisponivel')}", ln=True)
        if spatial_context.get('gps_extracted'):
            pdf.cell(0, 6, f"Latitude: {spatial_context.get('latitude', '')}", ln=True)
            pdf.cell(0, 6, f"Longitude: {spatial_context.get('longitude', '')}", ln=True)
            reverse = spatial_context.get('reverse_geocode', {}) if isinstance(spatial_context.get('reverse_geocode', {}), dict) else {}
            if reverse.get('display_name'):
                _mc(5, f"Local aproximado: {reverse.get('display_name')}")
        pdf.ln(1)

    if isinstance(vehicle_info, dict) and vehicle_info:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Informacoes veiculares complementares', ln=True)
        pdf.set_font('Arial', '', 10)
        for key in ('placa', 'fabricante', 'modelo', 'ano', 'cor', 'fonte', 'ambiente'):
            value = str(vehicle_info.get(key, '') or '').strip()
            if value:
                pdf.cell(0, 6, f'{key}: {value}', ln=True)
        pdf.ln(1)

    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, 'Sintese de confianca', ln=True)
    pdf.set_font('Arial', '', 10)
    if isinstance(consensus, dict):
        pdf.cell(0, 6, f"Consenso OCR: {consensus.get('agreement_ratio', 0)}", ln=True)
    if isinstance(assessment, dict):
        pdf.cell(0, 6, f"Nivel de evidencia: {assessment.get('evidence_level', '-')}", ln=True)
        recom = str(assessment.get('confidence_recommendation', '') or '').strip()
        if recom:
            _mc(5, f'Recomendacao: {recom}')
    if isinstance(pericial, dict):
        pdf.cell(0, 6, f"Status pericial: {pericial.get('status', '-')}", ln=True)

    if isinstance(forensic, dict) and forensic:
        pdf.ln(1)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Metadados forenses', ln=True)
        pdf.set_font('Arial', '', 10)
        for key in ('analysis_id', 'source_filename', 'generated_at_utc', 'signature'):
            value = str(forensic.get(key, '') or '').strip()
            if value:
                pdf.cell(0, 6, f'{key}: {value}', ln=True)

    warning_lines = _dedupe_text_lines([str(w) for w in warnings]) if isinstance(warnings, list) else []
    if warning_lines:
        pdf.ln(1)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 7, 'Alertas tecnicos', ln=True)
        pdf.set_font('Arial', '', 10)
        for warning in warning_lines[:16]:
            _mc(5, f'- {warning}')

    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'Evidencias visuais complementares', ln=True)
    pdf.ln(2)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, 'Recorte principal da placa', ln=True)
    try:
        pdf.image(plate_path, x=10, y=30, w=140)
    except Exception:
        pdf.cell(0, 6, 'Nao foi possivel incorporar recorte da placa no PDF.', ln=True)

    pdf.output(pdf_path)
    return pdf_name


def _build_process_payload(filename: str, detections: list, ocr_results: list, analysis_stage: str, analysis_id: str, photo_filename: str, plate_filename: str, crop_raw_filename: str, ocr_runtime_info: dict = None, ocr_runtime_events: list = None, vehicle_info_seed: dict = None):
    ocr_runtime_info = ocr_runtime_info or {}
    ocr_runtime_events = ocr_runtime_events or []
    vehicle_info_seed = vehicle_info_seed or {}

    normalized_ocr_rows = []
    for item in ocr_results:
        if not isinstance(item, dict):
            continue
        text = _normalize_plate_text(item.get('text', ''))
        if text == '':
            continue
        row = dict(item)
        row['text'] = text
        row['confidence'] = _normalize_confidence_value(row.get('confidence', row.get('score', 0.0)))
        normalized_ocr_rows.append(row)

    has_paddle_results = any(c.get('engine') == 'paddleocr' for c in normalized_ocr_rows)
    has_tesseract_results = any(c.get('engine') == 'tesseract' for c in normalized_ocr_rows)
    has_easyocr_results = any(c.get('engine') == 'easyocr' for c in normalized_ocr_rows)
    has_external_results = any(c.get('engine') == 'plate_recognizer_api' for c in normalized_ocr_rows)
    selected_engine = str(ocr_runtime_info.get('selected_engine', '') or '').strip().lower()
    paddle_error = str(ocr_runtime_info.get('paddle_error', '') or '').strip()
    paddle_disabled = bool(ocr_runtime_info.get('paddle_disabled', False))

    paddle_status = 'executed' if (has_paddle_results or selected_engine == 'paddleocr') else 'skipped'
    if paddle_disabled:
        paddle_status = 'disabled'
    elif paddle_error:
        paddle_status = 'failed'

    tesseract_status = 'executed' if (has_tesseract_results or selected_engine == 'tesseract') else 'skipped'

    engines_executed = sorted(list({str(c.get('engine', 'unknown')) for c in normalized_ocr_rows if str(c.get('engine', '')).strip()}))
    if selected_engine and selected_engine not in engines_executed:
        engines_executed.append(selected_engine)
        engines_executed = sorted(engines_executed)
    executed_engine_count = len(engines_executed)

    consolidated = {}
    for row in normalized_ocr_rows:
        text = _normalize_plate_text(row.get('text', ''))
        if text == '':
            continue
        engine = str(row.get('engine', 'ocr')).strip() or 'ocr'
        conf = _normalize_confidence_value(row.get('confidence', row.get('score', 0.0)))
        if text not in consolidated:
            consolidated[text] = {
                'text': text,
                'engine': engine,
                'engine_votes': {},
                'sum_conf': 0.0,
                'support_count': 0,
                'pattern_quality': _plate_pattern_quality(text),
                'bbox_likelihood': _bbox_plate_likelihood(row.get('bbox', [])),
            }
        consolidated[text]['engine_votes'][engine] = int(consolidated[text]['engine_votes'].get(engine, 0) or 0) + 1
        if int(consolidated[text]['engine_votes'][engine]) >= int(consolidated[text]['engine_votes'].get(consolidated[text]['engine'], 0) or 0):
            consolidated[text]['engine'] = engine
        consolidated[text]['bbox_likelihood'] = max(float(consolidated[text]['bbox_likelihood']), _bbox_plate_likelihood(row.get('bbox', [])))
        consolidated[text]['sum_conf'] += conf
        consolidated[text]['support_count'] += 1

    normalized_candidates = []
    for row in consolidated.values():
        support_count = int(row['support_count'])
        engine_support_count = len(set([str(x).strip() for x in row.get('engine_votes', {}).keys() if str(x).strip()]))
        avg_conf = float(row['sum_conf']) / max(1, support_count)
        weighted_support = float(row['sum_conf'])
        support_bonus = 1.0 + min(0.15, 0.03 * (support_count - 1))
        pattern_quality = float(row.get('pattern_quality', 0.0) or 0.0)
        bbox_likelihood = float(row.get('bbox_likelihood', 0.35) or 0.35)
        score = ((avg_conf * 0.60) + (pattern_quality * 0.30) + (bbox_likelihood * 0.10)) * support_bonus
        agreement_ratio = 0.0
        if executed_engine_count > 1:
            agreement_ratio = round((engine_support_count / float(executed_engine_count)) * 100.0, 1)
        normalized_candidates.append({
            'rank': 0,
            'text': row['text'],
            'engine': row['engine'],
            'avg_conf': round(avg_conf, 4),
            'score': round(score, 4),
            'support_count': support_count,
            'engine_support_count': engine_support_count,
            'agreement_ratio': agreement_ratio,
            'weighted_support': round(weighted_support, 4),
            'pattern_quality': round(pattern_quality, 4),
            'bbox_likelihood': round(bbox_likelihood, 4),
            'region': 'BR',
        })

    normalized_candidates.sort(key=lambda c: float(c.get('score', 0.0)), reverse=True)

    if len(normalized_candidates) > 1:
        filtered = []
        for row in normalized_candidates:
            text_len = len(str(row.get('text', '') or ''))
            if text_len < 3 and float(row.get('pattern_quality', 0.0) or 0.0) < 0.30:
                continue
            if float(row.get('score', 0.0) or 0.0) < 0.16:
                continue
            filtered.append(row)
        if filtered:
            normalized_candidates = filtered

    for idx, row in enumerate(normalized_candidates):
        row['rank'] = idx + 1

    plausible_candidates = []
    for row in normalized_candidates:
        text = str(row.get('text', '') or '')
        pattern_quality = float(row.get('pattern_quality', 0.0) or 0.0)
        if pattern_quality >= 0.60:
            plausible_candidates.append(row)
            continue
        if len(text) >= 6 and pattern_quality >= 0.20:
            plausible_candidates.append(row)

    best = plausible_candidates[0] if plausible_candidates else {
        'text': '',
        'engine': 'none',
        'avg_conf': 0.0,
        'score': 0.0,
    }

    warnings = []
    if not normalized_candidates:
        warnings.append('ocr_sem_resultado')
    elif not plausible_candidates:
        warnings.append('best_candidate_low_plausibility')

    fallback_used = bool(ocr_runtime_info.get('fallback_used', False)) or any(
        bool((event or {}).get('fallback_used', False)) for event in ocr_runtime_events
    )

    best_supporting_engines = set()
    best_text_value = _normalize_plate_text(best.get('text', ''))
    if best_text_value:
        for row in normalized_ocr_rows:
            row_text = _normalize_plate_text((row or {}).get('text', ''))
            if row_text == best_text_value:
                row_engine = str((row or {}).get('engine', '') or '').strip()
                if row_engine:
                    best_supporting_engines.add(row_engine)

    consensus_ratio = 0.0
    consensus_basis = 'single_engine_or_no_consensus'
    if executed_engine_count > 1 and best_supporting_engines:
        consensus_ratio = round((len(best_supporting_engines) / float(executed_engine_count)) * 100.0, 1)
        consensus_basis = 'cross_engine_consensus'

    process_trace = [
        '1) Obtencao da imagem e preservacao de evidencia (arquivo original).',
        '2) Tratamento/pre-processamento (qualidade, rotacao e normalizacao).',
        '3) Deteccao de placas com ordenacao por primeiro plano (area, centralidade e confianca).',
        '4) OCR multi-regiao em cascata (motor local + fallbacks externos quando necessario).',
        '5) Consolidacao por consenso, validacao tecnica e trilha forense auditavel.',
    ]

    plate_analyses = _build_plate_analyses(detections, normalized_ocr_rows)

    return {
        'best': best,
        'top_candidates': normalized_candidates,
        'ocr': normalized_ocr_rows,
        'ocr_engine_status': {
            'paddleocr': {'status': paddle_status, 'error': paddle_error},
            'tesseract': {'status': tesseract_status},
            'easyocr': {'status': 'executed' if has_easyocr_results else ('available' if _EASYOCR_AVAILABLE else 'unavailable')},
            'plate_recognizer_api': {'status': 'executed' if has_external_results else ('available' if _PLATE_RECOGNIZER_AVAILABLE else 'unavailable')},
        },
        'ocr_engine_summary': {
            'total_candidates': len(normalized_candidates),
            'engines_executed': engines_executed,
            'fallback_used': fallback_used,
            'paddle_disabled': paddle_disabled,
        },
        'ocr_runtime': ocr_runtime_info,
        'ocr_runtime_events': ocr_runtime_events,
        'regions_tested': [d.get('bbox') for d in detections],
        'detections': detections,
        'forensic': {
            'analysis_id': analysis_id,
            'source_filename': filename,
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        },
        'report_context': {
            'analysis_id': analysis_id,
            'photo_filename': photo_filename,
            'plate_filename': plate_filename,
            'crop_raw_path': crop_raw_filename,
            'crop_treated_path': plate_filename,
            'analysis_stage': analysis_stage,
            'process_trace': process_trace,
            'detection_count': len(detections),
            'plate_analyses': plate_analyses,
            'top_candidates': normalized_candidates,
            'image_evidence': {
                'photo': photo_filename,
                'plate': plate_filename,
                'crop_raw': crop_raw_filename,
            },
        },
        'plate_analyses': plate_analyses,
        'vehicle_info': vehicle_info_seed or {},
        'pdf_report': '',
        'assessment': {
            'manual_review_required': best.get('text', '') == '',
            'evidence_level': 'MEDIA' if best.get('text', '') else 'BAIXA',
        },
        'consensus': {
            'agreement_ratio': consensus_ratio,
            'basis': consensus_basis,
            'best_text': best_text_value,
            'engines_executed_count': executed_engine_count,
            'engines_supporting_best_count': len(best_supporting_engines),
            'engines_supporting_best': sorted(list(best_supporting_engines)),
        },
        'pericial': {
            'status': 'CONCLUIDO' if best.get('text', '') else 'INCONCLUSIVO',
            'quality': {'score': float(best.get('score', 0.0))},
            'cross_checks': {},
        },
        'analysis_stage': analysis_stage,
        'report_ready': False,
        'warnings': warnings,
        'plate_validation': {},
        'image_quality': {},
        'confidence_score': {},
        'analysis_trace': process_trace,
        'spatial_context': {},
        'scene_brief_report': {},
    }

@app.post("/detect-plate/")
async def detect_plate_endpoint(file: UploadFile = File(...)):
    tmp_path = _save_upload_to_temp(file)
    preprocess_image(tmp_path).save(tmp_path)
    detections = detect_plate(tmp_path)
    try:
        os.remove(tmp_path)
    except (PermissionError, OSError):
        pass
    return JSONResponse({
        "filename": file.filename,
        "detections": detections
    })

@app.post("/ocr-plate/")
async def ocr_plate_endpoint(file: UploadFile = File(...)):
    tmp_path = _save_upload_to_temp(file)
    preprocess_image(tmp_path).save(tmp_path)
    try:
        ocr_results = run_ocr(tmp_path)
    except RuntimeError as exc:
        try:
            os.remove(tmp_path)
        except (PermissionError, OSError):
            pass
        return JSONResponse(status_code=503, content={
            "filename": file.filename,
            "error": str(exc)
        })
    try:
        os.remove(tmp_path)
    except (PermissionError, OSError):
        pass
    return JSONResponse({
        "filename": file.filename,
        "ocr_results": ocr_results,
        "ocr_runtime": get_last_ocr_runtime_info(),
    })

@app.post("/full-pipeline/")
async def full_pipeline(file: UploadFile = File(...)):
    """
    Pipeline completo com orquestração forense.

    Hierarquia de tarefas:
    1. detect - detecção de placa
    2. ocr - reconhecimento de caracteres
    3. validate - validação de qualidade

    Suporta delegação ao pipeline legado com fallback.
    """
    # Inicializar contexto forense
    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(
        source_filename=file.filename or 'upload.jpg',
        analysis_stage='final',
    )

    # Definir hierarquia de tarefas
    tasks = {
        'detect': TaskDomain.PLATE_DETECTION,
        'ocr': TaskDomain.OCR_RECOGNITION,
        'validate': TaskDomain.QUALITY_VALIDATION,
    }
    dependencies = {
        'ocr': ['detect'],
        'validate': ['ocr'],
    }
    task_order = orchestrator.define_task_hierarchy(tasks, dependencies)

    tmp_path = _save_upload_to_temp(file)
    preprocess_image(tmp_path).save(tmp_path)
    detections = detect_plate(tmp_path)
    ocr_results = []
    ocr_runtime_events = []
    img = Image.open(tmp_path)
    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        crop = img.crop((x1, y1, x2, y2))
        crop_path = tmp_path + "_crop.jpg"
        crop.save(crop_path)
        try:
            _upscale_crop_for_ocr(crop_path)
            ocr = run_ocr(crop_path)
            ocr_runtime_events.append(get_last_ocr_runtime_info())
        except RuntimeError as exc:
            try:
                os.remove(crop_path)
            except (PermissionError, OSError):
                pass
            try:
                os.remove(tmp_path)
            except (PermissionError, OSError):
                pass
            return JSONResponse(status_code=503, content={
                "filename": file.filename,
                "error": str(exc)
            })
        ocr_results.append({"bbox": det['bbox'], "ocr": ocr})
        try:
            os.remove(crop_path)
        except (PermissionError, OSError):
            pass
    try:
        os.remove(tmp_path)
    except (PermissionError, OSError):
        pass

    result = {
        "filename": file.filename,
        "detections": detections,
        "ocr_results": ocr_results,
        "ocr_runtime_events": ocr_runtime_events,
        "orchestration": {
            "analysis_id": context.analysis_id,
            "task_order": task_order,
            "delegated": False,
        }
    }

    return JSONResponse(result)


@app.post("/process")
async def process_legacy_endpoint(
    image: UploadFile = File(None),
    file: UploadFile = File(None),
    analysis_stage: str = Form('final')
):
    upload = image or file
    if upload is None:
        return JSONResponse(status_code=400, content={'error': 'campo image ou file e obrigatorio'})

    if _is_legacy_pipeline_enabled() and _legacy_pipeline_ok:
        try:
            return _delegate_to_legacy_process(upload, analysis_stage)
        except Exception as exc:
            # Fallback resiliente para o pipeline simplificado se a delegacao falhar em runtime.
            upload.file.seek(0)
            fallback_warning = f'legacy_pipeline_fallback:{exc}'
        else:
            fallback_warning = ''
    else:
        fallback_warning = ''

    analysis_id = str(uuid4())
    safe_upload_name = _sanitize_filename(upload.filename or 'upload.jpg')
    persisted_photo_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, default_extension=os.path.splitext(safe_upload_name)[1] or '.jpg')
    persisted_photo_path = os.path.join(UPLOAD_DIR, persisted_photo_name)

    tmp_path = _save_upload_to_temp(upload)
    shutil.copy2(tmp_path, persisted_photo_path)

    persisted_plate_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, prefix='placa_', default_extension='.jpg', force_extension=True)
    persisted_plate_path = os.path.join(UPLOAD_DIR, persisted_plate_name)
    persisted_crop_raw_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, prefix='placa_raw_', default_extension='.jpg', force_extension=True)
    persisted_crop_raw_path = os.path.join(UPLOAD_DIR, persisted_crop_raw_name)

    try:
        # Análise de qualidade antecipada para guiar o preprocessing
        _pre_quality = ImageQualityAnalyzer().analyze(tmp_path)
        _pre_rotation = _pre_quality.get('rotation_angle', None)

        # Passa o dict completo: preprocessing extrai quality_score e resolution_category
        preprocess_image(
            tmp_path,
            quality_score=_pre_quality,
            rotation_angle=_pre_rotation,
        ).save(tmp_path)
        detector_detections = detect_plate(tmp_path) or []
        try:
            ensemble_detections = detect_ensemble(tmp_path) or []
        except Exception:
            ensemble_detections = []

        raw_detections = _merge_detections(detector_detections, ensemble_detections, iou_threshold=0.45, max_regions=12)
        if not raw_detections:
            raw_detections = _heuristic_plate_detections(tmp_path, max_regions=12)

        ocr_results = []
        ocr_runtime_events = []
        external_metadata = {}
        img = Image.open(tmp_path)
        img_w, img_h = img.size
        detections = _prioritize_detections(raw_detections, (img_w, img_h))
        if detections:
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                crop = img.crop((x1, y1, x2, y2))
                crop_path = tmp_path + '_crop.jpg'
                crop.save(crop_path)
                # Persistimos evidencia principal (placa prioritaria rank=1)
                if det.get('priority_rank', 99) == 1 and not os.path.exists(persisted_crop_raw_path):
                    shutil.copy2(crop_path, persisted_crop_raw_path)
                _upscale_crop_for_ocr(crop_path)
                if det.get('priority_rank', 99) == 1 and not os.path.exists(persisted_plate_path):
                    shutil.copy2(crop_path, persisted_plate_path)
                try:
                    local_ocr = run_ocr(crop_path)
                    for item in local_ocr:
                        item = dict(item)
                        item['bbox'] = det.get('bbox')
                        item['detection_priority_rank'] = det.get('priority_rank')
                        item['detection_priority_score'] = det.get('priority_score')
                        ocr_results.append(item)
                    ocr_runtime_events.append(get_last_ocr_runtime_info())
                except RuntimeError:
                    pass
                finally:
                    if os.path.exists(crop_path):
                        os.remove(crop_path)
        else:
            try:
                ocr_results = run_ocr(tmp_path)
                ocr_runtime_events.append(get_last_ocr_runtime_info())
            except RuntimeError:
                ocr_results = []
            shutil.copy2(tmp_path, persisted_crop_raw_path)
            shutil.copy2(tmp_path, persisted_plate_path)

        has_valid_local_ocr = any(
            isinstance(item, dict) and len(str(item.get('text', '')).strip()) >= 6
            for item in (ocr_results or [])
        )

        # FALLBACK 1: Se OCR local falhou (ou veio inválido), tentar EasyOCR (mais preciso)
        if (not has_valid_local_ocr) and _EASYOCR_AVAILABLE:
            try:
                easyocr_results = recognize_with_easyocr(persisted_plate_path)
                if easyocr_results:
                    for item in easyocr_results:
                        row = dict(item) if isinstance(item, dict) else {}
                        row.setdefault('engine', 'easyocr')
                        if detections:
                            row.setdefault('bbox', detections[0].get('bbox', []))
                            row.setdefault('detection_priority_rank', 1)
                            row.setdefault('detection_priority_score', detections[0].get('priority_score', 0.0))
                        ocr_results.append(row)
                    ocr_runtime_events.append({
                        'engine': 'easyocr',
                        'fallback_used': True,
                        'success': True,
                        'result_count': len(easyocr_results),
                    })
            except Exception as eo_exc:
                import logging
                logging.error(f"EasyOCR fallback falhou: {eo_exc}")

        has_valid_ocr_after_easyocr = any(
            isinstance(item, dict) and len(str(item.get('text', '')).strip()) >= 6
            for item in (ocr_results or [])
        )

        # FALLBACK 2 / ENRIQUECIMENTO: tenta Plate Recognizer em regiões sem OCR plausível.
        missing_detections = _detections_missing_valid_ocr(detections, ocr_results)
        should_call_external = _PLATE_RECOGNIZER_AVAILABLE and (
            (not has_valid_ocr_after_easyocr) or bool(missing_detections)
        )
        if should_call_external:
            try:
                target_detections = missing_detections if missing_detections else detections
                external_rows, best_external_metadata = _external_ocr_for_regions(
                    persisted_photo_path,
                    target_detections,
                    analysis_id,
                    max_regions=8,
                )
                if external_rows:
                    external_metadata = best_external_metadata or {}
                    ocr_results = _merge_ocr_rows_without_duplicates(ocr_results, external_rows)
                    ocr_runtime_events.append({
                        'engine': 'plate_recognizer_api',
                        'fallback_used': True,
                        'success': True,
                        'result_count': len(external_rows),
                    })
            except Exception as pr_exc:
                import logging
                logging.error(f"Plate Recognizer fallback falhou: {pr_exc}")

        vehicle_info_seed = {}
        if external_metadata:
            vehicle_info_seed.update({
                'placa': _normalize_plate_text(external_metadata.get('plate', '')),
                'fabricante': str(external_metadata.get('vehicle_make', '') or '').strip(),
                'modelo': str(external_metadata.get('vehicle_model', '') or '').strip(),
                'cor': str(external_metadata.get('vehicle_color', '') or '').strip(),
                'fonte': 'plate_recognizer_api',
            })

        vehicle_analysis_result = {}
        if _va_ok:
            try:
                vehicle_analysis_result = analyze_vehicle(persisted_photo_path) or {}
                va = vehicle_analysis_result
                top_clip = (va.get('make_model_clip') or [{}])[0] if isinstance(va, dict) else {}
                if isinstance(top_clip, dict):
                    label = str(top_clip.get('label', '') or '').strip()
                    if label and not vehicle_info_seed.get('fabricante'):
                        vehicle_info_seed['fabricante'] = label.split(' ')[0]
                    if label and not vehicle_info_seed.get('modelo'):
                        vehicle_info_seed['modelo'] = label
                if isinstance(va, dict) and va.get('vehicle_detections'):
                    best_vehicle = max(va.get('vehicle_detections', []), key=lambda d: float(d.get('confidence', 0.0) or 0.0))
                    vehicle_info_seed.setdefault('ambiente', f"veiculo:{best_vehicle.get('class_name', 'desconhecido')}")
            except Exception:
                pass

        payload = _build_process_payload(
            upload.filename or 'upload',
            detections,
            ocr_results,
            analysis_stage.lower(),
            analysis_id,
            persisted_photo_name,
            persisted_plate_name,
            persisted_crop_raw_name,
            ocr_runtime_info=get_last_ocr_runtime_info(),
            ocr_runtime_events=ocr_runtime_events,
            vehicle_info_seed=vehicle_info_seed,
        )

        payload['vehicle_analysis'] = vehicle_analysis_result

        # Enriquece com validação, qualidade e confiança
        payload = _enrich_payload_with_validation(payload, persisted_photo_path)
        if fallback_warning:
            payload.setdefault('warnings', [])
            if isinstance(payload['warnings'], list):
                payload['warnings'].append(fallback_warning)

        return JSONResponse(payload)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except (PermissionError, OSError):
                pass


@app.post("/process-ensemble")
async def process_ensemble_endpoint(
    upload: UploadFile = File(...),
    analysis_stage: str = Form(default='investigacao'),
):
    """
    Endpoint de detecção em ensemble (Phase 3) com orquestração forense.

    Hierarquia de tarefas:
    1. detect (ensemble) - detecção de placa via YOLO + fallback contours
    2. ocr - reconhecimento de caracteres
    3. validate - validação de qualidade e conformidade

    Suporta delegação robusta ao pipeline legado com fallback resiliente.
    """
    # Inicializar contexto forense com orquestrador
    orchestrator = get_global_orchestrator()
    context = orchestrator.create_analysis_context(
        source_filename=upload.filename or 'upload.jpg',
        analysis_stage=analysis_stage.lower(),
    )

    # Definir hierarquia de tarefas
    tasks = {
        'detect': TaskDomain.ENSEMBLE_DETECTION,
        'ocr': TaskDomain.OCR_RECOGNITION,
        'validate': TaskDomain.QUALITY_VALIDATION,
    }
    dependencies = {
        'ocr': ['detect'],
        'validate': ['ocr'],
    }
    task_order = orchestrator.define_task_hierarchy(tasks, dependencies)

    # Verificar se deve delegar integralmente ao pipeline legado
    if _is_legacy_pipeline_enabled() and _legacy_pipeline_ok:
        try:
            return _delegate_to_legacy_process(upload, analysis_stage)
        except Exception as exc:
            pass  # Continuar com execução local

    analysis_id = str(uuid4())
    safe_upload_name = _sanitize_filename(upload.filename or 'upload.jpg')
    persisted_photo_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, default_extension=os.path.splitext(safe_upload_name)[1] or '.jpg')
    persisted_photo_path = os.path.join(UPLOAD_DIR, persisted_photo_name)

    tmp_path = _save_upload_to_temp(upload)
    shutil.copy2(tmp_path, persisted_photo_path)

    persisted_plate_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, prefix='placa_', default_extension='.jpg', force_extension=True)
    persisted_plate_path = os.path.join(UPLOAD_DIR, persisted_plate_name)
    persisted_crop_raw_name = _build_unique_artifact_filename(safe_upload_name, analysis_id, prefix='placa_raw_', default_extension='.jpg', force_extension=True)
    persisted_crop_raw_path = os.path.join(UPLOAD_DIR, persisted_crop_raw_name)

    try:
        _pre_quality = ImageQualityAnalyzer().analyze(tmp_path)
        _pre_rotation = _pre_quality.get('rotation_angle', None)

        preprocess_image(
            tmp_path,
            quality_score=_pre_quality,
            rotation_angle=_pre_rotation,
        ).save(tmp_path)

        # Detecção combinada para aumentar cobertura multi-placa
        try:
            ensemble_detections = detect_ensemble(tmp_path) or []
        except Exception:
            ensemble_detections = []
        detector_detections = detect_plate(tmp_path) or []
        raw_detections = _merge_detections(ensemble_detections, detector_detections, iou_threshold=0.45, max_regions=12)
        if not raw_detections:
            raw_detections = _heuristic_plate_detections(tmp_path, max_regions=12)

        ocr_results = []
        ocr_runtime_events = []
        external_metadata = {}
        img = Image.open(tmp_path)
        img_w, img_h = img.size
        detections = _prioritize_detections(raw_detections, (img_w, img_h))
        sources = list({d.get('source', 'unknown') for d in detections})
        if detections:
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                crop = img.crop((x1, y1, x2, y2))
                crop_path = tmp_path + '_crop.jpg'
                crop.save(crop_path)
                if det.get('priority_rank', 99) == 1 and not os.path.exists(persisted_crop_raw_path):
                    shutil.copy2(crop_path, persisted_crop_raw_path)
                if det.get('priority_rank', 99) == 1 and not os.path.exists(persisted_plate_path):
                    shutil.copy2(crop_path, persisted_plate_path)
                try:
                    local_ocr = run_ocr(crop_path)
                    for item in local_ocr:
                        item = dict(item)
                        item['bbox'] = det.get('bbox')
                        item['detection_priority_rank'] = det.get('priority_rank')
                        item['detection_priority_score'] = det.get('priority_score')
                        ocr_results.append(item)
                    ocr_runtime_events.append(get_last_ocr_runtime_info())
                except RuntimeError:
                    pass
                finally:
                    if os.path.exists(crop_path):
                        os.remove(crop_path)
        else:
            try:
                ocr_results = run_ocr(tmp_path)
                ocr_runtime_events.append(get_last_ocr_runtime_info())
            except RuntimeError:
                ocr_results = []
            shutil.copy2(tmp_path, persisted_crop_raw_path)
            shutil.copy2(tmp_path, persisted_plate_path)

        has_valid_local_ocr = any(
            isinstance(item, dict) and len(str(item.get('text', '')).strip()) >= 6
            for item in (ocr_results or [])
        )

        # FALLBACK 1: Se OCR local falhou (ou veio inválido), tentar EasyOCR (mais preciso)
        if (not has_valid_local_ocr) and _EASYOCR_AVAILABLE:
            try:
                easyocr_results = recognize_with_easyocr(persisted_plate_path)
                if easyocr_results:
                    for item in easyocr_results:
                        row = dict(item) if isinstance(item, dict) else {}
                        row.setdefault('engine', 'easyocr')
                        if detections:
                            row.setdefault('bbox', detections[0].get('bbox', []))
                            row.setdefault('detection_priority_rank', 1)
                            row.setdefault('detection_priority_score', detections[0].get('priority_score', 0.0))
                        ocr_results.append(row)
                    ocr_runtime_events.append({
                        'engine': 'easyocr',
                        'fallback_used': True,
                        'success': True,
                        'result_count': len(easyocr_results),
                    })
            except Exception as eo_exc:
                import logging
                logging.error(f"EasyOCR fallback falhou: {eo_exc}")

        has_valid_ocr_after_easyocr = any(
            isinstance(item, dict) and len(str(item.get('text', '')).strip()) >= 6
            for item in (ocr_results or [])
        )

        # FALLBACK 2 / ENRIQUECIMENTO: tenta Plate Recognizer em regiões sem OCR plausível.
        missing_detections = _detections_missing_valid_ocr(detections, ocr_results)
        should_call_external = _PLATE_RECOGNIZER_AVAILABLE and (
            (not has_valid_ocr_after_easyocr) or bool(missing_detections)
        )
        if should_call_external:
            try:
                target_detections = missing_detections if missing_detections else detections
                external_rows, best_external_metadata = _external_ocr_for_regions(
                    persisted_photo_path,
                    target_detections,
                    analysis_id,
                    max_regions=8,
                )
                if external_rows:
                    external_metadata = best_external_metadata or {}
                    ocr_results = _merge_ocr_rows_without_duplicates(ocr_results, external_rows)
                    ocr_runtime_events.append({
                        'engine': 'plate_recognizer_api',
                        'fallback_used': True,
                        'success': True,
                        'result_count': len(external_rows),
                    })
            except Exception as pr_exc:
                import logging
                logging.error(f"Plate Recognizer fallback falhou: {pr_exc}")

        vehicle_info_seed = {}
        if external_metadata:
            vehicle_info_seed.update({
                'placa': _normalize_plate_text(external_metadata.get('plate', '')),
                'fabricante': str(external_metadata.get('vehicle_make', '') or '').strip(),
                'modelo': str(external_metadata.get('vehicle_model', '') or '').strip(),
                'cor': str(external_metadata.get('vehicle_color', '') or '').strip(),
                'fonte': 'plate_recognizer_api',
            })

        vehicle_analysis_result = {}
        if _va_ok:
            try:
                vehicle_analysis_result = analyze_vehicle(persisted_photo_path) or {}
                va = vehicle_analysis_result
                top_clip = (va.get('make_model_clip') or [{}])[0] if isinstance(va, dict) else {}
                if isinstance(top_clip, dict):
                    label = str(top_clip.get('label', '') or '').strip()
                    if label and not vehicle_info_seed.get('fabricante'):
                        vehicle_info_seed['fabricante'] = label.split(' ')[0]
                    if label and not vehicle_info_seed.get('modelo'):
                        vehicle_info_seed['modelo'] = label
                if isinstance(va, dict) and va.get('vehicle_detections'):
                    best_vehicle = max(va.get('vehicle_detections', []), key=lambda d: float(d.get('confidence', 0.0) or 0.0))
                    vehicle_info_seed.setdefault('ambiente', f"veiculo:{best_vehicle.get('class_name', 'desconhecido')}")
            except Exception:
                pass

        payload = _build_process_payload(
            upload.filename or 'upload',
            detections,
            ocr_results,
            analysis_stage.lower(),
            analysis_id,
            persisted_photo_name,
            persisted_plate_name,
            persisted_crop_raw_name,
            ocr_runtime_info=get_last_ocr_runtime_info(),
            ocr_runtime_events=ocr_runtime_events,
            vehicle_info_seed=vehicle_info_seed,
        )

        payload['vehicle_analysis'] = vehicle_analysis_result

        payload = _enrich_payload_with_validation(payload, persisted_photo_path)

        payload['ensemble_info'] = {
            'detector_sources': sources,
            'total_raw_detections': len(detections),
            'fallback_activated': 'contour' in sources,
        }

        # Adicionar contexto de orquestração ao payload
        payload['orchestration'] = {
            'analysis_id': context.analysis_id,
            'task_order': task_order,
            'delegated': False,
        }

        return JSONResponse(payload)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/detect-plate-onnx")
async def detect_plate_onnx_endpoint(upload: UploadFile = File(...)):
    """
    Detecção de placa via ONNX Runtime (Phase 4).
    Requer que o modelo ONNX exista (yolov8n.onnx).
    Para exportar: POST /export-onnx

    Returns:
        {
            'detections': [...],
            'backend': 'onnx',
            'model_path': str,
        }
    """
    detector = get_onnx_detector()
    if not detector.is_ready:
        return JSONResponse(
            {
                'error': 'Modelo ONNX não encontrado. Use POST /export-onnx primeiro.',
                'model_path': detector.model_path,
            },
            status_code=503,
        )

    tmp_path = _save_upload_to_temp(upload)
    try:
        detections = detector.detect(tmp_path)
        return JSONResponse({
            'detections': detections,
            'backend': 'onnx',
            'model_path': os.path.basename(detector.model_path),
            'total': len(detections),
        })
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except (PermissionError, OSError):
                pass


@app.post("/export-onnx")
async def export_onnx_endpoint(
    pt_model: str = Body(default=None, embed=True),
    imgsz: int = Body(default=640, embed=True),
    quantize: bool = Body(default=False, embed=True),
):
    """
    Exporta o modelo YOLOv8 para ONNX (Phase 4).
    Operação demorada (~30s na primeira execução).

    Body JSON (todos opcionais):
        pt_model: caminho para .pt (default: yolov8n.pt)
        imgsz: tamanho de entrada (default: 640)
        quantize: se true, gera também versão INT8
    """
    model_path = pt_model or os.getenv('GROM_YOLO_MODEL', 'yolov8n.pt')
    try:
        onnx_path = export_to_onnx(
            pt_model_path=model_path,
            imgsz=imgsz,
        )
        info = get_export_info(onnx_path)
        result = {'status': 'ok', 'onnx': info}

        if quantize:
            from fastapi_backend.onnx_exporter import quantize_onnx_int8
            int8_path = quantize_onnx_int8(onnx_path)
            result['int8'] = get_export_info(int8_path)

        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@app.post("/benchmark-onnx")
async def benchmark_onnx_endpoint(upload: UploadFile = File(...), runs: int = Form(default=20)):
    """
    Benchmark YOLO vs ONNX na imagem enviada (Phase 4).

    Returns:
        Relatório JSON comparativo com latências e speedup.
    """
    tmp_path = _save_upload_to_temp(upload)
    try:
        result = run_benchmark(image_path=tmp_path, runs=runs)
        result['report_text'] = format_report(result)
        return JSONResponse(result)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except (PermissionError, OSError):
                pass


@app.post("/enrich_report")
async def enrich_report_legacy_endpoint(payload: dict = Body(default_factory=dict)):
    if not isinstance(payload, dict):
        payload = {}

    report_context = payload.get('report_context', {})
    if isinstance(report_context, str):
        report_context = _parse_json_dict(report_context)
    if not isinstance(report_context, dict):
        report_context = {}

    image_evidence = report_context.get('image_evidence', {}) if isinstance(report_context.get('image_evidence'), dict) else {}
    photo_filename = (
        report_context.get('photo_filename')
        or payload.get('photo_filename')
        or image_evidence.get('photo')
    )
    plate_filename = (
        report_context.get('plate_filename')
        or payload.get('plate_filename')
        or report_context.get('crop_treated_path')
        or report_context.get('crop_raw_path')
        or image_evidence.get('plate')
    )
    analysis_id = str(report_context.get('analysis_id') or payload.get('analysis_id') or uuid4())
    origem = str(payload.get('origem', 'web') or 'web')

    vehicle_info = _parse_json_dict(payload.get('vehicle_info'))
    forensic = _parse_json_dict(payload.get('forensic') or report_context.get('forensic'))
    consensus = _parse_json_dict(payload.get('consensus') or report_context.get('consensus'))
    assessment = _parse_json_dict(payload.get('assessment') or report_context.get('assessment'))
    pericial = _parse_json_dict(payload.get('pericial') or report_context.get('pericial'))
    warnings = _parse_json_list(payload.get('warnings'))

    top_candidates = _parse_json_list(payload.get('top_candidates') or report_context.get('top_candidates'))
    plate_analyses = _parse_json_list(payload.get('plate_analyses') or report_context.get('plate_analyses'))
    detections = _parse_json_list(payload.get('detections') or report_context.get('detections'))
    ocr_engine_status = _parse_json_dict(payload.get('ocr_engine_status') or report_context.get('ocr_engine_status'))
    ocr_engine_summary = _parse_json_dict(payload.get('ocr_engine_summary') or report_context.get('ocr_engine_summary'))
    image_quality = _parse_json_dict(payload.get('image_quality') or report_context.get('image_quality'))
    vehicle_analysis = _parse_json_dict(payload.get('vehicle_analysis') or report_context.get('vehicle_analysis'))

    if analysis_id and not forensic.get('analysis_id'):
        forensic['analysis_id'] = analysis_id

    photo_path = _resolve_upload_file(str(photo_filename or ''))
    plate_path = _resolve_upload_file(str(plate_filename or ''))
    if not photo_path or not plate_path:
        return JSONResponse(status_code=404, content={'error': 'Arquivos de contexto do relatorio nao encontrados'})

    spatial_context = _parse_json_dict(payload.get('spatial_context') or report_context.get('spatial_context'))
    if not spatial_context:
        try:
            spatial_context = analyze_spatial_context(photo_path)
        except Exception:
            spatial_context = {'status': 'spatial_context_error', 'gps_extracted': False}

    spatial_brief_report = _parse_json_dict(payload.get('spatial_brief_report') or report_context.get('spatial_brief_report'))
    if not spatial_brief_report:
        spatial_brief_report = build_spatial_brief_report(
            spatial_context=spatial_context,
            filename=str(forensic.get('source_filename', '') or os.path.basename(photo_path)),
            analysis_id=analysis_id,
        )

    scene_brief_report = _parse_json_dict(payload.get('scene_brief_report') or report_context.get('scene_brief_report'))
    if not scene_brief_report:
        scene_brief_report = build_scene_brief_report(
            {},
            filename=str(forensic.get('source_filename', '') or os.path.basename(photo_path)),
            analysis_id=analysis_id,
            image_quality=image_quality,
            vehicle_analysis=vehicle_analysis,
            spatial_context=spatial_context,
            detections=detections,
        )

    primary_from_candidates = ''
    if isinstance(top_candidates, list) and top_candidates:
        primary_from_candidates = _normalize_plate_text((top_candidates[0] or {}).get('text', ''))

    ocr_text = _normalize_plate_text(str(payload.get('ocr_text', '') or ''))
    if not ocr_text:
        ocr_text = primary_from_candidates

    report_context.setdefault('analysis_id', analysis_id)
    report_context.setdefault('photo_filename', str(photo_filename or ''))
    report_context.setdefault('plate_filename', str(plate_filename or ''))
    report_context['detection_count'] = len(detections) if isinstance(detections, list) else int(report_context.get('detection_count', 0) or 0)
    report_context['top_candidates'] = top_candidates
    report_context['plate_analyses'] = plate_analyses
    report_context['detections'] = detections
    report_context['ocr_engine_status'] = ocr_engine_status
    report_context['ocr_engine_summary'] = ocr_engine_summary
    report_context['spatial_context'] = spatial_context
    report_context['spatial_brief_report'] = spatial_brief_report
    report_context['scene_brief_report'] = scene_brief_report
    report_context['primary_plate_reading'] = {
        'text': ocr_text,
        'status': 'plausible' if ocr_text else 'inconclusive',
        'source': 'enrich_report_context',
    }

    try:
        pdf_report = _generate_pdf_report(
            photo_path=photo_path,
            plate_path=plate_path,
            recognized_text=ocr_text,
            analysis_id=analysis_id,
            report_context=report_context,
            vehicle_info=vehicle_info,
            forensic=forensic,
            consensus=consensus,
            assessment=assessment,
            pericial=pericial,
            warnings=warnings,
        )
    except Exception as exc:
        import traceback as _tb
        _tb.print_exc()
        return JSONResponse(status_code=500, content={'error': f'Falha ao atualizar relatorio: {exc}'})

    return JSONResponse({
        'status': 'ok',
        'pdf_report': pdf_report,
        'origem': origem,
        'vehicle_info_included': bool(vehicle_info),
        'analysis_id': analysis_id,
    })


@app.get('/pdf/{filename}')
def download_pdf(filename: str):
    safe_name = _sanitize_filename(filename)
    path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={'error': 'Arquivo nao encontrado'})
    return FileResponse(path, media_type='application/pdf', filename=safe_name)


@app.get('/artifact/{filename}')
def download_artifact(filename: str):
    safe_name = _sanitize_filename(filename)
    path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={'error': 'Evidencia nao encontrada'})
    return FileResponse(path, filename=safe_name)


@app.post('/analyze-spatial-metadata')
async def analyze_spatial_metadata_endpoint(file: UploadFile = File(...)):
    """
    Analisa metadados GPS EXIF e contexto espacial da imagem.
    Endpoint focado em imagens sem placa e investigacao de local.
    """
    tmp_path = _save_upload_to_temp(file)
    try:
        spatial = analyze_spatial_context(tmp_path)
        brief = build_spatial_brief_report(
            spatial_context=spatial,
            filename=file.filename or '',
            analysis_id=str(uuid4()),
        )
        return JSONResponse({
            'filename': file.filename,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'spatial_context': spatial,
            'spatial_brief_report': brief,
        })
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except (PermissionError, OSError):
                pass


async def _analyze_video_frame_lightweight(img_bytes: bytes, filename: str) -> dict:
    """
    Pipeline LEVE para frames de vídeo: detecção + OCR local apenas.
    Sem PlateRecognizer, sem PDF, sem CLIP, sem GPS, sem evidência chain.
    Retorna dict mínimo com detections, best, confidence estimado, bbox.
    """
    import io as _io_mod
    import tempfile as _tmp_mod

    suffix = os.path.splitext(filename or 'frame.jpg')[1] or '.jpg'
    tmp_path = None
    try:
        with _tmp_mod.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(img_bytes)
            tmp_path = tf.name

        # Pré-processamento
        try:
            preprocess_image(tmp_path).save(tmp_path)
        except Exception:
            pass

        # Detecção de placa
        try:
            detector_dets = detect_plate(tmp_path) or []
        except Exception:
            detector_dets = []
        try:
            ensemble_dets = detect_ensemble(tmp_path) or []
        except Exception:
            ensemble_dets = []

        raw_dets = _merge_detections(detector_dets, ensemble_dets, iou_threshold=0.45, max_regions=6)
        if not raw_dets:
            raw_dets = _heuristic_plate_detections(tmp_path, max_regions=6)

        img = Image.open(tmp_path)
        img_w, img_h = img.size
        dets = _prioritize_detections(raw_dets, (img_w, img_h))

        # OCR local apenas (sem PlateRecognizer externo)
        ocr_results = []
        if dets:
            for det in dets:
                x1, y1, x2, y2 = det['bbox']
                crop = img.crop((x1, y1, x2, y2))
                crop_path = tmp_path + '_crop.jpg'
                try:
                    crop.save(crop_path)
                    _upscale_crop_for_ocr(crop_path)
                    local_ocr = run_ocr(crop_path)
                    for item in local_ocr:
                        row = dict(item)
                        row['bbox'] = det.get('bbox')
                        row['detection_priority_rank'] = det.get('priority_rank')
                        ocr_results.append(row)
                except Exception:
                    pass
                finally:
                    if os.path.exists(crop_path):
                        try:
                            os.remove(crop_path)
                        except OSError:
                            pass
        else:
            try:
                ocr_results = run_ocr(tmp_path)
            except Exception:
                ocr_results = []

        # Consolida melhor candidato OCR
        valid_candidates = [
            r for r in (ocr_results or [])
            if isinstance(r, dict) and len(_normalize_plate_text(r.get('text', ''))) >= 5
        ]
        valid_candidates.sort(key=lambda r: float(r.get('avg_conf', r.get('score', 0.0))), reverse=True)
        best = valid_candidates[0] if valid_candidates else {}
        best_text = _normalize_plate_text(best.get('text', ''))

        # Validação rápida de placa
        plate_valid = False
        if best_text:
            try:
                pv = PlateValidator(strict_mode=False)
                plate_valid = bool(pv.validate(best_text).get('valid'))
            except Exception:
                pass

        # Estimativa simples de confiança
        avg_conf = float(best.get('avg_conf', best.get('score', 0.0)) or 0.0)
        if avg_conf > 1.0:
            avg_conf = avg_conf / 100.0
        det_conf = float((dets[0].get('confidence', 0.5) if dets else 0.2))
        est_confidence = round((avg_conf * 0.6 + det_conf * 0.4) * (1.1 if plate_valid else 0.7), 4)
        est_confidence = min(1.0, max(0.0, est_confidence))

        return {
            'best': {'text': best_text, 'avg_conf': avg_conf, 'valid': plate_valid},
            'detections': [
                {'bbox': d.get('bbox', []), 'confidence': d.get('confidence', 0.0),
                 'priority_rank': d.get('priority_rank', 99)}
                for d in dets
            ],
            'ocr_results': ocr_results,
            'confidence_score': {'overall_confidence': est_confidence},
            'img_w': img_w,
            'img_h': img_h,
        }
    except Exception as ex:
        return {
            'best': {'text': '', 'avg_conf': 0.0, 'valid': False},
            'detections': [],
            'ocr_results': [],
            'confidence_score': {'overall_confidence': 0.0},
            'error': str(ex),
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _temporal_vehicle_tracking(frame_analyses: list, iou_threshold: float = 0.4) -> dict:
    """
    Rastreia veículos através de frames usando centroide + IoU.
    Agrupa múltiplas detecções do mesmo veículo e consolida leituras OCR.

    Retorna:
        {
            'vehicle_tracks': [
                {
                    'track_id': int,
                    'frames': [{frame_index, timestamp_sec, bbox, confidence, plate_readings}],
                    'consolidated_plate': str (consenso por votação),
                    'plate_candidates': {plate_text: count, ...},
                    'timespan_sec': (start_ts, end_ts),
                    'detections_count': int,
                    'avg_confidence': float,
                }
            ],
            'total_vehicles': int,
        }
    """
    def centroid(bbox):
        if not bbox or len(bbox) < 4:
            return None
        x1, y1, x2, y2 = bbox[:4]
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def iou_overlap(bbox1, bbox2):
        if not bbox1 or not bbox2 or len(bbox1) < 4 or len(bbox2) < 4:
            return 0.0
        x1_1, y1_1, x2_1, y2_1 = bbox1[:4]
        x1_2, y1_2, x2_2, y2_2 = bbox2[:4]
        inter_x1 = max(x1_1, x1_2)
        inter_y1 = max(y1_1, y1_2)
        inter_x2 = min(x2_1, x2_2)
        inter_y2 = min(y2_1, y2_2)
        if inter_x2 < inter_x1 or inter_y2 < inter_y1:
            return 0.0
        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
        box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = box1_area + box2_area - inter_area
        return inter_area / union_area if union_area > 0 else 0.0

    tracks = []
    track_counter = 0

    for frame_data in frame_analyses:
        if not isinstance(frame_data, dict):
            continue
        frame_idx = frame_data.get('frame_index', -1)
        ts = frame_data.get('timestamp_sec', 0.0)
        detections = frame_data.get('detections', [])

        for det in detections:
            if not isinstance(det, dict):
                continue
            bbox = det.get('bbox', [])
            plate_text = det.get('best_text', '').strip()
            conf = det.get('overall_confidence', 0.0)

            matched_track = None
            for track in tracks:
                if not track['frames']:
                    continue
                last_frame = track['frames'][-1]
                last_bbox = last_frame.get('bbox', [])
                if iou_overlap(bbox, last_bbox) >= iou_threshold:
                    matched_track = track
                    break

            if matched_track:
                matched_track['frames'].append({
                    'frame_index': frame_idx,
                    'timestamp_sec': ts,
                    'bbox': bbox,
                    'confidence': conf,
                    'plate_text': plate_text,
                })
                if plate_text:
                    matched_track['plate_votes'][plate_text] = matched_track['plate_votes'].get(plate_text, 0) + 1
            else:
                track_counter += 1
                tracks.append({
                    'track_id': track_counter,
                    'frames': [{
                        'frame_index': frame_idx,
                        'timestamp_sec': ts,
                        'bbox': bbox,
                        'confidence': conf,
                        'plate_text': plate_text,
                    }],
                    'plate_votes': {plate_text: 1} if plate_text else {},
                })

    vehicle_tracks = []
    for track in tracks:
        if not track['frames']:
            continue

        plate_votes = track['plate_votes']
        consolidated = max(plate_votes.items(), key=lambda x: x[1])[0] if plate_votes else ''

        timestamps = [f.get('timestamp_sec', 0.0) for f in track['frames']]
        timespan = (min(timestamps), max(timestamps)) if timestamps else (0.0, 0.0)

        confidences = [f.get('confidence', 0.0) for f in track['frames']]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        vehicle_tracks.append({
            'track_id': track['track_id'],
            'frames': track['frames'],
            'consolidated_plate': consolidated,
            'plate_candidates': plate_votes,
            'timespan_sec': timespan,
            'detections_count': len(track['frames']),
            'avg_confidence': round(avg_conf, 4),
        })

    return {
        'vehicle_tracks': vehicle_tracks,
        'total_vehicles': len(vehicle_tracks),
    }


@app.post("/process_video")
async def process_video_legacy_endpoint(
    video: UploadFile = File(...),
    analysis_stage: str = Form(default='final'),
    max_frames_to_analyze: int = Form(default=10),
    sample_every_n_frames: int = Form(default=5),
):
    """
    Processamento pericial de vídeo com rastreamento temporal de veículos.

    Pipeline em duas fases para garantir conclusão rápida:
    1. Fase leve (todos os frames): detecção + OCR local sem APIs externas,
       sem PDF, sem GPS — apenas para rastrear veículos e eleger o melhor frame.
    2. Fase completa (melhor frame): pipeline pericial completo com enriquecimento,
       PDF, evidência chain e prontidão jurídica.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return JSONResponse(status_code=503, content={'error': 'opencv/numpy nao disponivel para processamento de video'})

    max_frames_to_analyze = max(1, min(int(max_frames_to_analyze or 10), 30))
    sample_every_n_frames = max(1, min(int(sample_every_n_frames or 5), 60))

    if not str(video.filename or '').lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v')):
        return JSONResponse(status_code=400, content={'error': 'Formato de video nao suportado'})

    tmp_video_path = _save_upload_to_temp(video)
    frame_candidates = []

    try:
        cap = cv2.VideoCapture(tmp_video_path)
        if not cap.isOpened():
            return JSONResponse(status_code=400, content={'error': 'Nao foi possivel abrir o video enviado'})

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        # Distribuir amostragem por TODO o vídeo usando seek direto.
        # Gera posições uniformemente distribuídas no vídeo inteiro.
        target_candidates = max_frames_to_analyze * 3
        if total_frames > 0 and target_candidates > 0:
            step = max(1, total_frames // target_candidates)
            frame_positions = list(range(0, total_frames, step))[:target_candidates]
        else:
            frame_positions = list(range(0, max(1, max_frames_to_analyze * 3)))

        for frame_idx in frame_positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok:
                continue

            sharpness = float(lap_variance(frame)) if _frame_selector_ok else float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            mean_luma = float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))
            exposure_penalty = abs(mean_luma - 128.0) / 128.0
            frame_quality = sharpness * (1.0 - min(0.7, exposure_penalty))

            success, encoded = cv2.imencode('.jpg', frame)
            if success:
                frame_candidates.append({
                    'frame_index': frame_idx,
                    'timestamp_sec': round(frame_idx / fps, 3) if fps > 0 else None,
                    'sharpness': round(sharpness, 2),
                    'mean_luma': round(mean_luma, 2),
                    'frame_quality': float(frame_quality),
                    'bytes': encoded.tobytes(),
                })

        cap.release()

        if not frame_candidates:
            return JSONResponse(status_code=400, content={'error': 'Nenhum frame valido extraido do video'})

        frame_candidates.sort(key=lambda x: float(x.get('frame_quality', 0.0)), reverse=True)
        selected = frame_candidates[:max_frames_to_analyze]

        # --- Fase 1: análise leve de todos os frames (sem PDF, sem APIs externas) ---
        frame_analyses = []
        best_overall_cand = None
        best_overall_score = -1.0

        for cand in selected:
            frame_name = f"{Path(video.filename or 'video').stem}_f{cand['frame_index']}.jpg"
            light = await _analyze_video_frame_lightweight(cand['bytes'], frame_name)

            frame_conf = float(light.get('confidence_score', {}).get('overall_confidence', 0.0) or 0.0)
            best_text = str(light.get('best', {}).get('text', '') or '').strip()

            frame_detections = []
            for det in light.get('detections', []):
                if isinstance(det, dict):
                    frame_detections.append({
                        'bbox': det.get('bbox', []),
                        'best_text': best_text,
                        'overall_confidence': frame_conf,
                    })

            frame_analyses.append({
                'frame_index': cand['frame_index'],
                'timestamp_sec': cand.get('timestamp_sec'),
                'sharpness': cand['sharpness'],
                'frame_quality': round(cand['frame_quality'], 3),
                'overall_confidence': frame_conf,
                'detections': frame_detections,
                'best_text': best_text,
            })

            boost = 0.10 if best_text else 0.0
            combined = frame_conf + boost
            if combined > best_overall_score:
                best_overall_score = combined
                best_overall_cand = cand

        # Rastreamento temporal de veículos
        tracking_result = _temporal_vehicle_tracking(frame_analyses, iou_threshold=0.4)
        vehicle_tracks = tracking_result.get('vehicle_tracks', [])
        total_vehicles = tracking_result.get('total_vehicles', 0)

        # --- Fase 2: pipeline completo APENAS no melhor frame eleito ---
        best_cand = best_overall_cand or selected[0]
        up = UploadFile(
            filename=f"{Path(video.filename or 'video').stem}_f{best_cand['frame_index']}.jpg",
            file=io.BytesIO(best_cand['bytes'])
        )
        response = await process_legacy_endpoint(image=up, file=None, analysis_stage=analysis_stage)
        if not isinstance(response, JSONResponse):
            return JSONResponse(status_code=500, content={'error': 'Falha no pipeline pericial do frame selecionado'})

        try:
            best_payload = json.loads(response.body.decode('utf-8'))
        except Exception:
            best_payload = {}

        if not isinstance(best_payload, dict):
            best_payload = {}

        best_payload.setdefault('forensic', {})
        if isinstance(best_payload.get('forensic'), dict):
            best_payload['forensic']['source_type'] = 'video'
            best_payload['forensic']['source_filename'] = str(video.filename or '')

        best_payload['video_context'] = {
            'source_video': video.filename,
            'source_video_sha256': _file_sha256(tmp_video_path),
            'fps': round(fps, 3),
            'total_frames': total_frames,
            'duration_sec': round(total_frames / fps, 2) if fps > 0 else None,
            'sample_every_n_frames': sample_every_n_frames,
            'frames_analyzed': len(selected),
            'best_frame_index': best_cand['frame_index'],
            'best_frame_timestamp_sec': best_cand.get('timestamp_sec'),
            'vehicle_tracks': vehicle_tracks,
            'total_vehicles_detected': total_vehicles,
            'frame_summary': [
                {
                    'frame_index': fa['frame_index'],
                    'timestamp_sec': fa['timestamp_sec'],
                    'sharpness': fa['sharpness'],
                    'frame_quality': fa['frame_quality'],
                    'plate_read': fa['best_text'],
                    'confidence': fa['overall_confidence'],
                }
                for fa in sorted(frame_analyses, key=lambda x: x.get('frame_index', 0))
            ],
        }

        # Garantia explícita: análise de vídeo também sempre retorna OSINT.
        best_payload = _ensure_vehicle_osint_presence(best_payload)

        return JSONResponse(best_payload)
    finally:
        if os.path.exists(tmp_video_path):
            try:
                os.remove(tmp_video_path)
            except (PermissionError, OSError):
                pass


# ---------------------------------------------------------------------------
# Novos endpoints: Frame Selector, HDR Merge, Vehicle Analyzer
# ---------------------------------------------------------------------------

@app.post("/select-frame")
async def select_frame_endpoint(
    files: List[UploadFile] = File(...),
    mode: str = Form(default='best'),
):
    """
    Seleciona o melhor frame de um burst ou faz HDR merge.

    Parâmetros:
      files: lista de imagens (burst de 2–10 frames)
      mode:  'best'  → seleciona frame mais nítido (Laplacian variance)
             'hdr'   → fusão de exposições via Mertens (OpenCV)
    """

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return JSONResponse({'error': 'opencv/numpy indisponivel'}, status_code=503)

    tmp_paths = []
    frames = []
    for f in files:
        tmp = _save_upload_to_temp(f)
        tmp_paths.append(tmp)
        data = np.fromfile(tmp, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size > 0 else None
        frames.append(img)

    sharpness = [
        round(lap_variance(f), 2) if f is not None else 0.0
        for f in frames
    ]

    try:
        if mode == 'hdr':
            result_frame = merge_hdr(frames)
            extra = {'hdr_mean_brightness': round(float(result_frame.mean()), 2)}
        else:
            result_frame = select_best_frame(frames)
            best_idx = sharpness.index(max(sharpness))
            extra = {'selected_index': best_idx}

        # Salva resultado como artifact
        analysis_id = str(uuid4())[:12]
        artifact_name = f'frame_{mode}_{analysis_id}.jpg'
        artifact_path = os.path.join(UPLOAD_DIR, artifact_name)
        cv2.imwrite(artifact_path, result_frame)

        return JSONResponse({
            'mode': mode,
            'frames_received': len(files),
            'sharpness_scores': sharpness,
            'artifact': artifact_name,
            **extra,
        })
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    finally:
        for p in tmp_paths:
            if os.path.exists(p):
                os.remove(p)


@app.post("/analyze-vehicle")
async def analyze_vehicle_endpoint(
    file: UploadFile = File(...),
    include_clip: bool = Form(default=True),
):
    """
    Análise complementar do veículo além da placa.

    Retorna:
      - vehicle_detections: detecções YOLOv8 (class, bbox, confidence)
      - light_regions: regiões estimadas de faróis/lanternas
      - headlight_templates: assinatura de faróis por template matching
      - make_model_clip: identificação de marca/modelo via CLIP zero-shot
      - clip_available, yolo_available, parts_model_available

    Este endpoint é isolado do pipeline /process - não afeta latência
    nem confiança de detecção de placa.
    """
    if not _va_ok:
        return JSONResponse(
            {'error': 'vehicle_analyzer não disponível'},
            status_code=503,
        )

    import os as _os
    if not include_clip:
        _os.environ['GROM_VA_CLIP_ENABLED'] = 'false'

    tmp_path = _save_upload_to_temp(file)
    try:
        result = analyze_vehicle(tmp_path)
        result['filename'] = file.filename
        result['timestamp_utc'] = datetime.now(timezone.utc).isoformat()
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)
    finally:
        if _os.path.exists(tmp_path):
            try:
                _os.remove(tmp_path)
            except (PermissionError, OSError):
                pass
        if not include_clip:
            _os.environ.pop('GROM_VA_CLIP_ENABLED', None)


@app.get("/capabilities")
def capabilities_endpoint():
    """
    Retorna disponibilidade de todos os módulos e backends.

    Útil para health-check expandido e diagnóstico de integração.
    """
    return JSONResponse({
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'super_resolution': get_sr_info(),
        'lprnet': get_lprnet_info(),
        'vehicle_analyzer': get_vehicle_analyzer_info() if _va_ok else {'available': False},
        'geo_context': get_geo_context_info() if _geo_ok else {'available': False},
        'spatial_report': {'available': _spatial_report_ok},
        'scene_report': {'available': _scene_report_ok},
        'frame_selector': {'available': _frame_selector_ok},
        'datasets': datasets_status(),
        'modules': {
            'frame_selector': _frame_selector_ok,
            'super_resolution': _sr_info_ok,
            'lprnet_ocr': _lprnet_info_ok,
            'vehicle_analyzer': _va_ok,
            'geo_context': _geo_ok,
            'spatial_report': _spatial_report_ok,
            'scene_report': _scene_report_ok,
            'datasets_loader': _datasets_loader_ok,
        },
    })


@app.get('/datasets/status')
def datasets_status_endpoint():
    """
    Retorna status direto dos datasets locais e um indicador de prontidão.

    Pronto para etapa final quando:
    - referência brasileira disponível (models.json)
    - sumário BRCars disponível (brcars_summary.json)
    """
    status = datasets_status()
    br_ref_ok = bool(status.get('brazilian_cars_ref', {}).get('available', False))
    brcars_ok = bool(status.get('brcars_summary', {}).get('available', False))
    ready = br_ref_ok and brcars_ok

    return JSONResponse({
        'status': 'ok',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'ready_for_brcars_osint': ready,
        'datasets': status,
        'missing_requirements': [
            req for req, ok in (
                ('brazilian_cars_ref', br_ref_ok),
                ('brcars_summary', brcars_ok),
            ) if not ok
        ],
    })


@app.get('/osint/search')
def osint_search_endpoint(
    make: str = '',
    model: str = '',
    color: str = '',
    year: int = None,
    limit: int = 10,
    query: str = '',
):
    """
    Busca estruturada de candidatos veiculares via OSINTVehicleDatabase.

    Parâmetros:
      make  — marca (ex: toyota, honda)
      model — modelo (ex: corolla, civic)
      color — cor estimada (ex: prata, branco)
      year  — ano estimado
      limit — máximo de resultados (padrão: 10)
      query — texto livre para busca semântica (requer open_clip)

    Retorna candidatos ordenados por score com fonte auditável.
    """
    db = _get_osint_db()
    if db is None:
        return JSONResponse({'status': 'unavailable', 'candidates': [], 'error': 'osint_database nao disponivel'}, status_code=503)

    limit = max(1, min(50, limit))

    try:
        candidates = db.search_by_attributes(
            make=make,
            model=model,
            color=color,
            year=year,
            limit=limit,
        )
    except Exception as exc:
        return JSONResponse({'status': 'error', 'candidates': [], 'error': str(exc)}, status_code=500)

    # Reranking semântico se query fornecida e open_clip disponível
    semantic_applied = False
    if query and is_semantic_search_available():
        ss = _get_semantic_search()
        if ss is not None:
            try:
                candidates = ss.search_query(query, candidates)
                semantic_applied = True
            except Exception:
                pass

    db_status = {}
    try:
        db_status = db.status()
    except Exception:
        pass

    return JSONResponse({
        'status': 'ok',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'query': {'make': make, 'model': model, 'color': color, 'year': year, 'text_query': query},
        'total': len(candidates),
        'semantic_reranking_applied': semantic_applied,
        'candidates': candidates,
        'db_status': db_status,
        'legal_disclaimer': (
            'Resultado probabilistico. Nao substitui identificacao formal por placa '
            'ou confirmacao em bases oficiais.'
        ),
    })


@app.post('/spatial-brief-report')
async def spatial_brief_report_endpoint(payload: dict = Body(default_factory=dict)):
    """
    Gera relatorio breve geoespacial a partir de spatial_context existente.
    """
    if not isinstance(payload, dict):
        payload = {}

    spatial_context = payload.get('spatial_context', {})
    if isinstance(spatial_context, str):
        spatial_context = _parse_json_dict(spatial_context)
    if not isinstance(spatial_context, dict):
        spatial_context = {}

    report = build_spatial_brief_report(
        spatial_context=spatial_context,
        filename=str(payload.get('filename', '') or ''),
        analysis_id=str(payload.get('analysis_id', '') or ''),
    )
    return JSONResponse({'status': 'ok', 'spatial_brief_report': report})


@app.post('/scene-brief-report')
async def scene_brief_report_endpoint(payload: dict = Body(default_factory=dict)):
    """
    Gera analise preliminar da cena a partir de observacoes manuais ou heuristicas.
    """
    if not isinstance(payload, dict):
        payload = {}

    scene_context = payload.get('scene_context', {})
    if isinstance(scene_context, str):
        scene_context = _parse_json_dict(scene_context)
    if not isinstance(scene_context, dict):
        scene_context = {}

    report = build_scene_brief_report(
        scene_context,
        filename=str(payload.get('filename', '') or ''),
        analysis_id=str(payload.get('analysis_id', '') or ''),
        image_quality=_parse_json_dict(payload.get('image_quality')),
        vehicle_analysis=_parse_json_dict(payload.get('vehicle_analysis')),
        spatial_context=_parse_json_dict(payload.get('spatial_context')),
        detections=_parse_json_list(payload.get('detections')),
    )
    return JSONResponse({'status': 'ok', 'scene_brief_report': report})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


def _ensure_vehicle_osint_presence(payload: dict) -> dict:
    """Garante presença do bloco OSINT no payload e no report_context."""
    if not isinstance(payload, dict):
        return payload

    if not isinstance(payload.get('vehicle_osint'), dict) or not payload.get('vehicle_osint'):
        payload['vehicle_osint'] = build_vehicle_osint_report(
            vehicle_analysis=payload.get('vehicle_analysis', {}) if isinstance(payload.get('vehicle_analysis'), dict) else {},
            top_candidates=payload.get('top_candidates', []) if isinstance(payload.get('top_candidates'), list) else [],
            vehicle_info=payload.get('vehicle_info', {}) if isinstance(payload.get('vehicle_info'), dict) else {},
            analysis_id=str(payload.get('forensic', {}).get('analysis_id', '') or ''),
            source_filename=str(payload.get('forensic', {}).get('source_filename', '') or ''),
        )

    report_context = payload.get('report_context', {}) if isinstance(payload.get('report_context'), dict) else {}
    report_context['vehicle_osint'] = payload.get('vehicle_osint', {}) if isinstance(payload.get('vehicle_osint'), dict) else {}
    payload['report_context'] = report_context
    return payload


def _enrich_payload_with_validation(payload: dict, image_path: str) -> dict:
    """Enriquece payload com validação de placa, qualidade e confiança."""

    best_text = _normalize_plate_text(payload.get('best', {}).get('text', ''))
    detections = payload.get('detections', [])

    if isinstance(payload.get('best'), dict):
        payload['best']['text'] = best_text

    # Padroniza candidatos/ocr para formato juridico em caixa alta sem separadores.
    for key in ('top_candidates', 'ocr'):
        if isinstance(payload.get(key), list):
            normalized = []
            seen = set()
            for item in payload[key]:
                if not isinstance(item, dict):
                    continue
                text = _normalize_plate_text(item.get('text', ''))
                if not text:
                    continue
                row = dict(item)
                row['text'] = text
                sig = (text, str(row.get('engine', '')), str(row.get('bbox', '')))
                if sig in seen:
                    continue
                seen.add(sig)
                normalized.append(row)
            payload[key] = normalized

    # Validação de placa
    if best_text:
        validator = PlateValidator(strict_mode=False)
        plate_validation = validator.validate(best_text)
    else:
        plate_validation = {'valid': False, 'score': 0.0, 'issues': ['Sem texto para validar']}

    payload['plate_validation'] = plate_validation

    # Adiciona padrão da placa ao objeto best para compatibilidade com PHP
    if plate_validation.get('pattern'):
        if isinstance(payload.get('best'), dict):
            payload['best']['pattern'] = plate_validation['pattern']

    # Análise de qualidade
    if image_path and os.path.exists(image_path):
        analyzer = ImageQualityAnalyzer()
        image_quality = analyzer.analyze(image_path)
    else:
        image_quality = {
            'overall_quality_score': 0.5,
            'quality_status': 'fallback',
            'error': 'Imagem de referência indisponível para análise',
            'image_path': str(image_path or ''),
        }

    if isinstance(image_quality, dict) and image_quality.get('error'):
        image_quality.setdefault('quality_status', 'fallback')
        payload.setdefault('warnings', []).append('image_quality_fallback')
    else:
        image_quality.setdefault('quality_status', 'ok')

    payload['image_quality'] = image_quality

    # Confidence scoring integrado
    if best_text:
        # Tem OCR válido
        det_confidence = max([d.get('confidence', 0.0) for d in detections]) if detections else 0.3
        ocr_confidence = payload.get('best', {}).get('avg_conf', 0.0)

        scorer = ConfidenceScorer()
        confidence = scorer.calculate(
            det_confidence, ocr_confidence,
            plate_validation, image_quality
        )

        # Ajuste: se não há detecção mas placa é válida, não rejeitar automaticamente
        if not detections and confidence.get('confidence_level') == 'reject':
            if plate_validation.get('valid') and ocr_confidence > 30.0:
                confidence['confidence_level'] = 'medium'
                confidence['recommendation'] = '⚠️ Placa válida mas sem detecção de veículo'
                confidence['requires_review'] = False
    else:
        # Sem OCR válido
        confidence = {
            'overall_confidence': 0.0,
            'confidence_level': 'reject',
            'accept': False,
            'requires_review': False,
            'recommendation': '❌ OCR não disponível',
            'reason': 'Sem resultado de OCR válido',
        }

    payload['confidence_score'] = confidence

    # Contexto espacial forense (GPS EXIF + reverse geocoding), mesmo sem placa.
    try:
        payload['spatial_context'] = analyze_spatial_context(image_path) if image_path else {
            'status': 'no_image_for_spatial_context',
            'gps_extracted': False,
        }
    except Exception:
        payload['spatial_context'] = {
            'status': 'spatial_context_error',
            'gps_extracted': False,
        }

    payload['spatial_brief_report'] = build_spatial_brief_report(
        spatial_context=payload.get('spatial_context', {}),
        filename=str(payload.get('forensic', {}).get('source_filename', '') or ''),
        analysis_id=str(payload.get('forensic', {}).get('analysis_id', '') or ''),
    )

    payload['scene_brief_report'] = build_scene_brief_report(
        payload.get('scene_context', {}) if isinstance(payload.get('scene_context'), dict) else {},
        filename=str(payload.get('forensic', {}).get('source_filename', '') or ''),
        analysis_id=str(payload.get('forensic', {}).get('analysis_id', '') or ''),
        image_quality=payload.get('image_quality', {}) if isinstance(payload.get('image_quality'), dict) else {},
        vehicle_analysis=payload.get('vehicle_analysis', {}) if isinstance(payload.get('vehicle_analysis'), dict) else {},
        spatial_context=payload.get('spatial_context', {}) if isinstance(payload.get('spatial_context'), dict) else {},
        detections=payload.get('detections', []) if isinstance(payload.get('detections'), list) else [],
    )

    payload = _ensure_vehicle_osint_presence(payload)

    # Atualiza assessment baseado em confiança
    conf_level = confidence.get('confidence_level', 'reject')
    payload.setdefault('assessment', {})
    payload['assessment']['confidence_level'] = conf_level
    payload['assessment']['manual_review_required'] = conf_level in ['low', 'reject']
    payload['assessment']['confidence_recommendation'] = confidence.get('recommendation', '')

    # Matriz de prontidão jurídica/pericial para triagem de uso judicial.
    payload['judicial_readiness'] = _compute_judicial_readiness(payload)
    payload['assessment']['judicial_readiness_status'] = payload['judicial_readiness'].get('status', 'nao_apto')
    payload['assessment']['judicial_recommendation'] = payload['judicial_readiness'].get('recommendation', '')
    payload['assessment']['manual_review_required'] = payload['assessment']['manual_review_required'] or (
        payload['judicial_readiness'].get('status', 'nao_apto') != 'apto_prova_preliminar'
    )

    # Gera PDF automaticamente e inclui links de evidencias para front-end/relatorio.
    report_context = payload.get('report_context', {}) if isinstance(payload.get('report_context'), dict) else {}
    report_context['spatial_context'] = payload.get('spatial_context', {}) if isinstance(payload.get('spatial_context'), dict) else {}
    report_context['spatial_brief_report'] = payload.get('spatial_brief_report', {}) if isinstance(payload.get('spatial_brief_report'), dict) else {}
    report_context['scene_brief_report'] = payload.get('scene_brief_report', {}) if isinstance(payload.get('scene_brief_report'), dict) else {}
    report_context['vehicle_analysis'] = payload.get('vehicle_analysis', {}) if isinstance(payload.get('vehicle_analysis'), dict) else {}
    report_context['vehicle_osint'] = payload.get('vehicle_osint', {}) if isinstance(payload.get('vehicle_osint'), dict) else {}
    report_context['judicial_readiness'] = payload.get('judicial_readiness', {}) if isinstance(payload.get('judicial_readiness'), dict) else {}
    report_context['top_candidates'] = payload.get('top_candidates', []) if isinstance(payload.get('top_candidates'), list) else []
    report_context['plate_analyses'] = payload.get('plate_analyses', []) if isinstance(payload.get('plate_analyses'), list) else []
    report_context['ocr_engine_status'] = payload.get('ocr_engine_status', {}) if isinstance(payload.get('ocr_engine_status'), dict) else {}
    report_context['ocr_engine_summary'] = payload.get('ocr_engine_summary', {}) if isinstance(payload.get('ocr_engine_summary'), dict) else {}
    report_context['detection_count'] = len(payload.get('detections', [])) if isinstance(payload.get('detections'), list) else 0
    payload['report_context'] = report_context

    photo_name = report_context.get('photo_filename', '')
    plate_name = report_context.get('plate_filename', '')
    analysis_id = payload.get('forensic', {}).get('analysis_id', '')
    photo_path = _resolve_upload_file(photo_name)
    plate_path = _resolve_upload_file(plate_name)

    if photo_path and plate_path:
        try:
            pdf_name, pdf_success = generate_forensic_pdf(
                photo_path=photo_path,
                plate_path=plate_path,
                recognized_text=best_text,
                analysis_id=str(analysis_id or ''),
                report_context=report_context,
                vehicle_info=payload.get('vehicle_info', {}),
                forensic=payload.get('forensic', {}),
                consensus=payload.get('consensus', {}),
                assessment=payload.get('assessment', {}),
                pericial=payload.get('pericial', {}),
                warnings=payload.get('warnings', []),
                output_dir=UPLOAD_DIR
            )
            payload['pdf_report'] = pdf_name if pdf_success else None
            payload['report_ready'] = pdf_success
            payload.setdefault('report_context', {})
            payload['report_context']['evidence_links'] = {
                'photo': f"/artifact/{photo_name}",
                'plate': f"/artifact/{plate_name}",
                'pdf': f"/pdf/{pdf_name}",
            }

            if pdf_success and _evidence_chain_ok:
                evidence_hashes = {
                    'photo_sha256': sha256_file(photo_path),
                    'plate_sha256': sha256_file(plate_path),
                }

                pdf_path = _resolve_upload_file(pdf_name)
                evidence_hashes['pdf_sha256'] = sha256_file(pdf_path)

                video_ctx = payload.get('video_context', {}) if isinstance(payload.get('video_context'), dict) else {}
                video_sha = str(video_ctx.get('source_video_sha256', '') or '').strip()
                if video_sha:
                    evidence_hashes['video_sha256'] = video_sha
                if photo_path:
                    evidence_hashes['frame_sha256'] = sha256_file(photo_path)

                payload_hash = compute_payload_hash({
                    'analysis_id': payload.get('forensic', {}).get('analysis_id', ''),
                    'best': payload.get('best', {}),
                    'top_candidates': payload.get('top_candidates', []),
                    'assessment': payload.get('assessment', {}),
                    'consensus': payload.get('consensus', {}),
                    'judicial_readiness': payload.get('judicial_readiness', {}),
                    'report_context': payload.get('report_context', {}),
                    'pdf_report': payload.get('pdf_report', ''),
                })

                chain_info = register_evidence_chain_entry(
                    analysis_id=str(payload.get('forensic', {}).get('analysis_id', '') or ''),
                    source_type='video' if video_sha else 'image',
                    evidence_hashes=evidence_hashes,
                    payload_hash=payload_hash,
                )
                if chain_info:
                    payload.setdefault('forensic', {})
                    if isinstance(payload.get('forensic'), dict):
                        payload['forensic']['evidence_chain'] = chain_info
        except Exception:
            payload.setdefault('warnings', []).append('pdf_generation_failed')
    else:
        payload.setdefault('warnings', []).append('evidence_images_missing')

    # Remove duplicidade de chave legada se existir
    payload.pop('ocr_results', None)

    return payload


def _compute_judicial_readiness(payload: dict) -> dict:
    """
    Avalia aptidão técnico-jurídica da evidência para triagem pericial.
    Não substitui cadeia formal de custódia e validação humana.
    """
    confidence = payload.get('confidence_score', {}) if isinstance(payload.get('confidence_score'), dict) else {}
    plate_validation = payload.get('plate_validation', {}) if isinstance(payload.get('plate_validation'), dict) else {}
    consensus = payload.get('consensus', {}) if isinstance(payload.get('consensus'), dict) else {}
    image_quality = payload.get('image_quality', {}) if isinstance(payload.get('image_quality'), dict) else {}
    forensic = payload.get('forensic', {}) if isinstance(payload.get('forensic'), dict) else {}
    best = payload.get('best', {}) if isinstance(payload.get('best'), dict) else {}

    policy = _load_judicial_policy()
    thresholds = policy.get('thresholds', {}) if isinstance(policy.get('thresholds'), dict) else {}

    conf_min = float(thresholds.get('confidence_min', 0.75) or 0.75)
    consensus_min = float(thresholds.get('consensus_ratio_min', 50.0) or 50.0)
    quality_min = float(thresholds.get('image_quality_min', 0.60) or 0.60)

    conf_score = float(confidence.get('overall_confidence', 0.0) or 0.0)
    conf_level = str(confidence.get('confidence_level', 'reject') or 'reject')
    plate_valid = bool(plate_validation.get('valid', False))
    agreement_ratio = float(consensus.get('agreement_ratio', 0.0) or 0.0)
    img_quality_score = float(image_quality.get('overall_quality_score', 0.0) or 0.0)
    has_analysis_id = bool(str(forensic.get('analysis_id', '') or '').strip())
    has_timestamp = bool(str(forensic.get('generated_at_utc', '') or '').strip())
    has_best_text = bool(str(best.get('text', '') or '').strip())

    blockers = []
    cautions = []

    if not has_best_text:
        blockers.append('Sem leitura OCR consolidada da placa')
    if not has_analysis_id or not has_timestamp:
        blockers.append('Metadados forenses incompletos (analysis_id/timestamp)')
    if conf_level in ('reject', 'low') or conf_score < conf_min:
        cautions.append(f'Confianca global abaixo do limiar pericial recomendado ({conf_min:.2f})')
    if not plate_valid:
        cautions.append('Padrao de placa nao validado automaticamente')
    if agreement_ratio < consensus_min:
        cautions.append('Baixo consenso entre motores OCR')
    if img_quality_score < quality_min:
        cautions.append('Qualidade de imagem abaixo do ideal para uso judicial')

    if blockers:
        status = 'nao_apto'
        recommendation = 'Nao apto para uso judicial sem nova coleta/prova complementar e revisao tecnica.'
    elif cautions:
        status = 'apto_com_revisao'
        recommendation = 'Apto com revisao pericial obrigatoria e correlacao com outras evidencias independentes.'
    else:
        status = 'apto_prova_preliminar'
        recommendation = 'Apto para uso preliminar em dossie tecnico, mantendo revisao humana e cadeia de custodia formal.'

    return {
        'status': status,
        'recommendation': recommendation,
        'confidence_score': round(conf_score, 4),
        'consensus_ratio': round(agreement_ratio, 2),
        'image_quality_score': round(img_quality_score, 4),
        'thresholds_applied': {
            'confidence_min': conf_min,
            'consensus_ratio_min': consensus_min,
            'image_quality_min': quality_min,
        },
        'plate_pattern_valid': plate_valid,
        'blockers': blockers,
        'cautions': cautions,
        'legal_notes': [
            'Resultado automatizado exige revisao pericial humana para fins judiciais.',
            'Evidencia digital deve ser acompanhada de cadeia de custodia formal e integridade verificavel.',
            'Recomenda-se correlacao com provas independentes (CFTV, metadata, testemunhos, telemetria).',
        ],
    }


_JUDICIAL_POLICY_CACHE = None


def _load_judicial_policy() -> dict:
    global _JUDICIAL_POLICY_CACHE
    if isinstance(_JUDICIAL_POLICY_CACHE, dict):
        return _JUDICIAL_POLICY_CACHE

    default_policy = {
        'thresholds': {
            'confidence_min': 0.75,
            'consensus_ratio_min': 50.0,
            'image_quality_min': 0.60,
        }
    }

    policy_path = os.path.join(PROJECT_ROOT, 'data', 'judicial_threshold_policy.json')
    if not os.path.exists(policy_path):
        _JUDICIAL_POLICY_CACHE = default_policy
        return _JUDICIAL_POLICY_CACHE

    try:
        with open(policy_path, 'r', encoding='utf-8') as stream:
            loaded = json.load(stream)
        if isinstance(loaded, dict):
            _JUDICIAL_POLICY_CACHE = loaded
            return _JUDICIAL_POLICY_CACHE
    except Exception:
        pass

    _JUDICIAL_POLICY_CACHE = default_policy
    return _JUDICIAL_POLICY_CACHE
