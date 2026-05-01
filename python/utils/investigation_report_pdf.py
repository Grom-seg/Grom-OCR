from fpdf import FPDF
from datetime import datetime
import os

from utils.report_branding import (
    apply_formal_report_palette,
    draw_report_cover_header,
    draw_report_footer,
    draw_report_section_header,
    draw_report_watermark,
    get_image_dimensions,
    resolve_report_logo_path,
    REPORT_ACCENT_RGB,
    REPORT_LINE_RGB,
    REPORT_MUTED_RGB,
    REPORT_PANEL_RGB,
    REPORT_PRIMARY_RGB,
    REPORT_SECONDARY_RGB,
    REPORT_TEXT_RGB,
)
from utils.evidence_manifest import build_evidence_manifest, manifest_summary_dict
from utils.pericial_labels import format_report_label, format_report_value
from utils.pericial_labels import humanize_pericial_label
from utils.report_outline import get_analysis_report_outline
from utils.report_visuals import build_capture_comparison_sheet
from PIL import Image
import numpy as np


ANALYSIS_REPORT_OUTLINE = get_analysis_report_outline()


def _safe_float(value, fallback=0.0):
    try:
        if value is None or value == '':
            return float(fallback)
        return float(value)
    except Exception:
        return float(fallback)


def _safe_list(value):
    return value if isinstance(value, list) else []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _coerce_ocr_record(data):
    data = _as_dict(data)
    operational_protocol = _as_dict(data.get('operational_protocol'))
    pericial = _as_dict(data.get('pericial'))
    return _as_dict(
        data.get('ocr_record')
        or operational_protocol.get('ocr_record')
        or pericial.get('ocr_record')
    )


def _extract_scene_visual_summary(source_path):
    source_path = str(source_path or '').strip()
    if not source_path or not os.path.exists(source_path):
        return {}

    try:
        with Image.open(source_path) as source:
            image = source.convert('RGB')
            width, height = image.size
            if width <= 0 or height <= 0:
                return {}

            scale = max(1.0, float(max(width, height)) / 420.0)
            resized = image.resize(
                (max(48, int(round(width / scale))), max(48, int(round(height / scale)))),
                Image.Resampling.BILINEAR,
            )
            arr = np.asarray(resized, dtype=np.float32)
            if arr.size == 0:
                return {}

            norm = arr / 255.0
            rgb_max = np.max(norm, axis=2)
            rgb_min = np.min(norm, axis=2)
            saturation = rgb_max - rgb_min

            white_ratio = float(np.mean((arr[:, :, 0] > 170) & (arr[:, :, 1] > 170) & (arr[:, :, 2] > 170)) * 100.0)
            blue_ratio = float(np.mean((arr[:, :, 2] > arr[:, :, 0] + 12) & (arr[:, :, 2] > arr[:, :, 1] + 6) & (arr[:, :, 2] > 90)) * 100.0)
            bright_low_sat_ratio = float(np.mean((rgb_max > 0.72) & (saturation < 0.18)) * 100.0)

            lower_region = arr[int(arr.shape[0] * 0.58):, :, :] if arr.shape[0] >= 6 else arr
            if lower_region.size:
                lower_green_ratio = float(
                    np.mean(
                        (lower_region[:, :, 1] > lower_region[:, :, 0] + 2)
                        & (lower_region[:, :, 1] > lower_region[:, :, 2] + 2)
                        & (lower_region[:, :, 1] > 60)
                    ) * 100.0
                )
            else:
                lower_green_ratio = 0.0

            return {
                'white_ratio': round(white_ratio, 2),
                'blue_ratio': round(blue_ratio, 2),
                'bright_low_sat_ratio': round(bright_low_sat_ratio, 2),
                'lower_green_ratio': round(lower_green_ratio, 2),
                'source_resolution': {'width': width, 'height': height},
            }
    except Exception:
        return {}


def _resolve_scene_visual_summary(scene_context=None):
    scene_context = _as_dict(scene_context)
    summary = _as_dict(scene_context.get('scene_visual_summary'))
    if summary:
        return summary

    source_path = (
        scene_context.get('original_path')
        or scene_context.get('foto_path')
        or scene_context.get('photo_path')
        or ''
    )
    return _extract_scene_visual_summary(source_path)


def _resolve_scene_view_descriptor(visual_profile):
    visual_profile = _as_dict(visual_profile)
    component_profile = _as_dict(visual_profile.get('assinaturas_componentes'))
    geometry_profile = _as_dict(visual_profile.get('geometria'))
    rear_signature = _as_dict(visual_profile.get('lanterna_traseira'))

    low_context = bool(component_profile.get('low_context_blocked'))
    rear_layout_only = (
        str(rear_signature.get('source', '') or '').strip().lower() == 'rear_layout_hint'
        and not bool(rear_signature.get('vertical_pair'))
        and not rear_signature.get('left')
        and not rear_signature.get('right')
    )
    strong_frontal = bool(
        geometry_profile.get('dual_headlamps')
        and _safe_float(geometry_profile.get('frontal_symmetry', 0.0), 0.0) >= 65.0
        and 2.0 <= _safe_float(geometry_profile.get('grille_edge_density', 0.0), 0.0) <= 26.0
    )

    raw_view = str(visual_profile.get('vista_detectada', '') or '').strip().lower()
    if strong_frontal and (low_context or rear_layout_only or raw_view in ('indefinida', 'traseira')):
        return 'frontal'
    if not low_context and raw_view in ('frontal', 'traseira', 'lateral'):
        return raw_view
    return ''


def _coerce_report_ocr_results(data, ocr_record=None):
    data = _as_dict(data)
    ocr_results = _as_dict(data.get('ocr_results') or data.get('ocr_engines'))
    if ocr_results:
        return ocr_results

    ocr_record = _as_dict(ocr_record or _coerce_ocr_record(data))
    if not ocr_record:
        return {}

    synthetic = {}
    main_text = str(ocr_record.get('leitura_principal', '') or '').strip()
    if main_text:
        synthetic['ocr_record_principal'] = {
            'engine': 'ocr_record',
            'text': main_text,
            'avg_conf': _safe_float(
                ocr_record.get('avg_conf', ocr_record.get('confidencia_estimativa', 0.0)),
                0.0,
            ),
            'score': _safe_float(
                ocr_record.get('score_bruto', ocr_record.get('score', ocr_record.get('avg_conf', 0.0))),
                0.0,
            ),
            'pattern': str(ocr_record.get('padrao_placa', 'Indefinido') or 'Indefinido'),
            'region': str(ocr_record.get('pattern_source', 'ocr_record') or 'ocr_record'),
            'support_engines': _as_list(ocr_record.get('supports', [])),
        }

    for idx, alt in enumerate(_as_list(ocr_record.get('leitura_alternativas', [])), start=1):
        if not isinstance(alt, dict):
            continue
        text = str(alt.get('text', '') or '').strip()
        if not text:
            continue
        synthetic[f'ocr_record_alt_{idx}'] = {
            'engine': str(alt.get('engine', f'ocr_record_alt_{idx}')),
            'text': text,
            'avg_conf': _safe_float(
                alt.get(
                    'avg_conf',
                    alt.get('confidence', alt.get('conf', ocr_record.get('avg_conf', 0.0))),
                ),
                0.0,
            ),
            'score': _safe_float(
                alt.get('score', alt.get('weighted_support', alt.get('avg_conf', 0.0))),
                0.0,
            ),
            'pattern': str(alt.get('pattern', ocr_record.get('padrao_placa', 'Indefinido')) or 'Indefinido'),
            'region': str(alt.get('region', 'ocr_record') or 'ocr_record'),
            'support_engines': _as_list(alt.get('support_engines', alt.get('engines', []))),
        }

    if not synthetic and main_text:
        synthetic['ocr_record_summary'] = {
            'engine': 'ocr_record',
            'text': main_text,
            'avg_conf': _safe_float(
                ocr_record.get('avg_conf', ocr_record.get('confidencia_estimativa', 0.0)),
                0.0,
            ),
            'score': _safe_float(
                ocr_record.get('score_bruto', ocr_record.get('score', ocr_record.get('avg_conf', 0.0))),
                0.0,
            ),
            'pattern': str(ocr_record.get('padrao_placa', 'Indefinido') or 'Indefinido'),
            'region': 'ocr_record',
            'support_engines': _as_list(ocr_record.get('supports', [])),
        }

    return synthetic


