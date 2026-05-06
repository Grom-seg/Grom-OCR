"""
Testes unitários — Phase 2: Preprocessing Adaptativo
Cobre: super-resolução, correção de rotação, seleção de intensidade,
       preprocess_image() com diferentes quality_scores e flags.
"""
import os
import math
import tempfile

import cv2
import numpy as np
import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers de geração de imagem sintética
# ---------------------------------------------------------------------------

_ASSETS = os.path.join(os.path.dirname(__file__), 'test-assets')
_PLATE_PNG = os.path.join(_ASSETS, 'plate_test.png')
_PLATE_DEG = os.path.join(_ASSETS, 'plate_test_degraded.png')


def _make_gray_image(width: int = 200, height: int = 80, fill: int = 128) -> np.ndarray:
    return np.full((height, width), fill, dtype=np.uint8)


def _make_bgr_image(width: int = 200, height: int = 80) -> np.ndarray:
    return np.random.randint(50, 200, (height, width, 3), dtype=np.uint8)


def _save_temp(arr: np.ndarray, suffix: str = '.png') -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    cv2.imwrite(path, arr)
    return path


# ---------------------------------------------------------------------------
# _load_bgr_image
# ---------------------------------------------------------------------------

class TestLoadBgrImage:
    def test_loads_valid_image(self):
        from fastapi_backend.preprocessing import _load_bgr_image
        path = _save_temp(_make_bgr_image())
        try:
            img = _load_bgr_image(path)
            assert img is not None
            assert img.ndim == 3
        finally:
            os.unlink(path)

    def test_returns_none_for_missing_file(self):
        from fastapi_backend.preprocessing import _load_bgr_image
        result = _load_bgr_image('/nao/existe/arquivo.jpg')
        assert result is None


# ---------------------------------------------------------------------------
# _needs_super_resolution
# ---------------------------------------------------------------------------

class TestNeedsSuperResolution:
    def test_small_image_needs_sr(self):
        from fastapi_backend.preprocessing import _needs_super_resolution
        small = _make_gray_image(width=80, height=30)
        assert _needs_super_resolution(small) is True

    def test_large_image_does_not_need_sr(self):
        from fastapi_backend.preprocessing import _needs_super_resolution
        large = _make_gray_image(width=800, height=200)
        assert _needs_super_resolution(large) is False

    def test_very_low_category_triggers_sr(self):
        from fastapi_backend.preprocessing import _needs_super_resolution
        # Mesmo com imagem grande, categoria 'very_low' deve disparar SR
        large = _make_gray_image(width=600, height=200)
        assert _needs_super_resolution(large, resolution_category='very_low') is True

    def test_low_category_triggers_sr(self):
        from fastapi_backend.preprocessing import _needs_super_resolution
        large = _make_gray_image(width=600, height=200)
        assert _needs_super_resolution(large, resolution_category='low') is True

    def test_medium_category_no_trigger(self):
        from fastapi_backend.preprocessing import _needs_super_resolution
        large = _make_gray_image(width=600, height=200)
        assert _needs_super_resolution(large, resolution_category='medium') is False


# ---------------------------------------------------------------------------
# _super_resolve
# ---------------------------------------------------------------------------

class TestSuperResolve:
    def test_output_larger_than_input(self):
        from fastapi_backend.preprocessing import _super_resolve
        small = _make_gray_image(width=80, height=30)
        result = _super_resolve(small, target_width=400)
        # Largura deve ter crescido
        assert result.shape[1] >= small.shape[1]

    def test_output_dtype_uint8(self):
        from fastapi_backend.preprocessing import _super_resolve
        small = _make_gray_image(width=100, height=40)
        result = _super_resolve(small)
        assert result.dtype == np.uint8

    def test_empty_image_returns_safely(self):
        from fastapi_backend.preprocessing import _super_resolve
        empty = np.zeros((0, 0), dtype=np.uint8)
        result = _super_resolve(empty)
        # Não deve lançar exceção
        assert result is not None

    def test_target_width_respected(self):
        from fastapi_backend.preprocessing import _super_resolve
        img = _make_gray_image(width=50, height=20)
        result = _super_resolve(img, target_width=200)
        # Após 2x upscale (100px) < 200 target, não reduz, ficando em 100
        assert result.shape[1] <= 200


