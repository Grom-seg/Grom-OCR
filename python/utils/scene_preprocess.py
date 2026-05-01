from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


from utils.pericial_labels import humanize_scene_label

# --- Advanced Preprocessing Variants ---
def apply_clahe(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    cl = clahe.apply(l)
    limg = cv2.merge((cl, a, b))
    return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

def apply_denoise(img):
    return cv2.fastNlMeansDenoisingColored(img, None, h=10, hColor=10, templateWindowSize=7, searchWindowSize=21)

def apply_bilateral(img):
    return cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)

def apply_deskew(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray > 0))
    if coords.shape[0] < 10:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = img.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

def apply_glare_removal(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 240, 255)
    result = cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)
    return result

try:
    from PIL import Image as PILImage, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    PILImage = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None


def parse_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value, default=False):
    if value is None:
        return bool(default)
    normalized = str(value).strip().lower()
    if normalized in ('1', 'true', 'yes', 'on', 'sim'):
        return True
    if normalized in ('0', 'false', 'no', 'off', 'nao'):
        return False
    return bool(default)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENE_PREPROCESS_ENABLED = parse_bool(os.environ.get('GROM_OCR_SCENE_PREPROCESS_ENABLE', '1'), True)
SCENE_PREPROCESS_BLEND = max(0.0, min(parse_float(os.environ.get('GROM_OCR_SCENE_PREPROCESS_BLEND'), 0.26), 0.65))
SCENE_PREPROCESS_CALIBRATION_PATH = (
    os.environ.get('GROM_OCR_SCENE_PREPROCESS_CALIBRATION_PATH')
    or str(PROJECT_ROOT / 'data' / 'scene_preprocess_calibration.json')
).strip()


