
from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.responses import JSONResponse, FileResponse
from typing import List
import uvicorn
import os
import tempfile
import shutil
import re
from datetime import datetime, timezone
from uuid import uuid4
from fastapi_backend.preprocessing import preprocess_image
from fastapi_backend.detector_module import detect_plate
from fastapi_backend.ensemble_detector import detect_ensemble
from fastapi_backend.onnx_detector import get_onnx_detector
from fastapi_backend.onnx_exporter import export_to_onnx, get_export_info
from fastapi_backend.benchmark_onnx import run_benchmark, format_report
from fastapi_backend.ocr_module import run_ocr, get_last_ocr_runtime_info
from PIL import Image
from fpdf import FPDF
from fastapi_backend.plate_validator import PlateValidator
from fastapi_backend.quality_metrics import ImageQualityAnalyzer
from fastapi_backend.confidence_scorer import ConfidenceScorer

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

app = FastAPI(title="Grom OCR Backend", description="API para detecção e leitura de placas veiculares com IA pericial.")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
UPLOAD_DIR = os.getenv('GROM_OCR_UPLOAD_DIR') or os.path.join(tempfile.gettempdir(), 'grom_ocr_uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

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


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]', '_', str(name or '').strip())
    cleaned = cleaned.strip('._')
    return cleaned or 'upload.jpg'


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
    safe_name = _sanitize_filename(filename or '')
    if not safe_name:
        return None
    path = os.path.join(UPLOAD_DIR, safe_name)
    if not os.path.exists(path):
        return None
    return path


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


def _generate_pdf_report(photo_path: str, plate_path: str, recognized_text: str, analysis_id: str, report_context: dict, vehicle_info: dict, forensic: dict, consensus: dict, assessment: dict, pericial: dict, warnings: list):
    source_name = os.path.basename(photo_path or 'report.jpg')
    pdf_name = _build_unique_artifact_filename(source_name, analysis_id, prefix='relatorio_', default_extension='.pdf', force_extension=True)
    pdf_path = os.path.join(UPLOAD_DIR, pdf_name)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'Relatorio Tecnico - Grom OCR', ln=True)

    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, f'Analise: {analysis_id or "-"}', ln=True)
    pdf.cell(0, 7, f'Gerado UTC: {datetime.now(timezone.utc).isoformat()}', ln=True)
    pdf.cell(0, 7, f'Arquivo fonte: {os.path.basename(photo_path)}', ln=True)
    pdf.cell(0, 7, f'Placa reconhecida: {(recognized_text or "").strip() or "Nao reconhecida"}', ln=True)
    pdf.ln(2)

    if isinstance(vehicle_info, dict) and vehicle_info:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'Informacoes veiculares', ln=True)
        pdf.set_font('Arial', '', 10)
        for key in ('placa', 'fabricante', 'modelo', 'ano', 'cor', 'fonte'):
            value = str(vehicle_info.get(key, '') or '').strip()
            if value:
                pdf.cell(0, 6, f'{key}: {value}', ln=True)
        pdf.ln(1)

    if isinstance(forensic, dict) and forensic:
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'Forense', ln=True)
        pdf.set_font('Arial', '', 10)
        for key in ('analysis_id', 'source_filename', 'generated_at_utc', 'signature'):
            value = str(forensic.get(key, '') or '').strip()
            if value:
                pdf.cell(0, 6, f'{key}: {value}', ln=True)
        pdf.ln(1)

    if isinstance(consensus, dict) and consensus:
        pdf.cell(0, 6, f"Consenso: {consensus.get('agreement_ratio', 0)}", ln=True)
    if isinstance(assessment, dict) and assessment:
        pdf.cell(0, 6, f"Nivel de evidencia: {assessment.get('evidence_level', '-')}", ln=True)
    if isinstance(pericial, dict) and pericial:
        pdf.cell(0, 6, f"Status pericial: {pericial.get('status', '-')}", ln=True)

    if isinstance(warnings, list) and warnings:
        pdf.ln(2)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 8, 'Alertas', ln=True)
        pdf.set_font('Arial', '', 10)
        for warning in warnings[:12]:
            pdf.multi_cell(0, 6, f'- {str(warning)}')

    pdf.add_page()
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'Evidencias visuais', ln=True)
    pdf.ln(2)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, 'Foto original', ln=True)
    try:
        pdf.image(photo_path, x=10, y=35, w=180)
    except Exception:
        pdf.cell(0, 6, 'Nao foi possivel incorporar foto original no PDF.', ln=True)

    pdf.ln(105)
    pdf.cell(0, 6, 'Recorte da placa', ln=True)
    try:
        pdf.image(plate_path, x=10, y=150, w=120)
    except Exception:
        pdf.cell(0, 6, 'Nao foi possivel incorporar recorte da placa no PDF.', ln=True)

    pdf.output(pdf_path)
    return pdf_name


