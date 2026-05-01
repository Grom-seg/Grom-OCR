from fpdf import FPDF
from PIL import Image, ExifTags
import datetime
import os

from utils.report_branding import (
    apply_formal_report_palette,
    draw_report_cover_header,
    draw_report_footer,
    draw_report_section_header,
    draw_report_watermark,
    get_image_dimensions,
    resolve_report_logo_path,
)
from utils.pericial_labels import (
    format_report_label,
    format_report_value,
    humanize_engine_health_label,
    humanize_official_validation_label,
    humanize_official_validation_source_kind_label,
    humanize_official_validation_source_label,
    humanize_pericial_label,
    humanize_roi_quality_label,
    humanize_scene_label,
)
from utils.report_visuals import build_capture_comparison_sheet
from utils.evidence_manifest import build_evidence_manifest, manifest_summary_dict
from utils.report_outline import get_analysis_report_outline


def extract_exif(filepath):
    try:
        img = Image.open(filepath)
        exif_data = img._getexif()
        if not exif_data:
            return {}
        exif = {ExifTags.TAGS.get(key, key): value for key, value in exif_data.items()}
        return exif
    except Exception:
        return {}


def normalize_pdf_text(value):
    text = '' if value is None else str(value)
    return text.encode('latin-1', 'replace').decode('latin-1')


def resolve_brand_logo_path():
    return resolve_report_logo_path()


class AnalysisReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=28)
        self.set_margins(12, 18, 12)
        self.add_page()
        self.set_font('Arial', size=12)
        apply_formal_report_palette(self)

    def _draw_watermark(self):
        draw_report_watermark(self, logo_path=resolve_report_logo_path())

    def header(self):
        self._draw_watermark()

    def footer(self):
        draw_report_footer(self, logo_path=resolve_report_logo_path())


def write_key_values(pdf, data):
    if not isinstance(data, dict) or not data:
        pdf.multi_cell(0, 8, normalize_pdf_text('Sem dados disponíveis.'))
        return

    for key, value in data.items():
        pdf.multi_cell(0, 8, normalize_pdf_text(f'{format_report_label(key)}: {format_report_value(value)}'))


def write_section_title(pdf, title):
    draw_report_section_header(pdf, format_report_label(title), level='section')
    pdf.set_font('Arial', '', 10)


def _resolve_evidence_manifest(report_data, analysis_kind=None):
    manifest = report_data.get('evidence_manifest', {})
    if isinstance(manifest, dict) and manifest:
        return manifest
    return build_evidence_manifest(report_data, analysis_kind=analysis_kind)


def write_evidence_manifest_section(pdf, report_data, analysis_kind=None):
    manifest = _resolve_evidence_manifest(report_data, analysis_kind=analysis_kind)
    if not isinstance(manifest, dict) or not manifest:
        pdf.multi_cell(0, 8, normalize_pdf_text('Manifesto pericial indisponível.'))
        return

    write_section_title(pdf, 'Manifesto pericial e cadeia de custódia:')
    write_key_values(pdf, manifest_summary_dict(manifest))
    custody = manifest.get('custody', {})
    if isinstance(custody, dict):
        step_summary = str(custody.get('step_summary', '') or '').strip()
        if step_summary:
            pdf.multi_cell(
                0,
                7,
                normalize_pdf_text(
                    'Etapas registradas: ' + step_summary + '.'
                ),
            )
    pdf.ln(1)


def write_report_outline(pdf, outline=None):
    outline = _safe_report_list(outline) or get_analysis_report_outline()
    if not outline:
        pdf.multi_cell(0, 8, normalize_pdf_text('Procedimentos informados indisponiveis.'))
        return

    pdf.set_font('Arial', 'B', 10)
    pdf.multi_cell(0, 7, normalize_pdf_text('Procedimentos efetuados na análise:'))
    pdf.set_font('Arial', '', 10)

    for section in outline:
        if not isinstance(section, dict):
            continue
        number = str(section.get('number', '') or '').strip()
        title = str(section.get('title', '') or '').strip()
        summary = str(section.get('summary', '') or '').strip()
        subitems = _safe_report_list(section.get('subitems'))

        heading = f'{number} - {title}'.strip(' -')
        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 6, normalize_pdf_text(heading))
        if summary:
            pdf.set_font('Arial', '', 9)
            pdf.multi_cell(0, 5, normalize_pdf_text(summary))

        for subitem in subitems:
            if not isinstance(subitem, dict):
                continue
            sub_number = str(subitem.get('number', '') or '').strip()
            sub_title = str(subitem.get('title', '') or '').strip()
            sub_summary = str(subitem.get('summary', '') or '').strip()
            sub_heading = f'  {sub_number} - {sub_title}'.strip()
            pdf.set_font('Arial', 'B', 9)
            pdf.multi_cell(0, 5, normalize_pdf_text(sub_heading))
            if sub_summary:
                pdf.set_font('Arial', '', 8.5)
                pdf.multi_cell(0, 5, normalize_pdf_text(f'    {sub_summary}'))
        pdf.ln(1)

    pdf.set_font('Arial', '', 10)


def mask_sensitive_value(value, visible_tail=4):
    text = '' if value is None else str(value).strip()
    if not text:
        return ''

    compact = ''.join(text.split())
    if compact == '':
        return text

    if visible_tail <= 0:
        return '*' * max(1, len(compact))
    if len(compact) <= visible_tail:
        return '*' * max(1, len(compact))

    return ('*' * max(1, len(compact) - visible_tail)) + compact[-visible_tail:]


def sanitize_vehicle_info_for_report(vehicle_info):
    vehicle = dict(vehicle_info) if isinstance(vehicle_info, dict) else {}
    if not vehicle:
        return {}

    fields_to_mask = {
        'chassi': 4,
        'renavam': 4,
        'proprietario': 0,
        'cpf_cnpj': 0,
        'endereco': 0,
        'estampador': 0,
        'codigo_seguranca_crv': 3,
        'serial_qrcode': 4,
    }
    for field, visible_tail in fields_to_mask.items():
        value = vehicle.get(field)
        if value is None or str(value).strip() == '':
            continue
        vehicle[field] = mask_sensitive_value(value, visible_tail) if visible_tail > 0 else '[restrito]'

    return vehicle


def write_official_vehicle_validation(pdf, validation):
    validation = validation if isinstance(validation, dict) else {}
    if not validation:
        pdf.multi_cell(0, 8, normalize_pdf_text('Validação oficial pós-placa indisponível.'))
        return

    public_found = validation.get('public_fields_found', [])
    if not isinstance(public_found, list):
        public_found = []
    public_missing = validation.get('public_fields_missing', [])
    if not isinstance(public_missing, list):
        public_missing = []
    sensitive_found = validation.get('sensitive_fields_found', [])
    if not isinstance(sensitive_found, list):
        sensitive_found = []
    notes = validation.get('notes', [])
    if not isinstance(notes, list):
        notes = []

    write_key_values(pdf, {
        'validacao_status': humanize_official_validation_label(validation.get('status', 'indefinido')),
        'validacao_oficial': 'Sim' if validation.get('is_official') else 'Nao',
        'validacao_tipo_fonte': humanize_official_validation_source_kind_label(validation.get('source_kind', 'indefinida')),
        'validacao_fonte': humanize_official_validation_source_label(validation.get('source_label', 'indefinida')),
        'validacao_placa_consultada': validation.get('lookup_plate', '-'),
        'validacao_campos_publicos': ', '.join([str(item) for item in public_found]) or '-',
        'validacao_campos_publicos_ausentes': ', '.join([str(item) for item in public_missing]) or '-',
        'validacao_campos_restritos': ', '.join([str(item) for item in sensitive_found]) or '-',
        'validacao_politica_sensiveis': validation.get('sensitive_policy', 'mascarado_por_padrao'),
        'validacao_notas': '; '.join([str(item) for item in notes if str(item).strip()]) or '-',
    })


def write_vehicle_identification(pdf, vehicle_info):
    vehicle = sanitize_vehicle_info_for_report(vehicle_info)
    if not vehicle:
        pdf.multi_cell(0, 8, normalize_pdf_text('Sem dados veiculares disponiveis.'))
        return

    validation = vehicle.pop('official_validation', {})
    if not isinstance(validation, dict):
        validation = {}

    ordered_fields = [
        ('placa', 'Placa'),
        ('fabricante', 'Fabricante'),
        ('marca_modelo', 'Marca/Modelo bruto'),
        ('modelo', 'Modelo'),
        ('ano', 'Ano'),
        ('cor', 'Cor'),
        ('categoria', 'Categoria'),
        ('uf', 'UF'),
        ('cidade', 'Cidade'),
        ('municipio', 'Municipio'),
        ('chassi', 'Chassi'),
        ('renavam', 'Renavam'),
        ('restricoes', 'Restricoes'),
        ('estampador', 'Estampador'),
        ('fipe_preco_medio', 'FIPE preco medio'),
        ('fipe_codigo', 'FIPE codigo'),
        ('fipe_ano_modelo', 'FIPE ano/modelo'),
        ('fonte', 'Fonte'),
        ('fonte_complementar', 'Fonte complementar'),
        ('fontes_utilizadas', 'Fontes utilizadas'),
        ('consulta_status', 'Consulta status'),
        ('consulta_evento', 'Consulta evento'),
        ('consulta_request_id', 'Consulta request id'),
        ('consulta_detalhe', 'Consulta detalhe'),
        ('consulta_multifonte_status', 'Consulta multicamada'),
        ('consulta_multifonte_candidatos', 'Fontes consultadas'),
        ('consulta_multifonte_confianca', 'Confiança da consulta'),
        ('consulta_multifonte_taxa_consenso', 'Taxa de consenso'),
        ('consulta_multifonte_score', 'Score da melhor fonte'),
        ('consulta_multifonte_limite', 'Limite de fontes'),
        ('consulta_multifonte_limite_aplicado', 'Limite aplicado'),
        ('consulta_multifonte_fontes', 'Fontes consolidadas'),
        ('consulta_multifonte_oficiais', 'Fontes oficiais'),
        ('consulta_multifonte_consenso', 'Campos em consenso'),
        ('consulta_multifonte_divergencias', 'Divergencias'),
        ('consulta_multifonte_resumo', 'Resumo da consulta'),
        ('consulta_multifonte_fonte_principal', 'Fonte principal'),
        ('consulta_multifonte_fonte_tipo', 'Tipo da fonte'),
        ('consulta_multifonte_alertas', 'Alertas da consulta'),
    ]

    rendered = {}
    for key, label in ordered_fields:
        value = vehicle.get(key)
        if value is None or str(value).strip() == '':
            continue
        rendered[label] = value

    for key, value in vehicle.items():
        if key in ('official_validation',):
            continue
        if str(value).strip() == '' or key in [field for field, _ in ordered_fields]:
            continue
        rendered[key] = value

    write_key_values(pdf, rendered)
    if validation:
        pdf.multi_cell(0, 8, normalize_pdf_text('Validação oficial pós-placa:'))
        write_official_vehicle_validation(pdf, validation)