def compute_scene_quality_metrics(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {
            'brightness': 0.0,
            'contrast': 0.0,
            'sharpness': 0.0,
            'noise': 0.0,
            'motion_blur_score': 0.0,
            'glare_score': 0.0,
            'saturation': 0.0,
            'edge_density': 0.0,
            'underexposed_ratio': 0.0,
            'overexposed_ratio': 0.0,
            'quality_score': 0.0,
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Forensic Blur/Glare Estimation
    motion_blur_score = 0.0
    if sharpness < 140.0:
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened_temp = cv2.filter2D(gray, -1, kernel)
        motion_blur_score = float(np.std(gray - sharpened_temp))

    glare_score = float(np.mean(gray >= 210) * 100.0)

    denoise_ref = cv2.GaussianBlur(gray, (3, 3), 0)
    noise = float(np.std(gray.astype(np.float32) - denoise_ref.astype(np.float32)))
    saturation = float(np.mean(hsv[:, :, 1]))
    edge_density = float(np.mean(cv2.Canny(gray, 70, 170) > 0) * 100.0)
    underexposed_ratio = float(np.mean(gray <= 15) * 100.0)
    overexposed_ratio = float(np.mean(gray >= 245) * 100.0)

    score = (
        min(28.0, contrast * 0.55)
        + min(26.0, sharpness / 10.0)
        + min(16.0, edge_density * 1.6)
        + min(14.0, saturation * 0.20)
        + min(16.0, max(0.0, 130.0 - abs(brightness - 138.0)) * 0.12)
    )
    if noise > 26.0:
        score -= min(16.0, (noise - 26.0) * 1.4)
    if underexposed_ratio > 8.0:
        score -= min(12.0, (underexposed_ratio - 8.0) * 0.35)
    if overexposed_ratio > 8.0:
        score -= min(14.0, (overexposed_ratio - 8.0) * 0.38)
    score = max(0.0, min(100.0, score))

    return {
        'brightness': round(brightness, 2),
        'contrast': round(contrast, 2),
        'sharpness': round(sharpness, 2),
        'noise': round(noise, 2),
        'saturation': round(saturation, 2),
        'edge_density': round(edge_density, 2),
        'underexposed_ratio': round(underexposed_ratio, 2),
        'overexposed_ratio': round(overexposed_ratio, 2),
        'motion_blur_score': round(motion_blur_score, 2),
        'glare_score': round(glare_score, 2),
        'quality_score': round(score, 2),
    }


def _scene_preprocess_default_calibration():
    return {
        'version': '2026-04-04',
        'source': 'builtin_default',
        'default_profile_name': 'balanced',
        'scenario_priority': ['dark', 'bright', 'low_contrast', 'foggy', 'adulterated_lighting', 'noisy', 'blurred', 'balanced'],
        'thresholds': {
            'dark_brightness': 92.0,
            'bright_brightness': 194.0,
            'low_contrast': 34.0,
            'foggy_contrast_max': 28.0,
            'foggy_saturation_max': 60.0,
            'noisy': 24.0,
            'blurred_sharpness': 160.0,
            'underexposed_ratio': 12.0,
            'overexposed_ratio': 12.0,
            'edge_weak': 1.8,
            'adulterated_edge_min': 2.0,
        },
        'profiles': {
            'balanced': {
                'quality_multiplier': 1.0,
                'quality_bias': 0.0,
                'distance_weight': 3.8,
                'original_margin': 0.8,
                'family_bonus': {'opencv': 0.1, 'pillow': 0.1, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_balance': 0.6,
                    'gray_world_clahe': 0.8,
                    'gray_world_equalize': 0.4,
                    'gray_world_gamma': 0.5,
                    'gray_world_sharpen': 0.7,
                    'gray_world_blend': 0.4,
                    'gray_world_blackhat': 0.2,
                    'gray_world_tophat': 0.2,
                    'gray_world_median': 0.2,
                    'gray_world_morph_close': 0.5,
                    'pillow_autocontrast': 0.8,
                    'pillow_detail': 0.2,
                    'pillow_sharpen': 0.5,
                    'pillow_unsharp': 0.7,
                    'pillow_edge_enhance': 0.4,
                },
            },
            'foggy': {
                'quality_multiplier': 1.08,
                'quality_bias': 0.8,
                'distance_weight': 3.5,
                'original_margin': 0.4,
                'family_bonus': {'opencv': 0.8, 'pillow': 0.2, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_dehaze': 3.5,
                    'gray_world_clahe': 1.5,
                    'gray_world_equalize': 1.2,
                    'gray_world_sharpen': 1.0,
                },
            },
            'adulterated_lighting': {
                'quality_multiplier': 1.05,
                'quality_bias': 0.6,
                'distance_weight': 3.4,
                'original_margin': 0.45,
                'family_bonus': {'opencv': 0.7, 'pillow': 0.3, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_adaptive_morph': 3.5,
                    'gray_world_tophat': 1.5,
                    'gray_world_blackhat': 1.5,
                    'gray_world_sharpen': 1.0,
                    'pillow_edge_enhance': 1.2,
                },
            },
            'dark': {
                'quality_multiplier': 1.04,
                'quality_bias': 0.5,
                'distance_weight': 3.1,
                'original_margin': 0.45,
                'family_bonus': {'opencv': 0.3, 'pillow': 0.6, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_balance': 1.3,
                    'gray_world_denoise': 1.4,
                    'gray_world_bilateral': 1.6,
                    'gray_world_clahe': 2.6,
                    'gray_world_equalize': 0.8,
                    'gray_world_gamma': 1.8,
                    'gray_world_sharpen': 1.0,
                    'gray_world_blend': 0.7,
                    'gray_world_blackhat': 0.6,
                    'gray_world_tophat': 0.4,
                    'gray_world_median': 1.0,
                    'pillow_autocontrast': 1.4,
                    'pillow_brightness_up': 2.8,
                    'pillow_contrast_up': 1.9,
                    'pillow_detail': 0.5,
                    'pillow_sharpen': 0.9,
                    'pillow_unsharp': 1.0,
                    'pillow_median': 1.2,
                },
            },
            'bright': {
                'quality_multiplier': 1.02,
                'quality_bias': 0.4,
                'distance_weight': 3.25,
                'original_margin': 0.55,
                'family_bonus': {'opencv': 0.5, 'pillow': 0.2, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_gamma': 1.4,
                    'gray_world_clahe': 1.2,
                    'gray_world_equalize': 1.7,
                    'gray_world_sharpen': 0.7,
                    'gray_world_blend': 0.5,
                    'gray_world_blackhat': 0.7,
                    'gray_world_tophat': 0.6,
                    'gray_world_median': 0.4,
                    'pillow_autocontrast': 1.5,
                    'pillow_brightness_down': 2.8,
                    'pillow_contrast_up': 0.5,
                    'pillow_detail': 0.2,
                    'pillow_unsharp': 0.4,
                },
            },
            'low_contrast': {
                'quality_multiplier': 1.05,
                'quality_bias': 0.7,
                'distance_weight': 3.4,
                'original_margin': 0.42,
                'family_bonus': {'opencv': 0.5, 'pillow': 0.4, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_clahe': 3.0,
                    'gray_world_balance': 1.0,
                    'gray_world_equalize': 2.3,
                    'gray_world_sharpen': 1.0,
                    'gray_world_blend': 0.9,
                    'gray_world_gamma': 1.1,
                    'gray_world_blackhat': 1.3,
                    'gray_world_tophat': 1.0,
                    'gray_world_median': 0.7,
                    'pillow_autocontrast': 2.5,
                    'pillow_equalize': 2.1,
                    'pillow_contrast_up': 2.2,
                    'pillow_detail': 0.7,
                    'pillow_unsharp': 0.8,
                },
            },
            'noisy': {
                'quality_multiplier': 1.03,
                'quality_bias': 0.5,
                'distance_weight': 3.2,
                'original_margin': 0.48,
                'family_bonus': {'opencv': 0.5, 'pillow': 0.5, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_denoise': 3.0,
                    'gray_world_bilateral': 2.8,
                    'gray_world_clahe': 1.2,
                    'gray_world_balance': 0.8,
                    'gray_world_equalize': 0.7,
                    'gray_world_sharpen': 0.4,
                    'gray_world_blackhat': 0.5,
                    'gray_world_tophat': 0.4,
                    'gray_world_median': 2.2,
                    'pillow_median': 2.5,
                    'pillow_autocontrast': 0.8,
                    'pillow_detail': 0.3,
                    'pillow_unsharp': 0.4,
                },
            },
            'blurred': {
                'quality_multiplier': 1.04,
                'quality_bias': 0.5,
                'distance_weight': 3.3,
                'original_margin': 0.5,
                'family_bonus': {'opencv': 0.4, 'pillow': 0.5, 'default': 0.0},
                'variant_prefix_bonus': {
                    'gray_world_sharpen': 2.9,
                    'gray_world_clahe': 1.1,
                    'gray_world_balance': 0.7,
                    'gray_world_blend': 0.8,
                    'gray_world_equalize': 0.8,
                    'gray_world_blackhat': 0.4,
                    'gray_world_tophat': 0.4,
                    'gray_world_median': 0.3,
                    'pillow_sharpen': 2.2,
                    'pillow_unsharp': 2.7,
                    'pillow_detail': 1.6,
                    'pillow_edge_enhance': 1.4,
                    'pillow_autocontrast': 0.8,
                },
            },
        },
    }


def _merge_scene_preprocess_dict(base, overlay):
    merged = dict(base or {})
    if not isinstance(overlay, dict):
        return merged

    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(value, dict):
            nested = dict(existing) if isinstance(existing, dict) else {}
            nested.update(value)
            merged[key] = nested
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _merge_scene_preprocess_calibration(base, overlay):
    merged = dict(base or {})
    if not isinstance(overlay, dict):
        return merged

    for key, value in overlay.items():
        if key in ('thresholds', 'profiles') and isinstance(value, dict):
            existing = merged.get(key, {})
            if not isinstance(existing, dict):
                existing = {}
            nested = dict(existing)
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, dict):
                    nested_existing = nested.get(nested_key, {})
                    if isinstance(nested_existing, dict):
                        nested[nested_key] = _merge_scene_preprocess_dict(nested_existing, nested_value)
                    else:
                        nested[nested_key] = dict(nested_value)
                elif isinstance(nested_value, list):
                    nested[nested_key] = list(nested_value)
                else:
                    nested[nested_key] = nested_value
            merged[key] = nested
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_scene_preprocess_dict(merged.get(key, {}), value)
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_scene_preprocess_calibration():
    calibration = _scene_preprocess_default_calibration()
    calibration['loaded_from'] = 'builtin_default'
    calibration['calibration_path'] = SCENE_PREPROCESS_CALIBRATION_PATH

    if not SCENE_PREPROCESS_CALIBRATION_PATH:
        return calibration

    if not os.path.exists(SCENE_PREPROCESS_CALIBRATION_PATH):
        calibration['load_error'] = 'calibration_file_not_found'
        return calibration

    try:
        with open(SCENE_PREPROCESS_CALIBRATION_PATH, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
    except Exception as exc:
        calibration['load_error'] = str(exc) or 'calibration_file_load_failed'
        return calibration

    if not isinstance(loaded, dict):
        calibration['load_error'] = 'calibration_file_invalid_format'
        return calibration

    merged = _merge_scene_preprocess_calibration(calibration, loaded)
    merged['loaded_from'] = 'file'
    merged['load_error'] = ''
    return merged


def _scene_preprocess_score_severity(metrics, thresholds, tag):
    brightness = float(metrics.get('brightness', 0.0))
    contrast = float(metrics.get('contrast', 0.0))
    sharpness = float(metrics.get('sharpness', 0.0))
    noise = float(metrics.get('noise', 0.0))
    underexposed_ratio = float(metrics.get('underexposed_ratio', 0.0))
    overexposed_ratio = float(metrics.get('overexposed_ratio', 0.0))

    if tag == 'dark':
        brightness_limit = float(thresholds.get('dark_brightness', 92.0))
        under_limit = float(thresholds.get('underexposed_ratio', 12.0))
        return max(0.0, (brightness_limit - brightness) * 0.9) + max(0.0, underexposed_ratio - under_limit) * 1.1
    if tag == 'bright':
        brightness_limit = float(thresholds.get('bright_brightness', 194.0))
        over_limit = float(thresholds.get('overexposed_ratio', 12.0))
        return max(0.0, brightness - brightness_limit) * 0.9 + max(0.0, overexposed_ratio - over_limit) * 1.1
    if tag == 'low_contrast':
        contrast_limit = float(thresholds.get('low_contrast', 34.0))
        return max(0.0, contrast_limit - contrast) * 1.3
    if tag == 'foggy':
        fog_limit = float(thresholds.get('foggy_contrast_max', 28.0))
        sat_limit = float(thresholds.get('foggy_saturation_max', 60.0))
        sat = float(metrics.get('saturation', 0.0))
        return max(0.0, fog_limit - contrast) * 1.5 + max(0.0, sat_limit - sat) * 1.0
    if tag == 'adulterated_lighting':
        return 1.2
    if tag == 'noisy':
        noisy_limit = float(thresholds.get('noisy', 24.0))
        return max(0.0, noise - noisy_limit) * 1.4
    if tag == 'blurred':
        blur_limit = float(thresholds.get('blurred_sharpness', 160.0))
        return max(0.0, blur_limit - sharpness) * 0.9
    return 0.0


def _classify_scene_preprocess(metrics, calibration=None):
    calibration = calibration or load_scene_preprocess_calibration()
    thresholds = calibration.get('thresholds', {})
    if not isinstance(thresholds, dict):
        thresholds = {}
    scenario_priority = calibration.get('scenario_priority', ['dark', 'bright', 'low_contrast', 'noisy', 'blurred', 'balanced'])
    if not isinstance(scenario_priority, list) or not scenario_priority:
        scenario_priority = ['dark', 'bright', 'low_contrast', 'noisy', 'blurred', 'balanced']

    candidate_tags = []
    reasons = []

    brightness = float(metrics.get('brightness', 0.0))
    contrast = float(metrics.get('contrast', 0.0))
    sharpness = float(metrics.get('sharpness', 0.0))
    noise = float(metrics.get('noise', 0.0))
    underexposed_ratio = float(metrics.get('underexposed_ratio', 0.0))
    overexposed_ratio = float(metrics.get('overexposed_ratio', 0.0))
    edge_density = float(metrics.get('edge_density', 0.0))

    dark_limit = float(thresholds.get('dark_brightness', 92.0))
    bright_limit = float(thresholds.get('bright_brightness', 194.0))
    low_contrast_limit = float(thresholds.get('low_contrast', 34.0))
    foggy_contrast_limit = float(thresholds.get('foggy_contrast_max', 28.0))
    foggy_saturation_limit = float(thresholds.get('foggy_saturation_max', 60.0))
    noisy_limit = float(thresholds.get('noisy', 24.0))
    blur_limit = float(thresholds.get('blurred_sharpness', 160.0))
    under_limit = float(thresholds.get('underexposed_ratio', 12.0))
    over_limit = float(thresholds.get('overexposed_ratio', 12.0))
    edge_weak_limit = float(thresholds.get('edge_weak', 1.8))
    adulterated_edge_min = float(thresholds.get('adulterated_edge_min', 2.0))
    saturation = float(metrics.get('saturation', 0.0))

    if contrast <= foggy_contrast_limit and saturation <= foggy_saturation_limit:
        candidate_tags.append('foggy')
        reasons.append('nevoa_ou_esbranquicado')
    if brightness <= dark_limit or underexposed_ratio >= under_limit:
        candidate_tags.append('dark')
        reasons.append('imagem_subexposta')
    if brightness >= bright_limit or overexposed_ratio >= over_limit:
        candidate_tags.append('bright')
        reasons.append('imagem_superexposta')
    if contrast <= low_contrast_limit and 'foggy' not in candidate_tags:
        candidate_tags.append('low_contrast')
        reasons.append('contraste_baixo')
    if noise >= noisy_limit:
        candidate_tags.append('noisy')
        reasons.append('ruido_elevado')
    if sharpness <= blur_limit:
        candidate_tags.append('blurred')
        reasons.append('baixa_nitidez')
    if edge_weak_limit < edge_density < adulterated_edge_min * 2.0 and noise > noisy_limit * 0.4:
        candidate_tags.append('adulterated_lighting')
        reasons.append('iluminacao_adulterada_ou_reflexo')
    if edge_density <= edge_weak_limit:
        candidate_tags.append('low_contrast')
        reasons.append('bordas_pouco_definidas')

    if not candidate_tags:
        candidate_tags = ['balanced']
        reasons.append('imagem_equilibrada')

    severity_map = {}
    for tag in candidate_tags:
        severity_map[tag] = _scene_preprocess_score_severity(metrics, thresholds, tag)

    tags_sorted = sorted(
        set(candidate_tags),
        key=lambda tag: (
            -float(severity_map.get(tag, 0.0)),
            scenario_priority.index(tag) if tag in scenario_priority else len(scenario_priority),
        ),
    )
    primary = tags_sorted[0] if tags_sorted else 'balanced'
    scenario_label = primary if len(tags_sorted) == 1 else '+'.join(tags_sorted)

    base_profile_name = str(calibration.get('default_profile_name', 'balanced'))
    profiles = calibration.get('profiles', {})
    if not isinstance(profiles, dict):
        profiles = {}
    base_profile = profiles.get(base_profile_name, profiles.get('balanced', {}))
    if not isinstance(base_profile, dict):
        base_profile = {}
    profile = _merge_scene_preprocess_dict(base_profile, {})
    for tag in tags_sorted:
        profile = _merge_scene_preprocess_dict(profile, profiles.get(tag, {}))

    return {
        'primary': primary,
        'label': scenario_label,
        'tags': tags_sorted,
        'reasons': reasons,
        'severity': severity_map,
        'profile': profile,
        'thresholds': thresholds,
        'calibration_version': str(calibration.get('version', 'builtin_default')),
        'calibration_source': str(calibration.get('loaded_from', 'builtin_default')),
        'calibration_path': str(calibration.get('calibration_path', SCENE_PREPROCESS_CALIBRATION_PATH)),
    }


def _scene_preprocess_variant_bonus(candidate_name, family, profile):
    bonus = 0.0
    matched_prefix = ''
    name = str(candidate_name or '').strip().lower()
    family_name = str(family or 'opencv').strip().lower()
    prefix_bonuses = profile.get('variant_prefix_bonus', {}) if isinstance(profile, dict) else {}
    if isinstance(prefix_bonuses, dict):
        for prefix, value in prefix_bonuses.items():
            prefix_text = str(prefix or '').strip().lower()
            if not prefix_text:
                continue
            if name.startswith(prefix_text) and len(prefix_text) >= len(matched_prefix):
                matched_prefix = prefix_text
                bonus = float(value)

    family_bonus = 0.0
    family_bonuses = profile.get('family_bonus', {}) if isinstance(profile, dict) else {}
    if isinstance(family_bonuses, dict):
        family_bonus = float(family_bonuses.get(family_name, family_bonuses.get('default', 0.0)) or 0.0)

    return round(bonus + family_bonus, 4), matched_prefix, round(family_bonus, 4)


def _score_scene_preprocess_candidate(entry, profile):
    metrics = entry.get('metrics', {})
    quality_score = float(metrics.get('quality_score', 0.0))
    distance = float(entry.get('distance', 0.0))
    quality_multiplier = float(profile.get('quality_multiplier', 1.0) if isinstance(profile, dict) else 1.0)
    quality_bias = float(profile.get('quality_bias', 0.0) if isinstance(profile, dict) else 0.0)
    distance_weight = float(profile.get('distance_weight', 3.8) if isinstance(profile, dict) else 3.8)
    variant_bonus, matched_prefix, family_bonus = _scene_preprocess_variant_bonus(entry.get('name', ''), entry.get('family', 'opencv'), profile)

    score = (quality_score * quality_multiplier) + quality_bias + variant_bonus - (distance * distance_weight)
    return score, {
        'quality_score': round(quality_score, 2),
        'quality_multiplier': round(quality_multiplier, 3),
        'quality_bias': round(quality_bias, 2),
        'distance_penalty': round(distance * distance_weight, 2),
        'variant_bonus': round(variant_bonus, 2),
        'family_bonus': round(family_bonus, 2),
        'matched_prefix': matched_prefix,
        'distance_weight': round(distance_weight, 2),
    }


def _gray_world_balance(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    source = img.astype(np.float32)
    channel_means = np.mean(source, axis=(0, 1))
    global_mean = float(np.mean(channel_means))
    balanced = np.zeros_like(source)
    for index, ch_mean in enumerate(channel_means):
        gain = global_mean / max(1.0, float(ch_mean))
        balanced[:, :, index] = source[:, :, index] * gain
    return np.clip(balanced, 0, 255).astype(np.uint8)


def _pillow_ready():
    return (
        PILImage is not None
        and ImageEnhance is not None
        and ImageFilter is not None
        and ImageOps is not None
    )


def _bgr_to_pillow_rgb(img):
    if not _pillow_ready() or img is None or getattr(img, 'size', 0) == 0:
        return None

    if len(img.shape) == 2:
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    try:
        return PILImage.fromarray(rgb)
    except Exception:
        return None


def _gray_to_pillow(img):
    if not _pillow_ready() or img is None or getattr(img, 'size', 0) == 0:
        return None

    if len(img.shape) == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    try:
        return PILImage.fromarray(gray)
    except Exception:
        return None


def _pillow_to_bgr(pil_img):
    if pil_img is None or PILImage is None:
        return None

    try:
        array = np.array(pil_img)
    except Exception:
        return None

    if array is None or getattr(array, 'size', 0) == 0:
        return None
    if array.ndim == 2:
        return cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    if array.shape[2] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_RGBA2RGB)
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def _pillow_to_gray(pil_img):
    if pil_img is None or PILImage is None:
        return None

    try:
        array = np.array(pil_img)
    except Exception:
        return None

    if array is None or getattr(array, 'size', 0) == 0:
        return None
    if array.ndim == 2:
        return array
    if array.shape[2] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_RGBA2RGB)
    return cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)


