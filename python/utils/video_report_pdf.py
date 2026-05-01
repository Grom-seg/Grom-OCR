from __future__ import annotations

import os
from datetime import datetime

from fpdf import FPDF

from utils.pericial_labels import format_report_label, format_report_value, humanize_pericial_label
from utils.report_branding import (
    apply_formal_report_palette,
    draw_report_cover_header,
    draw_report_footer,
    draw_report_section_header,
    draw_report_watermark,
    get_image_dimensions,
    resolve_report_logo_path,
)
from utils.report_visuals import build_capture_comparison_sheet
from utils.evidence_manifest import build_evidence_manifest, manifest_summary_dict
from utils.video_analysis import build_video_contact_sheet
from utils.video_report_outline import get_video_analysis_report_outline
from utils.video_session import normalize_video_target_entry


VIDEO_ANALYSIS_REPORT_OUTLINE = get_video_analysis_report_outline()


def _safe_float(value, fallback=0.0):
    try:
        if value is None or value == '':
            return float(fallback)
        return float(value)
    except Exception:
        return float(fallback)


def _safe_int(value, fallback=0):
    try:
        if value is None or value == '':
            return int(fallback)
        return int(float(value))
    except Exception:
        return int(fallback)


def _safe_text(value, fallback=''):
    text = str(value if value is not None else '').strip()
    return text or str(fallback)


def _safe_list(value):
    return value if isinstance(value, list) else []


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _normalize_text(value):
    return str(value if value is not None else '').encode('latin-1', 'replace').decode('latin-1')


def _format_timecode(seconds):
    try:
        seconds = float(seconds or 0.0)
    except Exception:
        seconds = 0.0
    if seconds < 0:
        return 'Indefinido'
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f'{hours:02d}:{minutes:02d}:{secs:02d}'
    return f'{minutes:02d}:{secs:02d}'


def _normalize_target_list(value):
    entries = []
    for item in _safe_list(value):
        if not isinstance(item, dict):
            continue
        entries.append(normalize_video_target_entry(item))
    return entries


def _target_frame_entry(target):
    target = normalize_video_target_entry(target)
    frame_entry = dict(target.get('best_frame', {})) if isinstance(target.get('best_frame'), dict) else {}
    if not frame_entry:
        frame_entry = {}
    frame_entry.setdefault('frame_path', target.get('frame_path', ''))
    frame_entry.setdefault('frame_url', target.get('frame_url', ''))
    frame_entry.setdefault('crop_raw_path', target.get('crop_raw_path', ''))
    frame_entry.setdefault('crop_raw_url', target.get('crop_raw_url', ''))
    frame_entry.setdefault('crop_treated_path', target.get('crop_treated_path', ''))
    frame_entry.setdefault('crop_treated_url', target.get('crop_treated_url', ''))
    frame_entry.setdefault('ocr', target.get('text', frame_entry.get('ocr', '')))
    frame_entry.setdefault('confidence', target.get('best_confidence', target.get('avg_confidence', 0.0)))
    frame_entry.setdefault('score', target.get('best_score', target.get('avg_score', 0.0)))
    frame_entry.setdefault('pattern', target.get('pattern', 'Indefinido'))
    frame_entry.setdefault('timestamp_seconds', target.get('timestamp_seconds', 0.0))
    frame_entry.setdefault('frame_index', target.get('frame_index', 0))
    frame_entry.setdefault('frame_order', target.get('frame_order', 0))
    frame_entry.setdefault('frame_quality', target.get('quality_metrics', {}))
    return frame_entry


class VideoInvestigationReport(FPDF):
    def __init__(self):
        super().__init__()
        self.alias_nb_pages()
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
        draw_report_footer(self, logo_path=resolve_report_logo_path(), date_text=datetime.now().strftime('%d/%m/%Y'))

    def normalize_text(self, text):
        return _normalize_text(text)

    def add_key_value(self, key, value):
        self.set_font('Arial', 'B', 9)
        self.cell(62, 7, self.normalize_text(f'{format_report_label(key)}:'), 0, 0)
        self.set_font('Arial', '', 9)
        self.cell(0, 7, self.normalize_text(format_report_value(value) if value not in (None, '') else 'N/A'), 0, 1)


