from __future__ import annotations

import hashlib
import os
import tempfile
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps

from utils.report_branding import get_image_dimensions


def _safe_text(value, fallback='-'):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _build_signature(*paths):
    parts = []
    for path in paths:
        if path and os.path.exists(path):
            stat = os.stat(path)
            parts.extend([
                os.path.abspath(path),
                str(int(stat.st_mtime_ns)),
                str(int(stat.st_size)),
            ])
        else:
            parts.extend(['', '0', '0'])
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:20]


def _load_image(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as source:
            return source.convert('RGB').copy()
    except Exception:
        return None


def _font_candidates(bold=False, size=28):
    windows_fonts = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    if bold:
        candidates = [
            os.path.join(windows_fonts, 'arialbd.ttf'),
            os.path.join(windows_fonts, 'calibrib.ttf'),
            os.path.join(windows_fonts, 'timesbd.ttf'),
            os.path.join(windows_fonts, 'verdanab.ttf'),
        ]
    else:
        candidates = [
            os.path.join(windows_fonts, 'arial.ttf'),
            os.path.join(windows_fonts, 'calibri.ttf'),
            os.path.join(windows_fonts, 'times.ttf'),
            os.path.join(windows_fonts, 'verdana.ttf'),
        ]
    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_panel(base, box, title, subtitle, image_path, accent=(9, 54, 95), muted=(91, 104, 122)):
    draw = ImageDraw.Draw(base)
    x0, y0, x1, y1 = box
    radius = 28
    draw.rounded_rectangle(box, radius=radius, fill=(249, 252, 255), outline=(214, 225, 237), width=3)
    draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius=radius - 2, outline=(255, 255, 255), width=1)

    header_h = 104
    header_box = (x0 + 18, y0 + 16, x1 - 18, y0 + header_h)
    draw.rounded_rectangle(header_box, radius=20, fill=(238, 244, 250), outline=(220, 229, 238), width=1)

    title_font = _font_candidates(bold=True, size=26)
    subtitle_font = _font_candidates(bold=False, size=18)
    draw.text((x0 + 36, y0 + 34), _safe_text(title), font=title_font, fill=accent)
    draw.text((x0 + 36, y0 + 70), _safe_text(subtitle), font=subtitle_font, fill=muted)

    image_area = (x0 + 28, y0 + header_h + 22, x1 - 28, y1 - 28)
    panel_img = _load_image(image_path)
    if panel_img is None:
        placeholder_font = _font_candidates(bold=True, size=24)
        draw.rounded_rectangle(image_area, radius=18, fill=(240, 244, 249), outline=(221, 229, 237), width=2)
        draw.text(
            (image_area[0] + 22, image_area[1] + 22),
            'Imagem indisponível',
            font=placeholder_font,
            fill=muted,
        )
        return

    target_w = max(1, image_area[2] - image_area[0])
    target_h = max(1, image_area[3] - image_area[1])
    fitted = ImageOps.contain(panel_img, (target_w, target_h))

    bg = Image.new('RGB', (target_w, target_h), (255, 255, 255))
    offset_x = (target_w - fitted.width) // 2
    offset_y = (target_h - fitted.height) // 2
    bg.paste(fitted, (offset_x, offset_y))
    base.paste(bg, (image_area[0], image_area[1]))
    draw.rounded_rectangle(image_area, radius=18, outline=(214, 225, 237), width=2)