def _build_scene_diagnosis_lines(scenario_label, tech_details, scene_context=None):
    scene_context = _as_dict(scene_context)
    input_meta = _as_dict(scene_context.get('input_meta'))
    scene_preprocess = _as_dict(
        scene_context.get('scene_preprocess')
        or input_meta.get('scene_preprocess')
        or input_meta.get('visual_scene_preprocess')
    )
    visual_profile = _as_dict(scene_context.get('visual_profile'))
    plate_detection = _as_dict(scene_context.get('plate_detection') or input_meta.get('plate_detection'))
    operational_protocol = _as_dict(scene_context.get('operational_protocol'))
    vehicle_basics = _as_dict(scene_context.get('vehicle_basics') or operational_protocol.get('vehicle_basics'))
    scene_visual_summary = _resolve_scene_visual_summary(scene_context)
    component_profile = _as_dict(visual_profile.get('assinaturas_componentes'))
    low_context = bool(component_profile.get('low_context_blocked'))

    lines = []
    label = str(scenario_label or scene_preprocess.get('scenario_display_label') or 'Indeterminado').strip()
    if label:
        lines.append(f'Cenário identificado: {label}.')

    context_bits = []
    scene_reasons = _as_list(scene_preprocess.get('scenario_reasons', []))
    if scene_reasons:
        context_bits.append(
            'motivos do pré-processamento: ' + ', '.join(
                str(item).replace('_', ' ') for item in scene_reasons[:3]
            )
        )
    primary = str(scene_preprocess.get('scenario_primary', scene_preprocess.get('scenario_label', '')) or '').strip().lower()
    if primary == 'bright' or label.lower() in ('muito claro', 'claro'):
        context_bits.append('cena externa com iluminação natural forte e reflexos moderados')

    candidate_count = int(_safe_float(plate_detection.get('candidate_count', 0.0), 0.0))
    if candidate_count >= 10:
        context_bits.append(
            'enquadramento amplo com múltiplos veículos estacionados e diversos contornos candidatos'
        )
        context_bits.append('veículos posicionados lado a lado no enquadramento')

    if 'comparativo_aberto_disponivel' in _as_list(vehicle_basics.get('observacoes', [])):
        context_bits.append('ambiente aberto com comparação visual disponível')

    scene_view = _resolve_scene_view_descriptor(visual_profile)
    if scene_view == 'frontal':
        if candidate_count >= 3:
            context_bits.append('faces frontais predominantes entre os veículos visíveis')
        else:
            context_bits.append('vista predominante frontal')
    elif scene_view in ('traseira', 'lateral'):
        context_bits.append(f'vista predominante {humanize_pericial_label(scene_view)}')

    white_ratio = _safe_float(scene_visual_summary.get('white_ratio', 0.0), 0.0)
    bright_low_sat_ratio = _safe_float(scene_visual_summary.get('bright_low_sat_ratio', 0.0), 0.0)
    lower_green_ratio = _safe_float(scene_visual_summary.get('lower_green_ratio', 0.0), 0.0)
    if white_ratio >= 26.0 and bright_low_sat_ratio >= 24.0:
        context_bits.append('veículos claros, com predominância de branco')
    elif not low_context:
        cor_probavel = str(visual_profile.get('cor_probavel', '') or '').strip()
        if cor_probavel:
            context_bits.append(f'cor predominante observada {cor_probavel}')

    if lower_green_ratio >= 16.0:
        context_bits.append('cena em área aberta com faixa gramada visível')

    if primary == 'bright' and candidate_count >= 10:
        context_bits.append('sugere fileira de veículos em área aberta, com predominância de placa visível')

    if context_bits:
        unique_bits = list(dict.fromkeys(context_bits))
        lines.append('Leitura contextual: ' + '; '.join(unique_bits) + '.')

    if tech_details:
        lines.append(f'Estratégia de restauração: {tech_details}.')

    selected_region = str(plate_detection.get('selected_region', '') or '').strip()
    if selected_region:
        lines.append(f'ROI principal: {selected_region}.')

    if not lines:
        lines.append('Cenário identificado: Indeterminado.')
        if tech_details:
            lines.append(f'Estratégia de restauração: {tech_details}.')

    return lines


def write_analysis_outline(pdf, outline=None):
    outline = _safe_list(outline) or ANALYSIS_REPORT_OUTLINE
    if not outline:
        pdf.multi_cell(0, 8, pdf.normalize_text('Procedimentos informados indisponíveis.'))
        return

    pdf.set_font('Arial', 'B', 10)
    pdf.multi_cell(0, 7, pdf.normalize_text('Procedimentos efetuados na análise:'))
    pdf.set_font('Arial', '', 10)

    for section in outline:
        if not isinstance(section, dict):
            continue
        number = str(section.get('number', '') or '').strip()
        title = str(section.get('title', '') or '').strip()
        summary = str(section.get('summary', '') or '').strip()
        subitems = _safe_list(section.get('subitems'))

        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 6, pdf.normalize_text(f'{number} - {title}'.strip(' -')))
        if summary:
            pdf.set_font('Arial', '', 9)
            pdf.multi_cell(0, 5, pdf.normalize_text(summary))

        for subitem in subitems:
            if not isinstance(subitem, dict):
                continue
            sub_number = str(subitem.get('number', '') or '').strip()
            sub_title = str(subitem.get('title', '') or '').strip()
            sub_summary = str(subitem.get('summary', '') or '').strip()
            pdf.set_font('Arial', 'B', 9)
            pdf.multi_cell(0, 5, pdf.normalize_text(f'  {sub_number} - {sub_title}'.strip()))
            if sub_summary:
                pdf.set_font('Arial', '', 8.5)
                pdf.multi_cell(0, 5, pdf.normalize_text(f'    {sub_summary}'))
        pdf.ln(1)