def write_video_outline(pdf, outline=None):
    outline = _safe_list(outline) or VIDEO_ANALYSIS_REPORT_OUTLINE
    if not outline:
        pdf.multi_cell(0, 8, pdf.normalize_text('Procedimentos informados indisponíveis.'))
        return

    pdf.set_font('Arial', 'B', 10)
    pdf.multi_cell(0, 7, pdf.normalize_text('Procedimentos efetuados na análise de vídeo:'))
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


def write_frame_summary(pdf, frame_results):
    entries = [entry for entry in _safe_list(frame_results) if isinstance(entry, dict)]
    if not entries:
        pdf.multi_cell(0, 8, pdf.normalize_text('Nenhum quadro de vídeo foi selecionado.'))
        return

    pdf.set_font('Arial', 'B', 10)
    pdf.multi_cell(0, 7, pdf.normalize_text('Quadros-chave e leituras principais:'))
    pdf.set_font('Arial', '', 9)

    for entry in entries[:6]:
        frame_label = f"Quadro {int(entry.get('frame_order', 0) or 0):02d}"
        timestamp = _safe_float(entry.get('timestamp_seconds', 0.0), 0.0)
        ocr_text = str(entry.get('ocr', '') or '-')
        confidence = _safe_float(entry.get('confidence', 0.0), 0.0)
        score = _safe_float(entry.get('score', 0.0), 0.0)
        pattern = str(entry.get('pattern', 'Indefinido') or 'Indefinido')
        quality = _safe_dict(entry.get('frame_quality'))
        sharpness = _safe_float(quality.get('sharpness', 0.0), 0.0)
        pdf.multi_cell(
            0,
            5,
            pdf.normalize_text(
                f'{frame_label} | {timestamp:0.2f}s | OCR {ocr_text} | '
                f'Confiança {confidence:0.1f}% | Score {score:0.1f} | Padrão {pattern} | Nitidez {sharpness:0.1f}'
            ),
        )


def write_partial_candidates_block(pdf, partial_candidates):
    entries = [entry for entry in _safe_list(partial_candidates) if isinstance(entry, dict)]
    if not entries:
        return

    pdf.add_page()
    draw_report_section_header(pdf, 'Fragmentos parciais preservados para confronto', level='section')
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(
        0,
        7,
        pdf.normalize_text(
            'Os fragmentos abaixo não são tratados como placa final. Eles ficam preservados como '
            'evidência de confronto, especialmente quando apenas 1 ou 2 caracteres ficaram legíveis.'
        ),
    )
    pdf.ln(1)

    for entry in entries[:8]:
        text = str(entry.get('text', '') or entry.get('normalized_text', '') or '-').strip()
        fragment_kind = str(entry.get('fragment_kind', 'fragmento_parcial') or 'fragmento_parcial').strip()
        minute_range = str(entry.get('minute_range', 'Indefinido') or 'Indefinido').strip()
        frame_index = _safe_int(entry.get('frame_index', 0), 0)
        frame_order = _safe_int(entry.get('frame_order', 0), 0)
        timestamp_seconds = _safe_float(entry.get('timestamp_seconds', -1.0), -1.0)
        support_label = str(entry.get('support_label', '') or '').strip()
        slot_hint = str(entry.get('slot_hint', '') or '').strip()
        confidence = _safe_float(entry.get('best_confidence', entry.get('avg_confidence', 0.0)), 0.0)
        score = _safe_float(entry.get('best_score', entry.get('avg_score', 0.0)), 0.0)
        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 5, pdf.normalize_text(f'{text} | {fragment_kind}'))
        pdf.set_font('Arial', '', 9)
        details = [
            f'Minuto {minute_range}',
            f'Quadro #{frame_order:02d}' if frame_order > 0 else f'Quadro {frame_index}',
            f'Tempo {_format_timecode(timestamp_seconds)}' if timestamp_seconds >= 0 else 'Tempo indefinido',
            f'Confiança {confidence:0.1f}%',
            f'Score {score:0.1f}',
        ]
        if support_label:
            details.append(support_label)
        if slot_hint:
            details.append(f'Slot {slot_hint}')
        pdf.multi_cell(0, 5, pdf.normalize_text(' | '.join(details)))
        pdf.ln(1)


