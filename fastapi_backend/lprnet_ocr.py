"""
LPRNet OCR — Terceira fonte de reconhecimento de placa — Grom OCR

LPRNet é uma CNN end-to-end para leitura de placas sem segmentação
de caracteres (usa CTC loss). Muito mais rápido que PaddleOCR para
crops de placa e mais tolerante a rotações leves e blur moderado.

Referência: "Toward End-to-End Car License Plate Detection and Recognition
            with Deep Neural Networks" (He et al., 2018)
            https://arxiv.org/abs/1806.10447

Env vars:
  GROM_LPRNET_MODEL_PATH  caminho do modelo ONNX
                           (default: <projeto>/models/lprnet_mercosul.onnx)
  GROM_LPRNET_ENABLED     habilita/desabilita LPRNet (default: true)
  GROM_LPRNET_CONF_MIN    confiança mínima para incluir resultado (default: 0.40)

Formato de entrada ONNX (padrão LPRNet):
  [1, 3, 24, 94] float32, normalizado para [-0.5, 0.5]

Saída ONNX:
  [1, num_classes, seq_len] → decodificado via CTC greedy

Alfabeto Mercosul:
  Dígitos 0–9 + letras A–Z + blank CTC (-)
  Padrão antigo BR: ABC1234 (3 letras + 4 dígitos)
  Padrão Mercosul:  ABC1D23 (3 letras + 1 dígito + 1 letra + 2 dígitos)

Nota: o modelo ONNX precisa ser fornecido externamente.
  Para gerar um modelo compatível, consulte:
  https://github.com/sirius-ai/LPRNet_Pytorch
  Configure GROM_LPRNET_MODEL_PATH para apontar ao arquivo .onnx.
"""

import logging
import os
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, 'models', 'lprnet_mercosul.onnx')

# Alfabeto: dígitos + letras maiúsculas + blank CTC
_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-'
_BLANK_IDX = len(_CHARS) - 1  # '-' é o blank CTC

# Dimensões de entrada padrão LPRNet
_INPUT_H = 24
_INPUT_W = 94


def _is_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


# ---------------------------------------------------------------------------
# Pré-processamento
# ---------------------------------------------------------------------------