def _build_pillow_scene_variants(source_img):
    if not _pillow_ready() or source_img is None or getattr(source_img, 'size', 0) == 0:
        return []

    pil_img = _bgr_to_pillow_rgb(source_img)
    if pil_img is None:
        return []

    metrics = compute_scene_quality_metrics(source_img)
    brightness = float(metrics.get('brightness', 128.0))
    contrast = float(metrics.get('contrast', 0.0))
    noise = float(metrics.get('noise', 0.0))
    sharpness = float(metrics.get('sharpness', 0.0))

    candidates = []
    seen_signatures = set()

    def add_candidate(name, pil_variant, steps):
        candidate = _pillow_to_bgr(pil_variant)
        if candidate is None or getattr(candidate, 'size', 0) == 0:
            return
        signature = _scene_variant_signature(candidate)
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        candidates.append({
            'name': name,
            'image': candidate,
            'steps': list(steps),
            'metrics': compute_scene_quality_metrics(candidate),
            'distance': _scene_variant_distance_ratio(source_img, candidate),
            'family': 'pillow',
        })

    add_candidate('pillow_autocontrast', ImageOps.autocontrast(pil_img, cutoff=1), ['pillow_autocontrast'])
    add_candidate('pillow_equalize', ImageOps.equalize(pil_img), ['pillow_equalize'])
    add_candidate('pillow_detail', pil_img.filter(ImageFilter.DETAIL), ['pillow_detail'])
    add_candidate('pillow_sharpen', pil_img.filter(ImageFilter.SHARPEN), ['pillow_sharpen'])
    add_candidate('pillow_unsharp', pil_img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=170, threshold=2)), ['pillow_unsharp'])
    add_candidate('pillow_edge_enhance', pil_img.filter(ImageFilter.EDGE_ENHANCE_MORE), ['pillow_edge_enhance_more'])

    if contrast < 46.0:
        add_candidate(
            'pillow_contrast_up',
            ImageEnhance.Contrast(pil_img).enhance(1.42),
            ['pillow_contrast_up'],
        )
    if brightness < 112.0:
        add_candidate(
            'pillow_brightness_up',
            ImageEnhance.Brightness(pil_img).enhance(1.16),
            ['pillow_brightness_up'],
        )
    elif brightness > 188.0:
        add_candidate(
            'pillow_brightness_down',
            ImageEnhance.Brightness(pil_img).enhance(0.88),
            ['pillow_brightness_down'],
        )

    if noise > 24.0:
        add_candidate(
            'pillow_median',
            pil_img.filter(ImageFilter.MedianFilter(size=3)),
            ['pillow_median_3'],
        )

    if sharpness < 150.0:
        add_candidate(
            'pillow_sharpness_up',
            ImageEnhance.Sharpness(pil_img).enhance(1.45),
            ['pillow_sharpness_up'],
        )

    if not candidates:
        return []

    candidates.sort(
        key=lambda item: (
            float(item['metrics'].get('quality_score', 0.0)) - (float(item.get('distance', 0.0)) * 4.2),
            float(item['metrics'].get('quality_score', 0.0)),
        ),
        reverse=True,
    )
    return candidates