def write_selected_targets_block(pdf, selected_targets):
    entries = _normalize_target_list(selected_targets)
    if not entries:
        return

    pdf.add_page()
    draw_report_section_header(pdf, 'Alvos consolidados pelo operador', level='section')
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(
        0,
        6,
        pdf.normalize_text(
            'Os alvos abaixo foram marcados pelo operador na etapa de revisão e são os '
            'elementos consolidados no PDF final. A sequência preserva a ordem de seleção.'
        ),
    )
    pdf.ln(1)

    for index, target in enumerate(entries, start=1):
        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 6, pdf.normalize_text(f'{index}. {target.get("display_label", "Indisponível")}'))
        pdf.set_font('Arial', '', 9)
        pdf.multi_cell(
            0,
            5,
            pdf.normalize_text(
                f'    ID {target.get("candidate_id", "-")} | '
                f'{int(target.get("frames_count", 0) or 0)} quadros | '
                f'Confiança média {float(target.get("avg_confidence", 0.0) or 0.0):0.1f}% | '
                f'Score médio {float(target.get("avg_score", 0.0) or 0.0):0.1f} | '
                f'Padrão {target.get("pattern", "Indefinido")} | '
                f'Minuto {target.get("minute_range", "Indefinido")} | '
                f'Rank {float(target.get("support_rank", target.get("frames_count", 0)) or 0.0):0.2f} | '
                f'Estilo {float(target.get("style_rank_priority", 0.0) or 0.0):0.2f}'
            ),
        )