class InvestigationReport(FPDF):
    def __init__(self):
        super(InvestigationReport, self).__init__()
        self.set_auto_page_break(auto=True, margin=28)
        self.set_margins(12, 18, 12)
        self.add_page()
        self.set_font("Arial", size=12)
        apply_formal_report_palette(self)

    def _draw_watermark(self):
        draw_report_watermark(self, logo_path=resolve_report_logo_path())

    def header(self):
        self._draw_watermark()

    def footer(self):
        draw_report_footer(self, logo_path=resolve_report_logo_path(), date_text=datetime.now().strftime('%d/%m/%Y'))

    def normalize_text(self, text):
        return str(text).encode('latin-1', 'replace').decode('latin-1')

    def add_section_title(self, number, title):
        self.ln(2)
        draw_report_section_header(self, f'{number} - {format_report_label(title)}', level='section')

    def add_subsection_title(self, number, title):
        draw_report_section_header(self, f'{number} - {format_report_label(title)}', level='subsection')

    def add_key_value(self, key, value):
        self.set_font('Arial', 'B', 9)
        self.cell(60, 7, self.normalize_text(f'{format_report_label(key)}:'), 0, 0)
        self.set_font('Arial', '', 9)
        self.cell(0, 7, self.normalize_text(format_report_value(value) if value not in (None, '') else 'N/A'), 0, 1)

    def draw_ocr_summary_panel(self, plate_text, confidence_text, consensus_text, pattern_text):
        left = float(getattr(self, 'l_margin', 12.0))
        right = float(getattr(self, 'r_margin', 12.0))
        usable_width = float(getattr(self, 'w', 210.0)) - left - right
        top = float(getattr(self, 'y', 0.0))
        panel_h = 29.0

        self.set_draw_color(*REPORT_LINE_RGB)
        self.set_fill_color(*REPORT_PANEL_RGB)
        self.rect(left, top, usable_width, panel_h, 'DF')

        self.set_fill_color(*REPORT_ACCENT_RGB)
        self.rect(left, top, 2.6, panel_h, 'F')

        self.set_xy(left + 6.0, top + 3.0)
        self.set_font('Helvetica', 'B', 7.8)
        self.set_text_color(*REPORT_SECONDARY_RGB)
        self.cell(0, 4, self.normalize_text('LEITURA CONSOLIDADA'), 0, 1, 'L')

        self.set_xy(left + 6.0, top + 8.5)
        self.set_font('Times', 'B', 24)
        self.set_text_color(*REPORT_PRIMARY_RGB)
        self.cell(0, 8, self.normalize_text(plate_text or 'Nao conclusivo'), 0, 1, 'L')

        chip_y = top + 18.4
        chip_gap = 2.8
        chip_w = (usable_width - 12.0 - (chip_gap * 2.0)) / 3.0
        chip_x = left + 6.0
        chips = [
            ('Confianca estimada', confidence_text),
            ('Consenso OCR', consensus_text),
            ('Padrao legal', pattern_text),
        ]

        for label, value in chips:
            self.set_draw_color(*REPORT_LINE_RGB)
            self.set_fill_color(255, 255, 255)
            self.rect(chip_x, chip_y, chip_w, 7.6, 'DF')
            self.set_xy(chip_x + 2.0, chip_y + 0.9)
            self.set_font('Helvetica', 'B', 6.6)
            self.set_text_color(*REPORT_MUTED_RGB)
            self.cell(chip_w - 4.0, 2.8, self.normalize_text(label.upper()), 0, 2, 'L')
            self.set_x(chip_x + 2.0)
            self.set_font('Helvetica', 'B', 8.9)
            self.set_text_color(*REPORT_TEXT_RGB)
            self.cell(chip_w - 4.0, 3.1, self.normalize_text(value or '-'), 0, 0, 'L')
            chip_x += chip_w + chip_gap

        self.set_text_color(*REPORT_TEXT_RGB)
        self.set_y(top + panel_h + 2.6)

    def add_visual_assisted_vehicle_section(self, assisted_identification):
        assisted_identification = _as_dict(assisted_identification)
        self.add_subsection_title('4.5', 'Identificação visual assistida')

        if not assisted_identification:
            self.set_font('Arial', '', 10)
            self.multi_cell(
                0,
                7,
                self.normalize_text(
                    'Camada de identificação visual assistida indisponível nesta execução.'
                ),
            )
            self.ln(3)
            return

        status = humanize_pericial_label(assisted_identification.get('status', 'indefinido'))
        label = str(assisted_identification.get('label', 'Indeterminado') or 'Indeterminado').strip()
        confidence = _safe_float(assisted_identification.get('confidence', 0.0), 0.0)
        self.add_key_value('Hipótese visual assistida', label)
        self.add_key_value('Status operacional', status)
        self.add_key_value('Confiança estimada', f'{confidence:.1f}%')
        self.add_key_value(
            'Natureza da evidência',
            humanize_pericial_label(assisted_identification.get('evidence_role', 'apoio_tecnico_visual')),
        )
        self.add_key_value(
            'Revisão humana',
            'Obrigatória' if assisted_identification.get('manual_review_required', True) else 'Dispensável',
        )
        self.add_key_value(
            'Corroboração externa',
            'Sim' if assisted_identification.get('corroborated') else 'Não',
        )
        self.add_key_value(
            'Sistemas de apoio',
            int(assisted_identification.get('supporting_systems_count', 0) or 0),
        )
        if assisted_identification.get('cor'):
            self.add_key_value('Cor inferida', assisted_identification.get('cor'))
        if assisted_identification.get('ano'):
            self.add_key_value('Ano/faixa', assisted_identification.get('ano'))
        if assisted_identification.get('tipo_carroceria'):
            self.add_key_value('Carroceria', assisted_identification.get('tipo_carroceria'))
        if assisted_identification.get('vista_detectada'):
            self.add_key_value('Vista analisada', assisted_identification.get('vista_detectada'))

        statement = str(assisted_identification.get('statement', '') or '').strip()
        if statement:
            self.set_font('Arial', '', 10)
            self.multi_cell(0, 7, self.normalize_text(statement))

        supporting_systems = _as_list(assisted_identification.get('supporting_systems'))
        if supporting_systems:
            lines = []
            for item in supporting_systems[:3]:
                if not isinstance(item, dict):
                    continue
                system_label = str(item.get('nome', item.get('id', 'sistema_externo')) or 'sistema_externo').strip()
                vehicle_label = ' '.join(
                    [
                        part for part in [
                            str(item.get('fabricante', '') or '').strip(),
                            str(item.get('modelo', '') or '').strip(),
                        ] if part
                    ]
                ).strip() or 'indeterminado'
                vehicle_confidence = _safe_float(item.get('vehicle_confidence', 0.0), 0.0)
                lines.append(f'{system_label}: {vehicle_label} ({vehicle_confidence:.1f}%)')
            if lines:
                self.multi_cell(
                    0,
                    7,
                    self.normalize_text('Sistemas de apoio: ' + ' | '.join(lines)),
                )

        alternatives = _as_list(assisted_identification.get('alternatives'))
        if alternatives:
            alt_lines = []
            for item in alternatives[:3]:
                if not isinstance(item, dict):
                    continue
                alt_label = str(item.get('label', '') or '').strip()
                alt_conf = _safe_float(item.get('confidence', 0.0), 0.0)
                alt_year = str(item.get('year_range', '') or '').strip()
                if not alt_label:
                    continue
                if alt_year:
                    alt_lines.append(f'{alt_label} ({alt_conf:.1f}% | {alt_year})')
                else:
                    alt_lines.append(f'{alt_label} ({alt_conf:.1f}%)')
            if alt_lines:
                self.multi_cell(
                    0,
                    7,
                    self.normalize_text('Hipóteses alternativas: ' + ' | '.join(alt_lines)),
                )

        disclaimer = str(assisted_identification.get('disclaimer', '') or '').strip()
        if disclaimer:
            self.set_font('Arial', 'I', 9)
            self.multi_cell(0, 6, self.normalize_text(disclaimer))
        self.ln(3)

    def add_report_overview_section(self, data):
        data = data if isinstance(data, dict) else {}
        forensic = data.get('forensic_chain', {})
        if not isinstance(forensic, dict):
            forensic = {}
        consensus = data.get('consensus', {})
        if not isinstance(consensus, dict):
            consensus = {}
        assessment = data.get('assessment', {})
        if not isinstance(assessment, dict):
            assessment = {}
        pericial = data.get('pericial', {})
        if not isinstance(pericial, dict):
            pericial = {}
        human_review = data.get('human_review', {})
        if not isinstance(human_review, dict):
            human_review = {}
        capture_integrity = data.get('capture_integrity', {})
        if not isinstance(capture_integrity, dict):
            capture_integrity = {}
        plate_pattern_info = data.get('plate_pattern_info', {})
        if not isinstance(plate_pattern_info, dict):
            plate_pattern_info = {}
        plate_detection = data.get('plate_detection', {})
        if not isinstance(plate_detection, dict):
            plate_detection = {}
        input_meta = data.get('input_meta', {})
        if not isinstance(input_meta, dict):
            input_meta = {}
        operational_protocol = _as_dict(data.get('operational_protocol'))
        legal_validation = pericial.get('legal_validation', {})
        if not isinstance(legal_validation, dict):
            legal_validation = {}
        ocr_record = _coerce_ocr_record(data)
        ocr_results = _coerce_report_ocr_results(data, ocr_record=ocr_record)
        metadata = data.get('metadata', {})
        if not isinstance(metadata, dict):
            metadata = {}
        scene_preprocess = input_meta.get('scene_preprocess', {})
        if not isinstance(scene_preprocess, dict) or not scene_preprocess:
            scene_preprocess = input_meta.get('visual_scene_preprocess', {})
        if not isinstance(scene_preprocess, dict):
            scene_preprocess = {}

        plate_text = str(
            consensus.get('best_text', '')
            or ocr_record.get('leitura_principal', '')
            or data.get('ocr', '')
            or ''
        ).strip()
        if not plate_text:
            for engine_result in ocr_results.values():
                if not isinstance(engine_result, dict):
                    continue
                candidate_text = str(engine_result.get('text', '') or '').strip()
                if candidate_text:
                    plate_text = candidate_text
                    break
        if not plate_text:
            plate_text = 'Indefinido'

        plate_pattern = (
            str(plate_pattern_info.get('padrao_placa', '') or '').strip()
            or str(plate_pattern_info.get('plate_pattern', '') or '').strip()
            or str(plate_pattern_info.get('detected_pattern', '') or '').strip()
            or str(ocr_record.get('padrao_placa', '') or '').strip()
            or str(legal_validation.get('detected_pattern', '') or '').strip()
            or str(legal_validation.get('best_fit_pattern', '') or '').strip()
            or str(plate_detection.get('selected_shape_hint', '') or '').strip()
            or 'Indefinido'
        )
        style_hint = (
            str(plate_pattern_info.get('style_hint', '') or '').strip()
            or str(plate_detection.get('selected_style_hint', '') or '').strip()
            or str(plate_detection.get('style_hint', '') or '').strip()
            or 'Indefinido'
        )
        style_confidence = _safe_float(
            plate_pattern_info.get('style_confidence', 0.0)
            or plate_detection.get('selected_style_confidence', 0.0)
            or plate_detection.get('style_confidence', 0.0)
            or 0.0
        )
        consensus_ratio = _safe_float(
            consensus.get(
                'agreement_ratio',
                consensus.get(
                    'consensus_ratio',
                    consensus.get('agreement_ratio_percent', ocr_record.get('agreement_ratio', 0.0)),
                ),
            )
            or 0.0
        )
        record_alt_count = len(_as_list(ocr_record.get('leitura_alternativas', [])))
        record_support_count = len(_as_list(ocr_record.get('supports', [])))
        consensus_count = int(
            max(
                _safe_float(consensus.get('agreement_count', consensus.get('support_count', 0)) or 0.0, 0.0),
                len(ocr_results),
                record_alt_count,
                record_support_count,
            )
        )
        engines_considered = int(
            max(
                _safe_float(consensus.get('engines_considered', consensus.get('total_engines', 0)) or 0.0, 0.0),
                len(ocr_results),
                record_support_count,
                record_alt_count,
                1 if plate_text != 'Indefinido' else 0,
            )
        )
        capture_status = humanize_pericial_label(capture_integrity.get('status', 'indefinido'))
        capture_score = _safe_float(capture_integrity.get('integrity_score', 0.0) or 0.0)
        review_status = humanize_pericial_label(human_review.get('decision_label', human_review.get('decision', 'Pendente')))
        analysis_id = str(
            forensic.get('analysis_id', data.get('analysis_id', pericial.get('analysis_id', '-')))
        )
        analysis_stage = str(data.get('analysis_stage', 'final') or 'final').strip().lower()
        if analysis_stage == 'preview':
            report_state = 'Aguardando correção em tela'
            document_hint = 'Corrija a leitura para liberar o documento final.'
            report_status = 'Pré-análise'
        else:
            report_state = 'Disponível para impressão documental'
            document_hint = 'Documento pronto para conferência, arquivamento e impressão.'
            report_status = 'Consolidado'
        assessment_level = str(assessment.get('display_evidence_level', assessment.get('evidence_level', 'Indefinido')))
        assessment_confidence = _safe_float(
            assessment.get(
                'confidence_percent',
                assessment.get(
                    'confidence',
                    assessment.get('avg_conf', ocr_record.get('confidencia_estimativa', ocr_record.get('avg_conf', 0.0))),
                ),
            )
            or 0.0
        )
        photo_path = str(data.get('original_path', '') or '').strip()
        raw_crop_path = str(data.get('crop_raw_path') or data.get('crop_path') or '').strip()
        treated_crop_path = str(data.get('crop_treated_path') or data.get('crop_path') or raw_crop_path).strip()
        source_resolution = metadata.get('resolution') or input_meta.get('source_resolution') or {}
        if isinstance(source_resolution, dict):
            source_resolution_text = f"{source_resolution.get('width', '?')}x{source_resolution.get('height', '?')} px"
        else:
            source_resolution_text = str(source_resolution or 'Indisponível')
        if source_resolution_text == 'Indisponível' and photo_path and os.path.exists(photo_path):
            img_w, img_h = get_image_dimensions(photo_path)
            if img_w and img_h:
                source_resolution_text = f'{img_w}x{img_h} px'
        source_sha256 = str(forensic.get('source_sha256', '') or capture_integrity.get('source_sha256', '') or '-')
        crop_sha256 = str(
            forensic.get('plate_sha256', forensic.get('crop_sha256', '-'))
            if isinstance(forensic, dict)
            else '-'
        )
        source_name = os.path.basename(photo_path) if photo_path else 'Indisponível'
        raw_crop_name = os.path.basename(raw_crop_path) if raw_crop_path else 'Indisponível'
        treated_crop_name = os.path.basename(treated_crop_path) if treated_crop_path else 'Indisponível'
        scene_family = humanize_pericial_label(scene_preprocess.get('selected_family', 'opencv') or 'opencv')
        scene_variant = humanize_pericial_label(scene_preprocess.get('selected_variant', 'original') or 'original')
        scene_reason = humanize_pericial_label(scene_preprocess.get('selection_reason', 'n/a') or 'n/a')
        partial_plate_evidence = _as_dict(
            data.get('partial_plate_evidence')
            or pericial.get('partial_plate_evidence')
            or input_meta.get('partial_plate_evidence')
        )
        partial_plate_candidates = _as_list(
            data.get('partial_plate_candidates')
            or partial_plate_evidence.get('partial_plate_candidates')
            or pericial.get('partial_plate_candidates')
        )
        partial_plate_text = str(
            data.get('partial_plate_text')
            or partial_plate_evidence.get('partial_plate_text')
            or pericial.get('partial_plate_text')
            or ''
        ).strip()
        partial_plate_summary = str(
            data.get('partial_plate_summary')
            or partial_plate_evidence.get('partial_plate_summary')
            or pericial.get('partial_plate_summary')
            or ''
        ).strip()
        assisted_identification = _as_dict(
            data.get('assisted_vehicle_identification')
            or _as_dict(pericial.get('cross_checks')).get('assisted_vehicle_identification')
        )

        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, self.normalize_text('Resumo técnico-documental'), 0, 1)
        self.set_font('Arial', '', 10)
        self.multi_cell(
            0,
            7,
            self.normalize_text(
                'Fluxo pericial: imagem-fonte preservada, recorte bruto documentado, recorte tratado '
                'confrontado, OCR em consenso e revisão humana antes da liberação documental.'
            ),
        )
        self.ln(2)

        self.add_key_value('Status do relatório', report_status)
        self.add_key_value('Identificação da análise', analysis_id)
        self.add_key_value('Placa principal', plate_text)
        self.add_key_value('Padrão visual', plate_pattern)
        self.add_key_value(
            'Estilo visual',
            f'{style_hint} ({style_confidence:.1f}%)' if style_hint != 'Indefinido' else 'Indefinido',
        )
        self.add_key_value('Integridade da captura', f'{capture_status} ({capture_score:.1f}/100)')
        self.add_key_value('Nível técnico-probatório', f'{assessment_level} ({assessment_confidence:.1f}%)')
        self.add_key_value('Consenso OCR', f'{consensus_ratio:.1f}% ({consensus_count}/{engines_considered} motores)')
        self.add_key_value('Revisão humana', review_status if review_status else 'Pendente')
        self.add_key_value('Fonte documental', f'{source_name} | {source_resolution_text}')
        self.add_key_value('Recorte bruto', raw_crop_name)
        self.add_key_value('Recorte tratado', treated_crop_name)
        self.add_key_value('Assinatura SHA-256 da fonte', source_sha256)
        self.add_key_value('Assinatura SHA-256 do recorte', crop_sha256)
        self.add_key_value('Tratamento técnico', f'{scene_family} | {scene_variant} | {scene_reason}')
        if assisted_identification:
            assisted_label = str(assisted_identification.get('label', 'Indeterminado') or 'Indeterminado').strip()
            assisted_status = humanize_pericial_label(assisted_identification.get('status', 'indefinido'))
            assisted_conf = _safe_float(assisted_identification.get('confidence', 0.0), 0.0)
            self.add_key_value(
                'Identificação visual assistida',
                f'{assisted_label} | {assisted_status} | {assisted_conf:.1f}%',
            )
        partial_label = partial_plate_text or ('Sim' if partial_plate_candidates else 'Não')
        if partial_label.lower() in ('indefinido', 'indefinida', '-', 'n/a', 'na', 'nao', 'não'):
            partial_label = 'Sim' if partial_plate_candidates else 'Não'
        if partial_plate_candidates:
            partial_label = f'{partial_label} | {len(partial_plate_candidates)} fragmento(s)'
        self.add_key_value('Leitura parcial', partial_label)
        if partial_plate_summary:
            self.multi_cell(0, 7, self.normalize_text(f'Fragmentos preservados para confronto: {partial_plate_summary}'))

        self.multi_cell(0, 7, self.normalize_text(document_hint))
        self.ln(2)

        write_analysis_outline(self, data.get('analysis_report_outline'))

        if capture_integrity:
            self.ln(2)
            self.multi_cell(
                0,
                7,
                self.normalize_text(
                    'Indicadores de captura: '
                    f"ROI={capture_integrity.get('plate_detection_selected_region', '-')}"
                    f" | ROI OCR={capture_integrity.get('plate_detection_ocr_selected_region', '-')}"
                    f" | Score={float(capture_integrity.get('integrity_score', 0.0) or 0.0):.1f}"
                ),
            )

        self.ln(3)

    def add_metadata_section(self, metadata):
        """Section 0: Detailed EXIF and Capture Metadata"""
        self.add_section_title(0, 'Metadados técnicos da captura')

        if not metadata or not isinstance(metadata, dict):
            self.set_font('Arial', 'I', 10)
            self.multi_cell(0, 8, self.normalize_text(
                'Metadados EXIF nao disponiveis para este arquivo.'
            ))
            return

        # Camera Info
        self.add_subsection_title('0.1', 'Dispositivo de captura')
        camera = metadata.get('camera') or 'Indefinido'
        make = metadata.get('camera_make')
        model = metadata.get('camera_model')
        if make and model:
            camera = f'{make} {model}'
        elif make:
            camera = make
        elif model:
            camera = model
        self.add_key_value('Dispositivo', camera)
        if metadata.get('software'):
            self.add_key_value('Software', metadata['software'])

        # Temporal Info
        self.add_subsection_title('0.2', 'Dados Temporais')
        dt_original = metadata.get('datetime_original') or metadata.get('timestamp')
        dt_digitized = metadata.get('datetime_digitized')
        self.add_key_value('Data/Hora Original', dt_original or 'Indisponivel')
        if dt_digitized and dt_digitized != dt_original:
            self.add_key_value('Data/Hora Digitalizacao', dt_digitized)

        # Resolution & Imaging
            self.add_subsection_title('0.3', 'Parâmetros da imagem')
        resolution = metadata.get('resolution')
        if isinstance(resolution, dict):
            res_str = f"{resolution.get('width', '?')}x{resolution.get('height', '?')}"
        else:
            res_str = str(resolution or 'Indisponivel')
        self.add_key_value('Resolucao', res_str)
        if metadata.get('orientation'):
            self.add_key_value('Orientacao EXIF', metadata['orientation'])

        # Photographic parameters
        exposure = metadata.get('exposure_time')
        f_number = metadata.get('f_number')
        iso = metadata.get('iso')
        focal = metadata.get('focal_length')
        flash = metadata.get('flash')
        has_photo_params = any([exposure, f_number, iso, focal])

        if has_photo_params:
            self.add_subsection_title('0.4', 'Parâmetros fotográficos')
            if exposure:
                # ExposureTime can be a tuple (numerator, denominator)
                if isinstance(exposure, tuple) and len(exposure) == 2:
                    self.add_key_value('Exposicao', f'{exposure[0]}/{exposure[1]}s')
                else:
                    self.add_key_value('Exposicao', f'{exposure}s')
            if f_number:
                if isinstance(f_number, tuple) and len(f_number) == 2 and f_number[1]:
                    self.add_key_value('Abertura', f'f/{f_number[0] / f_number[1]:.1f}')
                else:
                    self.add_key_value('Abertura', f'f/{f_number}')
            if iso:
                self.add_key_value('ISO', iso)
            if focal:
                if isinstance(focal, tuple) and len(focal) == 2 and focal[1]:
                    self.add_key_value('Distancia Focal', f'{focal[0] / focal[1]:.1f}mm')
                else:
                    self.add_key_value('Distancia Focal', f'{focal}mm')
            if flash is not None:
                self.add_key_value('Flash', 'Sim' if flash else 'Nao')

        # GPS indicator
        if metadata.get('gps_available'):
            self.set_font('Arial', 'I', 9)
            self.multi_cell(0, 7, self.normalize_text(
                'Nota: Dados GPS presentes no arquivo. '
                'Coordenadas omitidas por padrão de segurança.'
            ))

        if not metadata.get('exif_present'):
            self.set_font('Arial', 'I', 9)
            self.multi_cell(0, 7, self.normalize_text(
                'Nota: O arquivo nao contem metadados EXIF embutidos. '
                'Dados de câmera e data/hora indisponíveis para validação técnica.'
            ))

        self.ln(3)

    def add_captura_section(self, original_img_path, crop_raw_img_path, crop_treated_img_path=None, metadata=None):
        self.add_section_title(1, 'Captura e análise da imagem')

        metadata = metadata if isinstance(metadata, dict) else {}
        camera = metadata.get('camera') or 'N/A'
        resolution = metadata.get('resolution')
        if isinstance(resolution, dict):
            res_str = f"{resolution.get('width', '?')}x{resolution.get('height', '?')}"
        else:
            res_str = str(resolution or 'N/A')
        timestamp = metadata.get('datetime_original') or metadata.get('timestamp') or 'N/A'

        self.set_font('Arial', 'B', 10)
        self.cell(0, 8, self.normalize_text('Resumo da captura:'), 0, 1)
        self.set_font('Arial', '', 10)
        self.cell(10)
        self.multi_cell(
            0,
            8,
            self.normalize_text(
                f'Câmera: {camera} | Resolução: {res_str} | Data/Hora: {timestamp}'
            ),
        )
        self.ln(2)

        raw_path = crop_raw_img_path or crop_treated_img_path or ''
        treated_path = crop_treated_img_path or crop_raw_img_path or ''
        comparison_sheet = build_capture_comparison_sheet(original_img_path, raw_path, treated_path)
        if comparison_sheet:
            self.set_font('Arial', 'I', 8)
            self.cell(0, 5, 'Figura 1: Comparativo documental da captura', 0, 1, 'L')
            self.image(comparison_sheet, x=12, w=186)
            self.ln(4)
            self.set_font('Arial', '', 9)
            self.multi_cell(
                0,
                6,
                self.normalize_text(
                    'A folha comparativa preserva a imagem-fonte, documenta o recorte bruto e '
                    'mostra o recorte tratado aplicado ao OCR.'
                ),
            )
            self.ln(2)

    def add_diagnostico_section(self, scenario_label, tech_details):
        self.add_section_title(2, 'Diagnóstico de cena')
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 8, self.normalize_text(f'Cenário identificado: {scenario_label}'))
        self.multi_cell(0, 8, self.normalize_text(f'Estratégia de restauração: {tech_details}'))
        self.ln(5)

    def add_diagnostico_section_v2(self, scenario_label, tech_details, scene_context=None):
        self.add_section_title(2, 'Diagnóstico de cena')
        self.set_font('Arial', '', 10.5)
        for line in _build_scene_diagnosis_lines(scenario_label, tech_details, scene_context=scene_context):
            self.multi_cell(0, 7, self.normalize_text(line))
        self.ln(4)

    def add_diagnostico_section(self, scenario_label, tech_details):
        return self.add_diagnostico_section_v2(
            scenario_label,
            tech_details,
            scene_context=getattr(self, '_scene_context', {}),
        )

    def add_tecnologia_section(self, steps):
        self.add_section_title(3, 'Fundamentação tecnológica')
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 8, self.normalize_text('Cadeia de processamento e algoritmos forenses aplicados:'))
        for step in steps:
            self.cell(10)
            self.cell(0, 8, self.normalize_text(f'- {step}'), 0, 1, 'L')
        self.ln(5)

    def add_consenso_section(self, ocr_results, suggested_vehicle, targets=None,
                              consensus=None, assessment=None):
        self.add_section_title(4, 'OCR, consenso e ambiguidade')

        # Section 4.1: OCR Ensemble Table
        self.add_subsection_title('4.1', 'Análise transversal de motores (ensemble logic)')

        # Table Header
        self.set_fill_color(240, 240, 240)
        self.set_font('Arial', 'B', 10)
        self.cell(45, 10, 'Motor / Algoritmo', 1, 0, 'C', 1)
        self.cell(45, 10, 'Leitura', 1, 0, 'C', 1)
        self.cell(35, 10, 'Confiança %', 1, 0, 'C', 1)
        self.cell(55, 10, 'Status Forense', 1, 1, 'C', 1)

        # Table Rows
        self.set_font('Arial', '', 10)
        for engine, res in ocr_results.items():
            if not isinstance(res, dict):
                continue
            self.cell(45, 8, self.normalize_text(engine), 1)
            self.cell(45, 8, self.normalize_text(res.get('text', '-')), 1)
            avg_conf = float(res.get('avg_conf', 0))
            self.cell(35, 8, f"{avg_conf:.1f}%", 1, 0, 'C')
            if avg_conf > 85:
                status = 'ALTA PRECISAO'
            elif res.get('text'):
                status = 'MODERADO'
            else:
                status = 'BAIXO SINAL'
            self.cell(55, 8, self.normalize_text(status), 1)
        self.ln(5)

        # Section 4.2: Consensus Result
        if consensus and isinstance(consensus, dict):
            self.add_subsection_title('4.2', 'Resultado do consenso entre motores')
            self.set_font('Arial', '', 10)
            best_text = consensus.get('best_text', '-')
            agreeing = consensus.get('agreeing_engines', [])
            agreement_ratio = consensus.get('agreement_ratio', 0)
            self.add_key_value('Placa Consensual', best_text or 'Não conclusivo')
            self.add_key_value('Motores em Acordo', f"{consensus.get('agreement_count', 0)} de {consensus.get('engines_considered', 0)}")
            self.add_key_value('Taxa de Acordo', f"{agreement_ratio:.1f}%")
            if agreeing:
                self.add_key_value('Motores Concordantes', ', '.join(str(e) for e in agreeing))
            self.ln(3)

        # Section 4.3: Assessment (Evidence Level)
        if assessment and isinstance(assessment, dict):
            self.add_subsection_title('4.3', 'Classificação técnico-probatória')
            self.set_font('Arial', '', 10)
            self.add_key_value('Nível probatório', assessment.get('display_evidence_level', assessment.get('evidence_level', '-')))
            self.add_key_value('Confiança', f"{assessment.get('confidence_percent', 0):.1f}%")
            self.add_key_value('Revisão manual', 'Obrigatória' if assessment.get('manual_review_required') else 'Dispensável')
            reasons = assessment.get('reasons', [])
            if isinstance(reasons, list) and reasons:
                self.add_key_value('Fundamentos', '; '.join(str(r) for r in reasons[:4]))
            self.ln(3)

        # Section 4.4: Multiple Targets
        if targets and isinstance(targets, list):
            primary_targets = [t for t in targets if isinstance(t, dict) and t.get('role') == 'primary']
            secondary_targets = [t for t in targets if isinstance(t, dict) and t.get('role') == 'secondary']

            if secondary_targets:
                self.add_subsection_title('4.4', 'Identificação multi-alvo (cenários múltiplos)')
                self.set_font('Arial', '', 10)
                self.multi_cell(0, 8, self.normalize_text(
                    f'Total de alvos distintos detectados: {len(targets)}'
                ))

                # Primary target highlight
                if primary_targets:
                    pt = primary_targets[0]
                    self.set_font('Arial', 'B', 10)
                    self.multi_cell(0, 8, self.normalize_text(
                        f"ALVO PRINCIPAL: [{pt.get('text', '-')}] | "
                        f"Conf: {pt.get('conf', 0):.1f}% | "
                        f"Padrão: {pt.get('pattern', '-')} | "
                        f"Motor: {pt.get('engine', '-')}"
                    ))

                # Secondary targets
                self.set_font('Arial', '', 10)
                for i, target in enumerate(secondary_targets, 1):
                    self.cell(10)
                    target_str = (
                        f"Alvo Secundario {i}: [{target.get('text', '-')}] | "
                        f"Conf: {target.get('conf', 0):.1f}% | "
                        f"Padrão: {target.get('pattern', '-')} | "
                        f"Motor: {target.get('engine', '-')}"
                    )
                    self.cell(0, 8, self.normalize_text(target_str), 0, 1)
                self.ln(5)

        # Suggested vehicle
        self.set_font('Arial', 'B', 11)
        self.multi_cell(0, 10, self.normalize_text(
            f'Veículo sugerido (consenso visual): {suggested_vehicle}'
        ))
        self.ln(5)

    def add_consenso_section_v2(self, ocr_results, suggested_vehicle, targets=None,
                                 consensus=None, assessment=None, ocr_record=None):
        self.add_section_title(4, 'OCR, consenso e ambiguidade')
        ocr_results = _as_dict(ocr_results)
        consensus = consensus if isinstance(consensus, dict) else {}
        assessment = assessment if isinstance(assessment, dict) else {}
        ocr_record = _as_dict(ocr_record)
        if not ocr_results and ocr_record:
            ocr_results = _coerce_report_ocr_results({'ocr_record': ocr_record}, ocr_record=ocr_record)

        consolidated_text = str(
            ocr_record.get('leitura_principal', '')
            or consensus.get('best_text', '')
            or next(
                (
                    res.get('text', '')
                    for res in ocr_results.values()
                    if isinstance(res, dict) and str(res.get('text', '') or '').strip()
                ),
                '',
            )
            or 'Não conclusivo'
        ).strip()
        consolidated_conf = _safe_float(
            ocr_record.get(
                'confidencia_estimativa',
                ocr_record.get(
                    'avg_conf',
                    assessment.get(
                        'confidence_percent',
                        assessment.get('confidence', assessment.get('avg_conf', 0.0)),
                    ),
                ),
            )
            or 0.0
        )
        consolidated_consensus = _safe_float(
            ocr_record.get(
                'agreement_ratio',
                consensus.get(
                    'agreement_ratio',
                    consensus.get('consensus_ratio', consensus.get('agreement_ratio_percent', 0.0)),
                ),
            )
            or 0.0
        )
        consolidated_pattern = (
            str(ocr_record.get('padrao_placa', '') or '').strip()
            or str(consensus.get('best_pattern', '') or '').strip()
            or str(consensus.get('pattern', '') or '').strip()
            or 'Indefinido'
        )

        self.add_subsection_title('4.1', 'Síntese OCR consolidada')
        self.draw_ocr_summary_panel(
            consolidated_text,
            f'{consolidated_conf:.1f}%',
            f'{consolidated_consensus:.1f}%',
            consolidated_pattern,
        )
        self.set_font('Arial', '', 10)
        if ocr_record.get('caracteres_incertos_resumo') or ocr_record.get('partial_plate_summary'):
            self.add_key_value(
                'Observação OCR',
                ocr_record.get('caracteres_incertos_resumo')
                or ocr_record.get('partial_plate_summary')
                or '-',
            )
        if ocr_record.get('leituras_conflitantes'):
            self.multi_cell(
                0,
                7,
                self.normalize_text(
                    'Leituras conflitantes: ' + '; '.join(
                        str(item) for item in _as_list(ocr_record.get('leituras_conflitantes', []))[:4]
                    )
                ),
            )
        self.ln(2)

        self.add_subsection_title('4.2', 'Análise transversal de motores (ensemble logic)')
        self.set_fill_color(240, 240, 240)
        self.set_font('Arial', 'B', 9)
        self.cell(46, 9, 'Motor / Algoritmo', 1, 0, 'C', 1)
        self.cell(44, 9, 'Leitura', 1, 0, 'C', 1)
        self.cell(34, 9, 'Confiança %', 1, 0, 'C', 1)
        self.cell(56, 9, 'Status Forense', 1, 1, 'C', 1)

        self.set_font('Arial', '', 8.8)
        engine_rows = []
        for engine, res in ocr_results.items():
            if not isinstance(res, dict):
                continue
            avg_conf = _safe_float(res.get('avg_conf', res.get('confidence', res.get('conf', 0.0))), 0.0)
            text = str(res.get('text', '') or '').strip()
            engine_rows.append((engine, res, avg_conf, text))

        engine_rows.sort(key=lambda item: item[2], reverse=True)
        visible_rows = [item for item in engine_rows if item[2] > 0.0 or item[3]]
        if not visible_rows:
            visible_rows = engine_rows[:4]

        for engine, res, avg_conf, text in visible_rows[:4]:
            self.cell(46, 8, self.normalize_text(format_report_label(engine)), 1)
            self.cell(44, 8, self.normalize_text(text or '-'), 1)
            self.cell(34, 8, f"{avg_conf:.1f}%", 1, 0, 'C')
            if avg_conf >= 85.0 or (avg_conf >= 75.0 and res.get('text')):
                status = 'ALTA PRECISAO'
            elif avg_conf >= 65.0:
                status = 'CONFIAVEL'
            elif res.get('text'):
                status = 'LEITURA PARCIAL'
            else:
                status = 'SEM LEITURA'
            self.cell(56, 8, self.normalize_text(status), 1, 1)
        self.ln(5)

        if consensus and isinstance(consensus, dict):
            self.add_subsection_title('4.3', 'Resultado do consenso entre motores')
            self.set_font('Arial', '', 10)
            best_text = consensus.get('best_text', consolidated_text or '-')
            agreeing = consensus.get('agreeing_engines', [])
            agreement_ratio = _safe_float(
                consensus.get('agreement_ratio', consensus.get('consensus_ratio', consolidated_consensus)) or 0.0,
                0.0,
            )
            engines_considered = consensus.get('engines_considered', len(ocr_results) or 0)
            self.add_key_value('Placa Consensual', best_text or 'Não conclusivo')
            self.add_key_value('Motores em Acordo', f"{consensus.get('agreement_count', 0)} de {engines_considered}")
            self.add_key_value('Taxa de Acordo', f"{agreement_ratio:.1f}%")
            if agreeing:
                self.add_key_value('Motores Concordantes', ', '.join(str(e) for e in agreeing))
            self.ln(3)

        if assessment and isinstance(assessment, dict):
            self.add_subsection_title('4.4', 'Classificação técnico-probatória')
            self.set_font('Arial', '', 10)
            self.add_key_value('Nível probatório', assessment.get('display_evidence_level', assessment.get('evidence_level', '-')))
            self.add_key_value(
                'Confiança',
                f"{_safe_float(assessment.get('confidence_percent', assessment.get('confidence', assessment.get('avg_conf', 0.0))), 0.0):.1f}%",
            )
            self.add_key_value('Revisão manual', 'Obrigatória' if assessment.get('manual_review_required') else 'Dispensável')
            reasons = assessment.get('reasons', [])
            if isinstance(reasons, list) and reasons:
                self.add_key_value('Fundamentos', '; '.join(str(r) for r in reasons[:4]))
            self.ln(3)

        assisted_identification = _as_dict(getattr(self, '_scene_context', {}).get('assisted_vehicle_identification'))
        if assisted_identification:
            self.add_visual_assisted_vehicle_section(assisted_identification)

        if targets and isinstance(targets, list):
            primary_targets = [t for t in targets if isinstance(t, dict) and t.get('role') == 'primary']
            secondary_targets = [t for t in targets if isinstance(t, dict) and t.get('role') == 'secondary']

            if secondary_targets:
                self.add_subsection_title('4.6', 'Identificação multi-alvo (cenários múltiplos)')
                self.set_font('Arial', '', 10)
                self.multi_cell(0, 8, self.normalize_text(
                    f'Total de alvos distintos detectados: {len(targets)}'
                ))

                if primary_targets:
                    pt = primary_targets[0]
                    self.set_font('Arial', 'B', 10)
                    self.multi_cell(0, 8, self.normalize_text(
                        f"ALVO PRINCIPAL: [{pt.get('text', '-')}] | "
                        f"Conf: {pt.get('conf', 0):.1f}% | "
                        f"Padrão: {pt.get('pattern', '-')} | "
                        f"Motor: {pt.get('engine', '-')}"
                    ))

                self.set_font('Arial', '', 10)
                for i, target in enumerate(secondary_targets, 1):
                    self.cell(10)
                    target_str = (
                        f"Alvo Secundario {i}: [{target.get('text', '-')}] | "
                        f"Conf: {target.get('conf', 0):.1f}% | "
                        f"Padrão: {target.get('pattern', '-')} | "
                        f"Motor: {target.get('engine', '-')}"
                    )
                    self.cell(0, 8, self.normalize_text(target_str), 0, 1)
                self.ln(5)

        self.set_font('Arial', 'B', 11)
        self.multi_cell(0, 10, self.normalize_text(
            f'Veículo sugerido (apoio visual): {suggested_vehicle}'
        ))
        self.ln(5)

    def add_consenso_section(self, ocr_results, suggested_vehicle, targets=None,
                              consensus=None, assessment=None):
        return self.add_consenso_section_v2(
            ocr_results,
            suggested_vehicle,
            targets=targets,
            consensus=consensus,
            assessment=assessment,
            ocr_record=getattr(self, '_ocr_record', {}),
        )

    def add_forensic_chain_section(self, forensic_chain, analysis_id=None):
        """Section 5: Chain of Custody"""
        self.add_section_title(5, 'Cadeia de custódia digital')

        if not forensic_chain or not isinstance(forensic_chain, dict):
            self.set_font('Arial', 'I', 10)
            self.multi_cell(0, 8, self.normalize_text(
                'Cadeia de custódia indisponível para esta análise.'
            ))
            return

        self.set_font('Arial', '', 10)
        self.add_key_value('ID da análise', analysis_id or forensic_chain.get('analysis_id', '-'))
        self.add_key_value('Inicio (UTC)', forensic_chain.get('started_at_utc', '-'))
        self.add_key_value('Fim (UTC)', forensic_chain.get('finished_at_utc', '-'))
        self.add_key_value('Hash SHA-256 Fonte', forensic_chain.get('source_sha256', '-'))
        self.add_key_value('Hash SHA-256 Recorte', forensic_chain.get('plate_sha256', forensic_chain.get('crop_sha256', '-')))
        self.add_key_value('Assinatura Digital', forensic_chain.get('signature', '-'))
        self.add_key_value('Algoritmo', forensic_chain.get('signature_algorithm', 'SHA256'))
        self.ln(5)

    def add_consideracoes_section(self, summary):
        self.set_font('Arial', 'B', 14)
        self.ln(5)
        self.cell(0, 10, 'Considerações finais', 'B', 1, 'L')
        self.ln(5)
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 8, self.normalize_text(summary))

        # Standard disclaimer
        self.ln(5)
        self.set_font('Arial', 'I', 9)
        self.multi_cell(0, 7, self.normalize_text(
            'NOTA: Este relatório constitui material técnico preliminar de apoio à investigação. '
            'Todos os resultados devem ser validados por profissional qualificado antes de '
            'utilização em procedimentos oficiais. O sistema aplica algoritmos automatizados '
            'de reconhecimento e não substitui a análise humana especializada.'
        ))


