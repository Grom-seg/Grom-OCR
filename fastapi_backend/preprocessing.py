import os

import cv2
from PIL import Image
import numpy as np


def _load_bgr_image(image_path):
    """Carrega imagem com fallback para path Unicode no Windows."""
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is not None:
        return img

    try:
        data = np.fromfile(image_path, dtype=np.uint8)
        if data.size == 0:
            return None
        decoded = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return decoded
    except Exception:
        return None


def _is_enabled(env_name: str, default: bool = True) -> bool:
    raw = str(os.getenv(env_name, str(default))).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def preprocess_image(image_path):
    """
    Pré-processamento adaptativo de imagem para OCR.

    Flags (env vars):
    - GROM_OCR_PREPROCESS_ADAPTIVE (default: true)
    - GROM_OCR_PREPROCESS_DENOISE (default: true)
    - GROM_OCR_PREPROCESS_THRESHOLD (default: false)
    """
    img = _load_bgr_image(image_path)
    if img is None:
        # Mantém compatibilidade em caso de falha de leitura.
        return Image.open(image_path).convert('L')

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    adaptive_enabled = _is_enabled('GROM_OCR_PREPROCESS_ADAPTIVE', default=True)
    denoise_enabled = _is_enabled('GROM_OCR_PREPROCESS_DENOISE', default=True)
    threshold_enabled = _is_enabled('GROM_OCR_PREPROCESS_THRESHOLD', default=False)

    if adaptive_enabled:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        processed = clahe.apply(gray)
    else:
        processed = cv2.equalizeHist(gray)

    if denoise_enabled:
        processed = cv2.fastNlMeansDenoising(processed, None, h=7, templateWindowSize=7, searchWindowSize=21)

    # Unsharp mask leve para preservar contornos dos caracteres.
    blurred = cv2.GaussianBlur(processed, (0, 0), sigmaX=1.2)
    processed = cv2.addWeighted(processed, 1.35, blurred, -0.35, 0)

    if threshold_enabled:
        processed = cv2.adaptiveThreshold(
            processed,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            8,
        )

    return Image.fromarray(processed)