def write_metadata_block(pdf, data):
    video_metadata = _safe_dict(data.get('video_metadata'))
    frame_sampling = _safe_dict(data.get('frame_sampling'))
    best_frame = _safe_dict(data.get('best_frame'))
    best_result = _safe_dict(data.get('best_result'))
    consensus = _safe_dict(data.get('consensus'))
    capture_integrity = _safe_dict(data.get('capture_integrity'))
    human_review = _safe_dict(data.get('human_review'))
    selected_targets = _normalize_target_list(data.get('selected_targets'))
    selected_candidate_ids = [
        str(item).strip()
        for item in _safe_list(data.get('selected_candidate_ids'))
        if str(item).strip()
    ]
    video_candidates_preview = _safe_list(data.get('video_candidates_preview'))
    video_candidates_count = int(data.get('video_candidates_count', len(video_candidates_preview)) or len(video_candidates_preview))
    video_partial_candidates_preview = _safe_list(data.get('video_partial_candidates_preview'))
    video_partial_candidates_count = int(
        data.get('video_partial_candidates_count', len(video_partial_candidates_preview)) or len(video_partial_candidates_preview)
    )
    primary_partial_candidate = _safe_dict(video_partial_candidates_preview[0] if video_partial_candidates_preview else {})
    partial_text = _safe_text(primary_partial_candidate.get('text', '') or primary_partial_candidate.get('normalized_text', ''), '-')
    partial_minute = _safe_text(primary_partial_candidate.get('minute_range', ''), 'Indefinido')
    primary_target = selected_targets[0] if selected_targets else normalize_video_target_entry(best_frame)

    if not video_metadata:
        pdf.multi_cell(0, 8, pdf.normalize_text('Metadados do vídeo indisponíveis.'))
        return

    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, pdf.normalize_text('Resumo técnico-documental'), 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(
        0,
        7,
        pdf.normalize_text(
            'Fluxo pericial: vídeo-fonte preservado, varredura frame a frame, alvos '
            'candidatos agrupados por minuto, quadro de maior valor probatório tratado, '
            'OCR em consenso e conferência humana antes da liberação documental.'
        ),
    )
    pdf.ln(2)

    source_name = os.path.basename(str(video_metadata.get('video_path', '') or '')) or 'Indisponível'
    source_resolution = f"{int(video_metadata.get('width', 0) or 0)}x{int(video_metadata.get('height', 0) or 0)} px"
    duration = _safe_float(video_metadata.get('duration_seconds', 0.0), 0.0)
    fps = _safe_float(video_metadata.get('fps', 0.0), 0.0)
    frame_count = int(video_metadata.get('frame_count', 0) or 0)
    sample_count = len(_safe_list(frame_sampling.get('selected_frames')))
    selected_frame_count = int(frame_sampling.get('selected_frame_count', sample_count) or sample_count)
    duration_seconds = _safe_float(frame_sampling.get('duration_seconds', video_metadata.get('duration_seconds', 0.0)), 0.0)
    scan_interval_seconds = _safe_float(frame_sampling.get('scan_interval_seconds', 0.0), 0.0)
    coverage_label = str(frame_sampling.get('coverage_label', '') or '').strip() or 'Indefinido'
    frame_timestamp = _safe_float(primary_target.get('timestamp_seconds', best_frame.get('timestamp_seconds', 0.0)), 0.0)
    frame_index = int(primary_target.get('frame_index', best_frame.get('frame_index', 0)) or 0)
    best_text = str(
        primary_target.get('text')
        or best_result.get('text', best_frame.get('ocr', ''))
        or best_frame.get('ocr', '')
        or ''
    ).strip() or 'Indefinido'
    best_pattern = str(
        primary_target.get('pattern')
        or best_result.get('pattern', best_frame.get('pattern', 'Indefinido'))
        or best_frame.get('pattern', 'Indefinido')
    )
    consensus_ratio = _safe_float(consensus.get('agreement_ratio', 0.0), 0.0)
    consensus_count = int(consensus.get('agreement_count', consensus.get('consensus_count', 0)) or 0)
    engines_considered = int(consensus.get('engines_considered', consensus.get('total_engines', 0)) or 0)
    capture_status = humanize_pericial_label(capture_integrity.get('status', 'indefinido'))
    capture_score = _safe_float(capture_integrity.get('integrity_score', 0.0), 0.0)
    review_status = humanize_pericial_label(human_review.get('decision_label', human_review.get('decision', 'Pendente')))
    analysis_stage = str(data.get('analysis_stage', 'final') or 'final').strip().lower()
    report_state = 'Aguardando correção em tela' if analysis_stage == 'preview' else 'Disponível para impressão documental'
    selected_targets_count = len(selected_targets)
    candidate_pool_count = video_candidates_count
    best_text_normalized = str(best_text or '').strip().upper()
    has_meaningful_target = (
        selected_targets_count > 0
        and best_text_normalized not in ('', 'INDEFINIDO', 'SEM_TEXTO', 'SEM LEITURA CONFIÁVEL')
    )
    selected_ids_label = f'{selected_targets_count} alvo(s) | ordem preservada' if has_meaningful_target else 'Nenhum alvo consolidado'
    primary_target_label = str(primary_target.get('display_label', '') or '').strip() if has_meaningful_target else 'Nenhum alvo consolidado'
    if not primary_target_label:
        primary_target_label = 'Nenhum alvo consolidado'
    scan_strategy = str(frame_sampling.get('strategy', 'frame_by_frame_scan') or 'frame_by_frame_scan')
    primary_support_rank = _safe_float(primary_target.get('support_rank', primary_target.get('frames_count', 0)), 0.0) if has_meaningful_target else 0.0
    primary_style_rank = _safe_float(primary_target.get('style_rank_priority', 0.0), 0.0) if has_meaningful_target else 0.0
    primary_minute = str(primary_target.get('minute_range', '') or '').strip() if has_meaningful_target else 'Indisponível'
    if not primary_minute:
        primary_minute = 'Indisponível'
    if not has_meaningful_target:
        best_text = 'Nenhuma leitura confiável'
        best_pattern = 'Indefinido'
    partial_fragment_label = 'Nenhum fragmento'
    if video_partial_candidates_count:
        partial_fragment_label = f'{partial_text} | {partial_minute} | {video_partial_candidates_count} observação(ões)'

    key_values = {
        'Status do relatório': report_state,
        'Identificação da análise': data.get('analysis_id', '-'),
        'Fonte documental': source_name,
        'Resolução do vídeo': source_resolution,
        'Duração': f'{duration_seconds:0.2f}s' if duration_seconds else f'{duration:0.2f}s',
        'Cobertura temporal': coverage_label,
        'Intervalo de varredura': f'{scan_interval_seconds:0.2f}s' if scan_interval_seconds else 'Indefinido',
        'Estratégia de varredura': scan_strategy,
        'Taxa de quadros': f'{fps:0.2f} fps',
        'Quadros no vídeo': frame_count,
        'Quadros varridos': selected_frame_count,
        'Quadros avaliados': len(_safe_list(data.get('frame_results'))),
        'Candidatos apresentados': candidate_pool_count,
        'Fragmentos parciais': partial_fragment_label,
        'Alvos selecionados': selected_targets_count,
        'Seleção do operador': selected_ids_label,
        'Alvo principal': primary_target_label,
        'Faixa temporal do alvo': primary_minute,
        'Rank de suporte do alvo': f'{primary_support_rank:0.2f}',
        'Crédito de estilo': f'{primary_style_rank:0.2f}',
        'Placa principal': best_text,
        'Padrão visual': best_pattern,
        'Quadro selecionado': f'#{frame_index} @ {frame_timestamp:0.2f}s',
        'Integridade da captura': f'{capture_status} ({capture_score:0.1f}/100)',
        'Consenso temporal': f'{consensus_ratio:0.1f}% ({consensus_count}/{engines_considered} quadros)',
        'Revisão humana': review_status,
        'Hash SHA-256 do vídeo': video_metadata.get('sha256', '-'),
        'Codec percebido': video_metadata.get('codec_fourcc', video_metadata.get('codec_hint', '-')),
    }

    for key, value in key_values.items():
        pdf.add_key_value(key, value)


