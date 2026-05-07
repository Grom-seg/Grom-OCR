"""
Testes para os 4 novos módulos:
  - frame_selector
  - super_resolution
  - lprnet_ocr
  - vehicle_analyzer

Todos os testes são unitários, sem chamadas de rede, sem modelos externos.
Módulos que exigem modelos ONNX/CLIP são testados via fallback gracioso.
"""

import os
import sys
import numpy as np
import pytest
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))


# ===========================================================================
# frame_selector
# ===========================================================================

class TestLapVariance:
    def test_sharp_image_returns_high_value(self):
        from fastapi_backend.frame_selector import lap_variance
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[::4, :] = 255
        img[:, ::4] = 255
        assert lap_variance(img) > 100.0

    def test_flat_image_returns_low_value(self):
        from fastapi_backend.frame_selector import lap_variance
        img = np.full((64, 64, 3), 128, dtype=np.uint8)
        assert lap_variance(img) < 10.0

    def test_grayscale_input(self):
        from fastapi_backend.frame_selector import lap_variance
        gray = np.random.randint(0, 256, (64, 64), dtype=np.uint8)
        score = lap_variance(gray)
        assert isinstance(score, float) and score >= 0.0

    def test_none_returns_zero(self):
        from fastapi_backend.frame_selector import lap_variance
        assert lap_variance(None) == 0.0

    def test_empty_returns_zero(self):
        from fastapi_backend.frame_selector import lap_variance
        assert lap_variance(np.array([])) == 0.0


class TestSelectBestFrame:
    def _frames(self):
        blurry = cv2.GaussianBlur(
            np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8), (15, 15), 0
        )
        sharp = np.zeros((64, 64, 3), dtype=np.uint8)
        sharp[::2, :] = 255
        return blurry, sharp

    def test_returns_sharpest_frame(self):
        from fastapi_backend.frame_selector import select_best_frame, lap_variance
        blurry, sharp = self._frames()
        result = select_best_frame([blurry, sharp])
        assert lap_variance(result) >= lap_variance(blurry)

    def test_single_frame(self):
        from fastapi_backend.frame_selector import select_best_frame
        frame = np.full((32, 32, 3), 200, dtype=np.uint8)
        assert select_best_frame([frame]).shape == frame.shape

    def test_empty_list_raises(self):
        from fastapi_backend.frame_selector import select_best_frame
        with pytest.raises(ValueError):
            select_best_frame([])

    def test_all_none_raises(self):
        from fastapi_backend.frame_selector import select_best_frame
        with pytest.raises(ValueError):
            select_best_frame([None, None])

    def test_ignores_none_frames(self):
        from fastapi_backend.frame_selector import select_best_frame
        frame = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = select_best_frame([None, frame, None])
        assert result.shape == frame.shape


class TestMergeHdr:
    def _frames(self, n=3):
        return [np.full((64, 64, 3), 80 + i * 50, dtype=np.uint8) for i in range(n)]

    def test_output_is_uint8(self):
        from fastapi_backend.frame_selector import merge_hdr
        assert merge_hdr(self._frames()).dtype == np.uint8

    def test_output_shape_preserved(self):
        from fastapi_backend.frame_selector import merge_hdr
        frames = self._frames()
        assert merge_hdr(frames).shape == frames[0].shape

    def test_single_frame_fallback(self):
        from fastapi_backend.frame_selector import merge_hdr
        frame = np.full((32, 32, 3), 150, dtype=np.uint8)
        result = merge_hdr([frame])
        assert result.dtype == np.uint8

    def test_two_frames(self):
        from fastapi_backend.frame_selector import merge_hdr
        result = merge_hdr(self._frames(2))
        assert result.dtype == np.uint8


class TestLoadFramesFromPaths:
    def test_loads_valid_images(self):
        import tempfile
        from fastapi_backend.frame_selector import load_frames_from_paths
        paths = []
        with tempfile.TemporaryDirectory(prefix='grom_test_') as tmpdir:
            for i in range(3):
                p = os.path.join(tmpdir, f'frame_{i}.jpg')
                cv2.imwrite(p, np.full((32, 32, 3), i * 80, dtype=np.uint8))
                paths.append(p)
            frames = load_frames_from_paths(paths)
        assert len(frames) == 3
        assert all(f is not None for f in frames)

    def test_missing_file_returns_none(self):
        from fastapi_backend.frame_selector import load_frames_from_paths
        result = load_frames_from_paths(['/tmp/grom_test_no_such_file_abc123.jpg'])
        assert result == [None]

    def test_empty_list(self):
        from fastapi_backend.frame_selector import load_frames_from_paths
        assert load_frames_from_paths([]) == []


# ===========================================================================
# super_resolution
# ===========================================================================