def write_ocr_engines(pdf, ocr_data, engine_status=None, engine_summary=None, engine_runtime=None):
    ocr_data = ocr_data if isinstance(ocr_data, dict) else {}
    engine_status = engine_status if isinstance(engine_status, dict) else {}
    engine_summary = engine_summary if isinstance(engine_summary, dict) else {}
    engine_runtime = engine_runtime if isinstance(engine_runtime, dict) else {}

    if engine_summary:
        write_key_values(pdf, {
            'Motores registrados': engine_summary.get('engines_registered', 0),
            'Motores configurados': engine_summary.get('engines_configured', 0),
            'Motores disponiveis': engine_summary.get('engines_available', 0),
            'Motores prontos': engine_summary.get('engines_ready', 0),
            'Motores executados': engine_summary.get('engines_executed', 0),
            'Motores com texto': engine_summary.get('engines_with_text', 0),
            'Motores sem texto': engine_summary.get('engines_without_text', 0),
            'Motores pulados': engine_summary.get('engines_skipped', 0),
            'Motores falhos': engine_summary.get('engines_failed', 0),
            'Motores desabilitados': engine_summary.get('engines_disabled', 0),
            'Motores indisponiveis': engine_summary.get('engines_unavailable', 0),
            'Calibracao do reranking': humanize_pericial_label(engine_summary.get('reranking_calibration_source', 'builtin_default')),
            'Arquivo da calibracao': engine_summary.get('reranking_calibration_path', '-'),
            'Versao da calibracao': engine_summary.get('reranking_calibration_version', 'builtin_default'),
        })
        pdf.ln(1)

    engine_names = list(ocr_data.keys())
    for name in engine_status.keys():
        if name not in engine_names:
            engine_names.append(name)

    if not engine_names:
        pdf.multi_cell(0, 8, normalize_pdf_text('Nenhum motor de análise OCR registrado na execução.'))
        return

    runtime_warnings = []
    for name, runtime in engine_runtime.items():
        if not isinstance(runtime, dict):
            continue
        error = str(runtime.get('error', '') or '').strip()
        if not error:
            continue
        runtime_warnings.append(f'{name}: {error}')

    if runtime_warnings:
        pdf.multi_cell(0, 8, normalize_pdf_text('Estado operacional dos motores: ' + ' | '.join(runtime_warnings[:4])))

    for engine in engine_names:
        payload = ocr_data.get(engine, {}) if isinstance(ocr_data.get(engine, {}), dict) else {}
        status_payload = engine_status.get(engine, {}) if isinstance(engine_status.get(engine, {}), dict) else {}
        text = payload.get('text', '')
        score = payload.get('score', 0)
        avg_conf = payload.get('avg_conf', 0)
        pattern = payload.get('pattern', 'Indefinido')
        status_name = humanize_engine_health_label(status_payload.get('status', 'indefinido'))
        reason = str(status_payload.get('reason', '-'))
        runtime_info = engine_runtime.get(engine, {}) if isinstance(engine_runtime.get(engine, {}), dict) else {}
        runtime_error = str(runtime_info.get('error', '')).strip()
        executed = 'sim' if bool(status_payload.get('executed', False)) else 'nao'
        line = (
            f'Motor: {engine} | Status: {status_name} | Executado: {executed} | '
            f'Texto: {text or "-"} | Pontuação: {score} | Confiança: {avg_conf}% | '
            f'Padrão: {pattern} | Motivo: {reason}'
        )
        if runtime_error:
            line += f' | Runtime: {runtime_error}'
        pdf.multi_cell(0, 8, normalize_pdf_text(line))


def write_consensus(pdf, consensus):
    if not isinstance(consensus, dict) or not consensus:
        pdf.multi_cell(0, 8, normalize_pdf_text('Consenso OCR indisponível.'))
        return

    consensus_text = str(consensus.get('best_text', '') or '').strip() or 'Não conclusivo'
    write_key_values(pdf, {
        'Placa consensual': consensus_text,
        'Motores considerados': consensus.get('engines_considered', 0),
        'Motores em acordo': consensus.get('agreement_count', 0),
        'Taxa de acordo': f"{consensus.get('agreement_ratio', 0)}%",
        'Motores concordantes': ', '.join(consensus.get('agreeing_engines', [])),
    })


def write_forensic_chain(pdf, forensic):
    if not isinstance(forensic, dict) or not forensic:
        pdf.multi_cell(0, 8, normalize_pdf_text('Cadeia de custódia indisponível.'))
        return

    write_key_values(pdf, {
        'Identificador da análise': forensic.get('analysis_id', '-'),
        'Inicio da cadeia (UTC)': forensic.get('started_at_utc', forensic.get('created_at_utc', '-')),
        'Fim da cadeia (UTC)': forensic.get('finished_at_utc', forensic.get('updated_at_utc', '-')),
        'Hash SHA-256 da fonte': forensic.get('source_sha256', '-'),
        'Hash SHA-256 do recorte': forensic.get('plate_sha256', forensic.get('crop_sha256', '-')),
        'Assinatura digital': forensic.get('signature', '-'),
        'Algoritmo de assinatura': forensic.get('signature_algorithm', 'SHA256'),
    })


def write_assessment(pdf, assessment):
    if not isinstance(assessment, dict) or not assessment:
        pdf.multi_cell(0, 8, normalize_pdf_text('Classificação técnico-probatória indisponível.'))
        return

    reasons = assessment.get('reasons', [])
    if isinstance(reasons, list):
        reasons_text = '; '.join([humanize_pericial_label(item) for item in reasons if str(item).strip() != ''])
    else:
        reasons_text = humanize_pericial_label(reasons)

    write_key_values(pdf, {
        'Nivel tecnico-probatorio': humanize_pericial_label(assessment.get('display_evidence_level', assessment.get('evidence_level', 'BAIXA'))),
        'Confianca da inferencia': f"{assessment.get('confidence_percent', 0)}%",
        'Ratificacao manual obrigatoria': 'Sim' if assessment.get('manual_review_required') else 'Nao',
        'Fundamentos tecnicos': reasons_text or '-',
    })


def write_pericial(pdf, pericial):
    if not isinstance(pericial, dict) or not pericial:
        pdf.multi_cell(0, 8, normalize_pdf_text('Validação pericial indisponível.'))
        return

    quality = pericial.get('quality', {}) if isinstance(pericial.get('quality', {}), dict) else {}
    legal = pericial.get('legal_validation', {}) if isinstance(pericial.get('legal_validation', {}), dict) else {}
    ambiguity = pericial.get('character_ambiguity', {}) if isinstance(pericial.get('character_ambiguity', {}), dict) else {}
    cross_checks = pericial.get('cross_checks', {}) if isinstance(pericial.get('cross_checks', {}), dict) else {}
    local_history = cross_checks.get('local_history', {}) if isinstance(cross_checks.get('local_history', {}), dict) else {}
    external_source = cross_checks.get('external_source', {}) if isinstance(cross_checks.get('external_source', {}), dict) else {}
    official_validation = cross_checks.get('official_vehicle_validation', {}) if isinstance(cross_checks.get('official_vehicle_validation', {}), dict) else {}
    external_systems = cross_checks.get('external_systems', {}) if isinstance(cross_checks.get('external_systems', {}), dict) else {}
    visual_profile = cross_checks.get('visual_profile', {}) if isinstance(cross_checks.get('visual_profile', {}), dict) else {}
    capture_integrity = cross_checks.get('capture_integrity', {}) if isinstance(cross_checks.get('capture_integrity', {}), dict) else {}
    critical = pericial.get('critical_findings', [])
    if not isinstance(critical, list):
        critical = [str(critical)]
    ambiguous_positions = ambiguity.get('ambiguous_positions', [])
    ambiguity_detail = '-'
    if isinstance(ambiguous_positions, list) and ambiguous_positions:
        rendered = []
        for entry in ambiguous_positions:
            if not isinstance(entry, dict):
                continue
            pos = entry.get('position')
            slot = entry.get('expected_slot', '?')
            rendered.append(f'P{pos}[{slot}]')
        if rendered:
            ambiguity_detail = '; '.join(rendered)

    external_match = external_source.get('matches_ocr')
    if external_match is True:
        external_match_text = 'Sim'
    elif external_match is False:
        external_match_text = 'Não'
    else:
        external_match_text = 'N/A'

    write_key_values(pdf, {
        'natureza_documento': 'relatorio_tecnico_pericial_preliminar_de_apoio',
        'intervencao_humana_obrigatoria': 'Sim',
        'status_pericial': humanize_pericial_label(pericial.get('status', 'INDEFINIDO')),
        'qualidade_score': quality.get('score', 0),
        'qualidade_nivel': humanize_pericial_label(quality.get('display_label', quality.get('grade', 'INDEFINIDO'))),
        'lei_score': legal.get('law_score', 0),
        'placa_valida_lei': 'Sim' if legal.get('is_valid') else 'Nao',
        'padrao_detectado': legal.get('detected_pattern', 'Indefinido'),
        'melhor_encaixe_legal': legal.get('best_fit_pattern', 'Indefinido'),
        'ambiguidade_posicoes': ambiguity.get('ambiguity_count', 0),
        'ambiguidade_detalhe': ambiguity_detail,
        'historico_local_status': humanize_pericial_label(local_history.get('status', 'indefinido')),
        'historico_local_ocorrencias': local_history.get('previous_occurrences', 0),
        'integridade_captura_status': humanize_pericial_label(capture_integrity.get('status', 'indefinido')),
        'integridade_captura_nota': f"{float(capture_integrity.get('integrity_score', 0.0)):.1f}",
        'integridade_captura_faixa': humanize_pericial_label(capture_integrity.get('integrity_grade', 'indefinida')),
        'integridade_captura_limiar_revisao': f"{float(capture_integrity.get('integrity_review_threshold', 0.0)):.1f}",
        'integridade_captura_limiar_critico': f"{float(capture_integrity.get('integrity_critical_threshold', 0.0)):.1f}",
        'integridade_captura_input_status': humanize_pericial_label(capture_integrity.get('input_status', 'indefinido')),
        'integridade_captura_tipo_entrada': capture_integrity.get('input_type', 'indefinido'),
        'integridade_captura_assinatura': capture_integrity.get('input_signature', '-'),
        'integridade_captura_assinatura_compativel': 'Sim' if capture_integrity.get('input_signature_ok') else 'Nao',
        'integridade_captura_roi_status': humanize_pericial_label(capture_integrity.get('plate_detection_status', 'indefinido')),
        'integridade_captura_roi': capture_integrity.get('plate_detection_selected_region', '-'),
        'integridade_captura_roi_ocr': capture_integrity.get('plate_detection_ocr_selected_region', '-'),
        'integridade_captura_roi_fonte': capture_integrity.get('plate_detection_selected_source', '-'),
        'integridade_captura_roi_calibracao': capture_integrity.get('plate_detection_calibration_source', 'builtin_default'),
        'integridade_captura_roi_fonte_ocr': capture_integrity.get('plate_detection_ocr_selected_source', '-'),
        'integridade_captura_roi_aspecto': f"{float(capture_integrity.get('plate_detection_selected_aspect_ratio', 0.0)):.3f}",
        'integridade_captura_roi_qualidade_nivel': humanize_roi_quality_label(capture_integrity.get('plate_detection_selected_quality_label', 'indefinida')),
        'integridade_captura_roi_qualidade': f"{float(capture_integrity.get('plate_detection_selected_quality_score', 0.0)):.1f}",
        'integridade_captura_roi_score': f"{float(capture_integrity.get('plate_detection_selected_score', 0.0)):.1f}",
        'integridade_captura_roi_candidatos': capture_integrity.get('plate_detection_candidate_count', 0),
        'integridade_captura_roi_full_image': 'Sim' if capture_integrity.get('plate_detection_used_full_image') else 'Nao',
        'integridade_captura_revisao_manual': 'Sim' if capture_integrity.get('manual_review_recommended') else 'Nao',
        'integridade_captura_fatores': capture_integrity.get('score_breakdown_text', '-'),
        'fonte_externa_status': humanize_pericial_label(external_source.get('status', 'indefinido')),
        'fonte_externa_nome': external_source.get('source', '-'),
        'fonte_externa_compativel_ocr': external_match_text,
        'fonte_externa_multifonte_status': humanize_pericial_label(external_source.get('multifonte_status', 'indefinido')),
        'fonte_externa_multifonte_candidatos': external_source.get('multifonte_candidatos', 0),
        'fonte_externa_multifonte_confianca': external_source.get('multifonte_confianca', '0.0'),
        'fonte_externa_multifonte_taxa_consenso': external_source.get('multifonte_taxa_consenso', '0.0'),
        'fonte_externa_multifonte_score': external_source.get('multifonte_score', '0.0'),
        'fonte_externa_multifonte_limite': external_source.get('multifonte_limite', 0),
        'fonte_externa_multifonte_limite_aplicado': external_source.get('multifonte_limite_aplicado', 'Nao'),
        'fonte_externa_multifonte_consenso': external_source.get('multifonte_consenso', '-'),
        'fonte_externa_multifonte_divergencias': external_source.get('multifonte_divergencias', '-'),
        'fonte_externa_multifonte_resumo': external_source.get('multifonte_resumo', '-'),
        'fonte_externa_multifonte_alertas': external_source.get('multifonte_alertas', '-'),
        'validacao_oficial_status': humanize_official_validation_label(official_validation.get('status', 'indefinido')),
        'validacao_oficial_tipo': humanize_official_validation_source_kind_label(official_validation.get('source_kind', 'indefinido')),
        'validacao_oficial_fonte': humanize_official_validation_source_label(official_validation.get('source_label', 'indefinida')),
        'validacao_oficial_campos_publicos': ', '.join([str(item) for item in (official_validation.get('public_fields_found', []) if isinstance(official_validation.get('public_fields_found', []), list) else [])]) or '-',
        'validacao_oficial_campos_restritos': ', '.join([str(item) for item in (official_validation.get('sensitive_fields_found', []) if isinstance(official_validation.get('sensitive_fields_found', []), list) else [])]) or '-',
        'comparativo_externo_status': humanize_pericial_label(external_systems.get('status', 'indefinido')),
        'comparativo_externo_catalogados': external_systems.get('systems_cataloged', 0),
        'comparativo_externo_executados': external_systems.get('systems_executed', 0),
        'comparativo_externo_ok': external_systems.get('systems_ok', 0),
        'comparativo_externo_placa_match': external_systems.get('plate_compatible_count', 0),
        'comparativo_externo_veiculo_match': external_systems.get('vehicle_compatible_count', 0),
        'visual_profile_status': humanize_pericial_label(visual_profile.get('status', 'indefinido')),
        'visual_profile_vista': visual_profile.get('vista_detectada', 'indefinida'),
        'visual_profile_modelo': (
            str(visual_profile.get('fabricante', '-')) + ' ' + str(visual_profile.get('modelo', '-'))
        ).strip(),
        'visual_profile_modelo_bruto': visual_profile.get('modelo_bruto', '-'),
        'visual_profile_modelo_abstido': 'Sim' if visual_profile.get('modelo_abstido') else 'Nao',
        'visual_profile_modelo_abstencao_motivos': visual_profile.get('modelo_abstencao_motivos', '-'),
        'visual_profile_modelo_margem_top2': visual_profile.get('margem_top2_modelo', 0),
        'visual_profile_modelo_evidencias_discriminativas': visual_profile.get('evidencias_discriminativas', 0),
        'visual_profile_confianca': f"{visual_profile.get('confianca', 0)}%",
        'visual_profile_fontes_abertas': visual_profile.get('fontes_abertas_count', 0),
        'visual_profile_componentes': f"{visual_profile.get('componentes_detectados', 0)}/{visual_profile.get('componentes_avaliados', 0)}",
        'visual_profile_cobertura': f"{float(visual_profile.get('componentes_cobertura', 0.0)):.1f}%",
        'visual_profile_forense_status': humanize_pericial_label(visual_profile.get('caracteristicas_forenses_status', 'indefinido')),
        'visual_profile_forense_total': visual_profile.get('caracteristicas_forenses_detectadas', 0),
        'visual_profile_forense_resumo': visual_profile.get('caracteristicas_forenses_resumo', '-'),
        'achados_criticos': '; '.join([humanize_pericial_label(item) for item in critical if str(item).strip() != '']) or '-',
    })

    protocol = pericial.get('operational_protocol', {})
    if not isinstance(protocol, dict):
        protocol = {}
    if protocol:
        write_section_title(pdf, 'Protocolo operacional técnico-pericial')
        write_operational_protocol(pdf, protocol)

    confrontation_form = pericial.get('vehicle_confrontation_form', {})
    if not isinstance(confrontation_form, dict):
        confrontation_form = {}
    if confrontation_form:
        write_section_title(pdf, 'Formulário técnico-pericial de confrontação visual de veículo')
        write_vehicle_confrontation_form(pdf, confrontation_form)