@lru_cache(maxsize=16)
def _build_capture_comparison_sheet_cached(signature, original_path, raw_crop_path, treated_crop_path):
    del signature

    canvas_w = 2400
    canvas_h = 1440
    base = Image.new('RGB', (canvas_w, canvas_h), (252, 253, 255))
    draw = ImageDraw.Draw(base)

    primary = (9, 54, 95)
    accent = (199, 144, 49)
    muted = (90, 105, 122)
    line = (215, 225, 236)

    draw.rounded_rectangle((48, 44, canvas_w - 48, canvas_h - 44), radius=34, fill=(255, 255, 255), outline=line, width=3)
    draw.line((78, 128, canvas_w - 78, 128), fill=accent, width=6)
    draw.line((78, 138, canvas_w - 78, 138), fill=(233, 237, 242), width=1)

    title_font = _font_candidates(bold=True, size=42)
    subtitle_font = _font_candidates(bold=False, size=21)
    meta_font = _font_candidates(bold=False, size=16)
    small_font = _font_candidates(bold=False, size=16)

    draw.text((82, 58), 'Identificação da captura e recortes comparativos', font=title_font, fill=primary)
    draw.text(
        (84, 108),
        'Imagem original, recorte bruto da placa e recorte tratado para comparação documental.',
        font=subtitle_font,
        fill=muted,
    )

    left_x = 78
    top_y = 180
    left_w = 1392
    right_x = left_x + left_w + 28
    right_w = canvas_w - right_x - 78
    panel_h = 1030
    right_h = (panel_h - 24) // 2

    original_dims = get_image_dimensions(original_path)
    raw_dims = get_image_dimensions(raw_crop_path)
    treated_dims = get_image_dimensions(treated_crop_path)

    _draw_panel(
        base,
        (left_x, top_y, left_x + left_w, top_y + panel_h),
        'Imagem original',
        f'Fonte documental | {original_dims[0]} x {original_dims[1]} px' if original_dims != (0, 0) else 'Fonte documental',
        original_path,
        accent=primary,
        muted=muted,
    )
    _draw_panel(
        base,
        (right_x, top_y, right_x + right_w, top_y + right_h),
        'Recorte bruto da placa',
        f'Recorte inicial | {raw_dims[0]} x {raw_dims[1]} px' if raw_dims != (0, 0) else 'Recorte inicial',
        raw_crop_path or original_path,
        accent=accent,
        muted=muted,
    )
    _draw_panel(
        base,
        (right_x, top_y + right_h + 24, right_x + right_w, top_y + panel_h),
        'Recorte tratado da placa',
        f'Recorte refinado | {treated_dims[0]} x {treated_dims[1]} px' if treated_dims != (0, 0) else 'Recorte refinado',
        treated_crop_path or raw_crop_path or original_path,
        accent=primary,
        muted=muted,
    )

    footer_top = top_y + panel_h + 36
    draw.rounded_rectangle((78, footer_top, canvas_w - 78, footer_top + 182), radius=24, fill=(245, 248, 252), outline=line, width=2)
    draw.text((102, footer_top + 18), 'Observações de validação', font=title_font if title_font.size <= 26 else _font_candidates(bold=True, size=26), fill=primary)

    lines = [
        f'Fonte original: {_safe_text(os.path.basename(original_path), "indisponível")}',
        f'Recorte bruto: {_safe_text(os.path.basename(raw_crop_path), "indisponível")}',
        f'Recorte tratado: {_safe_text(os.path.basename(treated_crop_path), "indisponível")}',
    ]
    y = footer_top + 72
    for line_text in lines:
        draw.text((102, y), f'• {line_text}', font=meta_font, fill=muted)
        y += 34

    note_font = small_font if hasattr(small_font, 'size') else _font_candidates(size=16)
    draw.text(
        (1180, footer_top + 74),
        'Ferramentas documentadas:\n'
        'preservação da fonte, recorte bruto, recorte tratado e validação visual.\n'
        'A composição privilegia rastreabilidade e conferência pericial.',
        font=note_font,
        fill=primary,
        spacing=8,
    )

    digest = _build_signature(original_path, raw_crop_path, treated_crop_path)
    output_path = os.path.join(tempfile.gettempdir(), f'grom_ocr_capture_sheet_{digest}.png')
    base.save(output_path)
    return output_path


def build_capture_comparison_sheet(original_path, raw_crop_path=None, treated_crop_path=None):
    if not original_path or not os.path.exists(original_path):
        return ''
    signature = _build_signature(original_path, raw_crop_path, treated_crop_path)
    return _build_capture_comparison_sheet_cached(signature, original_path, raw_crop_path or '', treated_crop_path or '')
