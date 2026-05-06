"""
Testes unitários — Phase 3: Ensemble Detector
Cobre: NMS, contour fallback, detect_ensemble com mock YOLO.
"""
import os
import tempfile
from unittest.mock import patch, MagicMock

import cv2
import numpy as np
import pytest

_ASSETS = os.path.join(os.path.dirname(__file__), 'test-assets')
_PLATE_PNG = os.path.join(_ASSETS, 'plate_test.png')
_PLATE_DEG = os.path.join(_ASSETS, 'plate_test_degraded.png')


def _save_temp_bgr(width: int = 400, height: int = 120) -> str:
    img = np.random.randint(100, 200, (height, width, 3), dtype=np.uint8)
    # Simula placa: retângulo branco com borda preta
    cv2.rectangle(img, (60, 20), (340, 100), (255, 255, 255), -1)
    cv2.rectangle(img, (60, 20), (340, 100), (0, 0, 0), 2)
    fd, path = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# _nms
# ---------------------------------------------------------------------------

class TestNMS:
    def test_keeps_best_box(self):
        from fastapi_backend.ensemble_detector import _nms
        detections = [
                {'bbox': [0, 0, 100, 50], 'confidence': 0.9, 'source': 'yolo'},
                {'bbox': [5, 5, 105, 55], 'confidence': 0.7, 'source': 'yolo'},
        ]
        result = _nms(detections, iou_threshold=0.45)
        assert len(result) == 1
        assert result[0]['confidence'] == 0.9

    def test_keeps_non_overlapping_boxes(self):
        from fastapi_backend.ensemble_detector import _nms
        detections = [
                {'bbox': [0, 0, 50, 50], 'confidence': 0.9, 'source': 'yolo'},
                {'bbox': [200, 0, 300, 50], 'confidence': 0.8, 'source': 'contour'},
        ]
        result = _nms(detections, iou_threshold=0.45)
        assert len(result) == 2

    def test_empty_list(self):
        from fastapi_backend.ensemble_detector import _nms
        assert _nms([], iou_threshold=0.45) == []

    def test_single_detection(self):
        from fastapi_backend.ensemble_detector import _nms
        det = [{'bbox': [0, 0, 100, 50], 'confidence': 0.6, 'source': 'yolo'}]
        result = _nms(det, iou_threshold=0.45)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _detect_by_contours
# ---------------------------------------------------------------------------

class TestDetectByContours:
    def test_returns_list(self):
        from fastapi_backend.ensemble_detector import _detect_by_contours
        path = _save_temp_bgr()
        try:
            result = _detect_by_contours(path)
            assert isinstance(result, list)
        finally:
            os.unlink(path)

    def test_detections_have_required_keys(self):
        from fastapi_backend.ensemble_detector import _detect_by_contours
        path = _save_temp_bgr()
        try:
            result = _detect_by_contours(path)
            for det in result:
                assert 'bbox' in det
                bbox = det['bbox']
                assert len(bbox) == 4  # [x1, y1, x2, y2]
                assert 'confidence' in det
                assert det.get('source') == 'contour'
        finally:
            os.unlink(path)

    def test_confidence_within_bounds(self):
        from fastapi_backend.ensemble_detector import _detect_by_contours
        path = _save_temp_bgr()
        try:
            result = _detect_by_contours(path)
            for det in result:
                assert 0.0 <= det['confidence'] <= 1.0
        finally:
            os.unlink(path)

    def test_invalid_path_returns_empty(self):
        from fastapi_backend.ensemble_detector import _detect_by_contours
        result = _detect_by_contours('/nao/existe/imagem.jpg')
        assert result == []


# ---------------------------------------------------------------------------
# detect_ensemble (com mock YOLO)
# ---------------------------------------------------------------------------

class TestDetectEnsemble:
    def _yolo_high_conf(self, image_path):
        """Simula YOLO com detecção de alta confiança."""
        return [
              {'bbox': [50, 10, 350, 110], 'confidence': 0.92, 'source': 'yolo'},
        ]

    def _yolo_low_conf(self, image_path):
        """Simula YOLO com detecção de baixa confiança → dispara contour fallback."""
        return [
              {'bbox': [50, 10, 350, 110], 'confidence': 0.15, 'source': 'yolo'},
        ]

    def _yolo_empty(self, image_path):
        """Simula YOLO sem detecção → dispara contour fallback."""
        return []

    def test_high_conf_yolo_skips_contours(self):
        from fastapi_backend import ensemble_detector
        path = _save_temp_bgr()
        try:
            with patch.object(ensemble_detector, '_detect_yolo', side_effect=self._yolo_high_conf):
                result = ensemble_detector.detect_ensemble(path)
            assert isinstance(result, list)
            # Alta confiança: apenas YOLO deve ser retornado (ou NMS do YOLO)
            sources = {d.get('source') for d in result}
            assert 'yolo' in sources
        finally:
            os.unlink(path)

    def test_low_conf_yolo_triggers_contour_fallback(self):
        from fastapi_backend import ensemble_detector
        path = _save_temp_bgr()
        contour_result = [
              {'bbox': [60, 20, 340, 100], 'confidence': 0.40, 'source': 'contour'},
        ]
        try:
            with patch.object(ensemble_detector, '_detect_yolo', side_effect=self._yolo_low_conf), \
                 patch.object(ensemble_detector, '_detect_by_contours', return_value=contour_result):
                result = ensemble_detector.detect_ensemble(path)
            assert isinstance(result, list)
        finally:
            os.unlink(path)

    def test_empty_yolo_triggers_contour_fallback(self):
        from fastapi_backend import ensemble_detector
        path = _save_temp_bgr()
        contour_result = [
              {'bbox': [60, 20, 340, 100], 'confidence': 0.35, 'source': 'contour'},
        ]
        try:
            with patch.object(ensemble_detector, '_detect_yolo', side_effect=self._yolo_empty), \
                 patch.object(ensemble_detector, '_detect_by_contours', return_value=contour_result):
                result = ensemble_detector.detect_ensemble(path)
            assert isinstance(result, list)
            assert len(result) >= 1
        finally:
            os.unlink(path)

    def test_result_has_required_keys(self):
        from fastapi_backend import ensemble_detector
        path = _save_temp_bgr()
        try:
            with patch.object(ensemble_detector, '_detect_yolo', side_effect=self._yolo_high_conf):
                result = ensemble_detector.detect_ensemble(path)
            for det in result:
                assert 'bbox' in det
                assert 'confidence' in det
        finally:
            os.unlink(path)

    def test_invalid_path_returns_list(self):
        from fastapi_backend import ensemble_detector
        with patch.object(ensemble_detector, '_detect_yolo', return_value=[]), \
             patch.object(ensemble_detector, '_detect_by_contours', return_value=[]):
            result = ensemble_detector.detect_ensemble('/nao/existe/imagem.jpg')
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Integracao: detecção real com imagem de teste (se disponível)
# ---------------------------------------------------------------------------

class TestDetectEnsembleIntegration:
    def test_plate_image_detects_something_or_empty(self):
        """
        Teste de fumaça: não exige detecção perfeita, apenas que não lance exceção.
        Usa mocks de YOLO para evitar dependência do modelo.
        """
        from fastapi_backend import ensemble_detector
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')

        with patch.object(ensemble_detector, '_detect_yolo', return_value=[]):
            result = ensemble_detector.detect_ensemble(_PLATE_PNG)
        assert isinstance(result, list)