def write_operational_protocol(pdf, protocol):
    if not isinstance(protocol, dict) or not protocol:
        pdf.multi_cell(0, 8, normalize_pdf_text('Protocolo operacional indisponível.'))
        return

    def _fmt_resolution(value):
        if isinstance(value, dict):
            width = value.get('width')
            height = value.get('height')
            if width and height:
                return f'{width}x{height}'
        return '-'

    evidence = protocol.get('evidence_preservation', {})
    if not isinstance(evidence, dict):
        evidence = {}
    triage = protocol.get('quality_triage', {})
    if not isinstance(triage, dict):
        triage = {}
    ocr_record = protocol.get('ocr_record', {})
    if not isinstance(ocr_record, dict):
        ocr_record = {}
    vehicle_basics = protocol.get('vehicle_basics', {})
    if not isinstance(vehicle_basics, dict):
        vehicle_basics = {}
    matrix = protocol.get('compatibility_matrix', {})
    if not isinstance(matrix, dict):
        matrix = {}
    exclusions = protocol.get('exclusion_checks', {})
    if not isinstance(exclusions, dict):
        exclusions = {}
    conclusion = protocol.get('conclusion', {})
    if not isinstance(conclusion, dict):
        conclusion = {}
    checklist = protocol.get('checklist_operacional', [])
    if not isinstance(checklist, list):
        checklist = []
    available_crops = evidence.get('available_crops', [])
    if not isinstance(available_crops, list):
        available_crops = []
    transformations = evidence.get('transformations', [])
    if not isinstance(transformations, list):
        transformations = []

    write_key_values(pdf, {
        'protocolo_status': humanize_pericial_label(protocol.get('status', 'indefinido')),
        'protocolo_decisao': humanize_pericial_label(conclusion.get('display_decision', conclusion.get('decision', 'indefinido'))),
        'protocolo_nivel': humanize_pericial_label(conclusion.get('display_level', conclusion.get('level', 'INDEFINIDO'))),
        'protocolo_pontuacao': f"{float(conclusion.get('score', matrix.get('score_total', 0.0))):.1f}",
        'protocolo_revisao_manual': 'Sim' if conclusion.get('manual_review_required') else 'Nao',
        'protocolo_resumo': protocol.get('summary', conclusion.get('summary', '-')),
    })

    write_section_title(pdf, 'Preservacao da evidencia tecnico-digital')
    write_key_values(pdf, {
        'analise_id': evidence.get('analysis_id', '-'),
        'origem': evidence.get('origem', '-'),
        'arquivo_origem': evidence.get('source_filename', '-'),
        'recorte_placa': evidence.get('plate_filename', '-'),
        'imagem_ampliada': evidence.get('visual_scene_filename', '-'),
        'capture_timestamp_utc': evidence.get('capture_timestamp_utc', '-'),
        'gerado_em_utc': evidence.get('generated_timestamp_utc', '-'),
        'resolucao_original': _fmt_resolution(evidence.get('source_resolution', {})),
        'resolucao_ampliada': _fmt_resolution(evidence.get('visual_scene_resolution', {})),
        'resolucao_placa': _fmt_resolution(evidence.get('plate_resolution', {})),
        'assinatura_entrada': evidence.get('input_signature', '-'),
        'assinatura_compativel': 'Sim' if evidence.get('input_signature_ok') else 'Nao',
        'transformacoes': ', '.join([str(item) for item in transformations if str(item).strip()]) or '-',
    })

    crop_lines = []
    for crop in available_crops[:5]:
        if not isinstance(crop, dict):
            continue
        name = str(crop.get('name', '-'))
        label = str(crop.get('label', '-'))
        available = 'sim' if crop.get('available') else 'nao'
        path = str(crop.get('path', '')).strip()
        line = f'- {name} | {label} | disponivel={available}'
        if path:
            line += f' | {path}'
        crop_lines.append(line)
    if crop_lines:
        pdf.multi_cell(0, 8, normalize_pdf_text('Cortes preservados:'))
        for line in crop_lines:
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

    write_section_title(pdf, 'Triagem de qualidade tecnica')
    write_key_values(pdf, {
        'classe': humanize_pericial_label(triage.get('class', 'D')),
        'faixa': humanize_pericial_label(triage.get('display_label', triage.get('label', 'indefinida'))),
        'nota': f"{float(triage.get('score', 0.0)):.1f}",
        'qualidade_base': f"{float(triage.get('quality_score', 0.0)):.1f}",
        'integridade_base': f"{float(triage.get('integrity_score', 0.0)):.1f}",
        'consenso_base': f"{float(triage.get('consensus_ratio', 0.0)):.1f}",
        'confianca_base': f"{float(triage.get('avg_confidence', 0.0)):.1f}",
        'revisao_manual': 'Sim' if triage.get('manual_review') else 'Nao',
    })
    reasons = triage.get('reasons', [])
    if isinstance(reasons, list) and reasons:
        pdf.multi_cell(0, 8, normalize_pdf_text('Motivos: ' + '; '.join([str(item) for item in reasons if str(item).strip()])))

    write_section_title(pdf, 'Registro OCR tecnico-pericial')
    write_key_values(pdf, {
        'leitura_principal': ocr_record.get('leitura_principal', 'indefinido'),
        'caracteres_impossiveis': ocr_record.get('caracteres_incertos_resumo', '-'),
        'padrao_placa': ocr_record.get('padrao_placa', 'Indefinido'),
        'ocr_confidencia': f"{float(ocr_record.get('confidencia_estimativa', 0.0)):.1f}",
        'ocr_media_conf': f"{float(ocr_record.get('avg_conf', 0.0)):.1f}",
        'ocr_score_bruto': f"{float(ocr_record.get('score_bruto', 0.0)):.1f}",
        'ocr_score_lei': f"{float(ocr_record.get('law_score', 0.0)):.1f}",
        'ocr_consenso': f"{float(ocr_record.get('agreement_ratio', 0.0)):.1f}",
        'ocr_parcial': 'Sim' if ocr_record.get('partial_plate') else 'Nao',
        'ocr_valido_na_lei': 'Sim' if ocr_record.get('pattern_valid') else 'Nao',
        'ocr_origem': ocr_record.get('pattern_source', '-'),
    })
    supports = ocr_record.get('supports', [])
    if isinstance(supports, list) and supports:
        pdf.multi_cell(0, 8, normalize_pdf_text('Motores de suporte: ' + ', '.join([str(item) for item in supports if str(item).strip()])))
    uncertainties = ocr_record.get('caracteres_incertos', [])
    if isinstance(uncertainties, list) and uncertainties:
        pdf.multi_cell(0, 8, normalize_pdf_text('Posicoes incertas:'))
        for item in uncertainties[:5]:
            if not isinstance(item, dict):
                continue
            line = (
                f"- P{item.get('position', '?')} | slot={item.get('expected_slot', '?')} | "
                f"impossivel_de_ler"
            )
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

    write_section_title(pdf, 'Base primaria do veiculo')
    write_key_values(pdf, {
        'categoria_primaria': vehicle_basics.get('categoria_primaria', 'indefinida'),
        'porte': vehicle_basics.get('porte', 'indefinido'),
        'portas_visiveis': vehicle_basics.get('numero_portas_visiveis_estimado', 'indefinido'),
        'volume_traseiro': vehicle_basics.get('volume_traseiro', 'indefinido'),
        'caimento_teto': vehicle_basics.get('caimento_teto', 'indefinido'),
        'posicao_placa': vehicle_basics.get('posicao_placa', 'indefinida'),
        'vidro_traseiro': vehicle_basics.get('formato_vidro_traseiro', 'indefinida'),
        'coluna_c': vehicle_basics.get('coluna_c', 'indefinida'),
        'fabricante_probavel': vehicle_basics.get('fabricante_probavel', '-'),
        'modelo_probavel': vehicle_basics.get('modelo_probavel', '-'),
        'faixa_ano_probavel': vehicle_basics.get('faixa_ano_probavel', '-'),
        'confianca_visual': f"{float(vehicle_basics.get('confianca_hipotese_visual', 0.0)):.1f}",
    })
    observations = vehicle_basics.get('observacoes', [])
    if isinstance(observations, list) and observations:
        pdf.multi_cell(0, 8, normalize_pdf_text('Observacoes: ' + '; '.join([str(item) for item in observations if str(item).strip()])))

    write_section_title(pdf, 'Matriz de compatibilidade')
    write_key_values(pdf, {
        'pontuacao_total': f"{float(matrix.get('score_total', 0.0)):.1f}",
        'pontuacao_maxima': f"{float(matrix.get('max_score', 100.0)):.1f}",
        'pontuacao_disponivel': f"{float(matrix.get('available_score', 0.0)):.1f}",
        'pontuacao_disponivel_max': f"{float(matrix.get('available_max_score', 0.0)):.1f}",
        'cobertura_percentual': f"{float(matrix.get('coverage_percent', 0.0)):.1f}",
        'taxa_disponivel': f"{float(matrix.get('available_ratio', 0.0)):.1f}",
        'nivel': humanize_pericial_label(matrix.get('display_level', matrix.get('level', 'INCOMPATIVEL'))),
        'resumo': '; '.join([str(item) for item in matrix.get('summary', []) if str(item).strip()]) or '-',
    })
    matrix_items = matrix.get('items', [])
    if isinstance(matrix_items, list) and matrix_items:
        pdf.multi_cell(0, 8, normalize_pdf_text('Itens da matriz:'))
        for item in matrix_items[:8]:
            if not isinstance(item, dict):
                continue
            evidences = item.get('evidencias', [])
            if not isinstance(evidences, list):
                evidences = []
            notes = item.get('observacoes', [])
            if not isinstance(notes, list):
                notes = []
            line = (
                f"- {item.get('criterio', '-')}: {float(item.get('pontuacao', 0.0)):.1f}/"
                f"{float(item.get('peso_maximo', 0.0)):.1f} | status={humanize_pericial_label(item.get('status', 'indefinido'))} | "
                f"disp={'Sim' if item.get('disponivel') else 'Nao'} | fonte={item.get('fonte', '-')}"
            )
            pdf.multi_cell(0, 8, normalize_pdf_text(line))
            if evidences:
                pdf.multi_cell(0, 8, normalize_pdf_text('  evidencias: ' + ', '.join([str(x) for x in evidences if str(x).strip()])))
            if notes:
                pdf.multi_cell(0, 8, normalize_pdf_text('  observacoes: ' + ', '.join([str(x) for x in notes if str(x).strip()])))

    write_section_title(pdf, 'Criterios de exclusao tecnico-pericial')
    write_key_values(pdf, {
        'gatilhos': exclusions.get('triggered_count', 0),
        'gatilhos_fortes': exclusions.get('strong_triggered_count', 0),
        'resumo': '; '.join([str(item) for item in exclusions.get('summary', []) if str(item).strip()]) or '-',
    })
    exclusion_items = exclusions.get('items', [])
    if isinstance(exclusion_items, list) and exclusion_items:
        for item in exclusion_items[:8]:
            if not isinstance(item, dict):
                continue
            line = (
                f"- {item.get('code', '-')}: {item.get('label', '-')} | status={humanize_pericial_label(item.get('status', 'indefinido'))} | "
                f"forte={'Sim' if item.get('strong_excluder') else 'Nao'} | impacto={item.get('impact', '-')}"
            )
            pdf.multi_cell(0, 8, normalize_pdf_text(line))
            reason = str(item.get('reason', '')).strip()
            if reason:
                pdf.multi_cell(0, 8, normalize_pdf_text('  motivo: ' + reason))

    write_section_title(pdf, 'Conclusao pericial')
    write_key_values(pdf, {
        'decisao': humanize_pericial_label(conclusion.get('display_decision', conclusion.get('decision', 'indefinido'))),
        'nivel': humanize_pericial_label(conclusion.get('display_level', conclusion.get('level', 'INDEFINIDO'))),
        'pontuacao': f"{float(conclusion.get('score', 0.0)):.1f}",
        'revisao_manual': 'Sim' if conclusion.get('manual_review_required') else 'Nao',
        'resumo': conclusion.get('summary', '-'),
    })
    supporting = conclusion.get('supporting_items', [])
    if isinstance(supporting, list) and supporting:
        pdf.multi_cell(0, 8, normalize_pdf_text('Sustentacoes: ' + '; '.join([str(item) for item in supporting if str(item).strip()])))

    if checklist:
        pdf.multi_cell(0, 8, normalize_pdf_text('Checklist operacional:'))
        for item in checklist[:10]:
            pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))