def _build_pillow_plate_variants(base_img):
    if not _pillow_ready() or base_img is None or getattr(base_img, 'size', 0) == 0:
        return []

    pil_img = _gray_to_pillow(base_img)
    if pil_img is None:
        return []

    if len(base_img.shape) == 2:
        gray = base_img
    else:
        gray = cv2.cvtColor(base_img, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    variants = []

    def add_variant(name, pil_variant):
        candidate = _pillow_to_gray(pil_variant)
        if candidate is None or getattr(candidate, 'size', 0) == 0:
            return
        variants.append((name, candidate))

    add_variant('pil_autocontrast', ImageOps.autocontrast(pil_img, cutoff=1))
    add_variant('pil_equalize', ImageOps.equalize(pil_img))
    add_variant('pil_sharpen', pil_img.filter(ImageFilter.SHARPEN))
    add_variant('pil_detail', pil_img.filter(ImageFilter.DETAIL))
    add_variant('pil_unsharp', pil_img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=2)))

    if contrast < 36.0:
        add_variant('pil_contrast_up', ImageEnhance.Contrast(pil_img).enhance(1.38))
    if brightness < 92.0:
        add_variant('pil_brightness_up', ImageEnhance.Brightness(pil_img).enhance(1.18))
    elif brightness > 196.0:
        add_variant('pil_brightness_down', ImageEnhance.Brightness(pil_img).enhance(0.88))

    if blur < 120.0:
        add_variant('pil_edge_enhance', pil_img.filter(ImageFilter.EDGE_ENHANCE_MORE))
    if blur < 90.0:
        add_variant('pil_median', pil_img.filter(ImageFilter.MedianFilter(size=3)))

    return variants