def write_evidence_manifest_section(pdf, data, analysis_kind=None):
    data = data if isinstance(data, dict) else {}
    manifest = data.get('evidence_manifest', {})
    if not isinstance(manifest, dict) or not manifest:
        manifest = build_evidence_manifest(data, analysis_kind=analysis_kind)

    if not isinstance(manifest, dict) or not manifest:
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 8, pdf.normalize_text('Manifesto pericial indisponível para esta análise.'))
        return

    pdf.set_font('Arial', 'B', 14)
    pdf.ln(2)
    pdf.cell(0, 10, 'Manifesto pericial e cadeia de custódia', 0, 1, 'L')
    pdf.set_font('Arial', '', 10)
    for key, value in manifest_summary_dict(manifest).items():
        pdf.add_key_value(key, value)
    custody = manifest.get('custody', {}) if isinstance(manifest.get('custody', {}), dict) else {}
    step_summary = str(custody.get('step_summary', '') or '').strip()
    if step_summary:
        pdf.multi_cell(0, 7, pdf.normalize_text(f'Etapas registradas: {step_summary}.'))
    pdf.ln(2)


def generate_investigation_report(data, output_path):
    pdf = InvestigationReport()
    pdf._scene_context = data if isinstance(data, dict) else {}
    pdf._ocr_record = _coerce_ocr_record(data)
    pdf.set_title('Relatório de Análise de Imagens')
    pdf.set_author('Grom_OCR')
    pdf.set_subject('Relatório técnico para correção em tela e impressão documental')
    pdf.alias_nb_pages()

    analysis_id = str(data.get('analysis_id', '') or '').strip()
    analysis_stage = str(data.get('analysis_stage', 'final') or 'final').strip().lower()
    cover_metadata = [
        'Estado operacional: %s' % ('Pré-análise' if analysis_stage == 'preview' else 'Consolidado'),
        'Gerado em: %s' % datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
    ]
    if analysis_id:
        cover_metadata.insert(0, 'Identificação da análise: %s' % analysis_id)
    origem = str(data.get('origem', '') or '').strip()
    if origem:
        cover_metadata.append('Origem: %s' % origem)

    draw_report_cover_header(
        pdf,
        'Relatório de Análise de Imagens',
        'Material técnico para conferência, correção em tela e impressão documental',
        cover_metadata,
    )

    # Report overview
    pdf.add_report_overview_section(data)
    write_evidence_manifest_section(pdf, data)

    # Section 0: EXIF/Metadata
    pdf.add_metadata_section(data.get('metadata'))

    # Section 1: Capture and Analysis
    pdf.add_captura_section(
        data.get('original_path'),
        data.get('crop_raw_path') or data.get('crop_path'),
        data.get('crop_treated_path') or data.get('crop_path'),
        metadata=data.get('metadata'),
    )

    # Section 2: Scene Diagnostics
    pdf.add_diagnostico_section(
        data.get('scenario_label', 'Indeterminado'),
        data.get('tech_details', 'Análise automática de histograma.')
    )

    # Section 3: Technology Foundation
    pdf.add_tecnologia_section(data.get('forensic_steps', []))

    # Section 4: Consensus Convention
    pdf.add_consenso_section(
        data.get('ocr_results', {}),
        data.get('suggested_vehicle', '-'),
        targets=data.get('targets'),
        consensus=data.get('consensus'),
        assessment=data.get('assessment'),
    )

    # Section 5: Chain of Custody
    pdf.add_forensic_chain_section(
        data.get('forensic_chain'),
        analysis_id=data.get('analysis_id'),
    )

    # Final Remarks
    pdf.add_consideracoes_section(data.get('summary', ''))

    pdf.output(output_path, 'F')
    return output_path