def write_vehicle_confrontation_form(pdf, form):
    if not isinstance(form, dict) or not form:
        pdf.multi_cell(0, 8, normalize_pdf_text('Formulário de confrontação indisponível.'))
        return

    def to_list(value):
        return value if isinstance(value, list) else []

    def fmt_bool(value):
        return 'Sim' if bool(value) else 'Não'

    def join_nonempty(values):
        values = to_list(values)
        return '; '.join([str(item) for item in values if str(item).strip()]) or '-'

    def render_features(title, section):
        section = section if isinstance(section, dict) else {}
        pdf.multi_cell(0, 8, normalize_pdf_text(f"{title}: {humanize_pericial_label(section.get('compatibility', 'indefinido'))} | score={float(section.get('score', 0.0)):.1f}"))
        description = str(section.get('description', '')).strip()
        if description and description != '-':
            pdf.multi_cell(0, 8, normalize_pdf_text('  descricao: ' + description))
        for item in to_list(section.get('features', []))[:8]:
            if not isinstance(item, dict):
                continue
            detail = str(item.get('detail', '')).strip()
            line = f"  - {item.get('label', '-')} | {humanize_pericial_label(item.get('status', 'indefinido'))} ({float(item.get('confidence', 0.0)):.1f}%)"
            if detail and detail != '-':
                line += f" | {detail}"
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

    identification = form.get('identificacao', {}) if isinstance(form.get('identificacao', {}), dict) else {}
    material = form.get('material_examined', {}) if isinstance(form.get('material_examined', {}), dict) else {}
    quality = form.get('quality', {}) if isinstance(form.get('quality', {}), dict) else {}
    ocr = form.get('ocr', {}) if isinstance(form.get('ocr', {}), dict) else {}
    classification = form.get('vehicle_classification', {}) if isinstance(form.get('vehicle_classification', {}), dict) else {}
    confrontation = form.get('confrontacao_externa', {}) if isinstance(form.get('confrontacao_externa', {}), dict) else {}
    internal = form.get('confrontacao_interna', {}) if isinstance(form.get('confrontacao_interna', {}), dict) else {}
    hypothesis = form.get('hipotese_principal', {}) if isinstance(form.get('hipotese_principal', {}), dict) else {}
    alternatives = to_list(form.get('hipoteses_alternativas', []))
    favorable = to_list(form.get('elementos_favoraveis', []))
    exclusion = to_list(form.get('elementos_excludentes', []))
    cross_check = form.get('cruzamento_ocr', {}) if isinstance(form.get('cruzamento_ocr', {}), dict) else {}
    matrix = form.get('matriz', {}) if isinstance(form.get('matriz', {}), dict) else {}
    conclusion = form.get('conclusao', {}) if isinstance(form.get('conclusao', {}), dict) else {}
    closing = form.get('encerramento', {}) if isinstance(form.get('encerramento', {}), dict) else {}
    quick = form.get('checklist_rapido', {}) if isinstance(form.get('checklist_rapido', {}), dict) else {}

    write_key_values(pdf, {
        'numero_analise': identification.get('numero_analise', '-'),
        'data': identification.get('data', '-'),
        'hora': identification.get('hora', '-'),
        'responsavel': identification.get('responsavel', '-'),
        'origem': identification.get('origem_imagem', '-'),
        'arquivo': identification.get('arquivo', '-'),
        'local': identification.get('local', '-'),
        'observacoes_iniciais': identification.get('observacoes_iniciais', '-'),
    })

    material_items = to_list(material.get('items', []))
    if material_items:
        pdf.multi_cell(0, 8, normalize_pdf_text('Material examinado:'))
        for item in material_items[:10]:
            if not isinstance(item, dict):
                continue
            pdf.multi_cell(0, 8, normalize_pdf_text(f"- {item.get('label', '-')} | {fmt_bool(item.get('available'))}"))
        pdf.multi_cell(0, 8, normalize_pdf_text(f"Quantidade de arquivos analisados: {int(material.get('count', 0))}"))

    write_section_title(pdf, 'Qualidade tecnica da imagem')
    write_key_values(pdf, {
        'classe_geral': humanize_pericial_label(quality.get('class', 'D')),
        'faixa': humanize_pericial_label(quality.get('display_label', quality.get('label', 'indefinida'))),
        'observacoes': join_nonempty(quality.get('observations', [])),
    })
    conditions = to_list(quality.get('conditions', []))
    if conditions:
        pdf.multi_cell(0, 8, normalize_pdf_text('Condicoes observadas: ' + '; '.join([str(item) for item in conditions if str(item).strip()])))

    write_section_title(pdf, 'Dados textuais extraidos e leitura OCR')
    write_key_values(pdf, {
        'placa_integral_lida': ocr.get('plate_full', '-'),
        'placa_parcial_lida': ocr.get('plate_partial', '-'),
        'leitura_principal': ocr.get('main', '-'),
        'caracteres_nao_legiveis': ocr.get('uncertain_chars', '-'),
        'confianca_estimativa': f"{float(ocr.get('confidence', 0.0)):.1f}%",
        'padrao_probavel': ocr.get('pattern', '-'),
    })
    uncertain_positions = to_list(ocr.get('uncertain_positions', []))
    if uncertain_positions:
        pdf.multi_cell(0, 8, normalize_pdf_text('Posicoes incertas:'))
        for item in uncertain_positions[:6]:
            if not isinstance(item, dict):
                continue
            slot = str(item.get('expected_slot', '?'))
            pdf.multi_cell(0, 8, normalize_pdf_text(f"- P{item.get('position', '?')} | slot={slot} | impossivel_de_ler"))

    partial_candidates = to_list(ocr.get('partial_candidates', []))
    if partial_candidates:
        pdf.multi_cell(0, 8, normalize_pdf_text('Fragmentos parciais observados:'))
        for item in partial_candidates[:5]:
            if not isinstance(item, dict):
                continue
            minute_range = str(item.get('minute_range', '') or '').strip()
            support_label = str(item.get('support_label', '') or '').strip()
            line = f"- {item.get('text', '-')}"
            details = []
            if support_label:
                details.append(support_label)
            if minute_range and minute_range != 'Indefinido':
                details.append(minute_range)
            if details:
                line += f" | {' | '.join(details)}"
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

    write_section_title(pdf, 'Classificação técnico-visual do veículo')
    write_key_values(pdf, {
        'tipo': classification.get('tipo', '-'),
        'porte': classification.get('porte', '-'),
        'cor_predominante': classification.get('cor', '-'),
        'num_portas_visiveis': classification.get('num_portas', '-'),
        'carroceria': classification.get('carroceria', '-'),
        'posicao_placa': classification.get('placa_posicao', '-'),
        'vidro_traseiro': classification.get('vidro_traseiro', '-'),
        'coluna_cd': classification.get('coluna_cd', '-'),
        'altura_solo': classification.get('altura_solo', '-'),
    })

    write_section_title(pdf, 'Confrontação técnico-visual externa')
    render_features('Frente', confrontation.get('frente'))
    render_features('Traseira', confrontation.get('traseira'))
    render_features('Lateral', confrontation.get('lateral'))
    render_features('Rodas / calotas', confrontation.get('rodas'))
    render_features('Interno', internal)

    write_section_title(pdf, 'Hipóteses técnico-periciais')
    write_key_values(pdf, {
        'fabricante_provavel': hypothesis.get('fabricante', '-'),
        'modelo_provavel': hypothesis.get('modelo', '-'),
        'versao_provavel': hypothesis.get('versao', '-'),
        'geracao_provavel': hypothesis.get('geracao', '-'),
        'faixa_de_ano_provavel': hypothesis.get('faixa_ano', '-'),
    })
    if alternatives:
        pdf.multi_cell(0, 8, normalize_pdf_text('Hipóteses alternativas:'))
        for item in alternatives[:3]:
            pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))

    if favorable:
        pdf.multi_cell(0, 8, normalize_pdf_text('Elementos distintivos favoráveis:'))
        for item in favorable[:6]:
            pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))

    if exclusion:
        pdf.multi_cell(0, 8, normalize_pdf_text('Elementos excludentes ou contraditórios:'))
        for item in exclusion[:6]:
            pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))

    write_section_title(pdf, 'Cruzamento OCR e compatibilidade')
    write_key_values(pdf, {
        'placa_parcial_obtida': cross_check.get('placa_parcial', '-'),
        'padrao_probavel': cross_check.get('padrao', '-'),
        'compatibilidade': humanize_pericial_label(cross_check.get('compatibility', '-')),
    })
    if cross_check.get('observacoes'):
        pdf.multi_cell(0, 8, normalize_pdf_text('Observacoes: ' + '; '.join([str(item) for item in to_list(cross_check.get('observacoes', [])) if str(item).strip()])))

    write_section_title(pdf, 'Matriz de pontuacao')
    write_key_values(pdf, {
        'pontuacao_final': f"{float(matrix.get('pontuacao_final', 0.0)):.1f} / 100",
        'faixa_interpretativa': humanize_pericial_label(matrix.get('interpretacao', '-')),
        'faixa_operacional': humanize_pericial_label(matrix.get('faixa', '-')),
    })
    matrix_items = to_list(matrix.get('itens', []))
    if matrix_items:
        pdf.multi_cell(0, 8, normalize_pdf_text('Criterios:'))
        for item in matrix_items[:10]:
            if not isinstance(item, dict):
                continue
            pdf.multi_cell(0, 8, normalize_pdf_text(f"- {item.get('criterio', '-')} | {float(item.get('nota', 0.0)):.1f}/{float(item.get('maximo', 0.0)):.1f} | {humanize_pericial_label(item.get('status', 'indefinido'))} | fonte={item.get('fonte', '-')}"))

    write_section_title(pdf, 'Conclusao padronizada')
    write_key_values(pdf, {
        'marcacao': humanize_pericial_label(conclusion.get('marca', 'inconclusivo')),
        'resultado': humanize_pericial_label(conclusion.get('resultado', 'inconclusivo')),
        'nivel': humanize_pericial_label(conclusion.get('nivel', '-')),
        'revisao_manual': 'Sim' if humanize_pericial_label(conclusion.get('resultado', 'inconclusivo')) == 'Inconclusivo' else 'Nao',
        'texto': conclusion.get('texto', '-'),
    })

    write_section_title(pdf, 'Encerramento tecnico')
    write_key_values(pdf, {
        'responsavel_preenchimento': closing.get('responsavel_preenchimento', '-'),
        'cargo_funcao': closing.get('cargo_funcao', '-'),
        'data': closing.get('data', '-'),
        'assinatura': closing.get('assinatura', '-'),
        'rubrica': closing.get('rubrica', '-'),
    })

    quick_items = to_list(quick.get('items', []))
    if quick_items:
        pdf.multi_cell(0, 8, normalize_pdf_text('Checklist rapido:'))
        for item in quick_items[:8]:
            if not isinstance(item, dict):
                continue
            pdf.multi_cell(0, 8, normalize_pdf_text(f"- {item.get('label', '-')}: {humanize_pericial_label(item.get('status', 'indefinido'))}"))

