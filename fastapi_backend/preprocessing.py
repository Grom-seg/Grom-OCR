import os
import logging

import cv2
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

# Importa SR unificado (Real-ESRGAN ONNX com fallback bicúbico)
try:
    from fastapi_backend.super_resolution import apply_super_resolution as _sr_apply
    _SR_MODULE_AVAILABLE = True
except Exception:
    _sr_apply = None
    _SR_MODULE_AVAILABLE = False


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


# Largura mínima alvo para super-resolução (pixels)
_SR_TARGET_WIDTH = int(os.getenv('GROM_SR_TARGET_WIDTH', '400'))
# Categoria de resolução que dispara SR (very_low, low)
_SR_TRIGGER_CATEGORIES = {'very_low', 'low'}


def _classify_blur(gray: np.ndarray) -> str:
    """
    Classifica nível de blur pela variância do Laplaciano.

    Inspirado no subset ccpd_blur (borrão de movimento por veículo em alta velocidade).
    Limiares calibrados empiricamente para imagens de placa (crop reduzido):
      - strong_blur : var < 50   → sharpening muito agressivo necessário
      - moderate_blur: var < 150  → sharpening padrão elevado
      - sharp       : var >= 150  → sharpening leve

    Retorna: 'strong_blur' | 'moderate_blur' | 'sharp'
    """
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var < 50.0:
        return 'strong_blur'
    if lap_var < 150.0:
        return 'moderate_blur'
    return 'sharp'