def _maybe_add_image(pdf, image_path, title, available_width=None):
    if not image_path or not os.path.exists(image_path):
        return False

    width, height = get_image_dimensions(image_path)
    if width <= 0 or height <= 0:
        return False

    pdf.add_page()
    draw_report_section_header(pdf, title, level='section')
    pdf.ln(2)
    page_width = available_width or (pdf.w - pdf.l_margin - pdf.r_margin)
    max_height = 170
    if width > 0 and height > 0:
        ratio = min(page_width / float(width), max_height / float(height))
    else:
        ratio = 1.0
    draw_width = max(1, int(width * ratio))
    draw_height = max(1, int(height * ratio))
    x = pdf.l_margin + max(0, (page_width - draw_width) / 2.0)
    pdf.image(image_path, x=x, w=draw_width, h=draw_height)
    pdf.ln(draw_height + 4)
    return True


def write_evidence_manifest_block(pdf, data):
    data = data if isinstance(data, dict) else {}
    manifest = _safe_dict(data.get('evidence_manifest'))
    if manifest and (not manifest.get('analysis_kind') or not manifest.get('source') or not manifest.get('selection')):
        manifest = {}
    if not manifest:
        manifest = build_evidence_manifest(data, analysis_kind='video')

    if not manifest:
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 8, pdf.normalize_text('Manifesto pericial indisponível para esta análise.'))
        return

    pdf.add_page()
    draw_report_section_header(pdf, 'Manifesto pericial e cadeia de custódia', level='section')
    pdf.set_font('Arial', '', 10)
    for key, value in manifest_summary_dict(manifest).items():
        pdf.add_key_value(key, value)
    custody = _safe_dict(manifest.get('custody'))
    step_summary = str(custody.get('step_summary', '') or '').strip()
    if step_summary:
        pdf.multi_cell(0, 7, pdf.normalize_text(f'Etapas registradas: {step_summary}.'))
    pdf.ln(1)


