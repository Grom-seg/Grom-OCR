"""Structured vehicle confrontation form derived from the operational protocol."""

import re
import unicodedata

from utils import vehicle_analysis_protocol as vehicle_analysis_protocol_module


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


def _unique_preserve_order(values):
    seen = set()
    ordered = []
    for value in _as_list(values):
        text = str(value).strip()
        if not text:
            continue
        key = _normalize_text(text)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered


def _normalize_text(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.upper().strip()
    text = re.sub(r'[^A-Z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _compatibility_label(score):
    score = max(0.0, min(100.0, _safe_float(score, 0.0)))
    if score >= 90.0:
        return 'muito provavelmente correspondente'
    if score >= 75.0:
        return 'fortemente compativel'
    if score >= 60.0:
        return 'compativel'
    if score >= 40.0:
        return 'pouco compativel'
    return 'incompativel'


def _presence_text(component):
    component = _as_dict(component)
    status = _normalize_text(component.get('status', ''))
    confidence = _safe_float(component.get('confianca', 0.0), 0.0)
    if status in ('SIM', 'DETECTADO', 'PRESENTE', 'PAR_DETECTADO', 'PAR_VERTICAL', 'VINCOS_VISIVEIS'):
        return 'Sim'
    if status in ('PARCIAL', 'FRACA', 'LINHA_PARCIAL'):
        return 'Parcial'
    if status in ('NAO', 'NAO_DETECTADO', 'NAO_DETECTADA', 'AUSENTE'):
        return 'Nao'
    if confidence >= 55.0:
        return 'Parcial'
    return 'Indefinido'


def _match_matrix(matrix, names):
    matrix = _as_dict(matrix)
    items = _as_list(matrix.get('items', []))
    wanted = [_normalize_text(name) for name in names]
    scores = []
    labels = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _normalize_text(item.get('criterio', ''))
        if not label or not any(name in label for name in wanted):
            continue
        max_score = _safe_float(item.get('peso_maximo', 0.0), 0.0)
        score = _safe_float(item.get('pontuacao', 0.0), 0.0)
        if max_score > 0:
            scores.append((score / max_score) * 100.0)
        labels.append(f"{item.get('criterio', '-')}: {score:.1f}/{max_score:.1f}")
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    return avg_score, labels


def _feature(component, label, fallback=''):
    component = _as_dict(component)
    detail = str(component.get('detalhe', fallback) or '').strip()
    return {
        'label': label,
        'status': _presence_text(component),
        'confidence': round(_safe_float(component.get('confianca', 0.0), 0.0), 1),
        'detail': detail or '-',
    }


def _timestamp_parts(value):
    text = str(value or '').replace('Z', '+00:00').strip()
    if not text:
        return {'date': '', 'time': ''}
    try:
        dt = __import__('datetime').datetime.fromisoformat(text)
    except Exception:
        return {'date': '', 'time': ''}
    return {'date': dt.strftime('%d/%m/%Y'), 'time': dt.strftime('%H:%M')}


def _build_conditions(quality_report, capture_integrity):
    text = ' '.join([
        _normalize_text(quality_report.get('issues', [])),
        _normalize_text(capture_integrity.get('issues', [])),
        _normalize_text(capture_integrity.get('score_breakdown_text', '')),
    ])
    conditions = []
    if any(token in text for token in ('BLUR', 'BORR', 'MOVIMENTO', 'DESFOCO')):
        conditions.append('borramento por movimento')
    if 'REFLEX' in text:
        conditions.append('reflexo')
    if 'CONTRALUZ' in text:
        conditions.append('contraluz')
    if any(token in text for token in ('BAIXA LUZ', 'LOW LIGHT', 'ESCURA', 'LOWLIGHT')):
        conditions.append('baixa iluminacao')
    if any(token in text for token in ('ESTOUR', 'OVEREXPOSE', 'BRILHO')):
        conditions.append('excesso de iluminacao')
    if any(token in text for token in ('OBSTRU', 'OCCLUS', 'PARCIAL')):
        conditions.append('obstrucao parcial')
    if any(token in text for token in ('CHUVA', 'SUJEIRA', 'MUD')):
        conditions.append('chuva/sujeira')
    if any(token in text for token in ('COMPRESS', 'JPEG')):
        conditions.append('compressao excessiva')
    if any(token in text for token in ('ANGULO', 'PERSPECT')):
        conditions.append('angulo desfavoravel')
    if not conditions:
        conditions.append('foco adequado')
    return conditions


def build_vehicle_confrontation_form(context=None):
    context = context if isinstance(context, dict) else {}
    operational = _as_dict(context.get('operational_protocol'))
    if not operational:
        operational = vehicle_analysis_protocol_module.build_operational_protocol(context)

    visual_profile = _as_dict(context.get('visual_profile'))
    pericial = _as_dict(context.get('pericial'))
    input_meta = _as_dict(context.get('input_meta'))
    report_context = _as_dict(context.get('report_context'))
    quality_report = _as_dict(context.get('quality_report'))
    capture_integrity = _as_dict(context.get('capture_integrity') or pericial.get('capture_integrity'))
    operational_evidence = _as_dict(operational.get('evidence_preservation'))
    ocr_record = _as_dict(operational.get('ocr_record'))
    vehicle_basics = _as_dict(operational.get('vehicle_basics'))
    matrix = _as_dict(operational.get('compatibility_matrix'))
    exclusions = _as_dict(operational.get('exclusion_checks'))
    conclusion = _as_dict(operational.get('conclusion'))

    source_filename = str(
        operational_evidence.get('source_filename')
        or report_context.get('photo_filename')
        or context.get('photo_filename')
        or ''
    ).strip()
    capture_ts = _timestamp_parts(operational_evidence.get('capture_timestamp_utc') or context.get('capture_timestamp_utc'))
    responsible = str(
        context.get('responsavel')
        or report_context.get('responsavel')
        or 'Operador autenticado'
    ).strip() or 'Operador autenticado'

    raw_plate_text = str(ocr_record.get('leitura_principal', '-'))
    plate_full = raw_plate_text
    partial_plate_text = str(ocr_record.get('partial_plate_text', '') or '').strip()
    partial_plate_candidates = _as_list(ocr_record.get('partial_plate_candidates', []))
    partial_plate_summary = str(ocr_record.get('partial_plate_summary', '') or '').strip()
    plate_partial = partial_plate_text if partial_plate_text else (raw_plate_text if bool(ocr_record.get('partial_plate')) else '-')
    if len(str(plate_full).replace(' ', '')) != 7:
        plate_full = '-'

    front_score, front_labels = _match_matrix(matrix, ('Farois', 'Grade dianteira', 'Parachoques', 'Emblemas / inscricoes'))
    rear_score, rear_labels = _match_matrix(matrix, ('Lanternas traseiras', 'Parachoques', 'Emblemas / inscricoes'))
    side_score, side_labels = _match_matrix(matrix, ('Linha lateral / vidros / colunas', 'Macanetas / retrovisores / detalhes'))
    wheel_score, wheel_labels = _match_matrix(matrix, ('Rodas / calotas',))
    interior_score, interior_labels = _match_matrix(matrix, ('Painel / interior',))

    main_hypothesis = _as_dict(_as_dict(visual_profile).get('hipotese_principal'))
    alt_hypotheses = []

    score_total = _safe_float(
        matrix.get('score_total')
        or matrix.get('pontuacao_final')
        or matrix.get('score')
        or 0.0,
        0.0,
    )
    summary = str(conclusion.get('summary', '') or operational.get('summary', '') or '').strip()

    material_items = [
        {'label': 'Imagem original', 'available': True},
        {'label': 'Imagem ampliada', 'available': bool(operational_evidence.get('visual_scene_filename'))},
        {'label': 'Frame de video', 'available': _normalize_text(input_meta.get('input_type') or report_context.get('input_type')) in ('VIDEO', 'FRAME', 'MP4', 'MOV', 'AVI', 'MKV', 'WEBM')},
        {'label': 'Recorte frontal', 'available': _normalize_text(_as_dict(visual_profile).get('vista_detectada', '')) == 'FRONTAL'},
        {'label': 'Recorte traseiro', 'available': _normalize_text(_as_dict(visual_profile).get('vista_detectada', '')) == 'TRASEIRA'},
        {'label': 'Recorte lateral', 'available': _normalize_text(_as_dict(visual_profile).get('vista_detectada', '')) == 'LATERAL'},
        {'label': 'Recorte da placa', 'available': bool(operational_evidence.get('plate_filename'))},
        {'label': 'Recorte do interior', 'available': bool(_as_dict(context.get('vehicle_interior')) or _as_dict(context.get('interior_profile')))},
        {'label': 'Resultado de OCR', 'available': bool(ocr_record)},
        {'label': 'Outra fonte comparativa', 'available': bool(_as_dict(visual_profile).get('comparativo_fontes_abertas') or _as_dict(context.get('external_systems_comparison')))},
    ]

    front_components = _as_dict(_as_dict(visual_profile).get('assinaturas_componentes', {})).get('componentes', {})
    front_components = _as_dict(front_components)
    emblema = _feature(front_components.get('emblema_frontal', {}), 'logotipo central')
    farois = _feature(front_components.get('farois_dianteiros', {}), 'formato dos farois')
    grade = _feature(front_components.get('grade_dianteira', {}), 'desenho da grade')
    capo = _feature(front_components.get('capo_dianteiro', {}), 'vincos do capo')
    lanternas = _feature(front_components.get('lanternas_traseiras', {}), 'formato das lanternas')
    portas = _feature(front_components.get('linhas_portas', {}), 'linha das janelas / colunas')

    plate_pattern = str(ocr_record.get('padrao_placa', 'Indefinido'))
    if conclusion.get('decision') == 'inconclusivo':
        plate_compatibility = 'inconclusivo'
    else:
        plate_compatibility = _compatibility_label(score_total)

    vehicle_form = {
        'status': 'ok' if operational else 'indefinido',
        'identificacao': {
            'numero_analise': str(operational_evidence.get('analysis_id') or context.get('analysis_id') or report_context.get('analysis_id') or '').strip() or '-',
            'data': capture_ts.get('date', ''),
            'hora': capture_ts.get('time', ''),
            'responsavel': responsible,
            'origem_imagem': str(operational_evidence.get('origem') or context.get('origem') or input_meta.get('input_type') or 'indefinida'),
            'arquivo': source_filename or '-',
            'local': str(context.get('capture_location') or report_context.get('capture_location') or input_meta.get('capture_location') or '-'),
            'observacoes_iniciais': summary or '-',
        },
        'material_examined': {
            'items': material_items,
            'count': sum(1 for item in material_items if item.get('available')),
        },
        'quality': {
            'class': str(_as_dict(operational.get('quality_triage')).get('class', 'D')),
            'label': str(_as_dict(operational.get('quality_triage')).get('label', 'indefinida')),
            'conditions': _build_conditions(quality_report, capture_integrity),
            'observations': _unique_preserve_order(
                [str(item) for item in _as_list(quality_report.get('issues', []))[:4]]
                + [str(item) for item in _as_list(capture_integrity.get('issues', []))[:4]]
            ),
        },
        'ocr': {
            'plate_full': plate_full,
            'plate_partial': plate_partial,
            'partial_text': partial_plate_text or '-',
            'partial_summary': partial_plate_summary or '-',
            'partial_candidates': partial_plate_candidates[:4],
            'partial_candidates_count': len(partial_plate_candidates),
            'main': str(plate_full if plate_full != '-' else ocr_record.get('leitura_principal', '-')),
            'alternatives': _as_list(ocr_record.get('leitura_alternativas', []))[:2],
            'uncertain_chars': str(ocr_record.get('caracteres_incertos_resumo', '-')),
            'uncertain_positions': _as_list(ocr_record.get('caracteres_incertos', [])),
            'confidence': round(
                _safe_float(
                    ocr_record.get('confidencia_estimativa')
                    or ocr_record.get('confidence_percent')
                    or ocr_record.get('confidence')
                    or ocr_record.get('avg_conf')
                    or 0.0,
                    0.0,
                ),
                1,
            ),
            'pattern': plate_pattern,
        },
        'textual_elements': {
            'marca_visivel': bool(str(main_hypothesis.get('fabricante', '')).strip()),
            'modelo_visivel': bool(str(main_hypothesis.get('modelo', '')).strip()),
            'versao_visivel': bool(str(main_hypothesis.get('versao_probavel', '')).strip()),
            'emblema_visivel': emblema['status'] in ('Sim', 'Parcial'),
            'adesivo_visivel': any('ADESIVO' in _normalize_text(item.get('descricao', '')) for item in _as_list(_as_dict(_as_dict(visual_profile).get('caracteristicas_forenses', {})).get('achados', [])) if isinstance(item, dict)),
            'outro_texto_visivel': bool(_normalize_text(ocr_record.get('raw_text', '')) and _normalize_text(ocr_record.get('raw_text', '')) != _normalize_text(ocr_record.get('leitura_principal', ''))),
        },
        'vehicle_classification': {
            'tipo': str(vehicle_basics.get('categoria_primaria', 'indefinido')),
            'porte': str(vehicle_basics.get('porte', 'indefinido')),
            'cor': str(_as_dict(visual_profile).get('cor_probavel', 'indefinida')),
            'num_portas': str(vehicle_basics.get('numero_portas_visiveis_estimado', 'indefinido')),
            'carroceria': str(vehicle_basics.get('volume_traseiro', 'indefinido')),
            'placa_posicao': str(vehicle_basics.get('posicao_placa', 'indefinida')),
            'vidro_traseiro': str(vehicle_basics.get('formato_vidro_traseiro', 'indefinida')),
            'coluna_cd': str(vehicle_basics.get('coluna_c', 'indefinida')),
            'altura_solo': 'alta' if _normalize_text(vehicle_basics.get('categoria_primaria', '')) in ('SUV', 'PICAPE CAMINHONETE', 'MOTOCICLETA') else ('baixa' if _normalize_text(vehicle_basics.get('categoria_primaria', '')) == 'SEDAN' else 'media'),
        },
        'confrontacao_externa': {
            'frente': {'features': [farois, grade, emblema, capo], 'score': round(front_score, 1), 'compatibility': _compatibility_label(front_score), 'description': ' | '.join(front_labels) or '-'},
            'traseira': {'features': [lanternas, emblema, capo], 'score': round(rear_score, 1), 'compatibility': _compatibility_label(rear_score), 'description': ' | '.join(rear_labels) or '-'},
            'lateral': {'features': [portas], 'score': round(side_score, 1), 'compatibility': _compatibility_label(side_score), 'description': ' | '.join(side_labels) or '-'},
            'rodas': {'features': [], 'score': round(wheel_score, 1), 'compatibility': _compatibility_label(wheel_score), 'description': ' | '.join(wheel_labels) or '-'},
        },
        'confrontacao_interna': {
            'available': bool(_as_dict(context.get('vehicle_interior')) or _as_dict(context.get('interior_profile'))),
            'score': round(interior_score, 1),
            'compatibility': _compatibility_label(interior_score),
            'description': ' | '.join(interior_labels) or '-',
        },
        'hipotese_principal': {
            'fabricante': str(main_hypothesis.get('fabricante', '-')),
            'modelo': str(main_hypothesis.get('modelo', '-')),
            'versao': str(main_hypothesis.get('versao_probavel', main_hypothesis.get('versao', '-'))),
            'geracao': str(main_hypothesis.get('geracao', main_hypothesis.get('geracao_probavel', '-'))),
            'faixa_ano': str(main_hypothesis.get('faixa_ano_modelo', '-')),
            'confianca': round(
                _safe_float(
                    main_hypothesis.get('confianca')
                    or main_hypothesis.get('confidence')
                    or main_hypothesis.get('confianca_modelo')
                    or main_hypothesis.get('confianca_hipotese_visual')
                    or 0.0,
                    0.0,
                ),
                1,
            ),
        },
        'hipoteses_alternativas': alt_hypotheses,
        'elementos_favoraveis': _unique_preserve_order(_as_list(_as_dict(conclusion).get('supporting_items', [])) or _as_list(_as_dict(operational.get('compatibility_matrix')).get('summary', []))),
        'elementos_excludentes': _unique_preserve_order([
            f"{item.get('label', '-')}: {item.get('status', 'indefinido')} ({item.get('reason', '-')})"
            for item in _as_list(exclusions.get('items', []))
            if isinstance(item, dict) and item.get('status') not in ('ok', 'valida', 'inativa', 'baixo', 'indisponivel')
        ]),
        'cruzamento_ocr': {
            'placa_parcial': plate_partial,
            'fragmento_parcial': partial_plate_text or '-',
            'padrao': plate_pattern,
            'compatibilidade': plate_compatibility,
            'observacoes': _unique_preserve_order([
                f"placa_parcial={plate_partial}",
                f"fragmento_parcial={partial_plate_text or '-'}",
                f"padrao={plate_pattern}",
                f"score={score_total:.1f}",
            ]),
        },
        'matriz': {
            'itens': [
                {
                    'criterio': str(item.get('criterio', '-')),
                    'nota': round(_safe_float(item.get('pontuacao', 0.0), 0.0), 1),
                    'maximo': round(_safe_float(item.get('peso_maximo', 0.0), 0.0), 1),
                    'status': str(item.get('status', 'indefinido')),
                    'fonte': str(item.get('fonte', 'local')),
                }
                for item in _as_list(matrix.get('items', []))
                if isinstance(item, dict)
            ],
            'pontuacao_final': round(score_total, 1),
            'faixa': str(matrix.get('level', 'INCOMPATIVEL')),
            'interpretacao': _compatibility_label(score_total),
        },
        'conclusao': {
            'marca': 'inconclusivo' if conclusion.get('decision') == 'inconclusivo' else _compatibility_label(score_total),
            'texto': summary or 'Analise sem conclusao textual disponivel.',
            'resultado': str(conclusion.get('decision', 'inconclusivo')),
            'nivel': str(conclusion.get('level', 'INCOMPATIVEL')),
        },
        'encerramento': {
            'responsavel_preenchimento': responsible,
            'cargo_funcao': str(context.get('cargo_funcao') or report_context.get('cargo_funcao') or 'Pericia / analise tecnica'),
            'data': capture_ts.get('date', ''),
            'assinatura': '____________________________',
            'rubrica': 'assinatura/rubrica',
        },
        'checklist_rapido': {
            'identificacao': 'ok' if source_filename else 'indefinido',
            'qualidade': str(_as_dict(operational.get('quality_triage')).get('class', 'D')),
            'veiculo': str(vehicle_basics.get('categoria_primaria', 'indefinido')),
            'elementos_visiveis': 'ok' if any(item.get('available') for item in material_items) else 'indefinido',
            'hipotese': str(main_hypothesis.get('modelo', '-')),
            'resultado': str(conclusion.get('decision', 'inconclusivo')),
        },
    }

    return vehicle_form
