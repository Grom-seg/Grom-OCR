from __future__ import annotations

import hashlib
import math
import os
import tempfile
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


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


def _safe_text(value, fallback='-'):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _font_candidates(bold=False, size=22):
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


def sha256_file(filepath):
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


def probe_video_metadata(video_path):
    metadata = {
        'video_path': os.path.abspath(video_path) if video_path else '',
        'video_filename': os.path.basename(video_path) if video_path else '',
        'file_size_bytes': 0,
        'file_size_mb': 0.0,
        'sha256': '',
        'backend': 'opencv',
        'codec_fourcc': '',
        'codec_hint': '',
        'fps': 0.0,
        'frame_count': 0,
        'duration_seconds': 0.0,
        'width': 0,
        'height': 0,
        'rotation': 0,
        'opened': False,
        'input_signature': 'unknown',
        'input_mime': '',
        'notes': [],
    }

    if not video_path or not os.path.isfile(video_path):
        metadata['notes'].append('video_nao_encontrado')
        return metadata

    try:
        stat = os.stat(video_path)
        metadata['file_size_bytes'] = int(stat.st_size)
        metadata['file_size_mb'] = round(stat.st_size / (1024 * 1024), 2)
    except Exception:
        metadata['notes'].append('falha_ao_ler_tamanho')

    metadata['sha256'] = sha256_file(video_path)

    capture = cv2.VideoCapture(video_path)
    try:
        metadata['opened'] = bool(capture.isOpened())
        if not metadata['opened']:
            metadata['notes'].append('decoder_nao_abriu_video')
            return metadata

        fps = _safe_float(capture.get(getattr(cv2, 'CAP_PROP_FPS', 5)), 0.0)
        frame_count = _safe_int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_COUNT', 7)), 0)
        width = _safe_int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_WIDTH', 3)), 0)
        height = _safe_int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_HEIGHT', 4)), 0)
        fourcc = _safe_int(capture.get(getattr(cv2, 'CAP_PROP_FOURCC', 6)), 0)
        rotation = _safe_int(capture.get(getattr(cv2, 'CAP_PROP_ORIENTATION_META', 0)), 0)

        metadata['fps'] = round(fps, 4)
        metadata['frame_count'] = frame_count
        metadata['width'] = width
        metadata['height'] = height
        metadata['duration_seconds'] = round(frame_count / fps, 4) if fps > 0 and frame_count > 0 else 0.0
        metadata['rotation'] = rotation
        if fourcc > 0:
            try:
                codec = ''.join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4))
                metadata['codec_fourcc'] = codec.strip('\x00')
            except Exception:
                metadata['codec_fourcc'] = ''
        if metadata['codec_fourcc']:
            metadata['codec_hint'] = metadata['codec_fourcc']
    finally:
        try:
            capture.release()
        except Exception:
            pass

    return metadata


def _frame_quality_metrics(frame):
    if frame is None or not isinstance(frame, np.ndarray) or getattr(frame, 'size', 0) <= 0:
        return {
            'sharpness': 0.0,
            'brightness': 0.0,
            'contrast': 0.0,
            'colorfulness': 0.0,
            'blur_penalty': 0.0,
            'quality_score': 0.0,
        }

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    b, g, r = cv2.split(frame)
    rg = np.abs(r.astype('float32') - g.astype('float32'))
    yb = np.abs(((r.astype('float32') + g.astype('float32')) / 2.0) - b.astype('float32'))
    colorfulness = float(np.sqrt(np.mean(rg ** 2) + np.mean(yb ** 2)))
    blur_penalty = max(0.0, 1.0 - min(1.0, sharpness / 180.0))
    quality_score = (
        min(100.0, sharpness / 6.0)
        + min(18.0, contrast / 10.0)
        + max(0.0, 12.0 - abs(brightness - 128.0) / 10.0)
        + min(8.0, colorfulness / 18.0)
    )
    return {
        'sharpness': round(sharpness, 4),
        'brightness': round(brightness, 4),
        'contrast': round(contrast, 4),
        'colorfulness': round(colorfulness, 4),
        'blur_penalty': round(blur_penalty, 4),
        'quality_score': round(quality_score, 4),
    }


