from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from utils.video_session import normalize_video_target_entry
except Exception:
    normalize_video_target_entry = None


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _safe_text(value, fallback='-'):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _safe_float(value, default=0.0):
    try:
        if value is None or value == '':
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        if value is None or value == '':
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_component(value):
    text = re.sub(r'[^A-Za-z0-9._-]+', '_', _safe_text(value, ''))
    return text.strip('._-') or 'manifest'


def _format_size(size_bytes):
    size_bytes = _safe_int(size_bytes, 0)
    if size_bytes <= 0:
        return '0.00 MB'
    return f'{size_bytes / (1024 * 1024):0.2f} MB'


def _format_resolution(value):
    value = _as_dict(value)
    width = _safe_int(value.get('width', value.get('w', 0)), 0)
    height = _safe_int(value.get('height', value.get('h', 0)), 0)
    if width <= 0 or height <= 0:
        return 'Indisponível'
    return f'{width}x{height} px'


def _format_duration(value):
    seconds = _safe_float(value, 0.0)
    if seconds <= 0:
        return 'Indisponível'
    if seconds >= 60.0:
        minutes = seconds / 60.0
        return f'{minutes:0.2f} min'
    return f'{seconds:0.2f} s'


def _sha256_file(filepath):
    if not filepath or not os.path.isfile(filepath):
        return ''

    digest = hashlib.sha256()
    try:
        with open(filepath, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    except Exception:
        return ''
    return digest.hexdigest()


def _file_stat(filepath):
    if not filepath or not os.path.isfile(filepath):
        return {}

    try:
        stat = os.stat(filepath)
    except Exception:
        return {}

    return {
        'exists': True,
        'path': os.path.abspath(filepath),
        'filename': os.path.basename(filepath),
        'size_bytes': int(stat.st_size),
        'size_text': _format_size(stat.st_size),
        'modified_utc': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        'sha256': _sha256_file(filepath),
    }


def _image_dimensions(filepath):
    if not filepath or not os.path.isfile(filepath) or Image is None:
        return {}

    try:
        with Image.open(filepath) as source:
            width, height = source.size
    except Exception:
        return {}

    if width <= 0 or height <= 0:
        return {}
    return {'width': int(width), 'height': int(height)}


def _resolve_path(report_data, *keys):
    for key in keys:
        value = report_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _choose_source_path(report_data, input_meta, analysis_kind):
    kind = _safe_text(analysis_kind, '').lower()
    candidates = []

    if kind.startswith('video'):
        candidates.extend([
            report_data.get('video_path'),
            input_meta.get('source_path'),
            input_meta.get('video_path'),
            report_data.get('photo_path'),
            report_data.get('original_path'),
        ])
    else:
        candidates.extend([
            report_data.get('original_path'),
            report_data.get('photo_path'),
            report_data.get('foto_path'),
            input_meta.get('source_path'),
            input_meta.get('photo_path'),
            input_meta.get('video_path'),
            report_data.get('video_path'),
        ])

    for candidate in candidates:
        text = _safe_text(candidate, '')
        if text:
            return text
    return ''


def _summarize_target(target):
    target = _as_dict(target)
    if not target and normalize_video_target_entry is not None:
        try:
            target = normalize_video_target_entry(target)
        except Exception:
            target = {}

    best_frame = _as_dict(target.get('best_frame'))
    timestamp_seconds = _safe_float(target.get('timestamp_seconds', best_frame.get('timestamp_seconds', 0.0)), 0.0)
    minute_label = _safe_text(target.get('minute_label'), '')
    minute_range = _safe_text(target.get('minute_range'), '')
    label = _safe_text(target.get('display_label'), _safe_text(target.get('label'), 'Alvo'))
    text = _safe_text(target.get('text') or best_frame.get('ocr'), 'Indefinido')

    summary = {
        'candidate_id': _safe_text(target.get('candidate_id'), ''),
        'label': label,
        'text': text,
        'pattern': _safe_text(target.get('pattern') or best_frame.get('pattern'), 'Indefinido'),
        'timestamp_seconds': round(timestamp_seconds, 4),
        'timestamp_label': _safe_text(target.get('timestamp_label'), _format_duration(timestamp_seconds)),
        'minute_label': minute_label,
        'minute_range': minute_range,
        'frames_count': _safe_int(target.get('frames_count'), 0),
        'best_confidence': round(_safe_float(target.get('best_confidence'), target.get('avg_confidence', 0.0)), 1),
        'best_score': round(_safe_float(target.get('best_score'), target.get('avg_score', 0.0)), 1),
    }

    if not summary['minute_label'] and minute_range:
        summary['minute_label'] = minute_range

    return summary


def _build_artifact_record(role, label, path):
    path_text = _safe_text(path, '')
    if not path_text:
        return {}

    stat = _file_stat(path_text)
    if not stat:
        return {}

    dims = _image_dimensions(path_text)
    if dims:
        stat['resolution'] = dims
        stat['resolution_text'] = _format_resolution(dims)

    stat.update({
        'role': _safe_text(role, 'derived'),
        'label': _safe_text(label, role),
    })
    return stat


def _candidate_summary_text(targets):
    items = []
    for target in _as_list(targets):
        summary = _summarize_target(target)
        label = summary.get('label', '')
        text = summary.get('text', '')
        minute = summary.get('minute_label') or summary.get('timestamp_label') or ''
        if text and minute:
            items.append(f'{label} [{text}] @ {minute}')
        elif text:
            items.append(f'{label} [{text}]')
        elif label:
            items.append(label)
    return '; '.join(items) if items else 'Indisponível'


def _build_processing_snapshot(report_data, input_meta, analysis_kind):
    scene_preprocess = _as_dict(report_data.get('scene_preprocess') or input_meta.get('scene_preprocess') or input_meta.get('visual_scene_preprocess'))
    plate_detection = _as_dict(report_data.get('plate_detection') or input_meta.get('plate_detection'))
    consensus = _as_dict(report_data.get('consensus') or input_meta.get('consensus'))
    best_result = _as_dict(report_data.get('best_result') or report_data.get('best_payload') or input_meta.get('best_result'))
    human_review = _as_dict(report_data.get('human_review') or input_meta.get('human_review'))
    assessment = _as_dict(report_data.get('assessment') or input_meta.get('assessment'))
    frame_sampling = _as_dict(report_data.get('frame_sampling') or input_meta.get('frame_sampling'))
    video_metadata = _as_dict(report_data.get('video_metadata') or input_meta.get('video_metadata'))

    processing = {
        'scene_preprocess': {},
        'plate_detection': {},
        'ocr': {},
        'human_review': {},
    }

    if scene_preprocess:
        processing['scene_preprocess'] = {
            'selected': _safe_text(scene_preprocess.get('selected'), ''),
            'selected_family': _safe_text(scene_preprocess.get('selected_family'), ''),
            'selected_variant': _safe_text(scene_preprocess.get('selected_variant'), ''),
            'selection_reason': _safe_text(scene_preprocess.get('selection_reason'), ''),
            'quality_before': _as_dict(scene_preprocess.get('quality_before')),
            'quality_after': _as_dict(scene_preprocess.get('quality_after')),
        }

    if plate_detection:
        processing['plate_detection'] = {
            'status': _safe_text(plate_detection.get('status'), 'indefinido'),
            'strategy': _safe_text(plate_detection.get('strategy'), 'plate_roi_first'),
            'candidate_count': _safe_int(plate_detection.get('candidate_count'), 0),
            'selected_region': _safe_text(plate_detection.get('selected_region'), ''),
            'selected_source': _safe_text(plate_detection.get('selected_source'), ''),
            'ocr_selected_region': _safe_text(plate_detection.get('ocr_selected_region'), ''),
            'ocr_selected_source': _safe_text(plate_detection.get('ocr_selected_source'), ''),
            'selected_raw_path': _safe_text(
                report_data.get('crop_raw_path')
                or input_meta.get('crop_raw_path')
                or plate_detection.get('selected_raw_path'),
                '',
            ),
            'selected_treated_path': _safe_text(
                report_data.get('crop_treated_path')
                or input_meta.get('crop_treated_path')
                or plate_detection.get('selected_treated_path')
                or report_data.get('plate_path'),
                '',
            ),
            'selected_quality_score': round(_safe_float(plate_detection.get('selected_quality_score'), 0.0), 1),
            'selected_score': round(_safe_float(plate_detection.get('selected_score'), 0.0), 1),
            'selected_style_hint': _safe_text(
                plate_detection.get('selected_style_hint')
                or plate_detection.get('ocr_selected_style_hint')
                or plate_detection.get('style_hint'),
                'indefinida',
            ),
            'selected_style_confidence': round(_safe_float(
                plate_detection.get('selected_style_confidence')
                or plate_detection.get('ocr_selected_style_confidence')
                or plate_detection.get('style_confidence'),
                0.0,
            ), 1),
        }

    if best_result:
        processing['ocr'] = {
            'text': _safe_text(best_result.get('text'), ''),
            'pattern': _safe_text(best_result.get('pattern'), 'Indefinido'),
            'avg_conf': round(_safe_float(best_result.get('avg_conf'), 0.0), 1),
            'score': round(_safe_float(best_result.get('score'), 0.0), 1),
            'consensus_ratio': round(_safe_float(consensus.get('agreement_ratio', consensus.get('consensus_ratio', 0.0)), 0.0), 1),
            'engines_considered': _safe_int(consensus.get('engines_considered', consensus.get('total_engines', 0)), 0),
        }

    if human_review:
        processing['human_review'] = {
            'status': _safe_text(human_review.get('status'), _safe_text(human_review.get('decision'), 'pendente')),
            'decision': _safe_text(human_review.get('decision'), ''),
            'decision_label': _safe_text(human_review.get('decision_label'), ''),
            'confirmed_text': _safe_text(human_review.get('confirmed_text'), ''),
            'notes': _safe_text(human_review.get('notes'), ''),
        }

    if _safe_text(analysis_kind, '').lower().startswith('video') or video_metadata:
        processing['frame_sampling'] = {
            'strategy': _safe_text(frame_sampling.get('strategy'), 'frame_by_frame_scan'),
            'coverage_label': _safe_text(frame_sampling.get('coverage_label'), 'Indefinido'),
            'scan_interval_seconds': round(_safe_float(frame_sampling.get('scan_interval_seconds'), 0.0), 4),
            'selected_frame_count': _safe_int(frame_sampling.get('selected_frame_count'), 0),
            'frame_count_total': _safe_int(frame_sampling.get('frame_count_total'), _safe_int(video_metadata.get('frame_count'), 0)),
        }

    return processing


def _build_source_snapshot(report_data, input_meta, analysis_kind):
    source_path = _choose_source_path(report_data, input_meta, analysis_kind)
    source_stat = _file_stat(source_path)
    source_resolution = _as_dict(
        report_data.get('source_resolution')
        or input_meta.get('source_resolution')
        or input_meta.get('resolution')
    )
    video_metadata = _as_dict(report_data.get('video_metadata') or input_meta.get('video_metadata'))
    capture_metadata = _as_dict(report_data.get('metadata') or input_meta.get('capture_metadata'))
    input_security = _as_dict(input_meta.get('input_security') or report_data.get('input_security'))
    frame_context = _as_dict(input_meta.get('video_context') or report_data.get('frame_context'))
    family = 'video' if _safe_text(analysis_kind, '').lower().startswith('video') or video_metadata else 'image'

    source = dict(source_stat)
    source.update({
        'family': family,
        'analysis_kind': _safe_text(analysis_kind, family),
        'input_type': _safe_text(input_meta.get('input_type'), family),
        'mime_type': _safe_text(input_meta.get('content_type') or input_meta.get('detected_mime') or input_meta.get('mime_type'), ''),
        'signature': _safe_text(input_security.get('detected_signature') or input_meta.get('detected_signature'), ''),
        'signature_ok': bool(input_security.get('signature_ok', True)),
        'camera': _safe_text(capture_metadata.get('camera') or input_meta.get('camera'), ''),
        'timestamp_utc': _safe_text(capture_metadata.get('timestamp') or input_meta.get('timestamp') or input_meta.get('capture_timestamp_utc'), ''),
        'source_resolution': source_resolution,
        'source_resolution_text': _format_resolution(source_resolution),
        'exif_present': bool(input_meta.get('exif') or capture_metadata.get('exif_present')),
        'duration_seconds': _safe_float(video_metadata.get('duration_seconds', 0.0), 0.0) if family == 'video' else 0.0,
        'duration_text': _format_duration(video_metadata.get('duration_seconds', 0.0)) if family == 'video' else 'Indisponível',
        'fps': round(_safe_float(video_metadata.get('fps', 0.0), 0.0), 4) if family == 'video' else 0.0,
        'frame_count': _safe_int(video_metadata.get('frame_count', 0), 0) if family == 'video' else 0,
        'codec': _safe_text(video_metadata.get('codec_fourcc') or video_metadata.get('codec_hint'), '') if family == 'video' else '',
        'frame_context': frame_context if frame_context else {},
        'input_security': {
            'status': _safe_text(input_security.get('status'), ''),
            'detected_signature': _safe_text(input_security.get('detected_signature'), ''),
            'detected_mime': _safe_text(input_security.get('detected_mime'), ''),
            'policy': _safe_text(input_security.get('policy'), ''),
            'warnings': _as_list(input_security.get('warnings')),
        } if input_security else {},
    })
    return source


def _build_artifacts(report_data, source_path, analysis_kind):
    input_meta = _as_dict(report_data.get('input_meta'))
    artifacts = []
    seen = set()

    candidate_paths = [
        ('crop_raw_path', 'Recorte bruto da placa'),
        ('crop_treated_path', 'Recorte tratado da placa'),
        ('plate_path', 'Recorte principal da placa'),
        ('comparison_sheet_path', 'Comparativo documental'),
        ('contact_sheet_path', 'Quadros-chave'),
        ('scan_record_path', 'Registro de varredura'),
        ('report_path', 'Relatório consolidado'),
    ]

    if _safe_text(analysis_kind, '').lower().startswith('video'):
        candidate_paths.extend([
            ('selected_targets_sheet_path', 'Alvos selecionados'),
            ('final_report_path', 'Relatório final consolidado'),
        ])
    else:
        candidate_paths.extend([
            ('pdf_report_path', 'Relatório documental'),
        ])

    for key, label in candidate_paths:
        path = _resolve_path(report_data, key)
        if not path:
            path = _resolve_path(input_meta, key)
        if not path:
            continue
        abs_path = os.path.abspath(path) if os.path.exists(path) else path
        if abs_path in seen:
            continue
        record = _build_artifact_record(key, label, path)
        if record:
            artifacts.append(record)
            seen.add(record.get('path', abs_path))

    # Keep the source out of the derived list, but record its existence in the manifest source block.
    return artifacts


def _build_custody_steps(report_data, analysis_kind, analysis_stage, source_exists, derived_count, review_required):
    input_meta = _as_dict(report_data.get('input_meta'))
    family = 'video' if _safe_text(analysis_kind, '').lower().startswith('video') else 'image'
    steps = [
        {
            'order': 1,
            'label': 'Entrada preservada',
            'status': 'registrada' if source_exists else 'indisponivel',
            'detail': 'A fonte original foi mantida sem substituicao.',
        },
        {
            'order': 2,
            'label': 'Tratamento tecnico',
            'status': 'aplicado' if derived_count > 0 else 'pendente',
            'detail': 'Derivativos periciais gerados sem tocar no arquivo-fonte.',
        },
    ]

    if family == 'video':
        steps.append({
            'order': 3,
            'label': 'Varredura frame a frame',
            'status': 'executada' if _safe_int(_as_dict(report_data.get('frame_sampling')).get('selected_frame_count'), 0) > 0 else 'pendente',
            'detail': 'Quadros distribuidos ao longo da linha temporal.',
        })
        steps.append({
            'order': 4,
            'label': 'Selecao do operador',
            'status': 'registrada' if _as_list(report_data.get('selected_targets')) else 'automatica',
            'detail': 'Alvos marcados pelo operador para consolidacao documental.',
        })
        steps.append({
            'order': 5,
            'label': 'OCR e consenso',
            'status': 'executado' if _as_dict(report_data.get('consensus')) else 'pendente',
            'detail': 'Leitura consolidada com registro de ambiguidade.',
        })
        steps.append({
            'order': 6,
            'label': 'Conferencia humana',
            'status': 'obrigatoria' if review_required else 'registrada',
            'detail': 'Conferencia antes da liberacao documental.',
        })
    else:
        steps.append({
            'order': 3,
            'label': 'Recorte bruto',
            'status': 'registrado' if _safe_text(report_data.get('crop_raw_path') or input_meta.get('crop_raw_path')) else 'indisponivel',
            'detail': 'Recorte inicial documentado para comparacao.',
        })
        steps.append({
            'order': 4,
            'label': 'Recorte tratado',
            'status': 'registrado' if _safe_text(report_data.get('crop_treated_path') or input_meta.get('crop_treated_path')) else 'indisponivel',
            'detail': 'Recorte refinado preparado para OCR e comparacao visual.',
        })
        steps.append({
            'order': 5,
            'label': 'OCR e consenso',
            'status': 'executado' if _as_dict(report_data.get('consensus')) else 'pendente',
            'detail': 'Motor OCR consolidado com rastreabilidade.',
        })
        steps.append({
            'order': 6,
            'label': 'Conferencia humana',
            'status': 'obrigatoria' if review_required else 'registrada',
            'detail': 'Aprovação humana antes da impressao documental.',
        })

    steps.append({
        'order': 7,
        'label': 'Documento gerado',
        'status': 'consolidado' if _safe_text(analysis_stage, '').lower() != 'preview' else 'pre-analise',
        'detail': 'Relatorio final ou previa de revisao emitido pela plataforma.',
    })

    return steps


def build_evidence_manifest(report_data, analysis_kind=None):
    report_data = _as_dict(report_data)
    input_meta = _as_dict(report_data.get('input_meta'))
    analysis_stage = _safe_text(report_data.get('analysis_stage') or input_meta.get('analysis_mode') or 'final', 'final').lower()
    resolved_kind = _safe_text(analysis_kind, '').strip().lower()
    if not resolved_kind:
        if _safe_text(report_data.get('video_path') or input_meta.get('video_path'), '') or _as_dict(report_data.get('video_metadata')) or _as_dict(input_meta.get('video_metadata')):
            resolved_kind = 'video'
        elif _safe_text(input_meta.get('video_context') or report_data.get('frame_context'), ''):
            resolved_kind = 'video_frame'
        else:
            resolved_kind = 'image'

    source = _build_source_snapshot(report_data, input_meta, resolved_kind)
    processing = _build_processing_snapshot(report_data, input_meta, resolved_kind)
    derived_artifacts = _build_artifacts(report_data, source.get('path', ''), resolved_kind)

    selected_targets = _as_list(report_data.get('selected_targets'))
    if not selected_targets and _safe_text(resolved_kind, '').startswith('video'):
        selected_targets = _as_list(report_data.get('targets'))
    if not selected_targets and _as_list(report_data.get('targets')):
        selected_targets = _as_list(report_data.get('targets'))

    selected_candidate_ids = [
        _safe_text(item, '')
        for item in _as_list(report_data.get('selected_candidate_ids'))
        if _safe_text(item, '')
    ]

    selection_targets = []
    for target in selected_targets:
        summary = _summarize_target(target)
        if summary.get('label') or summary.get('text'):
            selection_targets.append(summary)

    if not selection_targets and _as_list(report_data.get('targets')):
        for target in _as_list(report_data.get('targets')):
            if not isinstance(target, dict):
                continue
            selection_targets.append({
                'candidate_id': _safe_text(target.get('candidate_id'), ''),
                'label': _safe_text(target.get('label') or target.get('display_label'), 'Alvo'),
                'text': _safe_text(target.get('text'), ''),
                'pattern': _safe_text(target.get('pattern'), 'Indefinido'),
                'timestamp_seconds': _safe_float(target.get('timestamp_seconds'), 0.0),
                'timestamp_label': _format_duration(target.get('timestamp_seconds', 0.0)),
                'minute_label': _safe_text(target.get('minute_label'), ''),
                'minute_range': _safe_text(target.get('minute_range'), ''),
                'frames_count': _safe_int(target.get('frames_count'), 0),
                'best_confidence': round(_safe_float(target.get('conf') or target.get('best_confidence') or target.get('avg_confidence'), 0.0), 1),
                'best_score': round(_safe_float(target.get('score') or target.get('best_score') or target.get('avg_score'), 0.0), 1),
            })

    human_review = _as_dict(report_data.get('human_review') or input_meta.get('human_review'))
    capture_integrity = _as_dict(report_data.get('capture_integrity') or input_meta.get('capture_integrity'))
    review_required = bool(human_review) or bool(capture_integrity.get('manual_review_recommended'))

    custody_steps = _build_custody_steps(
        report_data,
        resolved_kind,
        analysis_stage,
        bool(source.get('exists')),
        len(derived_artifacts),
        review_required,
    )
    step_summary = '; '.join([f"{step.get('order')}. {step.get('label')}" for step in custody_steps if isinstance(step, dict)])

    manifest = {
        'manifest_version': '1.0',
        'analysis_id': _safe_text(report_data.get('analysis_id') or input_meta.get('analysis_id'), ''),
        'analysis_kind': resolved_kind,
        'analysis_family': 'video' if resolved_kind.startswith('video') else 'image',
        'analysis_stage': analysis_stage,
        'status': 'preview' if analysis_stage == 'preview' else 'final',
        'generated_at_utc': _utc_now(),
        'summary': (
            'Frame de vídeo preservado, varredura temporal, alvos consolidados e conferência humana antes da impressão documental.'
            if resolved_kind == 'video_frame'
            else (
                'Vídeo fonte preservado, varredura frame a frame, alvos consolidados e conferência humana antes da impressão documental.'
                if resolved_kind.startswith('video')
                else 'Imagem fonte preservada, recorte bruto documentado, recorte tratado confrontado e conferência humana antes da impressão documental.'
            )
        ),
        'source': source,
        'processing': processing,
        'selection': {
            'mode': 'operator_selected' if selection_targets and resolved_kind.startswith('video') else 'ocr_candidates',
            'selected_candidate_ids': selected_candidate_ids,
            'selected_targets': selection_targets,
            'selected_target_count': len(selection_targets),
            'selection_summary': _candidate_summary_text(selection_targets) if selection_targets else 'Automática',
        },
        'derived_artifacts': derived_artifacts,
        'custody': {
            'preserved_original': bool(source.get('exists')),
            'source_sha256': _safe_text(source.get('sha256'), ''),
            'artifact_count': len(derived_artifacts),
            'step_summary': step_summary,
            'steps': custody_steps,
        },
        'review': {
            'required': review_required or analysis_stage == 'preview',
            'status': _safe_text(human_review.get('status') or human_review.get('decision') or ('preview' if analysis_stage == 'preview' else 'pendente'), ''),
            'decision': _safe_text(human_review.get('decision'), ''),
            'decision_label': _safe_text(human_review.get('decision_label'), ''),
            'confirmed_text': _safe_text(human_review.get('confirmed_text'), ''),
            'notes': _safe_text(human_review.get('notes'), ''),
        },
    }

    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop('manifest_fingerprint', None)
    fingerprint_payload.pop('output', None)
    fingerprint_source = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    manifest['manifest_fingerprint'] = hashlib.sha256(fingerprint_source).hexdigest()[:24]
    return manifest


def persist_evidence_manifest(manifest, output_dir, analysis_id=None, analysis_kind=None):
    manifest = _as_dict(manifest)
    output_dir = _safe_text(output_dir, '')
    if not output_dir:
        return {}

    os.makedirs(output_dir, exist_ok=True)

    analysis_id_text = _normalize_component(analysis_id or manifest.get('analysis_id') or 'analysis')
    kind_text = _normalize_component(analysis_kind or manifest.get('analysis_kind') or 'evidence')
    filename = f'GromOCR_EvidenceManifest_{analysis_id_text}_{kind_text}.json'
    path = os.path.join(output_dir, filename)

    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)

    return {
        'manifest_path': path,
        'manifest_url': f'/artifact/{filename}',
        'manifest_filename': filename,
        'manifest_fingerprint': _safe_text(manifest.get('manifest_fingerprint'), ''),
    }


