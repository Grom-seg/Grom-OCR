"""
ONNX Detector - Phase 4
Inferência de detecção de placas via ONNX Runtime.
Usa o mesmo modelo YOLOv8 exportado, com pós-processamento de bounding boxes.

Compatível com yolov8n.onnx exportado via ultralytics (formato output: [1, 84, N]).
"""
import logging
import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_ONNX_MODEL = os.getenv(
    'GROM_ONNX_MODEL',
    str(Path(os.getenv('GROM_YOLO_MODEL', 'yolov8n.pt')).with_suffix('.onnx')),
)
_DEFAULT_CONF_THRESHOLD = float(os.getenv('GROM_ONNX_CONF_THRESH', '0.25'))
_DEFAULT_IOU_THRESHOLD = float(os.getenv('GROM_ONNX_IOU_THRESH', '0.45'))
_DEFAULT_INPUT_SIZE = int(os.getenv('GROM_ONNX_INPUT_SIZE', '640'))


def _load_onnx_session(model_path: str):
    """Carrega sessão ONNX Runtime. Usa GPU (CUDA) se disponível, senão CPU."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ImportError('onnxruntime é necessário: pip install onnxruntime') from exc

    providers = ['CPUExecutionProvider']
    if 'CUDAExecutionProvider' in ort.get_available_providers():
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        logger.info('ONNX usando GPU (CUDA)')
    else:
        logger.debug('ONNX usando CPU')

    session = ort.InferenceSession(model_path, providers=providers)
    return session


def _preprocess_for_onnx(
    image_path: str,
    input_size: int = _DEFAULT_INPUT_SIZE,
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """
    Pré-processa imagem para inferência ONNX (letterbox + normalização).

    Returns:
        (blob, scale, (pad_w, pad_h))
        - blob: float32 [1, 3, H, W]
        - scale: fator de redimensionamento original/input
        - (pad_w, pad_h): padding adicionado
    """
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        try:
            data = np.fromfile(image_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        except Exception:
            pass
    if img is None:
        raise ValueError(f'Falha ao carregar imagem: {image_path}')

    orig_h, orig_w = img.shape[:2]

    # Letterbox: redimensiona mantendo aspect ratio com padding cinza
    scale = min(input_size / orig_w, input_size / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    pad_w = (input_size - new_w) // 2
    pad_h = (input_size - new_h) // 2
    padded = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
    padded[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized

    # Normaliza e transpõe para [1, C, H, W]
    blob = padded.astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[np.newaxis, ...]  # [1, 3, 640, 640]

    return blob, scale, (pad_w, pad_h)


def _postprocess_yolov8(
    output: np.ndarray,
    scale: float,
    pad: Tuple[int, int],
    orig_w: int,
    orig_h: int,
    conf_threshold: float,
    iou_threshold: float,
) -> List[Dict]:
    """
    Pós-processa saída YOLOv8 ONNX.
    Output YOLOv8: [1, 84, N] onde 84 = 4 bbox + 80 classes.
    """
    # Transpõe para [N, 84]
    preds = output[0].T  # [N, 84]

    boxes = preds[:, :4]        # cx, cy, w, h
    scores = preds[:, 4:]       # [N, 80]

    class_ids = np.argmax(scores, axis=1)
    confidences = scores[np.arange(len(scores)), class_ids]

    # Filtra por threshold
    mask = confidences >= conf_threshold
    boxes = boxes[mask]
    confidences = confidences[mask]

    if len(boxes) == 0:
        return []

    # Converte cx,cy,w,h → x1,y1,x2,y2 (em coordenadas do espaço letterboxed)
    pad_w, pad_h = pad
    x1 = boxes[:, 0] - boxes[:, 2] / 2 - pad_w
    y1 = boxes[:, 1] - boxes[:, 3] / 2 - pad_h
    x2 = boxes[:, 0] + boxes[:, 2] / 2 - pad_w
    y2 = boxes[:, 1] + boxes[:, 3] / 2 - pad_h

    # Escala de volta para coordenadas originais
    x1 = np.clip(x1 / scale, 0, orig_w).astype(int)
    y1 = np.clip(y1 / scale, 0, orig_h).astype(int)
    x2 = np.clip(x2 / scale, 0, orig_w).astype(int)
    y2 = np.clip(y2 / scale, 0, orig_h).astype(int)

    # NMS via OpenCV
    bboxes_for_nms = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1).tolist()
    indices = cv2.dnn.NMSBoxes(
        bboxes_for_nms,
        confidences.tolist(),
        conf_threshold,
        iou_threshold,
    )

    detections = []
    if len(indices) > 0:
        for i in indices.flatten():
            detections.append({
                'bbox': [int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])],
                'confidence': round(float(confidences[i]), 4),
                'source': 'onnx',
            })

    detections.sort(key=lambda d: d['confidence'], reverse=True)
    return detections


class OnnxDetector:
    """
    Detector de placas via ONNX Runtime.
    Lazy-loads o modelo na primeira chamada (thread-safe via lock).
    """

    def __init__(
        self,
        model_path: str = _DEFAULT_ONNX_MODEL,
        conf_threshold: float = _DEFAULT_CONF_THRESHOLD,
        iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
        input_size: int = _DEFAULT_INPUT_SIZE,
    ):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.input_size = input_size
        self._session = None
        self._input_name: Optional[str] = None

    def _ensure_session(self):
        if self._session is None:
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(
                    f'Modelo ONNX não encontrado: {self.model_path}. '
                    f'Execute: python -m fastapi_backend.onnx_exporter'
                )
            self._session = _load_onnx_session(self.model_path)
            self._input_name = self._session.get_inputs()[0].name
            logger.info('OnnxDetector carregado: %s', self.model_path)

    def detect(self, image_path: str) -> List[Dict]:
        """
        Detecta placas na imagem.

        Returns:
            List of {'bbox': [x1,y1,x2,y2], 'confidence': float, 'source': 'onnx'}

        Raises:
            FileNotFoundError: Se modelo ONNX não existir.
            ValueError: Se imagem não puder ser carregada.
        """
        self._ensure_session()

        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            try:
                data = np.fromfile(image_path, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            except Exception:
                pass
        if img is None:
            raise ValueError(f'Imagem não pôde ser carregada: {image_path}')

        orig_h, orig_w = img.shape[:2]

        blob, scale, pad = _preprocess_for_onnx(image_path, self.input_size)

        t0 = time.perf_counter()
        outputs = self._session.run(None, {self._input_name: blob})
        inference_ms = (time.perf_counter() - t0) * 1000

        logger.debug('ONNX inferência: %.1f ms', inference_ms)

        detections = _postprocess_yolov8(
            outputs[0],
            scale, pad,
            orig_w, orig_h,
            self.conf_threshold,
            self.iou_threshold,
        )

        return detections

    @property
    def is_ready(self) -> bool:
        """True se o modelo ONNX existir e puder ser carregado."""
        return os.path.exists(self.model_path)

    def benchmark(self, image_path: str, runs: int = 20) -> dict:
        """
        Mede latência média de inferência ONNX.

        Returns:
            {'runs': int, 'avg_ms': float, 'min_ms': float, 'max_ms': float}
        """
        self._ensure_session()

        blob, _, _ = _preprocess_for_onnx(image_path, self.input_size)
        times = []

        # Warm-up
        for _ in range(3):
            self._session.run(None, {self._input_name: blob})

        for _ in range(runs):
            t0 = time.perf_counter()
            self._session.run(None, {self._input_name: blob})
            times.append((time.perf_counter() - t0) * 1000)

        return {
            'runs': runs,
            'avg_ms': round(float(np.mean(times)), 2),
            'min_ms': round(float(np.min(times)), 2),
            'max_ms': round(float(np.max(times)), 2),
            'std_ms': round(float(np.std(times)), 2),
        }


# Instância global lazy (compartilhada pelo endpoint)
_onnx_detector: Optional[OnnxDetector] = None


def get_onnx_detector() -> OnnxDetector:
    """Retorna instância global do OnnxDetector (singleton lazy)."""
    global _onnx_detector
    if _onnx_detector is None:
        _onnx_detector = OnnxDetector()
    return _onnx_detector