def _build_process_payload(filename: str, detections: list, ocr_results: list, analysis_stage: str, analysis_id: str, photo_filename: str, plate_filename: str, crop_raw_filename: str, ocr_runtime_info: dict = None, ocr_runtime_events: list = None):
    ocr_runtime_info = ocr_runtime_info or {}
    ocr_runtime_events = ocr_runtime_events or []
    normalized_candidates = []
    for idx, item in enumerate(ocr_results):
        text = str(item.get('text', '')).strip()
        if text == '':
            continue
        confidence = float(item.get('confidence', 0))
        normalized_candidates.append({
            'rank': idx + 1,
            'text': text,
            'engine': str(item.get('engine', 'ocr')),
            'avg_conf': confidence,
            'score': confidence,
            'support_count': 1,
            'agreement_ratio': 100.0,
            'weighted_support': confidence,
            'region': 'BR',
        })

    best = normalized_candidates[0] if normalized_candidates else {
        'text': '',
        'engine': 'none',
        'avg_conf': 0.0,
        'score': 0.0,
    }

    warnings = []
    if not normalized_candidates:
        warnings.append('ocr_sem_resultado')

    has_paddle_results = any(c.get('engine') == 'paddleocr' for c in ocr_results)
    has_tesseract_results = any(c.get('engine') == 'tesseract' for c in ocr_results)
    selected_engine = str(ocr_runtime_info.get('selected_engine', '') or '').strip().lower()
    paddle_error = str(ocr_runtime_info.get('paddle_error', '') or '').strip()
    paddle_disabled = bool(ocr_runtime_info.get('paddle_disabled', False))

    paddle_status = 'executed' if (has_paddle_results or selected_engine == 'paddleocr') else 'skipped'
    if paddle_disabled:
        paddle_status = 'disabled'
    elif paddle_error:
        paddle_status = 'failed'

    tesseract_status = 'executed' if (has_tesseract_results or selected_engine == 'tesseract') else 'skipped'

    engines_executed = sorted(list({str(c.get('engine', 'unknown')) for c in ocr_results if str(c.get('engine', '')).strip()}))
    if selected_engine and selected_engine not in engines_executed:
        engines_executed.append(selected_engine)
        engines_executed = sorted(engines_executed)

    fallback_used = bool(ocr_runtime_info.get('fallback_used', False)) or any(
        bool((event or {}).get('fallback_used', False)) for event in ocr_runtime_events
    )

    return {
        'best': best,
        'top_candidates': normalized_candidates,
        'ocr': ocr_results,
        'ocr_engine_status': {
            'paddleocr': {'status': paddle_status, 'error': paddle_error},
            'tesseract': {'status': tesseract_status},
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
        },
        'pdf_report': '',
        'assessment': {
            'manual_review_required': best.get('text', '') == '',
            'evidence_level': 'MEDIA' if best.get('text', '') else 'BAIXA',
        },
        'consensus': {
            'agreement_ratio': 100.0 if best.get('text', '') else 0.0,
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
    }

@app.post("/detect-plate/")
async def detect_plate_endpoint(file: UploadFile = File(...)):
    tmp_path = _save_upload_to_temp(file)
    preprocess_image(tmp_path).save(tmp_path)
    detections = detect_plate(tmp_path)
    os.remove(tmp_path)
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
        os.remove(tmp_path)
        return JSONResponse(status_code=503, content={
            "filename": file.filename,
            "error": str(exc)
        })
    os.remove(tmp_path)
    return JSONResponse({
        "filename": file.filename,
        "ocr_results": ocr_results,
        "ocr_runtime": get_last_ocr_runtime_info(),
    })

@app.post("/full-pipeline/")
async def full_pipeline(file: UploadFile = File(...)):
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
            ocr = run_ocr(crop_path)
            ocr_runtime_events.append(get_last_ocr_runtime_info())
        except RuntimeError as exc:
            os.remove(crop_path)
            os.remove(tmp_path)
            return JSONResponse(status_code=503, content={
                "filename": file.filename,
                "error": str(exc)
            })
        ocr_results.append({"bbox": det['bbox'], "ocr": ocr})
        os.remove(crop_path)
    os.remove(tmp_path)
    return JSONResponse({
        "filename": file.filename,
        "detections": detections,
        "ocr_results": ocr_results,
        "ocr_runtime_events": ocr_runtime_events,
    })


@app.post("/process")
async def process_legacy_endpoint(
    image: UploadFile = File(None),
    file: UploadFile = File(None),
    analysis_stage: str = Form('final')
):
    upload = image or file
    if upload is None:
        return JSONResponse(status_code=400, content={'error': 'campo image ou file e obrigatorio'})

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
        detections = detect_plate(tmp_path)

        ocr_results = []
        ocr_runtime_events = []
        img = Image.open(tmp_path)
        if detections:
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                crop = img.crop((x1, y1, x2, y2))
                crop_path = tmp_path + '_crop.jpg'
                crop.save(crop_path)
                if not os.path.exists(persisted_crop_raw_path):
                    shutil.copy2(crop_path, persisted_crop_raw_path)
                if not os.path.exists(persisted_plate_path):
                    shutil.copy2(crop_path, persisted_plate_path)
                try:
                    ocr_results.extend(run_ocr(crop_path))
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
        )

        # Enriquece com validação, qualidade e confiança
        payload = _enrich_payload_with_validation(payload, persisted_photo_path)

        return JSONResponse(payload)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/process-ensemble")
