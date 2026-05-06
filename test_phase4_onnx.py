"""
Testes unitários — Phase 4: ONNX Exporter + Detector
Cobre: get_export_info, export_to_onnx (mock), OnnxDetector (com/sem modelo real),
       _postprocess_yolov8, benchmark estrutura, singleton get_onnx_detector.
"""
import os
import tempfile
from unittest.mock import patch, MagicMock

import cv2
import numpy as np
import pytest


def _save_temp_bgr(width: int = 400, height: int = 120) -> str:
    """Salva imagem BGR sintética em path sem caracteres Unicode."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(img, (60, 20), (340, 100), (255, 255, 255), -1)
    fd, path = tempfile.mkstemp(suffix='.png', dir=tempfile.gettempdir())
    os.close(fd)
    success, buf = cv2.imencode('.png', img)
    if not success:
        raise RuntimeError('imencode falhou')
    with open(path, 'wb') as f:
        f.write(buf.tobytes())
    return path


# ---------------------------------------------------------------------------
# onnx_exporter — get_export_info
# ---------------------------------------------------------------------------

class TestGetExportInfo:
    def test_missing_onnx_returns_error_dict(self):
        from fastapi_backend.onnx_exporter import get_export_info
        result = get_export_info('/nao/existe/modelo.onnx')
        assert isinstance(result, dict)
        assert 'error' in result

    def test_with_mock_onnx_model(self):
        from fastapi_backend.onnx_exporter import get_export_info

        fake_model = MagicMock()
        fake_model.opset_import = [MagicMock(version=17)]
        fake_graph = MagicMock()
        fake_input = MagicMock()
        fake_input.name = 'images'
        fake_input.type.tensor_type.shape.dim = [
            MagicMock(dim_value=1),
            MagicMock(dim_value=3),
            MagicMock(dim_value=640),
            MagicMock(dim_value=640),
        ]
        fake_output = MagicMock()
        fake_output.name = 'output0'
        fake_output.type.tensor_type.shape.dim = []
        fake_graph.input = [fake_input]
        fake_graph.output = [fake_output]
        fake_model.graph = fake_graph

        fd, onnx_path = tempfile.mkstemp(suffix='.onnx')
        os.close(fd)
        try:
            with open(onnx_path, 'wb') as f:
                f.write(b'\x00' * 1024)
            # onnx é importado localmente em get_export_info → patch em onnx diretamente
            with patch('onnx.load', return_value=fake_model):
                result = get_export_info(onnx_path)
            assert isinstance(result, dict)
            assert 'path' in result
            assert result['path'] == os.path.abspath(onnx_path)
        finally:
            os.unlink(onnx_path)



# ---------------------------------------------------------------------------
# onnx_exporter — export_to_onnx (smoke test com mock ultralytics)
# ---------------------------------------------------------------------------

class TestExportToOnnx:
    def test_missing_pt_raises_file_not_found(self):
        from fastapi_backend.onnx_exporter import export_to_onnx
        with pytest.raises(FileNotFoundError):
            export_to_onnx(pt_model_path='/nao/existe/modelo.pt')

    def test_export_calls_ultralytics_model(self):
        from fastapi_backend import onnx_exporter

        fd, fake_pt = tempfile.mkstemp(suffix='.pt')
        os.close(fd)
        fd2, fake_onnx = tempfile.mkstemp(suffix='.onnx')
        os.close(fd2)
        try:
            with open(fake_pt, 'wb') as f:
                f.write(b'\x00' * 64)
            mock_model = MagicMock()
            mock_model.export.return_value = fake_onnx
            # export_to_onnx importa YOLO localmente → patch em ultralytics.YOLO
            with patch('ultralytics.YOLO', return_value=mock_model):
                result = onnx_exporter.export_to_onnx(
                    pt_model_path=fake_pt,
                    output_path=fake_onnx,
                )
            mock_model.export.assert_called_once()
            assert isinstance(result, str)
        finally:
            for p in (fake_pt, fake_onnx):
                if os.path.exists(p):
                    os.unlink(p)


# ---------------------------------------------------------------------------
# onnx_detector — OnnxDetector sem modelo real
# ---------------------------------------------------------------------------

class TestOnnxDetector:
    def test_is_not_ready_without_model(self):
        from fastapi_backend.onnx_detector import OnnxDetector
        det = OnnxDetector(model_path='/nao/existe/modelo.onnx')
        assert not det.is_ready

    def test_detect_raises_without_model(self):
        """Sem modelo, detect() levanta FileNotFoundError."""
        from fastapi_backend.onnx_detector import OnnxDetector
        det = OnnxDetector(model_path='/nao/existe/modelo.onnx')
        with pytest.raises(FileNotFoundError):
            det.detect('/qualquer/imagem.jpg')

    def test_benchmark_raises_without_model(self):
        """Sem modelo, benchmark() levanta FileNotFoundError."""
        from fastapi_backend.onnx_detector import OnnxDetector
        det = OnnxDetector(model_path='/nao/existe/modelo.onnx')
        with pytest.raises(FileNotFoundError):
            det.benchmark('/qualquer/imagem.jpg', runs=5)

    def test_detect_with_mock_session(self):
        """Simula sessão ONNX para testar pipeline de pré/pós-processamento."""
        from fastapi_backend.onnx_detector import OnnxDetector

        # Usa helper que evita Unicode no path (cv2 no Windows)
        img_path = _save_temp_bgr(width=400, height=120)

        N = 100
        fake_output = np.zeros((1, 5, N), dtype=np.float32)
        fake_output[0, 0, 5] = 320.0
        fake_output[0, 1, 5] = 60.0
        fake_output[0, 2, 5] = 200.0
        fake_output[0, 3, 5] = 80.0
        fake_output[0, 4, 5] = 0.95

        mock_input = MagicMock()
        mock_input.name = 'images'
        mock_input.shape = [1, 3, 640, 640]
        mock_session = MagicMock()
        mock_session.run.return_value = [fake_output]
        mock_session.get_inputs.return_value = [mock_input]

        try:
            det = OnnxDetector(model_path='/fake/model.onnx')
            det._session = mock_session
            det._input_name = 'images'
            result = det.detect(img_path)
            assert isinstance(result, list)
        finally:
            os.unlink(img_path)


# ---------------------------------------------------------------------------
# _postprocess_yolov8 diretamente
# ---------------------------------------------------------------------------

class TestPostprocessYolov8:
    def test_no_detections_above_threshold(self):
        from fastapi_backend.onnx_detector import _postprocess_yolov8
        output = np.zeros((1, 5, 50), dtype=np.float32)
        result = _postprocess_yolov8(
            output,
            scale=1.0,
            pad=(0, 0),
            orig_w=640,
            orig_h=640,
            conf_threshold=0.50,
            iou_threshold=0.45,
        )
        assert result == []

    def test_one_valid_detection(self):
        from fastapi_backend.onnx_detector import _postprocess_yolov8
        output = np.zeros((1, 5, 50), dtype=np.float32)
        output[0, 0, 0] = 320.0
        output[0, 1, 0] = 320.0
        output[0, 2, 0] = 200.0
        output[0, 3, 0] = 100.0
        output[0, 4, 0] = 0.92
        result = _postprocess_yolov8(
            output,
            scale=1.0,
            pad=(0, 0),
            orig_w=640,
            orig_h=640,
            conf_threshold=0.50,
            iou_threshold=0.45,
        )
        assert len(result) == 1
        det = result[0]
        assert 'bbox' in det
        assert det['confidence'] > 0.5

    def test_result_format_has_source_onnx(self):
        from fastapi_backend.onnx_detector import _postprocess_yolov8
        output = np.zeros((1, 5, 10), dtype=np.float32)
        output[0, 0, 0] = 200.0
        output[0, 1, 0] = 200.0
        output[0, 2, 0] = 100.0
        output[0, 3, 0] = 50.0
        output[0, 4, 0] = 0.88
        result = _postprocess_yolov8(
            output,
            scale=1.0, pad=(0, 0),
            orig_w=400, orig_h=300,
            conf_threshold=0.5, iou_threshold=0.45,
        )
        if result:
            assert result[0].get('source') == 'onnx'


# ---------------------------------------------------------------------------
# get_onnx_detector — singleton
# ---------------------------------------------------------------------------

class TestGetOnnxDetectorSingleton:
    def test_returns_same_instance(self):
        from fastapi_backend import onnx_detector as mod
        # Reseta singleton para estado limpo
        mod._detector_instance = None
        with patch.dict(os.environ, {'GROM_ONNX_MODEL': '/fake/model.onnx'}):
            det1 = mod.get_onnx_detector()
            det2 = mod.get_onnx_detector()
        assert det1 is det2

    def test_instance_type(self):
        from fastapi_backend import onnx_detector as mod
        from fastapi_backend.onnx_detector import OnnxDetector
        mod._detector_instance = None
        with patch.dict(os.environ, {'GROM_ONNX_MODEL': '/fake/model.onnx'}):
            det = mod.get_onnx_detector()
        assert isinstance(det, OnnxDetector)


# ---------------------------------------------------------------------------
# benchmark_onnx — estrutura de resultado
# ---------------------------------------------------------------------------

class TestBenchmarkOnnxStructure:
    def test_format_report_smoke(self):
        from fastapi_backend.benchmark_onnx import format_report
        fake_result = {
            'image': 'test.jpg',
            'runs': 10,
            'yolo': {'avg_ms': 45.2, 'min_ms': 40.1, 'max_ms': 55.3, 'std_ms': 3.1},
            'onnx': {'avg_ms': 12.5, 'min_ms': 11.0, 'max_ms': 15.0, 'std_ms': 0.9},
            'speedup': 3.6,
            'winner': 'onnx',
            'error': None,
        }
        report = format_report(fake_result)
        assert isinstance(report, str)
        assert len(report) > 0
        assert 'onnx' in report.lower() or 'ONNX' in report

    def test_format_report_with_error(self):
        from fastapi_backend.benchmark_onnx import format_report
        fake_result = {
            'image': 'test.jpg',
            'runs': 10,
            'yolo': None,
            'onnx': None,
            'speedup': None,
            'winner': None,
            'error': 'Modelo ONNX não encontrado',
        }
        report = format_report(fake_result)
        assert isinstance(report, str)