class TestBicubicFallback:
    def test_output_wider_than_input(self):
        from fastapi_backend.super_resolution import _bicubic_fallback
        gray = np.random.randint(0, 256, (32, 64), dtype=np.uint8)
        assert _bicubic_fallback(gray, 200).shape[1] > gray.shape[1]

    def test_output_is_uint8(self):
        from fastapi_backend.super_resolution import _bicubic_fallback
        gray = np.full((32, 64), 128, dtype=np.uint8)
        assert _bicubic_fallback(gray, 200).dtype == np.uint8

    def test_small_image(self):
        from fastapi_backend.super_resolution import _bicubic_fallback
        gray = np.random.randint(0, 256, (8, 16), dtype=np.uint8)
        out = _bicubic_fallback(gray, 100)
        assert out.shape[1] >= 16


class TestApplySuperResolution:
    def test_returns_ndarray(self):
        from fastapi_backend.super_resolution import apply_super_resolution
        gray = np.random.randint(0, 256, (32, 64), dtype=np.uint8)
        assert isinstance(apply_super_resolution(gray, 200), np.ndarray)

    def test_output_wider_or_equal(self):
        from fastapi_backend.super_resolution import apply_super_resolution
        gray = np.full((32, 64), 100, dtype=np.uint8)
        out = apply_super_resolution(gray, 200)
        assert out.shape[1] >= gray.shape[1]

    def test_output_uint8(self):
        from fastapi_backend.super_resolution import apply_super_resolution
        gray = np.random.randint(0, 256, (32, 64), dtype=np.uint8)
        assert apply_super_resolution(gray).dtype == np.uint8


class TestGetSrInfo:
    def test_returns_dict(self):
        from fastapi_backend.super_resolution import get_sr_info
        assert isinstance(get_sr_info(), dict)

    def test_has_backend_key(self):
        from fastapi_backend.super_resolution import get_sr_info
        assert 'backend' in get_sr_info()

    def test_backend_is_string(self):
        from fastapi_backend.super_resolution import get_sr_info
        assert isinstance(get_sr_info()['backend'], str)


# ===========================================================================
# lprnet_ocr
# ===========================================================================

class TestPreprocessPlate:
    def test_output_shape(self, tmp_path):
        from fastapi_backend.lprnet_ocr import _preprocess_plate
        p = str(tmp_path / 'plate.jpg')
        cv2.imwrite(p, np.full((24, 94, 3), 200, dtype=np.uint8))
        result = _preprocess_plate(p)
        if result is not None:
            assert result.shape == (1, 3, 24, 94)

    def test_returns_float32(self, tmp_path):
        from fastapi_backend.lprnet_ocr import _preprocess_plate
        p = str(tmp_path / 'plate.jpg')
        cv2.imwrite(p, np.full((24, 94, 3), 200, dtype=np.uint8))
        result = _preprocess_plate(p)
        if result is not None:
            assert result.dtype == np.float32

    def test_invalid_path_returns_none(self):
        from fastapi_backend.lprnet_ocr import _preprocess_plate
        assert _preprocess_plate('/nao/existe.jpg') is None


class TestCtcGreedyDecode:
    def test_blank_only_returns_empty(self):
        from fastapi_backend.lprnet_ocr import _ctc_greedy_decode
        # shape: [1, num_classes=37, seq_len=94]
        logits = np.full((1, 37, 94), -10.0)
        logits[0, 36, :] = 10.0  # blank (idx 36) domina em todos os frames
        text, conf = _ctc_greedy_decode(logits)
        assert text == ''

    def test_valid_decode_contains_char(self):
        from fastapi_backend.lprnet_ocr import _ctc_greedy_decode
        # shape: [1, num_classes=37, seq_len=15]
        logits = np.full((1, 37, 15), -10.0)
        logits[0, 0, :5] = 10.0   # '0' nos frames 0-4
        logits[0, 36, 5:10] = 10.0  # blank frames 5-9
        logits[0, 1, 10:15] = 10.0  # '1' frames 10-14
        text, conf = _ctc_greedy_decode(logits)
        assert '0' in text or '1' in text
        assert 0.0 <= conf <= 1.0

    def test_confidence_range(self):
        from fastapi_backend.lprnet_ocr import _ctc_greedy_decode
        logits = np.random.randn(1, 37, 20)  # [1, classes, seq]
        _, conf = _ctc_greedy_decode(logits)
        assert 0.0 <= conf <= 1.0


class TestGetLprnetInfo:
    def test_returns_dict(self):
        from fastapi_backend.lprnet_ocr import get_lprnet_info
        assert isinstance(get_lprnet_info(), dict)

    def test_has_enabled_key(self):
        from fastapi_backend.lprnet_ocr import get_lprnet_info
        assert 'enabled' in get_lprnet_info()

    def test_has_available_key(self):
        from fastapi_backend.lprnet_ocr import get_lprnet_info
        assert 'available' in get_lprnet_info()