def manifest_summary_dict(manifest):
    manifest = _as_dict(manifest)
    source = _as_dict(manifest.get('source'))
    processing = _as_dict(manifest.get('processing'))
    selection = _as_dict(manifest.get('selection'))
    custody = _as_dict(manifest.get('custody'))
    review = _as_dict(manifest.get('review'))
    family = _safe_text(manifest.get('analysis_family') or source.get('family'), 'image')
    analysis_stage = _safe_text(manifest.get('analysis_stage'), 'final')
    selected_count = _safe_int(selection.get('selected_target_count'), 0)
    artifact_count = _safe_int(custody.get('artifact_count'), 0)
    step_summary = _safe_text(custody.get('step_summary'), 'Indisponível')
    source_resolution = _format_resolution(source.get('source_resolution'))
    source_duration = _format_duration(source.get('duration_seconds', 0.0))

    analysis_kind = _safe_text(manifest.get('analysis_kind'), '')
    if analysis_kind == 'video_frame':
        analysis_label = 'Frame de vídeo'
    elif family.startswith('video'):
        analysis_label = 'Vídeo'
    else:
        analysis_label = 'Imagem'

    summary = {
        'Tipo de análise': analysis_label,
        'Etapa operacional': 'Pré-análise' if analysis_stage == 'preview' else 'Consolidado',
        'Identificação da análise': _safe_text(manifest.get('analysis_id'), '-'),
        'Fonte original': _safe_text(source.get('filename'), 'Indisponível'),
        'Resolução da fonte': source_resolution,
        'Assinatura SHA-256 da fonte': _safe_text(source.get('sha256'), 'Indisponível'),
        'Artefatos derivados': str(artifact_count),
        'Procedimentos registrados': step_summary,
        'Revisão humana': 'Obrigatória' if review.get('required') else 'Registrada',
        'Estado da revisão': _safe_text(review.get('status'), 'Indisponível'),
        'Fingerprint do manifesto': _safe_text(manifest.get('manifest_fingerprint'), 'Indisponível'),
    }

    if family.startswith('video'):
        summary.update({
            'Duração do vídeo': source_duration,
            'Quadros totais': str(_safe_int(source.get('frame_count'), 0)),
            'Taxa de quadros': f"{_safe_float(source.get('fps', 0.0), 0.0):0.2f} fps" if _safe_float(source.get('fps', 0.0), 0.0) > 0 else 'Indisponível',
            'Alvos selecionados': str(selected_count),
            'Seleção do operador': _safe_text(selection.get('selection_summary'), 'Automática'),
        })
    else:
        plate_detection = _as_dict(processing.get('plate_detection'))
        summary.update({
            'Recorte bruto': _safe_text(
                plate_detection.get('selected_raw_path') or source.get('crop_raw_path'),
                'Indisponível',
            ),
            'Recorte tratado': _safe_text(
                plate_detection.get('selected_treated_path') or source.get('crop_treated_path'),
                'Indisponível',
            ),
            'Tratamento da cena': _safe_text(processing.get('scene_preprocess', {}).get('selected_variant'), 'Indisponível'),
            'Seleção OCR': _safe_text(selection.get('selection_summary'), 'Automática'),
        })

    return summary