def _correct_gamma(gray: np.ndarray) -> np.ndarray:
    """
    Corrige brilho global via correção de gama.

    Inspirado no subset ccpd_fn (far+night: subexposição) e condições de
    overexposure (sol direto, reflexo de asfalto).

    Regra:
      - mean < 70  → imagem escura  → gama < 1 (clareia, target ~128)
      - mean > 185 → imagem clara  → gama > 1 (escurece, target ~128)
      - 70–185     → sem alteração (CLAHE já lida com contraste local)

    Usa LUT de 256 posições para eficiência O(1) por pixel.
    """
    mean = float(gray.mean())
    if 70.0 <= mean <= 185.0:
        return gray

    target = 128.0
    # Resolve (mean/255)^gamma = target/255 → gamma = log(target/255)/log(mean/255)
    # O LUT aplica f(x) = x^gamma — NÃO o inverso.
    log_mean = np.log(max(mean, 1.0) / 255.0)
    if log_mean == 0.0:
        return gray
    gamma = float(np.log(target / 255.0) / log_mean)
    gamma = float(np.clip(gamma, 0.25, 4.0))

    table = np.array(
        [(i / 255.0) ** gamma * 255 for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(gray, table)


def _needs_super_resolution(img: np.ndarray, resolution_category: str = None) -> bool:
    """
    Decide se a imagem precisa de super-resolução.
    Critério: largura < _SR_TARGET_WIDTH ou categoria 'very_low'/'low'.
    """
    h, w = img.shape[:2]
    if resolution_category and resolution_category in _SR_TRIGGER_CATEGORIES:
        return True
    return w < _SR_TARGET_WIDTH


def _super_resolve(img: np.ndarray, target_width: int = _SR_TARGET_WIDTH) -> np.ndarray:
    """
    Super-resolução leve via upscaling bicúbico + unsharp mask agressivo.

    Estratégia em 3 passos:
      1. Upscale 2x com INTER_CUBIC (melhor para textos vs INTER_LINEAR)
      2. Reduz para target_width mantendo aspect ratio (INTER_AREA = antialiasing)
      3. Unsharp mask forte para recuperar bordas dos caracteres

    Nota: sem modelo DNN (evita dependência pesada). Se futuramente
    quisermos ESRGAN, basta substituir o passo 1.
    """
    h, w = img.shape[:2]
    if w == 0 or h == 0:
        return img

    # Passo 1: upscale 2x bicúbico
    up_w = w * 2
    up_h = h * 2
    upscaled = cv2.resize(img, (up_w, up_h), interpolation=cv2.INTER_CUBIC)

    # Passo 2: reduz para target_width se necessário
    if up_w > target_width:
        scale = target_width / up_w
        final_w = target_width
        final_h = max(1, int(up_h * scale))
        upscaled = cv2.resize(upscaled, (final_w, final_h), interpolation=cv2.INTER_AREA)

    # Passo 3: unsharp mask agressivo para recuperar nitidez dos caracteres
    blurred = cv2.GaussianBlur(upscaled, (0, 0), sigmaX=1.5)
    sharpened = cv2.addWeighted(upscaled, 1.8, blurred, -0.8, 0)

    return sharpened


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


def _select_intensity(quality_score: float, blur_level: str = 'sharp') -> dict:
    """
    Seleciona parâmetros de preprocessing com base no score de qualidade e blur.

    Dois eixos de controle:
      - quality_score: 0–1, governa CLAHE e denoise
      - blur_level: 'sharp' | 'moderate_blur' | 'strong_blur'
                    governa sharpening (inspirado no subset ccpd_blur)

    Tabela de sharpening por blur_level:
      sharp         → weight 1.25, sigma 1.0
      moderate_blur → weight 1.45, sigma 1.3  (+0.2/+0.3 vs sharp)
      strong_blur   → weight 1.65, sigma 1.8  (+0.4/+0.8 vs sharp)
    """
    # Parâmetros base por qualidade
    if quality_score >= 0.75:
        base = {'clahe_clip': 1.5, 'clahe_tile': (8, 8), 'denoise_h': 5,
                'sharpen_weight': 1.25, 'sharpen_blur_sigma': 1.0}
    elif quality_score >= 0.50:
        base = {'clahe_clip': 2.0, 'clahe_tile': (8, 8), 'denoise_h': 7,
                'sharpen_weight': 1.35, 'sharpen_blur_sigma': 1.2}
    else:
        base = {'clahe_clip': 3.0, 'clahe_tile': (6, 6), 'denoise_h': 10,
                'sharpen_weight': 1.50, 'sharpen_blur_sigma': 1.5}

    # Boost de sharpening conforme nível de blur (ccpd_blur)
    if blur_level == 'strong_blur':
        base['sharpen_weight'] = min(base['sharpen_weight'] + 0.40, 2.0)
        base['sharpen_blur_sigma'] = min(base['sharpen_blur_sigma'] + 0.8, 2.5)
    elif blur_level == 'moderate_blur':
        base['sharpen_weight'] = min(base['sharpen_weight'] + 0.20, 2.0)
        base['sharpen_blur_sigma'] = min(base['sharpen_blur_sigma'] + 0.3, 2.5)

    return base


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
        - GROM_OCR_PREPROCESS_SR (default: true)        ← super-resolução
        - GROM_OCR_PREPROCESS_GAMMA (default: true)     ← correção de gama (ccpd_fn)
        - GROM_OCR_PREPROCESS_BLUR_ADAPT (default: true)← sharpening adaptativo ao blur (ccpd_blur)
    """
    img = _load_bgr_image(image_path)
    if img is None:
        return Image.open(image_path).convert('L')

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- Resolução do quality_score ---
    if isinstance(quality_score, dict):
        resolution_category = quality_score.get('resolution_category', None)
        quality_score = quality_score.get('overall_quality_score', None)
    else:
        resolution_category = None

    if quality_score is None:
        quality_score = 0.60  # Intensidade padrão (média)

    # --- Flags de controle ---
    adaptive_enabled = _is_enabled('GROM_OCR_PREPROCESS_ADAPTIVE', default=True)
    denoise_enabled = _is_enabled('GROM_OCR_PREPROCESS_DENOISE', default=True)
    threshold_enabled = _is_enabled('GROM_OCR_PREPROCESS_THRESHOLD', default=False)
    rotation_enabled = _is_enabled('GROM_OCR_PREPROCESS_ROTATION', default=True)
    sr_enabled = _is_enabled('GROM_OCR_PREPROCESS_SR', default=True)
    gamma_enabled = _is_enabled('GROM_OCR_PREPROCESS_GAMMA', default=True)
    blur_adapt_enabled = _is_enabled('GROM_OCR_PREPROCESS_BLUR_ADAPT', default=True)

    # --- Correção de gama (ccpd_fn: noite/overexposure) ---
    # Feita ANTES de SR e rotação para normalizar brilho global primeiro.
    if gamma_enabled:
        gray = _correct_gamma(gray)
        logger.debug('Gamma aplicado: mean_pós=%.1f', gray.mean())

    # --- Classificação de blur (ccpd_blur) ---
    blur_level = _classify_blur(gray) if blur_adapt_enabled else 'sharp'
    if blur_level != 'sharp':
        logger.debug('Blur detectado: %s (Laplacian var usado internamente)', blur_level)

    # Parâmetros adaptativos (qualidade + blur)
    params = _select_intensity(quality_score, blur_level)

    # --- Super-resolução (antes da rotação para aproveitar SR em imagem menor) ---
    if sr_enabled and _needs_super_resolution(gray, resolution_category):
        logger.debug(
            'Aplicando super-resolução: %dx%d → target_width=%d (cat=%s)',
            gray.shape[1], gray.shape[0], _SR_TARGET_WIDTH, resolution_category,
        )
        if _SR_MODULE_AVAILABLE and _sr_apply is not None:
            # Usa Real-ESRGAN ONNX se disponível; fallback bicúbico interno
            gray = _sr_apply(gray, _SR_TARGET_WIDTH)
        else:
            gray = _super_resolve(gray)

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
