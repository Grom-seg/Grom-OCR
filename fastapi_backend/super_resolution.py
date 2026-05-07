"""
Super-Resolução via Real-ESRGAN ONNX — Grom OCR

Estratégia em dois níveis:
  1. ONNX (Real-ESRGAN x4): quando modelo disponível em disco.
  2. Fallback bicúbico + unsharp mask: comportamento atual preservado.

O fallback é idêntico ao _super_resolve() do preprocessing.py para
garantia de não-regressão.

Env vars:
  GROM_SR_ONNX_PATH      caminho do modelo .onnx
                          (default: <projeto>/models/realesrgan_x4.onnx)
  GROM_SR_ONNX_TILE      tamanho do tile para tiled-inference (default: 256)
  GROM_SR_ONNX_ENABLED   habilita ONNX SR (default: true)
  GROM_SR_DOWNLOAD_AUTO  baixa modelo se ausente (default: false)
                          URL configurável via GROM_SR_ONNX_URL

Modelo de referência:
  Real-ESRGAN x4plus — 17 MB ONNX
  Disponível em: https://github.com/xinntao/Real-ESRGAN
  Input : [1, 3, H, W] float32 normalizado [0, 1]
  Output: [1, 3, H*4, W*4] float32 normalizado [0, 1]
"""

import logging
import os
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, 'models', 'realesrgan_x4.onnx')
_DEFAULT_ONNX_URL = (
    'https://github.com/Grom-seg/Grom-OCR/releases/download/'
    'v0.1.0/realesrgan_x4.onnx'
)
_TILE_SIZE = int(os.getenv('GROM_SR_ONNX_TILE', '256'))
_TILE_PAD = 10
_SR_TARGET_WIDTH = int(os.getenv('GROM_SR_TARGET_WIDTH', '400'))


def _is_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


# ---------------------------------------------------------------------------
# Fallback bicúbico (sem modelo — idêntico ao comportamento atual)
# ---------------------------------------------------------------------------

def _bicubic_fallback(gray: np.ndarray, target_width: int = _SR_TARGET_WIDTH) -> np.ndarray:
    """
    Upscaling bicúbico 2× + unsharp mask.
    Preserva comportamento original de preprocessing._super_resolve().
    """
    h, w = gray.shape[:2]
    if w == 0 or h == 0:
        return gray

    up_w, up_h = w * 2, h * 2
    upscaled = cv2.resize(gray, (up_w, up_h), interpolation=cv2.INTER_CUBIC)

    if up_w > target_width:
        scale = target_width / up_w
        upscaled = cv2.resize(
            upscaled,
            (target_width, max(1, int(up_h * scale))),
            interpolation=cv2.INTER_AREA,
        )

    blurred = cv2.GaussianBlur(upscaled, (0, 0), sigmaX=1.5)
    return cv2.addWeighted(upscaled, 1.8, blurred, -0.8, 0)


# ---------------------------------------------------------------------------
# Modelo ONNX Real-ESRGAN
# ---------------------------------------------------------------------------