def write_visual_profile(pdf, visual_profile):
    if not isinstance(visual_profile, dict) or not visual_profile:
        pdf.multi_cell(0, 8, normalize_pdf_text('Perfil visual indisponível.'))
        return

    principal = visual_profile.get('hipotese_principal', {})
    if not isinstance(principal, dict):
        principal = {}
    principal_raw = visual_profile.get('hipotese_principal_bruta', {})
    if not isinstance(principal_raw, dict):
        principal_raw = {}
    model_quality = visual_profile.get('qualidade_modelo', {})
    if not isinstance(model_quality, dict):
        model_quality = {}

    hypotheses = visual_profile.get('hipoteses', [])
    if not isinstance(hypotheses, list):
        hypotheses = []

    fontes = visual_profile.get('fontes', [])
    if not isinstance(fontes, list):
        fontes = []
    alt_colors = visual_profile.get('cores_alternativas', [])
    if not isinstance(alt_colors, list):
        alt_colors = []
    rear = visual_profile.get('lanterna_traseira', {})
    if not isinstance(rear, dict):
        rear = {}
    comparison = visual_profile.get('comparativo_fontes_abertas', {})
    if not isinstance(comparison, dict):
        comparison = {}
    search_engines = comparison.get('motores_busca_utilizados', [])
    if not isinstance(search_engines, list):
        search_engines = []
    analysis_engines = comparison.get('motores_analise_utilizados', [])
    if not isinstance(analysis_engines, list):
        analysis_engines = []
    forensic_traits = visual_profile.get('caracteristicas_forenses', {})
    if not isinstance(forensic_traits, dict):
        forensic_traits = {}
    forensic_findings = forensic_traits.get('achados', [])
    if not isinstance(forensic_findings, list):
        forensic_findings = []
    component_profile = visual_profile.get('assinaturas_componentes', {})
    if not isinstance(component_profile, dict):
        component_profile = {}
    component_entries = component_profile.get('componentes', {})
    if not isinstance(component_entries, dict):
        component_entries = {}
    component_coverage = float(component_profile.get('cobertura_percentual', 0))
    component_detected = int(component_profile.get('itens_detectados', 0))
    component_total = int(component_profile.get('itens_avaliados', 0))
    alt_colors_text = '-'
    if alt_colors:
        rendered = []
        for item in alt_colors[:3]:
            if not isinstance(item, dict):
                continue
            rendered.append(f"{item.get('name', '-')}: {item.get('ratio', 0)}%")
        if rendered:
            alt_colors_text = '; '.join(rendered)

    write_key_values(pdf, {
        'natureza_relatorio': 'apoio_investigativo_com_revisao_humana_obrigatoria',
        'status': humanize_pericial_label(visual_profile.get('status', 'indefinido')),
        'vista_detectada': visual_profile.get('vista_detectada', 'indefinida'),
        'cor_probavel': visual_profile.get('cor_probavel', 'indefinida'),
        'confianca_cor': f"{visual_profile.get('confianca_cor', 0)}%",
        'cores_alternativas': alt_colors_text,
        'lanterna_traseira_vertical': 'Sim' if rear.get('vertical_pair') else 'Nao',
        'lanterna_traseira_confianca': f"{rear.get('confidence', 0)}%",
        'fabricante_hipotese': principal.get('fabricante', '-'),
        'modelo_hipotese': principal.get('modelo', '-'),
        'modelo_bruto_pre_calibracao': principal_raw.get('modelo', '-'),
        'qualidade_modelo_status': humanize_pericial_label(model_quality.get('status', 'indefinido')),
        'qualidade_modelo_abstencao': 'Sim' if model_quality.get('model_abstained') else 'Nao',
        'qualidade_modelo_margem_top2': model_quality.get('confidence_margin_top2', 0),
        'qualidade_modelo_evidencia_discriminativa': model_quality.get('discriminative_evidence_count', 0),
        'qualidade_modelo_motivos': '; '.join([str(item) for item in model_quality.get('reasons', [])]) if isinstance(model_quality.get('reasons', []), list) else '-',
        'faixa_ano_modelo': principal.get('faixa_ano_modelo', '-'),
        'confianca_hipotese': f"{principal.get('confianca', 0)}%",
        'comparativo_modelo_alvo': comparison.get('modelo_alvo', '-'),
        'comparativo_ajuste': comparison.get('modelo_alvo_ajuste_motivo', 'principal'),
        'componentes_detectados': f'{component_detected}/{component_total}',
        'componentes_cobertura': f'{component_coverage:.1f}%',
        'forense_status': humanize_pericial_label(forensic_traits.get('status', 'indefinido')),
        'forense_achados': forensic_traits.get('total_achados', len(forensic_findings)),
        'motores_busca_utilizados': '; '.join([str(item) for item in search_engines if str(item).strip() != '']) or '-',
        'motores_analise_utilizados': '; '.join([str(item) for item in analysis_engines if str(item).strip() != '']) or '-',
        'fontes': '; '.join([str(item) for item in fontes if str(item).strip() != '']) or '-',
    })

    show_hypotheses = bool(hypotheses) and not bool(model_quality.get('model_abstained')) and str(principal.get('modelo', '')).strip().lower() != 'nao conclusivo'
    if show_hypotheses:
        pdf.multi_cell(0, 8, normalize_pdf_text('Top hipóteses visuais:'))
        for index, item in enumerate(hypotheses[:3], start=1):
            if not isinstance(item, dict):
                continue
            line = (
                f"{index}) {item.get('fabricante', '-')} {item.get('modelo', '-')} "
                f"| confianca={item.get('confianca', 0)}% | ano={item.get('faixa_ano_modelo', '-')}"
            )
            pdf.multi_cell(0, 8, normalize_pdf_text(line))
            evidences = item.get('evidencias', [])
            if isinstance(evidences, list) and evidences:
                pdf.multi_cell(0, 8, normalize_pdf_text('   evidencias: ' + ', '.join([str(x) for x in evidences])))
    elif bool(model_quality.get('model_abstained')):
        pdf.multi_cell(0, 8, normalize_pdf_text('Hipóteses visuais retidas por abstenção pericial.'))

    if component_entries:
        labels = {
            'emblema_frontal': 'Emblema frontal',
            'grade_dianteira': 'Grade dianteira',
            'farois_dianteiros': 'Farois dianteiros',
            'lanternas_traseiras': 'Lanternas traseiras',
            'linhas_portas': 'Linhas de portas',
            'capo_dianteiro': 'Capo dianteiro',
            'tampa_traseira': 'Tampa traseira',
            'design_carroceria': 'Design de carroceria',
        }
        pdf.multi_cell(0, 8, normalize_pdf_text('Assinaturas por componente:'))
        for key in (
            'emblema_frontal',
            'grade_dianteira',
            'farois_dianteiros',
            'lanternas_traseiras',
            'linhas_portas',
            'capo_dianteiro',
            'tampa_traseira',
            'design_carroceria',
        ):
            item = component_entries.get(key, {})
            if not isinstance(item, dict):
                continue
            label = labels.get(key, key)
            status = humanize_pericial_label(item.get('status', 'indefinido'))
            conf = float(item.get('confianca', 0))
            detail = str(item.get('detalhe', '')).strip()
            line = f'- {label}: {status} ({conf:.1f}%)'
            if detail:
                line += f' | {detail}'
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

    evidence_matrix = visual_profile.get('matriz_evidencias', {})
    if not isinstance(evidence_matrix, dict):
        evidence_matrix = {}
    matrix_candidates = evidence_matrix.get('candidates', [])
    if not isinstance(matrix_candidates, list):
        matrix_candidates = []
    matrix_summary = evidence_matrix.get('summary', [])
    if not isinstance(matrix_summary, list):
        matrix_summary = []

    if evidence_matrix and matrix_candidates:
        pdf.multi_cell(0, 8, normalize_pdf_text('Matriz de evidencias para fabricante/modelo/faixa de ano:'))
        if matrix_summary:
            pdf.multi_cell(0, 8, normalize_pdf_text('Resumo: ' + ' | '.join([str(item) for item in matrix_summary[:3] if str(item).strip()])))

        for candidate in matrix_candidates[:3]:
            if not isinstance(candidate, dict):
                continue
            candidate_label = f"{candidate.get('fabricante', '-')} {candidate.get('modelo', '-')}".strip()
            conf = float(candidate.get('confianca', 0))
            year_label = str(candidate.get('faixa_ano_modelo', '-'))
            support_weight = float(candidate.get('peso_total_apoio', 0.0))
            pdf.multi_cell(
                0,
                8,
                normalize_pdf_text(
                    f'- {candidate_label} | conf={conf:.1f}% | ano={year_label} | apoio={support_weight:.1f}'
                ),
            )
            rows = candidate.get('rows', [])
            if not isinstance(rows, list):
                continue
            for row in rows[:4]:
                if not isinstance(row, dict):
                    continue
                evidencia = str(row.get('evidencia', '-'))
                descricao = str(row.get('descricao', '-'))
                peso = float(row.get('peso_nominal', 0.0))
                impacto = str(row.get('impacto', 'fraco'))
                relacionados = row.get('componentes_relacionados', [])
                if not isinstance(relacionados, list):
                    relacionados = []
                relacionados_text = []
                for rel in relacionados[:2]:
                    if not isinstance(rel, dict):
                        continue
                    comp_label = str(rel.get('componente', '-'))
                    comp_status = humanize_pericial_label(rel.get('status', 'indefinido'))
                    comp_conf = float(rel.get('confianca', 0.0))
                    relacionados_text.append(f'{comp_label}:{comp_status}({comp_conf:.1f}%)')
                line = f'  * {evidencia} [{impacto}] peso={peso:.1f} | {descricao}'
                if relacionados_text:
                    line += ' | ' + ', '.join(relacionados_text)
                pdf.multi_cell(0, 8, normalize_pdf_text(line))

    if forensic_findings:
        pdf.multi_cell(0, 8, normalize_pdf_text('Características forenses potenciais:'))
        for item in forensic_findings[:8]:
            if not isinstance(item, dict):
                continue
            code = str(item.get('codigo', 'achado_visual'))
            desc = str(item.get('descricao', '-'))
            conf = float(item.get('confianca', 0))
            loc = str(item.get('localizacao', 'indefinida'))
            evidence = str(item.get('evidencia', '')).strip()
            line = f'- {code} | {desc} | conf={conf:.1f}% | local={loc}'
            pdf.multi_cell(0, 8, normalize_pdf_text(line))
            if evidence:
                pdf.multi_cell(0, 8, normalize_pdf_text('  * evidencia: ' + evidence))

    if comparison:
        query = str(comparison.get('consulta_principal', ''))
        if query:
            pdf.multi_cell(0, 8, normalize_pdf_text('Consulta principal: ' + query))

        checklist = comparison.get('checklist_pericial', [])
        if isinstance(checklist, list) and checklist:
            pdf.multi_cell(0, 8, normalize_pdf_text('Checklist de comparação manual:'))
            for item in checklist[:5]:
                pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))

        criteria = comparison.get('criterios_individualizacao', [])
        if isinstance(criteria, list) and criteria:
            pdf.multi_cell(0, 8, normalize_pdf_text('Critérios de individualização:'))
            for item in criteria[:7]:
                pdf.multi_cell(0, 8, normalize_pdf_text('- ' + str(item)))

        families = comparison.get('familias_fontes', {})
        if isinstance(families, dict) and families:
            rendered = []
            for family_name, family_count in sorted(families.items(), key=lambda item: str(item[0])):
                rendered.append(f'{family_name}={int(family_count)}')
            if rendered:
                pdf.multi_cell(0, 8, normalize_pdf_text('Famílias de fontes: ' + ' | '.join(rendered)))

        component_queries = comparison.get('consultas_componentes', [])
        if isinstance(component_queries, list) and component_queries:
            pdf.multi_cell(0, 8, normalize_pdf_text('Consultas abertas por componente:'))
            for item in component_queries[:6]:
                if not isinstance(item, dict):
                    continue
                rotulo = str(item.get('rotulo', item.get('componente', '-')))
                status = humanize_pericial_label(item.get('status', 'indefinido'))
                confianca = float(item.get('confianca', 0))
                consulta = str(item.get('consulta', ''))
                header = f'- {rotulo}: {status} ({confianca:.1f}%)'
                if consulta:
                    header += f' | query: {consulta}'
                pdf.multi_cell(0, 8, normalize_pdf_text(header))
                local_sources = item.get('fontes', [])
                if isinstance(local_sources, list):
                    for src in local_sources[:2]:
                        if not isinstance(src, dict):
                            continue
                        src_name = str(src.get('fonte', '-'))
                        src_url = str(src.get('url', ''))
                        if src_url:
                            pdf.multi_cell(0, 8, normalize_pdf_text(f'  * {src_name}: {src_url}'))

        feature_queries = comparison.get('consultas_caracteristicas', [])
        if isinstance(feature_queries, list) and feature_queries:
            pdf.multi_cell(0, 8, normalize_pdf_text('Consultas abertas por característica forense:'))
            for item in feature_queries[:6]:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get('descricao', item.get('caracteristica', '-')))
                consulta = str(item.get('consulta', ''))
                localizacao = str(item.get('localizacao', 'indefinida'))
                header = f'- {desc} | local={localizacao}'
                if consulta:
                    header += f' | query: {consulta}'
                pdf.multi_cell(0, 8, normalize_pdf_text(header))
                local_sources = item.get('fontes', [])
                if isinstance(local_sources, list):
                    for src in local_sources[:2]:
                        if not isinstance(src, dict):
                            continue
                        src_name = str(src.get('fonte', '-'))
                        src_url = str(src.get('url', ''))
                        if src_url:
                            pdf.multi_cell(0, 8, normalize_pdf_text(f'  * {src_name}: {src_url}'))

        sources = comparison.get('fontes', [])
        if isinstance(sources, list) and sources:
            pdf.multi_cell(0, 8, normalize_pdf_text('Fontes abertas (URLs de consulta):'))
            for source in sources[:10]:
                if not isinstance(source, dict):
                    continue
                label = str(source.get('fonte', '-'))
                url = str(source.get('url', ''))
                if url:
                    pdf.multi_cell(0, 8, normalize_pdf_text(f'- {label}: {url}'))
        else:
            pdf.multi_cell(0, 8, normalize_pdf_text('Fontes abertas (URLs de consulta): não registradas nesta execução.'))


