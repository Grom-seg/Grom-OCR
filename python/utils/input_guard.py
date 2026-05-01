import os


DEFAULT_ALLOWED_EXTENSIONS = (
    '.jpg',
    '.jpeg',
    '.png',
    '.webp',
    '.bmp',
    '.tif',
    '.tiff',
    '.pdf',
)

DEFAULT_ALLOWED_VIDEO_EXTENSIONS = (
    '.mp4',
    '.m4v',
    '.mov',
    '.3gp',
    '.avi',
    '.mkv',
    '.webm',
    '.mpg',
    '.mpeg',
    '.ts',
    '.m2ts',
    '.mts',
    '.vob',
    '.dav',
    '.264',
    '.265',
    '.h264',
    '.h265',
)

IMAGE_SIGNATURES = {
    'jpeg': {'mime': 'image/jpeg', 'extensions': {'.jpg', '.jpeg'}},
    'png': {'mime': 'image/png', 'extensions': {'.png'}},
    'webp': {'mime': 'image/webp', 'extensions': {'.webp'}},
    'bmp': {'mime': 'image/bmp', 'extensions': {'.bmp'}},
    'tiff': {'mime': 'image/tiff', 'extensions': {'.tif', '.tiff'}},
    'pdf': {'mime': 'application/pdf', 'extensions': {'.pdf'}},
}

VIDEO_SIGNATURES = {
    'mp4': {'mime': 'video/mp4', 'extensions': {'.mp4', '.m4v', '.mov', '.3gp'}},
    'avi': {'mime': 'video/x-msvideo', 'extensions': {'.avi'}},
    'mkv': {'mime': 'video/x-matroska', 'extensions': {'.mkv', '.webm'}},
    'mpeg': {'mime': 'video/mpeg', 'extensions': {'.mpg', '.mpeg', '.vob'}},
    'transport_stream': {'mime': 'video/mp2t', 'extensions': {'.ts', '.m2ts', '.mts'}},
    'raw_stream': {'mime': 'video/h264', 'extensions': {'.264', '.h264', '.265', '.h265'}},
    'dav': {'mime': 'video/x-dav', 'extensions': {'.dav'}},
}


def _parse_int(value, default):
    try:
        parsed = int(float(str(value).strip()))
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _normalize_extension(filename):
    base = os.path.basename(filename or '').strip()
    _, ext = os.path.splitext(base)
    return ext.lower()


def allowed_upload_extensions():
    raw = os.environ.get('GROM_OCR_ALLOWED_INPUT_EXTENSIONS', '').strip()
    if not raw:
        return list(DEFAULT_ALLOWED_EXTENSIONS)

    extensions = []
    for token in raw.replace(';', ',').replace('|', ',').split(','):
        item = token.strip().lower()
        if not item:
            continue
        if not item.startswith('.'):
            item = '.' + item
        extensions.append(item)

    return list(dict.fromkeys(extensions)) if extensions else list(DEFAULT_ALLOWED_EXTENSIONS)


def allowed_video_upload_extensions():
    raw = os.environ.get('GROM_OCR_ALLOWED_VIDEO_EXTENSIONS', '').strip()
    if not raw:
        return list(DEFAULT_ALLOWED_VIDEO_EXTENSIONS)

    extensions = []
    for token in raw.replace(';', ',').replace('|', ',').split(','):
        item = token.strip().lower()
        if not item:
            continue
        if not item.startswith('.'):
            item = '.' + item
        extensions.append(item)

    return list(dict.fromkeys(extensions)) if extensions else list(DEFAULT_ALLOWED_VIDEO_EXTENSIONS)


def max_upload_bytes():
    raw_bytes = os.environ.get('GROM_OCR_MAX_UPLOAD_BYTES', '').strip()
    if raw_bytes:
        parsed = _parse_int(raw_bytes, 0)
        if parsed > 0:
            return parsed

    raw_mb = os.environ.get('GROM_OCR_MAX_UPLOAD_MB', '').strip()
    if raw_mb:
        parsed = _parse_int(raw_mb, 0)
        if parsed > 0:
            return parsed * 1024 * 1024

    return 80 * 1024 * 1024


def max_video_upload_bytes():
    raw_bytes = os.environ.get('GROM_OCR_MAX_VIDEO_BYTES', '').strip()
    if raw_bytes:
        parsed = _parse_int(raw_bytes, 0)
        if parsed > 0:
            return parsed

    raw_mb = os.environ.get('GROM_OCR_MAX_VIDEO_MB', '').strip()
    if raw_mb:
        parsed = _parse_int(raw_mb, 0)
        if parsed > 0:
            return parsed * 1024 * 1024

    return 800 * 1024 * 1024


def max_video_duration_seconds():
    raw_seconds = os.environ.get('GROM_OCR_MAX_VIDEO_DURATION_SECONDS', '').strip()
    if raw_seconds:
        parsed = _parse_int(raw_seconds, 0)
        if parsed > 0:
            return parsed

    raw_minutes = os.environ.get('GROM_OCR_MAX_VIDEO_DURATION_MINUTES', '').strip()
    if raw_minutes:
        parsed = _parse_int(raw_minutes, 0)
        if parsed > 0:
            return parsed * 60

    return 600


