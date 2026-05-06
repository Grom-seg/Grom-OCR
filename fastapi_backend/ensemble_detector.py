"""
Ensemble Detector - Phase 3
Encadeia múltiplos detectores com NMS e fallback chain.

Estratégia:
1. Tenta YOLO como detector primário.
2. Se confiança máxima < threshold ou sem detecções, tenta detector
   de fallback baseado em contornos (sem dependência de modelo).
3. Funde resultados de múltiplos detectores via Non-Maximum Suppression.
"""
import logging
import os
from typing import List, Dict, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Threshold mínimo de confiança para aceitar detecção primária
_YOLO_CONF_THRESHOLD = float(os.getenv('GROM_ENSEMBLE_YOLO_THRESH', '0.30'))
# IoU threshold para NMS entre detectores
_NMS_IOU_THRESHOLD = float(os.getenv('GROM_ENSEMBLE_NMS_IOU', '0.45'))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_image(image_path: str) -> Optional[np.ndarray]:
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        data = np.fromfile(image_path, dtype=np.uint8)
        if data.size > 0:
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        pass
    return None


def _iou(box_a: List[int], box_b: List[int]) -> float:
    """Intersection over Union entre dois bounding boxes [x1,y1,x2,y2]."""
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])

    inter_w = max(0, xb - xa)
    inter_h = max(0, yb - ya)
    inter = inter_w * inter_h

    area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
    area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def _nms(detections: List[Dict], iou_threshold: float = _NMS_IOU_THRESHOLD) -> List[Dict]:
    """
    Non-Maximum Suppression sobre lista de detecções.
    Cada detecção: {'bbox': [x1,y1,x2,y2], 'confidence': float, 'source': str}
    """
    if not detections:
        return []

    detections = sorted(detections, key=lambda d: d['confidence'], reverse=True)
    kept = []

    for det in detections:
        suppressed = False
        for kept_det in kept:
            if _iou(det['bbox'], kept_det['bbox']) >= iou_threshold:
                suppressed = True
                break
        if not suppressed:
            kept.append(det)

    return kept


# ---------------------------------------------------------------------------
# Detector de fallback: contornos retangulares (sem modelo)
# ---------------------------------------------------------------------------

def _detect_by_contours(image_path: str) -> List[Dict]:
    """
    Detector baseado em contornos para imagens de placa recortada ou cena.
    Procura regiões retangulares com proporção de placa (~2:1 a ~6:1).
    Retorna confiança heurística (0.0 - 0.60).
    """
    img = _load_image(image_path)
    if img is None:
        return []

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < (h * w * 0.005):  # ignora ruído muito pequeno
            continue

        rect = cv2.boundingRect(cnt)
        rx, ry, rw, rh = rect
        if rh == 0:
            continue

        aspect = rw / rh
        if not (1.8 <= aspect <= 7.0):
            continue

        # Confiança heurística baseada em área relativa e proporção ideal (~4:1)
        area_ratio = (rw * rh) / (w * h)
        ideal_aspect_deviation = abs(aspect - 4.0) / 4.0
        conf = max(0.05, min(0.60, area_ratio * 5.0 - ideal_aspect_deviation * 0.2))

        candidates.append({
            'bbox': [rx, ry, rx + rw, ry + rh],
            'confidence': round(conf, 4),
            'source': 'contour',
        })

    # Retorna os 3 melhores candidatos
    candidates.sort(key=lambda d: d['confidence'], reverse=True)
    return candidates[:3]


# ---------------------------------------------------------------------------
# Detector YOLO (wrapper isolado)
# ---------------------------------------------------------------------------

def _detect_yolo(image_path: str) -> List[Dict]:
    """Tenta detecção via YOLO. Retorna [] se YOLO não disponível."""
    try:
        from fastapi_backend.detector_module import detect_plate
        results = detect_plate(image_path)
        for det in results:
            det.setdefault('source', 'yolo')
        return results
    except Exception as exc:
        logger.warning('YOLO falhou: %s', exc)
        return []


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def detect_ensemble(image_path: str) -> List[Dict]:
    """
    Detecção em ensemble com fallback automático.

    Fluxo:
    1. Tenta YOLO.
    2. Se max(conf) < threshold → ativa fallback por contornos.
    3. Funde todas as detecções via NMS.
    4. Retorna lista ordenada por confiança (decrescente).

    Returns:
        List of {'bbox': [x1,y1,x2,y2], 'confidence': float, 'source': str}
    """
    yolo_detections = _detect_yolo(image_path)
    max_yolo_conf = max((d['confidence'] for d in yolo_detections), default=0.0)

    all_detections = list(yolo_detections)
    used_fallback = False

    if max_yolo_conf < _YOLO_CONF_THRESHOLD:
        logger.debug(
            'YOLO conf=%.3f < threshold=%.3f → ativando fallback por contornos',
            max_yolo_conf, _YOLO_CONF_THRESHOLD,
        )
        contour_detections = _detect_by_contours(image_path)
        all_detections.extend(contour_detections)
        used_fallback = True

    result = _nms(all_detections)

    if result:
        logger.debug(
            'Ensemble: %d detecções (YOLO=%d, fallback=%s) → %d após NMS',
            len(all_detections), len(yolo_detections), used_fallback, len(result),
        )
    else:
        logger.debug('Ensemble: nenhuma detecção em %s', image_path)

    return result
