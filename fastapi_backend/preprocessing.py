import os
import logging

import cv2
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


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


def _correct_rotation(gray: np.ndarray, angle: float) -> np.ndarray:
    """
    Corrige rotação da imagem.
    Só aplica se |angle| > 1.0° para evitar processamento desnecessário.
    """
    if abs(angle) <= 1.0:
        return gray

    h, w = gray.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, -angle, 1.0)

    # Calcula novo bounding box para não cortar a imagem
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w / 2.0) - center[0]
    M[1, 2] += (new_h / 2.0) - center[1]

    rotated = cv2.warpAffine(
        gray, M, (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def _estimate_rotation_angle(gray: np.ndarray) -> float:
    """
    Estima ângulo de rotação via linhas de Hough.
    Retorna ângulo em graus (-45 a 45).
    """
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=80,
            minLineLength=max(30, gray.shape[1] // 10),
            maxLineGap=10,
        )
        if lines is None or len(lines) == 0:
            return 0.0

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 != x1:
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Normaliza para [-45, 45]
                if angle > 45:
                    angle -= 90
                elif angle < -45:
                    angle += 90
                angles.append(angle)

        if not angles:
            return 0.0

        # Mediana é mais robusta que média
        return float(np.median(angles))
    except Exception:
        return 0.0


def _select_intensity(quality_score: float) -> dict:
    """
    Seleciona parâmetros de preprocessing com base no score de qualidade.
    Imagens de baixa qualidade recebem processamento mais agressivo.
    """
    if quality_score >= 0.75:
        # Boa qualidade: processamento leve
        return {
            'clahe_clip': 1.5,
            'clahe_tile': (8, 8),
            'denoise_h': 5,
            'sharpen_weight': 1.25,
            'sharpen_blur_sigma': 1.0,
        }
    elif quality_score >= 0.50:
        # Qualidade média: processamento padrão
        return {
            'clahe_clip': 2.0,
            'clahe_tile': (8, 8),
            'denoise_h': 7,
            'sharpen_weight': 1.35,
            'sharpen_blur_sigma': 1.2,
        }
    else:
        # Baixa qualidade: processamento agressivo
        return {
            'clahe_clip': 3.0,
            'clahe_tile': (6, 6),
            'denoise_h': 10,
            'sharpen_weight': 1.50,
            'sharpen_blur_sigma': 1.5,
        }


def preprocess_image(image_path, quality_score: float = None, rotation_angle: float = None):
    """
    Pré-processamento adaptativo de imagem para OCR.

    Args:
        image_path: Caminho para a imagem.
        quality_score: Score 0-1 do ImageQualityAnalyzer. Se None, usa
                       intensidade padrão (média). Aceita também dict com
                       campo 'overall_quality_score'.
        rotation_angle: Ângulo de rotação em graus para corrigir. Se None,
                        estima automaticamente via Hough. Use 0.0 para
                        desabilitar correção.

    Flags (env vars):
        - GROM_OCR_PREPROCESS_ADAPTIVE (default: true)
        - GROM_OCR_PREPROCESS_DENOISE (default: true)
        - GROM_OCR_PREPROCESS_THRESHOLD (default: false)
        - GROM_OCR_PREPROCESS_ROTATION (default: true)
    """
    img = _load_bgr_image(image_path)
    if img is None:
        return Image.open(image_path).convert('L')

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- Resolução do quality_score ---
    if isinstance(quality_score, dict):
        quality_score = quality_score.get('overall_quality_score', None)
    if quality_score is None:
        quality_score = 0.60  # Intensidade padrão (média)

    params = _select_intensity(quality_score)

    # --- Flags de controle ---
    adaptive_enabled = _is_enabled('GROM_OCR_PREPROCESS_ADAPTIVE', default=True)
    denoise_enabled = _is_enabled('GROM_OCR_PREPROCESS_DENOISE', default=True)
    threshold_enabled = _is_enabled('GROM_OCR_PREPROCESS_THRESHOLD', default=False)
    rotation_enabled = _is_enabled('GROM_OCR_PREPROCESS_ROTATION', default=True)

    # --- Correção de rotação ---
    if rotation_enabled:
        if rotation_angle is None:
            rotation_angle = _estimate_rotation_angle(gray)
        if abs(rotation_angle) > 1.0:
            logger.debug('Corrigindo rotação: %.1f°', rotation_angle)
            gray = _correct_rotation(gray, rotation_angle)

    # --- Equalização de histograma ---
    if adaptive_enabled:
        clahe = cv2.createCLAHE(
            clipLimit=params['clahe_clip'],
            tileGridSize=params['clahe_tile'],
        )
        processed = clahe.apply(gray)
    else:
        processed = cv2.equalizeHist(gray)

    # --- Redução de ruído ---
    if denoise_enabled:
        processed = cv2.fastNlMeansDenoising(
            processed, None,
            h=params['denoise_h'],
            templateWindowSize=7,
            searchWindowSize=21,
        )

    # --- Unsharp mask adaptativo ---
    blurred = cv2.GaussianBlur(processed, (0, 0), sigmaX=params['sharpen_blur_sigma'])
    processed = cv2.addWeighted(
        processed, params['sharpen_weight'],
        blurred, -(params['sharpen_weight'] - 1.0),
        0,
    )

    # --- Limiarização opcional ---
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