async def process_ensemble_endpoint(
    upload: UploadFile = File(...),
    analysis_stage: str = Form(default='investigacao'),
):
    """
    Endpoint de detecção em ensemble (Phase 3).
    Usa detect_ensemble() que encadeia YOLO + fallback por contornos com NMS.
    Retorna o mesmo payload do /process com campo extra 'ensemble_info'.
    """
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

        # Ensemble detection
        detections = detect_ensemble(tmp_path)
        sources = list({d.get('source', 'unknown') for d in detections})

        ocr_results = []
        ocr_runtime_events = []
        img = Image.open(tmp_path)
        if detections:
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                crop = img.crop((x1, y1, x2, y2))
                crop_path = tmp_path + '_crop.jpg'
                crop.save(crop_path)
                if not os.path.exists(persisted_crop_raw_path):
                    shutil.copy2(crop_path, persisted_crop_raw_path)
                if not os.path.exists(persisted_plate_path):
                    shutil.copy2(crop_path, persisted_plate_path)
                try:
                    ocr_results.extend(run_ocr(crop_path))
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
        )

        payload = _enrich_payload_with_validation(payload, persisted_photo_path)

        payload['ensemble_info'] = {
            'detector_sources': sources,
            'total_raw_detections': len(detections),
            'fallback_activated': 'contour' in sources,
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
            os.remove(tmp_path)


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
            os.remove(tmp_path)


@app.post("/enrich_report")
async def enrich_report_legacy_endpoint(payload: dict = Body(default_factory=dict)):
    if not isinstance(payload, dict):
        payload = {}

    report_context = payload.get('report_context', {})
    if isinstance(report_context, str):
        report_context = _parse_json_dict(report_context)
    if not isinstance(report_context, dict):
        report_context = {}

    photo_filename = report_context.get('photo_filename') or payload.get('photo_filename')
    plate_filename = report_context.get('plate_filename') or payload.get('plate_filename')
    analysis_id = str(report_context.get('analysis_id') or payload.get('analysis_id') or uuid4())
    ocr_text = str(payload.get('ocr_text', '') or '')
    origem = str(payload.get('origem', 'web') or 'web')

    vehicle_info = _parse_json_dict(payload.get('vehicle_info'))
    forensic = _parse_json_dict(payload.get('forensic') or report_context.get('forensic'))
    consensus = _parse_json_dict(payload.get('consensus') or report_context.get('consensus'))
    assessment = _parse_json_dict(payload.get('assessment') or report_context.get('assessment'))
    pericial = _parse_json_dict(payload.get('pericial') or report_context.get('pericial'))
    warnings = _parse_json_list(payload.get('warnings'))

    if analysis_id and not forensic.get('analysis_id'):
        forensic['analysis_id'] = analysis_id

    photo_path = _resolve_upload_file(str(photo_filename or ''))
    plate_path = _resolve_upload_file(str(plate_filename or ''))
    if not photo_path or not plate_path:
        return JSONResponse(status_code=404, content={'error': 'Arquivos de contexto do relatorio nao encontrados'})

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


@app.post("/process_video")
async def process_video_legacy_endpoint():
    return JSONResponse(status_code=501, content={
        'error': 'process_video nao implementado no fastapi_backend'
    })


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

    Retorna:
      JSON com 'mode', 'frames_received', 'sharpness_scores'
      e 'selected_index' (mode=best) ou 'hdr_mean_brightness' (mode=hdr).
      O arquivo resultante é salvo como artifact e o nome retornado em 'artifact'.
    """
    if not _frame_selector_ok:
        return JSONResponse(
            {'error': 'frame_selector não disponível'},
            status_code=503,
        )

    if not files:
        return JSONResponse({'error': 'Nenhum arquivo enviado.'}, status_code=400)

    import cv2
    import numpy as np

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

    Este endpoint é isolado do pipeline /process — não afeta latência
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
            _os.remove(tmp_path)
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
        'frame_selector': {'available': _frame_selector_ok},
        'modules': {
            'frame_selector': _frame_selector_ok,
            'super_resolution': _sr_info_ok,
            'lprnet_ocr': _lprnet_info_ok,
            'vehicle_analyzer': _va_ok,
        },
    })


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


def _enrich_payload_with_validation(payload: dict, image_path: str) -> dict:
    """Enriquece payload com validação de placa, qualidade e confiança."""

    best_text = payload.get('best', {}).get('text', '').strip()
    detections = payload.get('detections', [])

    # Validação de placa
    if best_text:
        validator = PlateValidator(strict_mode=False)
        plate_validation = validator.validate(best_text)
    else:
        plate_validation = {'valid': False, 'score': 0.0, 'issues': ['Sem texto para validar']}

    payload['plate_validation'] = plate_validation

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
    if detections and best_text:
        det_confidence = max([d.get('confidence', 0.0) for d in detections])
        ocr_confidence = payload.get('best', {}).get('avg_conf', 0.0)

        scorer = ConfidenceScorer()
        confidence = scorer.calculate(
            det_confidence, ocr_confidence,
            plate_validation, image_quality
        )
    else:
        # Sem detecção ou OCR
        confidence = {
            'overall_confidence': 0.0,
            'confidence_level': 'reject',
            'accept': False,
            'requires_review': False,
            'recommendation': '❌ Sem detecção ou OCR válido',
            'reason': 'Resultado incompleto',
        }

    payload['confidence_score'] = confidence

    # Atualiza assessment baseado em confiança
    conf_level = confidence.get('confidence_level', 'reject')
    payload['assessment']['confidence_level'] = conf_level
    payload['assessment']['manual_review_required'] = conf_level in ['low', 'reject']
    payload['assessment']['confidence_recommendation'] = confidence.get('recommendation', '')

    return payload