def _pick_sample_indices(frame_count, max_frames, skip_first_ratio=0.04, skip_last_ratio=0.02):
    frame_count = max(0, int(frame_count))
    max_frames = max(1, int(max_frames))
    if frame_count <= 0:
        return []
    if frame_count <= max_frames:
        return list(dict.fromkeys(range(frame_count)))

    start_index = int(round(frame_count * skip_first_ratio))
    end_index = int(round(frame_count * (1.0 - skip_last_ratio))) - 1
    start_index = max(0, min(start_index, frame_count - 1))
    end_index = max(start_index, min(end_index, frame_count - 1))
    if end_index <= start_index:
        start_index = 0
        end_index = frame_count - 1

    indices = np.linspace(start_index, end_index, num=max_frames, dtype=int).tolist()
    return list(dict.fromkeys(int(index) for index in indices))


def sample_video_frames(video_path, analysis_id, max_frames=12, save_dir=None):
    metadata = probe_video_metadata(video_path)
    if not metadata.get('opened'):
        return [], metadata

    frame_count = int(metadata.get('frame_count', 0) or 0)
    fps = float(metadata.get('fps', 0.0) or 0.0)
    indices = _pick_sample_indices(frame_count, max_frames=max_frames)
    if not indices and frame_count <= 0:
        indices = [0]

    target_dir = save_dir or tempfile.gettempdir()
    os.makedirs(target_dir, exist_ok=True)

    capture = cv2.VideoCapture(video_path)
    frame_entries = []
    try:
        for position, frame_index in enumerate(indices):
            if capture is None or not capture.isOpened():
                break
            capture.set(getattr(cv2, 'CAP_PROP_POS_FRAMES', 1), float(frame_index))
            ok, frame = capture.read()
            if not ok or frame is None or getattr(frame, 'size', 0) <= 0:
                continue

            quality = _frame_quality_metrics(frame)
            timestamp_seconds = (float(frame_index) / fps) if fps > 0 else float(position)
            frame_name = f"{analysis_id}_frame_{position + 1:03d}.jpg"
            frame_path = os.path.join(target_dir, frame_name)
            cv2.imwrite(frame_path, frame)

            frame_entries.append({
                'frame_index': int(frame_index),
                'frame_order': int(position + 1),
                'timestamp_seconds': round(timestamp_seconds, 4),
                'frame_name': frame_name,
                'frame_path': frame_path,
                'quality_metrics': quality,
                'source_resolution': {
                    'width': int(frame.shape[1]),
                    'height': int(frame.shape[0]),
                },
            })
    finally:
        try:
            capture.release()
        except Exception:
            pass

    return frame_entries, metadata


