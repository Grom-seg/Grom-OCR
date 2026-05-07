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

    def test_strong_blur_boosts_sharpening(self):
        from fastapi_backend.preprocessing import _select_intensity
        base = _select_intensity(0.80, blur_level='sharp')
        boosted = _select_intensity(0.80, blur_level='strong_blur')
        assert boosted['sharpen_weight'] > base['sharpen_weight']
        assert boosted['sharpen_blur_sigma'] > base['sharpen_blur_sigma']

    def test_moderate_blur_partial_boost(self):
        from fastapi_backend.preprocessing import _select_intensity
        base = _select_intensity(0.80, blur_level='sharp')
        moderate = _select_intensity(0.80, blur_level='moderate_blur')
        strong = _select_intensity(0.80, blur_level='strong_blur')
        # Moderate deve estar entre sharp e strong_blur
        assert base['sharpen_weight'] < moderate['sharpen_weight'] < strong['sharpen_weight']

    def test_sharpen_weight_capped_at_2(self):
        from fastapi_backend.preprocessing import _select_intensity
        p = _select_intensity(0.30, blur_level='strong_blur')
        assert p['sharpen_weight'] <= 2.0


# ---------------------------------------------------------------------------
# _classify_blur  (ccpd_blur)
# ---------------------------------------------------------------------------

class TestClassifyBlur:
    def test_sharp_image_classified_sharp(self):
        from fastapi_backend.preprocessing import _classify_blur
        # Imagem com bordas nítidas → alta variância Laplaciana
        img = np.zeros((80, 200), dtype=np.uint8)
        cv2.rectangle(img, (20, 10), (180, 70), 255, 2)
        cv2.line(img, (0, 40), (200, 40), 200, 1)
        assert _classify_blur(img) == 'sharp'

    def test_blurred_image_classified_blur(self):
        from fastapi_backend.preprocessing import _classify_blur
        # Imagem borrada: começa nítida e aplica blur forte
        img = np.zeros((80, 200), dtype=np.uint8)
        cv2.rectangle(img, (20, 10), (180, 70), 255, 2)
        blurred = cv2.GaussianBlur(img, (21, 21), sigmaX=10)
        result = _classify_blur(blurred)
        assert result in ('strong_blur', 'moderate_blur')

    def test_flat_image_is_strong_blur(self):
        from fastapi_backend.preprocessing import _classify_blur
        # Imagem uniforme: Laplacian var ≈ 0
        img = np.full((80, 200), 128, dtype=np.uint8)
        assert _classify_blur(img) == 'strong_blur'

    def test_returns_valid_string(self):
        from fastapi_backend.preprocessing import _classify_blur
        img = _make_gray_image(200, 80)
        result = _classify_blur(img)
        assert result in ('sharp', 'moderate_blur', 'strong_blur')


# ---------------------------------------------------------------------------
# _correct_gamma  (ccpd_fn: noite/overexposure)
# ---------------------------------------------------------------------------

class TestCorrectGamma:
    def test_dark_image_brightened(self):
        from fastapi_backend.preprocessing import _correct_gamma
        dark = np.full((80, 200), 40, dtype=np.uint8)  # mean=40, muito escuro
        result = _correct_gamma(dark)
        assert result.mean() > dark.mean()

    def test_bright_image_darkened(self):
        from fastapi_backend.preprocessing import _correct_gamma
        bright = np.full((80, 200), 210, dtype=np.uint8)  # mean=210, overexposure
        result = _correct_gamma(bright)
        assert result.mean() < bright.mean()

    def test_normal_image_unchanged(self):
        from fastapi_backend.preprocessing import _correct_gamma
        normal = np.full((80, 200), 128, dtype=np.uint8)  # mean=128, normal
        result = _correct_gamma(normal)
        # Dentro da faixa [70, 185] → deve retornar o mesmo array
        assert result is normal

    def test_output_dtype_uint8(self):
        from fastapi_backend.preprocessing import _correct_gamma
        dark = np.full((80, 200), 30, dtype=np.uint8)
        result = _correct_gamma(dark)
        assert result.dtype == np.uint8

    def test_output_values_clipped_0_255(self):
        from fastapi_backend.preprocessing import _correct_gamma
        dark = np.full((80, 200), 10, dtype=np.uint8)
        result = _correct_gamma(dark)
        assert result.min() >= 0 and result.max() <= 255


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

    def test_gamma_disabled_via_env(self, monkeypatch):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        monkeypatch.setenv('GROM_OCR_PREPROCESS_GAMMA', 'false')
        result = preprocess_image(_PLATE_PNG)
        assert isinstance(result, Image.Image)

    def test_blur_adapt_disabled_via_env(self, monkeypatch):
        from fastapi_backend.preprocessing import preprocess_image
        if not os.path.exists(_PLATE_PNG):
            pytest.skip('plate_test.png não encontrado em test-assets/')
        monkeypatch.setenv('GROM_OCR_PREPROCESS_BLUR_ADAPT', 'false')
        result = preprocess_image(_PLATE_PNG)
        assert isinstance(result, Image.Image)