def detect_upload_signature(filepath):
    signature = {
        'kind': 'unknown',
        'mime': '',
        'family': 'unknown',
        'recognized': False,
    }

    if not filepath or not os.path.isfile(filepath):
        return signature

    try:
        with open(filepath, 'rb') as stream:
            header = stream.read(16)
    except Exception:
        return signature

    if header.startswith(b'%PDF'):
        signature.update({'kind': 'pdf', 'mime': 'application/pdf', 'family': 'pdf', 'recognized': True})
        return signature
    if header.startswith(b'\xff\xd8\xff'):
        signature.update({'kind': 'jpeg', 'mime': 'image/jpeg', 'family': 'image', 'recognized': True})
        return signature
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        signature.update({'kind': 'png', 'mime': 'image/png', 'family': 'image', 'recognized': True})
        return signature
    if header.startswith(b'RIFF') and len(header) >= 12 and header[8:12] == b'WEBP':
        signature.update({'kind': 'webp', 'mime': 'image/webp', 'family': 'image', 'recognized': True})
        return signature
    if header.startswith(b'BM'):
        signature.update({'kind': 'bmp', 'mime': 'image/bmp', 'family': 'image', 'recognized': True})
        return signature
    if header[:2] in (b'II', b'MM') and header[2:4] in (b'*\x00', b'\x00*'):
        signature.update({'kind': 'tiff', 'mime': 'image/tiff', 'family': 'image', 'recognized': True})
        return signature

    return signature


def detect_video_signature(filepath):
    signature = {
        'kind': 'unknown',
        'mime': '',
        'family': 'unknown',
        'recognized': False,
    }

    if not filepath or not os.path.isfile(filepath):
        return signature

    try:
        with open(filepath, 'rb') as stream:
            header = stream.read(256)
    except Exception:
        return signature

    if len(header) >= 12 and header[4:8] == b'ftyp':
        return {'kind': 'mp4', 'mime': 'video/mp4', 'family': 'video', 'recognized': True}
    if len(header) >= 12 and header.startswith(b'RIFF') and header[8:12] == b'AVI ':
        return {'kind': 'avi', 'mime': 'video/x-msvideo', 'family': 'video', 'recognized': True}
    if header.startswith(b'\x1A\x45\xDF\xA3'):
        return {'kind': 'mkv', 'mime': 'video/x-matroska', 'family': 'video', 'recognized': True}
    if header.startswith(b'\x00\x00\x01\xBA') or header.startswith(b'\x00\x00\x01\xB3'):
        return {'kind': 'mpeg', 'mime': 'video/mpeg', 'family': 'video', 'recognized': True}
    if len(header) >= 16 and header[4:8] == b'ftyp':
        return {'kind': 'mp4', 'mime': 'video/mp4', 'family': 'video', 'recognized': True}

    return signature


def _probe_video_openable(filepath):
    try:
        import cv2  # Local import to keep the guard lightweight for image-only flows.
    except Exception:
        return False, {}

    try:
        capture = cv2.VideoCapture(filepath)
    except Exception:
        return False, {}

    try:
        if capture is None or not capture.isOpened():
            return False, {}

        frame_count = int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_COUNT', 7)) or 0)
        fps = float(capture.get(getattr(cv2, 'CAP_PROP_FPS', 5)) or 0.0)
        width = int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_WIDTH', 3)) or 0)
        height = int(capture.get(getattr(cv2, 'CAP_PROP_FRAME_HEIGHT', 4)) or 0)
        duration = (frame_count / fps) if fps > 0 else 0.0
        return True, {
            'frame_count': frame_count,
            'fps': round(fps, 4),
            'resolution': {'width': width, 'height': height},
            'duration_seconds': round(duration, 4),
        }
    finally:
        try:
            capture.release()
        except Exception:
            pass