def write_scene_preprocess(pdf, scene_preprocess):
    if not isinstance(scene_preprocess, dict) or not scene_preprocess:
        pdf.multi_cell(0, 8, normalize_pdf_text('Tratamento de imagem indisponível.'))
        return

    scene_profile = scene_preprocess.get('scene_profile', {})
    if not isinstance(scene_profile, dict):
        scene_profile = {}
    quality_before = scene_preprocess.get('quality_before', {})
    if not isinstance(quality_before, dict):
        quality_before = {}
    quality_after = scene_preprocess.get('quality_after', {})
    if not isinstance(quality_after, dict):
        quality_after = {}

    ranked_variants = scene_preprocess.get('ranked_variants', [])
    if not isinstance(ranked_variants, list):
        ranked_variants = []
    top_variants_text = '-'
    if ranked_variants:
        rendered = []
        for item in ranked_variants[:4]:
            if not isinstance(item, dict):
                continue
            variant = humanize_pericial_label(item.get('variant', '-'))
            family = humanize_pericial_label(item.get('family', 'opencv'))
            score = float(item.get('score', 0))
            rendered.append(f'{variant} [{family}]={score:.2f}')
        if rendered:
            top_variants_text = '; '.join(rendered)

    software_families = scene_preprocess.get('software_families', [])
    if not isinstance(software_families, list):
        software_families = []
    scenario_tags = scene_preprocess.get('scenario_tags', [])
    if not isinstance(scenario_tags, list):
        scenario_tags = []
    scenario_reasons = scene_preprocess.get('scenario_reasons', [])
    if not isinstance(scenario_reasons, list):
        scenario_reasons = []

    write_key_values(pdf, {
        'Status do tratamento': humanize_pericial_label(scene_preprocess.get('selected', 'original')),
        'Variante selecionada': humanize_pericial_label(scene_preprocess.get('selected_variant', 'original')),
        'Familia selecionada': humanize_pericial_label(scene_preprocess.get('selected_family', 'opencv')),
        'Cenario da cena': scene_preprocess.get(
            'scenario_display_label',
            scene_profile.get('display_label', humanize_scene_label(scene_preprocess.get('scenario_label', scene_profile.get('label', 'balanced')))),
        ),
        'Tags do cenario': ', '.join([humanize_pericial_label(item) for item in scenario_tags if str(item).strip()]) or '-',
        'Motivos de selecao': ', '.join([humanize_pericial_label(item) for item in scenario_reasons if str(item).strip()]) or '-',
        'Calibracao aplicada': humanize_pericial_label(scene_preprocess.get('calibration_source', scene_profile.get('calibration_source', 'builtin_default'))),
        'Motivo da selecao': humanize_pericial_label(scene_preprocess.get('selection_reason', 'n/a')),
        'Familias avaliadas': ', '.join([humanize_pericial_label(item) for item in software_families if str(item).strip() != '']) or 'OpenCV',
        'Candidatos avaliados': scene_preprocess.get('candidate_count', 0),
        'Qualidade antes': quality_before.get('quality_score', 0),
        'Qualidade depois': quality_after.get('quality_score', 0),
        'Melhoria estimada': scene_preprocess.get('improvement', 0),
        'Melhores variantes': top_variants_text,
    })

    steps = scene_preprocess.get('steps', [])
    if isinstance(steps, list) and steps:
        pdf.multi_cell(0, 8, normalize_pdf_text('Etapas aplicadas: ' + ' -> '.join([humanize_pericial_label(item) for item in steps if str(item).strip() != ''])))


def write_input_security(pdf, input_security):
    if not isinstance(input_security, dict) or not input_security:
        pdf.multi_cell(0, 8, normalize_pdf_text('Segurança da entrada indisponível.'))
        return

    warnings = input_security.get('warnings', [])
    if not isinstance(warnings, list):
        warnings = [warnings]

    write_key_values(pdf, {
        'Status da entrada': humanize_pericial_label(input_security.get('status', 'indefinido')),
        'Tipo de entrada': humanize_pericial_label(input_security.get('input_type', 'indefinido')),
        'Extensao do arquivo': input_security.get('extension', '-'),
        'Assinatura detectada': humanize_pericial_label(input_security.get('detected_signature', '-')),
        'Assinatura compativel': 'Sim' if input_security.get('signature_ok') else 'Nao',
        'Tamanho do arquivo (MB)': f"{float(input_security.get('file_size_mb', 0.0)):.2f}",
        'Limite maximo (MB)': f"{float(input_security.get('max_upload_mb', 0.0)):.2f}",
        'Politica aplicada': humanize_pericial_label(input_security.get('policy', 'allowlist_extension+signature+size')),
        'Alertas': '; '.join([str(item) for item in warnings if str(item).strip()]) or '-',
    })


def write_external_systems_comparison(pdf, comparison):
    if not isinstance(comparison, dict) or not comparison:
        pdf.multi_cell(0, 8, normalize_pdf_text('Fontes complementares auditáveis indisponíveis nesta execução.'))
        return

    summary = comparison.get('sumario', {})
    if not isinstance(summary, dict):
        summary = {}
    executions = comparison.get('execucoes', [])
    if not isinstance(executions, list):
        executions = []
    catalog = comparison.get('catalogo', [])
    if not isinstance(catalog, list):
        catalog = []

    write_key_values(pdf, {
        'status': humanize_pericial_label(comparison.get('status', 'indefinido')),
        'mensagem': comparison.get('message', '-'),
        'sistemas_catalogados': summary.get('sistemas_catalogados', len(catalog)),
        'sistemas_executados': summary.get('sistemas_executados', 0),
        'sistemas_ok': summary.get('sistemas_ok', 0),
        'placa_compativel_ocr': summary.get('placa_compativel_ocr', 0),
        'veiculo_compativel_visual': summary.get('veiculo_compativel_visual', 0),
        'taxa_concordancia_placa': f"{summary.get('taxa_concordancia_placa', 0)}%",
        'taxa_concordancia_veiculo': f"{summary.get('taxa_concordancia_veiculo', 0)}%",
    })

    pdf.multi_cell(
        0,
        8,
        normalize_pdf_text('Fontes complementares de apoio, com valor contextual e necessidade de correlação humana qualificada.'),
    )

    if executions:
        pdf.multi_cell(0, 8, normalize_pdf_text('Resultados por fonte complementar auditavel:'))
        for item in executions[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get('nome', item.get('id', 'sistema_externo')))
            status = humanize_pericial_label(item.get('status', 'indefinido'))
            reason = str(item.get('reason', '-'))
            plate = str(item.get('plate', '')) or '-'
            conf = float(item.get('plate_confidence', 0))
            plate_match = item.get('matches_internal_plate')
            if plate_match is True:
                plate_match_text = 'sim'
            elif plate_match is False:
                plate_match_text = 'nao'
            else:
                plate_match_text = 'n/a'
            vehicle_match = item.get('matches_internal_vehicle')
            if vehicle_match is True:
                vehicle_match_text = 'sim'
            elif vehicle_match is False:
                vehicle_match_text = 'nao'
            else:
                vehicle_match_text = 'n/a'

            line = (
                f'sistema={name} | status={status} | motivo={reason} | '
                f'placa={plate} | conf={conf:.1f}% | '
                f'placa_compativel={plate_match_text} | veiculo_compativel={vehicle_match_text}'
            )
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

            vehicle = item.get('vehicle', {})
            if isinstance(vehicle, dict) and vehicle:
                make = str(vehicle.get('fabricante', '-'))
                model = str(vehicle.get('modelo', '-'))
                color = str(vehicle.get('cor', '-'))
                year = str(vehicle.get('ano', '-'))
                pdf.multi_cell(
                    0,
                    8,
                    normalize_pdf_text(f'  * veiculo={make} {model} | cor={color} | ano={year}'),
                )
    else:
        pdf.multi_cell(0, 8, normalize_pdf_text('Nenhuma fonte complementar auditavel retornou resultado util nesta execucao.'))

    if catalog:
        pdf.multi_cell(0, 8, normalize_pdf_text('Catalogo de referencias complementares:'))
        for item in catalog[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get('nome', item.get('id', 'sistema')))
            category = str(item.get('categoria', 'indefinido'))
            mode = str(item.get('integracao_local', 'referencia'))
            url = str(item.get('source_url', ''))
            line = f'- {name} ({category}) | modo={mode}'
            if url:
                line += f' | {url}'
            pdf.multi_cell(0, 8, normalize_pdf_text(line))