class TestRunLprnet:
    def test_returns_list_when_model_absent(self, tmp_path):
        from fastapi_backend.lprnet_ocr import run_lprnet
        p = str(tmp_path / 'plate.jpg')
        cv2.imwrite(p, np.full((24, 94, 3), 200, dtype=np.uint8))
        assert isinstance(run_lprnet(p), list)

    def test_invalid_path_returns_empty(self):
        from fastapi_backend.lprnet_ocr import run_lprnet
        result = run_lprnet('/nao/existe.jpg')
        assert isinstance(result, list) and len(result) == 0


# ===========================================================================
# vehicle_analyzer
# ===========================================================================

class TestEstimateLightRegions:
    def test_returns_four_regions(self):
        from fastapi_backend.vehicle_analyzer import _estimate_light_regions
        r = _estimate_light_regions([100, 50, 400, 300], (600, 800))
        for k in ('headlight_left', 'headlight_right', 'taillight_left', 'taillight_right'):
            assert k in r

    def test_reliable_is_false(self):
        from fastapi_backend.vehicle_analyzer import _estimate_light_regions
        assert _estimate_light_regions([0, 0, 200, 100], (200, 300))['reliable'] is False

    def test_coords_within_vehicle_bbox(self):
        from fastapi_backend.vehicle_analyzer import _estimate_light_regions
        x1, y1, x2, y2 = 100, 50, 400, 300
        r = _estimate_light_regions([x1, y1, x2, y2], (600, 800))
        hl = r['headlight_left']
        assert x1 <= hl[0] and hl[2] <= x2
        assert y1 <= hl[1] and hl[3] <= y2


class TestMatchHeadlightTemplates:
    def test_no_dir_returns_empty(self):
        from fastapi_backend.vehicle_analyzer import _match_headlight_templates
        img = np.zeros((200, 400, 3), dtype=np.uint8)
        result = _match_headlight_templates(img, [0, 0, 100, 60])
        assert isinstance(result, list) and len(result) == 0

    def test_empty_roi_returns_empty(self, tmp_path):
        from fastapi_backend.vehicle_analyzer import _match_headlight_templates
        import os
        os.environ['GROM_VA_HEADLIGHT_TMPL'] = str(tmp_path)
        img = np.zeros((200, 400, 3), dtype=np.uint8)
        result = _match_headlight_templates(img, [0, 0, 0, 0])
        assert isinstance(result, list) and len(result) == 0
        del os.environ['GROM_VA_HEADLIGHT_TMPL']


class TestGetVehicleAnalyzerInfo:
    def test_returns_dict(self):
        from fastapi_backend.vehicle_analyzer import get_vehicle_analyzer_info
        assert isinstance(get_vehicle_analyzer_info(), dict)

    def test_has_expected_keys(self):
        from fastapi_backend.vehicle_analyzer import get_vehicle_analyzer_info
        info = get_vehicle_analyzer_info()
        for k in ('yolo_model', 'clip_enabled', 'make_prompts_count'):
            assert k in info

    def test_make_prompts_count_positive(self):
        from fastapi_backend.vehicle_analyzer import get_vehicle_analyzer_info
        assert get_vehicle_analyzer_info()['make_prompts_count'] > 0


class TestAnalyzeVehicle:
    def test_returns_dict(self, tmp_path):
        from fastapi_backend.vehicle_analyzer import analyze_vehicle
        p = str(tmp_path / 'car.jpg')
        cv2.imwrite(p, np.full((200, 400, 3), 128, dtype=np.uint8))
        assert isinstance(analyze_vehicle(p), dict)

    def test_has_vehicle_detections_key(self, tmp_path):
        from fastapi_backend.vehicle_analyzer import analyze_vehicle
        p = str(tmp_path / 'car.jpg')
        cv2.imwrite(p, np.full((200, 400, 3), 128, dtype=np.uint8))
        assert 'vehicle_detections' in analyze_vehicle(p)

    def test_has_clip_available_key(self, tmp_path):
        from fastapi_backend.vehicle_analyzer import analyze_vehicle
        p = str(tmp_path / 'car.jpg')
        cv2.imwrite(p, np.full((200, 400, 3), 128, dtype=np.uint8))
        assert 'clip_available' in analyze_vehicle(p)

    def test_invalid_path_returns_error(self):
        from fastapi_backend.vehicle_analyzer import analyze_vehicle
        assert 'error' in analyze_vehicle('/nao/existe.jpg')

    def test_detections_is_list(self, tmp_path):
        from fastapi_backend.vehicle_analyzer import analyze_vehicle
        p = str(tmp_path / 'car.jpg')
        cv2.imwrite(p, np.full((200, 400, 3), 128, dtype=np.uint8))
        assert isinstance(analyze_vehicle(p)['vehicle_detections'], list)