def inspect_upload_video_file(filepath, filename, content_type=''):
    allowed_extensions = allowed_video_upload_extensions()
    max_bytes = max_video_upload_bytes()
    normalized_extension = _normalize_extension(filename)
    size_bytes = 0
    warnings = []
    error = ''
    allowed = False
    signature = detect_video_signature(filepath)
    max_duration_seconds = max_video_duration_seconds()

    if not filepath or not os.path.exists(filepath):
        error = 'Arquivo enviado nao encontrado'
    else:
        try:
            size_bytes = int(os.path.getsize(filepath))
        except Exception:
            size_bytes = 0

        ext_allowed = normalized_extension in allowed_extensions
        content_type_normalized = (content_type or '').strip().lower()
        video_probe_ok, video_probe = _probe_video_openable(filepath)

        if size_bytes <= 0:
            error = 'Arquivo enviado esta vazio'
        elif not ext_allowed:
            error = 'Extensao nao permitida para analise'
        elif size_bytes > max_bytes:
            error = 'Arquivo enviado excede o limite configurado'
        elif not signature.get('recognized') and not video_probe_ok:
            error = 'Assinatura do video nao reconhecida e o arquivo nao abriu no decoder'
        elif float(video_probe.get('duration_seconds', 0.0) or 0.0) > float(max_duration_seconds):
            error = 'Video excede o limite de 10 minutos'
        else:
            allowed = True
            if not signature.get('recognized') and video_probe_ok:
                signature = {
                    'kind': f"video_{normalized_extension.lstrip('.') or 'unknown'}",
                    'mime': content_type_normalized or 'video/*',
                    'family': 'video',
                    'recognized': True,
                }
                warnings.append('video_signature_confirmed_by_decoder')
            if content_type_normalized and signature.get('mime'):
                expected = str(signature.get('mime', '')).lower()
                if content_type_normalized not in (expected, 'application/octet-stream', 'video/*'):
                    warnings.append('content_type_divergente')
            if size_bytes >= int(max_bytes * 0.8):
                warnings.append('arquivo_proximo_do_limite')

    return {
        'status': 'ok' if allowed else 'blocked',
        'allowed': allowed,
        'error': error,
        'warnings': warnings,
        'original_filename': os.path.basename(filename or ''),
        'extension': normalized_extension,
        'input_type': 'video' if normalized_extension in allowed_extensions else 'unsupported',
        'content_type': (content_type or '').strip(),
        'detected_signature': str(signature.get('kind', 'unknown')),
        'detected_mime': str(signature.get('mime', '')),
        'signature_ok': allowed and not error,
        'file_size_bytes': size_bytes,
        'file_size_mb': round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else 0.0,
        'max_upload_bytes': max_bytes,
        'max_upload_mb': round(max_bytes / (1024 * 1024), 2),
        'max_duration_seconds': max_duration_seconds,
        'allowed_extensions': allowed_extensions,
        'policy': 'allowlist_extension+signature+size+decoder_probe',
        'video_probe': video_probe if isinstance(video_probe, dict) else {},
    }


def inspect_upload_file(filepath, filename, content_type=''):
    allowed_extensions = allowed_upload_extensions()
    max_bytes = max_upload_bytes()
    normalized_extension = _normalize_extension(filename)
    size_bytes = 0
    warnings = []
    error = ''
    allowed = False
    signature = detect_upload_signature(filepath)

    if not filepath or not os.path.exists(filepath):
        error = 'Arquivo enviado nao encontrado'
    else:
        try:
            size_bytes = int(os.path.getsize(filepath))
        except Exception:
            size_bytes = 0

        ext_allowed = normalized_extension in allowed_extensions
        extension_family = 'pdf' if normalized_extension == '.pdf' else ('image' if normalized_extension in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'} else 'unknown')
        signature_kind = str(signature.get('kind', 'unknown'))
        signature_family = str(signature.get('family', 'unknown'))
        content_type_normalized = (content_type or '').strip().lower()

        if size_bytes <= 0:
            error = 'Arquivo enviado esta vazio'
        elif not ext_allowed:
            error = 'Extensao nao permitida para analise'
        elif size_bytes > max_bytes:
            error = 'Arquivo enviado excede o limite configurado'
        elif not signature.get('recognized'):
            error = 'Assinatura do arquivo nao reconhecida'
        elif extension_family == 'pdf' and signature_kind != 'pdf':
            error = 'Arquivo PDF invalido ou corrompido'
        elif extension_family == 'image' and signature_family != 'image':
            error = 'Arquivo de imagem invalido ou corrompido'
        else:
            allowed = True
            if content_type_normalized and signature.get('mime'):
                expected = str(signature.get('mime', '')).lower()
                if content_type_normalized not in (expected, 'application/octet-stream'):
                    warnings.append('content_type_divergente')
            if size_bytes >= int(max_bytes * 0.8):
                warnings.append('arquivo_proximo_do_limite')

    return {
        'status': 'ok' if allowed else 'blocked',
        'allowed': allowed,
        'error': error,
        'warnings': warnings,
        'original_filename': os.path.basename(filename or ''),
        'extension': normalized_extension,
        'input_type': 'pdf' if normalized_extension == '.pdf' else ('image' if normalized_extension in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'} else 'unsupported'),
        'content_type': (content_type or '').strip(),
        'detected_signature': str(signature.get('kind', 'unknown')),
        'detected_mime': str(signature.get('mime', '')),
        'signature_ok': allowed and not error,
        'file_size_bytes': size_bytes,
        'file_size_mb': round(size_bytes / (1024 * 1024), 2) if size_bytes > 0 else 0.0,
        'max_upload_bytes': max_bytes,
        'max_upload_mb': round(max_bytes / (1024 * 1024), 2),
        'allowed_extensions': allowed_extensions,
        'policy': 'allowlist_extension+signature+size',
    }