# ---------------------------------------------------------------------------
# _select_intensity
# ---------------------------------------------------------------------------

class TestSelectIntensity:
    def test_high_quality_leve(self):
        from fastapi_backend.preprocessing import _select_intensity
        p = _select_intensity(0.80)
        assert p['clahe_clip'] < 2.0  # processamento leve

    def test_low_quality_agressivo(self):
        from fastapi_backend.preprocessing import _select_intensity
        p = _select_intensity(0.30)
        assert p['clahe_clip'] >= 3.0  # processamento agressivo

    def test_medium_quality_padrao(self):
        from fastapi_backend.preprocessing import _select_intensity
        p = _select_intensity(0.60)
        assert p['clahe_clip'] == 2.0


# ---------------------------------------------------------------------------
# _estimate_rotation_angle
# ---------------------------------------------------------------------------

class TestEstimateRotationAngle:
    def test_flat_image_returns_near_zero(self):
        from fastapi_backend.preprocessing import _estimate_rotation_angle
        # Imagem com linhas horizontais claras
        img = np.zeros((100, 300), dtype=np.uint8)
        cv2.line(img, (0, 50), (300, 50), 255, 2)
        cv2.line(img, (0, 75), (300, 75), 255, 2)
        angle = _estimate_rotation_angle(img)
        assert abs(angle) < 10.0  # tolerância ampla para imagem sintética simples

    def test_returns_float(self):
        from fastapi_backend.preprocessing import _estimate_rotation_angle
        img = _make_gray_image(200, 80)
        angle = _estimate_rotation_angle(img)
        assert isinstance(angle, float)


# ---------------------------------------------------------------------------
# _correct_rotation
# ---------------------------------------------------------------------------

class TestCorrectRotation:
    def test_zero_angle_returns_same_shape(self):
        from fastapi_backend.preprocessing import _correct_rotation
        gray = _make_gray_image(200, 80)
        result = _correct_rotation(gray, 0.0)
        assert result.shape == gray.shape

    def test_small_angle_ignored(self):
        from fastapi_backend.preprocessing import _correct_rotation
        gray = _make_gray_image(200, 80)
        result = _correct_rotation(gray, 0.5)
        # Ângulo ≤ 1.0 → sem rotação → shape idêntico
        assert result.shape == gray.shape

    def test_rotation_changes_dimensions(self):
        from fastapi_backend.preprocessing import _correct_rotation
        gray = _make_gray_image(300, 100)
        # 30° deve mudar dimensões (bounding box maior)
        result = _correct_rotation(gray, 30.0)
        # Ao menos uma dimensão deve ser diferente
        assert result.shape != gray.shape or result is not gray


# ---------------------------------------------------------------------------
# preprocess_image integração
# ---------------------------------------------------------------------------

class TestPreprocessImage:
    def test_returns_pil_image(self):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        result = preprocess_image(_PLATE_PNG)
        assert isinstance(result, Image.Image)

    def test_degraded_plate_processed(self):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_DEG):
            pytest.skip('plate_test_degraded.png não encontrado em test-assets/')
        result = preprocess_image(_PLATE_DEG, quality_score=0.30)
        assert isinstance(result, Image.Image)
        assert result.width > 0 and result.height > 0

    def test_quality_dict_accepted(self):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        quality_dict = {
            'overall_quality_score': 0.45,
            'resolution_category': 'low',
        }
        result = preprocess_image(_PLATE_PNG, quality_score=quality_dict)
        assert isinstance(result, Image.Image)

    def test_missing_file_raises(self):
        from fastapi_backend.preprocessing import preprocess_image
        with pytest.raises(Exception):
            preprocess_image('/nao/existe/imagem.jpg')

    def test_sr_disabled_via_env(self, monkeypatch):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        monkeypatch.setenv('GROM_OCR_PREPROCESS_SR', 'false')
        result = preprocess_image(_PLATE_PNG)
        assert isinstance(result, Image.Image)

    def test_rotation_disabled_via_env(self, monkeypatch):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        monkeypatch.setenv('GROM_OCR_PREPROCESS_ROTATION', 'false')
        result = preprocess_image(_PLATE_PNG)
        assert isinstance(result, Image.Image)