def _preprocess_plate(image_path: str) -> Optional[np.ndarray]:
    """
    Prepara imagem de placa para LPRNet.

    Passos:
      1. Carrega BGR com fallback Unicode (Windows)
      2. Redimensiona para 94×24 (LPRNet input)
      3. Converte para RGB float32 normalizado [-0.5, 0.5]
      4. Transpõe para [1, 3, 24, 94]

    Returns:
        np.ndarray [1, 3, 24, 94] float32 ou None se falhar.
    """
    # Carregamento com suporte a path Unicode no Windows
    img = None
    try:
        data = np.fromfile(image_path, dtype=np.uint8)
        if data.size > 0:
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        pass

    if img is None:
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)

    if img is None:
        logger.warning('LPRNet: falha ao carregar imagem: %s', image_path)
        return None

    resized = cv2.resize(img, (_INPUT_W, _INPUT_H), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - 0.5
    return rgb.transpose(2, 0, 1)[np.newaxis]  # [1, 3, 24, 94]


# ---------------------------------------------------------------------------
# Decodificação CTC
# ---------------------------------------------------------------------------

def _ctc_greedy_decode(logits: np.ndarray) -> tuple:
    """
    Decodificação CTC greedy.

    Args:
        logits: np.ndarray [1, num_classes, seq_len]

    Returns:
        (text: str, confidence: float)
        confidence é a média das probabilidades dos caracteres aceitos.
    """
    probs = logits[0]  # [num_classes, seq_len]

    # Softmax coluna por coluna
    exp_p = np.exp(probs - probs.max(axis=0, keepdims=True))
    softmax = exp_p / (exp_p.sum(axis=0, keepdims=True) + 1e-8)

    best_idxs = softmax.argmax(axis=0)   # [seq_len]
    best_probs = softmax.max(axis=0)     # [seq_len]

    # Colapsa repetições e remove blanks (CTC decoding)
    chars: List[str] = []
    confs: List[float] = []
    prev_idx = -1

    for idx, prob in zip(best_idxs, best_probs):
        if idx != _BLANK_IDX and idx != prev_idx:
            if 0 <= idx < len(_CHARS):
                chars.append(_CHARS[idx])
                confs.append(float(prob))
        prev_idx = int(idx)

    text = ''.join(chars)
    confidence = float(np.mean(confs)) if confs else 0.0
    return text, confidence


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class LPRNetOCR:
    """
    Wrapper lazy para ONNX LPRNet.

    Carrega o modelo apenas na primeira chamada a run().
    Se o modelo não existir, retorna lista vazia sem exceção.
    """

    def __init__(self, model_path: Optional[str] = None):
        self._model_path = (
            model_path
            or os.getenv('GROM_LPRNET_MODEL_PATH', _DEFAULT_MODEL_PATH)
        )
        self._session = None
        self._input_name: Optional[str] = None
        self._enabled = _is_enabled('GROM_LPRNET_ENABLED', default=True)
        self._conf_min = float(os.getenv('GROM_LPRNET_CONF_MIN', '0.40'))
        self._loaded: bool = False

    def _try_load(self) -> bool:
        """Carrega sessão ONNX. Retorna True se bem-sucedido."""
        if self._loaded:
            return self._session is not None
        self._loaded = True

        if not self._enabled:
            return False

        if not os.path.exists(self._model_path):
            logger.info(
                'LPRNet: modelo ausente em %s. '
                'Defina GROM_LPRNET_MODEL_PATH para habilitar.',
                self._model_path,
            )
            return False

        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=opts,
                providers=['CPUExecutionProvider'],
            )
            self._input_name = self._session.get_inputs()[0].name
            logger.info('LPRNet ONNX carregado: %s', self._model_path)
            return True
        except Exception as exc:
            logger.warning('Falha ao carregar LPRNet ONNX: %s', exc)
            return False

    @property
    def available(self) -> bool:
        if self._session is not None:
            return True
        return self._try_load()

    def run(self, image_path: str) -> List[dict]:
        """
        Executa inferência LPRNet em um crop de placa.

        Args:
            image_path: caminho do arquivo de imagem (crop da placa).

        Returns:
            Lista de {'text': str, 'confidence': float, 'engine': 'lprnet'}
            ou lista vazia se indisponível / confiança abaixo do mínimo.
        """
        if not self.available:
            return []

        try:
            inp = _preprocess_plate(image_path)
            if inp is None:
                return []

            logits = self._session.run(None, {self._input_name: inp})[0]
            text, conf = _ctc_greedy_decode(logits)

            if not text:
                logger.debug('LPRNet: texto vazio após decodificação.')
                return []

            if conf < self._conf_min:
                logger.debug(
                    'LPRNet: conf %.3f < min %.3f para "%s" — descartado.',
                    conf, self._conf_min, text,
                )
                return []

            logger.debug('LPRNet: "%s" conf=%.3f', text, conf)
            return [{'text': text, 'confidence': conf * 100.0, 'engine': 'lprnet'}]

        except Exception as exc:
            logger.warning('LPRNet inference falhou: %s', exc)
            return []

    def info(self) -> dict:
        return {
            'enabled': self._enabled,
            'available': self._session is not None,
            'model_path': self._model_path,
            'model_exists': os.path.exists(self._model_path),
            'conf_min': self._conf_min,
            'input_shape': [1, 3, _INPUT_H, _INPUT_W],
            'charset_size': len(_CHARS),
        }


# ---------------------------------------------------------------------------
# Singleton + API pública
# ---------------------------------------------------------------------------

_lprnet: Optional[LPRNetOCR] = None


def get_lprnet() -> LPRNetOCR:
    """Retorna instância singleton (lazy init)."""
    global _lprnet
    if _lprnet is None:
        _lprnet = LPRNetOCR()
    return _lprnet


def run_lprnet(image_path: str) -> List[dict]:
    """
    API pública. Executa LPRNet e retorna resultados.

    Retorna [] se modelo indisponível — sem exceção.
    """
    return get_lprnet().run(image_path)


def get_lprnet_info() -> dict:
    """Retorna dict de diagnóstico do backend LPRNet."""
    return get_lprnet().info()