def write_legal_notice(pdf):
    pdf.set_font('Arial', 'I', 9)
    text = (
        'Aviso tecnico-pericial: este documento possui natureza preliminar e finalidade exclusiva de apoio a investigacao. '
        'Não constitui prova pericial conclusiva isolada. Toda inferência automatizada exige revisão humana qualificada, '
        'confronto com cadeia de custódia, verificação documental e correlação com demais elementos probatórios.'
    )
    pdf.multi_cell(0, 7, normalize_pdf_text(text))


def write_human_review(pdf, human_review):
    if not isinstance(human_review, dict) or not human_review:
        pdf.multi_cell(0, 8, normalize_pdf_text('Conferência técnico-pericial não registrada nesta execução.'))
        return

    reviewed_at = str(human_review.get('reviewed_at_utc', human_review.get('reviewed_at', '')))
    selected_candidate = str(human_review.get('selected_candidate', human_review.get('candidate', '')))
    confirmed_text = str(human_review.get('confirmed_text', human_review.get('final_text', '')))
    operator = str(human_review.get('operator', human_review.get('responsavel', '')))
    decision = str(human_review.get('decision', human_review.get('final_decision', '')))
    notes = str(human_review.get('notes', human_review.get('observations', '')))
    status = str(human_review.get('status', 'indefinido'))

    review_fields = {
        'Status técnico-pericial': humanize_pericial_label(status),
        'Responsável': operator or '-',
        'Deliberação pericial': humanize_pericial_label(decision) if decision else '-',
        'Hipótese ratificada': selected_candidate or '-',
        'Texto ratificado': confirmed_text or '-',
        'Observações técnicas': notes or '-',
        'Revisado em UTC': reviewed_at or '-',
    }
    selected_engine = str(human_review.get('selected_candidate_engine', ''))
    if selected_engine:
        review_fields['Motor da hipótese'] = selected_engine
    selected_score = human_review.get('selected_candidate_score')
    if selected_score is not None and str(selected_score) != '':
        review_fields['Score da hipótese'] = f'{float(selected_score):.2f}'
    selected_confidence = human_review.get('selected_candidate_confidence')
    if selected_confidence is not None and str(selected_confidence) != '':
        review_fields['Confiança da hipótese'] = f'{float(selected_confidence):.2f}%'
    selected_support = human_review.get('selected_candidate_support_count')
    if selected_support is not None and str(selected_support) != '':
        review_fields['Apoio entre motores'] = str(selected_support)
    selected_agreement = human_review.get('selected_candidate_agreement_ratio')
    if selected_agreement is not None and str(selected_agreement) != '':
        review_fields['Concordancia entre motores'] = f'{float(selected_agreement):.1f}%'
    selected_region = str(human_review.get('selected_candidate_region', ''))
    if selected_region:
        review_fields['Região do recorte'] = selected_region

    write_key_values(pdf, review_fields)


ANALYSIS_REPORT_OUTLINE = get_analysis_report_outline()


def _safe_report_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_report_list(value):
    return value if isinstance(value, list) else []


def _safe_report_text(value, fallback='-'):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _safe_report_float(value, fallback=0.0):
    try:
        if value is None or value == '':
            return float(fallback)
        return float(value)
    except Exception:
        return float(fallback)


def write_analysis_overview(pdf, report_data):
    report_data = _safe_report_dict(report_data)
    input_meta = _safe_report_dict(report_data.get('input_meta'))
    pericial = _safe_report_dict(report_data.get('pericial'))
    forensic = _safe_report_dict(report_data.get('forensic'))
    consensus = _safe_report_dict(report_data.get('consensus'))
    assessment = _safe_report_dict(report_data.get('assessment'))
    human_review = _safe_report_dict(report_data.get('human_review'))
    plate_detection = _safe_report_dict(report_data.get('plate_detection')) or _safe_report_dict(input_meta.get('plate_detection'))
    capture_integrity = (
        _safe_report_dict(report_data.get('capture_integrity'))
        or _safe_report_dict(pericial.get('capture_integrity'))
        or _safe_report_dict(input_meta.get('capture_integrity'))
    )
    plate_pattern_info = (
        _safe_report_dict(report_data.get('plate_pattern_info'))
        or _safe_report_dict(pericial.get('plate_pattern_info'))
        or _safe_report_dict(input_meta.get('plate_pattern_info'))
    )
    legal_validation = _safe_report_dict(pericial.get('legal_validation'))
    scene_preprocess = _safe_report_dict(input_meta.get('scene_preprocess')) or _safe_report_dict(input_meta.get('visual_scene_preprocess'))

    analysis_stage = str(report_data.get('analysis_stage', 'final') or 'final').strip().lower()
    if analysis_stage == 'preview':
        report_status = 'Pré-análise'
        report_state = 'Aguardando correção em tela'
        document_hint = (
            'A leitura ainda pode ser ajustada em tela; a consolidação documental só é '
            'liberada após conferência humana.'
        )
    else:
        report_status = 'Consolidado'
        report_state = 'Disponível para impressão documental'
        document_hint = (
            'A fonte original, o recorte bruto e o recorte tratado já foram confrontados e '
            'o resultado está apto para arquivamento e impressão.'
        )

    photo_path = str(report_data.get('foto_path') or report_data.get('original_path') or '').strip()
    raw_crop_path = str(report_data.get('crop_raw_path') or plate_detection.get('selected_raw_path') or '').strip()
    treated_crop_path = str(
        report_data.get('crop_treated_path')
        or report_data.get('placa_path')
        or plate_detection.get('selected_treated_path')
        or report_data.get('crop_path')
        or ''
    ).strip()

    source_resolution = input_meta.get('source_resolution') or report_data.get('source_resolution') or {}
    if isinstance(source_resolution, dict):
        source_resolution_text = f"{source_resolution.get('width', '?')}x{source_resolution.get('height', '?')} px"
    else:
        source_resolution_text = _safe_report_text(source_resolution, 'Indisponível')
    if source_resolution_text in ('Indisponível', '-') and photo_path and os.path.exists(photo_path):
        img_w, img_h = get_image_dimensions(photo_path)
        if img_w and img_h:
            source_resolution_text = f'{img_w}x{img_h} px'

    analysis_id = _safe_report_text(
        forensic.get('analysis_id')
        or report_data.get('analysis_id')
        or pericial.get('analysis_id'),
    )
    plate_text = _safe_report_text(
        human_review.get('confirmed_text')
        or report_data.get('ocr')
        or report_data.get('recognized_text')
        or report_data.get('plate_text'),
    )
    plate_pattern = _safe_report_text(
        plate_pattern_info.get('padrao_placa')
        or plate_pattern_info.get('plate_pattern')
        or plate_pattern_info.get('detected_pattern')
        or legal_validation.get('detected_pattern')
        or legal_validation.get('best_fit_pattern')
        or plate_detection.get('selected_shape_hint')
        or 'Indefinido',
    )
    style_hint = _safe_report_text(
        plate_pattern_info.get('style_hint')
        or plate_detection.get('selected_style_hint')
        or plate_detection.get('style_hint')
        or capture_integrity.get('plate_detection_selected_style_hint')
        or 'Indefinido',
    )
    style_confidence = _safe_report_float(
        plate_pattern_info.get('style_confidence')
        or plate_detection.get('selected_style_confidence')
        or plate_detection.get('style_confidence')
        or capture_integrity.get('plate_detection_selected_style_confidence')
        or 0.0,
    )
    capture_status = humanize_pericial_label(capture_integrity.get('status', 'indefinido'))
    capture_score = _safe_report_float(capture_integrity.get('integrity_score', 0.0), 0.0)
    consensus_ratio = _safe_report_float(consensus.get('agreement_ratio', consensus.get('consensus_ratio', 0.0)), 0.0)
    consensus_count = int(_safe_report_float(consensus.get('agreement_count', consensus.get('support_count', 0)), 0.0))
    engines_considered = int(_safe_report_float(consensus.get('engines_considered', consensus.get('total_engines', 0)), 0.0))
    review_status = humanize_pericial_label(
        human_review.get('decision_label', human_review.get('decision', 'pendente'))
    ) if human_review else 'Pendente'
    assessment_level = humanize_pericial_label(
        assessment.get('display_evidence_level', assessment.get('evidence_level', 'indefinido'))
    )
    assessment_confidence = _safe_report_float(assessment.get('confidence_percent', 0.0), 0.0)
    scene_family = humanize_pericial_label(scene_preprocess.get('selected_family', 'opencv')) if scene_preprocess else 'Indefinido'
    scene_variant = humanize_pericial_label(scene_preprocess.get('selected_variant', 'original')) if scene_preprocess else 'Indefinido'
    scene_reason = humanize_pericial_label(scene_preprocess.get('selection_reason', 'n/a')) if scene_preprocess else 'n/a'
    source_sha256 = _safe_report_text(
        forensic.get('source_sha256')
        or capture_integrity.get('source_sha256')
        or report_data.get('source_sha256'),
        'Indisponível',
    )
    crop_sha256 = _safe_report_text(
        forensic.get('plate_sha256')
        or forensic.get('crop_sha256')
        or report_data.get('crop_sha256'),
        'Indisponível',
    )
    original_name = _safe_report_text(os.path.basename(photo_path), 'Indisponível')
    raw_crop_name = _safe_report_text(os.path.basename(raw_crop_path), 'Indisponível')
    treated_crop_name = _safe_report_text(os.path.basename(treated_crop_path), 'Indisponível')

    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, normalize_pdf_text('Resumo técnico-documental'), 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(
        0,
        7,
        normalize_pdf_text(
            'Fluxo pericial: imagem-fonte preservada, recorte bruto documentado, recorte '
            'tratado confrontado, OCR em consenso e revisão humana antes da liberação '
            'documental.'
        ),
    )
    pdf.ln(2)

    write_key_values(pdf, {
        'Status do relatório': report_status,
        'Identificação da análise': analysis_id,
        'Etapa operacional': humanize_pericial_label(analysis_stage or 'final'),
        'Fonte documental': original_name,
        'Resolução da fonte': source_resolution_text,
        'Recorte bruto': raw_crop_name,
        'Recorte tratado': treated_crop_name,
        'Assinatura SHA-256 da fonte': source_sha256,
        'Assinatura SHA-256 do recorte': crop_sha256,
        'Família de tratamento': scene_family,
        'Variante técnica': scene_variant,
        'Motivo do tratamento': scene_reason,
        'Placa principal': plate_text,
        'Padrão visual': plate_pattern,
        'Estilo visual': f'{style_hint} ({style_confidence:.1f}%)' if style_hint != 'Indefinido' else 'Indefinido',
        'Integridade da captura': f'{capture_status} ({capture_score:.1f}/100)',
        'Nível técnico-probatório': f'{assessment_level} ({assessment_confidence:.1f}%)',
        'Consenso OCR': f'{consensus_ratio:.1f}% ({consensus_count}/{engines_considered} motores)',
        'Revisão humana': review_status,
        'Estado documental': report_state,
    })

    pdf.multi_cell(
        0,
        7,
        normalize_pdf_text(document_hint),
    )
    pdf.ln(1)

    write_report_outline(pdf, report_data.get('analysis_report_outline') or ANALYSIS_REPORT_OUTLINE)

    if capture_integrity:
        pdf.ln(1)
        pdf.multi_cell(
            0,
            7,
            normalize_pdf_text(
                'Indicadores de captura: '
                f"ROI={_safe_report_text(capture_integrity.get('plate_detection_selected_region', '-'))} | "
                f"ROI OCR={_safe_report_text(capture_integrity.get('plate_detection_ocr_selected_region', '-'))} | "
                f"Score={_safe_report_float(capture_integrity.get('integrity_score', 0.0), 0.0):.1f}"
            ),
        )