def generate_video_investigation_report(data, output_path):
    data = data if isinstance(data, dict) else {}
    video_metadata = _safe_dict(data.get('video_metadata'))
    frame_results = _safe_list(data.get('frame_results'))
    best_frame = _safe_dict(data.get('best_frame'))
    best_result = _safe_dict(data.get('best_result'))
    consensus = _safe_dict(data.get('consensus'))
    assessment = _safe_dict(data.get('assessment'))
    pericial = _safe_dict(data.get('pericial'))
    human_review = _safe_dict(data.get('human_review'))
    capture_integrity = _safe_dict(data.get('capture_integrity'))
    frame_sampling = _safe_dict(data.get('frame_sampling'))
    selected_targets = _normalize_target_list(data.get('selected_targets'))
    best_text_candidate = str(
        best_result.get('text')
        or best_frame.get('ocr', '')
        or best_frame.get('text', '')
        or ''
    ).strip().upper()
    has_meaningful_best = best_text_candidate not in ('', 'INDEFINIDO', 'SEM_TEXTO', 'SEM LEITURA CONFIÁVEL')
    if not selected_targets and best_frame and has_meaningful_best:
        selected_targets = [normalize_video_target_entry(best_frame)]
    analysis_report_outline = _safe_list(data.get('analysis_report_outline')) or VIDEO_ANALYSIS_REPORT_OUTLINE

    pdf = VideoInvestigationReport()

    draw_report_cover_header(
        pdf,
        title='Relatório de apoio à investigação - vídeo',
        subtitle='Varredura temporal, tratamento pericial e OCR frame a frame',
        metadata=[
            'Fluxo independente para análise de vídeo',
            'Quadros varridos, comparados e consolidados antes da impressão documental',
        ],
    )

    write_metadata_block(pdf, {
        'video_metadata': video_metadata,
        'frame_sampling': frame_sampling,
        'best_frame': best_frame,
        'best_result': best_result or _safe_dict(data.get('best_payload')),
        'consensus': consensus,
        'capture_integrity': capture_integrity,
        'human_review': human_review,
        'analysis_stage': data.get('analysis_stage', 'final'),
        'analysis_id': data.get('analysis_id', '-'),
        'frame_results': frame_results,
        'selected_targets': selected_targets,
        'selected_candidate_ids': _safe_list(data.get('selected_candidate_ids')),
        'video_candidates_preview': _safe_list(data.get('video_candidates_preview')),
        'video_partial_candidates_preview': _safe_list(data.get('video_partial_candidates_preview')),
        'video_partial_candidates_count': int(data.get('video_partial_candidates_count', len(_safe_list(data.get('video_partial_candidates_preview')))) or len(_safe_list(data.get('video_partial_candidates_preview')))),
    })

    write_partial_candidates_block(pdf, data.get('video_partial_candidates_preview'))
    write_evidence_manifest_block(pdf, data)

    selected_targets_sheet_path = ''
    if selected_targets:
        selected_frame_entries = [_target_frame_entry(target) for target in selected_targets]
        selected_targets_sheet_path = build_video_contact_sheet(
            selected_frame_entries,
            title='Alvos selecionados pelo operador',
            subtitle='Candidatos consolidados para a impressão documental',
        )

    contact_sheet_path = str(data.get('contact_sheet_path', '') or '').strip()
    comparison_sheet_path = str(data.get('comparison_sheet_path', '') or '').strip()

    write_selected_targets_block(pdf, selected_targets)

    if selected_targets_sheet_path:
        _maybe_add_image(pdf, selected_targets_sheet_path, 'Alvos selecionados pelo operador')

    for index, target in enumerate(selected_targets, start=1):
        target_frame = _target_frame_entry(target)
        target_frame_path = str(target_frame.get('frame_path', '') or '').strip()
        target_raw_path = str(target_frame.get('crop_raw_path', '') or '').strip()
        target_treated_path = str(target_frame.get('crop_treated_path', '') or '').strip()
        comparison = build_capture_comparison_sheet(
            target_frame_path or target.get('frame_path', ''),
            target_raw_path or target.get('crop_raw_path', ''),
            target_treated_path or target.get('crop_treated_path', ''),
        )
        if comparison:
            target_title = (
                f'Alvo consolidado {index}: '
                f'{target.get("display_label", target_frame.get("ocr", "Indisponível"))}'
            )
            _maybe_add_image(pdf, comparison, target_title)

    if contact_sheet_path:
        _maybe_add_image(pdf, contact_sheet_path, 'Quadros selecionados do vídeo')
    if comparison_sheet_path:
        _maybe_add_image(pdf, comparison_sheet_path, 'Comparação documental do quadro selecionado')

    pdf.add_page()
    draw_report_section_header(pdf, 'Distribuição temporal e leitura documental', level='section')
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(
        0,
        6,
        pdf.normalize_text(
            'Os quadros abaixo resumem a sequência processada, destacando o momento em que '
            'o sistema encontrou maior nitidez, maior estabilidade visual e melhor leitura OCR.'
        ),
    )
    pdf.ln(2)
    write_frame_summary(pdf, frame_results)

    pdf.add_page()
    write_video_outline(pdf, analysis_report_outline)

    pdf.add_page()
    draw_report_section_header(pdf, 'Conclusão técnica', level='section')
    pdf.set_font('Arial', '', 10)
    conclusion_summary = str(
        (pericial.get('summary', '') or data.get('summary', '') or data.get('conclusion', '') or '')
    ).strip()
    if not conclusion_summary:
        conclusion_summary = (
            'O vídeo foi varrido em quadros-chave, os melhores trechos foram tratados pelo '
            'motor OCR consolidado e o resultado final permaneceu condicionado à conferência '
            'humana antes de qualquer uso documental.'
        )
    pdf.multi_cell(0, 7, pdf.normalize_text(conclusion_summary))
    pdf.ln(2)

    pdf.set_font('Arial', 'B', 10)
    pdf.multi_cell(0, 6, pdf.normalize_text('Notas finais'))
    pdf.set_font('Arial', '', 9)
    pdf.multi_cell(
        0,
        5,
        pdf.normalize_text(
            'A peça foi gerada como relatório de apoio à investigação. O conjunto visual '
            'prioriza rastreabilidade, integridade da fonte, comparação entre quadros e '
            'conferência humana antes da impressão.'
        ),
    )

    pdf.output(output_path)
    return output_path