class SuperResolutionModel:
    """
    Wrapper lazy para ONNX Real-ESRGAN x4.

    - Carrega sessão ONNX apenas na primeira inferência.
    - Se modelo ausente e GROM_SR_DOWNLOAD_AUTO=true, tenta baixar.
    - Fallback automático para bicúbico se ONNX indisponível.
    - Thread-safe para leituras simultâneas (sem estado mutável pós-init).
    """

    def __init__(self, model_path: Optional[str] = None):
        self._model_path = (
            model_path
            or os.getenv('GROM_SR_ONNX_PATH', _DEFAULT_MODEL_PATH)
        )
        self._session = None
        self._input_name: Optional[str] = None
        self._onnx_enabled = _is_enabled('GROM_SR_ONNX_ENABLED', default=True)
        self._loaded: bool = False  # flag para tentar carregar apenas uma vez

    # ------------------------------------------------------------------
    # Carregamento lazy
    # ------------------------------------------------------------------

    def _try_load(self) -> bool:
        """Tenta carregar a sessão ONNX. Retorna True se bem-sucedido."""
        if self._loaded:
            return self._session is not None
        self._loaded = True

        if not self._onnx_enabled:
            return False

        if not os.path.exists(self._model_path):
            if _is_enabled('GROM_SR_DOWNLOAD_AUTO', default=False):
                self._try_download()
            if not os.path.exists(self._model_path):
                logger.info(
                    'Real-ESRGAN ONNX ausente em %s → usando fallback bicúbico.',
                    self._model_path,
                )
                return False

        try:
            import onnxruntime as ort  # já instalado no projeto
            opts = ort.SessionOptions()
            opts.log_severity_level = 3  # suprime warnings verbose do ORT
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=opts,
                providers=['CPUExecutionProvider'],
            )
            self._input_name = self._session.get_inputs()[0].name
            logger.info('Real-ESRGAN ONNX carregado: %s', self._model_path)
            return True
        except Exception as exc:
            logger.warning('Falha ao carregar Real-ESRGAN ONNX: %s → fallback bicúbico.', exc)
            return False

    def _try_download(self) -> None:
        """Baixa o modelo ONNX do release público."""
        url = os.getenv('GROM_SR_ONNX_URL', _DEFAULT_ONNX_URL)
        try:
            import urllib.request
            os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
            logger.info('Baixando Real-ESRGAN ONNX de %s ...', url)
            urllib.request.urlretrieve(url, self._model_path)
            logger.info('Download concluído: %s', self._model_path)
        except Exception as exc:
            logger.warning('Falha no download Real-ESRGAN: %s', exc)

    @property
    def available(self) -> bool:
        """True se sessão ONNX está pronta."""
        if self._session is not None:
            return True
        return self._try_load()

    # ------------------------------------------------------------------
    # Inferência
    # ------------------------------------------------------------------

    def apply(self, gray: np.ndarray, target_width: int = _SR_TARGET_WIDTH) -> np.ndarray:
        """
        Aplica super-resolução à imagem grayscale.

        Args:
            gray: np.ndarray grayscale uint8.
            target_width: largura mínima alvo (usada apenas pelo fallback).

        Returns:
            np.ndarray grayscale uint8 com resolução aumentada.
        """
        if gray is None or gray.size == 0:
            return gray

        if self.available:
            result = self._apply_onnx(gray)
            if result is not None:
                return result

        return _bicubic_fallback(gray, target_width)

    def _apply_onnx(self, gray: np.ndarray) -> Optional[np.ndarray]:
        """
        Inference Real-ESRGAN ONNX com tiling para memória controlada.
        Retorna None em caso de falha (o chamador usa fallback).
        """
        try:
            # ESRGAN espera RGB float32 normalizado [0, 1]
            rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB).astype(np.float32) / 255.0
            h, w = rgb.shape[:2]

            if h <= _TILE_SIZE and w <= _TILE_SIZE:
                out_rgb = self._inference_tile(rgb)
            else:
                out_rgb = self._tiled_inference(rgb, h, w)

            # Converte saída para grayscale uint8
            out_uint8 = np.clip(out_rgb * 255.0, 0, 255).astype(np.uint8)
            return cv2.cvtColor(out_uint8, cv2.COLOR_RGB2GRAY)

        except Exception as exc:
            logger.warning('Falha na inference Real-ESRGAN ONNX: %s → fallback bicúbico.', exc)
            return None

    def _inference_tile(self, rgb_f32: np.ndarray) -> np.ndarray:
        """Inference de tile único. Input/output: [H, W, 3] float32."""
        inp = rgb_f32.transpose(2, 0, 1)[np.newaxis]   # [1, 3, H, W]
        out = self._session.run(None, {self._input_name: inp})[0]  # [1, 3, H*4, W*4]
        return out[0].transpose(1, 2, 0).clip(0.0, 1.0)            # [H*4, W*4, 3]

    def _tiled_inference(self, rgb_f32: np.ndarray, h: int, w: int) -> np.ndarray:
        """Tiled inference para imagens maiores que _TILE_SIZE — evita OOM."""
        scale = 4  # ESRGAN x4
        out = np.zeros((h * scale, w * scale, 3), dtype=np.float32)

        for row in range(0, h, _TILE_SIZE):
            for col in range(0, w, _TILE_SIZE):
                r0 = max(0, row - _TILE_PAD)
                r1 = min(h, row + _TILE_SIZE + _TILE_PAD)
                c0 = max(0, col - _TILE_PAD)
                c1 = min(w, col + _TILE_SIZE + _TILE_PAD)

                tile_in = rgb_f32[r0:r1, c0:c1]
                tile_out = self._inference_tile(tile_in)

                # Coordenadas de escrita no output (sem padding)
                or0 = row * scale
                or1 = or0 + min(_TILE_SIZE, h - row) * scale
                oc0 = col * scale
                oc1 = oc0 + min(_TILE_SIZE, w - col) * scale

                tr0 = (row - r0) * scale
                tc0 = (col - c0) * scale
                out_h = or1 - or0
                out_w = oc1 - oc0

                out[or0:or1, oc0:oc1] = tile_out[tr0:tr0 + out_h, tc0:tc0 + out_w]

        return out

    # ------------------------------------------------------------------
    # Diagnóstico
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Retorna informações sobre o backend SR atual."""
        return {
            'onnx_enabled': self._onnx_enabled,
            'onnx_loaded': self._session is not None,
            'model_path': self._model_path,
            'model_exists': os.path.exists(self._model_path),
            'backend': (
                'realesrgan_onnx'
                if self._session is not None
                else 'bicubic_fallback'
            ),
        }


# ---------------------------------------------------------------------------
# Singleton + API pública
# ---------------------------------------------------------------------------

_sr_model: Optional[SuperResolutionModel] = None


def get_sr_model() -> SuperResolutionModel:
    """Retorna instância singleton do modelo SR (lazy init)."""
    global _sr_model
    if _sr_model is None:
        _sr_model = SuperResolutionModel()
    return _sr_model


def apply_super_resolution(
    gray: np.ndarray,
    target_width: int = _SR_TARGET_WIDTH,
) -> np.ndarray:
    """
    API pública de super-resolução.

    Usa Real-ESRGAN ONNX se disponível; bicúbico caso contrário.
    Compatível com a interface de preprocessing._super_resolve().

    Args:
        gray: imagem grayscale uint8.
        target_width: largura mínima alvo (só usada pelo fallback bicúbico).

    Returns:
        np.ndarray grayscale uint8.
    """
    return get_sr_model().apply(gray, target_width)


def get_sr_info() -> dict:
    """Retorna dict de diagnóstico do backend SR atual."""
    return get_sr_model().info()