def _scene_variant_signature(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return None
    return (
        int(img.shape[0]),
        int(img.shape[1]),
        int(float(np.mean(img))),
        int(float(np.std(img))),
    )


def _scene_variant_distance_ratio(source_img, candidate_img):
    if source_img is None or candidate_img is None:
        return 0.0
    if getattr(source_img, 'size', 0) == 0 or getattr(candidate_img, 'size', 0) == 0:
        return 0.0
    if source_img.shape != candidate_img.shape:
        try:
            candidate_img = cv2.resize(
                candidate_img,
                (int(source_img.shape[1]), int(source_img.shape[0])),
                interpolation=cv2.INTER_AREA,
            )
        except Exception:
            return 0.0
    try:
        diff = cv2.absdiff(source_img, candidate_img)
    except Exception:
        return 0.0
    return float(np.mean(diff)) / 255.0

def _apply_wiener_filter(img, balance=0.015):
    """Forensic Wiener filter for motion deblurring in frequency domain."""
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    kernel_size = 5
    psf = np.ones((1, kernel_size)) / kernel_size
    psf_pad = np.zeros_like(gray)
    psf_pad[0, :kernel_size] = psf

    img_fft = np.fft.fft2(gray)
    psf_fft = np.fft.fft2(psf_pad)
    psf_fft_conj = np.conj(psf_fft)

    # Wiener deconvolução: G = H* / (|H|^2 + K)
    result_fft = img_fft * psf_fft_conj / (np.abs(psf_fft)**2 + balance)
    deblurred = np.abs(np.fft.ifft2(result_fft))
    deblurred = np.clip(deblurred * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(deblurred, cv2.COLOR_GRAY2BGR)

def _forensic_character_restoration(img):
    """Morphological restoration for eroded/washed-out character segments."""
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Top-hat to isolate characters
    kernel_7 = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel_7)

    # Adaptive thresholding to create mask
    mask = cv2.adaptiveThreshold(blackhat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, -2)

    # Dilation sequence to link segments
    kernel_link = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    restored_mask = cv2.dilate(mask, kernel_link, iterations=1)

    # Invert and apply back to original (deep forensic look)
    restored = cv2.addWeighted(gray, 0.7, cv2.bitwise_not(restored_mask), 0.3, 0)
    return cv2.cvtColor(restored, cv2.COLOR_GRAY2BGR)

def _apply_local_tone_mapping(img):
    """Local tone mapping for glare mitigation and detail recovery."""
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # Log-domain local normalization
    l_float = l.astype(np.float32) / 255.0
    l_log = np.log1p(l_float * 15.0) / np.log1p(15.0)
    l_mapped = (l_log * 255.0).astype(np.uint8)

    # Combine with sensitive CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(6, 6))
    l_final = clahe.apply(l_mapped)

    result = cv2.cvtColor(cv2.merge([l_final, a, b]), cv2.COLOR_LAB2BGR)
    return result


def _build_scene_preprocess_candidates(source_img):
    if source_img is None or getattr(source_img, 'size', 0) == 0:
        return []

    candidates = []
    seen_signatures = set()

    def add_candidate(name, candidate_img, steps, family='opencv'):
        if candidate_img is None or getattr(candidate_img, 'size', 0) == 0:
            return
        if len(candidate_img.shape) == 2:
            candidate = cv2.cvtColor(candidate_img, cv2.COLOR_GRAY2BGR)
        else:
            candidate = candidate_img.copy()
        signature = _scene_variant_signature(candidate)
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        candidates.append({
            'name': name,
            'image': candidate,
            'steps': list(steps),
            'metrics': compute_scene_quality_metrics(candidate),
            'distance': _scene_variant_distance_ratio(source_img, candidate),
            'family': family,
        })

    def add_entry(entry):
        if not isinstance(entry, dict):
            return
        candidate = entry.get('image')
        if candidate is None or getattr(candidate, 'size', 0) == 0:
            return
        if len(candidate.shape) == 2:
            candidate = cv2.cvtColor(candidate, cv2.COLOR_GRAY2BGR)
        else:
            candidate = candidate.copy()
        signature = _scene_variant_signature(candidate)
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        candidates.append({
            'name': str(entry.get('name', 'variant')),
            'image': candidate,
            'steps': list(entry.get('steps', [])) or ['software_mix'],
            'metrics': entry.get('metrics', compute_scene_quality_metrics(candidate)),
            'distance': float(entry.get('distance', _scene_variant_distance_ratio(source_img, candidate))),
            'family': str(entry.get('family', 'opencv')),
        })

    add_candidate('original', source_img.copy(), ['original'])
    # --- Advanced variants ---
    add_candidate('clahe', apply_clahe(source_img), ['clahe'])
    add_candidate('denoise_nlmeans', apply_denoise(source_img), ['denoise_nlmeans'])
    add_candidate('bilateral', apply_bilateral(source_img), ['bilateral'])
    add_candidate('deskew', apply_deskew(source_img), ['deskew'])
    add_candidate('glare_removal', apply_glare_removal(source_img), ['glare_removal'])

    balanced = _gray_world_balance(source_img)
    add_candidate('gray_world_balance', balanced, ['gray_world_balance'])

    metrics_after_balance = compute_scene_quality_metrics(balanced)
    denoise_strength = 0
    if float(metrics_after_balance.get('noise', 0.0)) >= 22.0:
        denoise_strength = 9
    elif float(metrics_after_balance.get('noise', 0.0)) >= 17.0:
        denoise_strength = 6

    if denoise_strength > 0:
        denoised = cv2.fastNlMeansDenoisingColored(
            balanced,
            None,
            h=denoise_strength,
            hColor=max(5, denoise_strength - 1),
            templateWindowSize=7,
            searchWindowSize=21,
        )
        add_candidate(
            f'gray_world_denoise_{denoise_strength}',
            denoised,
            ['gray_world_balance', f'denoise_colored_{denoise_strength}'],
        )
    else:
        denoised = balanced

    if float(metrics_after_balance.get('noise', 0.0)) >= 20.0:
        bilateral = cv2.bilateralFilter(denoised, 7, 45, 45)
        add_candidate(
            'gray_world_bilateral',
            bilateral,
            ['gray_world_balance', 'denoise_or_balanced', 'bilateral_filter_7'],
        )

    scene_brightness = float(metrics_after_balance.get('brightness', 128.0))
    scene_contrast = float(metrics_after_balance.get('contrast', 0.0))
    if scene_contrast < 44.0 or scene_brightness < 110.0 or scene_brightness > 184.0:
        ycrcb = cv2.cvtColor(denoised, cv2.COLOR_BGR2YCrCb)
        y_channel, cr_channel, cb_channel = cv2.split(ycrcb)
        equalized_y = cv2.equalizeHist(y_channel)
        equalized_img = cv2.cvtColor(cv2.merge([equalized_y, cr_channel, cb_channel]), cv2.COLOR_YCrCb2BGR)
        add_candidate(
            'gray_world_equalize',
            equalized_img,
            ['gray_world_balance', 'ycrcb_equalize'],
        )

    if float(metrics_after_balance.get('noise', 0.0)) >= 18.0:
        median_img = cv2.medianBlur(denoised, 3)
        add_candidate(
            'gray_world_median',
            median_img,
            ['gray_world_balance', 'median_blur_3'],
        )

    if scene_contrast < 40.0 or scene_brightness < 108.0 or scene_brightness > 186.0:
        scene_gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
        morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 5))
        blackhat = cv2.morphologyEx(scene_gray, cv2.MORPH_BLACKHAT, morph_kernel)
        blackhat = cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)
        add_candidate(
            'gray_world_blackhat',
            cv2.cvtColor(blackhat, cv2.COLOR_GRAY2BGR),
            ['gray_world_balance', 'scene_blackhat_11x5'],
        )
        tophat = cv2.morphologyEx(scene_gray, cv2.MORPH_TOPHAT, morph_kernel)
        tophat = cv2.normalize(tophat, None, 0, 255, cv2.NORM_MINMAX)
        add_candidate(
            'gray_world_tophat',
            cv2.cvtColor(tophat, cv2.COLOR_GRAY2BGR),
            ['gray_world_balance', 'scene_tophat_11x5'],
        )

    # Pseudo-Dehaze for fog and rain
    inv_denoised = cv2.bitwise_not(denoised)
    inv_lab = cv2.cvtColor(inv_denoised, cv2.COLOR_BGR2LAB)
    l_inv, a_inv, b_inv = cv2.split(inv_lab)
    l_inv = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(l_inv)
    inv_eq = cv2.cvtColor(cv2.merge([l_inv, a_inv, b_inv]), cv2.COLOR_LAB2BGR)
    dehaze_img = cv2.bitwise_not(inv_eq)
    dehaze_metrics = compute_scene_quality_metrics(dehaze_img)
    if dehaze_metrics.get('brightness', 128) < 90:
        dehaze_img = cv2.convertScaleAbs(dehaze_img, alpha=1.2, beta=20)
    add_candidate(
        'gray_world_dehaze',
        dehaze_img,
        ['gray_world_balance', 'pseudo_dehaze_clahe'],
    )

    # Morphological closing for eroded/worn characters
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    morph_close = cv2.morphologyEx(denoised, cv2.MORPH_CLOSE, kernel_close, iterations=1)
    add_candidate(
        'gray_world_morph_close',
        morph_close,
        ['gray_world_balance', 'morph_close_3x3'],
    )

    # Adaptive Morph for Character edges (Adulteration / washout)
    scene_gray_adlut = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
    kernel_rect = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    top_adlut = cv2.morphologyEx(scene_gray_adlut, cv2.MORPH_TOPHAT, kernel_rect)
    blur_adlut = cv2.GaussianBlur(denoised, (0, 0), 2.0)
    unsharp_adlut = cv2.addWeighted(denoised, 1.8, blur_adlut, -0.8, 0)
    hsv_adlut = cv2.cvtColor(unsharp_adlut, cv2.COLOR_BGR2HSV)
    h_a, s_a, v_a = cv2.split(hsv_adlut)
    v_a = cv2.add(v_a, top_adlut)
    morph_adulteration = cv2.cvtColor(cv2.merge([h_a, s_a, v_a]), cv2.COLOR_HSV2BGR)
    add_candidate(
        'gray_world_adaptive_morph',
        morph_adulteration,
        ['gray_world_balance', 'adulteration_morph_tophat_hsv'],
    )


    lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    contrast_for_clahe = float(metrics_after_balance.get('contrast', 0.0))
    clahe_clip = 2.2 if contrast_for_clahe < 36.0 else 1.8
    l_eq = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8)).apply(l_channel)
    clahe_img = cv2.cvtColor(cv2.merge([l_eq, a_channel, b_channel]), cv2.COLOR_LAB2BGR)
    add_candidate(
        f'gray_world_clahe_{clahe_clip:.1f}',
        clahe_img,
        ['gray_world_balance', f'clahe_{clahe_clip:.1f}'],
    )

    enhanced_metrics = compute_scene_quality_metrics(clahe_img)
    brightness = float(enhanced_metrics.get('brightness', 128.0))
    gamma = 1.0
    if brightness < 88.0:
        gamma = 0.84
    elif brightness < 110.0:
        gamma = 0.92
    elif brightness > 198.0:
        gamma = 1.18
    elif brightness > 176.0:
        gamma = 1.08

    gamma_img = clahe_img
    if abs(gamma - 1.0) >= 0.03:
        gamma_img = np.clip(((clahe_img / 255.0) ** gamma) * 255.0, 0, 255).astype(np.uint8)
    add_candidate(
        f'gray_world_gamma_{gamma:.2f}',
        gamma_img,
        ['gray_world_balance', f'clahe_{clahe_clip:.1f}', f'gamma_{gamma:.2f}'],
    )

    blur = cv2.GaussianBlur(gamma_img, (0, 0), 1.2)
    sharpened = cv2.addWeighted(gamma_img, 1.36, blur, -0.36, 0)
    add_candidate(
        'gray_world_sharpen',
        sharpened,
        ['gray_world_balance', f'clahe_{clahe_clip:.1f}', f'gamma_{gamma:.2f}', 'unsharp_mask'],
    )

    blend = max(0.0, min(0.65, float(SCENE_PREPROCESS_BLEND)))
    if blend > 0.0:
        blended = cv2.addWeighted(sharpened, 1.0 - blend, source_img, blend, 0)
        add_candidate(
            f'gray_world_blend_{blend:.2f}',
            blended,
            [
                'gray_world_balance',
                f'clahe_{clahe_clip:.1f}',
                f'gamma_{gamma:.2f}',
                'unsharp_mask',
                f'blend_original_{blend:.2f}',
            ],
        )

    for entry in _build_pillow_scene_variants(source_img):
        add_entry(entry)

    # Deep Forensic Pack (Triggered for high-aspect ratio or low-context crops)
    image_height, image_width = source_img.shape[:2]
    is_crop = (float(image_width) / max(1.0, float(image_height))) >= 2.0

    if is_crop:
        # Wiener Deblur for blurry crops
        if float(metrics_after_balance.get('sharpness', 200.0)) < 160.0:
            deblurred = _apply_wiener_filter(denoised)
            add_candidate('forensic_wiener_deblur', deblurred, ['gray_world_balance', 'wiener_deblur_5_015'])

        # Character Restoration for washed-out plates
        if float(metrics_after_balance.get('contrast', 50.0)) < 38.0:
            restored = _forensic_character_restoration(denoised)
            add_candidate('forensic_char_restoration', restored, ['gray_world_balance', 'morph_char_restoration'])

        # Tone Mapping for glare
        if float(metrics_after_balance.get('glare_score', 0.0)) > 5.0:
            toned = _apply_local_tone_mapping(denoised)
            add_candidate('forensic_local_tone_map', toned, ['gray_world_balance', 'log_tone_mapping'])

    candidates.sort(
        key=lambda item: (
            float(item['metrics'].get('quality_score', 0.0)) - (float(item.get('distance', 0.0)) * 3.8),
            float(item['metrics'].get('quality_score', 0.0)),
        ),
        reverse=True,
    )
    return candidates


