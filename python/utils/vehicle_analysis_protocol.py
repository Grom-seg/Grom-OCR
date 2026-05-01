"""Operational protocol for forensic vehicle analysis."""

import re
import unicodedata
from datetime import datetime, timezone

from utils.pericial_labels import humanize_pericial_label


QUALITY_TRIAGE_LABELS = {
    'A': 'boa',
    'B': 'razoavel',
    'C': 'ruim',
    'D': 'impropria',
}

COMPATIBILITY_LEVELS = [
    (90.0, 'MUITO_PROVAVELMENTE_CORRESPONDENTE'),
    (75.0, 'FORTEMENTE_COMPATIVEL'),
    (60.0, 'COMPATIVEL'),
    (40.0, 'POUCO_COMPATIVEL'),
    (0.0, 'INCOMPATIVEL'),
]

OPERATIONAL_CHECKLIST = [
    'Preservar a imagem original e registrar a origem, data/hora e resolucao.',
    'Classificar a qualidade da captura em A/B/C/D antes de concluir.',
    'Registrar leitura principal, alternativas e caracteres incertos do OCR.',
    'Definir a base primaria do veiculo antes de individualizar o modelo.',
    'Confrontar frente, traseira, lateral, rodas e interior quando disponivel.',
    'Aplicar matriz de compatibilidade ponderada e explicita.',
    'Verificar exclusoes obrigatorias e contradires fortes.',
    'Cruzar a placa parcial com a hipoteses visual e com bases autorizadas.',
    'Marcar revisao humana obrigatoria quando a captura estiver fragil.',
]


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_text(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.upper().strip()
    text = re.sub(r'[^A-Z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_plate_text(value):
    return _normalize_text(value).replace(' ', '')


def _unique_preserve_order(items):
    seen = set()
    output = []
    for item in items:
        key = _normalize_plate_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(str(item))
    return output


def _extract_resolution(value):
    if isinstance(value, dict):
        width = _safe_int(value.get('width', value.get('w', 0)), 0)
        height = _safe_int(value.get('height', value.get('h', 0)), 0)
        if width > 0 and height > 0:
            return {'width': width, 'height': height}
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        width = _safe_int(value[0], 0)
        height = _safe_int(value[1], 0)
        if width > 0 and height > 0:
            return {'width': width, 'height': height}
    return {}


def _extract_pattern_label(best_payload, legal_validation, plate_pattern_info):
    for source in (
        _as_dict(plate_pattern_info).get('padrao_placa'),
        _as_dict(legal_validation).get('detected_pattern'),
        _as_dict(best_payload).get('pattern'),
        _as_dict(legal_validation).get('best_fit_pattern'),
    ):
        text = str(source or '').strip()
        if text:
            return text
    return 'Indefinido'


def _has_strong_ocr_evidence(ocr_record):
    ocr_record = _as_dict(ocr_record)
    ocr_text = _normalize_plate_text(ocr_record.get('leitura_principal', ''))
    ocr_conf = _safe_float(
        ocr_record.get('avg_conf', ocr_record.get('confidencia_estimativa', 0.0)),
        0.0,
    )
    ocr_consensus = _safe_float(ocr_record.get('agreement_ratio', 0.0), 0.0)
    ocr_pattern_valid = bool(ocr_record.get('pattern_valid'))
    ocr_pattern = str(ocr_record.get('padrao_placa', '') or '').strip()

    return bool(
        ocr_text
        and len(ocr_text) >= 6
        and ocr_conf >= 80.0
        and ocr_consensus >= 90.0
        and (ocr_pattern_valid or ocr_pattern not in ('', 'Indefinido'))
    )


def _status_score(weight, status, confidence, positive_statuses=(), partial_statuses=(), limited_prefix='limitado_vista'):
    weight = max(0.0, float(weight))
    status_text = _normalize_text(status)
    confidence = max(0.0, min(100.0, _safe_float(confidence, 0.0)))

    positive = {_normalize_text(item) for item in positive_statuses}
    partial = {_normalize_text(item) for item in partial_statuses}
    limited = _normalize_text(limited_prefix)
    weak = {_normalize_text(item) for item in ('fraca', 'sinal_fraco', 'linha_parcial', 'parcial')}
    empty = {_normalize_text(item) for item in ('nao_detectado', 'nao_detectada', 'ausente', 'indefinido', 'indefinida')}

    if status_text in positive:
        score = (weight * 0.70) + ((confidence / 100.0) * weight * 0.30)
    elif status_text in partial:
        score = (weight * 0.45) + ((confidence / 100.0) * weight * 0.20)
    elif status_text.startswith(limited):
        score = (weight * 0.20) + ((confidence / 100.0) * weight * 0.15)
    elif status_text in weak:
        score = (weight * 0.25) + ((confidence / 100.0) * weight * 0.15)
    elif status_text in empty:
        score = 0.0
    else:
        score = (weight * 0.15) + ((confidence / 100.0) * weight * 0.10)

    return round(min(weight, max(0.0, score)), 2)


def _select_component(visual_profile, key):
    visual_profile = _as_dict(visual_profile)
    component_entries = _as_dict(visual_profile.get('assinaturas_componentes', {})).get('componentes', {})
    if not isinstance(component_entries, dict):
        component_entries = {}

    entry = _as_dict(component_entries.get(key, {}))
    if entry:
        return {
            'source': 'assinaturas_componentes',
            'key': key,
            'label': str(entry.get('rotulo', key)),
            'status': str(entry.get('status', 'indefinido')),
            'confidence': round(_safe_float(entry.get('confianca', 0.0), 0.0), 1),
            'detail': str(entry.get('detalhe', '')),
        }

    comparison = _as_dict(visual_profile.get('comparativo_fontes_abertas', {}))
    component_queries = _as_list(comparison.get('consultas_componentes', []))
    for item in component_queries:
        if not isinstance(item, dict):
            continue
        item_key = _normalize_text(item.get('componente', ''))
        label_key = _normalize_text(item.get('rotulo', ''))
        if item_key == _normalize_text(key) or label_key == _normalize_text(key):
            return {
                'source': 'comparativo_fontes_abertas',
                'key': key,
                'label': str(item.get('rotulo', key)),
                'status': str(item.get('status', 'indefinido')),
                'confidence': round(_safe_float(item.get('confianca', 0.0), 0.0), 1),
                'detail': str(item.get('consulta', '')),
                'fonts': _as_list(item.get('fontes', [])),
            }

    return {
        'source': 'indisponivel',
        'key': key,
        'label': str(key),
        'status': 'indefinido',
        'confidence': 0.0,
        'detail': '',
        'fonts': [],
    }


def _build_evidence_preservation(context):
    input_meta = _as_dict(context.get('input_meta'))
    report_context = _as_dict(context.get('report_context'))
    plate_detection = _as_dict(context.get('plate_detection') or input_meta.get('plate_detection'))
    scene_preprocess = _as_dict(context.get('scene_preprocess') or input_meta.get('scene_preprocess'))
    visual_profile = _as_dict(context.get('visual_profile'))

    input_security = _as_dict(input_meta.get('input_security'))
    source_resolution = _extract_resolution(
        input_meta.get('source_resolution')
        or context.get('source_resolution')
        or context.get('photo_resolution')
    )
    visual_scene_resolution = _extract_resolution(
        input_meta.get('visual_scene_resolution')
        or context.get('visual_scene_resolution')
    )
    plate_resolution = _extract_resolution(
        plate_detection.get('selected_resolution')
        or plate_detection.get('ocr_selected_resolution')
        or context.get('plate_resolution')
    )

    transformations = []
    if scene_preprocess:
        transformations.append('scene_preprocess')
    if plate_detection:
        transformations.append('plate_detection')
    if visual_profile:
        transformations.append('visual_profile')
    if _as_dict(context.get('forensic')):
        transformations.append('forensic_chain')
    if _as_dict(context.get('external_systems_comparison')):
        transformations.append('external_validation')

    crop_states = [
        {
            'name': 'original',
            'available': True,
            'label': 'imagem original',
            'path': str(context.get('photo_path') or report_context.get('photo_filename') or input_meta.get('source_filename') or ''),
        },
        {
            'name': 'ampliada',
            'available': bool(scene_preprocess),
            'label': 'imagem ampliada',
            'path': str(input_meta.get('visual_scene_filename') or ''),
        },
        {
            'name': 'placa_crop',
            'available': bool(plate_detection),
            'label': 'recorte da placa',
            'path': str(context.get('plate_path') or report_context.get('plate_filename') or ''),
        },
        {'name': 'frontal_crop', 'available': False, 'label': 'recorte frontal', 'path': ''},
        {'name': 'traseiro_crop', 'available': False, 'label': 'recorte traseiro', 'path': ''},
        {'name': 'lateral_crop', 'available': False, 'label': 'recorte lateral', 'path': ''},
        {'name': 'interior_crop', 'available': False, 'label': 'recorte interior', 'path': ''},
    ]

    return {
        'analysis_id': str(
            context.get('analysis_id')
            or report_context.get('analysis_id')
            or input_meta.get('analysis_id')
            or ''
        ).strip(),
        'origem': str(context.get('origem') or report_context.get('origem') or input_meta.get('input_type') or 'indefinida'),
        'source_filename': str(
            context.get('photo_filename')
            or report_context.get('photo_filename')
            or input_meta.get('source_filename')
            or ''
        ).strip(),
        'plate_filename': str(
            context.get('plate_filename')
            or report_context.get('plate_filename')
            or plate_detection.get('selected_region')
            or ''
        ).strip(),
        'visual_scene_filename': str(
            context.get('visual_scene_filename')
            or report_context.get('visual_scene_filename')
            or input_meta.get('visual_scene_filename')
            or ''
        ).strip(),
        'capture_timestamp_utc': str(
            context.get('capture_timestamp_utc')
            or report_context.get('capture_timestamp_utc')
            or input_meta.get('capture_timestamp_utc')
            or ''
        ).strip(),
        'generated_timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'input_type': str(input_meta.get('input_type', 'indefinido')),
        'input_status': str(_as_dict(input_security).get('status', 'indefinido')),
        'camera': str(input_meta.get('camera') or 'Generic Forensic Capture'),
        'exif': _as_dict(input_meta.get('exif')),
        'input_signature': str(_as_dict(input_security).get('detected_signature', '')),
        'input_signature_ok': bool(_as_dict(input_security).get('signature_ok', True)),
        'source_resolution': source_resolution,
        'visual_scene_resolution': visual_scene_resolution,
        'plate_resolution': plate_resolution,
        'copy_preserved': True,
        'transformations': transformations,
        'available_crops': crop_states,
        'observations': [
            'original_preserved_em_copia',
            'crops_ausentes_marcados_como_indisponiveis',
        ],
    }


def _quality_tier_from_score(score):
    score = max(0.0, min(100.0, _safe_float(score, 0.0)))
    if score >= 85.0:
        return 'A'
    if score >= 70.0:
        return 'B'
    if score >= 50.0:
        return 'C'
    return 'D'


def _build_quality_triage(context):
    quality_report = _as_dict(context.get('quality_report'))
    capture_integrity = _as_dict(context.get('capture_integrity') or _as_dict(context.get('pericial')).get('capture_integrity'))
    plate_detection = _as_dict(context.get('plate_detection') or _as_dict(context.get('input_meta')).get('plate_detection'))
    best_payload = _as_dict(context.get('best_payload') or context.get('best'))
    consensus = _as_dict(context.get('consensus'))

    quality_score = _safe_float(quality_report.get('score', 0.0), 0.0)
    integrity_score = _safe_float(capture_integrity.get('integrity_score', 100.0), 100.0)
    consensus_ratio = _safe_float(consensus.get('agreement_ratio', 0.0), 0.0)
    avg_conf = _safe_float(best_payload.get('avg_conf', best_payload.get('score', 0.0)), 0.0)

    composite = (quality_score * 0.42) + (integrity_score * 0.38) + (consensus_ratio * 0.10) + (avg_conf * 0.10)
    triage_class = _quality_tier_from_score(composite)
    triage_label = QUALITY_TRIAGE_LABELS.get(triage_class, 'indefinida')
    reasons = []

    if quality_report.get('grade') == 'CRITICA':
        triage_class = 'D'
        triage_label = QUALITY_TRIAGE_LABELS['D']
        reasons.append('qualidade_da_imagem_critica')
    if capture_integrity.get('status') == 'revisao_obrigatoria':
        triage_class = 'D'
        triage_label = QUALITY_TRIAGE_LABELS['D']
        reasons.append('integridade_da_captura_requer_revisao')
    if plate_detection.get('status') == 'sem_candidato':
        triage_class = 'D'
        triage_label = QUALITY_TRIAGE_LABELS['D']
        reasons.append('sem_roi_confiavel')
    if plate_detection.get('status') == 'fallback_full_scene' and triage_class in ('A', 'B'):
        triage_class = 'C'
        triage_label = QUALITY_TRIAGE_LABELS['C']
        reasons.append('fallback_em_imagem_completa')

    if not reasons:
        issues = _as_list(quality_report.get('issues', []))
        if issues:
            reasons.extend([str(item) for item in issues[:4] if str(item).strip()])
        if _as_list(capture_integrity.get('issues', [])):
            reasons.extend([str(item) for item in _as_list(capture_integrity.get('issues', []))[:4] if str(item).strip()])
        if consensus_ratio < 40.0:
            reasons.append('consenso_ocr_baixo')

    manual_review = bool(
        triage_class == 'D'
        or capture_integrity.get('manual_review_recommended')
        or plate_detection.get('status') == 'sem_candidato'
        or quality_report.get('grade') == 'CRITICA'
    )

    return {
        'class': triage_class,
        'label': triage_label,
        'display_label': humanize_pericial_label(triage_label),
        'score': round(float(max(0.0, min(100.0, composite))), 1),
        'manual_review': manual_review,
        'reasons': _unique_preserve_order(reasons),
        'quality_score': round(quality_score, 1),
        'integrity_score': round(integrity_score, 1),
        'consensus_ratio': round(consensus_ratio, 1),
        'avg_confidence': round(avg_conf, 1),
    }


def _build_ocr_record(context):
    best_payload = _as_dict(context.get('best_payload') or context.get('best'))
    top_candidates = _as_list(context.get('top_candidates'))
    legal_validation = _as_dict(context.get('legal_validation') or _as_dict(context.get('pericial')).get('legal_validation'))
    plate_pattern_info = _as_dict(context.get('plate_pattern_info') or context.get('plate_pattern'))
    ambiguity = _as_dict(context.get('character_ambiguity') or _as_dict(context.get('pericial')).get('character_ambiguity'))
    partial_plate_evidence = _as_dict(context.get('partial_plate_evidence') or _as_dict(context.get('pericial')).get('partial_plate_evidence'))
    partial_plate_candidates = _as_list(context.get('partial_plate_candidates') or partial_plate_evidence.get('partial_plate_candidates') or _as_dict(context.get('pericial')).get('partial_plate_candidates'))
    partial_plate_summary = str(
        context.get('partial_plate_summary')
        or partial_plate_evidence.get('partial_plate_summary')
        or _as_dict(context.get('pericial')).get('partial_plate_summary')
        or ''
    ).strip()
    partial_plate_text = str(
        context.get('partial_plate_text')
        or partial_plate_evidence.get('partial_plate_text')
        or _as_dict(context.get('pericial')).get('partial_plate_text')
        or ''
    ).strip()
    consensus = _as_dict(context.get('consensus'))

    main_text = _normalize_plate_text(best_payload.get('text', ''))
    uncertainty_positions = []
    ambiguous_positions = _as_list(ambiguity.get('ambiguous_positions', []))

    scene_preprocess = _as_dict(context.get('scene_preprocess') or _as_dict(context.get('input_meta')).get('scene_preprocess'))
    scene_profile = _as_dict(scene_preprocess.get('scene_profile'))
    has_adulterated_lighting = 'adulterated_lighting' in _as_list(scene_profile.get('tags', []))
    
    possible_adulteration = False
    adulteration_details = []

    for entry in ambiguous_positions:
        if not isinstance(entry, dict):
            continue
        confusable = bool(entry.get('is_confusable', False))
        alts = _as_list(entry.get('alternatives', []))
        if confusable and alts:
            possible_adulteration = True
            adulteration_details.append(f"P{entry.get('position', '?')}: {' ou '.join(str(x) for x in alts[:2])}")
            
        uncertainty_positions.append({
            'position': _safe_int(entry.get('position', 0), 0),
            'expected_slot': str(entry.get('expected_slot', '?')),
            'is_confusable': confusable,
        })
        
    if has_adulterated_lighting:
        possible_adulteration = True
        if "Anomalia de luz/adulteracao" not in adulteration_details:
            adulteration_details.append("Anomalia de luz/adulteracao")

    alerta_adulteracao = "Atencao: Possivel adulteracao (" + "; ".join(adulteration_details) + ") - Verificar imagem" if possible_adulteration else "Nao detectada"

    avg_conf = _safe_float(best_payload.get('avg_conf', 0.0), 0.0)
    score = _safe_float(best_payload.get('score', 0.0), 0.0)
    law_score = _safe_float(legal_validation.get('law_score', 0.0), 0.0)
    consensus_ratio = _safe_float(consensus.get('agreement_ratio', 0.0), 0.0)
    confidence_estimated = round(
        max(
            0.0,
            min(100.0, (avg_conf * 0.48) + (consensus_ratio * 0.27) + (law_score * 0.25)),
        ),
        1,
    )

    return {
        'leitura_principal': main_text or 'indefinido',
        'leitura_alternativas': top_candidates[:3] if top_candidates else [],
        'alerta_adulteracao': alerta_adulteracao,
        'leituras_conflitantes': [
            f"{c.get('text', '')} detectado por: {', '.join([str(e) for e in _as_list(c.get('engines') or c.get('support_engines', []))])}"
            for c in top_candidates[1:4]
            if isinstance(c, dict) and c.get('text', '') and _normalize_plate_text(c.get('text', '')) != main_text
        ] if len(top_candidates) > 1 else [],
        'caracteres_incertos': uncertainty_positions,
        'caracteres_incertos_resumo': '; '.join(
            [
                f"P{item.get('position', '?')}[{item.get('expected_slot', '?')}]"
                for item in uncertainty_positions
            ]
        ) or '-',
        'padrao_placa': str(_extract_pattern_label(best_payload, legal_validation, plate_pattern_info) or 'Indefinido'),
        'padrão_placa': str(_extract_pattern_label(best_payload, legal_validation, plate_pattern_info) or 'Indefinido'),
        'confidencia_estimativa': confidence_estimated,
        'avg_conf': round(avg_conf, 1),
        'score_bruto': round(score, 1),
        'law_score': round(law_score, 1),
        'agreement_ratio': round(consensus_ratio, 1),
        'supports': _unique_preserve_order(_as_list(best_payload.get('support_engines', []))),
        'partial_plate': bool(main_text and len(main_text) < 7),
        'partial_plate_detected': bool(partial_plate_candidates),
        'partial_plate_text': partial_plate_text or (partial_plate_candidates[0].get('text', '') if partial_plate_candidates and isinstance(partial_plate_candidates[0], dict) else ''),
        'partial_plate_candidates': partial_plate_candidates[:6],
        'partial_plate_candidates_count': len(partial_plate_candidates),
        'partial_plate_summary': partial_plate_summary or ('; '.join(
            str(item.get('text', '')) for item in partial_plate_candidates[:4]
            if isinstance(item, dict) and str(item.get('text', '')).strip()
        ) or '-'),
        'pattern_valid': bool(_as_dict(legal_validation).get('is_valid', False)),
        'pattern_source': str(
            'plate_pattern_info'
            if _as_dict(plate_pattern_info).get('padrao_placa')
            else ('legal_validation' if _as_dict(legal_validation).get('detected_pattern') else 'ocr_ensemble')
        ),
        'raw_text': str(best_payload.get('text', '') or ''),
        'targets': _as_list(context.get('targets', [])),
    }


def _infer_vehicle_basics(context):
    visual_profile = _as_dict(context.get('visual_profile'))
    principal = _as_dict(visual_profile.get('hipotese_principal'))
    geometry = _as_dict(visual_profile.get('geometria'))
    rear_signature = _as_dict(visual_profile.get('lanterna_traseira'))
    comparison = _as_dict(visual_profile.get('comparativo_fontes_abertas'))

    aspect = _safe_float(geometry.get('vehicle_aspect_ratio', 0.0), 0.0)
    compact = bool(geometry.get('compact_vehicle'))
    view_type = _normalize_text(visual_profile.get('vista_detectada', 'indefinida'))
    rear_vertical = bool(rear_signature.get('vertical_pair'))
    rear_detected = bool(rear_signature.get('detected'))
    rear_conf = _safe_float(rear_signature.get('confidence', 0.0), 0.0)

    if aspect <= 0.0:
        body_style = 'indefinido'
        body_conf = 0.0
    elif compact and rear_vertical:
        body_style = 'hatch'
        body_conf = 82.0 if rear_conf >= 45.0 else 66.0
    elif aspect >= 2.7:
        body_style = 'picape/caminhonete'
        body_conf = min(88.0, 48.0 + ((aspect - 2.7) * 14.0))
    elif aspect >= 2.15:
        body_style = 'sedan/van'
        body_conf = min(82.0, 46.0 + ((aspect - 2.15) * 18.0))
    elif aspect >= 1.45:
        body_style = 'hatch'
        body_conf = min(78.0, 44.0 + ((2.1 - abs(aspect - 1.9)) * 10.0))
    else:
        body_style = 'indefinido'
        body_conf = 0.0

    porte = 'indefinido'
    if aspect > 0.0:
        if aspect >= 2.7:
            porte = 'grande'
        elif aspect >= 2.05:
            porte = 'medio'
        else:
            porte = 'compacto'

    portas_visiveis = 'indefinido'
    linhas_portas = _select_component(visual_profile, 'linhas_portas')
    if _normalize_text(linhas_portas.get('status')) in ('VINCOS_VISIVEIS', 'LINHA_PARCIAL'):
        portas_visiveis = '2-4'
    elif _normalize_text(linhas_portas.get('status')) not in ('INDEFINIDO', 'NAO_DETECTADO', 'NAO_DETECTADA', 'AUSENTE'):
        portas_visiveis = '2'

    volume_traseiro = 'indefinido'
    if body_style == 'hatch':
        volume_traseiro = 'curto'
    elif body_style == 'sedan/van':
        volume_traseiro = 'medio'
    elif body_style == 'picape/caminhonete':
        volume_traseiro = 'longo'

    roof_slope = 'indefinido'
    if body_style == 'hatch':
        roof_slope = 'acentuado'
    elif body_style == 'sedan/van':
        roof_slope = 'suave'
    elif body_style == 'picape/caminhonete':
        roof_slope = 'plano'

    plate_position = 'indefinida'
    if view_type == 'TRASEIRA':
        plate_position = 'traseira'
    elif view_type == 'FRONTAL':
        plate_position = 'dianteira'

    rear_window_shape = 'indefinida'
    c_pillar = 'indefinida'
    if body_style == 'hatch':
        rear_window_shape = 'compacta'
        c_pillar = 'integrada'
    elif body_style == 'sedan/van':
        rear_window_shape = 'ampla'
        c_pillar = 'proeminente'
    elif body_style == 'picape/caminhonete':
        rear_window_shape = 'vertical'
        c_pillar = 'robusta'

    observation = []
    if view_type == 'INDEFINIDA':
        observation.append('vista_geral_sem_orientacao_firme')
    if not rear_detected:
        observation.append('assinatura_traseira_nao_confirmada')
    if compact:
        observation.append('geometria_compacta')
    if rear_vertical:
        observation.append('lanternas_traseiras_verticais')
    if _as_dict(comparison).get('fontes'):
        observation.append('comparativo_aberto_disponivel')

    return {
        'categoria_primaria': body_style,
        'categoria_confidence': round(float(body_conf), 1),
        'porte': porte,
        'numero_portas_visiveis_estimado': portas_visiveis,
        'volume_traseiro': volume_traseiro,
        'caimento_teto': roof_slope,
        'posicao_placa': plate_position,
        'formato_vidro_traseiro': rear_window_shape,
        'coluna_c': c_pillar,
        'assinatura_frontal': str(view_type if view_type in ('FRONTAL', 'TRASEIRA') else 'indefinida').lower(),
        'fabricante_probavel': str(principal.get('fabricante', '-')),
        'modelo_probavel': str(principal.get('modelo', '-')),
        'faixa_ano_probavel': str(principal.get('faixa_ano_modelo', '-')),
        'confianca_hipotese_visual': round(_safe_float(principal.get('confianca', 0.0), 0.0), 1),
        'observacoes': _unique_preserve_order(observation),
    }


def _matrix_item(label, weight, score, available=True, status='indefinido', evidence=None, notes=None, source='local'):
    return {
        'criterio': label,
        'peso_maximo': round(float(weight), 1),
        'pontuacao': round(float(max(0.0, min(float(weight), score))), 1),
        'disponivel': bool(available),
        'status': str(status),
        'evidencias': _unique_preserve_order(evidence or []),
        'observacoes': _unique_preserve_order(notes or []),
        'fonte': str(source),
    }


def _extract_open_component(comparison, key):
    comparison = _as_dict(comparison)
    component_queries = _as_list(comparison.get('consultas_componentes', []))
    wanted = _normalize_text(key)
    for item in component_queries:
        if not isinstance(item, dict):
            continue
        item_key = _normalize_text(item.get('componente', ''))
        rotulo_key = _normalize_text(item.get('rotulo', ''))
        if item_key == wanted or rotulo_key == wanted:
            return item
    return {}


def _build_compatibility_matrix(context, ocr_record, quality_triage, vehicle_basics):
    visual_profile = _as_dict(context.get('visual_profile'))
    consensus = _as_dict(context.get('consensus'))
    quality_report = _as_dict(context.get('quality_report'))
    legal_validation = _as_dict(context.get('legal_validation') or _as_dict(context.get('pericial')).get('legal_validation'))
    comparison = _as_dict(visual_profile.get('comparativo_fontes_abertas'))
    component_profile = _as_dict(visual_profile.get('assinaturas_componentes'))
    component_entries = _as_dict(component_profile.get('componentes'))
    rear_signature = _as_dict(visual_profile.get('lanterna_traseira'))
    geometry = _as_dict(visual_profile.get('geometria'))
    forensic_traits = _as_dict(visual_profile.get('caracteristicas_forenses'))

    items = []

    main_text = _normalize_plate_text(ocr_record.get('leitura_principal', ''))
    alternatives = _as_list(ocr_record.get('leitura_alternativas', []))
    pattern_valid = bool(ocr_record.get('pattern_valid'))
    law_score = _safe_float(ocr_record.get('law_score', 0.0), 0.0)
    consensus_ratio = _safe_float(ocr_record.get('agreement_ratio', 0.0), 0.0)
    avg_conf = _safe_float(ocr_record.get('avg_conf', 0.0), 0.0)
    ocr_score = 0.0
    ocr_evidence = [f'texto={main_text or "indefinido"}']
    if alternatives:
        ocr_evidence.append('leitura_nao_ratifcada')
    if pattern_valid:
        ocr_score += 11.0
        ocr_evidence.append('padrao_legal_valido')
    if len(main_text) == 7:
        ocr_score += 4.0
    elif len(main_text) >= 5:
        ocr_score += 2.5
    ocr_score += min(6.0, law_score * 0.16)
    ocr_score += min(4.0, consensus_ratio * 0.06)
    ocr_score += min(4.0, avg_conf * 0.05)
    if not main_text:
        ocr_score = 0.0
    items.append(_matrix_item('Placa/OCR total ou parcial', 25.0, ocr_score, bool(main_text), ocr_record.get('padrao_placa', 'Indefinido'), ocr_evidence))

    headlamps = _as_dict(component_entries.get('farois_dianteiros'))
    headlamp_status = str(headlamps.get('status', 'indefinido'))
    headlamp_conf = _safe_float(headlamps.get('confianca', 0.0), 0.0)
    headlamp_score = _status_score(10.0, headlamp_status, headlamp_conf, positive_statuses=('simetricos',), partial_statuses=('parcial',))
    if bool(geometry.get('dual_headlamps')):
        headlamp_score = min(10.0, headlamp_score + 1.0)
    items.append(_matrix_item('Farois', 10.0, headlamp_score, headlamp_status not in ('indefinido', 'nao_detectado', 'nao_detectada'), headlamp_status, [headlamps.get('detalhe', ''), 'dual_headlamps' if geometry.get('dual_headlamps') else '']))

    tail_component = _as_dict(component_entries.get('lanternas_traseiras'))
    tail_status = str(tail_component.get('status', 'indefinido'))
    tail_conf = _safe_float(tail_component.get('confianca', 0.0), 0.0)
    rear_score = _status_score(10.0, tail_status, tail_conf, positive_statuses=('par_vertical', 'par_detectado'), partial_statuses=('parcial',))
    rear_evidence = [tail_component.get('detalhe', '')]
    if bool(rear_signature.get('vertical_pair')):
        rear_score = min(10.0, rear_score + 1.2)
        rear_evidence.append('lanterna_traseira_vertical')
    items.append(_matrix_item('Lanternas traseiras', 10.0, rear_score, tail_status not in ('indefinido', 'nao_detectado', 'nao_detectada'), tail_status, rear_evidence))

    grille_component = _as_dict(component_entries.get('grade_dianteira'))
    grille_status = str(grille_component.get('status', 'indefinido'))
    grille_conf = _safe_float(grille_component.get('confianca', 0.0), 0.0)
    grille_score = _status_score(8.0, grille_status, grille_conf, positive_statuses=('presente',), partial_statuses=('fraca',))
    items.append(_matrix_item('Grade dianteira', 8.0, grille_score, grille_status not in ('indefinido', 'nao_detectada', 'nao_detectado'), grille_status, [grille_component.get('detalhe', '')]))

    bumper_query = _as_dict(_extract_open_component(comparison, 'parachoque'))
    bumper_status = str(bumper_query.get('status', 'indefinido'))
    bumper_conf = _safe_float(bumper_query.get('confianca', 0.0), 0.0)
    bumper_score = _status_score(8.0, bumper_status, bumper_conf, positive_statuses=('presente', 'detectado'), partial_statuses=('fraca', 'parcial'))
    bumper_evidence = [str(bumper_query.get('consulta', '')), str(bumper_query.get('rotulo', ''))]
    items.append(_matrix_item('Parachoques', 8.0, bumper_score, bumper_status not in ('indefinido', ''), bumper_status, bumper_evidence, source='comparativo_fontes_abertas'))

    wheel_query = _as_dict(_extract_open_component(comparison, 'rodas_originais'))
    wheel_status = str(wheel_query.get('status', 'indefinido'))
    wheel_conf = _safe_float(wheel_query.get('confianca', 0.0), 0.0)
    wheel_score = _status_score(6.0, wheel_status, wheel_conf, positive_statuses=('detectado', 'presente'), partial_statuses=('parcial',))
    wheel_evidence = [str(wheel_query.get('consulta', '')), str(wheel_query.get('rotulo', ''))]
    items.append(_matrix_item('Rodas / calotas', 6.0, wheel_score, wheel_status not in ('indefinido', ''), wheel_status, wheel_evidence, source='comparativo_fontes_abertas'))

    side_component = _as_dict(component_entries.get('linhas_portas'))
    side_status = str(side_component.get('status', 'indefinido'))
    side_conf = _safe_float(side_component.get('confianca', 0.0), 0.0)
    side_score = _status_score(10.0, side_status, side_conf, positive_statuses=('vincos_visiveis',), partial_statuses=('linha_parcial',))
    design_query = _as_dict(_extract_open_component(comparison, 'design_carroceria'))
    if design_query:
        side_score = min(10.0, side_score + min(1.5, _safe_float(design_query.get('confianca', 0.0), 0.0) * 0.015))
    items.append(_matrix_item('Linha lateral / vidros / colunas', 10.0, side_score, side_status not in ('indefinido', ''), side_status, [side_component.get('detalhe', ''), str(design_query.get('consulta', ''))], source='assinaturas_componentes+comparativo'))

    mirror_query = _as_dict(_extract_open_component(comparison, 'retrovisores'))
    mirror_status = str(mirror_query.get('status', 'indefinido'))
    mirror_conf = _safe_float(mirror_query.get('confianca', 0.0), 0.0)
    mirror_score = _status_score(5.0, mirror_status, mirror_conf, positive_statuses=('detectado', 'presente'), partial_statuses=('parcial',))
    mirror_evidence = [str(mirror_query.get('consulta', '')), str(mirror_query.get('rotulo', ''))]
    if _as_list(forensic_traits.get('achados', [])):
        mirror_evidence.append('achados_forenses_presentes')
    items.append(_matrix_item('Macanetas / retrovisores / detalhes', 5.0, mirror_score, mirror_status not in ('indefinido', ''), mirror_status, mirror_evidence, source='comparativo_fontes_abertas'))

    emblem_component = _as_dict(component_entries.get('emblema_frontal'))
    emblem_status = str(emblem_component.get('status', 'indefinido'))
    emblem_conf = _safe_float(emblem_component.get('confianca', 0.0), 0.0)
    emblem_score = _status_score(8.0, emblem_status, emblem_conf, positive_statuses=('detectado',), partial_statuses=('parcial',))
    emblem_query = _as_dict(_extract_open_component(comparison, 'emblema_frontal'))
    if emblem_query:
        emblem_score = min(8.0, emblem_score + min(1.0, _safe_float(emblem_query.get('confianca', 0.0), 0.0) * 0.01))
    items.append(_matrix_item('Emblemas / inscricoes', 8.0, emblem_score, emblem_status not in ('indefinido', ''), emblem_status, [emblem_component.get('detalhe', ''), str(emblem_query.get('consulta', ''))], source='assinaturas_componentes+comparativo'))

    hood_query = _as_dict(_extract_open_component(comparison, 'linhas_capo'))
    hood_status = str(hood_query.get('status', 'indefinido'))
    hood_conf = _safe_float(hood_query.get('confianca', 0.0), 0.0)
    hood_score = _status_score(5.0, hood_status, hood_conf, positive_statuses=('presente', 'detectado'), partial_statuses=('parcial',))
    hood_evidence = [str(hood_query.get('consulta', '')), str(hood_query.get('rotulo', ''))]
    items.append(_matrix_item('Linhas do capo / dianteira', 5.0, hood_score, hood_status not in ('indefinido', ''), hood_status, hood_evidence, source='comparativo_fontes_abertas'))

    led_query = _as_dict(_extract_open_component(comparison, 'assinatura_led'))
    led_status = str(led_query.get('status', 'indefinido'))
    led_conf = _safe_float(led_query.get('confianca', 0.0), 0.0)
    led_score = _status_score(5.0, led_status, led_conf, positive_statuses=('presente', 'detectado'), partial_statuses=('parcial',))
    items.append(_matrix_item('Assinatura LED / luz diurna', 5.0, led_score, led_status not in ('indefinido', ''), led_status, [str(led_query.get('consulta', ''))], source='comparativo_fontes_abertas'))

    damage_query = _as_dict(_extract_open_component(comparison, 'amassados'))
    damage_status = str(damage_query.get('status', 'indefinido'))
    damage_score = _status_score(5.0, damage_status, _safe_float(damage_query.get('confianca', 0.0)), positive_statuses=('presente',), partial_statuses=('parcial',))
    items.append(_matrix_item('Amassados / retoques', 5.0, damage_score, damage_status not in ('indefinido', ''), damage_status, [str(damage_query.get('consulta', ''))], source='comparativo_fontes_abertas'))

    sticker_query = _as_dict(_extract_open_component(comparison, 'adesivos_propaganda'))
    sticker_status = str(sticker_query.get('status', 'indefinido'))
    sticker_score = _status_score(5.0, sticker_status, _safe_float(sticker_query.get('confianca', 0.0)), positive_statuses=('presente',), partial_statuses=('parcial',))
    items.append(_matrix_item('Adesivos / propaganda', 5.0, sticker_score, sticker_status not in ('indefinido', ''), sticker_status, [str(sticker_query.get('consulta', ''))], source='comparativo_fontes_abertas'))

    interior_available = bool(_as_dict(context.get('vehicle_interior')) or _as_dict(context.get('interior_profile')))
    interior_score = 0.0
    interior_evidence = ['sem_recorte_interno_disponivel']
    if interior_available:
        interior_score = 6.0
        interior_evidence = ['recorte_interno_disponivel']
    items.append(_matrix_item('Painel / interior', 10.0, interior_score, interior_available, 'indefinido' if not interior_available else 'detectado', interior_evidence))

    score_total = round(sum(float(item.get('pontuacao', 0.0)) for item in items), 1)
    available_max = round(sum(float(item.get('peso_maximo', 0.0)) for item in items if item.get('disponivel')), 1)
    available_ratio = round((score_total / available_max) * 100.0, 1) if available_max > 0 else 0.0
    coverage = round((available_max / 100.0) * 100.0, 1)

    level = 'INCOMPATIVEL'
    for threshold, label in COMPATIBILITY_LEVELS:
        if score_total >= threshold:
            level = label
            break

    items.sort(key=lambda item: float(item.get('peso_maximo', 0.0)), reverse=True)
    summary = []
    for item in items[:4]:
        label = str(item.get('criterio', '-'))
        score = float(item.get('pontuacao', 0.0))
        summary.append(f'{label}={score:.1f}')

    return {
        'score_total': score_total,
        'max_score': 100.0,
        'available_score': round(score_total, 1),
        'available_max_score': available_max,
        'coverage_percent': coverage,
        'available_ratio': available_ratio,
        'level': level,
        'display_level': humanize_pericial_label(level),
        'items': items,
        'summary': summary,
    }


def _build_exclusion_checks(context, quality_triage, ocr_record, compatibility_matrix):
    pericial = _as_dict(context.get('pericial'))
    capture_integrity = _as_dict(context.get('capture_integrity') or pericial.get('capture_integrity'))
    quality_report = _as_dict(context.get('quality_report'))
    legal_validation = _as_dict(context.get('legal_validation') or pericial.get('legal_validation'))
    visual_profile = _as_dict(context.get('visual_profile'))
    model_quality = _as_dict(visual_profile.get('qualidade_modelo'))
    consensus = _as_dict(context.get('consensus'))
    strong_ocr = _has_strong_ocr_evidence(ocr_record)

    checks = []

    def add_check(code, label, status, strong=False, reason='', impact='medio'):
        checks.append({
            'code': str(code),
            'label': str(label),
            'status': str(status),
            'strong_excluder': bool(strong),
            'reason': str(reason),
            'impact': str(impact),
        })

    add_check(
        'capture_integrity',
        'Integridade da captura',
        capture_integrity.get('status', 'indefinido'),
        bool(capture_integrity.get('status') == 'revisao_obrigatoria'),
        capture_integrity.get('summary', ''),
        'alto' if capture_integrity.get('status') == 'revisao_obrigatoria' else 'medio',
    )
    add_check(
        'image_quality',
        'Qualidade da imagem',
        quality_report.get('grade', 'indefinido'),
        bool(quality_report.get('grade') == 'CRITICA' or _safe_float(quality_report.get('score', 0.0), 0.0) < 48.0),
        'score=%.1f' % _safe_float(quality_report.get('score', 0.0), 0.0),
        'alto' if quality_report.get('grade') == 'CRITICA' else 'medio',
    )
    add_check(
        'ocr_pattern',
        'Padrao legal da placa',
        'valida' if legal_validation.get('is_valid') else 'invalida',
        bool(not legal_validation.get('is_valid')),
        str(legal_validation.get('detected_pattern', 'Indefinido')),
        'alto' if not legal_validation.get('is_valid') else 'baixo',
    )
    add_check(
        'ocr_ambiguity',
        'Ambiguidade OCR',
        'alta' if _safe_int(_as_dict(context.get('character_ambiguity')).get('ambiguity_count', 0), 0) >= 2 else 'ok',
        bool(_safe_int(_as_dict(context.get('character_ambiguity')).get('ambiguity_count', 0), 0) >= 3),
        str(_as_dict(context.get('character_ambiguity')).get('ambiguity_score', 100.0)),
        'medio',
    )
    add_check(
        'ocr_consensus',
        'Consenso entre motores',
        'baixo' if _safe_float(consensus.get('agreement_ratio', 0.0), 0.0) < 40.0 else 'ok',
        False,
        f"agreement_ratio={_safe_float(consensus.get('agreement_ratio', 0.0), 0.0):.1f}",
        'baixo' if _safe_float(consensus.get('agreement_ratio', 0.0), 0.0) < 40.0 else 'baixo',
    )
    add_check(
        'visual_abstention',
        'Abstencao visual',
        'ativa' if bool(model_quality.get('model_abstained')) else 'inativa',
        False,
        ';'.join([str(item) for item in _as_list(model_quality.get('reasons', []))]),
        'medio',
    )
    add_check(
        'compatibility_coverage',
        'Cobertura da matriz',
        'baixa' if _safe_float(compatibility_matrix.get('coverage_percent', 0.0), 0.0) < 35.0 else 'ok',
        bool(_safe_float(compatibility_matrix.get('coverage_percent', 0.0), 0.0) < 35.0 and not strong_ocr),
        f"coverage={_safe_float(compatibility_matrix.get('coverage_percent', 0.0), 0.0):.1f}%",
        'alto' if _safe_float(compatibility_matrix.get('coverage_percent', 0.0), 0.0) < 35.0 and not strong_ocr else 'medio',
    )
    add_check(
        'interior_presence',
        'Interior / painel',
        'indisponivel',
        False,
        'sem_recorte_interno',
        'baixo',
    )

    triggered = [item for item in checks if item.get('status') not in ('ok', 'valida', 'inativa', 'baixo', 'indisponivel')]
    strong_triggered = [item for item in checks if item.get('strong_excluder')]

    return {
        'items': checks,
        'triggered_count': len(triggered),
        'strong_triggered_count': len(strong_triggered),
        'strong_triggered': strong_triggered,
        'summary': [
            item.get('label', '')
            for item in checks
            if item.get('status') not in ('ok', 'valida', 'inativa')
        ],
    }


def _build_conclusion(context, quality_triage, vehicle_basics, compatibility_matrix, exclusion_checks, ocr_record=None):
    if ocr_record is None:
        ocr_record = {}
    if not isinstance(compatibility_matrix, dict):
        compatibility_matrix = {}
    if not isinstance(exclusion_checks, dict):
        exclusion_checks = {}

    score_total = _safe_float(compatibility_matrix.get('score_total', 0.0), 0.0)
    level = str(compatibility_matrix.get('level', 'INCOMPATIVEL'))
    triage_class = str(quality_triage.get('class', 'D'))
    strong_excluders = bool(exclusion_checks.get('strong_triggered_count', 0))
    manual_review = bool(quality_triage.get('manual_review')) or strong_excluders
    decision = 'conclusivo'

    ocr_text = _normalize_plate_text(ocr_record.get('leitura_principal', ''))
    ocr_conf = _safe_float(
        ocr_record.get('avg_conf', ocr_record.get('confidencia_estimativa', 0.0)),
        0.0,
    )
    ocr_consensus = _safe_float(ocr_record.get('agreement_ratio', 0.0), 0.0)
    ocr_pattern_valid = bool(ocr_record.get('pattern_valid'))
    strong_ocr = _has_strong_ocr_evidence(ocr_record)

    if strong_ocr and not strong_excluders:
        manual_review = False

    if triage_class == 'D' or manual_review:
        decision = 'inconclusivo'
    if score_total < 40.0:
        decision = 'inconclusivo'

    if strong_ocr and score_total < 40.0:
        decision = 'conclusivo'
        if level == 'INCOMPATIVEL':
            level = 'COMPATIVEL_PARCIAL'

    if decision == 'inconclusivo' and score_total < 40.0 and not strong_ocr:
        level = 'INCOMPATIVEL'

    if bool(ocr_record.get('partial_plate')):
        decision = 'inconclusivo' if triage_class == 'D' else decision
        level = level if level != 'INCOMPATIVEL' else 'COMPATIVEL_PARCIAL'

    maker = str(vehicle_basics.get('fabricante_probavel', '') or '').strip() or 'indeterminado'
    model = str(vehicle_basics.get('modelo_probavel', '') or '').strip() or 'indeterminado'
    year = str(vehicle_basics.get('faixa_ano_probavel', '') or '').strip() or 'indeterminado'
    body = str(vehicle_basics.get('categoria_primaria', '') or '').strip() or 'indefinido'

    top_items = _as_list(compatibility_matrix.get('items', []))[:3]
    supporting = []
    for item in top_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get('criterio', '-'))
        score = _safe_float(item.get('pontuacao', 0.0), 0.0)
        supporting.append(f'{label}={score:.1f}')

    if decision == 'inconclusivo':
        if strong_ocr:
            summary = (
                'A leitura documental da placa foi consolidada com alta confianca. '
                f'Resultado principal: {ocr_text or "indefinido"}; consenso OCR={ocr_consensus:.1f}%. '
                'A individualizacao completa de fabricante/modelo permanece limitada pela ausencia '
                'de assinaturas visuais externas suficientemente discriminativas.'
            )
        else:
            summary = (
                'A imagem apresenta limitacoes tecnicas relevantes, impedindo individualizacao segura. '
                f'Concluir como {humanize_pericial_label(level)} exige revisao humana qualificada.'
            )
    else:
        if strong_ocr and (maker in ('', 'indeterminado') or model in ('', 'indeterminado', 'Nao conclusivo')):
            summary = (
                'A leitura documental da placa foi consolidada com alta confianca. '
                f'Resultado principal: {ocr_text or "indefinido"}; consenso OCR={ocr_consensus:.1f}%. '
                'A placa permanece apta para confronto investigativo, embora a individualizacao '
                'completa do fabricante/modelo continue dependente de assinaturas visuais adicionais.'
            )
        else:
            summary = (
                'Apos confronto entre OCR, arquitetura visual e compatibilidade das assinaturas, '
                f'o conjunto mostra-se {humanize_pericial_label(level)} para {maker}/{model} '
                f'na faixa {year}, com base predominante em {body}.'
            )

    if supporting:
        summary += ' Principais sustentacoes: ' + '; '.join(supporting) + '.'

    return {
        'decision': decision,
        'level': level,
        'display_decision': humanize_pericial_label(decision),
        'display_level': humanize_pericial_label(level),
        'score': round(score_total, 1),
        'manual_review_required': manual_review,
        'strong_ocr_evidence': strong_ocr,
        'summary': summary,
        'supporting_items': supporting,
        'inconclusive': decision == 'inconclusivo',
    }


def build_operational_protocol(context=None):
    context = context if isinstance(context, dict) else {}

    quality_triage = _build_quality_triage(context)
    ocr_record = _build_ocr_record(context)
    vehicle_basics = _infer_vehicle_basics(context)
    compatibility_matrix = _build_compatibility_matrix(context, ocr_record, quality_triage, vehicle_basics)
    exclusion_checks = _build_exclusion_checks(context, quality_triage, ocr_record, compatibility_matrix)
    conclusion = _build_conclusion(context, quality_triage, vehicle_basics, compatibility_matrix, exclusion_checks, ocr_record=ocr_record)
    evidence_preservation = _build_evidence_preservation(context)

    protocol_status = 'ok'
    if conclusion.get('decision') == 'conclusivo' and not conclusion.get('manual_review_required'):
        if quality_triage.get('class') == 'C' or compatibility_matrix.get('level') in ('INCOMPATIVEL', 'POUCO_COMPATIVEL'):
            protocol_status = 'atencao'
        else:
            protocol_status = 'ok'
    elif quality_triage.get('class') == 'D' or quality_triage.get('manual_review'):
        protocol_status = 'revisao_obrigatoria'
    elif quality_triage.get('class') == 'C' or compatibility_matrix.get('level') in ('INCOMPATIVEL', 'POUCO_COMPATIVEL'):
        protocol_status = 'atencao'

    checklist = list(OPERATIONAL_CHECKLIST)
    source_checklist = _as_list(_as_dict(context.get('operational_checklist')).get('items', []))
    if source_checklist:
        checklist.extend([str(item) for item in source_checklist if str(item).strip()])

    return {
        'status': protocol_status,
        'evidence_preservation': evidence_preservation,
        'quality_triage': quality_triage,
        'ocr_record': ocr_record,
        'vehicle_basics': vehicle_basics,
        'compatibility_matrix': compatibility_matrix,
        'exclusion_checks': exclusion_checks,
        'conclusion': conclusion,
        'checklist_operacional': _unique_preserve_order(checklist),
        'summary': conclusion.get('summary', ''),
    }