def build_video_contact_sheet(frame_entries, title='Quadros-chave do vídeo', subtitle='Varredura temporal integral com seleção documental'):
    entries = [entry for entry in frame_entries if isinstance(entry, dict) and os.path.exists(str(entry.get('frame_path', '')))]
    if not entries:
        return ''

    entries = entries[:6]
    canvas_w = 2400
    canvas_h = 1500
    base = Image.new('RGB', (canvas_w, canvas_h), (252, 253, 255))
    draw = ImageDraw.Draw(base)
    primary = (9, 54, 95)
    accent = (199, 144, 49)
    muted = (93, 107, 124)
    line = (214, 224, 235)

    draw.rounded_rectangle((44, 40, canvas_w - 44, canvas_h - 40), radius=36, fill=(255, 255, 255), outline=line, width=3)
    draw.line((80, 128, canvas_w - 80, 128), fill=accent, width=6)
    draw.line((80, 138, canvas_w - 80, 138), fill=(236, 240, 244), width=1)

    title_font = _font_candidates(bold=True, size=42)
    subtitle_font = _font_candidates(bold=False, size=21)
    caption_font = _font_candidates(bold=True, size=17)
    small_font = _font_candidates(bold=False, size=15)

    draw.text((82, 58), _safe_text(title, 'Quadros-chave do vídeo'), font=title_font, fill=primary)
    draw.text((84, 110), _safe_text(subtitle, 'Seleção temporal para rastreabilidade e conferência pericial.'), font=subtitle_font, fill=muted)

    cols = 3
    rows = 2
    left = 76
    top = 182
    gap_x = 26
    gap_y = 24
    cell_w = (canvas_w - left * 2 - gap_x * (cols - 1)) // cols
    cell_h = 500

    for index, entry in enumerate(entries):
        row = index // cols
        col = index % cols
        x0 = left + col * (cell_w + gap_x)
        y0 = top + row * (cell_h + gap_y)
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        draw.rounded_rectangle((x0, y0, x1, y1), radius=24, fill=(249, 252, 255), outline=line, width=2)
        draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius=22, outline=(255, 255, 255), width=1)

        frame_img = Image.open(str(entry.get('frame_path'))).convert('RGB')
        frame_box = (x0 + 18, y0 + 18, x1 - 18, y1 - 76)
        fitted = ImageOps.contain(frame_img, (frame_box[2] - frame_box[0], frame_box[3] - frame_box[1]))
        bg = Image.new('RGB', (frame_box[2] - frame_box[0], frame_box[3] - frame_box[1]), (255, 255, 255))
        bg.paste(fitted, ((bg.width - fitted.width) // 2, (bg.height - fitted.height) // 2))
        base.paste(bg, (frame_box[0], frame_box[1]))
        draw.rounded_rectangle(frame_box, radius=18, outline=(220, 228, 236), width=2)

        timestamp = float(entry.get('timestamp_seconds', 0.0) or 0.0)
        quality = entry.get('quality_metrics', {})
        ocr_text = _safe_text(entry.get('ocr', ''), 'Sem OCR')
        confidence = _safe_float(entry.get('confidence', 0.0), 0.0)

        caption_y = y1 - 58
        draw.text((x0 + 20, caption_y), f'Quadro {index + 1:02d}', font=caption_font, fill=primary)
        draw.text((x0 + 128, caption_y + 1), f'{timestamp:0.2f}s | OCR {ocr_text[:12]}', font=small_font, fill=muted)
        draw.text((x0 + 20, caption_y + 22), f'Confiança {confidence:0.1f}% | Nitidez {float(quality.get("sharpness", 0.0)):0.1f}', font=small_font, fill=muted)

    footer_y = top + rows * cell_h + 28
    draw.rounded_rectangle((78, footer_y, canvas_w - 78, footer_y + 150), radius=22, fill=(245, 248, 252), outline=line, width=2)
    draw.text((102, footer_y + 18), 'Observações de amostragem', font=caption_font, fill=primary)
    draw.text(
        (102, footer_y + 58),
        'Os quadros acima foram extraídos do vídeo-fonte em posições distribuídas ao longo da linha temporal.\n'
        'O objetivo é manter rastreabilidade, permitir conferência humana e concentrar a leitura no trecho com maior evidência.',
        font=small_font,
        fill=muted,
        spacing=8,
    )

    signature = hashlib.sha1(
        '|'.join(
            [
                str(entry.get('frame_name', ''))
                for entry in entries
            ]
        ).encode('utf-8')
    ).hexdigest()[:20]
    output_path = os.path.join(tempfile.gettempdir(), f'grom_ocr_video_contact_sheet_{signature}.png')
    base.save(output_path)
    return output_path


def select_video_best_frame(frame_results):
    ranked = []
    for entry in frame_results:
        if not isinstance(entry, dict):
            continue
        ocr_text = str(entry.get('ocr', '') or '').strip()
        confidence = _safe_float(entry.get('confidence', 0.0), 0.0)
        score = _safe_float(entry.get('score', 0.0), 0.0)
        consensus = entry.get('consensus', {})
        if not isinstance(consensus, dict):
            consensus = {}
        agreement_ratio = _safe_float(consensus.get('agreement_ratio', 0.0), 0.0)
        assessment = entry.get('assessment', {})
        if not isinstance(assessment, dict):
            assessment = {}
        assessment_conf = _safe_float(assessment.get('confidence_percent', 0.0), 0.0)
        quality = entry.get('input_meta', {})
        plate_detection = {}
        if isinstance(quality, dict):
            plate_detection = quality.get('plate_detection', {})
        if not isinstance(plate_detection, dict):
            plate_detection = {}
        selection_bonus = 0.0
        if ocr_text:
            selection_bonus += 4.0
            if len(ocr_text) == 7:
                selection_bonus += 3.0
        if str(entry.get('status', '')).upper() == 'CONCLUSIVO':
            selection_bonus += 6.0
        if agreement_ratio >= 80.0:
            selection_bonus += 4.0
        if assessment_conf >= 70.0:
            selection_bonus += 3.0
        frame_quality = entry.get('frame_quality', {})
        if not isinstance(frame_quality, dict):
            frame_quality = {}
        sharpness = _safe_float(frame_quality.get('sharpness', 0.0), 0.0)
        sharpness_bonus = min(6.0, sharpness / 55.0)
        frame_score = (
            confidence * 0.55
            + min(100.0, score) * 0.2
            + agreement_ratio * 0.14
            + assessment_conf * 0.08
            + selection_bonus
            + sharpness_bonus
        )
        ranked.append((frame_score, entry))

    ranked.sort(key=lambda item: item[0], reverse=True)
    ordered = [entry for _, entry in ranked]
    best = ordered[0] if ordered else {}

    text_counts = {}
    confidence_samples = {}
    for entry in ordered:
        text = str(entry.get('ocr', '') or '').strip()
        if not text:
            continue
        text_counts[text] = text_counts.get(text, 0) + 1
        confidence_samples.setdefault(text, []).append(_safe_float(entry.get('confidence', 0.0), 0.0))

    consensus_text = ''
    consensus_count = 0
    consensus_confidence = 0.0
    if text_counts:
        consensus_text, consensus_count = sorted(text_counts.items(), key=lambda item: (item[1], len(item[0])), reverse=True)[0]
        sample_conf = confidence_samples.get(consensus_text, [])
        if sample_conf:
            consensus_confidence = sum(sample_conf) / len(sample_conf)

    return {
        'best_frame': best,
        'ranked_frames': ordered,
        'consensus_text': consensus_text,
        'consensus_count': consensus_count,
        'consensus_confidence': round(consensus_confidence, 2),
        'frames_with_text': len(text_counts),
    }


def build_video_forensic_chain(analysis_id, source_path, plate_path, started_utc, finished_utc):
    source_hash = sha256_file(source_path)
    plate_hash = sha256_file(plate_path)
    payload = {
        'analysis_id': str(analysis_id or '').strip(),
        'source_path': os.path.abspath(source_path) if source_path else '',
        'plate_path': os.path.abspath(plate_path) if plate_path else '',
        'source_sha256': source_hash,
        'plate_sha256': plate_hash,
        'video_sha256': source_hash,
        'media_type': 'video',
        'started_utc': str(started_utc or '').strip(),
        'finished_utc': str(finished_utc or '').strip(),
        'algorithm': 'sha256',
        'chain_type': 'video_forensic_chain',
    }
    payload['signature'] = hashlib.sha256(
        '|'.join([
            payload['analysis_id'],
            payload['source_sha256'],
            payload['plate_sha256'],
            payload['started_utc'],
            payload['finished_utc'],
        ]).encode('utf-8')
    ).hexdigest()
    return payload

