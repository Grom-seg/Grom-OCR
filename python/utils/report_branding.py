import hashlib
import hashlib
import os
import tempfile
from functools import lru_cache

from PIL import Image


REPORT_LOGO_FILENAME = 'grom-report-logo.png'
REPORT_WATERMARK_OPACITY = 0.085
REPORT_PRIMARY_RGB = (9, 54, 95)
REPORT_SECONDARY_RGB = (70, 89, 114)
REPORT_ACCENT_RGB = (199, 144, 49)
REPORT_LINE_RGB = (215, 225, 236)
REPORT_PANEL_RGB = (241, 245, 249)
REPORT_TEXT_RGB = (20, 32, 51)
REPORT_MUTED_RGB = (90, 105, 122)


def _project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def resolve_report_logo_path():
    base_dir = _project_root()
    candidates = [
        os.path.join(base_dir, 'public', 'assets', REPORT_LOGO_FILENAME),
        os.path.join(base_dir, 'public', 'assets', 'grom-logo.png'),
        os.path.join(base_dir, 'public', 'assets', 'grom-mark.png'),
        r'C:\Users\Família Grom\OneDrive\Desktop\Josuel\Logo.png',
        r'C:\Users\Família Grom\Desktop\Josuel\Logo.png',
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return ''


def _build_cache_signature(source_path, opacity):
    stat = os.stat(source_path)
    return '|'.join([
        os.path.abspath(source_path),
        str(int(stat.st_mtime)),
        str(int(stat.st_size)),
        f'{float(opacity):.4f}',
    ])


@lru_cache(maxsize=8)
def _build_transparent_logo_path_cached(signature, source_path, opacity):
    del signature
    opacity = max(0.0, min(1.0, float(opacity)))
    if not source_path or not os.path.exists(source_path):
        return ''

    try:
        with Image.open(source_path) as source:
            image = source.convert('RGBA')
            alpha = image.getchannel('A')
            alpha = alpha.point(lambda value: int(round(value * opacity)))
            image.putalpha(alpha)

            digest = hashlib.sha1(_build_cache_signature(source_path, opacity).encode('utf-8')).hexdigest()[:16]
            output_path = os.path.join(tempfile.gettempdir(), f'grom_ocr_watermark_{digest}.png')
            if not os.path.exists(output_path):
                image.save(output_path)
            return output_path
    except Exception:
        return ''


def build_transparent_logo_path(source_path, opacity=REPORT_WATERMARK_OPACITY):
    if not source_path or not os.path.exists(source_path):
        return ''

    signature = _build_cache_signature(source_path, opacity)
    return _build_transparent_logo_path_cached(signature, source_path, opacity)


@lru_cache(maxsize=8)
def _get_image_dimensions_cached(signature, source_path):
    del signature
    if not source_path or not os.path.exists(source_path):
        return (0, 0)
    try:
        with Image.open(source_path) as source:
            return source.size
    except Exception:
        return (0, 0)


def get_image_dimensions(source_path):
    if not source_path or not os.path.exists(source_path):
        return (0, 0)

    stat = os.stat(source_path)
    signature = '|'.join([
        os.path.abspath(source_path),
        str(int(stat.st_mtime)),
        str(int(stat.st_size)),
    ])
    return _get_image_dimensions_cached(signature, source_path)


def _latin1_text(value):
    text = '' if value is None else str(value)
    return text.encode('latin-1', 'replace').decode('latin-1')


def draw_report_cover_header(pdf, title, subtitle=None, metadata=None):
    metadata = metadata if isinstance(metadata, (list, tuple)) else []
    metadata = [str(item).strip() for item in metadata if str(item).strip()]

    page_width = float(getattr(pdf, 'w', 210.0))
    left_margin = float(getattr(pdf, 'l_margin', 12.0))
    right_margin = float(getattr(pdf, 'r_margin', 12.0))
    usable_width = max(0.0, page_width - left_margin - right_margin)
    start_y = max(12.0, float(getattr(pdf, 'y', 0.0)))

    try:
        pdf.set_draw_color(*REPORT_LINE_RGB)
        pdf.set_line_width(0.35)
        pdf.line(left_margin, start_y - 0.5, page_width - right_margin, start_y - 0.5)
    except Exception:
        pass

    pdf.set_xy(left_margin, start_y + 1.5)
    pdf.set_text_color(*REPORT_SECONDARY_RGB)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.cell(0, 4, _latin1_text('GROM_OCR | DOCUMENTO TECNICO-PERICIAL'), 0, 1, 'L')

    pdf.set_text_color(*REPORT_PRIMARY_RGB)
    pdf.set_font('Times', 'B', 19)
    pdf.cell(0, 9, _latin1_text(title), 0, 1, 'C')

    if subtitle:
        pdf.set_text_color(*REPORT_MUTED_RGB)
        pdf.set_font('Helvetica', 'I', 9.5)
        pdf.cell(0, 5, _latin1_text(subtitle), 0, 1, 'C')

    if metadata:
        pdf.ln(1)
        pdf.set_text_color(*REPORT_MUTED_RGB)
        pdf.set_font('Helvetica', '', 8.25)
        for line in metadata[:4]:
            pdf.set_x(left_margin)
            pdf.multi_cell(usable_width, 4.5, _latin1_text(f'- {line}'))

    pdf.ln(1)
    try:
        pdf.set_draw_color(*REPORT_ACCENT_RGB)
        pdf.set_line_width(0.82)
        pdf.line(left_margin, float(getattr(pdf, 'y', 0.0)), page_width - right_margin, float(getattr(pdf, 'y', 0.0)))
    except Exception:
        pass
    pdf.ln(2)
    pdf.set_text_color(*REPORT_TEXT_RGB)


def apply_formal_report_palette(pdf):
    pdf.set_text_color(*REPORT_TEXT_RGB)
    pdf.set_draw_color(*REPORT_LINE_RGB)
    pdf.set_fill_color(*REPORT_PANEL_RGB)
    pdf.set_line_width(0.2)


def draw_report_watermark(pdf, logo_path=None, width=84.0, opacity=REPORT_WATERMARK_OPACITY, y_shift=-6.0):
    logo_path = logo_path or resolve_report_logo_path()
    if not logo_path:
        return

    watermark_path = build_transparent_logo_path(logo_path, opacity=opacity)
    if not watermark_path:
        return

    logo_width, logo_height = get_image_dimensions(logo_path)
    if logo_width <= 0 or logo_height <= 0:
        return

    watermark_width = float(width)
    watermark_height = watermark_width * (float(logo_height) / float(logo_width))
    x = max(0.0, (float(getattr(pdf, 'w', 210.0)) - watermark_width) / 2.0)
    y = max(0.0, (float(getattr(pdf, 'h', 297.0)) - watermark_height) / 2.0 + float(y_shift))
    try:
        pdf.image(watermark_path, x=x, y=y, w=watermark_width)
    except Exception:
        pass


def draw_report_footer(pdf, logo_path=None, brand='GROM_OCR', website='www.grom.seg.br', date_text=None):
    logo_path = logo_path or resolve_report_logo_path()
    footer_top = float(getattr(pdf, 'h', 297.0)) - 20.0
    page_width = float(getattr(pdf, 'w', 210.0))
    row1_y = footer_top + 1.0
    row2_y = footer_top + 6.0

    try:
        pdf.set_draw_color(*REPORT_LINE_RGB)
        pdf.set_line_width(0.35)
        pdf.line(10.0, footer_top - 1.0, page_width - 10.0, footer_top - 1.0)
    except Exception:
        pass

    if logo_path:
        try:
            pdf.image(logo_path, x=10.0, y=footer_top + 0.65, w=12.0)
        except Exception:
            pass

    if not date_text:
        from datetime import datetime

        date_text = datetime.now().strftime('%d/%m/%Y')

    pdf.set_font('Times', 'B', 10.5)
    pdf.set_text_color(*REPORT_PRIMARY_RGB)
    pdf.set_xy(0, row1_y)
    pdf.cell(0, 5, _latin1_text(brand), 0, 1, 'C')

    pdf.set_font('Helvetica', '', 7.6)
    pdf.set_text_color(*REPORT_MUTED_RGB)
    pdf.set_xy(0, row2_y)
    pdf.cell(0, 4, _latin1_text(website), 0, 0, 'C')

    pdf.set_font('Helvetica', '', 8.1)
    pdf.set_text_color(*REPORT_TEXT_RGB)
    pdf.set_xy(page_width - 44.0, row1_y)
    pdf.cell(34.0, 4, _latin1_text(date_text), 0, 1, 'R')
    pdf.set_xy(page_width - 44.0, row2_y)
    pdf.cell(34.0, 4, f'{pdf.page_no()}/{{nb}}', 0, 0, 'R')


def draw_report_section_header(pdf, title, level='section'):
    level = str(level or 'section').lower()
    if level in ('subsection', 'sub', 'minor'):
        pdf.set_fill_color(245, 248, 252)
        pdf.set_draw_color(*REPORT_LINE_RGB)
        pdf.set_text_color(*REPORT_PRIMARY_RGB)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 8, _latin1_text(title), 1, 1, 'L', True)
        pdf.ln(1)
    else:
        pdf.set_fill_color(*REPORT_PRIMARY_RGB)
        pdf.set_draw_color(*REPORT_PRIMARY_RGB)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 9, _latin1_text(title), 0, 1, 'L', True)
        pdf.set_text_color(*REPORT_TEXT_RGB)
        pdf.ln(2)