def generate_pdf_report(report_data, output_path):
    timestamp = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    pdf = AnalysisReportPDF()
    pdf.set_title('Relatório de Análise de Imagens')
    pdf.set_author('Grom_OCR')
    pdf.set_subject('Relatório técnico para correção em tela e impressão documental')
    pdf.alias_nb_pages()
    input_meta = report_data.get('input_meta', {})
    if not isinstance(input_meta, dict):
        input_meta = {}
    scene_preprocess = input_meta.get('scene_preprocess', {})
    if not isinstance(scene_preprocess, dict) or not scene_preprocess:
        scene_preprocess = input_meta.get('visual_scene_preprocess', {})
    if not isinstance(scene_preprocess, dict):
        scene_preprocess = {}
    plate_detection = input_meta.get('plate_detection', {})
    if not isinstance(plate_detection, dict):
        plate_detection = {}

    cover_metadata = [
        'Origem da foto: %s' % report_data.get('origem', 'Desconhecida'),
        'Gerado em: %s' % timestamp,
    ]
    forensic = report_data.get('forensic', {})
    if not isinstance(forensic, dict):
        forensic = {}
    analysis_id = report_data.get('analysis_id') or forensic.get('analysis_id')
    if analysis_id:
        cover_metadata.insert(0, 'Identificacao da analise: %s' % analysis_id)

    draw_report_cover_header(
        pdf,
        'Relatório de Análise de Imagens',
        'Análise técnica para correção em tela e impressão documental',
        cover_metadata,
    )

    write_analysis_overview(pdf, report_data)
    write_evidence_manifest_section(pdf, report_data)
    pdf.ln(4)

    write_section_title(pdf, 'Metadados da foto:')
    write_key_values(pdf, report_data.get('exif', {}))
    pdf.ln(3)

    foto_path = report_data.get('foto_path')
    raw_crop_path = report_data.get('crop_raw_path') or plate_detection.get('selected_raw_path') or report_data.get('placa_path')
    treated_crop_path = (
        report_data.get('crop_treated_path')
        or report_data.get('placa_path')
        or plate_detection.get('selected_treated_path')
        or raw_crop_path
    )
    comparison_sheet = build_capture_comparison_sheet(foto_path, raw_crop_path, treated_crop_path)
    if comparison_sheet:
        write_section_title(pdf, 'Comparativo documental da captura:')
        pdf.image(comparison_sheet, w=180)
        pdf.ln(2)
        source_resolution = input_meta.get('source_resolution') or {}
        if isinstance(source_resolution, dict):
            source_resolution_text = f"{source_resolution.get('width', '?')}x{source_resolution.get('height', '?')} px"
        else:
            source_resolution_text = str(source_resolution or 'Indisponível')
        if source_resolution_text == 'Indisponível' and foto_path and os.path.exists(foto_path):
            img_w, img_h = get_image_dimensions(foto_path)
            if img_w and img_h:
                source_resolution_text = f'{img_w}x{img_h} px'
        write_key_values(
            pdf,
            {
                'Fonte documental': os.path.basename(foto_path) if foto_path else 'Indisponível',
                'Resolução da fonte': source_resolution_text,
                'Recorte bruto': os.path.basename(raw_crop_path) if raw_crop_path else 'Indisponível',
                'Recorte tratado': os.path.basename(treated_crop_path) if treated_crop_path else 'Indisponível',
                'Assinatura SHA-256 da fonte': forensic.get('source_sha256', '-') if isinstance(forensic, dict) else '-',
                'Assinatura SHA-256 do recorte': forensic.get('plate_sha256', forensic.get('crop_sha256', '-')) if isinstance(forensic, dict) else '-',
            },
        )
        pdf.ln(3)

    if scene_preprocess:
        write_section_title(pdf, 'Tratamento técnico da imagem:')
        write_scene_preprocess(pdf, scene_preprocess)
        pdf.ln(3)

    input_security = input_meta.get('input_security', {})
    if not isinstance(input_security, dict):
        input_security = {}
    if input_security:
        write_section_title(pdf, 'Segurança da entrada e custódia:')
        write_input_security(pdf, input_security)
        pdf.ln(3)

    write_section_title(pdf, 'Identificação do veículo:')
    write_vehicle_identification(pdf, report_data.get('veiculo', {}))
    pdf.ln(3)

    if plate_detection:
        write_section_title(pdf, 'Detecção e recorte da placa:')
        write_plate_detection(pdf, plate_detection)
        pdf.ln(3)

    write_section_title(pdf, 'Resultado OCR da placa:')
    pdf.set_font('Arial', '', 12)
    pdf.multi_cell(0, 10, normalize_pdf_text(report_data.get('ocr', 'Não reconhecido')))
    pdf.ln(2)
    pdf.set_font('Arial', '', 10)

    leituras_conflitantes = report_data.get('pericial', {}).get('ocr_record', {}).get('leituras_conflitantes', [])
    if leituras_conflitantes:
        write_section_title(pdf, 'Confusão OCR ou dissonância entre motores:')
        for conflito in leituras_conflitantes:
            pdf.multi_cell(0, 8, normalize_pdf_text('- ' + conflito))
        pdf.ln(2)

    human_review = report_data.get('human_review', {})
    if isinstance(human_review, dict) and human_review:
        write_section_title(pdf, 'Conferência técnico-pericial:')
        write_human_review(pdf, human_review)
        pdf.ln(2)

    write_section_title(pdf, 'Cadeia de custódia técnico-digital:')
    write_forensic_chain(pdf, report_data.get('forensic', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Consenso entre motores OCR:')
    write_consensus(pdf, report_data.get('consensus', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Classificação técnico-probatória:')
    write_assessment(pdf, report_data.get('assessment', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Validação técnico-pericial automatizada:')
    write_pericial(pdf, report_data.get('pericial', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Perfil visual do veículo (hipótese técnico-visual):')
    write_visual_profile(pdf, report_data.get('visual_profile', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Fontes complementares auditáveis:')
    write_external_systems_comparison(pdf, report_data.get('external_systems_comparison', {}))
    pdf.ln(2)

    write_section_title(pdf, 'Motores OCR empregados:')
    write_ocr_engines(
        pdf,
        report_data.get('ocr_engines', {}),
        report_data.get('ocr_engine_status', {}),
        report_data.get('ocr_engine_summary', {}),
        report_data.get('engine_runtime', {}),
    )
    pdf.ln(2)

    warnings = report_data.get('warnings', [])
    if isinstance(warnings, list) and warnings:
        write_section_title(pdf, 'Alertas técnicos:')
        for warning in warnings:
            pdf.multi_cell(0, 8, normalize_pdf_text(f'- {warning}'))
        pdf.ln(2)

    write_legal_notice(pdf)
    pdf.output(output_path)


def write_plate_detection(pdf, plate_detection):
    plate_detection = _safe_report_dict(plate_detection)
    if not plate_detection:
        pdf.multi_cell(0, 8, normalize_pdf_text('Detecção da placa indisponível.'))
        return

    selected_metrics = _safe_report_dict(plate_detection.get('selected_metrics'))
    candidates = plate_detection.get('candidates', [])
    if not isinstance(candidates, list):
        candidates = []

    selected_style_hint = _safe_report_text(
        selected_metrics.get('style_hint')
        or plate_detection.get('selected_style_hint')
        or plate_detection.get('style_hint')
        or 'Indefinido',
    )
    selected_style_confidence = _safe_report_float(
        selected_metrics.get('style_confidence')
        or plate_detection.get('selected_style_confidence')
        or plate_detection.get('style_confidence')
        or 0.0,
    )
    ocr_style_hint = _safe_report_text(
        plate_detection.get('ocr_selected_style_hint')
        or plate_detection.get('ocr_style_hint')
        or 'Indefinido',
    )
    ocr_style_confidence = _safe_report_float(
        plate_detection.get('ocr_selected_style_confidence')
        or plate_detection.get('ocr_style_confidence')
        or 0.0,
    )
    raw_crop_name = os.path.basename(str(plate_detection.get('selected_raw_path', '') or '').strip()) or 'Indisponível'
    treated_crop_name = os.path.basename(str(plate_detection.get('selected_treated_path', '') or '').strip()) or 'Indisponível'

    write_key_values(pdf, {
        'Status da deteccao': humanize_pericial_label(plate_detection.get('status', 'indefinido')),
        'Estrategia de busca': humanize_pericial_label(plate_detection.get('strategy', 'plate_roi_first')),
        'Regiao selecionada': plate_detection.get('selected_region', '-'),
        'Fonte selecionada': humanize_pericial_label(plate_detection.get('selected_source', '-')),
        'Calibracao aplicada': humanize_pericial_label(plate_detection.get('calibration_source', 'builtin_default')),
        'Arquivo de calibracao': plate_detection.get('calibration_path', '-'),
        'Regiao usada no OCR': plate_detection.get('ocr_selected_region', '-'),
        'Fonte usada no OCR': humanize_pericial_label(plate_detection.get('ocr_selected_source', '-')),
        'Padrao visual do ROI': f'{selected_style_hint} ({selected_style_confidence:.1f}%)' if selected_style_hint != 'Indefinido' else 'Indefinido',
        'Padrao visual do OCR': f'{ocr_style_hint} ({ocr_style_confidence:.1f}%)' if ocr_style_hint != 'Indefinido' else 'Indefinido',
        'Recorte bruto': raw_crop_name,
        'Recorte tratado': treated_crop_name,
        'Quantidade de candidatos': plate_detection.get('candidate_count', 0),
        'Qualidade do recorte': plate_detection.get('selected_quality_score', 0.0),
        'Pontuação da seleção': plate_detection.get('selected_score', 0.0),
        'Formato presumido': humanize_pericial_label(plate_detection.get('selected_shape_hint', 'indefinida')),
        'Usou imagem completa': 'Sim' if plate_detection.get('used_full_image') else 'Não',
        'Modo OCR': humanize_pericial_label(plate_detection.get('ocr_line_mode', 'single_line')),
        'Lista permitida de caracteres': plate_detection.get('tesseract_whitelist', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'),
    })

    if selected_metrics:
        pdf.multi_cell(
            0,
            8,
            normalize_pdf_text(
                'Metricas do recorte selecionado: '
                f"aspecto={selected_metrics.get('aspect_ratio', 0)} | "
                f"brilho={selected_metrics.get('brightness', 0)} | "
                f"contraste={selected_metrics.get('contrast', 0)} | "
                f"nitidez={selected_metrics.get('sharpness', 0)} | "
                f"bordas={selected_metrics.get('edge_density', 0)} | "
                f"estilo={selected_style_hint} | "
                f"confianca_estilo={selected_style_confidence:.1f}%"
            ),
        )

    if candidates:
        pdf.multi_cell(0, 8, normalize_pdf_text('Melhores candidatos de placa:'))
        for item in candidates[:4]:
            if not isinstance(item, dict):
                continue
            item_style_hint = _safe_report_text(item.get('style_hint', 'Indefinido'))
            item_style_confidence = _safe_report_float(item.get('style_confidence', 0.0), 0.0)
            line = (
                f"- {humanize_pericial_label(item.get('region', '-'))} | fonte={humanize_pericial_label(item.get('source_family', '-'))}"
                f" | pontuacao={float(item.get('score', 0.0)):.1f}"
                f" | qualidade={float(item.get('quality_score', 0.0)):.1f}"
                f" | aspecto={float(item.get('aspect_ratio', 0.0)):.2f}"
                f" | nitidez={float(item.get('sharpness', 0.0)):.1f}"
            )
            if item_style_hint != 'Indefinido':
                line += f" | estilo={item_style_hint} ({item_style_confidence:.1f}%)"
            pdf.multi_cell(0, 8, normalize_pdf_text(line))