def preprocess_scene_for_ocr(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return img, {
            'enabled': False,
            'applied': False,
            'selected': 'original',
            'reason': 'empty_scene',
            'quality_before': compute_scene_quality_metrics(img),
            'quality_after': compute_scene_quality_metrics(img),
            'improvement': 0.0,
            'steps': [],
            'scenario_display_label': humanize_scene_label('empty_scene'),
            'scene_profile': {
                'primary': 'balanced',
                'label': 'empty_scene',
                'display_label': humanize_scene_label('empty_scene'),
                'tags': [],
                'reasons': ['empty_scene'],
                'calibration_source': 'builtin_default',
                'calibration_version': 'builtin_default',
                'calibration_path': SCENE_PREPROCESS_CALIBRATION_PATH,
            },
        }

    if not SCENE_PREPROCESS_ENABLED:
        metrics = compute_scene_quality_metrics(img)
        return img, {
            'enabled': False,
            'applied': False,
            'selected': 'original',
            'reason': 'disabled_by_env',
            'quality_before': metrics,
            'quality_after': metrics,
            'improvement': 0.0,
            'steps': [],
            'scenario_display_label': humanize_scene_label('disabled'),
            'scene_profile': {
                'primary': 'balanced',
                'label': 'disabled',
                'display_label': humanize_scene_label('disabled'),
                'tags': [],
                'reasons': ['disabled_by_env'],
                'calibration_source': 'builtin_default',
                'calibration_version': 'builtin_default',
                'calibration_path': SCENE_PREPROCESS_CALIBRATION_PATH,
            },
        }

    quality_before = compute_scene_quality_metrics(img)
    source = img.copy()
    calibration = load_scene_preprocess_calibration()
    scene_profile = _classify_scene_preprocess(quality_before, calibration)
    if isinstance(scene_profile, dict):
        scene_profile = dict(scene_profile)
        scene_profile['display_label'] = humanize_scene_label(scene_profile.get('label', 'balanced'))
    candidates = _build_scene_preprocess_candidates(source)
    if not candidates:
        scene_profile_profile = scene_profile.get('profile', {}) if isinstance(scene_profile, dict) else {}
        return source, {
            'enabled': True,
            'applied': False,
            'selected': 'original',
            'selected_variant': 'original',
            'selected_family': 'opencv',
            'software_families': ['opencv'],
            'reason': 'no_scene_variants',
            'quality_before': quality_before,
            'quality_after': quality_before,
            'improvement': 0.0,
            'steps': ['original'],
            'candidate_count': 0,
            'ranked_variants': [],
            'scene_profile': scene_profile,
            'scenario_display_label': humanize_scene_label(scene_profile.get('label', 'balanced')),
            'scenario_label': scene_profile.get('label', 'balanced'),
            'scenario_primary': scene_profile.get('primary', 'balanced'),
            'scenario_tags': scene_profile.get('tags', []),
            'scenario_reasons': scene_profile.get('reasons', []),
            'calibration_source': scene_profile.get('calibration_source', 'builtin_default'),
            'calibration_version': scene_profile.get('calibration_version', 'builtin_default'),
            'calibration_path': scene_profile.get('calibration_path', SCENE_PREPROCESS_CALIBRATION_PATH),
            'selection_reason': 'no_scene_variants',
            'original_margin': float(scene_profile_profile.get('original_margin', 0.75)) if isinstance(scene_profile_profile, dict) else 0.75,
        }

    ranked_variants = []
    original_entry = None
    scene_profile_profile = dict(scene_profile.get('profile', {}) if isinstance(scene_profile, dict) else {})
    original_margin = float(scene_profile_profile.get('original_margin', 0.75)) if isinstance(scene_profile_profile, dict) else 0.75

    image_height, image_width = img.shape[:2]
    image_aspect_ratio = float(image_width) / float(max(1, image_height))
    plate_like_boost = 0.0
    if 2.1 <= image_aspect_ratio <= 6.8:
        scene_quality = float(quality_before.get('quality_score', 0.0))
        if scene_quality >= 92.0:
            plate_like_boost = 18.0
        elif scene_quality >= 85.0:
            plate_like_boost = 6.0
        elif scene_quality >= 70.0:
            plate_like_boost = 2.0
        elif scene_quality >= 55.0:
            plate_like_boost = 0.8
    if plate_like_boost > 0.0:
        original_margin = max(original_margin, plate_like_boost)
        scene_profile_profile['plate_like_input'] = True
        scene_profile_profile['plate_like_margin_boost'] = round(plate_like_boost, 2)
        scene_profile_profile['plate_like_aspect_ratio'] = round(image_aspect_ratio, 3)
        scene_profile_profile['original_margin'] = round(original_margin, 2)
        scene_profile_profile['selection_bias'] = 'plate_like_input'
        if isinstance(scene_profile, dict):
            reasons = scene_profile.get('reasons', [])
            if not isinstance(reasons, list):
                reasons = []
            if 'entrada_com_formato_de_placa' not in reasons:
                reasons = list(reasons) + ['entrada_com_formato_de_placa']
            scene_profile['reasons'] = reasons
            scene_profile['profile'] = scene_profile_profile
            scene_profile['display_label'] = humanize_scene_label(scene_profile.get('label', 'balanced'))

    for entry in candidates:
        final_score, score_details = _score_scene_preprocess_candidate(entry, scene_profile_profile)
        ranked_item = {
            'variant': entry['name'],
            'family': str(entry.get('family', 'opencv')),
            'quality_score': score_details.get('quality_score', 0.0),
            'distance_penalty': score_details.get('distance_penalty', 0.0),
            'variant_bonus': score_details.get('variant_bonus', 0.0),
            'family_bonus': score_details.get('family_bonus', 0.0),
            'matched_prefix': score_details.get('matched_prefix', ''),
            'quality_multiplier': score_details.get('quality_multiplier', 1.0),
            'quality_bias': score_details.get('quality_bias', 0.0),
            'distance_weight': score_details.get('distance_weight', 3.8),
            'score': round(final_score, 2),
        }
        ranked_variants.append(ranked_item)
        if entry['name'] == 'original':
            original_entry = {
                'entry': entry,
                'score': final_score,
            }

    ranked_variants.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)

    if not ranked_variants:
        best_entry = candidates[0] if candidates else {'name': 'original', 'image': source, 'metrics': quality_before}
        best_rank_score = 0.0
    else:
        best_variant_name = ranked_variants[0]['variant']
        best_entry = next((item for item in candidates if item['name'] == best_variant_name), candidates[0])
        best_rank_score = float(ranked_variants[0].get('score', 0.0))

    if original_entry is not None and best_rank_score < float(original_entry.get('score', 0.0)) + original_margin:
        best_entry = original_entry['entry']

    candidate = best_entry['image']
    quality_after = best_entry['metrics']
    selected_variant = best_entry['name']
    selected_family = str(best_entry.get('family', 'opencv'))
    selected = 'enhanced' if selected_variant != 'original' else 'original'
    improvement = float(quality_after.get('quality_score', 0.0)) - float(quality_before.get('quality_score', 0.0))
    software_families = sorted({str(item.get('family', 'opencv')) for item in candidates if isinstance(item, dict)})
    selected_score, selected_score_details = _score_scene_preprocess_candidate(best_entry, scene_profile_profile)
    original_score = float(original_entry.get('score', selected_score)) if original_entry is not None else float(selected_score)
    if selected_variant == 'original':
        selection_reason = 'scene_profile_kept_original'
        if original_entry is not None and best_rank_score < float(original_entry['score']) + original_margin:
            selection_reason = 'scene_profile_kept_original_by_margin'
    else:
        selection_reason = 'scene_profile_selected_variant'

    return candidate, {
        'enabled': True,
        'applied': True,
        'selected': selected,
        'selected_variant': selected_variant,
        'selected_family': selected_family,
        'software_families': software_families,
        'quality_before': quality_before,
        'quality_after': quality_after,
        'improvement': round(improvement, 2),
        'steps': best_entry.get('steps', ['original']),
        'candidate_count': len(candidates),
        'ranked_variants': ranked_variants[:5],
        'scene_profile': scene_profile,
        'scenario_display_label': humanize_scene_label(scene_profile.get('label', 'balanced')),
        'scenario_label': scene_profile.get('label', 'balanced'),
        'scenario_primary': scene_profile.get('primary', 'balanced'),
        'scenario_tags': scene_profile.get('tags', []),
        'scenario_reasons': scene_profile.get('reasons', []),
        'calibration_source': scene_profile.get('calibration_source', 'builtin_default'),
        'calibration_version': scene_profile.get('calibration_version', 'builtin_default'),
        'calibration_path': scene_profile.get('calibration_path', SCENE_PREPROCESS_CALIBRATION_PATH),
        'selection_reason': selection_reason,
        'selected_score': round(float(selected_score), 2),
        'selected_score_details': selected_score_details,
        'original_score': round(float(original_score), 2),
        'original_margin': round(float(original_margin), 2),
    }



