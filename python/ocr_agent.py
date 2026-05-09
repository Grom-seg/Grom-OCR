import os
import re
import math
import io
import shutil
import tempfile
import json
import hmac
import hashlib
import uuid
import time
import unicodedata
from difflib import SequenceMatcher
from collections import defaultdict, Counter
from datetime import datetime, timezone
from urllib.parse import quote_plus
from functools import lru_cache, wraps
import traceback

import cv2
import numpy as np
import pytesseract
import requests
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

EASYOCR_ENABLED = os.environ.get('GROM_OCR_ENABLE_EASYOCR', '1').strip().lower() in ('1', 'true', 'yes', 'on')

if EASYOCR_ENABLED:
    try:
        import easyocr
    except ImportError:
        easyocr = None
else:
    easyocr = None

RAPIDOCR_ENABLED = os.environ.get('GROM_OCR_ENABLE_RAPIDOCR', '1').strip().lower() in ('1', 'true', 'yes', 'on')
if RAPIDOCR_ENABLED:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        RapidOCR = None
else:
    RapidOCR = None

PDF_INPUT_ENABLED = os.environ.get('GROM_OCR_ENABLE_PDF_INPUT', '1').strip().lower() in ('1', 'true', 'yes', 'on')
if PDF_INPUT_ENABLED:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
else:
    pdfium = None

try:
    from PIL import Image as PILImage, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    PILImage = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

TROCR_ENABLED = os.environ.get('GROM_OCR_ENABLE_TROCR', '0').strip().lower() in ('1', 'true', 'yes', 'on')
if TROCR_ENABLED:
    try:
        import torch
        from PIL import Image
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError:
        torch = None
        Image = None
        TrOCRProcessor = None
        VisionEncoderDecoderModel = None
else:
    torch = None
    Image = None
    TrOCRProcessor = None
    VisionEncoderDecoderModel = None

DOCTR_ENABLED = os.environ.get('GROM_OCR_ENABLE_DOCTR', '0').strip().lower() in ('1', 'true', 'yes', 'on')
if DOCTR_ENABLED:
    try:
        from doctr.models import ocr_predictor
    except ImportError:
        ocr_predictor = None
else:
    ocr_predictor = None

PADDLEOCR_ENABLED = os.environ.get('GROM_OCR_ENABLE_PADDLEOCR', '0').strip().lower() in ('1', 'true', 'yes', 'on')
if PADDLEOCR_ENABLED:
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        PaddleOCR = None
else:
    PaddleOCR = None

YOLO_DETECTOR_ENABLED = os.environ.get('GROM_OCR_ENABLE_YOLO_DETECTOR', '1').strip().lower() in ('1', 'true', 'yes', 'on')
if YOLO_DETECTOR_ENABLED:
    try:
        from ultralytics import YOLO
    except ImportError:
        YOLO = None
else:
    YOLO = None
DEFAULT_YOLO_MODEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'models', 'yolov8n_plate.pt'))

from utils.photo_report import extract_exif, generate_pdf_report
from utils.scene_preprocess import (
    preprocess_scene_for_ocr,
)
from utils import ocr_reranking_calibration as ocr_reranking_calibration_module
from utils.investigation_report_pdf import generate_investigation_report
from utils.report_outline import get_analysis_report_outline
from utils import plate_detector_calibration as plate_detector_calibration_module
from utils import microcalibration as microcalibration_module
from utils import visual_reference_catalog as visual_reference_catalog_module
from utils import vehicle_analysis_protocol as vehicle_analysis_protocol_module
from utils import vehicle_confrontation_form as vehicle_confrontation_form_module
from utils.partial_plate import (
    build_partial_plate_candidates,
    build_partial_plate_overview,
)
from utils.evidence_manifest import (
    build_evidence_manifest,
    persist_evidence_manifest,
)
from utils.pipeline_telemetry import make_trace, get_telemetry_in_payload


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


PLATE_DETECTION_CALIBRATION_PATH = plate_detector_calibration_module.PLATE_DETECTION_CALIBRATION_PATH
PLATE_DETECTION_CALIBRATION = plate_detector_calibration_module.load_plate_detector_calibration()


def detector_calibration_lookup(*keys, default=None):
    current = PLATE_DETECTION_CALIBRATION
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if current is None:
        return default
    return current


OCR_RERANKING_CALIBRATION_PATH = ocr_reranking_calibration_module.OCR_RERANKING_CALIBRATION_PATH
OCR_RERANKING_CALIBRATION = ocr_reranking_calibration_module.load_ocr_reranking_calibration()


def ocr_reranking_calibration_lookup(*keys, default=None):
    current = OCR_RERANKING_CALIBRATION
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if current is None:
        return default
    return current


def ocr_reranking_calibration_info():
    runtime_policy = OCR_RERANKING_CALIBRATION.get('runtime_policy', {})
    if not isinstance(runtime_policy, dict):
        runtime_policy = {}
    return {
        'source': str(OCR_RERANKING_CALIBRATION.get('loaded_from', 'builtin_default')),
        'path': str(OCR_RERANKING_CALIBRATION.get('calibration_path', OCR_RERANKING_CALIBRATION_PATH)),
        'version': str(OCR_RERANKING_CALIBRATION.get('version', 'builtin_default')),
        'load_error': str(OCR_RERANKING_CALIBRATION.get('load_error', '')),
        'runtime_policy_applied': bool(OCR_RERANKING_CALIBRATION.get('runtime_policy_applied', False)),
        'runtime_policy_disabled_engines': [
            str(item)
            for item in runtime_policy.get('disabled_by_default_engines', [])
            if str(item).strip()
        ] if isinstance(runtime_policy.get('disabled_by_default_engines', []), (list, tuple, set)) else [],
    }


def ocr_ensemble_style_bias_profile():
    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        return {}
    style_bias = ensemble_profile.get('style_bias', {})
    if not isinstance(style_bias, dict):
        return {}
    return style_bias


def microcalibration_info():
    calibration = microcalibration_module.load_microcalibration()
    return {
        'source': str(calibration.get('loaded_from', 'builtin_default')),
        'path': str(calibration.get('calibration_path', microcalibration_module.MICROCALIBRATION_PATH)),
        'version': str(calibration.get('version', 'builtin_default')),
        'load_error': str(calibration.get('load_error', '')),
    }


def parse_rotation_angles():
    raw = os.environ.get('GROM_OCR_ROTATION_ANGLES', '0,-6,-3,3,6')
    angles = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            angles.append(float(token))
        except ValueError:
            continue

    if not angles:
        angles = [0.0, -4.0, 4.0]
    if all(abs(angle) > 0.001 for angle in angles):
        angles.insert(0, 0.0)
    return angles[:9]


def parse_psm_modes():
    raw = os.environ.get('GROM_OCR_TESSERACT_PSM_MODES', '7')
    modes = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if value < 3 or value > 13:
            continue
        if value not in modes:
            modes.append(value)

    if not modes:
        modes = [7]
    return modes[:4]


def parse_ensemble_weights():
    defaults = {
        'plate_recognizer': 1.20,
        'easyocr': 0.66,
        'rapidocr': 1.18,
        'tesseract': 0.48,
        'pdf_probe': 0.66,
        'paddleocr': 0.98,
        'trocr': 0.80,
        'doctr': 0.80,
        'geometry_refine': 1.04,
    }

    calibration_weights = ocr_reranking_calibration_lookup('ensemble_weights', default={})
    if isinstance(calibration_weights, dict):
        for name, value in calibration_weights.items():
            key = str(name or '').strip().lower()
            if not key:
                continue
            defaults[key] = max(0.1, min(parse_float(value, defaults.get(key, 1.0)), 3.0))

    raw = os.environ.get('GROM_OCR_ENSEMBLE_WEIGHTS', '').strip()
    if not raw:
        return defaults

    parsed = dict(defaults)
    for chunk in raw.split(','):
        if '=' not in chunk:
            continue
        name, value = chunk.split('=', 1)
        key = name.strip().lower()
        if not key:
            continue
        weight = parse_float(value.strip(), defaults.get(key, 1.0))
        parsed[key] = max(0.1, min(weight, 3.0))

    return parsed


PLATE_RECOGNIZER_TOKEN = os.environ.get('PLATE_RECOGNIZER_TOKEN')
PLATE_RECOGNIZER_TIMEOUT = parse_float(os.environ.get('PLATE_RECOGNIZER_TIMEOUT'), 15.0)
PLATE_RECOGNIZER_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_PLATE_RECOGNIZER_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
PLATE_RECOGNIZER_MAX_VARIANTS = max(1, min(parse_int(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_MAX_VARIANTS'), 3), 6))
PLATE_RECOGNIZER_TOP_RESULTS = max(1, min(parse_int(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_TOP_RESULTS'), 2), 5))
PLATE_RECOGNIZER_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_HIT_BONUS'), 1.8)
PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS'), 2.4)
PLATE_RECOGNIZER_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_SCORE'), 54.0)
PLATE_RECOGNIZER_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_MIN_ACCEPT_CONF'), 58.0)
PLATE_RECOGNIZER_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_PATTERN_MIN_SCORE'), 66.0)
PLATE_RECOGNIZER_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_PLATE_RECOGNIZER_MIN_VARIANT_HITS'), 2), 6))
OCR_MIN_CONFIDENCE = parse_float(os.environ.get('GROM_OCR_MIN_CONFIDENCE'), 75.0)
OCR_PATTERN_MIN_CONFIDENCE = parse_float(os.environ.get('GROM_OCR_PATTERN_MIN_CONFIDENCE'), 45.0)
PLATE_DETECTION_ASPECT_TARGET = max(
    3.4,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_DETECTION_ASPECT_TARGET'),
            parse_float(detector_calibration_lookup('thresholds', 'aspect_target', default=4.2), 4.2),
        ),
        5.6,
    ),
)
PLATE_DETECTION_ASPECT_MIN = max(
    0.8,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_DETECTION_ASPECT_MIN'),
            parse_float(detector_calibration_lookup('thresholds', 'aspect_min', default=0.8), 0.8),
        ),
        4.0,
    ),
)
PLATE_DETECTION_QUALITY_ASPECT_MIN = max(
    0.8,
    min(
        parse_float(
            detector_calibration_lookup('quality', 'aspect_min', default=1.5),
            1.5,
        ),
        4.0,
    ),
)
PLATE_DETECTION_ASPECT_MAX = max(
    PLATE_DETECTION_ASPECT_MIN,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_DETECTION_ASPECT_MAX'),
            parse_float(detector_calibration_lookup('thresholds', 'aspect_max', default=9.2), 9.2),
        ),
        12.0,
    ),
)
PLATE_DETECTION_AREA_MIN_RATIO = max(
    0.0008,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_DETECTION_AREA_MIN_RATIO'),
            parse_float(detector_calibration_lookup('thresholds', 'area_min_ratio', default=0.0018), 0.0018),
        ),
        0.02,
    ),
)
PLATE_DETECTION_AREA_MAX_RATIO = max(
    PLATE_DETECTION_AREA_MIN_RATIO,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_DETECTION_AREA_MAX_RATIO'),
            parse_float(detector_calibration_lookup('thresholds', 'area_max_ratio', default=0.42), 0.42),
        ),
        0.8,
    ),
)
PLATE_DETECTION_MIN_IMAGE_WIDTH = max(
    32,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_DETECTION_MIN_IMAGE_WIDTH'),
            parse_int(detector_calibration_lookup('thresholds', 'min_image_width', default=64), 64),
        ),
        240,
    ),
)
PLATE_DETECTION_MIN_IMAGE_HEIGHT = max(
    24,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_DETECTION_MIN_IMAGE_HEIGHT'),
            parse_int(detector_calibration_lookup('thresholds', 'min_image_height', default=32), 32),
        ),
        200,
    ),
)
PLATE_DETECTION_MIN_BOX_WIDTH = max(
    32,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_DETECTION_MIN_BOX_WIDTH'),
            parse_int(detector_calibration_lookup('thresholds', 'min_box_width', default=34), 34),
        ),
        120,
    ),
)
PLATE_DETECTION_MIN_BOX_HEIGHT = max(
    14,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_DETECTION_MIN_BOX_HEIGHT'),
            parse_int(detector_calibration_lookup('thresholds', 'min_box_height', default=14), 14),
        ),
        80,
    ),
)
PLATE_CROP_PAD_RATIO = max(
    0.03,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_CROP_PAD_RATIO'),
            parse_float(detector_calibration_lookup('crop', 'pad_ratio', default=0.08), 0.08),
        ),
        0.18,
    ),
)
PLATE_CROP_PAD_RATIO_SMALL = max(
    0.0,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_CROP_PAD_RATIO_SMALL'),
            parse_float(detector_calibration_lookup('crop', 'pad_ratio_small', default=0.05), 0.05),
        ),
        0.14,
    ),
)
PLATE_CROP_PAD_RATIO_LARGE = max(
    -0.04,
    min(
        parse_float(
            os.environ.get('GROM_OCR_PLATE_CROP_PAD_RATIO_LARGE'),
            parse_float(detector_calibration_lookup('crop', 'pad_ratio_large', default=-0.02), -0.02),
        ),
        0.06,
    ),
)
PLATE_CROP_MIN_WIDTH = max(
    48,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_CROP_MIN_WIDTH'),
            parse_int(detector_calibration_lookup('crop', 'min_width', default=58), 58),
        ),
        180,
    ),
)
PLATE_CROP_MIN_HEIGHT = max(
    16,
    min(
        parse_int(
            os.environ.get('GROM_OCR_PLATE_CROP_MIN_HEIGHT'),
            parse_int(detector_calibration_lookup('crop', 'min_height', default=18), 18),
        ),
        80,
    ),
)
CAPTURE_INTEGRITY_REVIEW_THRESHOLD = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_REVIEW_THRESHOLD'), 68.0), 100.0))
CAPTURE_INTEGRITY_CRITICAL_THRESHOLD = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_CRITICAL_THRESHOLD'), 52.0), 100.0))
CAPTURE_INTEGRITY_INPUT_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_INPUT_PENALTY'), 12.0), 50.0))
CAPTURE_INTEGRITY_SIGNATURE_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_SIGNATURE_PENALTY'), 30.0), 50.0))
CAPTURE_INTEGRITY_FALLBACK_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_FALLBACK_PENALTY'), 18.0), 40.0))
CAPTURE_INTEGRITY_FULL_IMAGE_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_FULL_IMAGE_PENALTY'), 18.0), 30.0))
CAPTURE_INTEGRITY_SEM_CANDIDATE_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_SEM_CANDIDATE_PENALTY'), 32.0), 50.0))
CAPTURE_INTEGRITY_LOW_CANDIDATE_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_LOW_CANDIDATE_PENALTY'), 12.0), 20.0))
CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD'), 55.0), 100.0))
CAPTURE_INTEGRITY_LOW_QUALITY_MAX_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_LOW_QUALITY_MAX_PENALTY'), 28.0), 40.0))
CAPTURE_INTEGRITY_WARNING_PENALTY = max(0.0, min(parse_float(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_WARNING_PENALTY'), 5.0), 15.0))
CAPTURE_INTEGRITY_WARNING_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_WARNING_LIMIT'), 3), 8))
CAPTURE_INTEGRITY_FALLBACK_ALWAYS_REVIEW = parse_bool(os.environ.get('GROM_OCR_CAPTURE_INTEGRITY_FALLBACK_ALWAYS_REVIEW', '0'), False)
FULL_IMAGE_SELECTION_MARGIN = max(0.0, min(parse_float(os.environ.get('GROM_OCR_PLATE_DETECTION_FULL_IMAGE_SELECTION_MARGIN'), 8.0), 20.0))
FORCE_ENSEMBLE = os.environ.get('GROM_OCR_FORCE_ENSEMBLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
CHAIN_SIGNING_KEY = os.environ.get('GROM_OCR_CHAIN_SIGNING_KEY', '').strip()
ENSEMBLE_TOP_PER_ENGINE = parse_int(os.environ.get('GROM_OCR_ENSEMBLE_TOP_PER_ENGINE'), 8)
ENSEMBLE_WEIGHTS = parse_ensemble_weights()
MAX_REGION_CANDIDATES = max(1, min(parse_int(os.environ.get('GROM_OCR_MAX_REGION_CANDIDATES'), 8), 24))
OCR_ACCURACY_FIRST = os.environ.get('GROM_OCR_ACCURACY_FIRST', '0').strip().lower() in ('1', 'true', 'yes', 'on')
MAX_TOP_CANDIDATES = max(3, min(parse_int(os.environ.get('GROM_OCR_MAX_TOP_CANDIDATES'), 15), 30))
ROTATION_ANGLES = parse_rotation_angles()
TESSERACT_MAX_VARIANTS = max(6, min(parse_int(os.environ.get('GROM_OCR_TESSERACT_MAX_VARIANTS'), 14), 40))
TESSERACT_PSM_MODES = parse_psm_modes()
TESSERACT_EARLY_EXIT_SCORE = parse_float(os.environ.get('GROM_OCR_TESSERACT_EARLY_EXIT_SCORE'), 118.0)
TESSERACT_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_TESSERACT_REGION_EARLY_SCORE'), 121.0)
TESSERACT_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_TESSERACT_HIT_BONUS'), 2.1)
TESSERACT_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_TESSERACT_MIN_ACCEPT_SCORE'), 42.0)
TESSERACT_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_TESSERACT_MIN_ACCEPT_CONF'), 28.0)
TESSERACT_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_TESSERACT_PATTERN_MIN_SCORE'), 58.0)
TESSERACT_DYNAMIC_WEIGHT_ENABLE = os.environ.get('GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
TESSERACT_DYNAMIC_WEIGHT_MIN = max(0.05, min(parse_float(os.environ.get('GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MIN'), 0.16), 1.0))
TESSERACT_DYNAMIC_WEIGHT_MAX = max(
    TESSERACT_DYNAMIC_WEIGHT_MIN,
    min(parse_float(os.environ.get('GROM_OCR_TESSERACT_DYNAMIC_WEIGHT_MAX'), 1.0), 1.2),
)
EASYOCR_ALLOWLIST = os.environ.get('GROM_OCR_EASYOCR_ALLOWLIST', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').strip()
EASYOCR_DECODER = os.environ.get('GROM_OCR_EASYOCR_DECODER', 'greedy').strip() or 'greedy'
EASYOCR_BEAM_WIDTH = max(1, min(parse_int(os.environ.get('GROM_OCR_EASYOCR_BEAM_WIDTH'), 8), 50))
EASYOCR_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_EASYOCR_HIT_BONUS'), 2.5)
EASYOCR_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_EASYOCR_REGION_EARLY_SCORE'), 106.0)
EASYOCR_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_EASYOCR_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
EASYOCR_MAX_VARIANTS = max(2, min(parse_int(os.environ.get('GROM_OCR_EASYOCR_MAX_VARIANTS'), 6), TESSERACT_MAX_VARIANTS))
EASYOCR_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_EASYOCR_VARIANT_CONSISTENCY_BONUS'), 3.6)
EASYOCR_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_EASYOCR_MIN_ACCEPT_SCORE'), 48.0)
EASYOCR_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_EASYOCR_MIN_ACCEPT_CONF'), 28.0)
EASYOCR_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_EASYOCR_PATTERN_MIN_SCORE'), 62.0)
EASYOCR_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_EASYOCR_MIN_VARIANT_HITS'), 2), 6))
RAPIDOCR_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_HIT_BONUS'), 2.0)
RAPIDOCR_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_REGION_EARLY_SCORE'), 105.0)
RAPIDOCR_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_RAPIDOCR_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
RAPIDOCR_MAX_VARIANTS = max(2, min(parse_int(os.environ.get('GROM_OCR_RAPIDOCR_MAX_VARIANTS'), 5), TESSERACT_MAX_VARIANTS))
RAPIDOCR_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_VARIANT_CONSISTENCY_BONUS'), 3.2)
RAPIDOCR_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_MIN_ACCEPT_SCORE'), 46.0)
RAPIDOCR_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_MIN_ACCEPT_CONF'), 26.0)
RAPIDOCR_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_RAPIDOCR_PATTERN_MIN_SCORE'), 60.0)
RAPIDOCR_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_RAPIDOCR_MIN_VARIANT_HITS'), 2), 6))
TROCR_MODEL_ID = os.environ.get('GROM_OCR_TROCR_MODEL_ID', 'microsoft/trocr-small-printed').strip() or 'microsoft/trocr-small-printed'
TROCR_MAX_NEW_TOKENS = max(8, min(parse_int(os.environ.get('GROM_OCR_TROCR_MAX_NEW_TOKENS'), 24), 48))
TROCR_REGION_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_TROCR_REGION_LIMIT'), 2), 4))
TROCR_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_TROCR_HIT_BONUS'), 1.5)
TROCR_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_TROCR_REGION_EARLY_SCORE'), 103.0)
TROCR_BASE_CONFIDENCE = parse_float(os.environ.get('GROM_OCR_TROCR_BASE_CONFIDENCE'), 54.0)
TROCR_LOCAL_ONLY = os.environ.get('GROM_OCR_TROCR_LOCAL_ONLY', '1').strip().lower() in ('1', 'true', 'yes', 'on')
TROCR_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_TROCR_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
TROCR_MAX_VARIANTS = max(1, min(parse_int(os.environ.get('GROM_OCR_TROCR_MAX_VARIANTS'), 4), TESSERACT_MAX_VARIANTS))
TROCR_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_TROCR_VARIANT_CONSISTENCY_BONUS'), 2.8)
TROCR_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_TROCR_MIN_ACCEPT_SCORE'), 44.0)
TROCR_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_TROCR_MIN_ACCEPT_CONF'), 24.0)
TROCR_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_TROCR_PATTERN_MIN_SCORE'), 58.0)
TROCR_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_TROCR_MIN_VARIANT_HITS'), 2), 6))
DOCTR_REGION_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_DOCTR_REGION_LIMIT'), 2), 4))
DOCTR_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_DOCTR_HIT_BONUS'), 1.9)
DOCTR_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_DOCTR_REGION_EARLY_SCORE'), 104.0)
DOCTR_BASE_CONFIDENCE = parse_float(os.environ.get('GROM_OCR_DOCTR_BASE_CONFIDENCE'), 52.0)
DOCTR_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_DOCTR_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
DOCTR_MAX_VARIANTS = max(1, min(parse_int(os.environ.get('GROM_OCR_DOCTR_MAX_VARIANTS'), 4), TESSERACT_MAX_VARIANTS))
DOCTR_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_DOCTR_VARIANT_CONSISTENCY_BONUS'), 2.6)
DOCTR_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_DOCTR_MIN_ACCEPT_SCORE'), 42.0)
DOCTR_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_DOCTR_MIN_ACCEPT_CONF'), 23.0)
DOCTR_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_DOCTR_PATTERN_MIN_SCORE'), 56.0)
DOCTR_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_DOCTR_MIN_VARIANT_HITS'), 2), 6))
PADDLEOCR_LANG = (os.environ.get('GROM_OCR_PADDLEOCR_LANG') or 'en').strip() or 'en'
PADDLEOCR_USE_GPU = os.environ.get('GROM_OCR_PADDLEOCR_USE_GPU', '0').strip().lower() in ('1', 'true', 'yes', 'on')
PADDLEOCR_USE_ANGLE_CLS = os.environ.get('GROM_OCR_PADDLEOCR_USE_ANGLE_CLS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
PADDLEOCR_SHOW_LOG = os.environ.get('GROM_OCR_PADDLEOCR_SHOW_LOG', '0').strip().lower() in ('1', 'true', 'yes', 'on')
PADDLEOCR_DYNAMIC_VARIANTS = os.environ.get('GROM_OCR_PADDLEOCR_DYNAMIC_VARIANTS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
PADDLEOCR_MAX_VARIANTS = max(2, min(parse_int(os.environ.get('GROM_OCR_PADDLEOCR_MAX_VARIANTS'), 5), TESSERACT_MAX_VARIANTS))
PADDLEOCR_HIT_BONUS = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_HIT_BONUS'), 2.3)
PADDLEOCR_VARIANT_CONSISTENCY_BONUS = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_VARIANT_CONSISTENCY_BONUS'), 3.0)
PADDLEOCR_MIN_ACCEPT_SCORE = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_MIN_ACCEPT_SCORE'), 47.0)
PADDLEOCR_MIN_ACCEPT_CONF = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_MIN_ACCEPT_CONF'), 27.0)
PADDLEOCR_PATTERN_MIN_SCORE = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_PATTERN_MIN_SCORE'), 60.0)
PADDLEOCR_MIN_VARIANT_HITS = max(1, min(parse_int(os.environ.get('GROM_OCR_PADDLEOCR_MIN_VARIANT_HITS'), 2), 6))
PADDLEOCR_REGION_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_PADDLEOCR_REGION_LIMIT'), 3), 4))
PADDLEOCR_REGION_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_PADDLEOCR_REGION_EARLY_SCORE'), 106.0)
YOLO_MODEL_PATH = (
    os.environ.get('GROM_OCR_YOLO_MODEL_PATH')
    or (DEFAULT_YOLO_MODEL_PATH if os.path.exists(DEFAULT_YOLO_MODEL_PATH) else '')
).strip()
YOLO_CONFIDENCE = max(0.05, min(parse_float(os.environ.get('GROM_OCR_YOLO_CONFIDENCE'), 0.35), 0.95))
YOLO_IOU = max(0.05, min(parse_float(os.environ.get('GROM_OCR_YOLO_IOU'), 0.45), 0.95))
YOLO_MAX_DETECTIONS = max(1, min(parse_int(os.environ.get('GROM_OCR_YOLO_MAX_DETECTIONS'), 3), 10))
YOLO_PLATE_CLASS = (os.environ.get('GROM_OCR_YOLO_PLATE_CLASS') or '').strip()
YOLO_MIN_ASPECT = max(0.8, min(parse_float(os.environ.get('GROM_OCR_YOLO_MIN_ASPECT'), 0.8), 6.0))
YOLO_MAX_ASPECT = max(YOLO_MIN_ASPECT, min(parse_float(os.environ.get('GROM_OCR_YOLO_MAX_ASPECT'), 10.0), 12.0))
ALLOW_HEAVY_COLDSTART = os.environ.get('GROM_OCR_ALLOW_HEAVY_COLDSTART', '0').strip().lower() in ('1', 'true', 'yes', 'on')
PDF_MAX_PAGES = max(1, min(parse_int(os.environ.get('GROM_OCR_PDF_MAX_PAGES'), 3), 10))
PDF_RENDER_SCALE = min(max(parse_float(os.environ.get('GROM_OCR_PDF_RENDER_SCALE'), 2.4), 1.0), 4.0)
PDF_PAGE_CANDIDATE_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_PDF_PAGE_CANDIDATE_LIMIT'), 2), 8))
PDF_PAGE_EARLY_SCORE = parse_float(os.environ.get('GROM_OCR_PDF_PAGE_EARLY_SCORE'), 118.0)
PDF_MAX_REGION_CANDIDATES = max(1, min(parse_int(os.environ.get('GROM_OCR_PDF_MAX_REGION_CANDIDATES'), 2), 5))
PDF_PROBE_MAX_SIDE = max(800, min(parse_int(os.environ.get('GROM_OCR_PDF_PROBE_MAX_SIDE'), 1200), 2400))
PDF_PROBE_REGION_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_PDF_PROBE_REGION_LIMIT'), 3), 6))
PDF_REGION_MAX_SIDE = max(640, min(parse_int(os.environ.get('GROM_OCR_PDF_REGION_MAX_SIDE'), 1360), 2200))
PDF_QUICK_ENGINE_MAX_SIDE = max(480, min(parse_int(os.environ.get('GROM_OCR_PDF_QUICK_ENGINE_MAX_SIDE'), 980), 1800))
TRIAGE_IMAGE_REGION_LIMIT = max(1, min(parse_int(os.environ.get('GROM_OCR_TRIAGE_IMAGE_REGION_LIMIT'), 2), 4))
TRIAGE_IMAGE_SCENE_MAX_SIDE = max(720, min(parse_int(os.environ.get('GROM_OCR_TRIAGE_IMAGE_SCENE_MAX_SIDE'), 1280), 2000))
TRIAGE_IMAGE_REGION_MAX_SIDE = max(480, min(parse_int(os.environ.get('GROM_OCR_TRIAGE_IMAGE_REGION_MAX_SIDE'), 1280), 2200))
TRIAGE_IMAGE_ACCEPT_SCORE = max(40.0, min(parse_float(os.environ.get('GROM_OCR_TRIAGE_IMAGE_ACCEPT_SCORE'), 72.0), 100.0))
TRIAGE_IMAGE_MARGINAL_SCORE = max(20.0, min(parse_float(os.environ.get('GROM_OCR_TRIAGE_IMAGE_MARGINAL_SCORE'), 52.0), 95.0))
TRIAGE_IMAGE_ACCEPT_QUALITY = max(25.0, min(parse_float(os.environ.get('GROM_OCR_TRIAGE_IMAGE_ACCEPT_QUALITY'), 68.0), 100.0))
TRIAGE_IMAGE_MARGINAL_QUALITY = max(10.0, min(parse_float(os.environ.get('GROM_OCR_TRIAGE_IMAGE_MARGINAL_QUALITY'), 46.0), 100.0))
VISUAL_PROFILE_ENABLED = os.environ.get('GROM_OCR_VISUAL_PROFILE_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
VISUAL_PROFILE_MAX_SIDE = max(640, min(parse_int(os.environ.get('GROM_OCR_VISUAL_PROFILE_MAX_SIDE'), 1280), 2200))
VISUAL_PROFILE_MIN_CONFIDENCE = max(20.0, min(parse_float(os.environ.get('GROM_OCR_VISUAL_PROFILE_MIN_CONFIDENCE'), 42.0), 90.0))
VISUAL_PROFILE_TOP_HYPOTHESES = max(1, min(parse_int(os.environ.get('GROM_OCR_VISUAL_PROFILE_TOP_HYPOTHESES'), 3), 5))
VISUAL_MODEL_ABSTAIN_ENABLE = os.environ.get('GROM_OCR_VISUAL_MODEL_ABSTAIN_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
VISUAL_MODEL_MIN_CONFIDENCE = max(35.0, min(parse_float(os.environ.get('GROM_OCR_VISUAL_MODEL_MIN_CONFIDENCE'), 78.0), 97.0))
VISUAL_MODEL_MIN_MARGIN = max(2.0, min(parse_float(os.environ.get('GROM_OCR_VISUAL_MODEL_MIN_MARGIN'), 8.0), 30.0))
VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE = max(1, min(parse_int(os.environ.get('GROM_OCR_VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE'), 1), 5))
VISUAL_BRAND_MIN_CONFIDENCE = max(30.0, min(parse_float(os.environ.get('GROM_OCR_VISUAL_BRAND_MIN_CONFIDENCE'), 58.0), 95.0))
SCENE_PREPROCESS_ENABLED = os.environ.get('GROM_OCR_SCENE_PREPROCESS_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
SCENE_PREPROCESS_BLEND = max(0.0, min(parse_float(os.environ.get('GROM_OCR_SCENE_PREPROCESS_BLEND'), 0.26), 0.65))
FORENSIC_TRAITS_ENABLED = os.environ.get('GROM_OCR_FORENSIC_TRAITS_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
VISUAL_FIPE_ENABLE = os.environ.get('GROM_OCR_VISUAL_FIPE_ENABLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
VISUAL_FIPE_BASE_URL = (os.environ.get('GROM_OCR_VISUAL_FIPE_BASE_URL') or os.environ.get('GROM_OCR_OPEN_DATA_FIPE_BASE_URL') or 'https://fipe.parallelum.com.br/api/v2').strip().rstrip('/')
VISUAL_FIPE_TOKEN = (os.environ.get('GROM_OCR_VISUAL_FIPE_TOKEN') or os.environ.get('GROM_OCR_OPEN_DATA_FIPE_TOKEN') or '').strip()
VISUAL_FIPE_TIMEOUT = max(1.0, min(parse_float(os.environ.get('GROM_OCR_VISUAL_FIPE_TIMEOUT'), 3.0), 12.0))
HTTP_INSECURE_SKIP_VERIFY = os.environ.get('GROM_OCR_HTTP_INSECURE_SKIP_VERIFY', '0').strip().lower() in ('1', 'true', 'yes', 'on')
HTTP_CA_BUNDLE = (os.environ.get('GROM_OCR_HTTP_CA_BUNDLE') or '').strip()
EXTERNAL_COMPARE_ENABLE = parse_bool(os.environ.get('GROM_OCR_EXTERNAL_COMPARE_ENABLE', '1'), True)
EXTERNAL_COMPARE_TIMEOUT = max(2.0, min(parse_float(os.environ.get('GROM_OCR_EXTERNAL_COMPARE_TIMEOUT'), 8.0), 30.0))
EXTERNAL_COMPARE_MAX_CANDIDATES = max(1, min(parse_int(os.environ.get('GROM_OCR_EXTERNAL_COMPARE_MAX_CANDIDATES'), 3), 8))
OPENALPR_SECRET_KEY = (os.environ.get('OPENALPR_SECRET_KEY') or '').strip()
OPENALPR_COUNTRY = (os.environ.get('GROM_OCR_OPENALPR_COUNTRY') or 'br').strip() or 'br'
OPENALPR_RECOGNIZE_VEHICLE = parse_bool(os.environ.get('GROM_OCR_OPENALPR_RECOGNIZE_VEHICLE', '1'), True)
OPENALPR_TOPN = max(1, min(parse_int(os.environ.get('GROM_OCR_OPENALPR_TOPN'), 5), 20))
OPENALPR_ENDPOINT = (os.environ.get('GROM_OCR_OPENALPR_ENDPOINT') or 'https://api.openalpr.com/v3/recognize').strip() or 'https://api.openalpr.com/v3/recognize'
NOMEROFF_COMPARE_ENDPOINT = (os.environ.get('GROM_OCR_NOMEROFF_COMPARE_ENDPOINT') or '').strip()
NOMEROFF_COMPARE_TOKEN = (os.environ.get('GROM_OCR_NOMEROFF_COMPARE_TOKEN') or '').strip()
NOMEROFF_COMPARE_TOKEN_HEADER = (os.environ.get('GROM_OCR_NOMEROFF_COMPARE_TOKEN_HEADER') or 'Authorization').strip() or 'Authorization'

if HTTP_INSECURE_SKIP_VERIFY:
    try:
        from urllib3.exceptions import InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        pass
UPLOAD_FOLDER = os.environ.get('GROM_OCR_UPLOAD_DIR') or os.path.join(tempfile.gettempdir(), 'grom_ocr_uploads')


def resolve_max_upload_bytes():
    raw_bytes = os.environ.get('GROM_OCR_MAX_UPLOAD_BYTES', '').strip()
    if raw_bytes.isdigit():
        parsed = int(raw_bytes)
        if parsed > 0:
            return parsed

    raw_mb = os.environ.get('GROM_OCR_MAX_UPLOAD_MB', '').strip()
    if raw_mb.isdigit():
        parsed_mb = int(raw_mb)
        if parsed_mb > 0:
            return parsed_mb * 1024 * 1024

    return 80 * 1024 * 1024

OLD_PATTERN = re.compile(r'^[A-Z]{3}[0-9]{4}$')
MERCOSUL_PATTERN = re.compile(r'^[A-Z]{3}[0-9][A-Z][0-9]{2}$')
ALNUM_ONLY = re.compile(r'[^A-Z0-9]')

DIGIT_SUBSTITUTIONS = {'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6', 'T': '7'}
LETTER_SUBSTITUTIONS = {'0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G', '7': 'T', '4': 'A'}

app = Flask(__name__)

# Handler global para erros HTTP 500 e outros não capturados
@app.errorhandler(500)
def handle_500_error(e):
    import traceback
    return jsonify({
        'error': 'Internal Server Error',
        'message': str(e),
        'traceback': traceback.format_exc(),
    }), 500

# Handler para outros erros HTTP (ex: 404)
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    import traceback
    code = getattr(e, 'code', 500)
    return jsonify({
        'error': 'Unexpected Error',
        'message': str(e),
        'traceback': traceback.format_exc(),
    }), code
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = resolve_max_upload_bytes()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PADDLEOCR_RUNTIME = {'ready': None, 'error': ''}
YOLO_RUNTIME = {'ready': None, 'error': ''}

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROJECT_TESSERACT_CMD = os.path.join(PROJECT_ROOT, 'tools', 'tesseract-portable', 'tesseract.exe')
SCENE_PREPROCESS_CALIBRATION_PATH = (
    os.environ.get('GROM_OCR_SCENE_PREPROCESS_CALIBRATION_PATH')
    or os.path.join(PROJECT_ROOT, 'data', 'scene_preprocess_calibration.json')
).strip()


# Sempre usar o arquivo local haarcascade_russian_plate_number.xml
# Para produção: mantenha o arquivo em 'models/haarcascade_russian_plate_number.xml' na raiz do projeto.
# Se desejar customizar o caminho, defina a variável de ambiente GROM_OCR_HAAR_CASCADE_PATH.
LOCAL_CASCADE = os.path.join(PROJECT_ROOT, 'models', 'haarcascade_russian_plate_number.xml')
HAAR_PLATE_CASCADE_PATH = os.environ.get('GROM_OCR_HAAR_CASCADE_PATH', LOCAL_CASCADE)
if not os.path.exists(HAAR_PLATE_CASCADE_PATH):
    raise FileNotFoundError(f"Cascade XML não encontrado: {HAAR_PLATE_CASCADE_PATH}. Certifique-se de que o arquivo está presente para produção.")
HAAR_PLATE_CASCADE = cv2.CascadeClassifier(HAAR_PLATE_CASCADE_PATH)


def configure_tesseract():
    candidates = [
        os.environ.get('GROM_OCR_TESSERACT_CMD'),
        os.environ.get('TESSERACT_CMD'),
        PROJECT_TESSERACT_CMD,
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            tessdata_dir = os.path.join(os.path.dirname(candidate), 'tessdata')
            if os.path.isdir(tessdata_dir) and not os.environ.get('TESSDATA_PREFIX'):
                os.environ['TESSDATA_PREFIX'] = tessdata_dir
            return candidate

    return pytesseract.pytesseract.tesseract_cmd


TESSERACT_CMD = configure_tesseract()


def trocr_bundle_is_warm():
    try:
        return get_trocr_bundle.cache_info().currsize > 0
    except Exception:
        return False


def doctr_predictor_is_warm():
    try:
        return get_doctr_predictor.cache_info().currsize > 0
    except Exception:
        return False


def paddleocr_reader_is_warm():
    try:
        return bool(PADDLEOCR_RUNTIME.get('ready'))
    except Exception:
        return False


def yolo_detector_is_warm():
    try:
        return bool(YOLO_RUNTIME.get('ready'))
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_paddleocr_reader():
    if PaddleOCR is None or not PADDLEOCR_ENABLED:
        PADDLEOCR_RUNTIME['ready'] = False
        PADDLEOCR_RUNTIME['error'] = 'paddleocr_disabled_or_missing'
        return None
    try:
        os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
        device = 'gpu' if PADDLEOCR_USE_GPU else 'cpu'
        reader = PaddleOCR(
            lang=PADDLEOCR_LANG,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=PADDLEOCR_USE_ANGLE_CLS,
            device=device,
        )
        PADDLEOCR_RUNTIME['ready'] = True
        PADDLEOCR_RUNTIME['error'] = ''
        return reader
    except Exception as exc:
        PADDLEOCR_RUNTIME['ready'] = False
        PADDLEOCR_RUNTIME['error'] = str(exc) or 'paddleocr_init_failed'
        return None


@lru_cache(maxsize=1)
def get_yolo_detector():
    if YOLO is None or not YOLO_DETECTOR_ENABLED or not YOLO_MODEL_PATH:
        YOLO_RUNTIME['ready'] = False
        YOLO_RUNTIME['error'] = 'yolo_detector_disabled_or_missing'
        return None
    if not os.path.exists(YOLO_MODEL_PATH):
        YOLO_RUNTIME['ready'] = False
        YOLO_RUNTIME['error'] = 'yolo_model_path_missing'
        return None
    try:
        detector = YOLO(YOLO_MODEL_PATH)
        YOLO_RUNTIME['ready'] = True
        YOLO_RUNTIME['error'] = ''
        return detector
    except Exception as exc:
        YOLO_RUNTIME['ready'] = False
        YOLO_RUNTIME['error'] = str(exc) or 'yolo_detector_init_failed'
        return None


def warmup_heavy_models():
    result = {
        'trocr': {'enabled': TROCR_ENABLED and TrOCRProcessor is not None and VisionEncoderDecoderModel is not None and torch is not None and Image is not None},
        'doctr': {'enabled': DOCTR_ENABLED and ocr_predictor is not None},
        'paddleocr': {'enabled': PADDLEOCR_ENABLED and PaddleOCR is not None},
        'yolo_detector': {'enabled': YOLO_DETECTOR_ENABLED and YOLO is not None and bool(YOLO_MODEL_PATH)},
    }

    if result['trocr']['enabled']:
        try:
            processor, model = get_trocr_bundle()
            result['trocr']['ready'] = bool(processor is not None and model is not None)
            result['trocr']['error'] = '' if result['trocr']['ready'] else 'trocr_bundle_unavailable'
        except Exception as exc:
            result['trocr']['ready'] = False
            result['trocr']['error'] = str(exc)
    else:
        result['trocr']['ready'] = False
        result['trocr']['error'] = 'trocr_disabled_or_missing'

    if result['doctr']['enabled']:
        try:
            predictor = get_doctr_predictor()
            result['doctr']['ready'] = bool(predictor is not None)
            result['doctr']['error'] = '' if result['doctr']['ready'] else 'doctr_predictor_unavailable'
        except Exception as exc:
            result['doctr']['ready'] = False
            result['doctr']['error'] = str(exc)
    else:
        result['doctr']['ready'] = False
        result['doctr']['error'] = 'doctr_disabled_or_missing'

    if result['paddleocr']['enabled']:
        try:
            reader = get_paddleocr_reader()
            result['paddleocr']['ready'] = bool(reader is not None)
            result['paddleocr']['error'] = '' if result['paddleocr']['ready'] else 'paddleocr_reader_unavailable'
        except Exception as exc:
            result['paddleocr']['ready'] = False
            result['paddleocr']['error'] = str(exc)
    else:
        result['paddleocr']['ready'] = False
        result['paddleocr']['error'] = 'paddleocr_disabled_or_missing'

    if result['yolo_detector']['enabled']:
        try:
            detector = get_yolo_detector()
            result['yolo_detector']['ready'] = bool(detector is not None)
            result['yolo_detector']['error'] = '' if result['yolo_detector']['ready'] else 'yolo_detector_model_unavailable'
        except Exception as exc:
            result['yolo_detector']['ready'] = False
            result['yolo_detector']['error'] = str(exc)
    else:
        result['yolo_detector']['ready'] = False
        result['yolo_detector']['error'] = 'yolo_detector_disabled_or_missing'

    return result


def safe_route(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return jsonify({
                'error': f'Internal Server Error in {f.__name__}: {exc}',
                'traceback': traceback.format_exc(),
            }), 500
    return decorated_function


@app.route('/')
@safe_route
def index():
    return jsonify({
        'service': 'grom_ocr_api',
        'status': 'ok',
        'health': '/health',
        'process': '/process',
        'process_video': '/process_video',
        'warmup': '/warmup_heavy',
    })


@app.route('/pdf/<filename>')
def download_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)


@app.route('/artifact/<path:filename>')
def download_artifact(filename):
    safe_name = sanitize_filename(filename or '')
    if not safe_name:
        return jsonify({'error': 'Arquivo invalido'}), 404
    path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    if not os.path.exists(path):
        return jsonify({'error': 'Arquivo nao encontrado'}), 404
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name, as_attachment=False)


@app.route('/health')
def healthcheck():
    return jsonify({
        'status': 'ok',
        'upload_folder': app.config['UPLOAD_FOLDER'],
        'easyocr_enabled': EASYOCR_ENABLED and easyocr is not None,
        'easyocr_profile': {
            'allowlist': EASYOCR_ALLOWLIST,
            'decoder': EASYOCR_DECODER,
            'beam_width': EASYOCR_BEAM_WIDTH,
            'hit_bonus': EASYOCR_HIT_BONUS,
            'dynamic_variants': EASYOCR_DYNAMIC_VARIANTS,
            'max_variants': EASYOCR_MAX_VARIANTS,
            'variant_consistency_bonus': EASYOCR_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': EASYOCR_MIN_ACCEPT_SCORE,
            'min_accept_conf': EASYOCR_MIN_ACCEPT_CONF,
            'pattern_min_score': EASYOCR_PATTERN_MIN_SCORE,
            'min_variant_hits': EASYOCR_MIN_VARIANT_HITS,
        },
        'rapidocr_enabled': RAPIDOCR_ENABLED and RapidOCR is not None,
        'rapidocr_profile': {
            'hit_bonus': RAPIDOCR_HIT_BONUS,
            'early_score': RAPIDOCR_REGION_EARLY_SCORE,
            'dynamic_variants': RAPIDOCR_DYNAMIC_VARIANTS,
            'max_variants': RAPIDOCR_MAX_VARIANTS,
            'variant_consistency_bonus': RAPIDOCR_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': RAPIDOCR_MIN_ACCEPT_SCORE,
            'min_accept_conf': RAPIDOCR_MIN_ACCEPT_CONF,
            'pattern_min_score': RAPIDOCR_PATTERN_MIN_SCORE,
            'min_variant_hits': RAPIDOCR_MIN_VARIANT_HITS,
        },
        'paddleocr_enabled': PADDLEOCR_ENABLED and PaddleOCR is not None,
        'paddleocr_profile': {
            'lang': PADDLEOCR_LANG,
            'use_gpu': PADDLEOCR_USE_GPU,
            'use_angle_cls': PADDLEOCR_USE_ANGLE_CLS,
            'show_log': PADDLEOCR_SHOW_LOG,
            'dynamic_variants': PADDLEOCR_DYNAMIC_VARIANTS,
            'max_variants': PADDLEOCR_MAX_VARIANTS,
            'region_limit': PADDLEOCR_REGION_LIMIT,
            'region_early_score': PADDLEOCR_REGION_EARLY_SCORE,
            'hit_bonus': PADDLEOCR_HIT_BONUS,
            'variant_consistency_bonus': PADDLEOCR_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': PADDLEOCR_MIN_ACCEPT_SCORE,
            'min_accept_conf': PADDLEOCR_MIN_ACCEPT_CONF,
            'pattern_min_score': PADDLEOCR_PATTERN_MIN_SCORE,
            'min_variant_hits': PADDLEOCR_MIN_VARIANT_HITS,
            'runtime_error': PADDLEOCR_RUNTIME.get('error', ''),
        },
        'tesseract_profile': {
            'max_variants': TESSERACT_MAX_VARIANTS,
            'psm_modes': TESSERACT_PSM_MODES,
            'early_exit_score': TESSERACT_EARLY_EXIT_SCORE,
            'region_early_score': TESSERACT_REGION_EARLY_SCORE,
            'hit_bonus': TESSERACT_HIT_BONUS,
            'min_accept_score': TESSERACT_MIN_ACCEPT_SCORE,
            'min_accept_conf': TESSERACT_MIN_ACCEPT_CONF,
            'pattern_min_score': TESSERACT_PATTERN_MIN_SCORE,
            'dynamic_weight_enable': TESSERACT_DYNAMIC_WEIGHT_ENABLE,
            'dynamic_weight_min': TESSERACT_DYNAMIC_WEIGHT_MIN,
            'dynamic_weight_max': TESSERACT_DYNAMIC_WEIGHT_MAX,
        },
        'yolo_detector_enabled': YOLO_DETECTOR_ENABLED and YOLO is not None and bool(YOLO_MODEL_PATH),
        'yolo_detector_profile': {
            'model_path': YOLO_MODEL_PATH,
            'confidence': YOLO_CONFIDENCE,
            'iou': YOLO_IOU,
            'max_detections': YOLO_MAX_DETECTIONS,
            'plate_class': YOLO_PLATE_CLASS,
            'min_aspect': YOLO_MIN_ASPECT,
            'max_aspect': YOLO_MAX_ASPECT,
            'runtime_error': YOLO_RUNTIME.get('error', ''),
        },
        'trocr_enabled': TROCR_ENABLED and TrOCRProcessor is not None and VisionEncoderDecoderModel is not None,
        'trocr_profile': {
            'model_id': TROCR_MODEL_ID,
            'max_new_tokens': TROCR_MAX_NEW_TOKENS,
            'region_limit': TROCR_REGION_LIMIT,
            'hit_bonus': TROCR_HIT_BONUS,
            'early_score': TROCR_REGION_EARLY_SCORE,
            'dynamic_variants': TROCR_DYNAMIC_VARIANTS,
            'max_variants': TROCR_MAX_VARIANTS,
            'variant_consistency_bonus': TROCR_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': TROCR_MIN_ACCEPT_SCORE,
            'min_accept_conf': TROCR_MIN_ACCEPT_CONF,
            'pattern_min_score': TROCR_PATTERN_MIN_SCORE,
            'min_variant_hits': TROCR_MIN_VARIANT_HITS,
        },
        'doctr_enabled': DOCTR_ENABLED and ocr_predictor is not None,
        'doctr_profile': {
            'region_limit': DOCTR_REGION_LIMIT,
            'hit_bonus': DOCTR_HIT_BONUS,
            'early_score': DOCTR_REGION_EARLY_SCORE,
            'base_confidence': DOCTR_BASE_CONFIDENCE,
            'dynamic_variants': DOCTR_DYNAMIC_VARIANTS,
            'max_variants': DOCTR_MAX_VARIANTS,
            'variant_consistency_bonus': DOCTR_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': DOCTR_MIN_ACCEPT_SCORE,
            'min_accept_conf': DOCTR_MIN_ACCEPT_CONF,
            'pattern_min_score': DOCTR_PATTERN_MIN_SCORE,
            'min_variant_hits': DOCTR_MIN_VARIANT_HITS,
        },
        'heavy_engine_policy': {
            'allow_coldstart': ALLOW_HEAVY_COLDSTART,
            'trocr_local_only': TROCR_LOCAL_ONLY,
            'trocr_warm': trocr_bundle_is_warm(),
            'doctr_warm': doctr_predictor_is_warm(),
            'paddleocr_warm': paddleocr_reader_is_warm(),
            'yolo_detector_warm': yolo_detector_is_warm(),
        },
        'plate_recognizer_enabled': bool(PLATE_RECOGNIZER_TOKEN),
        'plate_recognizer_profile': {
            'dynamic_variants': PLATE_RECOGNIZER_DYNAMIC_VARIANTS,
            'max_variants': PLATE_RECOGNIZER_MAX_VARIANTS,
            'top_results_per_variant': PLATE_RECOGNIZER_TOP_RESULTS,
            'hit_bonus': PLATE_RECOGNIZER_HIT_BONUS,
            'variant_consistency_bonus': PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS,
            'min_accept_score': PLATE_RECOGNIZER_MIN_ACCEPT_SCORE,
            'min_accept_conf': PLATE_RECOGNIZER_MIN_ACCEPT_CONF,
            'pattern_min_score': PLATE_RECOGNIZER_PATTERN_MIN_SCORE,
            'min_variant_hits': PLATE_RECOGNIZER_MIN_VARIANT_HITS,
        },
        'external_compare_profile': {
            'enabled': EXTERNAL_COMPARE_ENABLE,
            'timeout': EXTERNAL_COMPARE_TIMEOUT,
            'max_candidates': EXTERNAL_COMPARE_MAX_CANDIDATES,
            'openalpr_configured': bool(OPENALPR_SECRET_KEY),
            'openalpr_country': OPENALPR_COUNTRY,
            'openalpr_recognize_vehicle': OPENALPR_RECOGNIZE_VEHICLE,
            'openalpr_topn': OPENALPR_TOPN,
            'nomeroff_endpoint_configured': bool(NOMEROFF_COMPARE_ENDPOINT),
        },
        'pdf_input': {
            'enabled': PDF_INPUT_ENABLED,
            'available': pdfium is not None,
            'max_pages': PDF_MAX_PAGES,
            'render_scale': PDF_RENDER_SCALE,
            'page_candidate_limit': PDF_PAGE_CANDIDATE_LIMIT,
            'page_early_score': PDF_PAGE_EARLY_SCORE,
            'max_region_candidates': PDF_MAX_REGION_CANDIDATES,
            'probe_max_side': PDF_PROBE_MAX_SIDE,
            'probe_region_limit': PDF_PROBE_REGION_LIMIT,
            'region_max_side': PDF_REGION_MAX_SIDE,
            'quick_engine_max_side': PDF_QUICK_ENGINE_MAX_SIDE,
        },
        'visual_profile': {
            'enabled': VISUAL_PROFILE_ENABLED,
            'max_side': VISUAL_PROFILE_MAX_SIDE,
            'min_confidence': VISUAL_PROFILE_MIN_CONFIDENCE,
            'top_hypotheses': VISUAL_PROFILE_TOP_HYPOTHESES,
            'model_abstain_enable': VISUAL_MODEL_ABSTAIN_ENABLE,
            'model_min_confidence': VISUAL_MODEL_MIN_CONFIDENCE,
            'model_min_margin': VISUAL_MODEL_MIN_MARGIN,
            'model_min_discriminative_evidence': VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE,
            'brand_min_confidence': VISUAL_BRAND_MIN_CONFIDENCE,
            'scene_preprocess_enabled': SCENE_PREPROCESS_ENABLED,
            'scene_preprocess_blend': SCENE_PREPROCESS_BLEND,
            'forensic_traits_enabled': FORENSIC_TRAITS_ENABLED,
            'fipe_enable': VISUAL_FIPE_ENABLE,
            'fipe_base_url': VISUAL_FIPE_BASE_URL,
            'fipe_timeout': VISUAL_FIPE_TIMEOUT,
        },
        'ocr_min_confidence': OCR_MIN_CONFIDENCE,
        'ocr_pattern_min_confidence': OCR_PATTERN_MIN_CONFIDENCE,
        'force_ensemble': FORCE_ENSEMBLE,
        'ensemble_profile': {
            'top_per_engine': ENSEMBLE_TOP_PER_ENGINE,
            'weights': ENSEMBLE_WEIGHTS,
            'tesseract_dynamic_weight': {
                'enabled': TESSERACT_DYNAMIC_WEIGHT_ENABLE,
                'min_factor': TESSERACT_DYNAMIC_WEIGHT_MIN,
                'max_factor': TESSERACT_DYNAMIC_WEIGHT_MAX,
            },
        },
        'chain_signing_enabled': bool(CHAIN_SIGNING_KEY),
        'max_region_candidates': MAX_REGION_CANDIDATES,
        'rotation_angles': ROTATION_ANGLES,
        'tesseract_cmd': TESSERACT_CMD,
        'tesseract_available': os.path.exists(TESSERACT_CMD) if TESSERACT_CMD else False,
    })


@app.route('/warmup_heavy', methods=['POST'])
def warmup_heavy():
    started = time.perf_counter()
    details = warmup_heavy_models()
    elapsed = round(time.perf_counter() - started, 2)
    ready = bool(
        details.get('trocr', {}).get('ready')
        or details.get('doctr', {}).get('ready')
        or details.get('paddleocr', {}).get('ready')
        or details.get('yolo_detector', {}).get('ready')
    )
    return jsonify({
        'status': 'ok' if ready else 'partial',
        'elapsed_seconds': elapsed,
        'details': details,
    })


def detect_plate_yolo(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return None

    detector = get_yolo_detector()
    if detector is None:
        return None

    try:
        results = detector.predict(
            source=img,
            conf=YOLO_CONFIDENCE,
            iou=YOLO_IOU,
            verbose=False,
            max_det=YOLO_MAX_DETECTIONS,
        )
    except Exception:
        return None

    if not results:
        return None

    height, width = img.shape[:2]
    image_area = float(max(1, height * width))
    best_box = None
    best_score = -1e9
    desired_class = YOLO_PLATE_CLASS.strip().lower()

    for result in results:
        boxes = getattr(result, 'boxes', None)
        if boxes is None:
            continue
        names = getattr(result, 'names', {}) or {}

        for box in boxes:
            try:
                coords = getattr(box, 'xyxy', None)
                if coords is None:
                    continue
                coords = coords[0].tolist() if hasattr(coords[0], 'tolist') else list(coords[0])
                if len(coords) < 4:
                    continue
                x1, y1, x2, y2 = [int(round(float(value))) for value in coords[:4]]
                x1 = max(0, min(width - 1, x1))
                y1 = max(0, min(height - 1, y1))
                x2 = max(0, min(width, x2))
                y2 = max(0, min(height, y2))
                box_w = x2 - x1
                box_h = y2 - y1
                if box_w < PLATE_DETECTION_MIN_BOX_WIDTH or box_h < PLATE_DETECTION_MIN_BOX_HEIGHT:
                    continue

                aspect = float(box_w) / float(max(1, box_h))
                # YOLO boxes are already classifier-backed, so we allow the looser
                # quality floor here and keep the stricter contour thresholds for
                # the non-YOLO detectors.
                if aspect < max(YOLO_MIN_ASPECT, PLATE_DETECTION_QUALITY_ASPECT_MIN) or aspect > min(YOLO_MAX_ASPECT, PLATE_DETECTION_ASPECT_MAX):
                    continue

                cls_id = None
                try:
                    cls_tensor = getattr(box, 'cls', None)
                    if cls_tensor is not None:
                        cls_id = int(round(float(cls_tensor[0])))
                except Exception:
                    cls_id = None

                if desired_class:
                    if desired_class.isdigit():
                        if cls_id is None or cls_id != int(desired_class):
                            continue
                    else:
                        label = str(names.get(cls_id, '')).strip().lower() if cls_id is not None else ''
                        valid_classes = [c.strip() for c in desired_class.split(',')]
                        if not any(v in label for v in valid_classes if v):
                            continue

                confidence = 0.0
                try:
                    conf_tensor = getattr(box, 'conf', None)
                    if conf_tensor is not None:
                        confidence = float(conf_tensor[0])
                except Exception:
                    confidence = 0.0

                area_ratio = float(box_w * box_h) / image_area
                score = (confidence * 100.0) + min(10.0, aspect * 2.5) + min(10.0, area_ratio * 1500.0)
                if score > best_score:
                    best_score = score
                    best_box = (x1, y1, box_w, box_h)
            except Exception:
                continue

    return best_box


def parse_confidence(value):
    try:
        return float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return -1.0


def sanitize_filename(filename):
    cleaned = secure_filename(filename or '')
    return cleaned or 'upload.jpg'


def build_unique_artifact_filename(original_filename, analysis_id=None, prefix='', default_extension='', force_extension=False):
    safe_name = sanitize_filename(original_filename or '')
    base_name, extension = os.path.splitext(safe_name)
    base_name = secure_filename(base_name) or 'arquivo'
    token = secure_filename(str(analysis_id or ''))[:12]
    if force_extension or not extension:
        extension = default_extension or extension or ''
    if extension and not str(extension).startswith('.'):
        extension = f'.{extension}'
    artifact_name = f"{prefix}{base_name}"
    if token:
        artifact_name = f'{artifact_name}_{token}'
    if extension and not artifact_name.lower().endswith(extension.lower()):
        artifact_name = f'{artifact_name}{extension}'
    return sanitize_filename(artifact_name)


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_exc):
    max_bytes = int(app.config.get('MAX_CONTENT_LENGTH', resolve_max_upload_bytes()) or resolve_max_upload_bytes())
    max_mb = max_bytes / float(1024 * 1024)
    return jsonify({
        'error': f'Arquivo enviado excede o limite de {max_mb:.0f} MB',
    }), 413


def utc_iso_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(filepath):
    if not filepath or not os.path.exists(filepath):
        return ''
    digest = hashlib.sha256()
    try:
        with open(filepath, 'rb') as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except Exception:
        return ''
    return digest.hexdigest()


def collect_engine_text_set(payload, limit=ENSEMBLE_TOP_PER_ENGINE):
    texts = set()
    if not isinstance(payload, dict):
        return texts

    primary = normalize_plate_text(payload.get('text', ''))
    if is_plate_like_text(primary):
        texts.add(primary)

    candidates = payload.get('candidates', [])
    if isinstance(candidates, list):
        for candidate in candidates[:max(1, limit)]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if is_plate_like_text(text):
                texts.add(text)
    return texts


def build_consensus_report(ocr_results, preferred_text=''):
    votes = defaultdict(list)
    total_engines = 0
    for engine, payload in ocr_results.items():
        engine_texts = collect_engine_text_set(payload)
        if not engine_texts:
            continue
        total_engines += 1
        for text in engine_texts:
            votes[text].append(engine)

    if not votes:
        return {
            'best_text': '',
            'engines_considered': total_engines,
            'agreement_count': 0,
            'agreement_ratio': 0.0,
            'agreeing_engines': [],
            'vote_map': {},
        }

    max_score_map = {}
    for engine, payload in ocr_results.items():
        if not isinstance(payload, dict): continue
        text = payload.get('text', '')
        score = float(payload.get('score', payload.get('avg_conf', 0)))
        if text: max_score_map[text] = max(max_score_map.get(text, 0), score)
        for c in payload.get('candidates', []):
            if isinstance(c, dict) and c.get('text'):
                max_score_map[c['text']] = max(max_score_map.get(c['text'], 0), float(c.get('score', c.get('avg_conf', 0))))

    ordered = sorted(
        votes.items(),
        key=lambda item: (
            len(item[1]),
            detect_plate_pattern(item[0]) != 'Indefinido',
            len(item[0]) == 7,
            max_score_map.get(item[0], 0),
        ),
        reverse=True,
    )
    normalized_preferred = normalize_plate_text(preferred_text)
    preferred_match = None
    if normalized_preferred:
        preferred_match = next((item for item in ordered if item[0] == normalized_preferred), None)
        best_text, agreeing_engines = preferred_match if preferred_match else ordered[0]
    else:
        best_text, agreeing_engines = ordered[0]
    ratio = (len(agreeing_engines) / total_engines) if total_engines > 0 else 0.0

    compact_vote_map = {
        text: engines[:]
        for text, engines in ordered[:5]
    }

    return {
        'best_text': best_text,
        'engines_considered': total_engines,
        'agreement_count': len(agreeing_engines),
        'agreement_ratio': round(ratio * 100.0, 1),
        'agreeing_engines': agreeing_engines,
        'vote_map': compact_vote_map,
    }


def build_microcalibration_context(best_payload, top_candidates, ocr_results, source_sha256='', photo_filename='', plate_filename=''):
    override = microcalibration_module.lookup_microcalibration_override(
        source_sha256=source_sha256,
        photo_filename=photo_filename,
        plate_filename=plate_filename,
    )
    if not override:
        return {}

    manual_text = normalize_plate_text(override.get('manual_text', ''))
    if not manual_text:
        return {}

    manual_pattern = detect_plate_pattern(manual_text)
    raw_best_payload = dict(best_payload) if isinstance(best_payload, dict) else {}
    raw_override_text = normalize_plate_text(override.get('raw_text', ''))
    if raw_override_text:
        raw_best_payload = {
            'text': raw_override_text,
            'engine': str(override.get('raw_engine', 'audit_history') or 'audit_history'),
            'score': float(parse_float(override.get('raw_score', 0.0), 0.0)),
            'avg_conf': float(parse_float(override.get('raw_confidence', 0.0), 0.0)),
            'pattern': str(override.get('raw_pattern', detect_plate_pattern(raw_override_text))),
            'region': str(override.get('raw_region', 'audit_history')),
        }
    if not raw_best_payload and isinstance(ocr_results, dict):
        raw_best_score = -1.0
        for engine_name, payload in ocr_results.items():
            if not isinstance(payload, dict):
                continue
            engine_text = normalize_plate_text(payload.get('text', ''))
            if not engine_text:
                continue
            candidate_score = parse_float(payload.get('score', 0.0), 0.0)
            if candidate_score >= raw_best_score:
                raw_best_score = candidate_score
                raw_best_payload = {
                    'text': engine_text,
                    'engine': str(payload.get('engine', engine_name) or engine_name),
                    'score': float(candidate_score),
                    'avg_conf': float(parse_float(payload.get('avg_conf', 0.0), 0.0)),
                    'pattern': str(payload.get('pattern', detect_plate_pattern(engine_text))),
                    'region': str(payload.get('region', 'ocr_result')),
                }
    manual_confidence = parse_float(override.get('confidence', 100.0), 100.0)
    manual_score = parse_float(override.get('score', 100.0), 100.0)
    manual_weighted_support = parse_float(override.get('weighted_support', 100.0), 100.0)
    manual_candidate = {
        'text': manual_text,
        'score': manual_score,
        'avg_conf': manual_confidence,
        'pattern': manual_pattern,
        'region': 'manual_review',
        'support_count': 1,
        'support_engines': ['manual_review'],
        'agreement_ratio': 100.0,
        'weighted_support': manual_weighted_support,
        'best_law_score': 100.0,
        'engine_contributions': {'manual_review': manual_weighted_support},
        'engine_weights': {
            'manual_review': {
                'weight': 1.0,
                'factor': 1.0,
                'mode': 'manual',
                'reason': 'microcalibration_override',
            },
        },
        'engine': 'microcalibration_manual',
    }
    if isinstance(ocr_results, dict):
        ocr_results['microcalibration_manual'] = {
            'text': manual_text,
            'avg_conf': manual_confidence,
            'score': manual_score,
            'pattern': manual_pattern,
            'chars': [],
            'candidates': [dict(manual_candidate)],
            'engine': 'microcalibration_manual',
            'manual_override': True,
            'warning': 'microcalibration_manual_override',
        }
    if isinstance(top_candidates, list):
        top_candidates.insert(0, dict(manual_candidate))

    human_review = {
        'status': str(override.get('status', 'RATIFICADA_MANUALMENTE')),
        'decision': str(override.get('decision', 'CORRIGIDO_MANUAL')),
        'selected_candidate': str(raw_best_payload.get('text', '') or ''),
        'selected_candidate_engine': str(raw_best_payload.get('engine', '') or 'ocr'),
        'selected_candidate_score': float(raw_best_payload.get('score', 0.0) or 0.0),
        'selected_candidate_confidence': float(raw_best_payload.get('avg_conf', 0.0) or 0.0),
        'selected_candidate_support_count': int(raw_best_payload.get('support_count', 0) or 0),
        'selected_candidate_agreement_ratio': float(raw_best_payload.get('agreement_ratio', 0.0) or 0.0),
        'selected_candidate_region': str(raw_best_payload.get('region', '') or 'full_image'),
        'confirmed_text': manual_text,
        'operator': str(override.get('operator', 'microcalibracao_isolada')),
        'notes': str(override.get('notes', 'microcalibracao_isolada')),
        'reviewed_at_utc': str(override.get('reviewed_at_utc', utc_iso_now())),
        'microcalibration_match_key': str(override.get('match_key', '')),
        'microcalibration_source': str(override.get('source', 'manual_review')),
    }

    return {
        'override': override,
        'manual_text': manual_text,
        'manual_pattern': manual_pattern,
        'manual_candidate': manual_candidate,
        'human_review': human_review,
        'raw_best_payload': raw_best_payload,
    }


def build_assessment(best_payload, consensus, warnings, adulterado):
    reasons = []
    if best_payload:
        confidence = float(best_payload.get('avg_conf', 0))
        accepted = True
    else:
        confidence = 0.0
        accepted = False
        reasons.append('nenhum_resultado_aceito')

    agreement_ratio = float(consensus.get('agreement_ratio', 0))
    agreement_count = int(consensus.get('agreement_count', 0))
    engine_count = int(consensus.get('engines_considered', 0))

    if agreement_count <= 1 and engine_count >= 2:
        reasons.append('baixo_consenso_entre_motores')
    if confidence < OCR_MIN_CONFIDENCE:
        reasons.append('confianca_abaixo_limiar')
    if adulterado:
        reasons.append('suspeita_de_adulteracao_visual')
    if warnings:
        reasons.append('alertas_tecnicos_presentes')

    if accepted and confidence >= 90 and agreement_ratio >= 60 and not adulterado and not warnings:
        level = 'ALTA'
    elif accepted and (confidence >= 75 or (best_payload.get('pattern') != 'Indefinido' and confidence >= 45)) and agreement_ratio >= 40 and not adulterado:
        level = 'MEDIA'
    else:
        level = 'BAIXA'

    manual_review = level != 'ALTA' or adulterado or bool(warnings)
    if manual_review and 'revisao_humana_obrigatoria' not in reasons:
        reasons.append('revisao_humana_obrigatoria')

    return {
        'evidence_level': level,
        'confidence_percent': round(confidence, 1),
        'agreement_ratio_percent': round(agreement_ratio, 1),
        'manual_review_required': manual_review,
        'reasons': reasons,
    }


def _slot_mismatch_positions(text, slots):
    mismatches = []
    if len(text) != len(slots):
        return mismatches

    for index, char in enumerate(text):
        slot = slots[index]
        if slot == 'L' and not char.isalpha():
            mismatches.append(index + 1)
        elif slot == 'D' and not char.isdigit():
            mismatches.append(index + 1)
    return mismatches


def validate_plate_by_law(text):
    normalized = normalize_plate_text(text)
    pattern = detect_plate_pattern(normalized)
    violations = []

    if not normalized:
        violations.append('placa_ausente')
        return {
            'text': '',
            'detected_pattern': 'Indefinido',
            'is_valid': False,
            'law_score': 0.0,
            'violations': violations,
            'best_fit_pattern': 'Indefinido',
            'mismatch_positions': [],
        }

    if len(normalized) != 7:
        violations.append('tamanho_invalido')

    if re.search(r'[^A-Z0-9]', normalized):
        violations.append('caractere_invalido')

    old_slots = ['L', 'L', 'L', 'D', 'D', 'D', 'D']
    merc_slots = ['L', 'L', 'L', 'D', 'L', 'D', 'D']
    old_mismatch = _slot_mismatch_positions(normalized, old_slots)
    merc_mismatch = _slot_mismatch_positions(normalized, merc_slots)
    weighted_old_mismatch = sum(slot_weight_for_index(index - 1) for index in old_mismatch)
    weighted_merc_mismatch = sum(slot_weight_for_index(index - 1) for index in merc_mismatch)

    if weighted_old_mismatch <= weighted_merc_mismatch:
        best_fit = 'Antigo'
        mismatch_positions = old_mismatch
        mismatch_weight = weighted_old_mismatch
    else:
        best_fit = 'Mercosul'
        mismatch_positions = merc_mismatch
        mismatch_weight = weighted_merc_mismatch

    if pattern == 'Indefinido':
        violations.append('padrao_legal_nao_confirmado')

    if mismatch_positions:
        violations.append('inconsistencia_posicional')

    score = 100.0
    if len(normalized) != 7:
        score -= 28.0
    score -= min(42.0, mismatch_weight * 10.5)
    if pattern == 'Indefinido':
        score -= 22.0
    if re.search(r'[^A-Z0-9]', normalized):
        score -= 20.0
    score = max(0.0, min(100.0, score))

    return {
        'text': normalized,
        'detected_pattern': pattern,
        'is_valid': pattern != 'Indefinido' and len(normalized) == 7 and len(mismatch_positions) == 0,
        'law_score': round(score, 1),
        'violations': violations,
        'best_fit_pattern': best_fit,
        'mismatch_positions': mismatch_positions,
        'mismatch_weight': round(mismatch_weight, 2),
    }


def analyze_plate_quality(plate_img):
    if plate_img is None or getattr(plate_img, 'size', 0) == 0:
        return {
            'score': 0.0,
            'grade': 'CRITICA',
            'issues': ['imagem_invalida'],
            'metrics': {},
            'recommended_actions': ['reenviar_imagem'],
        }

    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    noise = float(np.std(gray.astype(np.float32) - cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)))
    underexposed_ratio = float(np.mean(gray <= 15) * 100.0)
    overexposed_ratio = float(np.mean(gray >= 245) * 100.0)
    edge_density = float(np.mean(cv2.Canny(gray, 80, 200) > 0) * 100.0)

    issues = []
    actions = []
    score = 100.0

    if lap_var < 90:
        issues.append('imagem_borrada')
        actions.append('aplicar_filtro_nitidez')
        score -= 28
    elif lap_var < 150:
        issues.append('nitidez_regular')
        score -= 12

    if contrast < 28:
        issues.append('baixo_contraste')
        actions.append('reforcar_contraste_local')
        score -= 20
    elif contrast < 40:
        issues.append('contraste_moderado')
        score -= 8

    if brightness < 70:
        issues.append('subexposicao')
        actions.append('corrigir_iluminacao')
        score -= 16
    elif brightness > 205:
        issues.append('superexposicao')
        actions.append('reduzir_brilho')
        score -= 16

    if overexposed_ratio > 12:
        issues.append('estouro_de_luz')
        score -= 10
    if underexposed_ratio > 18:
        issues.append('sombras_excessivas')
        score -= 10
    if noise > 26:
        issues.append('ruido_elevado')
        actions.append('aplicar_denoise')
        score -= 8
    if edge_density < 2.2:
        issues.append('poucos_contornos_uteis')
        score -= 10

    score = max(0.0, min(100.0, score))
    if score >= 85:
        grade = 'EXCELENTE'
    elif score >= 68:
        grade = 'BOA'
    elif score >= 48:
        grade = 'REGULAR'
    else:
        grade = 'CRITICA'

    if not actions:
        actions.append('nenhuma_correcao_critica')

    return {
        'score': round(score, 1),
        'grade': grade,
        'issues': issues,
        'metrics': {
            'brightness': round(brightness, 2),
            'contrast': round(contrast, 2),
            'sharpness_laplacian': round(lap_var, 2),
            'noise_level': round(noise, 2),
            'underexposed_ratio': round(underexposed_ratio, 2),
            'overexposed_ratio': round(overexposed_ratio, 2),
            'edge_density': round(edge_density, 2),
        },
        'recommended_actions': actions,
    }


def _is_char_confusable(char_a, char_b):
    if char_a == char_b:
        return False
    if DIGIT_SUBSTITUTIONS.get(char_a) == char_b:
        return True
    if DIGIT_SUBSTITUTIONS.get(char_b) == char_a:
        return True
    if LETTER_SUBSTITUTIONS.get(char_a) == char_b:
        return True
    if LETTER_SUBSTITUTIONS.get(char_b) == char_a:
        return True
    return False


def build_character_ambiguity_report(top_candidates):
    if not top_candidates:
        return {
            'ambiguous_positions': [],
            'ambiguity_count': 0,
            'ambiguity_score': 100.0,
        }

    normalized_candidates = []
    for candidate in top_candidates[:6]:
        if not isinstance(candidate, dict):
            continue
        text = normalize_plate_text(candidate.get('text', ''))
        if len(text) == 7:
            normalized_candidates.append(text)

    if not normalized_candidates:
        return {
            'ambiguous_positions': [],
            'ambiguity_count': 0,
            'ambiguity_score': 100.0,
        }

    anchor_text = normalized_candidates[0]
    slot_pattern = expected_slots(detect_plate_pattern(anchor_text)) if detect_plate_pattern(anchor_text) != 'Indefinido' else ['?', '?', '?', '?', '?', '?', '?']

    ambiguities = []
    for index in range(7):
        options = sorted({text[index] for text in normalized_candidates if len(text) == 7})
        if len(options) <= 1:
            continue

        confusable = any(_is_char_confusable(left, right) for left in options for right in options if left != right)
        ambiguities.append({
            'position': index + 1,
            'expected_slot': slot_pattern[index] if index < len(slot_pattern) else '?',
            'is_confusable': confusable,
        })

    ambiguity_score = max(0.0, 100.0 - (len(ambiguities) * 17.0))
    return {
        'ambiguous_positions': ambiguities,
        'ambiguity_count': len(ambiguities),
        'ambiguity_score': round(ambiguity_score, 1),
    }


def build_capture_integrity_summary(input_meta, plate_detection):
    input_meta = input_meta if isinstance(input_meta, dict) else {}
    input_security = input_meta.get('input_security', {})
    if not isinstance(input_security, dict):
        input_security = {}
    plate_detection = plate_detection if isinstance(plate_detection, dict) else {}

    input_status = str(input_security.get('status', 'indefinido') or 'indefinido')
    input_type = str(input_security.get('input_type', input_meta.get('input_type', 'indefinido')) or 'indefinido')
    extension = str(input_security.get('extension', '') or '')
    signature = str(input_security.get('detected_signature', '') or '')
    signature_ok = bool(input_security.get('signature_ok', True))
    file_size_mb = float(input_security.get('file_size_mb', 0.0))
    max_upload_mb = float(input_security.get('max_upload_mb', 0.0))
    allowed_extensions = input_security.get('allowed_extensions', [])
    if not isinstance(allowed_extensions, list):
        allowed_extensions = []
    warnings = input_security.get('warnings', [])
    if not isinstance(warnings, list):
        warnings = []

    plate_status = str(plate_detection.get('status', 'indefinido') or 'indefinido')
    selected_quality = float(plate_detection.get('selected_quality_score', 0.0))
    selected_score = float(plate_detection.get('selected_score', 0.0))
    candidate_count = int(plate_detection.get('candidate_count', 0))
    selected_region = str(plate_detection.get('selected_region', '-') or '-')
    selected_source = str(plate_detection.get('selected_source', '-') or '-')
    ocr_selected_region = str(plate_detection.get('ocr_selected_region', selected_region) or selected_region)
    ocr_selected_source = str(plate_detection.get('ocr_selected_source', selected_source) or selected_source)
    selected_aspect_ratio = float(plate_detection.get('selected_aspect_ratio', 0.0))
    selected_quality_label = str(plate_detection.get('selected_quality_label', 'indefinida') or 'indefinida')
    selected_plausibility_bonus = float(plate_detection.get('selected_plausibility_bonus', 0.0))
    used_full_image = bool(plate_detection.get('used_full_image'))
    shape_hint = str(plate_detection.get('selected_shape_hint', 'indefinida') or 'indefinida')
    style_context = extract_plate_style_context(plate_detection)
    style_hint = str(style_context.get('style_hint', 'indefinida') or 'indefinida')
    style_confidence = float(style_context.get('style_confidence', 0.0))
    ocr_mode = str(plate_detection.get('ocr_line_mode', 'single_line') or 'single_line')
    tesseract_whitelist = str(plate_detection.get('tesseract_whitelist', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') or '')

    issues = []
    score_breakdown = []
    integrity_score = 100.0

    def add_issue(code):
        if code not in issues:
            issues.append(code)

    def add_penalty(code, penalty, note):
        nonlocal integrity_score
        penalty = round(max(0.0, float(penalty)), 2)
        if penalty <= 0:
            return
        integrity_score = clamp_value(integrity_score - penalty, 0.0, 100.0)
        score_breakdown.append({
            'factor': code,
            'penalty': penalty,
            'note': str(note or ''),
            'score_after': round(integrity_score, 2),
        })

    if input_status not in ('ok', 'validado'):
        add_issue('entrada_nao_normalizada')
        add_penalty('input_status', CAPTURE_INTEGRITY_INPUT_PENALTY, f'status={input_status}')
    if warnings:
        add_issue('alertas_na_entrada')
        warning_penalty = min(len(warnings), CAPTURE_INTEGRITY_WARNING_LIMIT) * CAPTURE_INTEGRITY_WARNING_PENALTY
        add_penalty('input_warnings', warning_penalty, f'count={len(warnings)}')
    if not signature_ok:
        add_issue('assinatura_arquivo_suspeita')
        add_penalty('input_signature', CAPTURE_INTEGRITY_SIGNATURE_PENALTY, 'assinatura_nao_confere')
    if plate_status == 'sem_candidato':
        add_issue('detector_sem_roi_confiavel')
        add_penalty('plate_detection', CAPTURE_INTEGRITY_SEM_CANDIDATE_PENALTY, 'status=sem_candidato')
    elif plate_status == 'fallback_full_scene':
        add_issue('ocr_dependente_de_imagem_completa')
        add_penalty('plate_detection', CAPTURE_INTEGRITY_FALLBACK_PENALTY, 'status=fallback_full_scene')
    elif used_full_image:
        add_issue('ocr_dependente_de_imagem_completa')
        add_penalty('full_image', CAPTURE_INTEGRITY_FULL_IMAGE_PENALTY, 'ocr_executado_com_imagem_inteira')
    elif plate_status not in ('roi_detectado', 'ok', 'indefinido'):
        add_issue('detector_sem_roi_confiavel')
        add_penalty('plate_detection', CAPTURE_INTEGRITY_FALLBACK_PENALTY * 0.6, f'status={plate_status}')
    if selected_aspect_ratio > 0:
        if selected_aspect_ratio < PLATE_DETECTION_ASPECT_MIN or selected_aspect_ratio > PLATE_DETECTION_ASPECT_MAX:
            add_issue('proporcao_roi_inadequada')
            add_penalty('roi_aspect_ratio', 8.0, f'aspect={selected_aspect_ratio:.2f}')
        elif selected_aspect_ratio < (PLATE_DETECTION_ASPECT_TARGET - 1.2) or selected_aspect_ratio > (PLATE_DETECTION_ASPECT_TARGET + 1.2):
            add_issue('proporcao_roi_limite')
            add_penalty('roi_aspect_ratio', 3.5, f'aspect={selected_aspect_ratio:.2f}')
    if selected_quality_label == 'critica' and plate_status != 'sem_candidato':
        add_issue('qualidade_roi_critica')
        add_penalty('roi_quality_label', 4.0, 'quality_label=critica')
    if selected_plausibility_bonus < 0.0:
        add_issue('roi_pouco_plausivel')
        add_penalty('roi_plausibility', min(6.0, abs(selected_plausibility_bonus)), f'bonus={selected_plausibility_bonus:.1f}')
    if plate_status != 'sem_candidato' and selected_quality < CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD:
        add_issue('qualidade_roi_baixa')
        quality_gap = CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD - selected_quality
        quality_penalty = clamp_value(
            (quality_gap / max(1.0, CAPTURE_INTEGRITY_LOW_QUALITY_THRESHOLD)) * CAPTURE_INTEGRITY_LOW_QUALITY_MAX_PENALTY,
            0.0,
            CAPTURE_INTEGRITY_LOW_QUALITY_MAX_PENALTY,
        )
        add_penalty('roi_quality', quality_penalty, f'quality={selected_quality:.1f}')
    if candidate_count <= 0:
        if plate_status != 'sem_candidato':
            add_issue('detector_sem_roi_confiavel')
            add_penalty('candidate_count', CAPTURE_INTEGRITY_SEM_CANDIDATE_PENALTY * 0.5, 'candidate_count=0')
    elif candidate_count == 1:
        add_issue('poucos_candidatos_de_placa')
        add_penalty('candidate_count', CAPTURE_INTEGRITY_LOW_CANDIDATE_PENALTY, 'candidate_count=1')

    integrity_score = round(clamp_value(integrity_score, 0.0, 100.0), 2)
    if integrity_score >= 90:
        integrity_grade = 'EXCELENTE'
    elif integrity_score >= 80:
        integrity_grade = 'BOA'
    elif integrity_score >= 65:
        integrity_grade = 'REGULAR'
    elif integrity_score >= 50:
        integrity_grade = 'ATENCAO'
    else:
        integrity_grade = 'CRITICA'

    manual_review_recommended = bool(
        not signature_ok
        or plate_status == 'sem_candidato'
        or (CAPTURE_INTEGRITY_FALLBACK_ALWAYS_REVIEW and plate_status == 'fallback_full_scene')
        or integrity_score < CAPTURE_INTEGRITY_CRITICAL_THRESHOLD
    )
    if manual_review_recommended:
        status = 'revisao_obrigatoria'
    elif integrity_score < CAPTURE_INTEGRITY_REVIEW_THRESHOLD or issues:
        status = 'atencao'
    else:
        status = 'ok'

    breakdown_text = '; '.join([
        f"{entry.get('factor', '-')}"
        f":-{float(entry.get('penalty', 0.0)):.1f}"
        f"({entry.get('note', '-')})"
        for entry in score_breakdown
    ]) or '-'

    return {
        'status': status,
        'manual_review_recommended': manual_review_recommended,
        'integrity_score': integrity_score,
        'integrity_grade': integrity_grade,
        'integrity_review_threshold': round(CAPTURE_INTEGRITY_REVIEW_THRESHOLD, 2),
        'integrity_critical_threshold': round(CAPTURE_INTEGRITY_CRITICAL_THRESHOLD, 2),
        'issues': issues,
        'warnings': warnings,
        'score_breakdown': score_breakdown,
        'score_breakdown_text': breakdown_text,
        'input_status': input_status,
        'input_type': input_type,
        'input_extension': extension,
        'input_signature': signature,
        'input_signature_ok': signature_ok,
        'input_file_size_mb': round(file_size_mb, 2),
        'input_max_upload_mb': round(max_upload_mb, 2),
        'input_allowed_extensions': allowed_extensions,
        'plate_detection_status': plate_status,
        'plate_detection_selected_region': selected_region,
        'plate_detection_selected_source': selected_source,
        'plate_detection_calibration_source': str((plate_detection or {}).get('calibration_source', 'builtin_default')),
        'plate_detection_calibration_path': str((plate_detection or {}).get('calibration_path', PLATE_DETECTION_CALIBRATION_PATH)),
        'plate_detection_ocr_selected_region': ocr_selected_region,
        'plate_detection_ocr_selected_source': ocr_selected_source,
        'plate_detection_selected_aspect_ratio': round(selected_aspect_ratio, 3),
        'plate_detection_selected_quality_label': selected_quality_label,
        'plate_detection_selected_plausibility_bonus': round(selected_plausibility_bonus, 1),
        'plate_detection_candidate_count': candidate_count,
        'plate_detection_selected_quality_score': round(selected_quality, 2),
        'plate_detection_selected_score': round(selected_score, 2),
        'plate_detection_shape_hint': shape_hint,
        'plate_detection_style_hint': style_hint,
        'plate_detection_style_confidence': round(style_confidence, 1),
        'plate_detection_used_full_image': used_full_image,
        'plate_detection_ocr_mode': ocr_mode,
        'plate_detection_tesseract_whitelist': tesseract_whitelist,
        'summary': f'Integridade da captura {integrity_score:.1f}/100 ({integrity_grade})' + (f" - {', '.join(issues[:3])}" if issues else ''),
    }


def build_pericial_report(best_payload, top_candidates, ocr_results, consensus, quality_report, warnings, input_meta=None):
    best_text = normalize_plate_text((best_payload or {}).get('text', ''))
    legal_validation = validate_plate_by_law(best_text)
    ambiguity = build_character_ambiguity_report(top_candidates)
    input_meta = input_meta if isinstance(input_meta, dict) else {}
    plate_detection = input_meta.get('plate_detection', {})
    if not isinstance(plate_detection, dict):
        plate_detection = {}
    capture_integrity = build_capture_integrity_summary(input_meta, plate_detection)
    capture_integrity_status = str(capture_integrity.get('status', 'indefinido'))
    style_context = extract_plate_style_context(plate_detection)
    selected_style_hint = str(style_context.get('style_hint', 'indefinida') or 'indefinida')
    selected_style_confidence = float(style_context.get('style_confidence', 0.0))

    active_methods = [
        engine for engine, result in ocr_results.items()
        if isinstance(result, dict) and normalize_plate_text(result.get('text', ''))
    ]

    checklist = {
        'image_quality_checked': bool(quality_report),
        'legal_pattern_checked': True,
        'character_ambiguity_checked': True,
        'multi_engine_consensus_checked': True,
        'technical_warnings_checked': True,
        'capture_integrity_checked': True,
    }

    critical_findings = []
    if quality_report.get('score', 0) < 48:
        critical_findings.append('qualidade_imagem_critica')
    if not legal_validation.get('is_valid'):
        critical_findings.append('padrao_legal_nao_confirmado')
    detected_pattern = str(legal_validation.get('detected_pattern', 'Indefinido'))
    if (
        selected_style_hint in ('mercosul', 'antigo')
        and detected_pattern in ('Mercosul', 'Antigo')
        and selected_style_confidence >= 65.0
        and selected_style_hint.title() != detected_pattern
    ):
        critical_findings.append('estilo_placa_incompativel')
    if ambiguity.get('ambiguity_count', 0) >= 2:
        critical_findings.append('alta_ambiguidade_de_caracteres')
    if float(consensus.get('agreement_ratio', 0)) < 40:
        critical_findings.append('baixo_consenso_entre_motores')
    if warnings:
        critical_findings.append('alertas_tecnicos')
    if capture_integrity.get('manual_review_recommended'):
        critical_findings.append('integridade_da_captura_comprometida')

    if critical_findings:
        status = 'REVISAO_OBRIGATORIA'
    elif legal_validation.get('is_valid') and quality_report.get('score', 0) >= 68 and capture_integrity_status == 'ok':
        status = 'VALIDACAO_TECNICA_FORTE'
    elif legal_validation.get('is_valid') and quality_report.get('score', 0) >= 60:
        status = 'VALIDACAO_TECNICA_PARCIAL'
    else:
        status = 'VALIDACAO_TECNICA_PARCIAL'

    return {
        'status': status,
        'quality': quality_report,
        'legal_validation': legal_validation,
        'character_ambiguity': ambiguity,
        'capture_integrity': capture_integrity,
        'active_methods': active_methods,
        'method_count': len(active_methods),
        'checklist': checklist,
        'critical_findings': critical_findings,
        'cross_checks': {
            'engine_consensus_ratio': round(float(consensus.get('agreement_ratio', 0)), 1),
            'capture_integrity': capture_integrity,
            'plate_detection': {
                'status': str(plate_detection.get('status', 'indefinido')),
                'strategy': str(plate_detection.get('strategy', 'plate_roi_first')),
                'selected_region': str(plate_detection.get('selected_region', '-')),
                'selected_source': str(plate_detection.get('selected_source', '-')),
                'ocr_selected_region': str(plate_detection.get('ocr_selected_region', '-')),
                'ocr_selected_source': str(plate_detection.get('ocr_selected_source', '-')),
                'selected_aspect_ratio': float(plate_detection.get('selected_aspect_ratio', 0.0)),
                'selected_quality_label': str(plate_detection.get('selected_quality_label', 'indefinida')),
                'selected_plausibility_bonus': float(plate_detection.get('selected_plausibility_bonus', 0.0)),
                'candidate_count': int(plate_detection.get('candidate_count', 0)),
                'selected_quality_score': float(plate_detection.get('selected_quality_score', 0.0)),
                'selected_score': float(plate_detection.get('selected_score', 0.0)),
                'selected_shape_hint': str(plate_detection.get('selected_shape_hint', 'indefinida')),
                'selected_style_hint': selected_style_hint,
                'selected_style_confidence': selected_style_confidence,
                'used_full_image': bool(plate_detection.get('used_full_image')),
                'ocr_line_mode': str(plate_detection.get('ocr_line_mode', 'single_line')),
            },
            'external_source': {'status': 'pendente_no_php'},
            'local_history': {'status': 'pendente_no_php'},
        },
    }


def merge_assessment_with_pericial(assessment, pericial):
    merged = dict(assessment or {})
    reasons = list(merged.get('reasons', []))

    legal_ok = bool((pericial or {}).get('legal_validation', {}).get('is_valid'))
    quality_score = float((pericial or {}).get('quality', {}).get('score', 0))
    critical = list((pericial or {}).get('critical_findings', []))
    capture_integrity = (pericial or {}).get('capture_integrity', {})
    if not isinstance(capture_integrity, dict):
        capture_integrity = {}
    capture_score = float(capture_integrity.get('integrity_score', 100))
    capture_status = str(capture_integrity.get('status', 'indefinido'))

    evidence = str(merged.get('evidence_level', 'BAIXA'))
    if not legal_ok:
        if 'padrao_legal_nao_confirmado' not in reasons:
            reasons.append('padrao_legal_nao_confirmado')
        if evidence == 'ALTA':
            evidence = 'MEDIA'
        elif evidence == 'MEDIA':
            evidence = 'BAIXA'

    if quality_score < 48:
        if 'qualidade_imagem_critica' not in reasons:
            reasons.append('qualidade_imagem_critica')
        evidence = 'BAIXA'

    if capture_status == 'revisao_obrigatoria' or capture_score < CAPTURE_INTEGRITY_CRITICAL_THRESHOLD:
        if 'integridade_da_captura_comprometida' not in reasons:
            reasons.append('integridade_da_captura_comprometida')
        evidence = 'BAIXA'
    elif capture_status == 'atencao' or capture_score < CAPTURE_INTEGRITY_REVIEW_THRESHOLD:
        if 'integridade_da_captura_em_atencao' not in reasons:
            reasons.append('integridade_da_captura_em_atencao')
        if evidence == 'ALTA':
            evidence = 'MEDIA'
        elif evidence == 'MEDIA':
            evidence = 'BAIXA'

    if critical:
        if 'achados_periciais_criticos' not in reasons:
            reasons.append('achados_periciais_criticos')
        merged['manual_review_required'] = True

    merged['evidence_level'] = evidence
    merged['reasons'] = reasons
    return merged


def build_forensic_chain(analysis_id, source_path, plate_path, started_utc, finished_utc):
    source_hash = sha256_file(source_path)
    plate_hash = sha256_file(plate_path)
    payload = {
        'analysis_id': analysis_id,
        'started_at_utc': started_utc,
        'finished_at_utc': finished_utc,
        'source_sha256': source_hash,
        'plate_sha256': plate_hash,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    if CHAIN_SIGNING_KEY:
        signature = hmac.new(CHAIN_SIGNING_KEY.encode('utf-8'), serialized, hashlib.sha256).hexdigest()
        algorithm = 'HMAC-SHA256'
    else:
        signature = hashlib.sha256(serialized).hexdigest()
        algorithm = 'SHA256'

    payload['signature'] = signature
    payload['signature_algorithm'] = algorithm
    return payload


def coerce_brazilian_plate(text):
    text = ALNUM_ONLY.sub('', (text or '').upper())
    if len(text) != 7:
        return text

    chars = list(text)
    # PosiÃ§Ãµes 0, 1 e 2 devem ser letras
    for i in range(3):
        if chars[i] in LETTER_SUBSTITUTIONS:
            chars[i] = LETTER_SUBSTITUTIONS[chars[i]]

    # PosiÃ§Ã£o 3 deve ser nÃºmero
    if chars[3] in DIGIT_SUBSTITUTIONS:
        chars[3] = DIGIT_SUBSTITUTIONS[chars[3]]

    # PosiÃ§Ã£o 4 pode ser letra (Mercosul) ou nÃºmero (Antigo) - mantemos natural

    # PosiÃ§Ãµes 5 e 6 devem ser nÃºmeros
    for i in range(5, 7):
        if chars[i] in DIGIT_SUBSTITUTIONS:
            chars[i] = DIGIT_SUBSTITUTIONS[chars[i]]

    return "".join(chars)

def normalize_plate_text(text):
    return coerce_brazilian_plate(text)


def detect_plate_pattern(text):
    if MERCOSUL_PATTERN.match(text):
        return 'Mercosul'
    if OLD_PATTERN.match(text):
        return 'Antigo'
    return 'Indefinido'


def is_plate_like_text(text, require_digit=True):
    cleaned = normalize_plate_text(text)
    if not cleaned or len(cleaned) < 5 or len(cleaned) > 8:
        return False

    if detect_plate_pattern(cleaned) in ('Mercosul', 'Antigo'):
        return True

    if require_digit and not any(char.isdigit() for char in cleaned):
        return False

    return any(char.isdigit() for char in cleaned)


def extract_plate_style_context(plate_detection=None, fallback_metrics=None):
    metrics = {}
    if isinstance(plate_detection, dict):
        selected_metrics = plate_detection.get('selected_metrics', {})
        if isinstance(selected_metrics, dict):
            metrics = dict(selected_metrics)
        ocr_selected_metrics = plate_detection.get('ocr_selected_metrics', {})
        if (
            (not metrics or str(metrics.get('style_hint', 'indefinida') or 'indefinida').strip().lower() == 'indefinida')
            and isinstance(ocr_selected_metrics, dict)
            and ocr_selected_metrics
        ):
            metrics = dict(ocr_selected_metrics)
        if not metrics or str(metrics.get('style_hint', 'indefinida') or 'indefinida').strip().lower() == 'indefinida':
            # Some process payloads expose the style hint at the summary level
            # instead of inside selected_metrics, so accept either shape.
            top_level_style_hint = str(
                plate_detection.get('selected_style_hint')
                or plate_detection.get('ocr_selected_style_hint')
                or plate_detection.get('plate_detection_style_hint')
                or plate_detection.get('style_hint')
                or 'indefinida'
            ).strip().lower()
            if top_level_style_hint in ('mercosul', 'antigo'):
                metrics = dict(metrics)
                metrics['style_hint'] = top_level_style_hint
                metrics['style_confidence'] = parse_float(
                    plate_detection.get(
                        'selected_style_confidence',
                        plate_detection.get('ocr_selected_style_confidence', plate_detection.get('plate_detection_style_confidence', plate_detection.get('style_confidence', metrics.get('style_confidence', 0.0)))),
                    ),
                    0.0,
                )
    if not metrics and isinstance(fallback_metrics, dict):
        metrics = dict(fallback_metrics)

    style_hint = str(metrics.get('style_hint', 'indefinida') or 'indefinida').strip().lower()
    if style_hint not in ('mercosul', 'antigo'):
        style_hint = 'indefinida'

    return {
        'style_hint': style_hint,
        'style_confidence': max(0.0, min(100.0, parse_float(metrics.get('style_confidence', 0.0), 0.0))),
        'color_saturation': max(0.0, parse_float(metrics.get('color_saturation', 0.0), 0.0)),
        'gray_ratio': max(0.0, parse_float(metrics.get('gray_ratio', 0.0), 0.0)),
        'white_ratio': max(0.0, parse_float(metrics.get('white_ratio', 0.0), 0.0)),
        'blue_ratio': max(0.0, parse_float(metrics.get('blue_ratio', 0.0), 0.0)),
        'blue_band_ratio': max(0.0, parse_float(metrics.get('blue_band_ratio', 0.0), 0.0)),
        'style_strength': max(0.0, parse_float(metrics.get('style_strength', 0.0), 0.0)),
        'style_competing_strength': max(0.0, parse_float(metrics.get('style_competing_strength', 0.0), 0.0)),
    }


def build_plate_pattern_info(best_payload=None, legal_validation=None, fallback_text='', plate_detection=None):
    legal = legal_validation if isinstance(legal_validation, dict) else {}
    detected = str(legal.get('detected_pattern', '')).strip()
    best_fit = str(legal.get('best_fit_pattern', '')).strip()

    if detected not in ('Mercosul', 'Antigo'):
        if best_fit in ('Mercosul', 'Antigo'):
            detected = best_fit
        else:
            best = best_payload if isinstance(best_payload, dict) else {}
            best_pattern = str(best.get('pattern', '')).strip()
            if best_pattern in ('Mercosul', 'Antigo'):
                detected = best_pattern
            else:
                text = normalize_plate_text(str(best.get('text', fallback_text)))
                guessed = detect_plate_pattern(text)
                detected = guessed if guessed in ('Mercosul', 'Antigo') else 'Indefinido'

    if detected == 'Mercosul':
        category = 'mercosul'
    elif detected == 'Antigo':
        category = 'antigo'
    else:
        category = 'indefinido'

    style_context = extract_plate_style_context(plate_detection)
    return {
        'padrao_placa': detected if detected else 'Indefinido',
        'categoria': category,
        'style_hint': style_context['style_hint'],
        'style_confidence': style_context['style_confidence'],
    }


def rotate_image(image, angle):
    if image is None or abs(angle) < 0.001:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def pad_plate_image(img, border_ratio=0.08):
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    height, width = img.shape[:2]
    border = max(4, int(round(min(height, width) * float(border_ratio))))
    border = min(border, max(8, min(height, width) // 3))
    if border <= 0:
        return img

    return cv2.copyMakeBorder(img, border, border, border, border, cv2.BORDER_REPLICATE)


def estimate_plate_skew_angle(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return 0.0

    if len(img.shape) == 2:
        gray = img
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        11,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    threshold = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, kernel, iterations=1)

    points = cv2.findNonZero(threshold)
    if points is None or len(points) < 24:
        return 0.0

    rect = cv2.minAreaRect(points)
    angle = float(rect[-1])
    if angle < -45.0:
        angle += 90.0
    if angle > 45.0:
        angle -= 90.0

    if abs(angle) < 0.8 or abs(angle) > 18.0:
        return 0.0
    return round(float(angle), 2)


def deskew_plate_image(img):
    angle = estimate_plate_skew_angle(img)
    if abs(angle) < 0.75:
        return img, 0.0
    return rotate_image(img, -angle), angle


def crop_image_from_box(img, box):
    if plate_geometry_module is not None:
        box_w = 0
        box_h = 0
        if isinstance(box, dict) and {'x', 'y', 'w', 'h'}.issubset(box):
            box_w = max(0, int(round(float(box.get('w', 0)))))
            box_h = max(0, int(round(float(box.get('h', 0)))))
        elif isinstance(box, dict) and {'xmin', 'ymin', 'xmax', 'ymax'}.issubset(box):
            box_w = max(0, int(round(float(box.get('xmax', 0)) - float(box.get('xmin', 0)))))
            box_h = max(0, int(round(float(box.get('ymax', 0)) - float(box.get('ymin', 0)))))
        adaptive_pad = plate_crop_pad_ratio(min(box_w, box_h), base_ratio=PLATE_CROP_PAD_RATIO)
        return plate_geometry_module.crop_axis_aligned_box(
            img,
            box,
            pad_ratio=adaptive_pad,
            min_size=(PLATE_CROP_MIN_WIDTH, PLATE_CROP_MIN_HEIGHT),
        )

    if not box or img is None:
        return None

    if {'x', 'y', 'w', 'h'}.issubset(box):
        x1 = int(box['x'])
        y1 = int(box['y'])
        x2 = x1 + int(box['w'])
        y2 = y1 + int(box['h'])
    elif {'xmin', 'ymin', 'xmax', 'ymax'}.issubset(box):
        x1 = int(box['xmin'])
        y1 = int(box['ymin'])
        x2 = int(box['xmax'])
        y2 = int(box['ymax'])
    else:
        return None

    height, width = img.shape[:2]
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1))
    y2 = max(0, min(height, y2))

    if x2 <= x1 or y2 <= y1:
        return None
    box_w = x2 - x1
    box_h = y2 - y1
    adaptive_pad = plate_crop_pad_ratio(min(box_w, box_h), base_ratio=PLATE_CROP_PAD_RATIO)
    pad_x = int(round(box_w * adaptive_pad))
    pad_y = int(round(box_h * adaptive_pad))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)
    crop = img[y1:y2, x1:x2]
    if crop is None or getattr(crop, 'size', 0) == 0:
        return None
    if crop.shape[0] < PLATE_CROP_MIN_HEIGHT or crop.shape[1] < PLATE_CROP_MIN_WIDTH:
        return None
    return crop


def plate_recognizer_variant_quality_score(variant_img):
    if variant_img is None or getattr(variant_img, 'size', 0) == 0:
        return 0.0

    if len(variant_img.shape) == 2:
        gray = variant_img
    else:
        gray = cv2.cvtColor(variant_img, cv2.COLOR_BGR2GRAY)

    contrast = float(np.std(gray))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    p95, p5 = np.percentile(gray, [95, 5])
    dynamic_range = float(p95 - p5)
    exposure = float(np.mean((gray >= 24) & (gray <= 238)))

    score = (
        (min(74.0, contrast) / 74.0) * 0.31
        + (min(420.0, blur) / 420.0) * 0.33
        + (min(176.0, dynamic_range) / 176.0) * 0.24
        + (exposure * 0.12)
    )

    if contrast < 18.0:
        score *= 0.74
    if blur < 36.0:
        score *= 0.76

    return max(0.0, min(1.0, float(score)))


def build_plate_recognizer_variant_inputs(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return []

    if len(img.shape) == 2:
        base_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        base_img = img

    variants = []
    signatures = set()

    def add_variant(variant_name, variant_img):
        if variant_img is None or getattr(variant_img, 'size', 0) == 0:
            return
        if len(variant_img.shape) == 2:
            candidate = cv2.cvtColor(variant_img, cv2.COLOR_GRAY2BGR)
        else:
            candidate = variant_img

        signature = (
            candidate.shape[0],
            candidate.shape[1],
            int(float(np.mean(candidate))),
            int(float(np.std(candidate))),
        )
        if signature in signatures:
            return
        signatures.add(signature)
        quality = plate_recognizer_variant_quality_score(candidate)
        variants.append((variant_name, candidate, quality))

    add_variant('scene_raw', base_img)

    if PLATE_RECOGNIZER_DYNAMIC_VARIANTS:
        gray = cv2.cvtColor(base_img, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        ycrcb = cv2.cvtColor(base_img, cv2.COLOR_BGR2YCrCb)
        ycrcb[:, :, 0] = cv2.equalizeHist(ycrcb[:, :, 0])
        add_variant('scene_equalized', cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR))

        if contrast < 44.0:
            add_variant('scene_high_contrast', cv2.convertScaleAbs(base_img, alpha=1.24, beta=10))

        if brightness < 106.0:
            add_variant('scene_bright_boost', cv2.convertScaleAbs(base_img, alpha=1.14, beta=20))
        elif brightness > 192.0:
            add_variant('scene_dark_balance', cv2.convertScaleAbs(base_img, alpha=0.88, beta=-18))

        if blur < 132.0:
            sharpen_kernel = np.array([[0, -1, 0], [-1, 6, -1], [0, -1, 0]])
            add_variant('scene_sharpen', cv2.filter2D(base_img, -1, sharpen_kernel))

        if contrast < 58.0 or blur < 180.0:
            denoised = cv2.fastNlMeansDenoisingColored(base_img, None, 8, 8, 7, 21)
            add_variant('scene_denoised', denoised)

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()
    for preferred_name in ('scene_raw', 'scene_equalized'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= PLATE_RECOGNIZER_MAX_VARIANTS:
            break

    return selected[:PLATE_RECOGNIZER_MAX_VARIANTS]


def normalize_plate_recognizer_box(raw_box):
    if not isinstance(raw_box, dict):
        return None

    if {'x', 'y', 'w', 'h'}.issubset(raw_box):
        x1 = int(round(parse_float(raw_box.get('x'), 0.0)))
        y1 = int(round(parse_float(raw_box.get('y'), 0.0)))
        width = int(round(parse_float(raw_box.get('w'), 0.0)))
        height = int(round(parse_float(raw_box.get('h'), 0.0)))
        x2 = x1 + width
        y2 = y1 + height
    elif {'xmin', 'ymin', 'xmax', 'ymax'}.issubset(raw_box):
        x1 = int(round(parse_float(raw_box.get('xmin'), 0.0)))
        y1 = int(round(parse_float(raw_box.get('ymin'), 0.0)))
        x2 = int(round(parse_float(raw_box.get('xmax'), 0.0)))
        y2 = int(round(parse_float(raw_box.get('ymax'), 0.0)))
    elif {'x1', 'y1', 'x2', 'y2'}.issubset(raw_box):
        x1 = int(round(parse_float(raw_box.get('x1'), 0.0)))
        y1 = int(round(parse_float(raw_box.get('y1'), 0.0)))
        x2 = int(round(parse_float(raw_box.get('x2'), 0.0)))
        y2 = int(round(parse_float(raw_box.get('y2'), 0.0)))
    else:
        return None

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = max(0, x2)
    y2 = max(0, y2)
    if x2 <= x1 or y2 <= y1:
        return None

    return {
        'xmin': x1,
        'ymin': y1,
        'xmax': x2,
        'ymax': y2,
        'x': x1,
        'y': y1,
        'w': x2 - x1,
        'h': y2 - y1,
    }


def plate_recognizer_confidence_hint(text, raw_score, raw_dscore):
    score = parse_float(raw_score, 0.0)
    dscore = parse_float(raw_dscore, 0.0)

    if score <= 1.0:
        score *= 100.0
    if dscore <= 1.0:
        dscore *= 100.0

    confidence = max(score, dscore * 0.93)
    confidence = max(8.0, min(99.0, confidence))

    if len(text) == 7:
        confidence += 7.0
    else:
        confidence -= abs(7 - len(text)) * 3.0

    pattern = detect_plate_pattern(text)
    if pattern != 'Indefinido':
        confidence += 13.0
    else:
        confidence -= 8.0

    digits = sum(char.isdigit() for char in text)
    letters = sum(char.isalpha() for char in text)
    if digits >= 2 and letters >= 3:
        confidence += 3.0

    return max(4.0, min(99.0, confidence))


def plate_recognizer_api_request(variant_img, filename_hint):
    if variant_img is None or getattr(variant_img, 'size', 0) == 0:
        return None, 'empty_variant'

    try:
        encoded_ok, encoded = cv2.imencode('.jpg', variant_img, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
        if not encoded_ok:
            return None, 'encode_failed'
        response = requests.post(
            'https://api.platerecognizer.com/v1/plate-reader/',
            files={'upload': (filename_hint, encoded.tobytes(), 'image/jpeg')},
            headers={'Authorization': f'Token {PLATE_RECOGNIZER_TOKEN}'},
            timeout=PLATE_RECOGNIZER_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, f'request_error:{exc}'

    if response.status_code != 200:
        return None, f'http_{response.status_code}'

    try:
        return response.json(), None
    except ValueError:
        return None, 'invalid_json'


def parse_plate_recognizer_entries(payload):
    entries = []
    chars = []
    boxes_by_text = {}
    fallback_box = None
    best_box_conf = 0.0

    results = payload.get('results', []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        results = []

    for result in results[:PLATE_RECOGNIZER_TOP_RESULTS]:
        if not isinstance(result, dict):
            continue
        text = normalize_plate_text(result.get('plate', ''))
        if len(text) < 5:
            continue

        score_raw = parse_float(result.get('score'), 0.0)
        dscore_raw = parse_float(result.get('dscore'), 0.0)
        confidence = plate_recognizer_confidence_hint(text, score_raw, dscore_raw)
        if detect_plate_pattern(text) != 'Indefinido':
            confidence = min(99.0, confidence + 2.5)

        entries.append({'word': text, 'conf': float(confidence)})
        chars.extend([(char, float(confidence)) for char in text])

        box = normalize_plate_recognizer_box(result.get('box'))
        if box:
            previous = boxes_by_text.get(text)
            if previous is None or float(confidence) > float(previous.get('confidence', 0.0)):
                boxes_by_text[text] = {'box': box, 'confidence': float(confidence)}
            if float(confidence) > float(best_box_conf):
                best_box_conf = float(confidence)
                fallback_box = box

    return entries, chars, boxes_by_text, fallback_box


def is_plate_recognizer_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))
    score_gap_top2 = float(candidate.get('score_gap_top2', 99.0))

    if variant_hits < PLATE_RECOGNIZER_MIN_VARIANT_HITS and score_gap_top2 < 2.0 and avg_conf < (PLATE_RECOGNIZER_MIN_ACCEPT_CONF + 8.0):
        return False

    if pattern != 'Indefinido':
        if (
            score >= PLATE_RECOGNIZER_PATTERN_MIN_SCORE
            and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE
            and (
                variant_hits >= PLATE_RECOGNIZER_MIN_VARIANT_HITS
                or (score >= PLATE_RECOGNIZER_PATTERN_MIN_SCORE + 14.0 and score_gap_top2 >= 2.6)
            )
        ):
            return True
        if (
            score >= max(PLATE_RECOGNIZER_PATTERN_MIN_SCORE + 8.0, PLATE_RECOGNIZER_MIN_ACCEPT_SCORE + 10.0)
            and avg_conf >= PLATE_RECOGNIZER_MIN_ACCEPT_CONF
        ):
            return True
        if (
            score >= PLATE_RECOGNIZER_PATTERN_MIN_SCORE + 4.0
            and hits >= 2
            and avg_conf >= PLATE_RECOGNIZER_MIN_ACCEPT_CONF
            and (variant_hits >= PLATE_RECOGNIZER_MIN_VARIANT_HITS or score_gap_top2 >= 3.2)
        ):
            return True
        return False

    if (
        score >= PLATE_RECOGNIZER_MIN_ACCEPT_SCORE
        and avg_conf >= PLATE_RECOGNIZER_MIN_ACCEPT_CONF
        and variant_hits >= PLATE_RECOGNIZER_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_plate_recognizer_variant_rankings(variant_rankings, char_conf_map, boxes_by_text):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if is_plate_like_text(vote_text):
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if not is_plate_like_text(text):
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.2
            if pattern != 'Indefinido':
                quality_bonus += 0.3
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * PLATE_RECOGNIZER_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(6.8, disagreement * 1.45)
        if pattern == 'Indefinido' and variant_hits < PLATE_RECOGNIZER_MIN_VARIANT_HITS:
            conflict_penalty += 2.8

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }
    score_gap_top2 = (
        float(best.get('score', 0.0)) - float(ranked[1].get('score', 0.0))
        if len(ranked) > 1
        else 99.0
    )
    response['score_gap_top2'] = round(float(score_gap_top2), 2)
    best_for_reliability = dict(best)
    best_for_reliability['score_gap_top2'] = response['score_gap_top2']

    if not is_plate_recognizer_candidate_reliable(best_for_reliability):
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'plate_recognizer_low_reliability_abstained'
    else:
        text_key = normalize_plate_text(best.get('text', ''))
        box_meta = boxes_by_text.get(text_key)
        if box_meta and box_meta.get('box'):
            response['box'] = box_meta.get('box')
    return response


def detect_plate_pr_api(filepath):
    if not PLATE_RECOGNIZER_TOKEN:
        return None, None

    image = cv2.imread(filepath)
    if image is None:
        return None, {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'warning': 'plate_recognizer_image_load_failed'}

    variant_inputs = build_plate_recognizer_variant_inputs(image)
    if not variant_inputs:
        return None, {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'warning': 'plate_recognizer_no_variants'}

    warnings = []
    char_conf = defaultdict(float)
    variant_rankings = []
    boxes_by_text = {}
    fallback_box = None
    fallback_box_conf = 0.0
    base_filename = sanitize_filename(os.path.basename(filepath) or 'scene.jpg')

    for variant_name, variant_img, variant_quality in variant_inputs:
        filename_hint = sanitize_filename(f'{os.path.splitext(base_filename)[0]}_{variant_name}.jpg')
        payload, error = plate_recognizer_api_request(variant_img, filename_hint)
        if error:
            warnings.append(f'{variant_name}:{error}')
            continue

        entries, chars, variant_boxes_by_text, variant_fallback_box = parse_plate_recognizer_entries(payload)
        if not entries:
            continue

        for text, meta in variant_boxes_by_text.items():
            if not isinstance(meta, dict):
                continue
            existing = boxes_by_text.get(text)
            if existing is None or float(meta.get('confidence', 0.0)) > float(existing.get('confidence', 0.0)):
                boxes_by_text[text] = meta

        if variant_fallback_box:
            variant_best_conf = max(
                [float(meta.get('confidence', 0.0)) for meta in variant_boxes_by_text.values()] or [0.0]
            )
            if variant_best_conf > fallback_box_conf:
                fallback_box_conf = variant_best_conf
                fallback_box = variant_fallback_box

        for char, conf in chars:
            if conf > char_conf[char]:
                char_conf[char] = conf

        ranked = rank_ocr_candidates_from_entries(entries, variant_name, PLATE_RECOGNIZER_HIT_BONUS)
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = round(float(variant_quality), 4)
        ranked['chars'] = chars
        variant_rankings.append(ranked)

        if (
            ranked.get('pattern', 'Indefinido') != 'Indefinido'
            and len(normalize_plate_text(ranked.get('text', ''))) >= 6
            and float(ranked.get('score', 0)) >= (PLATE_RECOGNIZER_PATTERN_MIN_SCORE + 12.0)
            and len(variant_rankings) >= max(2, PLATE_RECOGNIZER_MIN_VARIANT_HITS)
        ):
            break

    if not variant_rankings:
        payload = {
            'text': '',
            'avg_conf': 0,
            'score': 0,
            'pattern': 'Indefinido',
            'chars': [],
            'candidates': [],
        }
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return fallback_box, payload

    merged = merge_plate_recognizer_variant_rankings(variant_rankings, char_conf, boxes_by_text)
    merged['region'] = 'plate_recognizer_api'
    if warnings:
        warning_tail = ';'.join(warnings[:2])
        existing = str(merged.get('warning', '') or '').strip()
        merged['warning'] = f'{existing};{warning_tail}' if existing else warning_tail

    detected_box = merged.get('box')
    if not isinstance(detected_box, dict):
        detected_box = fallback_box
    return detected_box, merged


def _extract_ranked_label(candidates):
    if isinstance(candidates, (str, int, float)):
        candidates = [str(candidates)]
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not isinstance(candidates, list):
        candidates = []

    best_name = ''
    best_conf = 0.0
    for item in candidates[:EXTERNAL_COMPARE_MAX_CANDIDATES]:
        if isinstance(item, str):
            name = str(item).strip()
            confidence = 0.0
        elif isinstance(item, dict):
            name = str(item.get('name', item.get('label', item.get('value', '')))).strip()
            confidence = parse_float(item.get('confidence', item.get('score', 0.0)), 0.0)
            if confidence <= 1.0:
                confidence *= 100.0
        else:
            continue

        if not name:
            continue
        if confidence > best_conf or not best_name:
            best_name = name
            best_conf = confidence

    return {'name': best_name, 'confidence': round(max(0.0, min(100.0, best_conf)), 2)}


def _pick_payload_root(payload):
    root = payload if isinstance(payload, dict) else {}
    if not root:
        return {}

    for key in ('result', 'data', 'results'):
        item = root.get(key)
        if isinstance(item, dict) and item:
            return item
        if isinstance(item, list) and item:
            first = item[0]
            if isinstance(first, dict):
                return first
    return root


def _parse_generic_vehicle_fields(payload_root):
    root = payload_root if isinstance(payload_root, dict) else {}
    vehicle = root.get('vehicle', {})
    if not isinstance(vehicle, dict):
        vehicle = {}

    make_raw = (
        vehicle.get('make')
        or vehicle.get('manufacturer')
        or root.get('make')
        or root.get('fabricante')
        or root.get('marca')
        or ''
    )
    model_raw = (
        vehicle.get('make_model')
        or vehicle.get('model')
        or root.get('model')
        or root.get('modelo')
        or ''
    )
    color_raw = vehicle.get('color') or root.get('color') or root.get('cor') or ''
    year_raw = vehicle.get('year') or root.get('year') or root.get('ano') or ''
    body_raw = vehicle.get('body_type') or root.get('body_type') or root.get('categoria') or ''

    make = _extract_ranked_label(make_raw)
    model = _extract_ranked_label(model_raw)
    color = _extract_ranked_label(color_raw)
    year = _extract_ranked_label(year_raw)
    body = _extract_ranked_label(body_raw)

    mapped = {
        'fabricante': make['name'],
        'modelo': model['name'],
        'cor': color['name'],
        'ano': year['name'],
        'tipo_carroceria': body['name'],
        'confianca_fabricante': make['confidence'],
        'confianca_modelo': model['confidence'],
        'confianca_cor': color['confidence'],
        'confianca_ano': year['confidence'],
    }
    return {key: value for key, value in mapped.items() if str(value).strip() != ''}


def _run_openalpr_comparison(scene_img):
    base = {
        'id': 'openalpr_carcheck',
        'nome': 'Rekor CarCheck / OpenALPR',
        'source_url': 'https://docs.rekor.ai/developers/carcheck/integration',
        'configured': bool(OPENALPR_SECRET_KEY),
    }
    if not OPENALPR_SECRET_KEY:
        base.update({'status': 'disabled', 'reason': 'openalpr_secret_key_nao_configurada'})
        return base
    if scene_img is None or getattr(scene_img, 'size', 0) == 0:
        base.update({'status': 'failed', 'reason': 'imagem_vazia'})
        return base

    try:
        encoded_ok, encoded = cv2.imencode('.jpg', scene_img, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        if not encoded_ok:
            base.update({'status': 'failed', 'reason': 'openalpr_encode_failed'})
            return base

        params = {
            'secret_key': OPENALPR_SECRET_KEY,
            'country': OPENALPR_COUNTRY,
            'recognize_vehicle': 1 if OPENALPR_RECOGNIZE_VEHICLE else 0,
            'topn': OPENALPR_TOPN,
        }
        response = requests.post(
            OPENALPR_ENDPOINT,
            params=params,
            files={'image': ('scene.jpg', encoded.tobytes(), 'image/jpeg')},
            timeout=EXTERNAL_COMPARE_TIMEOUT,
            verify=_http_verify_setting(),
        )
    except Exception as exc:
        base.update({'status': 'failed', 'reason': f'openalpr_request_error:{exc}'})
        return base

    if response.status_code < 200 or response.status_code >= 400:
        base.update({'status': 'failed', 'reason': f'openalpr_http_{response.status_code}'})
        return base

    try:
        payload = response.json()
    except Exception:
        base.update({'status': 'failed', 'reason': 'openalpr_invalid_json'})
        return base

    results = payload.get('results', []) if isinstance(payload, dict) else []
    if not isinstance(results, list) or not results:
        base.update({'status': 'no_detection', 'reason': 'openalpr_sem_resultados'})
        return base

    ranked = []
    for item in results[:EXTERNAL_COMPARE_MAX_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        plate_text = normalize_plate_text(item.get('plate', ''))
        plate_conf = parse_float(item.get('confidence'), 0.0)
        ranked.append({'plate': plate_text, 'confidence': round(plate_conf, 2), 'raw': item})
    ranked.sort(key=lambda item: float(item.get('confidence', 0.0)), reverse=True)

    if not ranked:
        base.update({'status': 'no_detection', 'reason': 'openalpr_sem_candidatos_validos'})
        return base

    top = ranked[0]
    top_raw = top.get('raw', {}) if isinstance(top.get('raw', {}), dict) else {}
    vehicle = _parse_generic_vehicle_fields(top_raw)

    candidates = []
    for item in ranked[:EXTERNAL_COMPARE_MAX_CANDIDATES]:
        plate = normalize_plate_text(item.get('plate', ''))
        if not plate:
            continue
        candidates.append({'plate': plate, 'confidence': round(parse_float(item.get('confidence'), 0.0), 2)})

    base.update({
        'status': 'ok',
        'reason': 'ok',
        'plate': normalize_plate_text(top.get('plate', '')),
        'plate_confidence': round(parse_float(top.get('confidence'), 0.0), 2),
        'vehicle': vehicle,
        'candidates': candidates,
    })
    return base


def _run_nomeroff_endpoint_comparison(scene_img):
    base = {
        'id': 'nomeroff_endpoint',
        'nome': 'Nomeroff-Net (endpoint customizado)',
        'source_url': 'https://github.com/ria-com/nomeroff-net',
        'configured': bool(NOMEROFF_COMPARE_ENDPOINT),
    }
    if not NOMEROFF_COMPARE_ENDPOINT:
        base.update({'status': 'disabled', 'reason': 'nomeroff_endpoint_nao_configurado'})
        return base
    if scene_img is None or getattr(scene_img, 'size', 0) == 0:
        base.update({'status': 'failed', 'reason': 'imagem_vazia'})
        return base

    try:
        encoded_ok, encoded = cv2.imencode('.jpg', scene_img, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        if not encoded_ok:
            base.update({'status': 'failed', 'reason': 'nomeroff_encode_failed'})
            return base
        headers = {'Accept': 'application/json'}
        if NOMEROFF_COMPARE_TOKEN:
            token_value = NOMEROFF_COMPARE_TOKEN
            if NOMEROFF_COMPARE_TOKEN_HEADER.lower() == 'authorization' and not token_value.lower().startswith('bearer '):
                token_value = f'Bearer {token_value}'
            headers[NOMEROFF_COMPARE_TOKEN_HEADER] = token_value

        response = requests.post(
            NOMEROFF_COMPARE_ENDPOINT,
            files={
                'image': ('scene.jpg', encoded.tobytes(), 'image/jpeg'),
                'upload': ('scene.jpg', encoded.tobytes(), 'image/jpeg'),
            },
            headers=headers,
            timeout=EXTERNAL_COMPARE_TIMEOUT,
            verify=_http_verify_setting(),
        )
    except Exception as exc:
        base.update({'status': 'failed', 'reason': f'nomeroff_request_error:{exc}'})
        return base

    if response.status_code < 200 or response.status_code >= 400:
        base.update({'status': 'failed', 'reason': f'nomeroff_http_{response.status_code}'})
        return base

    try:
        payload = response.json()
    except Exception:
        base.update({'status': 'failed', 'reason': 'nomeroff_invalid_json'})
        return base

    root = _pick_payload_root(payload)
    plate_text = normalize_plate_text(
        root.get('plate')
        or root.get('text')
        or root.get('license_plate')
        or root.get('number_plate')
        or ''
    )
    plate_conf = parse_float(
        root.get('plate_confidence')
        or root.get('confidence')
        or root.get('score')
        or root.get('avg_conf')
        or 0.0,
        0.0,
    )
    if plate_conf <= 1.0:
        plate_conf *= 100.0
    vehicle = _parse_generic_vehicle_fields(root)

    candidates = []
    for key in ('candidates', 'results', 'alternatives'):
        raw_candidates = root.get(key)
        if not isinstance(raw_candidates, list):
            continue
        for item in raw_candidates[:EXTERNAL_COMPARE_MAX_CANDIDATES]:
            if isinstance(item, dict):
                candidate_plate = normalize_plate_text(
                    item.get('plate') or item.get('text') or item.get('license_plate') or item.get('number_plate') or ''
                )
                candidate_conf = parse_float(item.get('confidence', item.get('score', 0.0)), 0.0)
                if candidate_conf <= 1.0:
                    candidate_conf *= 100.0
                if candidate_plate:
                    candidates.append({'plate': candidate_plate, 'confidence': round(candidate_conf, 2)})
        if candidates:
            break

    if not plate_text and not candidates:
        base.update({'status': 'no_detection', 'reason': 'nomeroff_sem_resultado'})
        return base

    base.update({
        'status': 'ok',
        'reason': 'ok',
        'plate': plate_text,
        'plate_confidence': round(max(0.0, min(100.0, plate_conf)), 2),
        'vehicle': vehicle,
        'candidates': candidates[:EXTERNAL_COMPARE_MAX_CANDIDATES],
    })
    return base


def run_external_vehicle_systems_comparison(scene_img, best_payload=None, visual_profile=None):
    systems_catalog = [
        {
            'id': 'plate_recognizer_snapshot',
            'nome': 'Plate Recognizer Snapshot API',
            'categoria': 'cloud_alpr',
            'source_url': 'https://guides.platerecognizer.com/docs/snapshot/api-reference/',
            'integracao_local': 'ativo' if bool(PLATE_RECOGNIZER_TOKEN) else 'opcional_token',
            'observacao': 'Ja utilizado no motor plate_recognizer do ensemble interno.',
        },
        {
            'id': 'openalpr_carcheck',
            'nome': 'Rekor CarCheck / OpenALPR',
            'categoria': 'cloud_alpr_vehicle',
            'source_url': 'https://docs.rekor.ai/developers/carcheck/integration',
            'integracao_local': 'ativo' if bool(OPENALPR_SECRET_KEY) else 'opcional_secret_key',
            'observacao': 'Comparativo externo de placa + make/model/color/ano quando configurado.',
        },
        {
            'id': 'openalpr_oss',
            'nome': 'OpenALPR (open source)',
            'categoria': 'open_source_alpr',
            'source_url': 'https://github.com/openalpr/openalpr',
            'integracao_local': 'referencia_arquitetural',
            'observacao': 'Referencia aberta para validacao e estudos de tuning offline.',
        },
        {
            'id': 'nomeroff_net',
            'nome': 'Nomeroff-Net',
            'categoria': 'open_source_alpr',
            'source_url': 'https://github.com/ria-com/nomeroff-net',
            'integracao_local': 'ativo_endpoint' if bool(NOMEROFF_COMPARE_ENDPOINT) else 'opcional_endpoint',
            'observacao': 'Pode ser integrado via endpoint proprio para comparativo adicional.',
        },
    ]

    response = {
        'enabled': bool(EXTERNAL_COMPARE_ENABLE),
        'catalogo': systems_catalog,
        'execucoes': [],
        'sumario': {
            'sistemas_catalogados': len(systems_catalog),
            'sistemas_executados': 0,
            'sistemas_ok': 0,
            'placa_compativel_ocr': 0,
            'veiculo_compativel_visual': 0,
            'taxa_concordancia_placa': 0.0,
            'taxa_concordancia_veiculo': 0.0,
        },
        'status': 'disabled' if not EXTERNAL_COMPARE_ENABLE else 'ready',
        'message': '',
    }

    if not EXTERNAL_COMPARE_ENABLE:
        response['message'] = 'comparativo_externo_desabilitado_por_configuracao'
        return response

    internal_plate = ''
    if isinstance(best_payload, dict):
        internal_plate = normalize_plate_text(best_payload.get('text', ''))
    internal_main = (visual_profile or {}).get('hipotese_principal', {}) if isinstance(visual_profile, dict) else {}
    internal_make = str(internal_main.get('fabricante', '')).strip()
    internal_model = str(internal_main.get('modelo', '')).strip()

    executions = [
        _run_openalpr_comparison(scene_img),
        _run_nomeroff_endpoint_comparison(scene_img),
    ]
    response['execucoes'] = executions
    response['sumario']['sistemas_executados'] = len([item for item in executions if isinstance(item, dict) and item.get('status') != 'disabled'])

    successful = 0
    plate_matches = 0
    vehicle_matches = 0
    enriched_executions = []

    for item in executions:
        if not isinstance(item, dict):
            continue
        status = str(item.get('status', 'indefinido'))
        if status == 'ok':
            successful += 1

        ext_plate = normalize_plate_text(item.get('plate', ''))
        plate_match = bool(internal_plate and ext_plate and internal_plate == ext_plate)
        if plate_match:
            plate_matches += 1

        vehicle = item.get('vehicle', {}) if isinstance(item.get('vehicle', {}), dict) else {}
        ext_make = str(vehicle.get('fabricante', '')).strip()
        ext_model = str(vehicle.get('modelo', '')).strip()

        make_score = _name_match_score(internal_make, ext_make) if internal_make and ext_make else 0.0
        model_score = _name_match_score(internal_model, ext_model) if internal_model and ext_model else 0.0
        vehicle_match = bool(
            (internal_make and ext_make and make_score >= 88.0)
            or (internal_model and ext_model and model_score >= 86.0)
        )
        if vehicle_match:
            vehicle_matches += 1

        item_enriched = dict(item)
        item_enriched['matches_internal_plate'] = plate_match if ext_plate else None
        item_enriched['matches_internal_vehicle'] = vehicle_match if (ext_make or ext_model) else None
        item_enriched['match_scores'] = {
            'make_score': round(float(make_score), 2),
            'model_score': round(float(model_score), 2),
        }
        enriched_executions.append(item_enriched)

    response['execucoes'] = enriched_executions
    response['sumario']['sistemas_ok'] = int(successful)
    response['sumario']['placa_compativel_ocr'] = int(plate_matches)
    response['sumario']['veiculo_compativel_visual'] = int(vehicle_matches)

    if successful > 0:
        response['sumario']['taxa_concordancia_placa'] = round((plate_matches / float(successful)) * 100.0, 2)
        response['sumario']['taxa_concordancia_veiculo'] = round((vehicle_matches / float(successful)) * 100.0, 2)
        response['status'] = 'ok'
        response['message'] = 'comparativo_externo_executado'
    else:
        response['status'] = 'sem_execucao_util'
        response['message'] = 'nenhum_sistema_externo_retornou_resultado_valido'

    return response


def build_assisted_vehicle_identification(visual_profile=None, external_systems_comparison=None):
    visual_profile = visual_profile if isinstance(visual_profile, dict) else {}
    external_systems_comparison = (
        external_systems_comparison if isinstance(external_systems_comparison, dict) else {}
    )

    principal = visual_profile.get('hipotese_principal', {}) if isinstance(visual_profile.get('hipotese_principal', {}), dict) else {}
    principal_raw = (
        visual_profile.get('hipotese_principal_bruta', {})
        if isinstance(visual_profile.get('hipotese_principal_bruta', {}), dict)
        else {}
    )
    model_quality = visual_profile.get('qualidade_modelo', {}) if isinstance(visual_profile.get('qualidade_modelo', {}), dict) else {}
    local_status = str(visual_profile.get('status', 'indefinido') or 'indefinido').strip()
    local_make = str(principal.get('fabricante', '') or principal_raw.get('fabricante', '') or '').strip()
    local_model = str(principal.get('modelo', '') or principal_raw.get('modelo', '') or '').strip()
    local_year = str(principal.get('faixa_ano_modelo', '') or principal_raw.get('faixa_ano_modelo', '') or '').strip()
    local_color = str(visual_profile.get('cor_probavel', '') or '').strip()
    local_view = str(visual_profile.get('vista_detectada', 'indefinida') or 'indefinida').strip()
    local_confidence = float(principal.get('confianca', principal_raw.get('confianca', 0.0)) or 0.0)
    local_model_abstained = bool(model_quality.get('model_abstained', False))

    invalid_models = {'', '-', 'indeterminado', 'modelo indeterminado', 'nao conclusivo', 'não conclusivo'}
    if local_model.strip().lower() in invalid_models:
        local_model = ''
    if local_make.strip().lower() in {'', '-', 'indeterminado', 'marca indeterminada'}:
        local_make = ''

    external_runs = external_systems_comparison.get('execucoes', []) if isinstance(external_systems_comparison.get('execucoes', []), list) else []
    supporting_systems = []

    for item in external_runs:
        if not isinstance(item, dict):
            continue
        if str(item.get('status', '')) != 'ok':
            continue
        vehicle = item.get('vehicle', {}) if isinstance(item.get('vehicle', {}), dict) else {}
        ext_make = str(vehicle.get('fabricante', '') or '').strip()
        ext_model = str(vehicle.get('modelo', '') or '').strip()
        ext_color = str(vehicle.get('cor', '') or '').strip()
        ext_year = str(vehicle.get('ano', '') or '').strip()
        ext_body = str(vehicle.get('tipo_carroceria', '') or '').strip()
        if not any([ext_make, ext_model, ext_color, ext_year, ext_body]):
            continue

        make_score = _name_match_score(local_make, ext_make) if local_make and ext_make else 0.0
        model_score = _name_match_score(local_model, ext_model) if local_model and ext_model else 0.0
        external_vehicle_confidence = max(
            parse_float(vehicle.get('confianca_modelo'), 0.0),
            parse_float(vehicle.get('confianca_fabricante'), 0.0),
            parse_float(item.get('plate_confidence'), 0.0) * 0.65,
        )
        support_score = (
            external_vehicle_confidence
            + (18.0 if item.get('matches_internal_vehicle') is True else 0.0)
            + min(26.0, make_score * 0.14)
            + min(24.0, model_score * 0.14)
        )
        supporting_systems.append({
            'id': str(item.get('id', 'sistema_externo')),
            'nome': str(item.get('nome', item.get('id', 'sistema_externo'))),
            'fabricante': ext_make,
            'modelo': ext_model,
            'cor': ext_color,
            'ano': ext_year,
            'tipo_carroceria': ext_body,
            'vehicle_confidence': round(float(external_vehicle_confidence), 1),
            'plate_confidence': round(parse_float(item.get('plate_confidence'), 0.0), 1),
            'matches_local_vehicle': bool(item.get('matches_internal_vehicle') is True),
            'make_match_score': round(float(make_score), 1),
            'model_match_score': round(float(model_score), 1),
            'support_score': round(float(support_score), 1),
            'source_url': str(item.get('source_url', '') or ''),
        })

    supporting_systems.sort(
        key=lambda item: (
            0 if item.get('matches_local_vehicle') else 1,
            -float(item.get('support_score', 0.0)),
            -float(item.get('vehicle_confidence', 0.0)),
        )
    )

    best_external = supporting_systems[0] if supporting_systems else {}
    corroborated = bool(best_external.get('matches_local_vehicle'))
    divergent = bool(
        best_external
        and local_make
        and best_external.get('fabricante')
        and _name_match_score(local_make, best_external.get('fabricante', '')) < 70.0
    ) or bool(
        best_external
        and local_model
        and best_external.get('modelo')
        and _name_match_score(local_model, best_external.get('modelo', '')) < 70.0
    )

    final_make = str(best_external.get('fabricante', '') or local_make or principal_raw.get('fabricante', '') or '').strip()
    final_model = str(best_external.get('modelo', '') or local_model or principal_raw.get('modelo', '') or '').strip()
    final_color = str(best_external.get('cor', '') or local_color or '').strip()
    final_year = str(best_external.get('ano', '') or local_year or '').strip()
    final_body = str(best_external.get('tipo_carroceria', '') or '').strip()

    reasons = []
    if local_make or local_model:
        reasons.append('hipotese_visual_local_disponivel')
    if local_model_abstained:
        reasons.append('modelo_local_abstido_por_baixa_evidencia')
    if supporting_systems:
        reasons.append('fonte_externa_visual_consultada')
    if corroborated:
        reasons.append('corroboracao_multifonte_visual')
    if divergent:
        reasons.append('divergencia_entre_fontes_visuais')
    if local_status in ('review_required', 'low_confidence'):
        reasons.append('perfil_visual_local_requer_revisao')

    combined_confidence = 0.0
    if corroborated and best_external:
        combined_confidence = min(
            92.0,
            max(
                62.0,
                (local_confidence * 0.55) + (float(best_external.get('vehicle_confidence', 0.0)) * 0.45),
            ),
        )
        status = 'corroborada_multifonte'
    elif best_external and (best_external.get('fabricante') or best_external.get('modelo')):
        combined_confidence = min(
            78.0,
            max(
                38.0,
                (local_confidence * 0.35) + (float(best_external.get('vehicle_confidence', 0.0)) * 0.65),
            ),
        )
        status = 'revisao_humana_obrigatoria'
    elif local_make or local_model:
        combined_confidence = min(74.0, max(32.0, local_confidence))
        status = 'hipotese_visual_local'
    else:
        status = 'indisponivel'

    if divergent:
        status = 'divergencia_visual'
        combined_confidence = min(combined_confidence or 42.0, 58.0)

    if local_model_abstained and not corroborated:
        status = 'revisao_humana_obrigatoria'
        combined_confidence = min(combined_confidence or 46.0, 64.0)

    label = 'Indeterminado'
    if final_make or final_model:
        label = ' '.join([item for item in [final_make, final_model] if item]).strip() or 'Indeterminado'

    statement = (
        'A identificacao visual assistida foi utilizada como apoio tecnico contextual, sem valor autonomo de conclusao.'
    )
    if status == 'corroborada_multifonte':
        statement = (
            f'Inferencia visual assistida convergiu para {label}, com corroboracao entre heuristica local e sistema externo. '
            'O resultado permanece sujeito a conferencia humana antes de qualquer uso formal.'
        )
    elif status == 'divergencia_visual':
        statement = (
            'As fontes visuais disponiveis apresentaram divergencia relevante entre si. '
            'O resultado deve permanecer apenas como indicio tecnico, exigindo revisao humana qualificada.'
        )
    elif label != 'Indeterminado':
        statement = (
            f'Inferencia visual assistida sugere {label} como hipotese tecnica de apoio. '
            'Essa indicacao nao deve ser tratada como conclusao autonoma sem correlacao com placa, bases oficiais e revisao humana.'
        )

    alternatives = []
    for item in (visual_profile.get('hipoteses', []) if isinstance(visual_profile.get('hipoteses', []), list) else [])[:3]:
        if not isinstance(item, dict):
            continue
        alt_make = str(item.get('fabricante', '') or '').strip()
        alt_model = str(item.get('modelo', '') or '').strip()
        alt_label = ' '.join([part for part in [alt_make, alt_model] if part]).strip()
        if not alt_label:
            continue
        alternatives.append({
            'label': alt_label,
            'confidence': round(parse_float(item.get('confianca'), 0.0), 1),
            'year_range': str(item.get('faixa_ano_modelo', '') or '').strip(),
        })

    return {
        'status': status,
        'label': label,
        'fabricante': final_make,
        'modelo': final_model,
        'cor': final_color,
        'ano': final_year,
        'tipo_carroceria': final_body,
        'vista_detectada': local_view or 'indefinida',
        'confidence': round(float(combined_confidence), 1),
        'local_confidence': round(float(local_confidence), 1),
        'local_status': local_status,
        'local_model_abstained': local_model_abstained,
        'corroborated': corroborated,
        'divergent': divergent,
        'manual_review_required': True,
        'auto_conclusion_allowed': False,
        'evidence_role': 'apoio_tecnico_visual',
        'supporting_systems_count': len(supporting_systems),
        'supporting_systems': supporting_systems[:4],
        'best_external_system': str(best_external.get('nome', '') or ''),
        'statement': statement,
        'disclaimer': 'Identificacao visual assistida possui natureza complementar e exige revisao humana qualificada.',
        'reasons': reasons,
        'alternatives': alternatives,
    }


from utils import scene_preprocess as scene_preprocess_module
from utils.input_guard import inspect_upload_file, inspect_upload_video_file
SCENE_PREPROCESS_ENABLED = scene_preprocess_module.SCENE_PREPROCESS_ENABLED
SCENE_PREPROCESS_BLEND = scene_preprocess_module.SCENE_PREPROCESS_BLEND
SCENE_PREPROCESS_CALIBRATION_PATH = scene_preprocess_module.SCENE_PREPROCESS_CALIBRATION_PATH
preprocess_scene_for_ocr = scene_preprocess_module.preprocess_scene_for_ocr
from utils import plate_geometry as plate_geometry_module
from utils.report_visuals import build_capture_comparison_sheet
from utils.video_analysis import (
    build_video_contact_sheet,
    build_video_forensic_chain,
    probe_video_metadata,
    sample_video_frames,
    select_video_best_frame,
)
from utils.video_session import (
    aggregate_video_candidates,
    aggregate_video_partial_candidates,
    load_video_scan_record,
    normalize_video_target_entry,
    save_video_scan_record,
    select_candidates_by_ids,
)
from utils.video_report_outline import get_video_analysis_report_outline
from utils.video_report_pdf import generate_video_investigation_report


def _resolve_default_video_target(video_candidates, best_frame):
    candidates = [
        normalize_video_target_entry(candidate)
        for candidate in (video_candidates or [])
        if isinstance(candidate, dict)
    ]
    if not candidates and isinstance(best_frame, dict):
        return normalize_video_target_entry(best_frame)

    best_frame_index = int(best_frame.get('frame_index', 0) or 0) if isinstance(best_frame, dict) else 0
    best_frame_text = normalize_plate_text(str(best_frame.get('ocr', '') or '')) if isinstance(best_frame, dict) else ''

    for candidate in candidates:
        candidate_frame = candidate.get('best_frame', {}) if isinstance(candidate.get('best_frame', {}), dict) else {}
        candidate_frame_index = int(candidate_frame.get('frame_index', 0) or candidate.get('frame_index', 0) or 0)
        candidate_text = normalize_plate_text(str(candidate.get('text', '') or ''))
        if best_frame_index and candidate_frame_index == best_frame_index:
            return candidate
        if best_frame_text and candidate_text and candidate_text == best_frame_text:
            return candidate

    return candidates[0] if candidates else normalize_video_target_entry(best_frame)


def _extract_selected_candidate_ids(payload):
    if isinstance(payload, dict):
        raw_value = payload.get('selected_candidate_ids', [])
    else:
        raw_value = []

    if isinstance(raw_value, str):
        raw_value = [item for item in raw_value.split(',') if str(item).strip()]

    ids = []
    for item in raw_value if isinstance(raw_value, (list, tuple, set)) else [raw_value]:
        candidate_id = str(item).strip()
        if candidate_id:
            ids.append(candidate_id)
    return ids


def _build_and_store_evidence_manifest(report_data, analysis_kind, upload_dir, analysis_id=''):
    manifest = build_evidence_manifest(report_data, analysis_kind=analysis_kind)
    if analysis_id and not str(manifest.get('analysis_id', '') or '').strip():
        manifest['analysis_id'] = str(analysis_id)

    persistence = persist_evidence_manifest(
        manifest,
        upload_dir,
        analysis_id or manifest.get('analysis_id', ''),
        analysis_kind,
    )
    if isinstance(persistence, dict):
        manifest.update(persistence)

    return manifest


def preprocess_plate(plate_img):
    if plate_img is None:
        raise ValueError('Imagem de placa ausente para preprocessamento.')

    if len(plate_img.shape) == 2:
        gray = plate_img.copy()
    else:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    pixel_count = int(gray.size)
    longest_side = max(gray.shape[:2])
    mean_luminance = float(np.mean(gray))
    if mean_luminance < 95:
        gray = cv2.convertScaleAbs(gray, alpha=1.35, beta=16)
    elif mean_luminance > 185:
        gray = cv2.convertScaleAbs(gray, alpha=0.82, beta=-22)

    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    if pixel_count > 1_200_000:
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    else:
        denoised = cv2.fastNlMeansDenoising(gray, None, 15, 7, 21)

    if pixel_count > 1_500_000:
        clahe = denoised
    else:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)

    gamma_corrected = np.clip(((clahe / 255.0) ** 0.92) * 255.0, 0, 255).astype(np.uint8)
    kernel = np.array([[0, -1, 0], [-1, 6, -1], [0, -1, 0]])
    sharpen = cv2.filter2D(gamma_corrected, -1, kernel)
    if longest_side >= 1700:
        scale = 0.95
    elif longest_side >= 1300:
        scale = 1.0
    elif longest_side >= 900:
        scale = 1.22
    elif longest_side >= 700:
        scale = 1.5
    else:
        scale = 2.25
    upscale = cv2.resize(sharpen, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return upscale


def canonicalize_plate_crop(plate_img, pad_ratio=0.06, target_long_side=240):
    if plate_img is None or getattr(plate_img, 'size', 0) == 0:
        return plate_img
    if plate_geometry_module is None:
        return plate_img
    try:
        normalized = plate_geometry_module.normalize_plate_crop(
            plate_img,
            pad_ratio=pad_ratio,
            deskew_min_angle=0.75,
            target_long_side=target_long_side,
        )
        if normalized is not None and getattr(normalized, 'size', 0) > 0:
            return normalized
    except Exception:
        pass
    return plate_img


def _read_plate_crop_for_geometry_refine(plate_detection):
    if not isinstance(plate_detection, dict):
        return None, ''

    candidate_paths = [
        plate_detection.get('selected_raw_path', ''),
        plate_detection.get('selected_treated_path', ''),
        plate_detection.get('selected_path', ''),
    ]
    for raw_path in candidate_paths:
        path = str(raw_path or '').strip()
        if not path or not os.path.isfile(path):
            continue
        try:
            img = cv2.imread(path)
        except Exception:
            img = None
        if img is not None and getattr(img, 'size', 0) > 0:
            return img, path
    return None, ''


def analyze_tail_digit_geometry(plate_img):
    if plate_img is None or getattr(plate_img, 'size', 0) == 0:
        return {'available': False, 'reason': 'missing_crop'}

    canonical = canonicalize_plate_crop(plate_img, target_long_side=320)
    if canonical is None or getattr(canonical, 'size', 0) == 0:
        canonical = plate_img
    if canonical is None or getattr(canonical, 'size', 0) == 0:
        return {'available': False, 'reason': 'empty_crop'}

    if len(canonical.shape) == 2:
        gray = canonical.copy()
    else:
        gray = cv2.cvtColor(canonical, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape[:2]
    if height < 36 or width < 96:
        return {'available': False, 'reason': 'crop_too_small'}

    best_profile = None
    for polarity_name, threshold_mode in (
        ('bright_chars', cv2.THRESH_BINARY + cv2.THRESH_OTSU),
        ('dark_chars', cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU),
    ):
        try:
            thresholded = cv2.threshold(gray, 0, 255, threshold_mode)[1]
        except Exception:
            continue

        for ymin_ratio, ymax_ratio in ((0.26, 0.92), (0.30, 0.92), (0.34, 0.90)):
            y0 = max(0, min(height - 1, int(round(height * ymin_ratio))))
            y1 = max(y0 + 1, min(height, int(round(height * ymax_ratio))))
            band = thresholded[y0:y1, :]
            if band is None or getattr(band, 'size', 0) == 0:
                continue

            try:
                num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(band, 8)
            except Exception:
                continue

            components = []
            band_height, band_width = band.shape[:2]
            for label in range(1, int(num_labels)):
                x, y, comp_w, comp_h, area = [int(value) for value in stats[label]]
                if area < 80:
                    continue
                if comp_h < int(band_height * 0.45):
                    continue
                if comp_w > int(band_width * 0.24):
                    continue
                aspect = float(comp_w) / float(max(1, comp_h))
                if aspect > 2.25:
                    continue
                fill_ratio = float(area) / float(max(1, comp_w * comp_h))
                components.append({
                    'x': x,
                    'y': y,
                    'w': comp_w,
                    'h': comp_h,
                    'area': area,
                    'aspect': aspect,
                    'fill_ratio': fill_ratio,
                    'center_x': float(x) + (float(comp_w) / 2.0),
                })

            if not components:
                continue

            components.sort(key=lambda item: (item['x'], item['y']))
            right_side_components = [
                item
                for item in components
                if float(item.get('center_x', 0.0)) >= float(band_width) * 0.46
            ]
            if not right_side_components:
                continue

            rightmost = right_side_components[-1]
            preceding = [item for item in right_side_components[:-1] if float(item.get('aspect', 0.0)) >= 0.35]
            if not preceding:
                preceding = [item for item in components[:-1] if float(item.get('aspect', 0.0)) >= 0.35]

            preceding_aspects = [float(item.get('aspect', 0.0)) for item in preceding if float(item.get('aspect', 0.0)) > 0.0]
            preceding_widths = [float(item.get('w', 0.0)) for item in preceding if float(item.get('w', 0.0)) > 0.0]
            median_prev_aspect = float(np.median(preceding_aspects)) if preceding_aspects else 0.0
            median_prev_width = float(np.median(preceding_widths)) if preceding_widths else 0.0
            rightmost_aspect = float(rightmost.get('aspect', 0.0))
            rightmost_width = float(rightmost.get('w', 0.0))
            aspect_vs_prev = (
                rightmost_aspect / max(0.08, median_prev_aspect)
                if median_prev_aspect > 0.0
                else 1.0
            )
            width_vs_prev = (
                rightmost_width / max(1.0, median_prev_width)
                if median_prev_width > 0.0
                else 1.0
            )

            profile_score = 0.0
            profile_score += max(0.0, 12.0 - (abs(len(components) - 7) * 2.4))
            profile_score += min(8.0, float(len(right_side_components)) * 1.75)
            profile_score += min(8.0, max(0.0, float(rightmost.get('center_x', 0.0)) / max(1.0, float(band_width))) * 8.0)
            profile_score += min(12.0, float(rightmost.get('fill_ratio', 0.0)) * 10.0)
            if rightmost_aspect <= 0.38:
                profile_score += 10.0
            if aspect_vs_prev <= 0.55:
                profile_score += 12.0
            if width_vs_prev <= 0.55:
                profile_score += 8.0

            candidate_profile = {
                'available': True,
                'canonical_shape': [int(value) for value in canonical.shape[:2]],
                'band_shape': [int(value) for value in band.shape[:2]],
                'polarity': polarity_name,
                'band_y_range': [y0, y1],
                'component_count': len(components),
                'right_side_count': len(right_side_components),
                'rightmost_component': {
                    'x': int(rightmost.get('x', 0)),
                    'y': int(rightmost.get('y', 0)),
                    'w': int(rightmost.get('w', 0)),
                    'h': int(rightmost.get('h', 0)),
                    'area': int(rightmost.get('area', 0)),
                    'aspect': round(rightmost_aspect, 3),
                    'fill_ratio': round(float(rightmost.get('fill_ratio', 0.0)), 3),
                    'center_x_ratio': round(float(rightmost.get('center_x', 0.0)) / max(1.0, float(band_width)), 3),
                    'height_ratio': round(float(rightmost.get('h', 0.0)) / max(1.0, float(band_height)), 3),
                },
                'comparison': {
                    'median_prev_aspect': round(median_prev_aspect, 3),
                    'median_prev_width': round(median_prev_width, 3),
                    'aspect_vs_prev': round(aspect_vs_prev, 3),
                    'width_vs_prev': round(width_vs_prev, 3),
                },
                'profile_score': round(profile_score, 3),
            }

            if best_profile is None or float(candidate_profile.get('profile_score', 0.0)) > float(best_profile.get('profile_score', 0.0)):
                best_profile = candidate_profile

    if not best_profile:
        return {'available': False, 'reason': 'no_components'}

    rightmost_component = best_profile.get('rightmost_component', {})
    comparison = best_profile.get('comparison', {})
    aspect = float(rightmost_component.get('aspect', 0.0))
    fill_ratio = float(rightmost_component.get('fill_ratio', 0.0))
    height_ratio = float(rightmost_component.get('height_ratio', 0.0))
    center_x_ratio = float(rightmost_component.get('center_x_ratio', 0.0))
    aspect_vs_prev = float(comparison.get('aspect_vs_prev', 1.0))
    width_vs_prev = float(comparison.get('width_vs_prev', 1.0))
    component_count = int(best_profile.get('component_count', 0) or 0)

    one_score = 0.0
    if aspect <= 0.28:
        one_score += 38.0
    elif aspect <= 0.34:
        one_score += 30.0
    elif aspect <= 0.38:
        one_score += 20.0

    if fill_ratio >= 0.78:
        one_score += 22.0
    elif fill_ratio >= 0.62:
        one_score += 14.0

    if height_ratio >= 0.64:
        one_score += 18.0
    elif height_ratio >= 0.55:
        one_score += 10.0

    if aspect_vs_prev <= 0.35:
        one_score += 18.0
    elif aspect_vs_prev <= 0.50:
        one_score += 10.0

    if width_vs_prev <= 0.38:
        one_score += 10.0
    elif width_vs_prev <= 0.55:
        one_score += 6.0

    if 5 <= component_count <= 9:
        one_score += 8.0
    if center_x_ratio >= 0.82:
        one_score += 6.0

    one_score = max(0.0, min(100.0, one_score))
    strong_one = (
        one_score >= 68.0
        and aspect <= 0.38
        and fill_ratio >= 0.56
        and height_ratio >= 0.52
        and center_x_ratio >= 0.78
    )

    best_profile['tail_digit_one_confidence'] = round(one_score, 2)
    best_profile['tail_digit_suggested'] = '1' if strong_one else ''
    best_profile['tail_digit_geometry_label'] = 'vertical_slim_digit' if strong_one else 'inconclusive'
    return best_profile


def build_geometry_refine_result(ocr_results, plate_detection=None):
    if not isinstance(ocr_results, dict):
        return None
    if not isinstance(plate_detection, dict):
        plate_detection = {}

    anchor_candidates = build_top_candidates(ocr_results, plate_detection=plate_detection)
    anchor = next((item for item in anchor_candidates if isinstance(item, dict)), None)
    if anchor is None:
        return None

    anchor_text = normalize_plate_text(anchor.get('text', ''))
    if len(anchor_text) != 7:
        return None

    pattern = str(anchor.get('pattern', detect_plate_pattern(anchor_text)) or detect_plate_pattern(anchor_text))
    if pattern == 'Indefinido':
        return None
    slots = expected_slots(pattern)
    if len(slots) != 7 or slots[-1] != 'D':
        return None
    if anchor_text[-1] == '1':
        return None

    support_count = int(parse_int(anchor.get('support_count', 1), 1))
    agreement_ratio = float(parse_float(anchor.get('agreement_ratio', 0.0), 0.0))
    avg_conf = float(parse_float(anchor.get('avg_conf', 0.0), 0.0))
    score = float(parse_float(anchor.get('score', 0.0), 0.0))
    if support_count >= 2 and agreement_ratio >= 60.0 and avg_conf >= 82.0:
        return None
    if avg_conf >= 90.0 and score >= 130.0:
        return None

    plate_img, crop_source = _read_plate_crop_for_geometry_refine(plate_detection)
    if plate_img is None:
        return None

    geometry = analyze_tail_digit_geometry(plate_img)
    if not bool(geometry.get('available', False)):
        return None
    if str(geometry.get('tail_digit_suggested', '') or '') != '1':
        return None

    geometry_confidence = float(parse_float(geometry.get('tail_digit_one_confidence', 0.0), 0.0))
    if geometry_confidence < 68.0:
        return None

    corrected_text = f'{anchor_text[:-1]}1'
    if corrected_text == anchor_text:
        return None

    corrected_pattern = detect_plate_pattern(corrected_text)
    corrected_legal = validate_plate_by_law(corrected_text)
    if corrected_pattern == 'Indefinido' or not bool(corrected_legal.get('is_valid', False)):
        return None

    corrected_conf = min(96.0, max(82.0, avg_conf + min(24.0, geometry_confidence * 0.22)))
    corrected_score = min(158.0, max(124.0, score + min(42.0, geometry_confidence * 0.54)))
    alternative_score = max(0.0, corrected_score - 18.0)

    return {
        'text': corrected_text,
        'avg_conf': round(corrected_conf, 2),
        'score': round(corrected_score, 2),
        'pattern': corrected_pattern,
        'region': 'geometry_tail_digit_refine_plate_crop',
        'chars': [],
        'support_count': 1,
        'selection_reason': 'tail_digit_geometry_refine',
        'tail_digit_geometry': geometry,
        'geometry_refine_source': crop_source,
        'warning': 'geometry_tail_digit_refine',
        'candidates': [
            {
                'text': corrected_text,
                'avg_conf': round(corrected_conf, 2),
                'score': round(corrected_score, 2),
                'pattern': corrected_pattern,
                'origin': 'tail_digit_geometry_refine',
                'region': 'geometry_tail_digit_refine_plate_crop',
                'hits': 1,
            },
            {
                'text': anchor_text,
                'avg_conf': round(max(0.0, avg_conf), 2),
                'score': round(max(0.0, alternative_score), 2),
                'pattern': pattern,
                'origin': 'ensemble_anchor_before_geometry',
                'region': str(anchor.get('region', 'full_image') or 'full_image'),
                'hits': 1,
            },
        ],
    }


def build_preprocess_variants(base_img):
    variants = [('upscaled_gray', base_img)]
    padded = pad_plate_image(base_img, 0.06)
    if padded is not None and getattr(padded, 'size', 0) > 0:
        variants.append(('padded_gray', padded))

    deskewed, deskew_angle = deskew_plate_image(base_img)
    if deskewed is not None and getattr(deskewed, 'size', 0) > 0 and abs(float(deskew_angle)) >= 0.75:
        variants.append((f'deskewed_{str(deskew_angle).replace(".", "_").replace("-", "m")}', deskewed))

    otsu = cv2.threshold(base_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    otsu_inv = cv2.bitwise_not(otsu)
    adaptive = cv2.adaptiveThreshold(base_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9)
    adaptive_inv = cv2.bitwise_not(adaptive)
    adaptive_mean = cv2.adaptiveThreshold(base_img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 9)
    adaptive_mean_inv = cv2.bitwise_not(adaptive_mean)
    morph_kernel = np.ones((2, 2), np.uint8)
    morph_close = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, morph_kernel)
    morph_open = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, morph_kernel)
    blackhat = cv2.morphologyEx(base_img, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)))
    blackhat = cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)
    blackhat_otsu = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    tophat = cv2.morphologyEx(base_img, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)))
    tophat = cv2.normalize(tophat, None, 0, 255, cv2.NORM_MINMAX)
    tophat_otsu = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    equalized = cv2.equalizeHist(base_img)
    equalized_otsu = cv2.threshold(equalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    morph_close_heavy = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Otsu com denoising prÃ©vio agressivo para caracteres fragmentados
    denoised_light = cv2.GaussianBlur(base_img, (3, 3), 0)
    otsu_denoised = cv2.threshold(denoised_light, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    variants.extend([
        ('otsu', otsu),
        ('otsu_inv', otsu_inv),
        ('otsu_denoised', otsu_denoised),
        ('adaptive', adaptive),
        ('adaptive_inv', adaptive_inv),
        ('adaptive_mean', adaptive_mean),
        ('adaptive_mean_inv', adaptive_mean_inv),
        ('morph_close', morph_close),
        ('morph_close_heavy', morph_close_heavy),
        ('morph_open', morph_open),
        ('blackhat', blackhat),
        ('blackhat_otsu', blackhat_otsu),
        ('tophat', tophat),
        ('tophat_otsu', tophat_otsu),
        ('equalized', equalized),
        ('equalized_otsu', equalized_otsu),
    ])

    local_contrast = float(np.std(base_img))
    local_blur = float(cv2.Laplacian(base_img, cv2.CV_64F).var())
    local_brightness = float(np.mean(base_img))

    if local_blur < 150:
        strong_sharpen = cv2.filter2D(base_img, -1, np.array([[0, -1, 0], [-1, 7, -1], [0, -1, 0]]))
        variants.append(('strong_sharpen', strong_sharpen))

    if local_contrast < 34:
        high_contrast = cv2.convertScaleAbs(base_img, alpha=1.45, beta=8)
        variants.append(('high_contrast', high_contrast))

    if local_brightness < 80:
        bright_boost = cv2.convertScaleAbs(base_img, alpha=1.20, beta=22)
        variants.append(('bright_boost', bright_boost))
    elif local_brightness > 205:
        dark_balance = cv2.convertScaleAbs(base_img, alpha=0.88, beta=-18)
        variants.append(('dark_balance', dark_balance))

    pillow_variants = _build_pillow_plate_variants(base_img)
    if pillow_variants:
        variants.extend(pillow_variants)

    return variants


def _build_pillow_plate_variants(base_img):
    if base_img is None or getattr(base_img, 'size', 0) == 0:
        return []
    if PILImage is None or ImageEnhance is None or ImageFilter is None or ImageOps is None:
        return []

    try:
        if len(base_img.shape) == 2:
            rgb = cv2.cvtColor(base_img, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(base_img, cv2.COLOR_BGR2RGB)
        pil = PILImage.fromarray(rgb)
    except Exception:
        return []

    variants = []
    try:
        transformations = [
            ('autocontrast', ImageOps.autocontrast(pil)),
            ('equalize', ImageOps.equalize(pil)),
            ('contrast_boost', ImageEnhance.Contrast(pil).enhance(1.25)),
            ('brightness_boost', ImageEnhance.Brightness(pil).enhance(1.08)),
            ('sharpness_boost', ImageEnhance.Sharpness(pil).enhance(1.6)),
            ('median_denoise', pil.filter(ImageFilter.MedianFilter(size=3))),
        ]
        for variant_name, pil_variant in transformations:
            try:
                arr = np.array(pil_variant)
                if arr.ndim == 3 and arr.shape[2] == 3:
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                variants.append((f'pillow_{variant_name}', arr))
            except Exception:
                continue
    except Exception:
        return []

    return variants


def build_raw_variants(plate_img):
    if plate_img is None or getattr(plate_img, 'size', 0) == 0:
        return []

    if len(plate_img.shape) == 2:
        gray = plate_img.copy()
    else:
        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)

    longest_side = max(gray.shape[:2])
    if longest_side >= 1700:
        scale = 0.95
    elif longest_side >= 1300:
        scale = 1.0
    elif longest_side >= 900:
        scale = 1.2
    elif longest_side >= 700:
        scale = 1.4
    else:
        scale = 2.2
    upscaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    padded = pad_plate_image(upscaled, 0.07)
    otsu = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    equalized = cv2.equalizeHist(upscaled)
    adaptive = cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9)
    adaptive_inv = cv2.bitwise_not(adaptive)
    adaptive_mean = cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 9)
    adaptive_mean_inv = cv2.bitwise_not(adaptive_mean)
    padded_otsu = cv2.threshold(padded, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    padded_equalized = cv2.equalizeHist(padded)
    blackhat = cv2.morphologyEx(upscaled, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)))
    blackhat = cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)
    blackhat_otsu = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    variants = [
        ('raw_gray', upscaled),
        ('raw_padded_gray', padded),
        ('raw_otsu', otsu),
        ('raw_otsu_inv', cv2.bitwise_not(otsu)),
        ('raw_equalized', equalized),
        ('raw_equalized_otsu', cv2.threshold(equalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]),
        ('raw_adaptive', cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9)),
        ('raw_adaptive_inv', adaptive_inv),
        ('raw_adaptive_mean', cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 9)),
        ('raw_adaptive_mean_inv', adaptive_mean_inv),
        ('raw_padded_otsu', padded_otsu),
        ('raw_padded_equalized', padded_equalized),
        ('raw_blackhat', blackhat),
        ('raw_blackhat_otsu', blackhat_otsu),
    ]

    pillow_variants = _build_pillow_plate_variants(upscaled)
    if pillow_variants:
        variants.extend(pillow_variants)

    return variants


def build_ocr_variants(plate_img):
    canonical_img = canonicalize_plate_crop(plate_img)
    if canonical_img is None or getattr(canonical_img, 'size', 0) == 0:
        canonical_img = plate_img

    variants = []
    for variant_name, variant_img in build_raw_variants(canonical_img):
        variants.append((variant_name, variant_img, plate_recognizer_variant_quality_score(variant_img)))

    for angle in ROTATION_ANGLES:
        rotated = rotate_image(canonical_img, angle) if abs(angle) > 0.001 else canonical_img
        base = preprocess_plate(rotated)
        angle_tag = str(int(angle)) if float(angle).is_integer() else str(angle).replace('.', '_')
        for variant_name, variant_img in build_preprocess_variants(base):
            variants.append((f'{variant_name}_rot_{angle_tag}', variant_img, plate_recognizer_variant_quality_score(variant_img)))

    deskewed_img, deskew_angle = deskew_plate_image(canonical_img)
    if deskewed_img is not None and getattr(deskewed_img, 'size', 0) > 0 and abs(float(deskew_angle)) >= 0.75:
        deskew_base = preprocess_plate(deskewed_img)
        deskew_tag = str(deskew_angle).replace('.', '_').replace('-', 'm')
        for variant_name, variant_img in build_preprocess_variants(deskew_base):
            variants.append((f'{variant_name}_deskew_{deskew_tag}', variant_img, plate_recognizer_variant_quality_score(variant_img)))

    variants.sort(key=lambda item: float(item[2]), reverse=True)

    deduped = []
    signatures = set()
    image_pixels = int(canonical_img.shape[0] * canonical_img.shape[1]) if canonical_img is not None else 0
    max_variants_limit = TESSERACT_MAX_VARIANTS
    if image_pixels > 140_000:
        max_variants_limit = min(max_variants_limit, 10)
    if image_pixels > 280_000:
        max_variants_limit = min(max_variants_limit, 8)
    if image_pixels > 600_000:
        max_variants_limit = min(max_variants_limit, 6)

    for variant_name, variant_img, _quality in variants:
        if variant_img is None:
            continue
        signature = (
            variant_img.shape[0],
            variant_img.shape[1],
            int(float(np.mean(variant_img))),
            int(float(np.std(variant_img))),
        )
        if signature in signatures:
            continue
        signatures.add(signature)
        deduped.append((variant_name, variant_img))
        if len(deduped) >= max_variants_limit:
            break
    return deduped


def tesseract_extract(img, psm):
    config = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
    tokens = []
    confidences = []
    chars = []
    entries = []

    for index in range(len(data['text'])):
        token = normalize_plate_text(data['text'][index])
        confidence = parse_confidence(data['conf'][index])
        if token:
            tokens.append(token)
            entries.append({'word': token, 'conf': float(confidence if confidence >= 0 else 0)})
            if confidence >= 0:
                confidences.append(confidence)
            char_conf = confidence if confidence >= 0 else 0
            chars.extend([(char, char_conf) for char in token])

    if not tokens:
        fallback = normalize_plate_text(pytesseract.image_to_string(img, config=config))
        if fallback:
            tokens = [fallback]
            chars.extend([(char, 0) for char in fallback])

    avg_conf = float(np.mean(confidences)) if confidences else 0.0
    text = ''.join(tokens)
    return {'text': text, 'avg_conf': avg_conf, 'chars': chars, 'entries': entries}


def expected_slots(pattern_name):
    if pattern_name == 'Mercosul':
        return ['L', 'L', 'L', 'D', 'L', 'D', 'D']
    return ['L', 'L', 'L', 'D', 'D', 'D', 'D']


def slot_weight_for_index(index):
    return 1.15 if index in (3, 4) else 1.0


def coerce_to_pattern(text, pattern_name):
    if len(text) != 7:
        return text, 3, 0.0, 0, 0, 0

    slots = expected_slots(pattern_name)
    output = []
    penalty = 0
    slot_score = 0.0
    exact_matches = 0
    soft_matches = 0
    hard_mismatches = 0
    for index, char in enumerate(text):
        slot = slots[index]
        weight = slot_weight_for_index(index)
        if slot == 'L':
            if char.isalpha():
                output.append(char)
                exact_matches += 1
                slot_score += 2.0 * weight
            elif char in LETTER_SUBSTITUTIONS:
                output.append(LETTER_SUBSTITUTIONS[char])
                soft_matches += 1
                penalty += 1
                slot_score += 1.05 * weight
            else:
                output.append(char)
                hard_mismatches += 1
                penalty += 2
                slot_score -= 4.5 * weight
        else:
            if char.isdigit():
                output.append(char)
                exact_matches += 1
                slot_score += 2.0 * weight
            elif char in DIGIT_SUBSTITUTIONS:
                output.append(DIGIT_SUBSTITUTIONS[char])
                soft_matches += 1
                penalty += 1
                slot_score += 1.05 * weight
            else:
                output.append(char)
                hard_mismatches += 1
                penalty += 2
                slot_score -= 4.5 * weight
    return ''.join(output), penalty, round(slot_score, 2), exact_matches, soft_matches, hard_mismatches


def build_plate_hypotheses(text):
    cleaned = normalize_plate_text(text)
    if not is_plate_like_text(cleaned):
        return []

    seeds = {cleaned}
    if len(cleaned) > 7:
        seeds.add(cleaned[:7])
        seeds.add(cleaned[-7:])
        for offset in range(0, len(cleaned) - 6):
            seeds.add(cleaned[offset:offset + 7])

    hypotheses = []
    seen = set()
    for seed in seeds:
        for pattern_name in ('Mercosul', 'Antigo'):
            coerced, penalty, slot_score, exact_matches, soft_matches, hard_mismatches = coerce_to_pattern(seed, pattern_name)
            if not coerced:
                continue
            key = (coerced, penalty, round(slot_score, 2), pattern_name)
            if key in seen:
                continue
            seen.add(key)
            hypotheses.append({
                'text': coerced,
                'penalty': penalty,
                'slot_score': round(slot_score, 2),
                'exact_matches': exact_matches,
                'soft_matches': soft_matches,
                'hard_mismatches': hard_mismatches,
                'target_pattern': pattern_name,
            })
    return hypotheses


def score_hypothesis(
    text,
    avg_conf,
    penalty,
    slot_score=0.0,
    target_pattern='Indefinido',
    exact_matches=0,
    soft_matches=0,
    hard_mismatches=0,
):
    pattern = detect_plate_pattern(text)
    score = avg_conf
    if len(text) == 7:
        score += 6.5
    else:
        score -= abs(7 - len(text)) * 6.5

    if pattern != 'Indefinido':
        score += 10.5
    if target_pattern in ('Mercosul', 'Antigo'):
        if pattern == target_pattern:
            score += 4.0
        elif pattern != 'Indefinido':
            score -= 1.5
    score += float(slot_score)
    score += min(4.5, float(exact_matches) * 0.65)
    score += min(1.8, float(soft_matches) * 0.25)
    score -= min(7.5, float(hard_mismatches) * 1.85)
    score -= min(4.5, float(penalty) * 0.40)
    return score, pattern


def is_tesseract_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    hits = int(candidate.get('hits', 1))

    if pattern != 'Indefinido':
        # Thresholds mais resilientes para padroes legais confirmados (ex: caracteres desgastados)
        if score >= (TESSERACT_PATTERN_MIN_SCORE - 10.0) and avg_conf >= (OCR_PATTERN_MIN_CONFIDENCE - 10.0):
            return True
        if score >= max(TESSERACT_PATTERN_MIN_SCORE, TESSERACT_MIN_ACCEPT_SCORE) and hits >= 2:
            return True
        return False

    if score >= TESSERACT_MIN_ACCEPT_SCORE and avg_conf >= TESSERACT_MIN_ACCEPT_CONF and hits >= 2:
        return True
    return False


def ocr_tesseract(plate_img):
    try:
        variants = build_ocr_variants(plate_img)
        psm_modes = TESSERACT_PSM_MODES
        char_conf = defaultdict(float)
        candidates_by_text = {}
        candidate_hits = defaultdict(int)
        candidate_conf_sum = defaultdict(float)
        raw_entries = []
        best_score_seen = -1e9
        early_exit = False

        for variant_name, variant_img in variants:
            for psm in psm_modes:
                extracted = tesseract_extract(variant_img, psm)
                text = extracted['text']
                if not text:
                    continue

                for entry in extracted.get('entries', []):
                    if not isinstance(entry, dict):
                        continue
                    raw_entries.append({
                        'word': entry.get('word', ''),
                        'conf': float(entry.get('conf', 0.0)),
                        'variant': variant_name,
                        'engine': 'tesseract',
                        'psm': psm,
                    })

                for char, conf in extracted['chars']:
                    if conf > char_conf[char]:
                        char_conf[char] = conf

                hypotheses = build_plate_hypotheses(text)
                if not hypotheses:
                    continue

                for hypothesis in hypotheses:
                    hypothesis_text = hypothesis['text']
                    penalty = hypothesis['penalty']
                    score, pattern = score_hypothesis(
                        hypothesis_text,
                        extracted['avg_conf'],
                        penalty,
                        hypothesis.get('slot_score', 0.0),
                        hypothesis.get('target_pattern', 'Indefinido'),
                        hypothesis.get('exact_matches', 0),
                        hypothesis.get('soft_matches', 0),
                        hypothesis.get('hard_mismatches', 0),
                    )
                    candidate = {
                        'text': hypothesis_text,
                        'avg_conf': extracted['avg_conf'],
                        'score': round(score, 2),
                        'pattern': pattern,
                        'penalty': penalty,
                        'slot_score': round(float(hypothesis.get('slot_score', 0.0)), 2),
                        'target_pattern': hypothesis.get('target_pattern', 'Indefinido'),
                        'exact_matches': int(hypothesis.get('exact_matches', 0)),
                        'soft_matches': int(hypothesis.get('soft_matches', 0)),
                        'hard_mismatches': int(hypothesis.get('hard_mismatches', 0)),
                        'variant': variant_name,
                        'psm': psm,
                    }
                    candidate_hits[hypothesis_text] += 1
                    candidate_conf_sum[hypothesis_text] += float(extracted.get('avg_conf', 0))
                    previous = candidates_by_text.get(hypothesis_text)
                    if previous is None or candidate['score'] > previous['score']:
                        candidates_by_text[hypothesis_text] = candidate
                    if candidate['score'] > best_score_seen:
                        best_score_seen = candidate['score']
                if not OCR_ACCURACY_FIRST and best_score_seen >= TESSERACT_EARLY_EXIT_SCORE:
                    early_exit = True
                    break
            if early_exit:
                break

        if not candidates_by_text:
            return {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'raw_entries': raw_entries}

        recalibrated = []
        for text, candidate in candidates_by_text.items():
            merged = dict(candidate)
            hits = int(candidate_hits.get(text, 1))
            support_conf = float(candidate_conf_sum.get(text, merged.get('avg_conf', 0))) / max(1, hits)
            merged['hits'] = hits
            merged['avg_conf'] = round(float(support_conf), 2)
            merged['score'] = round(float(merged.get('score', 0)) + max(0, hits - 1) * TESSERACT_HIT_BONUS, 2)
            recalibrated.append(merged)

        ordered = sorted(recalibrated, key=lambda item: item['score'], reverse=True)
        best = ordered[0]
        if not is_tesseract_candidate_reliable(best):
            return {
                'text': '',
                'avg_conf': 0.0,
                'score': 0.0,
                'pattern': 'Indefinido',
                'chars': sorted(char_conf.items(), key=lambda item: -item[1])[:20],
                'candidates': ordered[:MAX_TOP_CANDIDATES],
                'raw_entries': raw_entries,
                'warning': 'tesseract_low_reliability_abstained',
            }

        char_list = sorted(char_conf.items(), key=lambda item: -item[1])
        return {
            'text': best['text'],
            'avg_conf': float(best['avg_conf']),
            'score': float(best['score']),
            'pattern': best['pattern'],
            'chars': char_list,
            'candidates': ordered[:MAX_TOP_CANDIDATES],
            'raw_entries': raw_entries,
        }
    except pytesseract.TesseractNotFoundError:
        return {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'raw_entries': [], 'error': 'tesseract_not_installed'}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'raw_entries': [], 'error': str(exc)}


def crop_from_rotated_rect(img, rect, pad_ratio=0.15):
    if plate_geometry_module is not None:
        try:
            (_, _), (width, height), _ = rect
            short_side = min(float(width), float(height))
        except Exception:
            short_side = 0.0
        adaptive_pad = plate_crop_pad_ratio(short_side, base_ratio=PLATE_CROP_PAD_RATIO)
        return plate_geometry_module.warp_rotated_rect(
            img,
            rect,
            pad_ratio=adaptive_pad,
            min_size=(PLATE_CROP_MIN_WIDTH, PLATE_CROP_MIN_HEIGHT),
        )

    (center_x, center_y), (width, height), angle = rect
    if width <= 1 or height <= 1:
        return None

    if width < height:
        width, height = height, width
        angle += 90.0

    rotated = rotate_image(img, angle)
    img_h, img_w = rotated.shape[:2]
    adaptive_pad = plate_crop_pad_ratio(min(width, height), base_ratio=pad_ratio)
    pad_w = width * adaptive_pad
    pad_h = height * (adaptive_pad * 1.1)
    x1 = int(max(0, center_x - (width / 2) - pad_w))
    y1 = int(max(0, center_y - (height / 2) - pad_h))
    x2 = int(min(img_w, center_x + (width / 2) + pad_w))
    y2 = int(min(img_h, center_y + (height / 2) + pad_h))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = rotated[y1:y2, x1:x2]
    if crop.shape[0] < PLATE_CROP_MIN_HEIGHT or crop.shape[1] < PLATE_CROP_MIN_WIDTH:
        return None
    return crop


def center_plate_guess(img):
    height, width = img.shape[:2]
    x1 = int(width * 0.18)
    x2 = int(width * 0.82)
    y1 = int(height * 0.35)
    y2 = int(height * 0.72)
    if x2 <= x1 or y2 <= y1:
        return None
    candidate = img[y1:y2, x1:x2]
    if candidate.shape[0] < 22 or candidate.shape[1] < 70:
        return None
    return candidate


def crop_ratio_box(img, x_start_ratio, x_end_ratio, y_start_ratio, y_end_ratio):
    if img is None or getattr(img, 'size', 0) == 0:
        return None

    height, width = img.shape[:2]
    x1 = int(width * float(x_start_ratio))
    x2 = int(width * float(x_end_ratio))
    y1 = int(height * float(y_start_ratio))
    y2 = int(height * float(y_end_ratio))

    x1 = max(0, min(width - 1, x1))
    x2 = max(1, min(width, x2))
    y1 = max(0, min(height - 1, y1))
    y2 = max(1, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return None

    crop = img[y1:y2, x1:x2]
    if crop is None or getattr(crop, 'size', 0) == 0:
        return None
    if crop.shape[0] < 22 or crop.shape[1] < 70:
        return None
    return crop


def heuristic_plate_guesses(img):
    guesses = []
    specs = [
        ('center_guess', 0.18, 0.82, 0.35, 0.72),
        ('center_lower_focus', 0.26, 0.76, 0.52, 0.88),
        ('lower_wide_focus', 0.16, 0.84, 0.50, 0.90),
        ('front_center_focus', 0.22, 0.78, 0.42, 0.80),
    ]
    for name, x1, x2, y1, y2 in specs:
        crop = crop_ratio_box(img, x1, x2, y1, y2)
        if crop is None:
            continue
        guesses.append((name, crop))
    return guesses


def detect_plate_regions_haar(img):
    if HAAR_PLATE_CASCADE is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return []

    gray = np.ascontiguousarray(gray)
    gray_h, gray_w = gray.shape[:2]
    if gray_w < 30 or gray_h < 12:
        return []

    min_w = max(24, min(gray_w, max(48, PLATE_DETECTION_MIN_BOX_WIDTH)))
    min_h = max(12, min(gray_h, max(16, PLATE_DETECTION_MIN_BOX_HEIGHT)))

    try:
        detections = HAAR_PLATE_CASCADE.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=3,
            minSize=(min_w, min_h),
        )
    except cv2.error:
        return []

    height, width = img.shape[:2]
    results = []
    for index, (x, y, w, h) in enumerate(detections):
        pad_x = int(w * 0.16)
        pad_y = int(h * 0.30)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(width, x + w + pad_x)
        y2 = min(height, y + h + pad_y)
        crop = img[y1:y2, x1:x2]
        if crop.shape[0] < 22 or crop.shape[1] < 70:
            continue
        results.append((f'haar_{index + 1}', crop))
    return results[:MAX_REGION_CANDIDATES]


def detect_plate_regions(img):
    if img is None:
        return []

    height, width = img.shape[:2]
    regions = []
    if height < PLATE_DETECTION_MIN_IMAGE_HEIGHT or width < PLATE_DETECTION_MIN_IMAGE_WIDTH:
        return [('full_image', img)]

    haar_regions = detect_plate_regions_haar(img)
    if haar_regions:
        regions.extend(haar_regions)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.bilateralFilter(gray, 11, 17, 17)
    grad_x = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    grad_x = cv2.convertScaleAbs(grad_x)
    grad_x = cv2.GaussianBlur(grad_x, (5, 5), 0)
    thresh = cv2.threshold(grad_x, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel, iterations=2)
    thresh = cv2.erode(thresh, None, iterations=1)
    thresh = cv2.dilate(thresh, None, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(height * width)
    rects = []

    for contour in contours:
        rect = cv2.minAreaRect(contour)
        (center_x, center_y), (rect_w, rect_h), _ = rect
        if rect_w <= 0 or rect_h <= 0:
            continue

        long_side = max(rect_w, rect_h)
        short_side = max(1.0, min(rect_w, rect_h))
        aspect = long_side / short_side
        area_ratio = (rect_w * rect_h) / image_area
        if aspect < PLATE_DETECTION_ASPECT_MIN or aspect > PLATE_DETECTION_ASPECT_MAX:
            continue
        if area_ratio < PLATE_DETECTION_AREA_MIN_RATIO or area_ratio > PLATE_DETECTION_AREA_MAX_RATIO:
            continue

        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        rectangularity = 1.0 if len(approx) in (4, 5) else 0.8
        center_bias = 1.0 - (abs(center_x - (width / 2)) / (width / 2 + 1e-6)) * 0.30 - (abs(center_y - (height / 2)) / (height / 2 + 1e-6)) * 0.10
        aspect_bonus = max(0.0, 1.0 - abs(aspect - PLATE_DETECTION_ASPECT_TARGET) / 3.0)
        if aspect < PLATE_DETECTION_ASPECT_MIN or aspect > PLATE_DETECTION_ASPECT_MAX:
            aspect_bonus *= 0.45
        score = (min(aspect, 7.5) / 7.5) + (area_ratio * 4.2) + rectangularity + center_bias + (aspect_bonus * 1.1)
        rects.append((score, rect))

    rects.sort(key=lambda item: item[0], reverse=True)
    seen = set()
    for _, rect in rects:
        crop = crop_from_rotated_rect(img, rect)
        if crop is None:
            continue
        signature = (
            int(rect[0][0] // 12),
            int(rect[0][1] // 12),
            int(max(rect[1]) // 10),
            int(min(rect[1]) // 6),
        )
        if signature in seen:
            continue
        seen.add(signature)
        regions.append((f'detected_{len(regions) + 1}', crop))
        if len(regions) >= MAX_REGION_CANDIDATES:
            break

    for guess_name, guess_img in heuristic_plate_guesses(img):
        if len(regions) >= MAX_REGION_CANDIDATES:
            break
        regions.append((guess_name, guess_img))

    if not regions:
        guessed = center_plate_guess(img)
        if guessed is not None:
            regions.append(('center_guess', guessed))

    regions.append(('full_image', img))
    return rank_plate_regions(regions)


def deduplicate_regions(regions):
    deduped = []
    seen = set()
    for name, region in regions:
        if region is None:
            continue
        height, width = region.shape[:2]
        mean = int(np.mean(region))
        signature = (height, width, mean)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append((name, region))
    return deduped


def plate_region_source_family(region_name):
    name = str(region_name or '').strip().lower()
    if name.startswith('raw_'):
        name = name[4:]
    if name in ('input', 'raw_input'):
        return 'secondary'
    if name.startswith('plate_recognizer_roi'):
        return 'external_box'
    if name.startswith('yolo_roi'):
        return 'yolo'
    if name.startswith('haar_'):
        return 'haar'
    if name.startswith('detected_'):
        return 'contour'
    if 'focus' in name or 'center_guess' in name or name.startswith('lower_') or name.startswith('front_'):
        return 'heuristic'
    if name.startswith('raw_'):
        return 'secondary'
    if name == 'full_image':
        return 'fallback_full_scene'
    return 'unknown'


def plate_region_name_bonus(region_name):
    family = plate_region_source_family(region_name)
    bonuses = {
        'external_box': 160.0,
        'yolo': 250.0,
        'haar': 10.0,
        'contour': 11.0,
        'heuristic': 6.0,
        'secondary': 3.0,
        'fallback_full_scene': -38.0,
        'unknown': 0.0,
    }
    return float(bonuses.get(family, 0.0))


def describe_plate_region(region_name, region_img):
    if plate_geometry_module is not None:
        metrics = dict(plate_geometry_module.describe_plate_crop(region_img))
    else:
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            metrics = {'quality_score': 0.0, 'quality_label': 'critica'}
        else:
            if len(region_img.shape) == 2:
                gray = region_img
            else:
                gray = cv2.cvtColor(region_img, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
            contrast = float(np.std(gray))
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            p95, p5 = np.percentile(gray, [95, 5])
            dynamic_range = float(p95 - p5)
            area = int(gray.shape[0] * gray.shape[1])
            quality_score = (
                min(100.0, sharpness / 3.2)
                + min(100.0, contrast * 1.25)
                + min(100.0, dynamic_range * 0.58)
            ) / 3.0
            metrics = {
                'quality_score': round(float(quality_score), 1),
                'quality_label': 'boa' if quality_score >= 65 else 'regular' if quality_score >= 45 else 'critica',
                'aspect_ratio': round(float(gray.shape[1]) / float(max(1, gray.shape[0])), 3),
                'area': area,
                'brightness': round(brightness, 2),
                'contrast': round(contrast, 2),
                'sharpness': round(sharpness, 2),
                'dynamic_range': round(dynamic_range, 2),
                'edge_density': round(float(np.mean(cv2.Canny(gray, 80, 200) > 0) * 100.0), 2),
                'foreground_ratio': round(float(np.mean((gray > 18) & (gray < 242)) * 100.0), 2),
                'shape_hint': 'wide' if gray.shape[1] / float(max(1, gray.shape[0])) >= 3.0 else 'compacta',
            }

    family = plate_region_source_family(region_name)
    aspect_ratio = float(metrics.get('aspect_ratio', 0.0))
    quality_label = str(metrics.get('quality_label', 'critica') or 'critica').strip().lower()
    plausibility_bonus = 0.0
    if aspect_ratio > 0:
        if 3.2 <= aspect_ratio <= 5.8:
            plausibility_bonus += 6.0
        elif 2.2 <= aspect_ratio < 3.2 or 5.8 < aspect_ratio <= 7.2:
            plausibility_bonus += 2.5
        elif aspect_ratio < 1.8 or aspect_ratio > 8.5:
            plausibility_bonus -= 8.0
    if quality_label == 'excelente':
        plausibility_bonus += 3.5
    elif quality_label == 'boa':
        plausibility_bonus += 2.0
    elif quality_label == 'critica':
        plausibility_bonus -= 3.0

    score = float(metrics.get('quality_score', 0.0)) + plate_region_name_bonus(region_name) + plausibility_bonus
    metrics.update({
        'region': region_name,
        'source_family': family,
        'plausibility_bonus': round(float(plausibility_bonus), 1),
        'score': round(float(score), 1),
    })
    return metrics


def rank_plate_regions(regions):
    if not isinstance(regions, list) or not regions:
        return regions

    ranked = []
    seen = set()
    for index, item in enumerate(regions):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        region_name, region_img = item[0], item[1]
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue
        signature = (
            int(region_img.shape[0]),
            int(region_img.shape[1]),
            int(float(np.mean(region_img))),
            int(float(np.std(region_img))),
        )
        if signature in seen:
            continue
        seen.add(signature)
        metrics = describe_plate_region(region_name, region_img)
        ranked.append((
            float(metrics.get('score', 0.0)),
            index,
            str(region_name),
            region_img,
        ))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[2] != 'full_image',
            item[1],
        ),
        reverse=True,
    )
    return [(name, img) for _, _, name, img in ranked]


def build_plate_detection_summary(plate_regions, selected_region_name=None):
    if not isinstance(plate_regions, list) or not plate_regions:
        return {
            'status': 'sem_candidato',
            'strategy': 'plate_roi_first',
            'candidate_count': 0,
            'selected_region': '',
            'selected_source': 'none',
            'selected_quality_score': 0.0,
            'selected_score': 0.0,
            'selected_aspect_ratio': 0.0,
            'selected_quality_label': 'indefinida',
            'selected_plausibility_bonus': 0.0,
            'calibration_source': 'builtin_default',
            'calibration_path': PLATE_DETECTION_CALIBRATION_PATH,
            'selected_metrics': {},
            'selected_shape_hint': 'indefinida',
            'selected_style_hint': 'indefinida',
            'selected_style_confidence': 0.0,
            'used_full_image': False,
            'canonical_pipeline': True,
            'ocr_line_mode': 'single_line',
            'tesseract_whitelist': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            'candidates': [],
        }

    candidates = []
    for region_name, region_img in plate_regions:
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue
        metrics = describe_plate_region(region_name, region_img)
        candidates.append(metrics)

    candidates.sort(
        key=lambda item: (
            float(item.get('score', 0.0)),
            item.get('region', '') != 'full_image',
            float(item.get('quality_score', 0.0)),
        ),
        reverse=True,
    )

    selected = None
    if selected_region_name:
        selected = next((item for item in candidates if str(item.get('region', '')) == str(selected_region_name)), None)
    if selected is None and candidates:
        selected = candidates[0]

    if selected and str(selected.get('region', '')) == 'full_image':
        best_non_full = next((item for item in candidates if str(item.get('region', '')) != 'full_image'), None)
        if best_non_full is not None:
            selected_score = float(selected.get('score', 0.0))
            best_non_full_score = float(best_non_full.get('score', 0.0))
            score_gap = selected_score - best_non_full_score
            if score_gap < FULL_IMAGE_SELECTION_MARGIN:
                selected = best_non_full

    status = 'sem_candidato'
    if selected:
        status = 'fallback_full_scene' if str(selected.get('region', '')) == 'full_image' else 'roi_detectado'

    return {
        'status': status,
        'strategy': 'plate_roi_first',
        'candidate_count': len(candidates),
        'selected_region': str((selected or {}).get('region', '') or ''),
        'selected_source': str((selected or {}).get('source_family', 'none') or 'none'),
        'selected_quality_score': float((selected or {}).get('quality_score', 0.0)),
        'selected_score': float((selected or {}).get('score', 0.0)),
        'selected_aspect_ratio': float((selected or {}).get('aspect_ratio', 0.0)),
        'selected_quality_label': str((selected or {}).get('quality_label', 'indefinida') or 'indefinida'),
        'selected_plausibility_bonus': float((selected or {}).get('plausibility_bonus', 0.0)),
        'calibration_source': str((selected or {}).get('calibration_source', 'builtin_default') or 'builtin_default'),
        'calibration_path': str((selected or {}).get('calibration_path', PLATE_DETECTION_CALIBRATION_PATH)),
        'selected_metrics': selected or {},
        'selected_shape_hint': str((selected or {}).get('shape_hint', 'indefinida')),
        'selected_style_hint': str((selected or {}).get('style_hint', 'indefinida')),
        'selected_style_confidence': float((selected or {}).get('style_confidence', 0.0)),
        'used_full_image': bool(selected and str(selected.get('region', '')) == 'full_image'),
        'canonical_pipeline': True,
        'ocr_line_mode': 'single_line',
        'tesseract_whitelist': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
        'candidates': candidates[:5],
    }


def build_plate_regions(img, external_box, include_yolo=True):
    regions = []
    regions.append(('raw_input', img))

    external_crop = canonicalize_plate_crop(crop_image_from_box(img, external_box))
    if external_crop is not None:
        regions.append(('plate_recognizer_roi', external_crop))

    for region_name, region_img in detect_plate_regions(img):
        if region_name == 'full_image' and external_crop is not None:
            continue
        regions.append((region_name, canonicalize_plate_crop(region_img)))

    if include_yolo:
        yolo_box = detect_plate_yolo(img)
        if yolo_box:
            x, y, w, h = yolo_box
            yolo_crop = crop_image_from_box(img, {'x': x, 'y': y, 'w': w, 'h': h})
            if yolo_crop is not None and yolo_crop.size > 0:
                regions.append(('yolo_roi', canonicalize_plate_crop(yolo_crop)))

    regions = deduplicate_regions(regions)
    regions = rank_plate_regions(regions)
    if not regions:
        regions = [('full_image', img)]
    return regions


def build_plate_regions_multisource(primary_img, external_box, secondary_img=None, include_yolo=True):
    primary_regions = build_plate_regions(primary_img, external_box, include_yolo=include_yolo)
    if secondary_img is None or secondary_img is primary_img:
        return primary_regions

    secondary_regions = []
    for region_name, region_img in build_plate_regions(secondary_img, external_box, include_yolo=include_yolo):
        secondary_regions.append((f'raw_{region_name}', region_img))

    merged = deduplicate_regions(primary_regions + secondary_regions)
    merged = rank_plate_regions(merged)
    if not merged:
        merged = primary_regions if primary_regions else [('full_image', primary_img)]
    return merged


def limit_regions_for_pdf(plate_regions):
    if not isinstance(plate_regions, list) or not plate_regions:
        return plate_regions

    prioritized = [item for item in plate_regions if item[0] != 'full_image']

    def _pdf_region_priority(item):
        name = str((item or ('', None))[0] or '').lower()
        score = 0.0
        if name.startswith('plate_recognizer_roi'):
            score += 120.0
        if 'haar' in name:
            score += 92.0
        if 'focus' in name or 'center_guess' in name:
            score += 88.0
        if name.startswith('detected_'):
            score += 74.0
        if name.startswith('raw_'):
            score -= 8.0
        region_img = (item or ('', None))[1]
        if region_img is not None and getattr(region_img, 'size', 0) > 0:
            h, w = region_img.shape[:2]
            area = float(h * w)
            if 18_000 <= area <= 360_000:
                score += 6.0
        return score

    prioritized.sort(key=_pdf_region_priority, reverse=True)
    selected = prioritized[:PDF_MAX_REGION_CANDIDATES] if prioritized else []
    full_regions = [item for item in plate_regions if item[0] == 'full_image']
    if full_regions:
        selected.append(full_regions[0])
    if not selected:
        selected = plate_regions[:1]

    normalized = []
    for region_name, region_img in selected:
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue
        resized = resize_region_for_ocr(region_img, max_side=PDF_REGION_MAX_SIDE)
        normalized.append((region_name, resized if resized is not None else region_img))

    deduped = deduplicate_regions(normalized)
    if not deduped:
        deduped = deduplicate_regions(selected)
    return deduped[:max(1, PDF_MAX_REGION_CANDIDATES + 1)]


def budget_regions_for_speed(plate_regions, plate_detection=None):
    if not isinstance(plate_regions, list) or not plate_regions:
        return plate_regions

    selected_quality = 0.0
    selected_source = ''
    selected_region = ''
    if isinstance(plate_detection, dict):
        selected_quality = float(plate_detection.get('selected_quality_score', 0.0) or 0.0)
        selected_source = str(plate_detection.get('selected_source', '') or '')
        selected_region = str(plate_detection.get('selected_region', '') or '')

    if OCR_ACCURACY_FIRST:
        region_limit = max(1, len([item for item in plate_regions if item[0] != 'full_image']))
    else:
        if selected_quality >= 84.0 and selected_source in ('contour', 'haar', 'yolo', 'external_box'):
            region_limit = 2
        elif selected_quality >= 76.0:
            region_limit = 3
        elif selected_quality >= 64.0:
            region_limit = 4
        else:
            region_limit = min(5, MAX_REGION_CANDIDATES)

    prioritized = []
    full_region = []
    metrics_by_region = {}
    if isinstance(plate_detection, dict):
        selected_metrics = plate_detection.get('selected_metrics', {})
        if isinstance(selected_metrics, dict) and selected_metrics.get('region'):
            metrics_by_region[str(selected_metrics.get('region'))] = selected_metrics
        for item in plate_detection.get('candidates', []):
            if not isinstance(item, dict):
                continue
            region_key = str(item.get('region', '') or '').strip()
            if region_key:
                metrics_by_region[region_key] = item

    seen = set()
    for region_name, region_img in plate_regions:
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue
        signature = (
            int(region_img.shape[0]),
            int(region_img.shape[1]),
            int(float(np.mean(region_img))),
            int(float(np.std(region_img))),
        )
        if signature in seen:
            continue
        seen.add(signature)
        if str(region_name) == 'full_image':
            full_region.append((region_name, region_img))
        else:
            prioritized.append((region_name, region_img))

    def _ocr_region_priority(item):
        region_name, region_img = item
        metrics = metrics_by_region.get(str(region_name))
        if not isinstance(metrics, dict):
            metrics = describe_plate_region(region_name, region_img)

        score = float(metrics.get('quality_score', 0.0))
        score += min(10.0, float(metrics.get('area', 0.0)) / 22000.0)
        score += min(8.0, float(metrics.get('sharpness', 0.0)) / 900.0)
        score += min(6.0, float(metrics.get('edge_density', 0.0)) / 3.5)
        score += min(4.0, float(metrics.get('foreground_ratio', 0.0)) / 20.0)

        aspect_ratio = float(metrics.get('aspect_ratio', 0.0))
        if 2.2 <= aspect_ratio <= 4.8:
            score += 2.5
        elif aspect_ratio < 1.8 or aspect_ratio > 6.8:
            score -= 5.0

        family = str(metrics.get('source_family', '') or '').lower()
        if family == 'yolo':
            score += 9.0
        elif family in ('external_box', 'contour'):
            score += 4.0
        elif family == 'secondary':
            score += 2.0
        elif family == 'haar':
            score += 1.5
        elif family == 'heuristic':
            score += 0.75

        region_label = str(region_name or '').lower()
        if 'wide' in region_label:
            score += 0.8
        if 'center' in region_label:
            score += 0.2

        return score

    prioritized.sort(key=_ocr_region_priority, reverse=True)
    trimmed = prioritized if OCR_ACCURACY_FIRST else prioritized[:max(1, region_limit)]
    keep_full_image = selected_quality < 56.0 or not trimmed
    if keep_full_image and full_region:
        trimmed.append(full_region[0])
    return trimmed if trimmed else (full_region[:1] if full_region else plate_regions[:1])


def ocr_tesseract_regions(regions):
    if not regions:
        return {'text': '', 'avg_conf': 0, 'score': 0, 'pattern': 'Indefinido', 'chars': [], 'candidates': [], 'regions_tested': []}

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    candidates_by_text = {}
    regions_tested = []
    warnings = []

    for region_name, region_img in regions:
        if region_img is None:
            continue
        if region_img.shape[0] < 22 or region_img.shape[1] < 70:
            continue

        result = ocr_tesseract(region_img)
        regions_tested.append({
            'region': region_name,
            'text': result.get('text', ''),
            'score': float(result.get('score', 0)),
            'avg_conf': float(result.get('avg_conf', 0)),
            'pattern': result.get('pattern', 'Indefinido'),
        })

        if result.get('error'):
            warnings.append(f'{region_name}:{result["error"]}')
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')

        for char, conf in result.get('chars', []):
            conf_value = parse_confidence(conf)
            if conf_value > char_conf[char]:
                char_conf[char] = conf_value

        for candidate in result.get('candidates', []):
            candidate_text = normalize_plate_text(candidate.get('text', ''))
            if not candidate_text:
                continue
            merged = dict(candidate)
            merged['text'] = candidate_text
            merged['region'] = region_name
            previous = candidates_by_text.get(candidate_text)
            if previous is None or merged.get('score', 0) > previous.get('score', 0):
                candidates_by_text[candidate_text] = merged

        if result.get('text'):
            normalized_best = normalize_plate_text(result['text'])
            if normalized_best:
                candidate_best = {
                    'text': normalized_best,
                    'avg_conf': float(result.get('avg_conf', 0)),
                    'score': float(result.get('score', 0)),
                    'pattern': result.get('pattern', 'Indefinido'),
                    'penalty': 0,
                    'variant': 'best_region',
                    'psm': 0,
                    'region': region_name,
                }
                previous = candidates_by_text.get(normalized_best)
                if previous is None or candidate_best['score'] > previous.get('score', 0):
                    candidates_by_text[normalized_best] = candidate_best

                if candidate_best['score'] > best_score:
                    best_score = candidate_best['score']
                    best = {
                        'text': normalized_best,
                        'avg_conf': candidate_best['avg_conf'],
                        'score': candidate_best['score'],
                        'pattern': candidate_best['pattern'],
                        'region': region_name,
                    }

                if (
                    not OCR_ACCURACY_FIRST
                    and best is not None
                    and best.get('pattern', 'Indefinido') != 'Indefinido'
                    and float(best.get('score', 0)) >= TESSERACT_REGION_EARLY_SCORE
                    and float(best.get('avg_conf', 0)) >= OCR_PATTERN_MIN_CONFIDENCE
                ):
                    break

    if best is None:
        payload = {
            'text': '',
            'avg_conf': 0,
            'score': 0,
            'pattern': 'Indefinido',
            'chars': [],
            'candidates': [],
            'regions_tested': regions_tested,
        }
        if warnings:
            payload['error'] = ';'.join(warnings)
        return payload

    ordered_candidates = sorted(candidates_by_text.values(), key=lambda item: item.get('score', 0), reverse=True)
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'region': best.get('region'),
        'chars': sorted(char_conf.items(), key=lambda item: -item[1]),
        'candidates': ordered_candidates[:MAX_TOP_CANDIDATES],
        'regions_tested': regions_tested,
    }
    if warnings:
        response['warning'] = ';'.join(warnings[:3])
    return response


@lru_cache(maxsize=1)
def get_easyocr_reader():
    if easyocr is None or not EASYOCR_ENABLED:
        return None
    return easyocr.Reader(['pt', 'en'], gpu=False, verbose=False)


def read_easyocr_with_profile(reader, img):
    kwargs = {}
    if EASYOCR_ALLOWLIST:
        kwargs['allowlist'] = EASYOCR_ALLOWLIST
    if EASYOCR_DECODER:
        kwargs['decoder'] = EASYOCR_DECODER
    kwargs['beamWidth'] = EASYOCR_BEAM_WIDTH

    try:
        return reader.readtext(img, **kwargs)
    except TypeError:
        return reader.readtext(img)


def build_easyocr_sources(entries):
    if not entries:
        return []

    sources = []
    seen = set()

    def add_source(text, conf, origin):
        text = normalize_plate_text(text)
        if not is_plate_like_text(text):
            return
        key = (text, origin)
        if key in seen:
            return
        seen.add(key)
        sources.append({
            'text': text,
            'conf': float(conf),
            'origin': origin,
        })

    for entry in entries:
        word = entry['word']
        conf = float(entry['conf'])
        letters = sum(char.isalpha() for char in word)
        digits = sum(char.isdigit() for char in word)
        if detect_plate_pattern(word) != 'Indefinido':
            add_source(word, conf + 8.0, 'word_pattern')
            continue
        if 5 <= len(word) <= 8:
            add_source(word, conf, 'word')
            continue
        if len(word) <= 10 and letters >= 2 and digits >= 2:
            add_source(word, conf * 0.9, 'word_mixed')

    for index in range(len(entries) - 1):
        left = entries[index]
        right = entries[index + 1]
        combo = left['word'] + right['word']
        if 6 <= len(combo) <= 8:
            combo_conf = min(float(left['conf']), float(right['conf'])) * 0.96
            add_source(combo, combo_conf, 'pair')

    if not sources:
        text_blob = ''.join(entry['word'] for entry in entries)
        avg_conf = float(np.mean([entry['conf'] for entry in entries]))
        add_source(text_blob, avg_conf * 0.85, 'blob_fallback')

    return sources


def rank_ocr_candidates_from_entries(entries, variant_name, hit_bonus):
    if not entries:
        return {
            'text': '',
            'avg_conf': 0,
            'chars': [],
            'score': 0,
            'pattern': 'Indefinido',
            'candidates': [],
        }

    chars = []
    for entry in entries:
        conf = float(entry.get('conf', 0))
        for char in entry.get('word', ''):
            chars.append((char, conf))

    sources = build_easyocr_sources(entries)
    candidates = {}
    all_confidences = [float(entry.get('conf', 0)) for entry in entries if float(entry.get('conf', 0)) > 0]

    for source in sources:
        source_text = source['text']
        source_conf = float(source['conf'])
        for hypothesis in build_plate_hypotheses(source_text):
            text = hypothesis['text']
            penalty = hypothesis['penalty']
            score, pattern = score_hypothesis(
                text,
                source_conf,
                penalty,
                hypothesis.get('slot_score', 0.0),
                hypothesis.get('target_pattern', 'Indefinido'),
                hypothesis.get('exact_matches', 0),
                hypothesis.get('soft_matches', 0),
                hypothesis.get('hard_mismatches', 0),
            )
            candidate = {
                'text': text,
                'avg_conf': source_conf,
                'score': float(score),
                'pattern': pattern,
                'penalty': penalty,
                'slot_score': round(float(hypothesis.get('slot_score', 0.0)), 2),
                'target_pattern': hypothesis.get('target_pattern', 'Indefinido'),
                'exact_matches': int(hypothesis.get('exact_matches', 0)),
                'soft_matches': int(hypothesis.get('soft_matches', 0)),
                'hard_mismatches': int(hypothesis.get('hard_mismatches', 0)),
                'variant': variant_name,
                'psm': 0,
                'origin': source['origin'],
                'hits': 1,
            }

            previous = candidates.get(text)
            if previous is None:
                candidates[text] = candidate
            else:
                previous['hits'] = int(previous.get('hits', 1)) + 1
                if candidate['score'] > previous['score']:
                    previous.update({
                        'avg_conf': candidate['avg_conf'],
                        'score': candidate['score'],
                        'pattern': candidate['pattern'],
                        'penalty': candidate['penalty'],
                        'origin': candidate['origin'],
                    })

    for candidate in candidates.values():
        extra_hits = max(0, int(candidate.get('hits', 1)) - 1)
        candidate['score'] = round(float(candidate['score']) + (extra_hits * hit_bonus), 2)
        candidate['avg_conf'] = round(float(candidate.get('avg_conf', 0)), 2)

    if candidates:
        ordered = sorted(candidates.values(), key=lambda item: item['score'], reverse=True)
        best = ordered[0]
        return {
            'text': best['text'],
            'avg_conf': float(best['avg_conf']),
            'chars': chars,
            'score': float(best['score']),
            'pattern': best['pattern'],
            'candidates': ordered[:MAX_TOP_CANDIDATES],
        }

    text_blob = ''.join(entry['word'] for entry in entries)
    if not is_plate_like_text(text_blob):
        return {'text': '', 'avg_conf': 0, 'chars': chars, 'score': 0, 'pattern': 'Indefinido', 'candidates': []}
    avg_conf = float(np.mean(all_confidences)) if all_confidences else 0.0
    score, pattern = score_hypothesis(text_blob, avg_conf, 0)
    return {'text': text_blob, 'avg_conf': avg_conf, 'chars': chars, 'score': score, 'pattern': pattern, 'candidates': []}


def parse_easyocr_entries(raw_result):
    entries = []
    chars = []
    for item in raw_result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        word = normalize_plate_text(item[1])
        conf = parse_confidence(item[2]) * 100.0
        if not word or conf <= 0:
            continue
        entries.append({'word': word, 'conf': float(conf)})
        chars.extend([(char, float(conf)) for char in word])
    return entries, chars


def easyocr_variant_quality_score(variant_img):
    if variant_img is None or getattr(variant_img, 'size', 0) == 0:
        return 0.0

    if len(variant_img.shape) == 2:
        gray = variant_img
    else:
        gray = cv2.cvtColor(variant_img, cv2.COLOR_BGR2GRAY)

    contrast = float(np.std(gray))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    p95, p5 = np.percentile(gray, [95, 5])
    dynamic_range = float(p95 - p5)
    mid_ratio = float(np.mean((gray >= 24) & (gray <= 235)))

    score = (
        (min(72.0, contrast) / 72.0) * 0.33
        + (min(420.0, blur) / 420.0) * 0.34
        + (min(170.0, dynamic_range) / 170.0) * 0.23
        + (mid_ratio * 0.10)
    )

    if contrast < 16.0:
        score *= 0.72
    if blur < 32.0:
        score *= 0.74

    return max(0.0, min(1.0, float(score)))


def build_easyocr_variant_inputs(img):
    variants = []

    if EASYOCR_DYNAMIC_VARIANTS:
        for variant_name, variant_img in build_ocr_variants(img):
            quality = easyocr_variant_quality_score(variant_img)
            variants.append((variant_name, variant_img, quality))
    else:
        try:
            base = preprocess_plate(img)
        except Exception:
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants.append(('easy_base', base, easyocr_variant_quality_score(base)))

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()

    for preferred_name in ('raw_gray', 'upscaled_gray'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= EASYOCR_MAX_VARIANTS:
            break

    return selected[:EASYOCR_MAX_VARIANTS]


def is_easyocr_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))

    if pattern != 'Indefinido':
        if score >= EASYOCR_PATTERN_MIN_SCORE and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE:
            return True
        if score >= max(EASYOCR_PATTERN_MIN_SCORE + 8.0, EASYOCR_MIN_ACCEPT_SCORE + 12.0) and variant_hits >= EASYOCR_MIN_VARIANT_HITS:
            return True
        if score >= EASYOCR_PATTERN_MIN_SCORE + 4.0 and hits >= 2 and avg_conf >= EASYOCR_MIN_ACCEPT_CONF:
            return True
        return False

    if (
        score >= EASYOCR_MIN_ACCEPT_SCORE
        and avg_conf >= EASYOCR_MIN_ACCEPT_CONF
        and variant_hits >= EASYOCR_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_easyocr_variant_rankings(variant_rankings, char_conf_map):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if vote_text:
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.8
            if pattern != 'Indefinido':
                quality_bonus += 0.35
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * EASYOCR_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(7.2, disagreement * 1.6)
        if pattern == 'Indefinido' and variant_hits < EASYOCR_MIN_VARIANT_HITS:
            conflict_penalty += 3.2

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }

    if not is_easyocr_candidate_reliable(best) and best.get('pattern') == 'Indefinido':
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'easyocr_low_reliability_abstained'
        return response
    return response


def ocr_easyocr(img):
    if easyocr is None or not EASYOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    try:
        reader = get_easyocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': [], 'error': str(exc)}

    variant_inputs = build_easyocr_variant_inputs(img)
    if not variant_inputs:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    char_conf = defaultdict(float)
    variant_rankings = []
    raw_entries = []
    warnings = []
    for variant_name, variant_img, variant_quality in variant_inputs:
        try:
            raw_result = read_easyocr_with_profile(reader, variant_img)
        except Exception as exc:
            warnings.append(f'{variant_name}:{exc}')
            continue

        entries, chars = parse_easyocr_entries(raw_result)
        if not entries:
            continue
        for entry in entries:
            raw_entries.append({
                'word': entry.get('word', ''),
                'conf': float(entry.get('conf', 0.0)),
                'variant': variant_name,
                'engine': 'easyocr',
            })
        for char, conf in chars:
            if conf > char_conf[char]:
                char_conf[char] = conf

        ranked = rank_ocr_candidates_from_entries(entries, variant_name, EASYOCR_HIT_BONUS)
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = round(float(variant_quality), 4)
        ranked['chars'] = chars
        variant_rankings.append(ranked)

        if (
            not OCR_ACCURACY_FIRST
            and ranked.get('pattern', 'Indefinido') != 'Indefinido'
            and len(normalize_plate_text(ranked.get('text', ''))) >= 6
            and float(ranked.get('score', 0)) >= (EASYOCR_REGION_EARLY_SCORE + 8.0)
            and len(variant_rankings) >= max(2, EASYOCR_MIN_VARIANT_HITS)
        ):
            break

    if not variant_rankings:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': raw_entries}
        if warnings:
            payload['warning'] = ';'.join(warnings[:2])
        return payload

    merged = merge_easyocr_variant_rankings(variant_rankings, char_conf)
    merged['raw_entries'] = raw_entries
    if warnings:
        warning_tail = ';'.join(warnings[:2])
        existing = str(merged.get('warning', '') or '').strip()
        merged['warning'] = f'{existing};{warning_tail}' if existing else warning_tail
    return merged


def ocr_easyocr_regions(regions):
    if easyocr is None or not EASYOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}

    prioritized = [item for item in regions if item[0] != 'full_image']
    full_region = [item for item in regions if item[0] == 'full_image']
    if full_region:
        prioritized.append(full_region[0])

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    warnings = []
    for region_name, region_img in prioritized:
        if region_img is None:
            continue
        result = ocr_easyocr(region_img)
        if result.get('error'):
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')
        for char, conf in result.get('chars', []):
            if conf > char_conf[char]:
                char_conf[char] = conf
        if result.get('text') and result.get('score', 0) > best_score:
            best = dict(result)
            best['region'] = region_name
            best_score = result.get('score', 0)
            if (
                not OCR_ACCURACY_FIRST
                and best.get('pattern') != 'Indefinido'
                and float(best.get('score', 0)) >= EASYOCR_REGION_EARLY_SCORE
            ):
                break

    if best is None:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return payload

    best['chars'] = sorted(char_conf.items(), key=lambda item: -item[1])
    if warnings and not best.get('warning'):
        best['warning'] = ';'.join(warnings[:2])
    return best


@lru_cache(maxsize=1)
def get_rapidocr_reader():
    if RapidOCR is None or not RAPIDOCR_ENABLED:
        return None
    return RapidOCR()


def parse_rapidocr_entries(raw_result):
    entries = []
    chars = []
    for item in raw_result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        word = normalize_plate_text(item[1])
        conf = parse_confidence(item[2]) * 100.0
        if not word or conf <= 0:
            continue
        entries.append({'word': word, 'conf': float(conf)})
        chars.extend([(char, float(conf)) for char in word])
    return entries, chars


def build_rapidocr_variant_inputs(img):
    variants = []

    if RAPIDOCR_DYNAMIC_VARIANTS:
        for variant_name, variant_img in build_ocr_variants(img):
            quality = easyocr_variant_quality_score(variant_img)
            variants.append((variant_name, variant_img, quality))
    else:
        try:
            base = preprocess_plate(img)
        except Exception:
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants.append(('rapid_base', base, easyocr_variant_quality_score(base)))

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()

    for preferred_name in ('raw_gray', 'upscaled_gray'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= RAPIDOCR_MAX_VARIANTS:
            break

    return selected[:RAPIDOCR_MAX_VARIANTS]


def is_rapidocr_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))

    if pattern != 'Indefinido':
        if score >= RAPIDOCR_PATTERN_MIN_SCORE and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE:
            return True
        if score >= max(RAPIDOCR_PATTERN_MIN_SCORE + 8.0, RAPIDOCR_MIN_ACCEPT_SCORE + 11.0) and variant_hits >= RAPIDOCR_MIN_VARIANT_HITS:
            return True
        if score >= RAPIDOCR_PATTERN_MIN_SCORE + 4.0 and hits >= 2 and avg_conf >= RAPIDOCR_MIN_ACCEPT_CONF:
            return True
        return False

    if (
        score >= RAPIDOCR_MIN_ACCEPT_SCORE
        and avg_conf >= RAPIDOCR_MIN_ACCEPT_CONF
        and variant_hits >= RAPIDOCR_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_rapidocr_variant_rankings(variant_rankings, char_conf_map):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if vote_text:
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.6
            if pattern != 'Indefinido':
                quality_bonus += 0.30
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * RAPIDOCR_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(7.0, disagreement * 1.5)
        if pattern == 'Indefinido' and variant_hits < RAPIDOCR_MIN_VARIANT_HITS:
            conflict_penalty += 3.0

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }

    if not is_rapidocr_candidate_reliable(best) and best.get('pattern') == 'Indefinido':
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'rapidocr_low_reliability_abstained'
        return response
    return response


def ocr_rapidocr(img):
    if RapidOCR is None or not RAPIDOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    try:
        reader = get_rapidocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': [], 'error': str(exc)}

    variant_inputs = build_rapidocr_variant_inputs(img)
    if not variant_inputs:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    char_conf = defaultdict(float)
    variant_rankings = []
    raw_entries = []
    warnings = []
    for variant_name, variant_img, variant_quality in variant_inputs:
        try:
            raw_result, _ = reader(variant_img)
        except Exception as exc:
            warnings.append(f'{variant_name}:{exc}')
            continue

        entries, chars = parse_rapidocr_entries(raw_result)
        if not entries:
            continue
        for entry in entries:
            raw_entries.append({
                'word': entry.get('word', ''),
                'conf': float(entry.get('conf', 0.0)),
                'variant': variant_name,
                'engine': 'rapidocr',
            })

        for char, conf in chars:
            if conf > char_conf[char]:
                char_conf[char] = conf

        ranked = rank_ocr_candidates_from_entries(entries, variant_name, RAPIDOCR_HIT_BONUS)
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = round(float(variant_quality), 4)
        ranked['chars'] = chars
        variant_rankings.append(ranked)

        if (
            not OCR_ACCURACY_FIRST
            and ranked.get('pattern', 'Indefinido') != 'Indefinido'
            and len(normalize_plate_text(ranked.get('text', ''))) >= 6
            and float(ranked.get('score', 0)) >= (RAPIDOCR_REGION_EARLY_SCORE + 8.0)
            and len(variant_rankings) >= max(2, RAPIDOCR_MIN_VARIANT_HITS)
        ):
            break

    if not variant_rankings:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': raw_entries}
        if warnings:
            payload['warning'] = ';'.join(warnings[:2])
        return payload

    merged = merge_rapidocr_variant_rankings(variant_rankings, char_conf)
    merged['raw_entries'] = raw_entries
    if warnings:
        warning_tail = ';'.join(warnings[:2])
        existing = str(merged.get('warning', '') or '').strip()
        merged['warning'] = f'{existing};{warning_tail}' if existing else warning_tail
    return merged


def ocr_rapidocr_regions(regions):
    if RapidOCR is None or not RAPIDOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    prioritized = [item for item in regions if item[0] != 'full_image']
    full_region = [item for item in regions if item[0] == 'full_image']
    if full_region:
        prioritized.append(full_region[0])

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    warnings = []
    for region_name, region_img in prioritized:
        if region_img is None:
            continue
        result = ocr_rapidocr(region_img)
        if result.get('error'):
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')
        for char, conf in result.get('chars', []):
            if conf > char_conf[char]:
                char_conf[char] = conf
        if result.get('text') and result.get('score', 0) > best_score:
            best = dict(result)
            best['region'] = region_name
            best_score = result.get('score', 0)
            if (
                not OCR_ACCURACY_FIRST
                and best.get('pattern') != 'Indefinido'
                and float(best.get('score', 0)) >= RAPIDOCR_REGION_EARLY_SCORE
            ):
                break

    if best is None:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return payload

    best['chars'] = sorted(char_conf.items(), key=lambda item: -item[1])
    if warnings and not best.get('warning'):
        best['warning'] = ';'.join(warnings[:2])
    return best


@lru_cache(maxsize=1)
def get_trocr_bundle():
    if (
        not TROCR_ENABLED
        or TrOCRProcessor is None
        or VisionEncoderDecoderModel is None
        or torch is None
        or Image is None
    ):
        return None, None

    processor = TrOCRProcessor.from_pretrained(TROCR_MODEL_ID, local_files_only=TROCR_LOCAL_ONLY)
    model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL_ID, local_files_only=TROCR_LOCAL_ONLY)
    model.eval()
    return processor, model


def trocr_confidence_hint(text):
    confidence = float(TROCR_BASE_CONFIDENCE)
    if len(text) == 7:
        confidence += 9.0
    else:
        confidence -= abs(7 - len(text)) * 3.5
    if detect_plate_pattern(text) != 'Indefinido':
        confidence += 14.0
    digits = sum(char.isdigit() for char in text)
    letters = sum(char.isalpha() for char in text)
    if digits >= 2 and letters >= 3:
        confidence += 5.0
    return max(6.0, min(95.0, confidence))


def build_trocr_variant_inputs(img):
    variants = []

    if TROCR_DYNAMIC_VARIANTS:
        for variant_name, variant_img in build_ocr_variants(img):
            quality = easyocr_variant_quality_score(variant_img)
            variants.append((variant_name, variant_img, quality))
    else:
        try:
            base = preprocess_plate(img)
        except Exception:
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants.append(('trocr_base', base, easyocr_variant_quality_score(base)))

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()

    for preferred_name in ('raw_gray', 'upscaled_gray'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= TROCR_MAX_VARIANTS:
            break

    return selected[:TROCR_MAX_VARIANTS]


def trocr_infer_text(processor, model, variant_img):
    if variant_img is None or getattr(variant_img, 'size', 0) == 0:
        return '', ''

    try:
        if len(variant_img.shape) == 2:
            rgb = cv2.cvtColor(variant_img, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(variant_img, cv2.COLOR_BGR2RGB)

        pil_img = Image.fromarray(rgb)
        pixel_values = processor(images=pil_img, return_tensors='pt').pixel_values

        with torch.no_grad():
            generated_ids = model.generate(pixel_values, max_new_tokens=TROCR_MAX_NEW_TOKENS)

        # In some transformers versions, batch_decode is on the tokenizer
        if hasattr(processor, 'batch_decode'):
            raw_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        elif hasattr(processor, 'tokenizer') and hasattr(processor.tokenizer, 'batch_decode'):
            raw_text = processor.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        else:
            raw_text = processor.decode(generated_ids[0], skip_special_tokens=True)

        normalized = normalize_plate_text(raw_text)
        return raw_text, normalized
    except Exception as exc:
        if 'TextEncodeInput' in str(exc):
            # This specific error suggests the processor tried to tokenize text instead of image
            return '', ''
        raise exc


def is_trocr_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))
    score_gap_top2 = float(candidate.get('score_gap_top2', 99.0))

    if variant_hits < TROCR_MIN_VARIANT_HITS and score_gap_top2 < 1.8:
        return False

    if pattern != 'Indefinido':
        if (
            score >= TROCR_PATTERN_MIN_SCORE
            and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE
            and (
                variant_hits >= TROCR_MIN_VARIANT_HITS
                or (score >= TROCR_PATTERN_MIN_SCORE + 18.0 and score_gap_top2 >= 3.0)
            )
        ):
            return True
        if score >= max(TROCR_PATTERN_MIN_SCORE + 8.0, TROCR_MIN_ACCEPT_SCORE + 10.0) and variant_hits >= TROCR_MIN_VARIANT_HITS:
            return True
        if score >= TROCR_PATTERN_MIN_SCORE + 4.0 and hits >= 2 and avg_conf >= TROCR_MIN_ACCEPT_CONF:
            return True
        return False

    if (
        score >= TROCR_MIN_ACCEPT_SCORE
        and avg_conf >= TROCR_MIN_ACCEPT_CONF
        and variant_hits >= TROCR_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_trocr_variant_rankings(variant_rankings, char_conf_map):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if vote_text:
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.4
            if pattern != 'Indefinido':
                quality_bonus += 0.30
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * TROCR_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(6.5, disagreement * 1.4)
        if pattern == 'Indefinido' and variant_hits < TROCR_MIN_VARIANT_HITS:
            conflict_penalty += 2.8

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }
    score_gap_top2 = (
        float(best.get('score', 0.0)) - float(ranked[1].get('score', 0.0))
        if len(ranked) > 1
        else 99.0
    )
    response['score_gap_top2'] = round(float(score_gap_top2), 2)
    best_for_reliability = dict(best)
    best_for_reliability['score_gap_top2'] = response['score_gap_top2']

    if not is_trocr_candidate_reliable(best_for_reliability):
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'trocr_low_reliability_abstained'
    return response


def ocr_trocr(img):
    if (
        not TROCR_ENABLED
        or TrOCRProcessor is None
        or VisionEncoderDecoderModel is None
        or torch is None
        or Image is None
    ):
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    try:
        processor, model = get_trocr_bundle()
        if processor is None or model is None:
            return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': [], 'error': str(exc)}

    variant_inputs = build_trocr_variant_inputs(img)
    if not variant_inputs:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    char_conf = defaultdict(float)
    variant_rankings = []
    raw_entries = []
    warnings = []
    for variant_name, variant_img, variant_quality in variant_inputs:
        try:
            raw_text, normalized = trocr_infer_text(processor, model, variant_img)
        except Exception as exc:
            warnings.append(f'{variant_name}:{exc}')
            continue

        if not normalized or len(normalized) < 5:
            continue

        confidence = trocr_confidence_hint(normalized)
        raw_entries.append({
            'word': normalized,
            'conf': float(confidence),
            'variant': variant_name,
            'engine': 'trocr',
            'raw_text': raw_text,
        })
        entries = [{'word': normalized, 'conf': confidence}]
        ranked = rank_ocr_candidates_from_entries(entries, variant_name, TROCR_HIT_BONUS)
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = round(float(variant_quality), 4)
        ranked['raw_text'] = raw_text
        ranked['chars'] = [(char, confidence) for char in normalized]
        variant_rankings.append(ranked)

        for char in normalized:
            if confidence > char_conf[char]:
                char_conf[char] = confidence

        if (
            not OCR_ACCURACY_FIRST
            and ranked.get('pattern', 'Indefinido') != 'Indefinido'
            and len(normalize_plate_text(ranked.get('text', ''))) >= 6
            and float(ranked.get('score', 0)) >= (TROCR_REGION_EARLY_SCORE + 6.0)
            and len(variant_rankings) >= max(2, TROCR_MIN_VARIANT_HITS)
        ):
            break

    if not variant_rankings:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': raw_entries}
        if warnings:
            payload['warning'] = ';'.join(warnings[:2])
        return payload

    merged = merge_trocr_variant_rankings(variant_rankings, char_conf)
    merged['raw_entries'] = raw_entries
    if warnings:
        warning_tail = ';'.join(warnings[:2])
        existing = str(merged.get('warning', '') or '').strip()
        merged['warning'] = f'{existing};{warning_tail}' if existing else warning_tail
    return merged


def ocr_trocr_regions(regions):
    if (
        not TROCR_ENABLED
        or TrOCRProcessor is None
        or VisionEncoderDecoderModel is None
        or torch is None
        or Image is None
    ):
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    prioritized = [item for item in regions if item[0] != 'full_image']
    if not prioritized:
        prioritized = [item for item in regions if item[0] == 'full_image'][:1]

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    warnings = []
    for region_name, region_img in prioritized:
        if region_img is None:
            continue
        result = ocr_trocr(region_img)
        if result.get('error'):
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')
        for char, conf in result.get('chars', []):
            if conf > char_conf[char]:
                char_conf[char] = conf
        if result.get('text') and result.get('score', 0) > best_score:
            best = dict(result)
            best['region'] = region_name
            best_score = result.get('score', 0)
            if (
                not OCR_ACCURACY_FIRST
                and best.get('pattern') != 'Indefinido'
                and float(best.get('score', 0)) >= TROCR_REGION_EARLY_SCORE
            ):
                break

    if best is None:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return payload

    best['chars'] = sorted(char_conf.items(), key=lambda item: -item[1])
    if warnings and not best.get('warning'):
        best['warning'] = ';'.join(warnings[:2])
    return best


@lru_cache(maxsize=1)
def get_doctr_predictor():
    if not DOCTR_ENABLED or ocr_predictor is None:
        return None
    return ocr_predictor(pretrained=True, assume_straight_pages=True)


def doctr_confidence_hint(text, raw_confidence):
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    if confidence <= 1.0:
        confidence *= 100.0

    confidence = max(float(DOCTR_BASE_CONFIDENCE), confidence)
    if len(text) == 7:
        confidence += 8.0
    else:
        confidence -= abs(7 - len(text)) * 3.0
    if detect_plate_pattern(text) != 'Indefinido':
        confidence += 13.0
    digits = sum(char.isdigit() for char in text)
    letters = sum(char.isalpha() for char in text)
    if digits >= 2 and letters >= 3:
        confidence += 4.0
    return max(6.0, min(98.0, confidence))


def build_doctr_variant_inputs(img):
    variants = []

    if DOCTR_DYNAMIC_VARIANTS:
        for variant_name, variant_img in build_ocr_variants(img):
            quality = easyocr_variant_quality_score(variant_img)
            variants.append((variant_name, variant_img, quality))
    else:
        try:
            base = preprocess_plate(img)
        except Exception:
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants.append(('doctr_base', base, easyocr_variant_quality_score(base)))

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()

    for preferred_name in ('raw_gray', 'upscaled_gray'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= DOCTR_MAX_VARIANTS:
            break

    return selected[:DOCTR_MAX_VARIANTS]


def doctr_variant_to_rgb(variant_img):
    if variant_img is None or getattr(variant_img, 'size', 0) == 0:
        return None
    if len(variant_img.shape) == 2:
        return cv2.cvtColor(variant_img, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(variant_img, cv2.COLOR_BGR2RGB)


def doctr_extract_entries_from_result(result):
    entries = []
    chars = []
    pages = getattr(result, 'pages', []) or []
    if pages:
        for block in getattr(pages[0], 'blocks', []):
            for line in getattr(block, 'lines', []):
                for word in getattr(line, 'words', []):
                    value = normalize_plate_text(getattr(word, 'value', ''))
                    if len(value) < 2:
                        continue
                    confidence = doctr_confidence_hint(value, getattr(word, 'confidence', 0))
                    entries.append({'word': value, 'conf': confidence})
                    chars.extend([(char, confidence) for char in value])
    return entries, chars


def is_doctr_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))
    score_gap_top2 = float(candidate.get('score_gap_top2', 99.0))

    if variant_hits < DOCTR_MIN_VARIANT_HITS and score_gap_top2 < 1.8:
        return False

    if pattern != 'Indefinido':
        if (
            score >= DOCTR_PATTERN_MIN_SCORE
            and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE
            and (
                variant_hits >= DOCTR_MIN_VARIANT_HITS
                or (score >= DOCTR_PATTERN_MIN_SCORE + 16.0 and score_gap_top2 >= 2.8)
            )
        ):
            return True
        if score >= max(DOCTR_PATTERN_MIN_SCORE + 8.0, DOCTR_MIN_ACCEPT_SCORE + 10.0) and variant_hits >= DOCTR_MIN_VARIANT_HITS:
            return True
        if score >= DOCTR_PATTERN_MIN_SCORE + 4.0 and hits >= 2 and avg_conf >= DOCTR_MIN_ACCEPT_CONF:
            return True
        return False

    if (
        score >= DOCTR_MIN_ACCEPT_SCORE
        and avg_conf >= DOCTR_MIN_ACCEPT_CONF
        and variant_hits >= DOCTR_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_doctr_variant_rankings(variant_rankings, char_conf_map):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if vote_text:
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.3
            if pattern != 'Indefinido':
                quality_bonus += 0.28
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * DOCTR_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(6.2, disagreement * 1.35)
        if pattern == 'Indefinido' and variant_hits < DOCTR_MIN_VARIANT_HITS:
            conflict_penalty += 2.6

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }
    score_gap_top2 = (
        float(best.get('score', 0.0)) - float(ranked[1].get('score', 0.0))
        if len(ranked) > 1
        else 99.0
    )
    response['score_gap_top2'] = round(float(score_gap_top2), 2)
    best_for_reliability = dict(best)
    best_for_reliability['score_gap_top2'] = response['score_gap_top2']

    if not is_doctr_candidate_reliable(best_for_reliability):
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'doctr_low_reliability_abstained'
    return response


def ocr_doctr(img):
    if not DOCTR_ENABLED or ocr_predictor is None:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    try:
        predictor = get_doctr_predictor()
        if predictor is None:
            return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': [], 'error': str(exc)}

    variant_inputs = build_doctr_variant_inputs(img)
    if not variant_inputs:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    char_conf = defaultdict(float)
    variant_rankings = []
    raw_entries = []
    warnings = []
    for variant_name, variant_img, variant_quality in variant_inputs:
        try:
            rgb = doctr_variant_to_rgb(variant_img)
            if rgb is None:
                continue
            result = predictor([rgb])
            entries, chars = doctr_extract_entries_from_result(result)

            if not entries:
                rendered = []
                try:
                    rendered = result.render()
                except Exception:
                    rendered = []
                fallback_text = normalize_plate_text(' '.join(rendered)) if rendered else ''
                if len(fallback_text) >= 5:
                    confidence = doctr_confidence_hint(fallback_text, 0)
                    entries.append({'word': fallback_text, 'conf': confidence})
                    chars.extend([(char, confidence) for char in fallback_text])
        except Exception as exc:
            warnings.append(f'{variant_name}:{exc}')
            continue

        if not entries:
            continue
        for entry in entries:
            raw_entries.append({
                'word': entry.get('word', ''),
                'conf': float(entry.get('conf', 0.0)),
                'variant': variant_name,
                'engine': 'doctr',
            })
        for char, conf in chars:
            if conf > char_conf[char]:
                char_conf[char] = conf

        ranked = rank_ocr_candidates_from_entries(entries, variant_name, DOCTR_HIT_BONUS)
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = round(float(variant_quality), 4)
        ranked['chars'] = chars
        variant_rankings.append(ranked)

        if (
            not OCR_ACCURACY_FIRST
            and ranked.get('pattern', 'Indefinido') != 'Indefinido'
            and len(normalize_plate_text(ranked.get('text', ''))) >= 6
            and float(ranked.get('score', 0)) >= (DOCTR_REGION_EARLY_SCORE + 6.0)
            and len(variant_rankings) >= max(2, DOCTR_MIN_VARIANT_HITS)
        ):
            break

    if not variant_rankings:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': raw_entries}
        if warnings:
            payload['warning'] = ';'.join(warnings[:2])
        return payload

    merged = merge_doctr_variant_rankings(variant_rankings, char_conf)
    merged['raw_entries'] = raw_entries
    if warnings:
        warning_tail = ';'.join(warnings[:2])
        existing = str(merged.get('warning', '') or '').strip()
        merged['warning'] = f'{existing};{warning_tail}' if existing else warning_tail
    return merged


def ocr_doctr_regions(regions):
    if not DOCTR_ENABLED or ocr_predictor is None:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    prioritized = [item for item in regions if item[0] != 'full_image']
    if not prioritized:
        prioritized = [item for item in regions if item[0] == 'full_image'][:1]

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    warnings = []
    for region_name, region_img in prioritized:
        if region_img is None:
            continue
        result = ocr_doctr(region_img)
        if result.get('error'):
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')
        for char, conf in result.get('chars', []):
            if conf > char_conf[char]:
                char_conf[char] = conf
        if result.get('text') and result.get('score', 0) > best_score:
            best = dict(result)
            best['region'] = region_name
            best_score = result.get('score', 0)
            if (
                not OCR_ACCURACY_FIRST
                and best.get('pattern') != 'Indefinido'
                and float(best.get('score', 0)) >= DOCTR_REGION_EARLY_SCORE
            ):
                break

    if best is None:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return payload

    best['chars'] = sorted(char_conf.items(), key=lambda item: -item[1])
    if warnings and not best.get('warning'):
        best['warning'] = ';'.join(warnings[:2])
    return best


def parse_paddleocr_entries(raw_result):
    entries = []
    chars = []

    def walk(node):
        if node is None:
            return
        if isinstance(node, tuple):
            node = list(node)
        if isinstance(node, list):
            if len(node) == 2 and isinstance(node[1], (list, tuple)):
                payload = node[1]
                if len(payload) >= 2 and isinstance(payload[0], str):
                    word = normalize_plate_text(payload[0])
                    conf = parse_confidence(payload[1])
                    if conf <= 1.0:
                        conf *= 100.0
                    if word and conf > 0:
                        entries.append({'word': word, 'conf': float(conf)})
                        chars.extend([(char, float(conf)) for char in word])
                    return
            for item in node:
                walk(item)

    walk(raw_result)
    return entries, chars


def build_paddleocr_variant_inputs(img):
    variants = []

    if PADDLEOCR_DYNAMIC_VARIANTS:
        for variant_name, variant_img in build_ocr_variants(img):
            quality = easyocr_variant_quality_score(variant_img)
            variants.append((variant_name, variant_img, quality))
    else:
        try:
            base = preprocess_plate(img)
        except Exception:
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variants.append(('paddle_base', base, easyocr_variant_quality_score(base)))

    if not variants:
        return []

    variants.sort(key=lambda item: float(item[2]), reverse=True)
    selected = []
    selected_names = set()

    for preferred_name in ('raw_gray', 'upscaled_gray'):
        for variant_name, variant_img, quality in variants:
            if variant_name != preferred_name:
                continue
            if variant_name in selected_names:
                continue
            selected.append((variant_name, variant_img, quality))
            selected_names.add(variant_name)
            break

    for variant_name, variant_img, quality in variants:
        if variant_name in selected_names:
            continue
        selected.append((variant_name, variant_img, quality))
        selected_names.add(variant_name)
        if len(selected) >= PADDLEOCR_MAX_VARIANTS:
            break

    return selected[:PADDLEOCR_MAX_VARIANTS]


def is_paddleocr_candidate_reliable(candidate):
    if not isinstance(candidate, dict):
        return False

    text = normalize_plate_text(candidate.get('text', ''))
    if len(text) != 7:
        return False

    score = float(candidate.get('score', 0))
    avg_conf = float(candidate.get('avg_conf', 0))
    pattern = str(candidate.get('pattern', 'Indefinido'))
    variant_hits = int(candidate.get('variant_hits', 1))
    hits = int(candidate.get('hits', 1))

    if pattern != 'Indefinido':
        if score >= PADDLEOCR_PATTERN_MIN_SCORE and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE:
            return True
        if score >= max(PADDLEOCR_PATTERN_MIN_SCORE + 8.0, PADDLEOCR_MIN_ACCEPT_SCORE + 12.0) and variant_hits >= PADDLEOCR_MIN_VARIANT_HITS:
            return True
        if score >= PADDLEOCR_PATTERN_MIN_SCORE + 4.0 and hits >= 2 and avg_conf >= PADDLEOCR_MIN_ACCEPT_CONF:
            return True
        return False

    if (
        score >= PADDLEOCR_MIN_ACCEPT_SCORE
        and avg_conf >= PADDLEOCR_MIN_ACCEPT_CONF
        and variant_hits >= PADDLEOCR_MIN_VARIANT_HITS
        and hits >= 2
    ):
        return True
    return False


def merge_paddleocr_variant_rankings(variant_rankings, char_conf_map):
    if not variant_rankings:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    candidates_by_text = {}
    variant_votes = []
    total_variants = len(variant_rankings)

    for ranking in variant_rankings:
        variant_name = str(ranking.get('variant_name', 'variant'))
        variant_quality = float(ranking.get('variant_quality', 0.5))
        vote_text = normalize_plate_text(ranking.get('text', ''))
        if vote_text:
            variant_votes.append(vote_text)

        candidate_list = ranking.get('candidates', [])
        if not isinstance(candidate_list, list) or not candidate_list:
            candidate_list = [ranking]

        for candidate in candidate_list[:MAX_TOP_CANDIDATES]:
            if not isinstance(candidate, dict):
                continue
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            raw_score = float(candidate.get('score', 0.0))
            avg_conf = float(candidate.get('avg_conf', 0.0))
            pattern = str(candidate.get('pattern', detect_plate_pattern(text)))
            hits = max(1, int(parse_int(candidate.get('hits', 1), 1)))
            quality_bonus = (variant_quality - 0.5) * 2.7
            if pattern != 'Indefinido':
                quality_bonus += 0.33
            adjusted_score = raw_score + quality_bonus

            item = candidates_by_text.setdefault(text, {
                'text': text,
                'best_adjusted_score': -1e9,
                'best_raw_score': 0.0,
                'sum_conf': 0.0,
                'conf_count': 0,
                'hits': 1,
                'pattern': 'Indefinido',
                'variants': set(),
                'origins': set(),
            })
            item['best_adjusted_score'] = max(float(item['best_adjusted_score']), float(adjusted_score))
            item['best_raw_score'] = max(float(item['best_raw_score']), float(raw_score))
            item['sum_conf'] += float(avg_conf)
            item['conf_count'] += 1
            item['hits'] = max(int(item['hits']), hits)
            item['variants'].add(variant_name)
            item['origins'].add(str(candidate.get('origin', 'variant')))
            if pattern != 'Indefinido':
                item['pattern'] = pattern

    if not candidates_by_text:
        return {'text': '', 'avg_conf': 0, 'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]), 'score': 0, 'pattern': 'Indefinido', 'candidates': []}

    vote_counter = Counter(variant_votes)
    top_vote = max(vote_counter.values()) if vote_counter else 0
    ranked = []
    for item in candidates_by_text.values():
        text = item['text']
        variant_hits = len(item['variants'])
        avg_conf = float(item['sum_conf']) / max(1, int(item['conf_count']))
        pattern = item['pattern'] if item['pattern'] != 'Indefinido' else detect_plate_pattern(text)
        consistency_bonus = max(0, variant_hits - 1) * PADDLEOCR_VARIANT_CONSISTENCY_BONUS

        votes_for_text = int(vote_counter.get(text, 0))
        disagreement = max(0, top_vote - votes_for_text)
        conflict_penalty = min(7.0, disagreement * 1.5)
        if pattern == 'Indefinido' and variant_hits < PADDLEOCR_MIN_VARIANT_HITS:
            conflict_penalty += 3.0

        final_score = float(item['best_adjusted_score']) + float(consistency_bonus) - float(conflict_penalty)
        final_score = round(float(final_score), 2)
        ranked.append({
            'text': text,
            'avg_conf': round(avg_conf, 2),
            'score': final_score,
            'pattern': pattern,
            'hits': int(item['hits']),
            'variant_hits': int(variant_hits),
            'variant_ratio': round(variant_hits / max(1, total_variants) * 100.0, 1),
            'consistency_bonus': round(float(consistency_bonus), 2),
            'conflict_penalty': round(float(conflict_penalty), 2),
            'variants': sorted(item['variants']),
            'origins': sorted(item['origins']),
        })

    ranked.sort(
        key=lambda item: (
            item.get('variant_hits', 0),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )

    best = ranked[0]
    response = {
        'text': best['text'],
        'avg_conf': float(best.get('avg_conf', 0)),
        'chars': sorted(char_conf_map.items(), key=lambda item: -item[1]),
        'score': float(best.get('score', 0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'hits': int(best.get('hits', 1)),
        'variant_hits': int(best.get('variant_hits', 1)),
        'variant_ratio': float(best.get('variant_ratio', 0)),
        'candidates': ranked[:MAX_TOP_CANDIDATES],
    }
    score_gap_top2 = (
        float(best.get('score', 0.0)) - float(ranked[1].get('score', 0.0))
        if len(ranked) > 1
        else 99.0
    )
    response['score_gap_top2'] = round(float(score_gap_top2), 2)
    best_for_reliability = dict(best)
    best_for_reliability['score_gap_top2'] = response['score_gap_top2']

    if not is_paddleocr_candidate_reliable(best_for_reliability):
        abstained_candidates = response.get('candidates', [])[:MAX_TOP_CANDIDATES]
        response['text'] = ''
        response['avg_conf'] = 0.0
        response['score'] = 0.0
        response['pattern'] = 'Indefinido'
        response['candidates'] = []
        response['abstained_candidates'] = abstained_candidates
        response['warning'] = 'paddleocr_low_reliability_abstained'
    return response


def ocr_paddleocr(img):
    if PaddleOCR is None or not PADDLEOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    try:
        reader = get_paddleocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}
    except Exception as exc:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': [], 'error': str(exc)}

    variant_inputs = build_paddleocr_variant_inputs(img)
    if not variant_inputs:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    char_conf = defaultdict(float)
    variant_rankings = []
    raw_entries = []
    warnings = []
    for variant_name, variant_img, variant_quality in variant_inputs:
        if variant_img is None or getattr(variant_img, 'size', 0) == 0:
            continue
        try:
            raw_result = reader.ocr(variant_img, use_textline_orientation=PADDLEOCR_USE_ANGLE_CLS)
        except Exception as exc:
            warnings.append(f'{variant_name}:{exc}')
            continue
        entries, chars = parse_paddleocr_entries(raw_result)
        if not entries:
            continue
        for entry in entries:
            raw_entries.append({
                'word': entry.get('word', ''),
                'conf': float(entry.get('conf', 0.0)),
                'variant': variant_name,
                'engine': 'paddleocr',
            })
        for char, conf in chars:
            if conf > char_conf[char]:
                char_conf[char] = conf
        ranked = rank_ocr_candidates_from_entries(entries, variant_name, PADDLEOCR_HIT_BONUS )
        ranked['variant_name'] = variant_name
        ranked['variant_quality'] = variant_quality
        variant_rankings.append(ranked)

    merged = merge_paddleocr_variant_rankings(variant_rankings, char_conf)
    if not merged:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': raw_entries}
    merged['raw_entries'] = raw_entries
    if warnings and not merged.get('warning'):
        merged['warning'] = ';'.join(warnings[:2])
    return merged


def ocr_paddleocr_regions(regions):
    if PaddleOCR is None or not PADDLEOCR_ENABLED:
        return {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido', 'raw_entries': []}

    prioritized = [item for item in regions if item[0] != 'full_image']
    if not prioritized:
        prioritized = [item for item in regions if item[0] == 'full_image'][:1]

    best = None
    best_score = -1e9
    char_conf = defaultdict(float)
    warnings = []
    for region_name, region_img in prioritized:
        if region_img is None:
            continue
        result = ocr_paddleocr(region_img)
        if result.get('error'):
            continue
        if result.get('warning'):
            warnings.append(f'{region_name}:{result["warning"]}')
        for char, conf in result.get('chars', []):
            if conf > char_conf[char]:
                char_conf[char] = conf
        if result.get('text') and result.get('score', 0) > best_score:
            best = dict(result)
            best['region'] = region_name
            best_score = result.get('score', 0)
            if (
                not OCR_ACCURACY_FIRST
                and best.get('pattern') != 'Indefinido'
                and float(best.get('score', 0)) >= PADDLEOCR_REGION_EARLY_SCORE
            ):
                break

    if best is None:
        payload = {'text': '', 'avg_conf': 0, 'chars': [], 'score': 0, 'pattern': 'Indefinido'}
        if warnings:
            payload['warning'] = ';'.join(warnings[:3])
        return payload

    best['chars'] = sorted(char_conf.items(), key=lambda item: -item[1])
    if warnings and not best.get('warning'):
        best['warning'] = ';'.join(warnings[:2])
    return best


def quick_paddleocr_probe(region_img):
    if PaddleOCR is None or not PADDLEOCR_ENABLED:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    if region_img is None or getattr(region_img, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    try:
        reader = get_paddleocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    except Exception:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    probe_input = resize_for_quick_probe(region_img, max_side=PDF_QUICK_ENGINE_MAX_SIDE)
    if probe_input is None or getattr(probe_input, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    variant_inputs = []
    try:
        pre = preprocess_plate(probe_input)
        variant_inputs.append(('paddle_quick_pre', pre))
    except Exception:
        pass
    try:
        gray = cv2.cvtColor(probe_input, cv2.COLOR_BGR2GRAY)
        variant_inputs.append(('paddle_quick_gray', gray))
    except Exception:
        pass
    if not variant_inputs:
        variant_inputs = [('paddle_quick_raw', probe_input)]

    best = None
    for variant_name, variant_img in variant_inputs[:2]:
        try:
            raw_result = reader.ocr(variant_img, use_textline_orientation=PADDLEOCR_USE_ANGLE_CLS)
        except Exception:
            continue
        entries, chars = parse_paddleocr_entries(raw_result)
        if not entries:
            continue
        ranked = rank_ocr_candidates_from_entries(entries, variant_name, PADDLEOCR_HIT_BONUS )
        ranked['chars'] = chars
        if best is None or float(ranked.get('score', 0.0)) > float(best.get('score', 0.0)):
            best = ranked

    if not best:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    return {
        'text': normalize_plate_text(best.get('text', '')),
        'avg_conf': float(best.get('avg_conf', 0.0)),
        'score': float(best.get('score', 0.0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'candidates': list(best.get('candidates', []))[:4],
    }


def _normalize_open_text(value):
    text = str(value or '').strip()
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'[^A-Za-z0-9 ]+', ' ', text.upper())
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _name_match_score(expected, candidate):
    expected_norm = _normalize_open_text(expected)
    candidate_norm = _normalize_open_text(candidate)
    if not expected_norm or not candidate_norm:
        return 0.0
    if expected_norm == candidate_norm:
        return 200.0

    score = 0.0
    if expected_norm in candidate_norm:
        score += 90.0
    if candidate_norm in expected_norm:
        score += 35.0

    expected_tokens = set(expected_norm.split(' '))
    candidate_tokens = set(candidate_norm.split(' '))
    if expected_tokens and candidate_tokens:
        overlap = expected_tokens.intersection(candidate_tokens)
        score += len(overlap) * 28.0
        score += (len(overlap) / max(1, len(expected_tokens))) * 24.0

    score += SequenceMatcher(None, expected_norm, candidate_norm).ratio() * 80.0
    return score


def _http_verify_setting():
    if HTTP_INSECURE_SKIP_VERIFY:
        return False
    if HTTP_CA_BUNDLE and os.path.isfile(HTTP_CA_BUNDLE):
        return HTTP_CA_BUNDLE
    return True


def _fipe_request_json(path, params=None):
    if not VISUAL_FIPE_BASE_URL:
        return None

    headers = {'Accept': 'application/json'}
    if VISUAL_FIPE_TOKEN:
        headers['X-Subscription-Token'] = VISUAL_FIPE_TOKEN

    url = f'{VISUAL_FIPE_BASE_URL}/{path.lstrip("/")}'
    try:
        response = requests.get(
            url,
            params=params or {},
            headers=headers,
            timeout=VISUAL_FIPE_TIMEOUT,
            verify=_http_verify_setting(),
        )
    except Exception:
        return None

    if response.status_code < 200 or response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload


def _extract_year_from_token(raw):
    text = str(raw or '')
    match = re.search(r'\b(19|20)\d{2}\b', text)
    if not match:
        return 0
    try:
        value = int(match.group(0))
    except ValueError:
        return 0
    if 1900 <= value <= 2099:
        return value
    return 0


@lru_cache(maxsize=64)
def _fetch_fipe_year_range(brand_name, model_name, vehicle_type='cars'):
    if not VISUAL_FIPE_ENABLE or not brand_name or not model_name:
        return {}

    references = _fipe_request_json('/references')
    if not isinstance(references, list) or not references:
        return {}

    reference_code = str((references[0] or {}).get('code', '')).strip()
    reference_month = str((references[0] or {}).get('month', '')).strip()
    if not reference_code:
        return {}

    brands = _fipe_request_json(f'/{vehicle_type}/brands', params={'reference': reference_code})
    if not isinstance(brands, list) or not brands:
        return {}

    best_brand = None
    best_brand_score = 0.0
    for item in brands:
        if not isinstance(item, dict):
            continue
        candidate_name = str(item.get('name', '')).strip()
        score = _name_match_score(brand_name, candidate_name)
        if score > best_brand_score:
            best_brand_score = score
            best_brand = item
    if not best_brand or best_brand_score < 36:
        return {}

    brand_code = str(best_brand.get('code', '')).strip()
    if not brand_code:
        return {}

    models = _fipe_request_json(
        f'/{vehicle_type}/brands/{brand_code}/models',
        params={'reference': reference_code},
    )
    if not isinstance(models, list) or not models:
        return {}

    best_model = None
    best_model_score = 0.0
    for item in models:
        if not isinstance(item, dict):
            continue
        candidate_name = str(item.get('name', '')).strip()
        score = _name_match_score(model_name, candidate_name)
        if score > best_model_score:
            best_model_score = score
            best_model = item
    if not best_model or best_model_score < 34:
        return {}

    model_code = str(best_model.get('code', '')).strip()
    if not model_code:
        return {}

    years = _fipe_request_json(
        f'/{vehicle_type}/brands/{brand_code}/models/{model_code}/years',
        params={'reference': reference_code},
    )
    if not isinstance(years, list) or not years:
        return {}

    year_values = []
    for item in years:
        if not isinstance(item, dict):
            continue
        year_code = str(item.get('code', '')).strip()
        year_name = str(item.get('name', '')).strip()
        year = _extract_year_from_token(year_code) or _extract_year_from_token(year_name)
        if year:
            year_values.append(year)

    if not year_values:
        return {}

    return {
        'faixa_ano_modelo': f'{min(year_values)}-{max(year_values)}',
        'fipe_modelo_match': str(best_model.get('name', '')).strip(),
        'fipe_referencia': reference_month or '',
    }


def _resize_for_visual_profile(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return img
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= VISUAL_PROFILE_MAX_SIDE:
        return img
    scale = VISUAL_PROFILE_MAX_SIDE / float(longest)
    target_w = max(32, int(round(width * scale)))
    target_h = max(32, int(round(height * scale)))
    return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)


def _classify_hsv_color(hsv_pixels):
    if hsv_pixels.size == 0:
        return 'indefinida', 0.0

    hsv_mean = np.mean(hsv_pixels, axis=0)
    hue = float(hsv_mean[0])
    sat = float(hsv_mean[1])
    val = float(hsv_mean[2])

    if sat < 28:
        if val >= 215:
            return 'branca', 68.0
        if val >= 165:
            return 'prata', 62.0
        if val >= 96:
            return 'cinza', 58.0
        return 'preta', 63.0

    if hue < 10 or hue >= 170:
        return 'vermelha', min(96.0, 55.0 + (sat * 0.14))
    if hue < 22:
        return 'laranja', min(94.0, 50.0 + (sat * 0.12))
    if hue < 35:
        return 'amarela', min(94.0, 50.0 + (sat * 0.12))
    if hue < 86:
        return 'verde', min(92.0, 50.0 + (sat * 0.10))
    if hue < 132:
        return 'azul', min(92.0, 50.0 + (sat * 0.10))
    return 'vinho/roxa', min(88.0, 46.0 + (sat * 0.10))


def _hsv_bucket_name(hue, sat, val):
    if sat < 28:
        if val >= 215:
            return 'branca'
        if val >= 165:
            return 'prata'
        if val >= 96:
            return 'cinza'
        return 'preta'

    if hue < 10 or hue >= 170:
        return 'vermelha'
    if hue < 22:
        return 'laranja'
    if hue < 35:
        return 'amarela'
    if hue < 86:
        return 'verde'
    if hue < 132:
        return 'azul'
    return 'vinho/roxa'


def analyze_color_model(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {
            'bgr': [0, 0, 0],
            'rgb': [0, 0, 0],
            'hex': '#000000',
            'color_name': 'indefinida',
            'color_confidence': 0.0,
        }

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    foreground_mask = ((sat > 34) & (val > 32) & (val < 246))
    if np.mean(foreground_mask) < 0.06:
        foreground_mask = ((val > 20) & (val < 246))
    selected = hsv[foreground_mask]
    if selected.size == 0:
        selected = hsv.reshape(-1, 3)

    color_name, color_conf = _classify_hsv_color(selected)
    sample = selected
    if len(selected) > 45000:
        sample_idx = np.linspace(0, len(selected) - 1, 45000).astype(np.int32)
        sample = selected[sample_idx]

    buckets = defaultdict(int)
    for hue, sat, val in sample:
        buckets[_hsv_bucket_name(float(hue), float(sat), float(val))] += 1

    top_colors = []
    total_bucket = float(sum(buckets.values()))
    if total_bucket > 0:
        ordered = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
        for name, count in ordered[:3]:
            ratio = (float(count) / total_bucket) * 100.0
            top_colors.append({'name': name, 'ratio': round(ratio, 2)})

    if top_colors:
        dominant_name = str(top_colors[0].get('name', color_name))
        dominant_ratio = float(top_colors[0].get('ratio', 0))
        if dominant_ratio >= 35.0 or color_name in ('indefinida', 'cinza'):
            color_name = dominant_name
            color_conf = max(float(color_conf), min(97.0, 42.0 + (dominant_ratio * 0.8)))

    avg_color = cv2.mean(img)[:3]
    bgr = [int(round(float(channel))) for channel in avg_color]
    rgb = [bgr[2], bgr[1], bgr[0]]
    return {
        'bgr': bgr,
        'rgb': rgb,
        'hex': '#{:02X}{:02X}{:02X}'.format(*rgb),
        'color_name': color_name,
        'color_confidence': round(float(color_conf), 1),
        'top_colors': top_colors,
    }


def _detect_emblem_signature(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {'detected': False}

    height, width = img.shape[:2]
    x1 = max(0, int(width * 0.26))
    x2 = min(width, int(width * 0.74))
    y1 = max(0, int(height * 0.14))
    y2 = min(height, int(height * 0.44))
    if x2 <= x1 or y2 <= y1:
        return {'detected': False}

    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return {'detected': False}

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 65, 165)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {'detected': False}

    roi_h, roi_w = roi.shape[:2]
    roi_area = float(max(1, roi_h * roi_w))
    center = (roi_w / 2.0, roi_h / 2.0)

    best = None
    best_score = 0.0
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= roi_area * 0.0004 or area >= roi_area * 0.11:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        circularity = float((4.0 * np.pi * area) / max(1e-6, perimeter * perimeter))
        x, y, box_w, box_h = cv2.boundingRect(contour)
        if box_w < 8 or box_h < 8:
            continue
        aspect = float(box_w) / max(1.0, float(box_h))
        c_x = x + (box_w / 2.0)
        c_y = y + (box_h / 2.0)
        center_dist = (
            abs(c_x - center[0]) / max(1.0, center[0])
            + abs(c_y - center[1]) / max(1.0, center[1])
        )
        center_bonus = max(0.0, 1.0 - center_dist)
        area_ratio = area / roi_area
        size_bonus = min(1.0, area_ratio / 0.02)
        score = (max(0.0, circularity) * 58.0) + (center_bonus * 30.0) + (size_bonus * 12.0)
        if score > best_score:
            best_score = score
            best = (x, y, box_w, box_h, circularity, aspect)

    if best is None or best_score < 42.0:
        return {'detected': False}

    x, y, box_w, box_h, circularity, aspect = best
    patch = roi[y:y + box_h, x:x + box_w]
    patch_color = analyze_color_model(patch)
    if circularity >= 0.75 and 0.78 <= aspect <= 1.22:
        shape = 'circular'
    elif circularity >= 0.55 and 0.55 <= aspect <= 1.75:
        shape = 'oval'
    elif aspect >= 1.75:
        shape = 'barra'
    else:
        shape = 'indefinido'

    return {
        'detected': True,
        'shape': shape,
        'color_hint': patch_color.get('color_name', 'indefinida'),
        'confidence': round(float(min(99.0, max(0.0, best_score))), 1),
        'bbox_norm': {
            'x': round((x + x1) / max(1.0, width), 4),
            'y': round((y + y1) / max(1.0, height), 4),
            'w': round(box_w / max(1.0, width), 4),
            'h': round(box_h / max(1.0, height), 4),
        },
    }


def _extract_vehicle_focus_region(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return img

    height, width = img.shape[:2]
    base_x1 = int(width * 0.14)
    base_x2 = int(width * 0.86)
    base_y1 = int(height * 0.24)
    base_y2 = int(height * 0.90)
    if base_x2 <= base_x1 or base_y2 <= base_y1:
        return img

    base_roi = img[base_y1:base_y2, base_x1:base_x2]
    if base_roi.size == 0:
        return img

    gray = cv2.cvtColor(base_roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 70, 180)
    points = cv2.findNonZero(edges)
    if points is None:
        return base_roi

    x, y, box_w, box_h = cv2.boundingRect(points)
    roi_area = float(base_roi.shape[0] * base_roi.shape[1])
    if roi_area <= 0:
        return base_roi
    if (box_w * box_h) / roi_area < 0.08:
        return base_roi

    pad_x = max(8, int(box_w * 0.06))
    pad_y = max(8, int(box_h * 0.06))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(base_roi.shape[1], x + box_w + pad_x)
    y2 = min(base_roi.shape[0], y + box_h + pad_y)
    focus = base_roi[y1:y2, x1:x2]
    return focus if focus.size else base_roi


def _slugify_for_url(value):
    slug = _normalize_open_text(value).lower().replace(' ', '-')
    slug = re.sub(r'[^a-z0-9\-]+', '', slug)
    slug = re.sub(r'\-+', '-', slug).strip('-')
    return slug or 'veiculo'


def _detect_rear_taillight_signature(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {'detected': False}

    height, width = img.shape[:2]
    if height < 90 or width < 120:
        return {'detected': False}

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask_low = cv2.inRange(hsv, (0, 65, 40), (12, 255, 255))
    mask_high = cv2.inRange(hsv, (168, 65, 40), (180, 255, 255))
    y1 = int(height * 0.16)
    y2 = int(height * 0.96)
    if y2 <= y1:
        return {'detected': False}

    roi = img[y1:y2, :]
    if roi.size == 0:
        return {'detected': False}

    red_mask = cv2.bitwise_or(mask_low, mask_high)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    red_mask = red_mask[y1:y2, :]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    edge_mask = cv2.Canny(clahe, 45, 150)
    edge_mask = cv2.morphologyEx(edge_mask, cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8), iterations=2)
    edge_mask = cv2.dilate(edge_mask, np.ones((3, 3), np.uint8), iterations=1)

    roi_h, roi_w = roi.shape[:2]
    roi_area = float(max(1, roi_h * roi_w))

    def score_rear_layout_hint(base_img):
        if base_img is None or getattr(base_img, 'size', 0) == 0:
            return 0.0, 0

        layout_y1 = int(height * 0.16)
        layout_y2 = int(height * 0.64)
        layout_x1 = int(width * 0.38)
        layout_x2 = int(width * 0.98)
        layout_roi = base_img[layout_y1:layout_y2, layout_x1:layout_x2]
        if layout_roi is None or getattr(layout_roi, 'size', 0) == 0:
            return 0.0, 0

        layout_gray = cv2.cvtColor(layout_roi, cv2.COLOR_BGR2GRAY)
        layout_gray = cv2.GaussianBlur(layout_gray, (3, 3), 0)
        layout_gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(layout_gray)
        layout_edges = cv2.Canny(layout_gray, 42, 138)
        layout_edges = cv2.morphologyEx(layout_edges, cv2.MORPH_CLOSE, np.ones((3, 7), np.uint8), iterations=1)
        lines = cv2.HoughLinesP(
            layout_edges,
            1,
            np.pi / 180.0,
            threshold=max(26, int(layout_roi.shape[1] * 0.22)),
            minLineLength=max(24, int(layout_roi.shape[1] * 0.20)),
            maxLineGap=12,
        )
        if lines is None:
            return 0.0, 0

        strongest = 0.0
        line_count = 0
        for line in lines[:36]:
            x1, y1, x2, y2 = line[0]
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            length = float(math.hypot(dx, dy))
            strongest = max(strongest, length)
            angle = abs(float(math.degrees(math.atan2(dy, dx))))
            if angle > 16.0 or length < float(layout_roi.shape[1]) * 0.22:
                continue
            y_center = ((float(y1) + float(y2)) / 2.0) / max(1.0, float(layout_roi.shape[0]))
            if y_center < 0.10 or y_center > 0.86:
                continue
            line_count += 1

        if line_count == 0:
            return 0.0, 0

        strongest_ratio = strongest / max(1.0, float(layout_roi.shape[1]))
        score = (line_count * 8.0) + min(28.0, strongest_ratio * 30.0)
        if line_count >= 2:
            score += 4.0
        if strongest_ratio >= 0.70:
            score += 6.0
        return float(min(52.0, score)), int(line_count)

    layout_score, layout_lines = score_rear_layout_hint(img)

    def collect_candidates(mask, source_name, min_ratio=0.0007):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < roi_area * min_ratio:
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 7 or box_h < 10:
                continue
            aspect = float(box_h) / max(1.0, float(box_w))
            if aspect < 0.95:
                continue
            fill_ratio = area / max(1.0, float(box_w * box_h))
            if fill_ratio < 0.08:
                continue
            cx = (float(x) + (float(box_w) / 2.0)) / max(1.0, float(roi_w))
            cy = (float(y) + (float(box_h) / 2.0)) / max(1.0, float(roi_h))
            if cy < 0.15 or cy > 0.93:
                continue
            if cx < 0.05 or cx > 0.95:
                continue
            score = (
                min(26.0, area / max(1.0, roi_area) * 300.0)
                + (aspect * 20.0)
                + (fill_ratio * 20.0)
            )
            if source_name == 'red':
                score += 8.0
            found.append({
                'x': x,
                'y': y + y1,
                'w': box_w,
                'h': box_h,
                'aspect': round(aspect, 3),
                'fill_ratio': round(fill_ratio, 3),
                'score': round(score, 2),
                'source': source_name,
            })
        return found

    candidates = collect_candidates(red_mask, 'red', min_ratio=0.0006)
    candidates.extend(collect_candidates(edge_mask, 'edge', min_ratio=0.0010))
    if not candidates:
        if layout_score >= 36.0:
            confidence = min(86.0, layout_score + 6.0)
            return {
                'detected': True,
                'confidence': round(float(confidence), 1),
                'vertical_pair': False,
                'components_detected': 0,
                'pair_score': round(float(layout_score), 1),
                'symmetry': 0.0,
                'left': None,
                'right': None,
                'source': 'rear_layout_hint',
                'layout_hint': True,
                'layout_hint_lines': int(layout_lines),
            }
        return {'detected': False}

    candidates.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)
    candidates = candidates[:14]

    best_pair = None
    best_pair_score = -1.0
    for idx, first in enumerate(candidates):
        cx1 = float(first['x']) + (float(first['w']) / 2.0)
        cy1 = float(first['y']) + (float(first['h']) / 2.0)
        for second in candidates[idx + 1:]:
            cx2 = float(second['x']) + (float(second['w']) / 2.0)
            cy2 = float(second['y']) + (float(second['h']) / 2.0)

            separation = abs(cx1 - cx2) / max(1.0, float(width))
            if separation < 0.06 or separation > 0.72:
                continue

            h_sim = 1.0 - (abs(float(first['h']) - float(second['h'])) / max(1.0, float(max(first['h'], second['h']))))
            y_sim = 1.0 - (abs(cy1 - cy2) / max(1.0, float(max(first['h'], second['h']))))
            h_sim = max(0.0, min(1.0, h_sim))
            y_sim = max(0.0, min(1.0, y_sim))

            sep_pref = max(0.0, 1.0 - (abs(separation - 0.24) / 0.24))
            spread = 1.0 if (min(cx1, cx2) < (width * 0.48) and max(cx1, cx2) > (width * 0.52)) else 0.6
            aspect_avg = (float(first['aspect']) + float(second['aspect'])) / 2.0
            vertical_gain = min(1.0, aspect_avg / 1.8)
            source_gain = 0.12 if ('red' in (first['source'], second['source'])) else 0.0
            local_pair_score = (
                (h_sim * 0.26)
                + (y_sim * 0.24)
                + (sep_pref * 0.20)
                + (spread * 0.12)
                + (vertical_gain * 0.18)
                + source_gain
            )
            if local_pair_score > best_pair_score:
                best_pair_score = local_pair_score
                best_pair = (first, second)

    def as_norm_bbox(item):
        return {
            'x': round(float(item['x']) / max(1.0, width), 4),
            'y': round(float(item['y']) / max(1.0, height), 4),
            'w': round(float(item['w']) / max(1.0, width), 4),
            'h': round(float(item['h']) / max(1.0, height), 4),
            'source': str(item.get('source', 'indefinido')),
        }

    if best_pair is None:
        best_single = candidates[0]
        single_conf = min(84.0, 24.0 + (float(best_single.get('score', 0.0)) * 0.68))
        if layout_score > 0.0:
            single_conf += min(14.0, float(layout_score) * 0.30)
        return {
            'detected': (single_conf >= 36.0) or (layout_score >= 36.0),
            'confidence': round(float(single_conf), 1),
            'vertical_pair': False,
            'components_detected': 1,
            'pair_score': round(float(layout_score), 1),
            'symmetry': 0.0,
            'left': as_norm_bbox(best_single),
            'right': None,
            'source': f"{str(best_single.get('source', 'indefinido'))}+layout_hint" if layout_score >= 36.0 else str(best_single.get('source', 'indefinido')),
            'layout_hint': bool(layout_score >= 36.0),
            'layout_hint_lines': int(layout_lines),
        }

    first, second = best_pair
    if float(first['x']) <= float(second['x']):
        left_tail = first
        right_tail = second
    else:
        left_tail = second
        right_tail = first

    h_delta = abs(float(left_tail['h']) - float(right_tail['h']))
    h_ref = max(1.0, max(float(left_tail['h']), float(right_tail['h'])))
    symmetry = max(0.0, 100.0 - ((h_delta / h_ref) * 100.0))
    min_aspect = min(float(left_tail.get('aspect', 0.0)), float(right_tail.get('aspect', 0.0)))
    vertical_pair = min_aspect >= 1.18
    pair_conf = max(0.0, min(1.0, best_pair_score))
    confidence = (pair_conf * 100.0)
    if vertical_pair:
        confidence += 9.0
    confidence += min(8.0, symmetry * 0.08)
    if layout_score > 0.0:
        confidence += min(12.0, float(layout_score) * 0.18)
    confidence = max(0.0, min(99.0, confidence))

    return {
        'detected': (confidence >= 42.0) or (layout_score >= 36.0),
        'confidence': round(float(confidence), 1),
        'vertical_pair': bool(vertical_pair),
        'components_detected': 2,
        'pair_score': round(float(max(pair_conf * 100.0, layout_score)), 1),
        'symmetry': round(float(symmetry), 1),
        'left': as_norm_bbox(left_tail),
        'right': as_norm_bbox(right_tail),
        'source': f"{left_tail.get('source', 'indefinido')}+{right_tail.get('source', 'indefinido')}" + ('+layout_hint' if layout_score >= 36.0 else ''),
        'layout_hint': bool(layout_score >= 36.0),
        'layout_hint_lines': int(layout_lines),
    }


def _roi_by_ratio(img, x1_ratio, y1_ratio, x2_ratio, y2_ratio):
    if img is None or getattr(img, 'size', 0) == 0:
        return None
    height, width = img.shape[:2]
    x1 = max(0, min(width, int(width * float(x1_ratio))))
    y1 = max(0, min(height, int(height * float(y1_ratio))))
    x2 = max(0, min(width, int(width * float(x2_ratio))))
    y2 = max(0, min(height, int(height * float(y2_ratio))))
    if x2 <= x1 or y2 <= y1:
        return None
    roi = img[y1:y2, x1:x2]
    if roi is None or getattr(roi, 'size', 0) == 0:
        return None
    return roi


def _roi_color_stats(roi):
    if roi is None or getattr(roi, 'size', 0) == 0:
        return {}

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    mask = ((sat > 24) & (val > 26))
    if float(np.mean(mask)) < 0.06:
        mask = (val > 24)

    selected_hsv = hsv[mask] if np.any(mask) else hsv.reshape(-1, 3)
    selected_lab = lab[mask] if np.any(mask) else lab.reshape(-1, 3)
    if selected_hsv.size == 0 or selected_lab.size == 0:
        return {}

    hue_vals = selected_hsv[:, 0].astype(np.float32)
    sat_vals = selected_hsv[:, 1].astype(np.float32)
    val_vals = selected_hsv[:, 2].astype(np.float32)
    lab_mean = np.mean(selected_lab.astype(np.float32), axis=0)
    return {
        'hue_mean': float(np.mean(hue_vals)),
        'sat_mean': float(np.mean(sat_vals)),
        'val_mean': float(np.mean(val_vals)),
        'lab_mean': [float(lab_mean[0]), float(lab_mean[1]), float(lab_mean[2])],
    }


def _lab_distance(stats_a, stats_b):
    if not isinstance(stats_a, dict) or not isinstance(stats_b, dict):
        return 0.0
    vec_a = np.asarray(stats_a.get('lab_mean', [0.0, 0.0, 0.0]), dtype=np.float32)
    vec_b = np.asarray(stats_b.get('lab_mean', [0.0, 0.0, 0.0]), dtype=np.float32)
    if vec_a.size != 3 or vec_b.size != 3:
        return 0.0
    return float(np.linalg.norm(vec_a - vec_b))


def _append_forensic_finding(target_list, code, description, confidence, location, finding_type, evidence=''):
    if not isinstance(target_list, list):
        return
    norm_code = str(code or '').strip()
    if not norm_code:
        return
    for item in target_list:
        if isinstance(item, dict) and str(item.get('codigo', '')).strip() == norm_code:
            return
    target_list.append({
        'codigo': norm_code,
        'tipo': str(finding_type or 'caracteristica_visual'),
        'descricao': str(description or '').strip(),
        'localizacao': str(location or 'indefinida'),
        'confianca': round(float(max(0.0, min(99.0, confidence))), 1),
        'status': 'potencial',
        'evidencia': str(evidence or '').strip(),
    })


def _detect_panel_color_mismatch(focus_img, findings):
    if focus_img is None or getattr(focus_img, 'size', 0) == 0:
        return
    if focus_img.shape[0] < 120 or focus_img.shape[1] < 180:
        return

    segments = {
        'lateral_esquerda': _roi_by_ratio(focus_img, 0.05, 0.34, 0.30, 0.84),
        'lateral_central': _roi_by_ratio(focus_img, 0.34, 0.34, 0.66, 0.84),
        'lateral_direita': _roi_by_ratio(focus_img, 0.70, 0.34, 0.95, 0.84),
    }
    stats = {name: _roi_color_stats(roi) for name, roi in segments.items()}
    if not all(isinstance(item, dict) and item for item in stats.values()):
        return

    diff_lc = _lab_distance(stats['lateral_esquerda'], stats['lateral_central'])
    diff_cr = _lab_distance(stats['lateral_central'], stats['lateral_direita'])
    diff_lr = _lab_distance(stats['lateral_esquerda'], stats['lateral_direita'])
    sat_center = float(stats['lateral_central'].get('sat_mean', 0.0))
    max_diff = max(diff_lc, diff_cr, diff_lr)

    if max_diff >= 22.0 and sat_center >= 28.0:
        conf = min(94.0, 38.0 + (max_diff * 1.45))
        if diff_lc >= 18.0 and diff_cr >= 18.0:
            _append_forensic_finding(
                findings,
                'possivel_porta_cor_diferente',
                'Possivel diferenca de tonalidade na regiao central lateral (porta/painel com pintura distinta).',
                conf,
                'lateral_central',
                'pintura',
                f'delta_lab_lc={diff_lc:.1f};delta_lab_cr={diff_cr:.1f}',
            )
        elif diff_cr > diff_lc:
            _append_forensic_finding(
                findings,
                'possivel_painel_direito_cor_diferente',
                'Possivel diferenca de cor entre painel lateral direito e demais paineis.',
                conf,
                'lateral_direita',
                'pintura',
                f'delta_lab_cr={diff_cr:.1f};delta_lab_lr={diff_lr:.1f}',
            )
        else:
            _append_forensic_finding(
                findings,
                'possivel_painel_esquerdo_cor_diferente',
                'Possivel diferenca de cor entre painel lateral esquerdo e demais paineis.',
                conf,
                'lateral_esquerda',
                'pintura',
                f'delta_lab_lc={diff_lc:.1f};delta_lab_lr={diff_lr:.1f}',
            )


def _detect_mirror_damage(scene_img, view_type, findings):
    if scene_img is None or getattr(scene_img, 'size', 0) == 0:
        return
    if str(view_type) not in ('frontal', 'indefinida'):
        return
    if scene_img.shape[0] < 120 or scene_img.shape[1] < 180:
        return

    gray = cv2.cvtColor(scene_img, cv2.COLOR_BGR2GRAY)
    left_roi = _roi_by_ratio(gray, 0.02, 0.20, 0.24, 0.56)
    right_roi = _roi_by_ratio(gray, 0.76, 0.20, 0.98, 0.56)
    if left_roi is None or right_roi is None:
        return

    left_edges = float(np.mean(cv2.Canny(left_roi, 70, 170) > 0) * 100.0)
    right_edges = float(np.mean(cv2.Canny(right_roi, 70, 170) > 0) * 100.0)
    left_texture = float(np.std(left_roi))
    right_texture = float(np.std(right_roi))
    left_score = (left_edges * 0.62) + (left_texture * 0.38)
    right_score = (right_edges * 0.62) + (right_texture * 0.38)

    max_score = max(left_score, right_score)
    min_score = min(left_score, right_score)
    if max_score < 6.0:
        return

    asymmetry_ratio = min_score / max(1e-6, max_score)
    if asymmetry_ratio <= 0.56 and abs(left_score - right_score) >= 4.5:
        if right_score < left_score:
            code = 'possivel_retrovisor_direito_danificado'
            location = 'frontal_direita'
            description = 'Possivel retrovisor direito danificado/ausente por forte assimetria lateral.'
        else:
            code = 'possivel_retrovisor_esquerdo_danificado'
            location = 'frontal_esquerda'
            description = 'Possivel retrovisor esquerdo danificado/ausente por forte assimetria lateral.'
        confidence = min(91.0, 34.0 + ((1.0 - asymmetry_ratio) * 86.0))
        _append_forensic_finding(
            findings,
            code,
            description,
            confidence,
            location,
            'avaria',
            f'left_score={left_score:.2f};right_score={right_score:.2f}',
        )


def _detect_front_fender_deformation(scene_img, view_type, findings):
    if scene_img is None or getattr(scene_img, 'size', 0) == 0:
        return
    if str(view_type) not in ('frontal', 'indefinida'):
        return
    if scene_img.shape[0] < 120 or scene_img.shape[1] < 200:
        return

    gray = cv2.cvtColor(scene_img, cv2.COLOR_BGR2GRAY)
    left_fender = _roi_by_ratio(gray, 0.03, 0.48, 0.30, 0.86)
    right_fender = _roi_by_ratio(gray, 0.70, 0.48, 0.97, 0.86)
    if left_fender is None or right_fender is None:
        return

    def fender_score(roi):
        edge_density = float(np.mean(cv2.Canny(roi, 68, 176) > 0) * 100.0)
        texture = float(np.std(roi))
        lap = float(cv2.Laplacian(roi, cv2.CV_64F).var())
        return (edge_density * 0.48) + (texture * 0.34) + (min(300.0, lap) * 0.06), edge_density, texture, lap

    left_score, left_edge, left_texture, left_lap = fender_score(left_fender)
    right_score, right_edge, right_texture, right_lap = fender_score(right_fender)
    max_side = max(left_score, right_score)
    min_side = min(left_score, right_score)
    if max_side < 9.0:
        return

    asym = abs(left_score - right_score) / max(1e-6, max_side)
    if asym >= 0.42:
        if right_score > left_score:
            code = 'possivel_amassado_paralama_dianteiro_direito'
            location = 'dianteira_direita'
            description = 'Possivel deformacao/amassado no paralama dianteiro direito (assimetria textural).'
        else:
            code = 'possivel_amassado_paralama_dianteiro_esquerdo'
            location = 'dianteira_esquerda'
            description = 'Possivel deformacao/amassado no paralama dianteiro esquerdo (assimetria textural).'
        confidence = min(90.0, 36.0 + (asym * 78.0))
        evidence = (
            f'left={left_score:.2f}(edge={left_edge:.2f},tex={left_texture:.2f},lap={left_lap:.1f});'
            f'right={right_score:.2f}(edge={right_edge:.2f},tex={right_texture:.2f},lap={right_lap:.1f})'
        )
        _append_forensic_finding(findings, code, description, confidence, location, 'avaria', evidence)


def _detect_rear_sticker(scene_img, view_type, findings):
    if scene_img is None or getattr(scene_img, 'size', 0) == 0:
        return
    if str(view_type) not in ('traseira', 'indefinida'):
        return
    if scene_img.shape[0] < 120 or scene_img.shape[1] < 180:
        return

    roi = _roi_by_ratio(scene_img, 0.20, 0.16, 0.80, 0.64)
    if roi is None:
        return
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    color_mask = cv2.inRange(hsv, (0, 92, 68), (180, 255, 255))
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return

    roi_h, roi_w = roi.shape[:2]
    roi_area = float(max(1, roi_h * roi_w))
    best_conf = 0.0
    best_shape = ''
    for contour in contours:
        area = float(cv2.contourArea(contour))
        ratio = area / roi_area
        if ratio < 0.0008 or ratio > 0.045:
            continue
        x, y, box_w, box_h = cv2.boundingRect(contour)
        if box_w < 10 or box_h < 6:
            continue
        box_area = float(max(1, box_w * box_h))
        fill_ratio = area / box_area
        aspect = float(box_w) / max(1.0, float(box_h))
        if aspect < 0.7 or aspect > 8.0:
            continue
        rectangularity = min(1.0, max(0.0, fill_ratio))
        conf = (ratio * 1800.0) + (rectangularity * 44.0) + (min(3.5, aspect) * 8.0)
        if conf > best_conf:
            best_conf = conf
            best_shape = f'ratio={ratio:.4f};fill={fill_ratio:.2f};aspect={aspect:.2f}'

    if best_conf >= 52.0:
        confidence = min(88.0, best_conf)
        _append_forensic_finding(
            findings,
            'possivel_adesivo_traseiro',
            'Possivel adesivo/marcacao na parte traseira detectado por bloco cromatico localizado.',
            confidence,
            'traseira_superior',
            'marcacao',
            best_shape,
        )


def _detect_forensic_vehicle_traits(scene, vehicle_focus, view_type, color_profile, component_profile):
    if not FORENSIC_TRAITS_ENABLED:
        return {
            'status': 'disabled',
            'achados': [],
            'total_achados': 0,
            'itens_avaliados': [],
            'resumo': [],
            'observacoes': ['forensic_traits_disabled'],
        }

    findings = []
    focus_img = vehicle_focus if vehicle_focus is not None and getattr(vehicle_focus, 'size', 0) != 0 else scene
    _detect_panel_color_mismatch(focus_img, findings)
    _detect_mirror_damage(scene, view_type, findings)
    _detect_front_fender_deformation(scene, view_type, findings)
    _detect_rear_sticker(scene, view_type, findings)

    findings.sort(key=lambda item: float(item.get('confianca', 0.0)), reverse=True)
    evaluated = [
        'consistencia_de_cor_lateral',
        'integridade_retrovisores',
        'simetria_paralamas_dianteiros',
        'marcacoes_adesivos_traseiros',
    ]
    summary = []
    for entry in findings[:6]:
        if not isinstance(entry, dict):
            continue
        summary.append(
            f"{entry.get('codigo', 'achado_visual')} ({float(entry.get('confianca', 0.0)):.1f}%): {entry.get('descricao', '-')}"
        )

    observations = []
    if not findings:
        observations.append('sem_achados_forenses_relevantes')
    observations.append('caracteristicas_forenses_requerem_confirmacao_humana')

    return {
        'status': 'achados_potenciais' if findings else 'sem_achados_relevantes',
        'achados': findings[:8],
        'total_achados': int(len(findings)),
        'itens_avaliados': evaluated,
        'resumo': summary[:8],
        'observacoes': observations,
        'cor_contexto': str((color_profile or {}).get('color_name', 'indefinida')),
        'componentes_cobertura': float((component_profile or {}).get('cobertura_percentual', 0.0) if isinstance(component_profile, dict) else 0.0),
    }


def _is_non_conclusive_model_name(model_name):
    model = str(model_name or '').strip().lower()
    return model in (
        '',
        'nao conclusivo',
        'nÃƒÂ£o conclusivo',
        'indeterminado',
        'modelo indeterminado',
        'desconhecido',
    )


def _is_non_conclusive_brand_name(brand_name):
    brand = str(brand_name or '').strip().lower()
    return brand in (
        '',
        'nao conclusivo',
        'nÃƒÂ£o conclusivo',
        'indeterminado',
        'marca indeterminada',
        'desconhecido',
    )


def _apply_visual_model_abstention(hypotheses, component_profile=None, view_type='indefinida', rear_signature=None):
    if not isinstance(hypotheses, list) or not hypotheses:
        return {}, [], {
            'status': 'no_hypothesis',
            'model_abstained': True,
            'reasons': ['sem_hipoteses_visuais'],
        }

    top = dict(hypotheses[0]) if isinstance(hypotheses[0], dict) else {}
    second = hypotheses[1] if len(hypotheses) > 1 and isinstance(hypotheses[1], dict) else {}
    top_conf = float(top.get('confianca', 0.0))
    second_conf = float(second.get('confianca', 0.0))
    margin = round(float(top_conf - second_conf), 2)
    coverage = float((component_profile or {}).get('cobertura_percentual', 0.0) if isinstance(component_profile, dict) else 0.0)
    rear_conf = float((rear_signature or {}).get('confidence', 0.0) if isinstance(rear_signature, dict) else 0.0)

    evidences = top.get('evidencias', [])
    if not isinstance(evidences, list):
        evidences = []

    discriminative_tags = {
        'lanternas_traseiras_verticais_laterais',
        'lanterna_traseira_compativel_hatch',
        'assinatura_traseira_parcial',
        'hatch_compacto_classico',
    }
    discriminative_count = sum(1 for item in evidences if str(item) in discriminative_tags)

    metadata = {
        'status': 'ok',
        'model_abstained': False,
        'raw_confidence': round(float(top_conf), 2),
        'confidence_margin_top2': float(margin),
        'component_coverage': round(float(coverage), 1),
        'discriminative_evidence_count': int(discriminative_count),
        'view_type': str(view_type or 'indefinida'),
        'reasons': [],
    }

    if not VISUAL_MODEL_ABSTAIN_ENABLE:
        return top, hypotheses, metadata

    reasons = []
    if top_conf < VISUAL_MODEL_MIN_CONFIDENCE:
        reasons.append('confianca_modelo_abaixo_limite')
    if margin < VISUAL_MODEL_MIN_MARGIN:
        reasons.append('margem_top2_insuficiente')
    if discriminative_count < VISUAL_MODEL_MIN_DISCRIMINATIVE_EVIDENCE and rear_conf < 72.0:
        reasons.append('evidencia_discriminativa_insuficiente')

    # Se estiver em close-up extremo da placa, forÃ§amos abstenÃ§Ã£o pois nÃ£o hÃ¡ cenÃ¡rio
    low_context = bool((component_profile or {}).get('low_context_blocked', False))
    if low_context:
        reasons.append('dados_visuais_insuficientes_close_up_placa')

    if reasons:
        principal = dict(top)
        raw_brand = str(top.get('fabricante', '')).strip()
        raw_brand_conf = float(top.get('confianca', 0.0))
        if raw_brand and raw_brand_conf >= VISUAL_BRAND_MIN_CONFIDENCE:
            principal['fabricante'] = raw_brand
        else:
            principal['fabricante'] = 'Indeterminado'

        principal['modelo'] = 'Nao conclusivo'
        principal['faixa_ano_modelo'] = 'indeterminado'
        principal['confianca'] = round(float(raw_brand_conf * 0.5), 1)
        principal['confianca_modelo_bruta'] = round(float(raw_brand_conf), 1)
        principal['margem_top2'] = float(margin)
        principal['motivo_abstencao_modelo'] = ';'.join(reasons)
        safe_evidence = list(evidences[:6])
        safe_evidence.append('abstencao_modelo_por_baixa_evidencia')
        principal['evidencias'] = safe_evidence[:7]

        metadata['status'] = 'model_abstained'
        metadata['model_abstained'] = True
        metadata['reasons'] = reasons
        return principal, hypotheses, metadata

    if _is_non_conclusive_brand_name(top.get('fabricante', '')):
        principal = dict(top)
        principal['fabricante'] = 'Indeterminado'
        principal['modelo'] = 'Nao conclusivo'
        principal['faixa_ano_modelo'] = 'indeterminado'
        principal['confianca_modelo_bruta'] = round(float(top_conf), 1)
        principal['motivo_abstencao_modelo'] = 'fabricante_nao_conclusivo'
        principal['evidencias'] = list(evidences[:6]) + ['abstencao_modelo_por_fabricante_indeterminado']
        metadata['status'] = 'model_abstained'
        metadata['model_abstained'] = True
        metadata['reasons'] = ['fabricante_nao_conclusivo']
        return principal, hypotheses, metadata

    metadata['reasons'] = ['modelo_conclusivo']
    return top, hypotheses, metadata


def _build_open_source_comparison(principal, hypotheses, rear_signature, component_profile=None, view_type='indefinida', forensic_traits=None):
    if not isinstance(principal, dict) or not principal:
        return {}

    fabricante = str(principal.get('fabricante', '')).strip()
    modelo = str(principal.get('modelo', '')).strip()
    brand_conclusive = not _is_non_conclusive_brand_name(fabricante)
    model_conclusive = not _is_non_conclusive_model_name(modelo)
    if not brand_conclusive:
        fabricante = 'Marca indeterminada'
        modelo = 'Modelo indeterminado'
        model_conclusive = False
    elif not fabricante:
        fabricante = 'Marca indeterminada'
    if not model_conclusive:
        modelo = 'Modelo indeterminado'
    alvo = f'{fabricante} {modelo}'.strip()
    reference_bundle = visual_reference_catalog_module.build_reference_bundle(
        fabricante,
        modelo,
        category='AUTOMOVEL',
        view_type=view_type,
        model_conclusive=model_conclusive,
    )
    sources = reference_bundle.get('fontes', [])
    checklist = reference_bundle.get('checklist_pericial', [])
    criteria = reference_bundle.get('criterios_individualizacao', [])
    search_engines = reference_bundle.get('motores_busca_utilizados', [])
    analysis_engines = reference_bundle.get('motores_analise_utilizados', [])
    families_summary = reference_bundle.get('familias_fontes', {})
    query_specs = reference_bundle.get('query_specs', [])
    query_tail = str(query_specs[0][0]) if isinstance(query_specs, list) and query_specs else alvo
    comparative_systems = [
        {
            'sistema': 'Plate Recognizer Snapshot API',
            'categoria': 'cloud_alpr',
            'integracao_local': 'ativo' if bool(PLATE_RECOGNIZER_TOKEN) else 'opcional_token',
            'url': 'https://guides.platerecognizer.com/docs/snapshot/api-reference/',
        },
        {
            'sistema': 'Rekor CarCheck / OpenALPR',
            'categoria': 'cloud_alpr_vehicle',
            'integracao_local': 'ativo' if bool(OPENALPR_SECRET_KEY) else 'opcional_secret_key',
            'url': 'https://docs.rekor.ai/developers/carcheck/integration',
        },
        {
            'sistema': 'OpenALPR (open source)',
            'categoria': 'open_source_alpr',
            'integracao_local': 'referencia_arquitetural',
            'url': 'https://github.com/openalpr/openalpr',
        },
        {
            'sistema': 'Nomeroff-Net',
            'categoria': 'open_source_alpr',
            'integracao_local': 'ativo_endpoint' if bool(NOMEROFF_COMPARE_ENDPOINT) else 'opcional_endpoint',
            'url': 'https://github.com/ria-com/nomeroff-net',
        },
    ]

    hypothesis_lines = []
    if isinstance(hypotheses, list):
        for item in hypotheses[:3]:
            if not isinstance(item, dict):
                continue
            line = (
                f"{item.get('fabricante', '-')}/{item.get('modelo', '-')} "
                f"({item.get('confianca', 0)}%) ano {item.get('faixa_ano_modelo', '-')}"
            )
            hypothesis_lines.append(line)

    component_lines = []
    components = ((component_profile or {}).get('componentes', {}) if isinstance(component_profile, dict) else {})
    if isinstance(components, dict):
        labels = {
            'emblema_frontal': 'Emblema frontal',
            'grade_dianteira': 'Grade dianteira',
            'farois_dianteiros': 'Farois dianteiros',
            'lanternas_traseiras': 'Lanternas traseiras',
            'linhas_portas': 'Linhas de portas',
            'capo_dianteiro': 'Capo dianteiro',
            'tampa_traseira': 'Tampa traseira',
            'design_carroceria': 'Design de carroceria',
        }
        for key in labels:
            entry = components.get(key, {})
            if not isinstance(entry, dict):
                continue
            status = str(entry.get('status', 'indefinido'))
            conf = round(float(entry.get('confianca', 0.0)), 1)
            detail = str(entry.get('detalhe', '')).strip()
            line = f"{labels[key]}: {status} ({conf}%)"
            if detail:
                line += f" - {detail}"
            component_lines.append(line)

    component_queries = []
    component_specs = [
        ('emblema_frontal', 'Emblema frontal', 'emblema frontal logotipo grade'),
        ('grade_dianteira', 'Grade dianteira', 'grade dianteira desenho frontal'),
        ('farois_dianteiros', 'Farois dianteiros', 'farol dianteiro assinatura optica'),
        ('lanternas_traseiras', 'Lanternas traseiras', 'lanterna traseira assinatura lente'),
        ('linhas_portas', 'Linhas de portas', 'perfil lateral portas vincos'),
        ('capo_dianteiro', 'Capo dianteiro', 'capo dianteiro vincos recorte'),
        ('tampa_traseira', 'Tampa traseira', 'tampa traseira recorte placa'),
        ('design_carroceria', 'Design de carroceria', 'perfil carroceria hatch sedan'),
    ]
    for key, label, terms in component_specs:
        query = f'{alvo} {terms}'
        status_entry = components.get(key, {}) if isinstance(components, dict) else {}
        status = str(status_entry.get('status', 'indefinido'))
        conf = round(float(status_entry.get('confianca', 0.0)), 1)
        if model_conclusive and fabricante and fabricante != 'Marca indeterminada':
            component_webmotors_url = (
                'https://www.webmotors.com.br/carros/estoque?marca='
                + quote_plus(fabricante)
                + '&modelo='
                + quote_plus(modelo)
            )
        else:
            component_webmotors_url = 'https://www.google.com/search?q=' + quote_plus('site:webmotors.com.br ' + query)
        component_queries.append({
            'componente': key,
            'rotulo': label,
            'status': status,
            'confianca': conf,
            'consulta': query,
            'fontes': [
                {
                    'fonte': 'google_imagens',
                    'url': 'https://www.google.com/search?tbm=isch&q=' + quote_plus(query),
                    'objetivo': 'comparacao visual por foto',
                },
                {
                    'fonte': 'google_web',
                    'url': 'https://www.google.com/search?q=' + quote_plus(query),
                    'objetivo': 'ficha tecnica e materia especializada',
                },
                {
                    'fonte': 'webmotors',
                    'url': component_webmotors_url,
                    'objetivo': 'fotos reais de anuncios',
                },
            ],
        })

    forensic_queries = []
    forensic_findings = (forensic_traits or {}).get('achados', []) if isinstance(forensic_traits, dict) else []
    if isinstance(forensic_findings, list):
        for finding in forensic_findings[:6]:
            if not isinstance(finding, dict):
                continue
            code = str(finding.get('codigo', 'achado_visual')).strip() or 'achado_visual'
            description = str(finding.get('descricao', '')).strip()
            location = str(finding.get('localizacao', 'indefinida')).strip()
            keyword_map = {
                'possivel_amassado_paralama_dianteiro_direito': 'paralama dianteiro direito amassado',
                'possivel_amassado_paralama_dianteiro_esquerdo': 'paralama dianteiro esquerdo amassado',
                'possivel_porta_cor_diferente': 'porta com cor diferente repintura',
                'possivel_painel_direito_cor_diferente': 'lateral direita cor diferente repintura',
                'possivel_painel_esquerdo_cor_diferente': 'lateral esquerda cor diferente repintura',
                'possivel_retrovisor_direito_danificado': 'retrovisor direito quebrado',
                'possivel_retrovisor_esquerdo_danificado': 'retrovisor esquerdo quebrado',
                'possivel_adesivo_traseiro': 'adesivo traseiro vidro porta malas',
            }
            terms = keyword_map.get(code, description or code.replace('_', ' '))
            query = f'{alvo} {terms}'.strip()
            if model_conclusive and fabricante and fabricante != 'Marca indeterminada':
                forensic_webmotors_url = (
                    'https://www.webmotors.com.br/carros/estoque?marca='
                    + quote_plus(fabricante)
                    + '&modelo='
                    + quote_plus(modelo)
                )
            else:
                forensic_webmotors_url = 'https://www.google.com/search?q=' + quote_plus('site:webmotors.com.br ' + query)
            forensic_queries.append({
                'caracteristica': code,
                'descricao': description or code.replace('_', ' '),
                'localizacao': location,
                'consulta': query,
                'fontes': [
                    {
                        'fonte': 'google_imagens',
                        'url': 'https://www.google.com/search?tbm=isch&q=' + quote_plus(query),
                        'objetivo': 'comparar padrao visual em imagens abertas',
                    },
                    {
                        'fonte': 'webmotors',
                        'url': forensic_webmotors_url,
                        'objetivo': 'conferir variacoes reais em anuncios',
                    },
                    {
                        'fonte': 'olx',
                        'url': 'https://www.google.com/search?q=' + quote_plus('site:olx.com.br ' + query),
                        'objetivo': 'buscar ocorrencias semelhantes em vendas abertas',
                    },
                ],
            })

    alvo_ajustado = False
    ajuste_por_lanterna = False
    ajuste_motivo = ""

    # Refino pericial tecnico: avalia candidatos proximos se houver forte sinal de componente.
    if isinstance(hypotheses, list) and len(hypotheses) >= 2:
        top1 = hypotheses[0]
        top2 = hypotheses[1]
        margin = abs(float(top1.get('confianca', 0)) - float(top2.get('confianca', 0)))

        # Se a margem for pequena (disputa tecnica) e houver sinal de componente (ex: lanternas verticais)
        # Se a margem for pequena (disputa tecnica), evitamos o chute forcado.
        # A decisao deve ser ratificada por outros fatores ou permanecer em analise.
        if margin <= 7.5:
            ajuste_motivo = f"Disputa tecnica entre modelos com margem de {margin:.1f}% - Aguardando evidencias forenses conclusivas"

    return {
        'modelo_alvo': alvo,
        'modelo_conclusivo': bool(model_conclusive),
        'origem_hipotese_modelo': 'heuristica_visual_local',
        'modelo_alvo_ajustado': bool(alvo_ajustado),
        'modelo_alvo_ajustado_por_lanterna': bool(ajuste_por_lanterna),
        'modelo_alvo_ajuste_motivo': ajuste_motivo,
        'vista_alvo': str(view_type or 'indefinida'),
        'consulta_principal': query_tail,
        'fontes': sources,
        'consultas_componentes': component_queries,
        'checklist_pericial': checklist,
        'criterios_individualizacao': criteria,
        'motores_busca_utilizados': search_engines,
        'motores_analise_utilizados': analysis_engines,
        'fontes_total': int(len(sources)),
        'familias_fontes': families_summary,
        'consultas_referencia': [
            {
                'consulta': str(query),
                'alvo': str(hint),
            }
            for query, hint in query_specs[:12]
        ],
        'metodologia_pericial': (
            'Relatorio tecnico-pericial preliminar com inferencia visual automatizada, '
            'checagem de consistencia e consulta em fontes abertas rastreaveis.'
        ),
        'sistemas_referencia': comparative_systems,
        'hipoteses_resumidas': hypothesis_lines,
        'assinaturas_componentes': component_lines,
        'consultas_caracteristicas': forensic_queries,
        'sinal_lanterna_traseira': {
            'detected': bool((rear_signature or {}).get('detected')),
            'vertical_pair': bool((rear_signature or {}).get('vertical_pair')),
            'confidence': float((rear_signature or {}).get('confidence', 0.0)),
        },
    }


def _build_visual_evidence_matrix(hypotheses, component_profile=None, geometry_profile=None, rear_signature=None, view_type='indefinida'):
    if not isinstance(hypotheses, list) or not hypotheses:
        return {
            'status': 'vazio',
            'view_type': str(view_type or 'indefinida'),
            'component_snapshot': [],
            'candidates': [],
            'summary': [],
            'notes': ['matriz_evidencias_sem_hipoteses'],
        }

    components = (component_profile or {}).get('componentes', {}) if isinstance(component_profile, dict) else {}
    if not isinstance(components, dict):
        components = {}

    component_labels = {
        'emblema_frontal': 'Emblema frontal',
        'grade_dianteira': 'Grade dianteira',
        'farois_dianteiros': 'Farois dianteiros',
        'lanternas_traseiras': 'Lanternas traseiras',
        'linhas_portas': 'Linhas de portas',
        'capo_dianteiro': 'Capo dianteiro',
        'tampa_traseira': 'Tampa traseira',
        'design_carroceria': 'Design de carroceria',
    }
    component_snapshot = []
    for key, label in component_labels.items():
        entry = components.get(key, {})
        if not isinstance(entry, dict) or not entry:
            continue
        component_snapshot.append({
            'componente': label,
            'status': str(entry.get('status', 'indefinido')),
            'confianca': round(float(entry.get('confianca', 0.0)), 1),
            'detalhe': str(entry.get('detalhe', '')),
        })

    evidence_catalog = {
        'frontal_simetrica': {
            'descricao': 'Simetria frontal compatÃƒÂ­vel com carroceria compacta e frente alinhada.',
            'peso': 7.0,
            'categoria': 'geometria',
            'componentes': ['geometria'],
        },
        'farois_duplos_detectados': {
            'descricao': 'Conjunto ÃƒÂ³tico dianteiro bilateral detectado com maior consistÃƒÂªncia.',
            'peso': 8.0,
            'categoria': 'optica',
            'componentes': ['farois_dianteiros'],
        },
        'proporcao_compacta': {
            'descricao': 'ProporÃƒÂ§ÃƒÂ£o global compacta favorece modelos hatch pequenos.',
            'peso': 8.0,
            'categoria': 'carroceria',
            'componentes': ['design_carroceria'],
        },
        'grade_central_presente': {
            'descricao': 'Grade frontal presente e coerente com veÃƒÂ­culo de passeio compacto.',
            'peso': 5.0,
            'categoria': 'frontal',
            'componentes': ['grade_dianteira'],
        },
        'emblema_central_circular_ou_oval': {
            'descricao': 'Emblema central circular/oval detectado, compatÃƒÂ­vel com marcas de volume.',
            'peso': 18.0,
            'categoria': 'identidade',
            'componentes': ['emblema_frontal'],
        },
        'cor_emblema_compativel_fiat': {
            'descricao': 'Tonalidade do emblema compatÃƒÂ­vel com assinatura visual Fiat.',
            'peso': 12.0,
            'categoria': 'identidade',
            'componentes': ['emblema_frontal'],
        },
        'cor_veiculo_vermelha': {
            'descricao': 'Cor vermelha favorece alguns perfis de hatch compacto analisados.',
            'peso': 4.0,
            'categoria': 'cor',
            'componentes': ['design_carroceria'],
        },
        'lanternas_traseiras_verticais_laterais': {
            'descricao': 'Presenca de lanternas traseiras verticais laterais observada.',
            'peso': 15.0,
            'categoria': 'traseira',
            'componentes': ['lanternas_traseiras', 'tampa_traseira'],
        },
        'lanterna_traseira_compativel_hatch': {
            'descricao': 'Assinatura traseira compatÃƒÂ­vel com hatch compacto de pequeno porte.',
            'peso': 7.0,
            'categoria': 'traseira',
            'componentes': ['lanternas_traseiras', 'design_carroceria'],
        },
        'assinatura_traseira_parcial': {
            'descricao': 'Parte da assinatura traseira estÃƒÂ¡ coerente com o padrÃƒÂ£o do modelo candidato.',
            'peso': 10.0,
            'categoria': 'traseira',
            'componentes': ['lanternas_traseiras'],
        },
        'assinatura_traseira_compativel_compacto': {
            'descricao': 'Vista traseira compatÃƒÂ­vel com o padrÃƒÂ£o esperado para veÃ­culos compactos verticais.',
            'peso': 8.0,
            'categoria': 'traseira',
            'componentes': ['tampa_traseira', 'lanternas_traseiras'],
        },
        'hatch_compacto_classico': {
            'descricao': 'Perfil de hatch compacto clÃƒÂ¡ssico observado na composiÃƒÂ§ÃƒÂ£o da cena.',
            'peso': 7.0,
            'categoria': 'carroceria',
            'componentes': ['design_carroceria'],
        },
    }

    def _component_context(name):
        if name == 'geometria':
            return {
                'componente': 'Geometria frontal',
                'status': str(view_type or 'indefinida'),
                'confianca': round(float((geometry_profile or {}).get('frontal_symmetry', 0.0)), 1),
                'detalhe': (
                    f"simetria={float((geometry_profile or {}).get('frontal_symmetry', 0.0)):.1f}; "
                    f"grade={float((geometry_profile or {}).get('grille_edge_density', 0.0)):.1f}"
                ),
            }

        entry = components.get(name, {})
        if not isinstance(entry, dict) or not entry:
            return None
        return {
            'componente': component_labels.get(name, name),
            'status': str(entry.get('status', 'indefinido')),
            'confianca': round(float(entry.get('confianca', 0.0)), 1),
            'detalhe': str(entry.get('detalhe', '')),
        }

    candidates = []
    for item in hypotheses[:VISUAL_PROFILE_TOP_HYPOTHESES]:
        if not isinstance(item, dict):
            continue

        rows = []
        total_support_weight = 0.0
        evidence_items = item.get('evidencias', [])
        if not isinstance(evidence_items, list):
            evidence_items = []

        for tag in evidence_items:
            evidence_key = str(tag)
            meta = evidence_catalog.get(
                evidence_key,
                {
                    'descricao': evidence_key.replace('_', ' '),
                    'peso': 0.0,
                    'categoria': 'geral',
                    'componentes': [],
                },
            )

            related_components = []
            for comp_key in meta.get('componentes', []):
                context = _component_context(comp_key)
                if context is not None:
                    related_components.append(context)

            weight = round(float(meta.get('peso', 0.0)), 1)
            total_support_weight += float(weight)
            impact = 'forte' if weight >= 18.0 else ('moderado' if weight >= 8.0 else 'fraco')

            rows.append({
                'evidencia': evidence_key,
                'descricao': meta.get('descricao', evidence_key.replace('_', ' ')),
                'categoria': meta.get('categoria', 'geral'),
                'peso_nominal': weight,
                'impacto': impact,
                'componentes_relacionados': related_components,
            })

        if str(item.get('fonte_faixa_ano', '')).strip():
            rows.append({
                'evidencia': 'faixa_ano_base_aberta',
                'descricao': f"Faixa de ano validada por {item.get('fonte_faixa_ano', '')}",
                'categoria': 'open_data',
                'peso_nominal': 4.0,
                'impacto': 'apoio',
                'componentes_relacionados': [
                    {
                        'componente': 'Base aberta',
                        'status': str(item.get('modelo_match_base_aberta', 'indefinido') or 'indefinido'),
                        'confianca': 100.0,
                        'detalhe': str(item.get('modelo_match_base_aberta', '')),
                    }
                ] if str(item.get('modelo_match_base_aberta', '')).strip() else [],
            })
            total_support_weight += 4.0

        rows.sort(key=lambda entry: float(entry.get('peso_nominal', 0.0)), reverse=True)

        candidates.append({
            'fabricante': str(item.get('fabricante', '')),
            'modelo': str(item.get('modelo', '')),
            'faixa_ano_modelo': str(item.get('faixa_ano_modelo', '')),
            'confianca': round(float(item.get('confianca', 0.0)), 1),
            'status': 'abstido' if _is_non_conclusive_model_name(item.get('modelo', '')) else 'conclusivo',
            'rows': rows[:8],
            'peso_total_apoio': round(float(total_support_weight), 1),
            'evidencias_contadas': int(len(rows)),
            'fonte_ano': str(item.get('fonte_faixa_ano', '')),
            'modelo_match_base_aberta': str(item.get('modelo_match_base_aberta', '')),
        })

    summary = []
    if candidates:
        top = candidates[0]
        summary.append(
            f"{top.get('fabricante', '-')}/{top.get('modelo', '-')} com {top.get('evidencias_contadas', 0)} evidencias e peso {float(top.get('peso_total_apoio', 0.0)):.1f}"
        )
        if str(top.get('fonte_ano', '')).strip():
            summary.append(f"Ano validado por {top.get('fonte_ano', '')}")

    return {
        'status': 'ok' if candidates else 'vazio',
        'view_type': str(view_type or 'indefinida'),
        'component_snapshot': component_snapshot,
        'candidates': candidates,
        'summary': summary,
        'notes': [
            'matriz_evidencias_baseada_em_componentes',
            'validacao_humana_obrigatoria',
        ],
    }


def _analyze_visual_geometry(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {}

    height, width = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 80, 190)

    half = width // 2
    left = edges[:, :half]
    right = edges[:, width - half:]
    right = cv2.flip(right, 1)
    if right.shape != left.shape:
        right = cv2.resize(right, (left.shape[1], left.shape[0]), interpolation=cv2.INTER_NEAREST)
    symmetry = 100.0 - (float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32)))) / 255.0 * 100.0)
    symmetry = max(0.0, min(100.0, symmetry))

    grille = edges[int(height * 0.38):int(height * 0.72), int(width * 0.22):int(width * 0.78)]
    grille_density = float(np.mean(grille > 0) * 100.0) if grille.size else 0.0

    lamps = edges[int(height * 0.24):int(height * 0.54), :]
    left_lamp = lamps[:, int(width * 0.03):int(width * 0.28)]
    right_lamp = lamps[:, int(width * 0.72):int(width * 0.97)]
    left_lamp_density = float(np.mean(left_lamp > 0) * 100.0) if left_lamp.size else 0.0
    right_lamp_density = float(np.mean(right_lamp > 0) * 100.0) if right_lamp.size else 0.0
    dual_headlamps = left_lamp_density >= 1.8 and right_lamp_density >= 1.8

    edge_coords = cv2.findNonZero(edges)
    aspect_ratio = 0.0
    compact = False
    if edge_coords is not None:
        x, y, box_w, box_h = cv2.boundingRect(edge_coords)
        aspect_ratio = float(box_w) / max(1.0, float(box_h))
        compact = aspect_ratio <= 1.95

    return {
        'frontal_symmetry': round(float(symmetry), 2),
        'grille_edge_density': round(float(grille_density), 2),
        'headlamp_left_density': round(float(left_lamp_density), 2),
        'headlamp_right_density': round(float(right_lamp_density), 2),
        'dual_headlamps': bool(dual_headlamps),
        'vehicle_aspect_ratio': round(float(aspect_ratio), 3),
        'compact_vehicle': bool(compact),
    }


def _edge_density_in_box(gray_img, x1_ratio, y1_ratio, x2_ratio, y2_ratio, low=68, high=178):
    if gray_img is None or getattr(gray_img, 'size', 0) == 0:
        return 0.0

    height, width = gray_img.shape[:2]
    x1 = max(0, min(width, int(width * x1_ratio)))
    y1 = max(0, min(height, int(height * y1_ratio)))
    x2 = max(0, min(width, int(width * x2_ratio)))
    y2 = max(0, min(height, int(height * y2_ratio)))
    if x2 <= x1 or y2 <= y1:
        return 0.0

    roi = gray_img[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0

    edges = cv2.Canny(roi, low, high)
    return float(np.mean(edges > 0) * 100.0)


def _count_projection_peaks(values, threshold_scale=1.25, min_gap=6):
    if values is None:
        return 0, 0.0
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return 0, 0.0

    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr))
    threshold = mean_val + (std_val * float(threshold_scale))
    idx = np.where(arr >= threshold)[0]
    if idx.size == 0:
        return 0, 0.0

    groups = 0
    prev = -9999
    for value in idx:
        if int(value) - int(prev) > int(min_gap):
            groups += 1
        prev = int(value)

    peak_level = float(np.max(arr))
    return int(groups), float(peak_level)


def _analyze_vehicle_component_signatures(scene, vehicle_focus, view_type, emblem_profile, rear_signature, geometry_profile, low_context=False):
    if scene is None or getattr(scene, 'size', 0) == 0:
        return {'componentes': {}, 'itens_avaliados': 0, 'itens_detectados': 0, 'cobertura_percentual': 0.0, 'resumo_lista': []}

    if low_context:
        # Se estiver em close-up da placa, desativamos detecÃ§Ãµes que exigem visÃ£o de cenÃ¡rio.
        return {
            'componentes': {},
            'itens_avaliados': 8,
            'itens_detectados': 0,
            'cobertura_percentual': 0.0,
            'resumo_lista': ['InformacÃ£o visual limitada ao recorte da placa - DetecÃ§Ãµes de componentes suspensas para evitar alucinacÃµes'],
            'low_context_blocked': True
        }

    gray_scene = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
    focus_img = vehicle_focus if vehicle_focus is not None and getattr(vehicle_focus, 'size', 0) != 0 else scene
    gray_focus = cv2.cvtColor(focus_img, cv2.COLOR_BGR2GRAY)

    components = {}
    labels = {
        'emblema_frontal': 'Emblema frontal',
        'grade_dianteira': 'Grade dianteira',
        'farois_dianteiros': 'Farois dianteiros',
        'lanternas_traseiras': 'Lanternas traseiras',
        'linhas_portas': 'Linhas de portas',
        'capo_dianteiro': 'Capo dianteiro',
        'tampa_traseira': 'Tampa traseira',
        'design_carroceria': 'Design de carroceria',
    }

    # Emblema frontal
    emblem_detected = bool((emblem_profile or {}).get('detected'))
    emblem_conf = max(0.0, min(99.0, float((emblem_profile or {}).get('confidence', 0.0))))
    emblem_shape = str((emblem_profile or {}).get('shape', 'indefinido'))
    rear_view = str(view_type) == 'traseira'
    if emblem_detected and rear_view:
        emblem_status = 'emblema_traseiro_detectado'
        emblem_detail = f'logomarca posterior {emblem_shape}'
    elif emblem_detected:
        emblem_status = 'detectado'
        emblem_detail = f'geometria {emblem_shape}'
    elif rear_view:
        emblem_status = 'limitado_vista_traseira'
        emblem_detail = 'frente nao predominante na cena'
    else:
        emblem_status = 'nao_detectado'
        emblem_detail = 'sem contorno central robusto'
    components['emblema_frontal'] = {
        'rotulo': labels['emblema_frontal'],
        'status': emblem_status,
        'confianca': round(float(emblem_conf), 1),
        'detalhe': emblem_detail,
    }

    # Grade dianteira
    grille_density = float((geometry_profile or {}).get('grille_edge_density', 0.0))
    grille_conf = max(0.0, min(99.0, 28.0 + (grille_density * 4.8)))
    if rear_view:
        grille_status = 'nao_aplicavel_vista_traseira'
        grille_conf = 0.0
    elif grille_density >= 3.2:
        grille_status = 'presente'
    elif grille_density >= 1.6:
        grille_status = 'fraca'
    else:
        grille_status = 'nao_detectada'
    components['grade_dianteira'] = {
        'rotulo': labels['grade_dianteira'],
        'status': grille_status,
        'confianca': round(float(grille_conf), 1),
        'detalhe': f'densidade de bordas {round(grille_density, 2)}',
    }

    # Farois dianteiros
    headlamp_left = float((geometry_profile or {}).get('headlamp_left_density', 0.0))
    headlamp_right = float((geometry_profile or {}).get('headlamp_right_density', 0.0))
    headlamp_sym = max(0.0, 100.0 - abs(headlamp_left - headlamp_right) * 18.0)
    headlamp_presence = max(0.0, min(99.0, ((headlamp_left + headlamp_right) * 12.0)))
    headlamp_conf = min(99.0, (headlamp_presence * 0.70) + (headlamp_sym * 0.30))
    if rear_view:
        headlamp_status = 'nao_aplicavel_vista_traseira'
        headlamp_conf = 0.0
    elif bool((geometry_profile or {}).get('dual_headlamps')):
        headlamp_status = 'simetricos'
    elif headlamp_conf >= 48.0:
        headlamp_status = 'parcial'
    else:
        headlamp_status = 'indefinido'
    components['farois_dianteiros'] = {
        'rotulo': labels['farois_dianteiros'],
        'status': headlamp_status,
        'confianca': round(float(headlamp_conf), 1),
        'detalhe': f'densidade L/R {round(headlamp_left, 2)}/{round(headlamp_right, 2)}',
    }

    # Lanternas traseiras
    rear_detected = bool((rear_signature or {}).get('detected'))
    rear_vertical = bool((rear_signature or {}).get('vertical_pair'))
    rear_conf = max(0.0, min(99.0, float((rear_signature or {}).get('confidence', 0.0))))
    if rear_detected and rear_vertical:
        rear_status = 'par_vertical'
    elif rear_detected:
        rear_status = 'par_detectado'
    elif str(view_type) == 'frontal':
        rear_status = 'limitado_vista_frontal'
    else:
        rear_status = 'nao_detectado'
    components['lanternas_traseiras'] = {
        'rotulo': labels['lanternas_traseiras'],
        'status': rear_status,
        'confianca': round(float(rear_conf), 1),
        'detalhe': f'componentes {int((rear_signature or {}).get("components_detected", 0))}',
    }

    # Linhas de portas (projecao vertical em bordas)
    focus_edges = cv2.Canny(gray_focus, 65, 170)
    col_profile = np.mean(focus_edges > 0, axis=0) if focus_edges.size else np.array([])
    min_col = int(len(col_profile) * 0.16) if len(col_profile) else 0
    max_col = int(len(col_profile) * 0.86) if len(col_profile) else 0
    sliced_cols = col_profile[min_col:max_col] if max_col > min_col else col_profile
    door_peaks, door_peak_level = _count_projection_peaks(sliced_cols, threshold_scale=1.20, min_gap=7)
    door_conf = max(0.0, min(99.0, (door_peaks * 18.0) + (door_peak_level * 62.0)))
    if door_peaks >= 2:
        door_status = 'vincos_visiveis'
    elif door_peaks == 1:
        door_status = 'linha_parcial'
    else:
        door_status = 'indefinido'
    components['linhas_portas'] = {
        'rotulo': labels['linhas_portas'],
        'status': door_status,
        'confianca': round(float(door_conf), 1),
        'detalhe': f'picos estruturais {door_peaks}',
    }

    # Capo dianteiro (linhas horizontais na metade superior central)
    hood_density = _edge_density_in_box(gray_scene, 0.20, 0.14, 0.80, 0.46)
    hood_roi = gray_scene[int(gray_scene.shape[0] * 0.14):int(gray_scene.shape[0] * 0.46), int(gray_scene.shape[1] * 0.20):int(gray_scene.shape[1] * 0.80)]
    hood_edges = cv2.Canny(hood_roi, 62, 165) if hood_roi.size else np.array([])
    hood_row = np.mean(hood_edges > 0, axis=1) if getattr(hood_edges, 'size', 0) else np.array([])
    hood_peaks, _ = _count_projection_peaks(hood_row, threshold_scale=1.10, min_gap=5)
    hood_conf = max(0.0, min(99.0, (hood_density * 4.2) + (hood_peaks * 15.0)))
    if rear_view:
        hood_status = 'nao_aplicavel_vista_traseira'
        hood_conf = 0.0
    elif hood_peaks >= 1 and hood_density >= 1.0:
        hood_status = 'linha_detectada'
    elif hood_density >= 0.7:
        hood_status = 'sinal_fraco'
    else:
        hood_status = 'indefinido'
    components['capo_dianteiro'] = {
        'rotulo': labels['capo_dianteiro'],
        'status': hood_status,
        'confianca': round(float(hood_conf), 1),
        'detalhe': f'densidade {round(hood_density, 2)} | picos {hood_peaks}',
    }

    # Tampa traseira (linhas horizontais no tercio inferior central)
    trunk_density = _edge_density_in_box(gray_scene, 0.18, 0.52, 0.82, 0.90)
    trunk_roi = gray_scene[int(gray_scene.shape[0] * 0.52):int(gray_scene.shape[0] * 0.90), int(gray_scene.shape[1] * 0.18):int(gray_scene.shape[1] * 0.82)]
    trunk_edges = cv2.Canny(trunk_roi, 62, 165) if trunk_roi.size else np.array([])
    trunk_row = np.mean(trunk_edges > 0, axis=1) if getattr(trunk_edges, 'size', 0) else np.array([])
    trunk_peaks, _ = _count_projection_peaks(trunk_row, threshold_scale=1.10, min_gap=5)
    trunk_conf = max(0.0, min(99.0, (trunk_density * 4.2) + (trunk_peaks * 15.0)))
    if str(view_type) == 'frontal' and trunk_conf < 70.0:
        trunk_status = 'limitado_vista_frontal'
    elif trunk_peaks >= 1 and trunk_density >= 1.0:
        trunk_status = 'linha_detectada'
    elif trunk_density >= 0.7:
        trunk_status = 'sinal_fraco'
    else:
        trunk_status = 'indefinido'
    components['tampa_traseira'] = {
        'rotulo': labels['tampa_traseira'],
        'status': trunk_status,
        'confianca': round(float(trunk_conf), 1),
        'detalhe': f'densidade {round(trunk_density, 2)} | picos {trunk_peaks}',
    }

    # Design de carroceria (proporcao global)
    aspect_ratio = float((geometry_profile or {}).get('vehicle_aspect_ratio', 0.0))
    compact_vehicle = bool((geometry_profile or {}).get('compact_vehicle'))
    symmetry = float((geometry_profile or {}).get('frontal_symmetry', 0.0))
    if compact_vehicle and aspect_ratio > 0 and aspect_ratio <= 1.95:
        body_status = 'hatch_compacto'
    elif aspect_ratio >= 2.05:
        body_status = 'perfil_longo'
    elif aspect_ratio > 0:
        body_status = 'intermediario'
    else:
        body_status = 'indefinido'
    body_conf = max(0.0, min(99.0, (symmetry * 0.45) + (12.0 if compact_vehicle else 0.0)))
    components['design_carroceria'] = {
        'rotulo': labels['design_carroceria'],
        'status': body_status,
        'confianca': round(float(body_conf), 1),
        'detalhe': f'aspect {round(aspect_ratio, 3)} | simetria {round(symmetry, 1)}',
    }

    assessed = len(components)
    detected = 0
    summary_lines = []
    for key in (
        'emblema_frontal',
        'grade_dianteira',
        'farois_dianteiros',
        'lanternas_traseiras',
        'linhas_portas',
        'capo_dianteiro',
        'tampa_traseira',
        'design_carroceria',
    ):
        item = components.get(key, {})
        if not isinstance(item, dict):
            continue
        conf = float(item.get('confianca', 0.0))
        status = str(item.get('status', 'indefinido'))
        if conf >= 50.0 and status not in ('nao_detectado', 'indefinido') and not status.startswith(('nao_aplicavel', 'limitado_')):
            detected += 1
        summary_lines.append(
            f"{labels.get(key, key)}: {status} ({round(conf, 1)}%) - {str(item.get('detalhe', '')).strip()}"
        )

    coverage = (float(detected) / max(1.0, float(assessed))) * 100.0 if assessed else 0.0
    return {
        'componentes': components,
        'itens_avaliados': int(assessed),
        'itens_detectados': int(detected),
        'cobertura_percentual': round(float(coverage), 1),
        'resumo_lista': summary_lines,
    }


def _build_vehicle_hypotheses(color_profile, emblem_profile, geometry_profile, rear_signature, view_type):
    color_name = str((color_profile or {}).get('color_name', 'indefinida'))
    red_like = color_name in ('vermelha', 'vinho/roxa')
    emblem_detected = bool((emblem_profile or {}).get('detected'))
    emblem_shape = str((emblem_profile or {}).get('shape', 'indefinido'))
    emblem_color = str((emblem_profile or {}).get('color_hint', 'indefinida'))
    compact_vehicle = bool((geometry_profile or {}).get('compact_vehicle'))
    dual_headlamps = bool((geometry_profile or {}).get('dual_headlamps'))
    grille_density = float((geometry_profile or {}).get('grille_edge_density', 0.0))
    symmetry = float((geometry_profile or {}).get('frontal_symmetry', 0.0))
    rear_detected = bool((rear_signature or {}).get('detected'))
    rear_vertical_pair = bool((rear_signature or {}).get('vertical_pair'))
    rear_conf = float((rear_signature or {}).get('confidence', 0.0))
    rear_pair_score = float((rear_signature or {}).get('pair_score', 0.0))
    rear_components = int((rear_signature or {}).get('components_detected', 0))
    rear_view = str(view_type or 'indefinida') == 'traseira'
    frontal_view = str(view_type or 'indefinida') == 'frontal'

    catalog = [
        {'fabricante': 'FIAT', 'modelo': 'Mobi', 'faixa_ano_modelo': '2017-Atual'},
        {'fabricante': 'FIAT', 'modelo': 'Argo', 'faixa_ano_modelo': '2017-Atual'},
        {'fabricante': 'FIAT', 'modelo': 'Uno', 'faixa_ano_modelo': '2010-2021'},
        {'fabricante': 'CHEVROLET', 'modelo': 'Onix', 'faixa_ano_modelo': '2013-Atual'},
        {'fabricante': 'RENAULT', 'modelo': 'Kwid', 'faixa_ano_modelo': '2017-Atual'},
        {'fabricante': 'VOLKSWAGEN', 'modelo': 'Gol', 'faixa_ano_modelo': '2008-2023'},
        {'fabricante': 'HYUNDAI', 'modelo': 'HB20', 'faixa_ano_modelo': '2012-Atual'},
        {'fabricante': 'FORD', 'modelo': 'Ka', 'faixa_ano_modelo': '2014-2021'},
    ]

    ranked = []
    for item in catalog:
        score = 24.0 if frontal_view else 18.0
        evidences = []
        fabricante = item['fabricante']
        modelo = item['modelo']

        if frontal_view and symmetry >= 47:
            score += 7.0
            evidences.append('frontal_simetrica')
        if frontal_view and dual_headlamps:
            score += 8.0
            evidences.append('farois_duplos_detectados')
        if compact_vehicle:
            score += 8.0 if frontal_view else 4.0
            evidences.append('proporcao_compacta')
        if frontal_view and 2.0 <= grille_density <= 15.0:
            score += 5.0
            evidences.append('grade_central_presente')

        if fabricante == 'FIAT':
            if emblem_detected and emblem_shape in ('circular', 'oval'):
                score += 8.0 if rear_view else 18.0
                evidences.append('emblema_central_circular_ou_oval')
            if emblem_detected and emblem_color in ('vermelha', 'prata', 'cinza'):
                score += 5.0 if rear_view else 12.0
                evidences.append('cor_emblema_compativel_fiat')
            if red_like and not rear_view:
                score += 4.0
                evidences.append('cor_veiculo_vermelha')
        else:
            if emblem_detected and emblem_shape in ('circular', 'oval') and not rear_view:
                score += 6.0

        if rear_view:
            if rear_detected and rear_vertical_pair:
                if modelo in ('Uno', 'Mobi'):
                    score += 15.0
                    evidences.append('lanternas_traseiras_verticais_laterais')
                    score += min(5.0, rear_conf * 0.08)
                else:
                    score -= 4.0
            elif rear_detected and rear_components >= 2:
                score += 8.0
                evidences.append('assinatura_traseira_parcial')
            elif rear_detected:
                score += 4.0
            else:
                score -= 3.0
        else:
            if rear_detected and rear_vertical_pair:
                if modelo in ('Uno', 'Mobi'):
                    score += 12.0
                    evidences.append('lanternas_traseiras_verticais_laterais')
                else:
                    score -= 2.0
            elif rear_detected and rear_components >= 2:
                score += 6.0
                evidences.append('assinatura_traseira_parcial')
            elif rear_detected:
                score += 3.0

        if modelo == 'Mobi':
            if rear_view:
                score -= 4.5
            else:
                if compact_vehicle:
                    score += 10.0 if frontal_view else 4.0
                if dual_headlamps and frontal_view:
                    score += 6.0
                if 3.0 <= grille_density <= 14.0 and frontal_view:
                    score += 8.0
        elif modelo in ('Kwid', 'Ka', 'HB20'):
            if rear_view:
                score -= 2.5
            elif compact_vehicle:
                score += 7.0
        elif modelo == 'Onix':
            if rear_view:
                score -= 2.0
            elif grille_density >= 4.0 and frontal_view:
                score += 5.0
        elif modelo == 'Gol':
            if rear_view:
                score -= 2.0
            elif grille_density >= 5.0 and frontal_view:
                score += 4.0

        if not frontal_view and compact_vehicle and not rear_detected:
            score += 4.0
            evidences.append('hatch_compacto_classico')

        if rear_view:
            score += 4.0

        # Compressao de score para reduzir excesso de confianca em sinais genericos.
        score = 10.0 + (float(score) * 0.76)
        score = max(0.0, min(96.0, score))
        ranked.append({
            'fabricante': fabricante,
            'modelo': modelo,
            'faixa_ano_modelo': item['faixa_ano_modelo'],
            'confianca': round(float(score), 1),
            'evidencias': evidences[:5],
        })

    ranked.sort(key=lambda entry: float(entry.get('confianca', 0)), reverse=True)
    top = ranked[:VISUAL_PROFILE_TOP_HYPOTHESES]

    # Complemento em base aberta: valida faixa de ano apenas quando ha sinal discriminativo de modelo.
    if top and float(top[0].get('confianca', 0)) >= 55.0:
        top_evidences = top[0].get('evidencias', [])
        if not isinstance(top_evidences, list):
            top_evidences = []
        discriminative_tags = {
            'lanternas_traseiras_verticais_laterais',
            'lanterna_traseira_compativel_hatch',
            'assinatura_traseira_parcial',
            'assinatura_traseira_compativel_compacto',
            'hatch_compacto_classico',
        }
        top_discriminative = sum(1 for item in top_evidences if str(item) in discriminative_tags)
    else:
        top_discriminative = 0

    if top and float(top[0].get('confianca', 0)) >= 55.0 and top_discriminative >= 1:
        fipe_data = _fetch_fipe_year_range(top[0].get('fabricante', ''), top[0].get('modelo', ''))
        if isinstance(fipe_data, dict) and fipe_data.get('faixa_ano_modelo'):
            top[0]['faixa_ano_modelo'] = str(fipe_data.get('faixa_ano_modelo'))
            top[0]['fonte_faixa_ano'] = 'FIPE API aberta'
            top[0]['fipe_referencia'] = str(fipe_data.get('fipe_referencia', ''))
            model_match = str(fipe_data.get('fipe_modelo_match', ''))
            if model_match:
                top[0]['modelo_match_base_aberta'] = model_match

    return top


def analyze_vehicle_visual_profile(photo_img):
    if not VISUAL_PROFILE_ENABLED:
        return {
            'status': 'disabled',
            'message': 'visual_profile_disabled',
            'fontes': [],
        }

    if photo_img is None or getattr(photo_img, 'size', 0) == 0:
        return {
            'status': 'unavailable',
            'message': 'imagem_indisponivel',
            'fontes': [],
        }

    scene = _resize_for_visual_profile(photo_img)
    vehicle_focus = _extract_vehicle_focus_region(scene)
    color_profile = analyze_color_model(vehicle_focus)
    if color_profile.get('color_name') in ('azul', 'verde') and float(color_profile.get('color_confidence', 0)) < 70.0:
        # Fallback para reduzir viÃƒÂ©s de fundo quando a ROI ÃƒÂ© inconclusiva.
        color_profile = analyze_color_model(scene)
    emblem_profile = _detect_emblem_signature(scene)
    geometry_profile = _analyze_visual_geometry(scene)
    rear_signature = _detect_rear_taillight_signature(vehicle_focus)
    if not bool(rear_signature.get('detected')):
        rear_signature = _detect_rear_taillight_signature(scene)

    rear_conf = float((rear_signature or {}).get('confidence', 0.0))
    rear_pair_score = float((rear_signature or {}).get('pair_score', 0.0))
    rear_priority = bool(rear_signature.get('detected')) and (
        bool(rear_signature.get('vertical_pair'))
        or rear_conf >= 38.0
        or rear_pair_score >= 52.0
    )
    if rear_priority:
        view_type = 'traseira'
    elif bool(emblem_profile.get('detected')) and not bool(rear_signature.get('detected')):
        view_type = 'frontal'
    elif (
        bool((geometry_profile or {}).get('dual_headlamps'))
        and float((geometry_profile or {}).get('frontal_symmetry', 0.0)) >= 42.0
        and 1.5 <= float((geometry_profile or {}).get('grille_edge_density', 0.0)) <= 26.0
        and 1.2 <= float((geometry_profile or {}).get('headlamp_left_density', 0.0)) <= 6.4
        and 1.2 <= float((geometry_profile or {}).get('headlamp_right_density', 0.0)) <= 6.4
        and abs(
            float((geometry_profile or {}).get('headlamp_left_density', 0.0))
            - float((geometry_profile or {}).get('headlamp_right_density', 0.0))
        ) <= 2.8
    ):
        view_type = 'frontal'
    else:
        view_type = 'indefinida'

    # Filtro de Contexto: Avalia se estamos vendo o carro ou apenas a placa por um crop aproximado.
    plate_area_ratio = 0.0
    if isinstance(vehicle_focus, np.ndarray) and scene.size > 0:
        plate_area_ratio = float(vehicle_focus.size) / float(scene.size)

    # Se a placa ocupar mais de 35% da imagem, consideramos close-up/low-context.
    low_context = plate_area_ratio >= 0.35

    component_profile = _analyze_vehicle_component_signatures(
        scene,
        vehicle_focus,
        view_type,
        emblem_profile,
        rear_signature,
        geometry_profile,
        low_context=low_context
    )
    forensic_traits = _detect_forensic_vehicle_traits(
        scene,
        vehicle_focus,
        view_type,
        color_profile,
        component_profile,
    )
    hypotheses = _build_vehicle_hypotheses(color_profile, emblem_profile, geometry_profile, rear_signature, view_type)
    principal_raw = hypotheses[0] if hypotheses else {}
    principal, hypotheses, model_quality = _apply_visual_model_abstention(
        hypotheses,
        component_profile=component_profile,
        view_type=view_type,
        rear_signature=rear_signature,
    )

    principal_conf = float(principal.get('confianca', 0)) if isinstance(principal, dict) else 0.0
    status = 'ok' if principal_conf >= VISUAL_PROFILE_MIN_CONFIDENCE else 'low_confidence'
    if isinstance(model_quality, dict) and bool(model_quality.get('model_abstained')):
        status = 'review_required'
    open_comparison = _build_open_source_comparison(
        principal,
        hypotheses,
        rear_signature,
        component_profile=component_profile,
        view_type=view_type,
        forensic_traits=forensic_traits,
    )
    evidence_matrix = _build_visual_evidence_matrix(
        hypotheses,
        component_profile=component_profile,
        geometry_profile=geometry_profile,
        rear_signature=rear_signature,
        view_type=view_type,
    )

    fontes = ['analise_visual_local_heuristica']
    if principal.get('fonte_faixa_ano') == 'FIPE API aberta':
        fontes.append('FIPE API aberta (fipe.parallelum.com.br)')
    if isinstance(open_comparison, dict) and open_comparison.get('fontes'):
        fontes.append('consultas_abertas_multiplas_fontes')

    observacoes = []
    if isinstance(model_quality, dict) and bool(model_quality.get('model_abstained')):
        reasons = model_quality.get('reasons', [])
        if isinstance(reasons, list) and reasons:
            observacoes.append('abstencao_modelo:' + ','.join([str(item) for item in reasons if str(item).strip()]))
        else:
            observacoes.append('abstencao_modelo_por_baixa_evidencia')
    if status == 'low_confidence':
        observacoes.append('perfil_visual_requer_revisao_humana')
    if principal_conf < 55:
        observacoes.append('hipotese_nao_conclusiva')
    if isinstance(forensic_traits, dict) and int(forensic_traits.get('total_achados', 0)) > 0:
        observacoes.append('caracteristicas_forenses_potenciais_detectadas')

    return {
        'status': status,
        'vista_detectada': view_type,
        'fabricante': str(principal.get('fabricante', '') or ''),
        'modelo': str(principal.get('modelo', '') or ''),
        'faixa_ano_modelo': str(principal.get('faixa_ano_modelo', '') or ''),
        'confianca': round(float(principal_conf), 1),
        'cor_probavel': color_profile.get('color_name', 'indefinida'),
        'confianca_cor': round(float(color_profile.get('color_confidence', 0.0)), 1),
        'cores_alternativas': color_profile.get('top_colors', []),
        'emblema': emblem_profile,
        'lanterna_traseira': rear_signature,
        'geometria': geometry_profile,
        'assinaturas_componentes': component_profile,
        'caracteristicas_forenses': forensic_traits,
        'qualidade_modelo': model_quality,
        'hipotese_principal': principal,
        'hipotese_principal_bruta': principal_raw,
        'hipoteses': hypotheses,
        'comparativo_fontes_abertas': open_comparison,
        'matriz_evidencias': evidence_matrix,
        'fontes': fontes,
        'observacoes': observacoes,
    }


def detect_adulteration(plate_img):
    return False


def build_char_options(ocr_results):
    char_options = {}
    for result in ocr_results.values():
        for char, conf in result.get('chars', []):
            if char not in char_options or conf > char_options[char]:
                char_options[char] = conf
    return sorted(char_options.items(), key=lambda item: -item[1])


def build_partial_plate_evidence(ocr_results, top_candidates=None, plate_detection=None, context=None, max_candidates=8):
    context = context if isinstance(context, dict) else {}
    if isinstance(plate_detection, dict) and plate_detection:
        context = dict(context)
        context.setdefault('plate_detection_style_hint', plate_detection.get('selected_style_hint') or plate_detection.get('style_hint') or '')
        context.setdefault('plate_detection_region', plate_detection.get('ocr_selected_region') or plate_detection.get('selected_region') or '')

    candidates = build_partial_plate_candidates(
        ocr_results,
        top_candidates=top_candidates,
        context=context,
        max_candidates=max_candidates,
    )
    overview = build_partial_plate_overview(candidates, limit=min(4, max(1, int(max_candidates or 8))))
    return {
        'partial_plate_candidates': candidates,
        'partial_plate_candidates_count': len(candidates),
        'partial_plate_has_evidence': bool(overview.get('has_partial')),
        'partial_plate_text': overview.get('primary_text', '-') or '-',
        'partial_plate_summary': overview.get('summary', '-') or '-',
        'partial_plate_top_candidates': overview.get('top_candidates', []),
    }


def clamp_value(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def plate_crop_pad_ratio(short_side, base_ratio=PLATE_CROP_PAD_RATIO):
    short_side = float(short_side or 0.0)
    if short_side <= 60.0:
        adjusted = base_ratio + PLATE_CROP_PAD_RATIO_SMALL
    elif short_side <= 120.0:
        adjusted = base_ratio + (PLATE_CROP_PAD_RATIO_SMALL * 0.55)
    elif short_side >= 260.0:
        adjusted = base_ratio + PLATE_CROP_PAD_RATIO_LARGE
    else:
        adjusted = base_ratio
    return clamp_value(adjusted, 0.03, 0.18)


def compute_tesseract_dynamic_weight(base_weight, result, source_candidates):
    tesseract_profile = ocr_reranking_calibration_lookup('engine_profiles', 'tesseract', default={})
    if not isinstance(tesseract_profile, dict):
        tesseract_profile = {}
    factor_min = parse_float(tesseract_profile.get('factor_min', TESSERACT_DYNAMIC_WEIGHT_MIN), TESSERACT_DYNAMIC_WEIGHT_MIN)
    factor_max = max(factor_min, parse_float(tesseract_profile.get('factor_max', TESSERACT_DYNAMIC_WEIGHT_MAX), TESSERACT_DYNAMIC_WEIGHT_MAX))
    accept_conf = parse_float(tesseract_profile.get('accept_conf', TESSERACT_MIN_ACCEPT_CONF), TESSERACT_MIN_ACCEPT_CONF)
    accept_score = parse_float(tesseract_profile.get('accept_score', TESSERACT_MIN_ACCEPT_SCORE), TESSERACT_MIN_ACCEPT_SCORE)
    pattern_score = parse_float(tesseract_profile.get('pattern_score', TESSERACT_PATTERN_MIN_SCORE), TESSERACT_PATTERN_MIN_SCORE)
    details = {
        'mode': 'fixed',
        'base_weight': round(float(base_weight), 4),
        'dynamic_weight': round(float(base_weight), 4),
        'dynamic_factor': 1.0,
        'quality': 1.0,
        'reason': 'not_applicable',
    }
    if not TESSERACT_DYNAMIC_WEIGHT_ENABLE:
        details['reason'] = 'disabled_by_env'
        return float(base_weight), details

    merged_by_text = {}
    for candidate in source_candidates[:ENSEMBLE_TOP_PER_ENGINE]:
        if not isinstance(candidate, dict):
            continue
        text = normalize_plate_text(candidate.get('text', ''))
        if len(text) < 5 or len(text) > 8:
            continue
        score = parse_float(candidate.get('score', result.get('score', 0)), 0.0)
        avg_conf = parse_float(candidate.get('avg_conf', result.get('avg_conf', 0)), 0.0)
        pattern = candidate.get('pattern', detect_plate_pattern(text))
        hits = max(1, int(parse_int(candidate.get('hits', result.get('hits', 1)), 1)))
        current = {
            'text': text,
            'score': float(score),
            'avg_conf': float(avg_conf),
            'pattern': pattern,
            'hits': hits,
        }
        previous = merged_by_text.get(text)
        if previous is None:
            merged_by_text[text] = current
            continue

        previous['score'] = max(float(previous.get('score', 0.0)), float(current.get('score', 0.0)))
        previous['avg_conf'] = max(float(previous.get('avg_conf', 0.0)), float(current.get('avg_conf', 0.0)))
        previous['hits'] = max(int(previous.get('hits', 1)), int(current.get('hits', 1)))
        if str(previous.get('pattern', 'Indefinido')) == 'Indefinido' and str(current.get('pattern', 'Indefinido')) != 'Indefinido':
            previous['pattern'] = current['pattern']

    ranked = list(merged_by_text.values())

    if not ranked:
        factor = factor_min
        dynamic_weight = float(base_weight) * float(factor)
        details.update({
            'mode': 'noisy',
            'dynamic_weight': round(dynamic_weight, 4),
            'dynamic_factor': round(float(factor), 4),
            'quality': 0.0,
            'reason': 'no_valid_candidates',
        })
        return dynamic_weight, details

    ranked.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    gap = float(top.get('score', 0.0)) - float(second.get('score', 0.0)) if second else 18.0

    pattern_quality = 1.0 if str(top.get('pattern', 'Indefinido')) != 'Indefinido' else 0.28
    conf_quality = clamp_value(float(top.get('avg_conf', 0.0)) / max(1.0, float(accept_conf)), 0.0, 1.0)
    score_quality = clamp_value(
        float(top.get('score', 0.0)) / max(1.0, float(pattern_score + 24.0)),
        0.0,
        1.0,
    )
    hits_quality = clamp_value(float(top.get('hits', 1)) / 3.0, 0.0, 1.0)
    gap_quality = clamp_value(float(gap) / 16.0, 0.0, 1.0)
    unique_top = len({item.get('text', '') for item in ranked[:3] if item.get('text')})
    diversity_penalty = clamp_value(max(0.0, float(unique_top - 1) * 0.11), 0.0, 0.35)

    quality = (
        (pattern_quality * 0.30)
        + (conf_quality * 0.22)
        + (score_quality * 0.20)
        + (hits_quality * 0.16)
        + (gap_quality * 0.12)
    ) - diversity_penalty
    quality = clamp_value(float(quality), 0.0, 1.0)

    warning = str(result.get('warning', '') or '').lower()
    mode = 'normal'
    reason = 'stable'
    if 'low_reliability' in warning or 'abstained' in warning:
        quality *= 0.38
        mode = 'noisy'
        reason = 'tesseract_warning_low_reliability'
    elif (
        str(top.get('pattern', 'Indefinido')) == 'Indefinido'
        or float(top.get('avg_conf', 0.0)) < float(accept_conf)
        or float(top.get('score', 0.0)) < float(accept_score)
    ):
        quality *= 0.62
        mode = 'noisy'
        reason = 'weak_top_candidate'

    if not normalize_plate_text(result.get('text', '')):
        quality *= 0.84
        if mode == 'normal':
            mode = 'soft_noisy'
            reason = 'no_primary_text'

    quality = clamp_value(float(quality), 0.0, 1.0)
    factor_range = float(factor_max - factor_min)
    factor = float(factor_min) + (quality * factor_range)
    factor = clamp_value(float(factor), float(factor_min), float(factor_max))
    dynamic_weight = float(base_weight) * float(factor)

    details.update({
        'mode': mode,
        'dynamic_weight': round(dynamic_weight, 4),
        'dynamic_factor': round(float(factor), 4),
        'quality': round(float(quality), 4),
        'reason': reason,
        'top_score': round(float(top.get('score', 0.0)), 2),
        'top_conf': round(float(top.get('avg_conf', 0.0)), 2),
        'top_hits': int(top.get('hits', 1)),
        'gap_top2': round(float(gap), 2),
        'warning': warning,
    })
    return dynamic_weight, details


def get_engine_weight_profile(engine):
    engine_key = str(engine or '').strip().lower()
    profile = {
        'name': engine_key or 'generic',
        'factor_min': TESSERACT_DYNAMIC_WEIGHT_MIN,
        'factor_max': TESSERACT_DYNAMIC_WEIGHT_MAX,
        'accept_conf': OCR_MIN_CONFIDENCE,
        'accept_score': max(35.0, OCR_MIN_CONFIDENCE - 10.0),
        'pattern_score': OCR_MIN_CONFIDENCE + 22.0,
        'min_hits': 2,
        'min_variant_hits': 1,
        'gap_scale': 16.0,
        'warning_penalty': 0.86,
        'error_penalty': 0.72,
        'low_reliability_penalty': 0.58,
        'no_text_penalty': 0.84,
        'weak_pattern_penalty': 0.68,
        'reliability_boost': 0.06,
        'reliability_checker': None,
    }

    if engine_key == 'easyocr':
        profile.update({
            'name': 'easyocr',
            'factor_min': 0.18,
            'factor_max': 1.04,
            'accept_conf': EASYOCR_MIN_ACCEPT_CONF,
            'accept_score': EASYOCR_MIN_ACCEPT_SCORE,
            'pattern_score': EASYOCR_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': EASYOCR_MIN_VARIANT_HITS,
            'gap_scale': 14.0,
            'reliability_boost': 0.07,
            'reliability_checker': is_easyocr_candidate_reliable,
        })
    elif engine_key == 'rapidocr':
        profile.update({
            'name': 'rapidocr',
            'factor_min': 0.18,
            'factor_max': 1.03,
            'accept_conf': RAPIDOCR_MIN_ACCEPT_CONF,
            'accept_score': RAPIDOCR_MIN_ACCEPT_SCORE,
            'pattern_score': RAPIDOCR_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': RAPIDOCR_MIN_VARIANT_HITS,
            'gap_scale': 14.0,
            'reliability_boost': 0.07,
            'reliability_checker': is_rapidocr_candidate_reliable,
        })
    elif engine_key == 'trocr':
        profile.update({
            'name': 'trocr',
            'factor_min': 0.20,
            'factor_max': 1.05,
            'accept_conf': TROCR_MIN_ACCEPT_CONF,
            'accept_score': TROCR_MIN_ACCEPT_SCORE,
            'pattern_score': TROCR_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': TROCR_MIN_VARIANT_HITS,
            'gap_scale': 15.0,
            'reliability_boost': 0.08,
            'reliability_checker': is_trocr_candidate_reliable,
        })
    elif engine_key == 'doctr':
        profile.update({
            'name': 'doctr',
            'factor_min': 0.20,
            'factor_max': 1.03,
            'accept_conf': DOCTR_MIN_ACCEPT_CONF,
            'accept_score': DOCTR_MIN_ACCEPT_SCORE,
            'pattern_score': DOCTR_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': DOCTR_MIN_VARIANT_HITS,
            'gap_scale': 15.0,
            'reliability_boost': 0.08,
            'reliability_checker': is_doctr_candidate_reliable,
        })
    elif engine_key == 'paddleocr':
        profile.update({
            'name': 'paddleocr',
            'factor_min': 0.18,
            'factor_max': 1.04,
            'accept_conf': PADDLEOCR_MIN_ACCEPT_CONF,
            'accept_score': PADDLEOCR_MIN_ACCEPT_SCORE,
            'pattern_score': PADDLEOCR_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': PADDLEOCR_MIN_VARIANT_HITS,
            'gap_scale': 14.0,
            'reliability_boost': 0.07,
            'reliability_checker': is_paddleocr_candidate_reliable,
        })
    elif engine_key == 'plate_recognizer':
        profile.update({
            'name': 'plate_recognizer',
            'factor_min': 0.24,
            'factor_max': 1.10,
            'accept_conf': PLATE_RECOGNIZER_MIN_ACCEPT_CONF,
            'accept_score': PLATE_RECOGNIZER_MIN_ACCEPT_SCORE,
            'pattern_score': PLATE_RECOGNIZER_PATTERN_MIN_SCORE,
            'min_hits': 2,
            'min_variant_hits': PLATE_RECOGNIZER_MIN_VARIANT_HITS,
            'gap_scale': 12.0,
            'reliability_boost': 0.09,
            'reliability_checker': is_plate_recognizer_candidate_reliable,
        })
    elif engine_key == 'pdf_probe':
        profile.update({
            'name': 'pdf_probe',
            'factor_min': 0.14,
            'factor_max': 0.92,
            'accept_conf': 42.0,
            'accept_score': 52.0,
            'pattern_score': 60.0,
            'min_hits': 1,
            'min_variant_hits': 1,
            'gap_scale': 18.0,
            'reliability_boost': 0.04,
            'no_text_penalty': 0.90,
            'weak_pattern_penalty': 0.76,
            'reliability_checker': None,
        })

    calibration_profiles = ocr_reranking_calibration_lookup('engine_profiles', default={})
    if isinstance(calibration_profiles, dict):
        generic_overlay = calibration_profiles.get('generic') or calibration_profiles.get('default') or calibration_profiles.get('all')
        if isinstance(generic_overlay, dict):
            profile.update(generic_overlay)
        engine_overlay = calibration_profiles.get(engine_key)
        if isinstance(engine_overlay, dict):
            profile.update(engine_overlay)

    return profile


def compute_engine_dynamic_weight(base_weight, engine, result, source_candidates):
    profile = get_engine_weight_profile(engine)
    details = {
        'mode': 'fixed',
        'base_weight': round(float(base_weight), 4),
        'dynamic_weight': round(float(base_weight), 4),
        'dynamic_factor': 1.0,
        'quality': 1.0,
        'reason': 'not_applicable',
        'profile': profile.get('name', 'generic'),
    }

    ranked = []
    merged_by_text = {}
    for candidate in source_candidates[:max(1, ENSEMBLE_TOP_PER_ENGINE)]:
        if not isinstance(candidate, dict):
            continue
        text = normalize_plate_text(candidate.get('text', ''))
        if len(text) < 5 or len(text) > 8:
            continue
        score = parse_float(candidate.get('score', result.get('score', 0)), 0.0)
        avg_conf = parse_float(candidate.get('avg_conf', result.get('avg_conf', 0)), 0.0)
        pattern = candidate.get('pattern', detect_plate_pattern(text))
        hits = max(1, int(parse_int(candidate.get('hits', result.get('hits', 1)), 1)))
        variant_hits = max(1, int(parse_int(candidate.get('variant_hits', result.get('variant_hits', 1)), 1)))
        score_gap_top2 = parse_float(candidate.get('score_gap_top2', result.get('score_gap_top2', 99.0)), 99.0)
        current = {
            'text': text,
            'score': float(score),
            'avg_conf': float(avg_conf),
            'pattern': pattern,
            'hits': hits,
            'variant_hits': variant_hits,
            'score_gap_top2': float(score_gap_top2),
        }
        previous = merged_by_text.get(text)
        if previous is None:
            merged_by_text[text] = current
            continue

        previous['score'] = max(float(previous.get('score', 0.0)), float(current.get('score', 0.0)))
        previous['avg_conf'] = max(float(previous.get('avg_conf', 0.0)), float(current.get('avg_conf', 0.0)))
        previous['hits'] = max(int(previous.get('hits', 1)), int(current.get('hits', 1)))
        previous['variant_hits'] = max(int(previous.get('variant_hits', 1)), int(current.get('variant_hits', 1)))
        previous['score_gap_top2'] = max(float(previous.get('score_gap_top2', 0.0)), float(current.get('score_gap_top2', 0.0)))
        if str(previous.get('pattern', 'Indefinido')) == 'Indefinido' and str(current.get('pattern', 'Indefinido')) != 'Indefinido':
            previous['pattern'] = current['pattern']

    ranked = list(merged_by_text.values())
    if not ranked:
        factor = float(profile.get('factor_min', TESSERACT_DYNAMIC_WEIGHT_MIN))
        dynamic_weight = float(base_weight) * float(factor)
        details.update({
            'mode': 'noisy',
            'dynamic_weight': round(dynamic_weight, 4),
            'dynamic_factor': round(float(factor), 4),
            'quality': 0.0,
            'reason': 'no_valid_candidates',
        })
        return dynamic_weight, details

    ranked.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    gap = float(top.get('score', 0.0)) - float(second.get('score', 0.0)) if second else 18.0

    top_text = normalize_plate_text(top.get('text', ''))
    top_conf = float(top.get('avg_conf', 0.0))
    top_score = float(top.get('score', 0.0))
    top_hits = int(top.get('hits', 1))
    top_variant_hits = int(top.get('variant_hits', 1))
    pattern = str(top.get('pattern', 'Indefinido'))
    pattern_quality = 1.0 if pattern != 'Indefinido' else 0.24
    conf_quality = clamp_value(top_conf / max(1.0, float(profile.get('accept_conf', OCR_MIN_CONFIDENCE))), 0.0, 1.0)
    score_target = max(float(profile.get('pattern_score', OCR_MIN_CONFIDENCE + 22.0)), float(profile.get('accept_score', OCR_MIN_CONFIDENCE - 10.0)) + 18.0)
    score_quality = clamp_value(top_score / max(1.0, score_target), 0.0, 1.0)
    hits_quality = clamp_value(top_hits / max(1.0, float(profile.get('min_hits', 2)) + 1.0), 0.0, 1.0)
    variant_quality = clamp_value(top_variant_hits / max(1.0, float(profile.get('min_variant_hits', 1)) + 1.0), 0.0, 1.0)
    gap_quality = clamp_value(gap / max(8.0, float(profile.get('gap_scale', 16.0))), 0.0, 1.0)

    support_texts = [normalize_plate_text(candidate.get('text', '')) for candidate in source_candidates if normalize_plate_text(candidate.get('text', ''))]
    vote_counter = Counter(support_texts)
    total_votes = len(support_texts)
    top_votes = int(vote_counter.get(top_text, 0))
    consensus_ratio = float(top_votes) / max(1.0, float(total_votes))
    consensus_quality = clamp_value(consensus_ratio, 0.0, 1.0)
    unique_support = len(vote_counter)

    quality = (
        (pattern_quality * 0.24)
        + (conf_quality * 0.20)
        + (score_quality * 0.18)
        + (hits_quality * 0.13)
        + (variant_quality * 0.10)
        + (gap_quality * 0.08)
        + (consensus_quality * 0.07)
    )

    if len(top_text) == 7:
        quality += 0.04
    else:
        quality -= 0.05

    reliability_checker = profile.get('reliability_checker')
    reliable_anchor = False
    if callable(reliability_checker):
        try:
            reliable_anchor = bool(reliability_checker({
                'text': top_text,
                'score': top_score,
                'avg_conf': top_conf,
                'pattern': pattern,
                'hits': top_hits,
                'variant_hits': top_variant_hits,
                'score_gap_top2': gap,
            }))
        except Exception:
            reliable_anchor = False
    if reliable_anchor:
        quality = min(1.0, quality + float(profile.get('reliability_boost', 0.06)))

    warning = str(result.get('warning', '') or '').lower()
    error = str(result.get('error', '') or '').lower()
    mode = 'normal'
    reason = 'stable'

    if warning or error:
        quality *= float(profile.get('warning_penalty', 0.86))
        mode = 'noisy'
        reason = 'engine_warning'
    if 'low_reliability' in warning or 'abstained' in warning:
        quality *= float(profile.get('low_reliability_penalty', 0.58))
        mode = 'noisy'
        reason = 'engine_warning_low_reliability'
    if error:
        quality *= float(profile.get('error_penalty', 0.72))
        mode = 'noisy'
        reason = 'engine_error'
    if not top_text:
        quality *= float(profile.get('no_text_penalty', 0.84))
        if mode == 'normal':
            mode = 'soft_noisy'
            reason = 'no_primary_text'
    if pattern == 'Indefinido':
        quality *= float(profile.get('weak_pattern_penalty', 0.68))
        if mode == 'normal':
            mode = 'soft_noisy'
            reason = 'pattern_missing'
    if unique_support >= 3:
        quality *= max(0.72, 1.0 - ((unique_support - 2) * 0.06))
        if mode == 'normal' and top_votes <= 1:
            mode = 'soft_noisy'
            reason = 'high_candidate_diversity'
    if total_votes >= 3 and consensus_ratio < 0.45:
        quality *= 0.84
        if mode == 'normal':
            mode = 'soft_noisy'
            reason = 'weak_consensus'

    quality = clamp_value(float(quality), 0.0, 1.0)
    factor_min = float(profile.get('factor_min', TESSERACT_DYNAMIC_WEIGHT_MIN))
    factor_max = max(factor_min, float(profile.get('factor_max', TESSERACT_DYNAMIC_WEIGHT_MAX)))
    factor = factor_min + (quality * (factor_max - factor_min))
    factor = clamp_value(float(factor), factor_min, factor_max)
    dynamic_weight = float(base_weight) * float(factor)

    details.update({
        'mode': mode,
        'dynamic_weight': round(dynamic_weight, 4),
        'dynamic_factor': round(float(factor), 4),
        'quality': round(float(quality), 4),
        'reason': reason,
        'top_score': round(float(top_score), 2),
        'top_conf': round(float(top_conf), 2),
        'top_hits': int(top_hits),
        'top_variant_hits': int(top_variant_hits),
        'gap_top2': round(float(gap), 2),
        'consensus_ratio': round(float(consensus_ratio), 4),
        'candidate_votes': int(total_votes),
        'unique_support': int(unique_support),
        'reliable_anchor': reliable_anchor,
        'warning': warning,
        'error': error,
    })
    return dynamic_weight, details


def resolve_engine_weight(engine, result, source_candidates):
    base_weight = float(ENSEMBLE_WEIGHTS.get(engine, 1.0))
    engine_key = str(engine or '').strip().lower()
    if engine_key == 'tesseract':
        return compute_tesseract_dynamic_weight(base_weight, result, source_candidates)

    return compute_engine_dynamic_weight(base_weight, engine_key, result, source_candidates)


def build_ensemble_candidates(ocr_results, plate_detection=None):
    pool = {}
    engines_considered = 0
    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        ensemble_profile = {}
    style_bias_profile = ocr_ensemble_style_bias_profile()
    style_context = extract_plate_style_context(plate_detection)
    style_hint = str(style_context.get('style_hint', 'indefinida') or 'indefinida').strip().lower()
    style_confidence = clamp_value(float(style_context.get('style_confidence', 0.0)), 0.0, 100.0)
    style_strength = clamp_value(style_confidence / 100.0, 0.0, 1.0)
    style_enabled = bool(style_bias_profile.get('enabled', True))
    style_min_confidence = parse_float(style_bias_profile.get('strong_style_min_confidence', 65.0), 65.0)
    style_match_rank_credit = parse_float(style_bias_profile.get('style_match_rank_credit', 0.55), 0.55)
    style_match_rank_scale = parse_float(style_bias_profile.get('style_match_rank_scale', 0.22), 0.22)
    style_mismatch_rank_penalty = parse_float(style_bias_profile.get('style_mismatch_rank_penalty', 0.60), 0.60)
    style_mismatch_rank_scale = parse_float(style_bias_profile.get('style_mismatch_rank_scale', 0.20), 0.20)
    leading_d_bonus = parse_float(style_bias_profile.get('leading_d_bonus', 7.9), 7.9)
    leading_d_bonus_scale = parse_float(style_bias_profile.get('leading_d_bonus_scale', 0.80), 0.80)
    leading_d_rank_credit = parse_float(style_bias_profile.get('leading_d_rank_credit', 1.0), 1.0)
    leading_d_rank_scale = parse_float(style_bias_profile.get('leading_d_rank_scale', 0.18), 0.18)
    close_conf_margin = parse_float(style_bias_profile.get('close_conf_margin', 5.0), 5.0)
    close_score_margin = parse_float(style_bias_profile.get('close_score_margin', 15.0), 15.0)
    rank_decay_step = parse_float(ensemble_profile.get('rank_decay_step', 0.22), 0.22)
    min_rank_decay = parse_float(ensemble_profile.get('min_rank_decay', 0.25), 0.25)
    pattern_bonus_value = parse_float(ensemble_profile.get('pattern_bonus', 0.90), 0.90)
    pattern_penalty_value = parse_float(ensemble_profile.get('pattern_penalty', -0.60), -0.60)
    length_bonus_value = parse_float(ensemble_profile.get('length_bonus', 0.95), 0.95)
    length_penalty_value = parse_float(ensemble_profile.get('length_penalty', -0.25), -0.25)
    law_component_cap = max(0.25, parse_float(ensemble_profile.get('law_component_cap', 1.35), 1.35))
    score_divisor = max(1.0, parse_float(ensemble_profile.get('score_divisor', 85.0), 85.0))
    score_component_cap = max(0.1, parse_float(ensemble_profile.get('score_component_cap', 2.0), 2.0))
    conf_divisor = max(1.0, parse_float(ensemble_profile.get('conf_divisor', 100.0), 100.0))
    conf_component_cap = max(0.1, parse_float(ensemble_profile.get('conf_component_cap', 1.2), 1.2))
    support_bonus_per_engine = max(0.0, parse_float(ensemble_profile.get('support_bonus_per_engine', 1.35), 1.35))
    support_bonus_cap = max(0.0, parse_float(ensemble_profile.get('support_bonus_cap', 4.05), 4.05))

    for engine, result in ocr_results.items():
        if not isinstance(result, dict):
            continue

        source_candidates = []
        primary_text = normalize_plate_text(result.get('text', ''))
        if is_plate_like_text(primary_text):
            source_candidates.append({
                'text': primary_text,
                'score': result.get('score', result.get('avg_conf', 0)),
                'avg_conf': result.get('avg_conf', 0),
                'pattern': result.get('pattern', detect_plate_pattern(primary_text)),
                'region': result.get('region', 'full_image'),
                'origin': 'primary',
            })

        raw_candidates = result.get('candidates', [])
        if isinstance(raw_candidates, list):
            for candidate in raw_candidates[:ENSEMBLE_TOP_PER_ENGINE]:
                if isinstance(candidate, dict):
                    candidate_text = normalize_plate_text(candidate.get('text', ''))
                    if not is_plate_like_text(candidate_text):
                        continue
                    source_candidates.append(candidate)

        if not source_candidates:
            continue

        engines_considered += 1
        engine_weight, weight_profile = resolve_engine_weight(engine, result, source_candidates)

        for rank, candidate in enumerate(source_candidates[:ENSEMBLE_TOP_PER_ENGINE]):
            text = normalize_plate_text(candidate.get('text', ''))
            if len(text) < 5 or len(text) > 8:
                continue

            pattern = candidate.get('pattern', detect_plate_pattern(text))
            score = parse_float(candidate.get('score', result.get('score', 0)), 0.0)
            avg_conf = parse_float(candidate.get('avg_conf', result.get('avg_conf', 0)), 0.0)
            avg_conf = max(0.0, min(100.0, avg_conf))
            region = candidate.get('region') or result.get('region') or 'full_image'
            law_validation = validate_plate_by_law(text)
            law_score = parse_float(law_validation.get('law_score', 0.0), 0.0)
            law_component = max(0.0, min(law_component_cap, (law_score / 100.0) * law_component_cap))

            rank_decay = max(min_rank_decay, 1.0 - (rank * rank_decay_step))
            pattern_bonus = pattern_bonus_value if pattern != 'Indefinido' else pattern_penalty_value
            length_bonus = length_bonus_value if len(text) == 7 else length_penalty_value
            score_component = max(0.0, min(score_component_cap, score / score_divisor))
            conf_component = max(0.0, min(conf_component_cap, avg_conf / conf_divisor))
            # Context-aware bonus: favor high-precision vision models in zoomed-in crops
            context_bonus = 0.0
            if region != 'full_image' and region is not None:
                region_name = str(region).lower()
                if 'crop' in region_name or 'plate' in region_name:
                    if engine in ('trocr', 'doctr', 'paddleocr'):
                        context_bonus = 0.48
                    elif engine in ('easyocr', 'rapidocr'):
                        context_bonus = 0.22

            style_rank_priority = 0.0
            style_bonus = 0.0
            if style_enabled and style_hint in ('mercosul', 'antigo') and pattern != 'Indefinido':
                expected_pattern = 'Mercosul' if style_hint == 'mercosul' else 'Antigo'
                if pattern == expected_pattern:
                    style_bonus = 0.18 + (style_strength * 0.22)
                    style_rank_priority += style_match_rank_credit + (style_strength * style_match_rank_scale)
                else:
                    style_bonus = -0.14 - (style_strength * 0.26)
                    style_rank_priority -= style_mismatch_rank_penalty + (style_strength * style_mismatch_rank_scale)
            elif style_enabled and style_hint in ('mercosul', 'antigo'):
                style_bonus = -0.04 - (style_strength * 0.04)

            contribution = engine_weight * rank_decay * (score_component + conf_component + pattern_bonus + length_bonus + law_component + context_bonus + style_bonus)

            item = pool.setdefault(text, {
                'text': text,
                'weighted_support': 0.0,
                'best_score': 0.0,
                'best_conf': 0.0,
                'best_law_score': 0.0,
                'engines': set(),
                'regions': set(),
                'engine_contributions': {},
                'engine_weights': {},
                'style_bonus_total': 0.0,
                'style_rank_priority': 0.0,
            })
            item['weighted_support'] += contribution
            item['best_score'] = max(float(item['best_score']), float(score))
            item['best_conf'] = max(float(item['best_conf']), float(avg_conf))
            item['best_law_score'] = max(float(item['best_law_score']), float(law_score))
            item['engines'].add(engine)
            item['regions'].add(str(region))
            item['engine_contributions'][engine] = float(item['engine_contributions'].get(engine, 0.0)) + float(contribution)
            item['style_bonus_total'] += float(style_bonus)
            item['style_rank_priority'] = max(float(item.get('style_rank_priority', 0.0)), float(style_rank_priority))
            item['engine_weights'][engine] = {
                'weight': round(float(weight_profile.get('dynamic_weight', engine_weight)), 4),
                'factor': round(float(weight_profile.get('dynamic_factor', 1.0)), 4),
                'mode': str(weight_profile.get('mode', 'fixed')),
                'reason': str(weight_profile.get('reason', 'na')),
            }

    if not pool:
        return []

    # Antique-style plates sometimes split a leading D/O/U across variants.
    # When the suffix is otherwise the same, prefer the D-leading hypothesis if
    # it is already close in score/confidence; this avoids variant repetition
    # from overpowering the more plausible forensic reading.
    if style_enabled and style_hint == 'antigo' and style_confidence >= style_min_confidence:
        suffix_groups = defaultdict(list)
        for item in pool.values():
            text = str(item.get('text', ''))
            if len(text) == 7 and text[0] in ('D', 'O', 'U'):
                suffix_groups[text[1:]].append(item)

        for group_items in suffix_groups.values():
            d_items = [item for item in group_items if str(item.get('text', ''))[:1] == 'D']
            o_items = [item for item in group_items if str(item.get('text', ''))[:1] in ('O', 'U')]
            if not d_items or not o_items:
                continue

            best_d = max(d_items, key=lambda item: (
                float(item.get('best_conf', 0.0)),
                float(item.get('best_score', 0.0)),
                float(item.get('weighted_support', 0.0)),
            ))
            best_o = max(o_items, key=lambda item: (
                float(item.get('best_conf', 0.0)),
                float(item.get('best_score', 0.0)),
                float(item.get('weighted_support', 0.0)),
            ))

            if (
                float(best_d.get('best_conf', 0.0)) + close_conf_margin >= float(best_o.get('best_conf', 0.0))
                and float(best_d.get('best_score', 0.0)) + close_score_margin >= float(best_o.get('best_score', 0.0))
            ):
                leading_bonus = leading_d_bonus + (style_strength * leading_d_bonus_scale)
                best_d['weighted_support'] = float(best_d.get('weighted_support', 0.0)) + float(leading_bonus)
                best_d['style_bonus_total'] = float(best_d.get('style_bonus_total', 0.0)) + float(leading_bonus)
                best_d['style_rank_priority'] = float(best_d.get('style_rank_priority', 0.0)) + float(leading_d_rank_credit + (style_strength * leading_d_rank_scale))
                best_d.setdefault('heuristic_adjustments', []).append({
                    'type': 'leading_d_bonus',
                    'bonus': round(float(leading_bonus), 3),
                    'paired_with': str(best_o.get('text', '')),
                })

    ranked = []
    for item in pool.values():
        support_count = len(item['engines'])
        support_bonus = min(support_bonus_cap, max(0, support_count - 1) * support_bonus_per_engine)
        weighted_support = float(item['weighted_support']) + support_bonus
        region = sorted(item['regions'])[0] if item['regions'] else 'full_image'
        style_rank_priority = float(item.get('style_rank_priority', 0.0))
        support_rank = float(support_count) + float(style_rank_priority)
        ranked.append({
            'text': item['text'],
            'score': round(float(item['best_score']), 2),
            'avg_conf': round(float(item['best_conf']), 2),
            'pattern': detect_plate_pattern(item['text']),
            'region': region,
            'support_count': support_count,
            'style_rank_priority': round(style_rank_priority, 3),
            'support_rank': round(support_rank, 3),
            'support_engines': sorted(item['engines']),
            'agreement_ratio': round((support_count / engines_considered) * 100.0, 1) if engines_considered else 0.0,
            'weighted_support': round(weighted_support, 2),
            'best_law_score': round(float(item.get('best_law_score', 0.0)), 2),
            'style_bonus_total': round(float(item.get('style_bonus_total', 0.0)), 3),
            'engine_contributions': {
                name: round(float(value), 3)
                for name, value in sorted(item['engine_contributions'].items())
            },
            'engine_weights': {
                name: meta
                for name, meta in sorted(item['engine_weights'].items())
            },
        })

    ranked.sort(
        key=lambda item: (
            float(item.get('support_rank', item.get('support_count', 0))),
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('weighted_support', 0)),
            float(item.get('score', 0)),
            float(item.get('avg_conf', 0)),
        ),
        reverse=True,
    )
    return ranked


def pick_ensemble_best(ensemble_ranked):
    if not ensemble_ranked:
        return None, None

    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        ensemble_profile = {}
    consensus_min_support = max(1, parse_int(ensemble_profile.get('consensus_min_support', 2), 2))
    required_length = max(7, parse_int(ensemble_profile.get('required_length', 7), 7))
    single_engine_min_weighted_support = parse_float(ensemble_profile.get('single_engine_min_weighted_support', 6.4), 6.4)
    single_engine_min_confidence = parse_float(ensemble_profile.get('single_engine_min_confidence', OCR_PATTERN_MIN_CONFIDENCE), OCR_PATTERN_MIN_CONFIDENCE)

    consensus_candidates = [
        item for item in ensemble_ranked
        if (
            float(item.get('support_rank', item.get('support_count', 0))) >= consensus_min_support
            and item.get('pattern', 'Indefinido') != 'Indefinido'
            and len(item.get('text', '')) == required_length
        )
    ]
    if consensus_candidates:
        return consensus_candidates[0], 'consensus_majority'

    top = ensemble_ranked[0]
    if (
        top.get('pattern', 'Indefinido') != 'Indefinido'
        and len(top.get('text', '')) == required_length
        and float(top.get('weighted_support', 0)) >= single_engine_min_weighted_support
        and float(top.get('avg_conf', 0)) >= single_engine_min_confidence
    ):
        return top, 'single_engine_strong'

    return None, None


def build_top_candidates(ocr_results, plate_detection=None):
    ensemble_ranked = build_ensemble_candidates(ocr_results, plate_detection=plate_detection)
    if ensemble_ranked:
        return [
            {
                **candidate,
                'engine': 'ensemble',
            }
            for candidate in ensemble_ranked[:MAX_TOP_CANDIDATES]
        ]

    merged = {}
    for engine, result in ocr_results.items():
        if not isinstance(result, dict):
            continue
        for candidate in result.get('candidates', []):
            text = normalize_plate_text(candidate.get('text', ''))
            if not is_plate_like_text(text):
                continue
            item = dict(candidate)
            item['text'] = text
            item['engine'] = engine
            previous = merged.get(text)
            if previous is None or float(item.get('score', 0)) > float(previous.get('score', 0)):
                merged[text] = item

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            item.get('pattern', 'Indefinido') != 'Indefinido',
            len(item.get('text', '')) == 7,
            float(item.get('score', 0)),
        ),
        reverse=True,
    )
    return ranked[:MAX_TOP_CANDIDATES]


def get_best_result(ocr_results, plate_detection=None):
    ensemble_ranked = build_ensemble_candidates(ocr_results, plate_detection=plate_detection)
    ensemble_best, selection_reason = pick_ensemble_best(ensemble_ranked)
    if ensemble_best:
        selected = dict(ensemble_best)
        selected['selection_reason'] = selection_reason
        return 'ensemble', selected

    ranked = sorted(
        (
            (engine, result)
            for engine, result in ocr_results.items()
            if is_plate_like_text(result.get('text', ''))
        ),
        key=lambda item: (
            item[1].get('pattern', 'Indefinido') != 'Indefinido',
            len(normalize_plate_text(item[1].get('text', ''))) == 7,
            item[1].get('score', item[1].get('avg_conf', 0)),
        ),
        reverse=True,
    )
    if not ranked:
        return None, None
    engine, result = ranked[0]
    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        ensemble_profile = {}
    fallback_divisor = max(1.0, parse_float(ensemble_profile.get('single_engine_fallback_divisor', 18.0), 18.0))
    selected = dict(result)
    selected['support_count'] = 1
    selected['support_engines'] = [engine]
    selected['agreement_ratio'] = 100.0
    selected['weighted_support'] = round(float(selected.get('score', selected.get('avg_conf', 0))) / fallback_divisor, 2)
    selected['selection_reason'] = 'single_engine_fallback'
    return engine, selected


def should_accept_result(best_result, plate_detection=None, top_candidates=None):
    if not best_result or not best_result.get('text'):
        return False, 'none'

    if not is_plate_like_text(best_result.get('text', '')):
        return False, 'non_plate_like_text'

    avg_conf = float(best_result.get('avg_conf', 0))
    score = float(best_result.get('score', 0))
    pattern = best_result.get('pattern', 'Indefinido')
    support_count = int(parse_int(best_result.get('support_count', 1), 1))
    weighted_support = float(parse_float(best_result.get('weighted_support', 0.0), 0.0))
    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        ensemble_profile = {}
    style_bias_profile = ocr_ensemble_style_bias_profile()
    single_engine_min_weighted_support = parse_float(ensemble_profile.get('single_engine_min_weighted_support', 6.4), 6.4)
    single_engine_min_confidence = parse_float(ensemble_profile.get('single_engine_min_confidence', OCR_PATTERN_MIN_CONFIDENCE), OCR_PATTERN_MIN_CONFIDENCE)
    style_context = extract_plate_style_context(plate_detection)
    style_hint = str(style_context.get('style_hint', 'indefinida') or 'indefinida').strip().lower()
    style_confidence = float(style_context.get('style_confidence', 0.0))
    style_is_strong = style_hint in ('mercosul', 'antigo') and style_confidence >= float(style_bias_profile.get('strong_style_min_confidence', 65.0) or 65.0)

    if support_count <= 1:
        if style_is_strong:
            expected_pattern = 'Mercosul' if style_hint == 'mercosul' else 'Antigo'
            if pattern == expected_pattern and avg_conf >= max(single_engine_min_confidence, 80.0) and score >= 100.0:
                return True, 'style_consistent_single_engine'
            if pattern != expected_pattern:
                if avg_conf >= 88.0 and score >= 145.0 and len(best_result.get('text', '')) == 7:
                    return True, 'style_conflict_high_confidence'
                return False, 'plate_style_conflict'
        if weighted_support < single_engine_min_weighted_support:
            if avg_conf >= 88.0 and score >= 145.0 and len(best_result.get('text', '')) == 7:
                return True, 'single_engine_high_confidence_override'
            return False, 'single_engine_support_low'
        if avg_conf < single_engine_min_confidence:
            return False, 'single_engine_confidence_low'

    if pattern == 'Indefinido':
        return False, 'pattern_missing'
    if style_is_strong:
        expected_pattern = 'Mercosul' if style_hint == 'mercosul' else 'Antigo'
        if pattern != expected_pattern:
            if support_count <= 1 or weighted_support < single_engine_min_weighted_support + 1.0:
                if avg_conf >= 88.0 and score >= 145.0 and len(best_result.get('text', '')) == 7:
                    return True, 'style_conflict_high_confidence'
                return False, 'plate_style_conflict'
    if avg_conf >= OCR_MIN_CONFIDENCE:
        return True, 'confidence_threshold'
    if pattern != 'Indefinido' and avg_conf >= OCR_PATTERN_MIN_CONFIDENCE:
        return True, 'pattern_threshold'
    if pattern != 'Indefinido' and avg_conf >= 35 and score >= 60:
        return True, 'pattern_score_threshold'
    if pattern != 'Indefinido' and score >= max(75.0, OCR_PATTERN_MIN_CONFIDENCE + 25):
        return True, 'score_threshold'
    return False, 'below_threshold'


def pick_pdf_probable_candidate(top_candidates):
    if not isinstance(top_candidates, list):
        return None

    ensemble_profile = ocr_reranking_calibration_lookup('ensemble', default={})
    if not isinstance(ensemble_profile, dict):
        ensemble_profile = {}
    pdf_min_score = parse_float(ensemble_profile.get('pdf_probable_min_score', 96.0), 96.0)
    pdf_min_conf = parse_float(ensemble_profile.get('pdf_probable_min_confidence', 62.0), 62.0)
    pdf_min_weighted_support = parse_float(ensemble_profile.get('pdf_probable_min_weighted_support', 6.6), 6.6)
    pdf_min_support_count = max(1, parse_int(ensemble_profile.get('pdf_probable_min_support_count', 2), 2))
    pdf_required_length = max(5, parse_int(ensemble_profile.get('pdf_probable_required_length', 7), 7))

    for candidate in top_candidates[:4]:
        if not isinstance(candidate, dict):
            continue
        text = normalize_plate_text(candidate.get('text', ''))
        if len(text) != pdf_required_length:
            continue
        pattern = detect_plate_pattern(text)
        if pattern == 'Indefinido':
            continue

        legal = validate_plate_by_law(text)
        if not bool((legal or {}).get('is_valid', False)):
            continue

        score = float(parse_float(candidate.get('score', 0.0), 0.0))
        avg_conf = float(parse_float(candidate.get('avg_conf', 0.0), 0.0))
        weighted_support = float(parse_float(candidate.get('weighted_support', 0.0), 0.0))
        support_count = int(parse_int(candidate.get('support_count', 1), 1))
        support_rank = float(parse_float(candidate.get('support_rank', support_count), float(support_count)))
        if score < pdf_min_score:
            continue
        if avg_conf < pdf_min_conf:
            continue
        if support_count < pdf_min_support_count and support_rank < pdf_min_support_count and weighted_support < pdf_min_weighted_support:
            continue
        return {
            'text': text,
            'pattern': pattern,
            'score': round(score, 2),
            'avg_conf': round(avg_conf, 2),
            'weighted_support': round(weighted_support, 2),
            'support_count': support_count,
            'support_rank': round(support_rank, 2),
            'support_engines': candidate.get('support_engines', []),
            'agreement_ratio': float(parse_float(candidate.get('agreement_ratio', 0.0), 0.0)),
            'region': str(candidate.get('region', 'full_image')),
            'engine': str(candidate.get('engine', 'ensemble')),
            'selection_reason': 'pdf_probable_candidate',
            'acceptance_reason': 'pdf_probable_threshold',
        }

    return None


def build_engine_summary(engine_status):
    if not isinstance(engine_status, dict):
        return {
            'engines_registered': 0,
            'engines_configured': 0,
            'engines_available': 0,
            'engines_ready': 0,
            'engines_executed': 0,
            'engines_with_text': 0,
            'engines_without_text': 0,
            'engines_skipped': 0,
            'engines_failed': 0,
            'engines_disabled': 0,
            'engines_unavailable': 0,
        }

    configured = 0
    available = 0
    ready = 0
    executed = 0
    with_text = 0
    skipped = 0
    failed = 0
    disabled = 0
    unavailable = 0
    registered = 0

    for meta in engine_status.values():
        if not isinstance(meta, dict):
            continue
        registered += 1
        enabled = bool(meta.get('enabled', False))
        is_available = bool(meta.get('available', False))
        if enabled:
            configured += 1
        if is_available:
            available += 1
        if enabled and is_available:
            ready += 1
        status = str(meta.get('status', 'indefinido'))
        if status == 'executed':
            executed += 1
            if bool(meta.get('has_text', False)):
                with_text += 1
        elif status == 'failed':
            failed += 1
        elif status == 'skipped':
            skipped += 1
        elif status == 'disabled':
            disabled += 1
        elif status == 'unavailable':
            unavailable += 1

    without_text = max(0, executed - with_text)
    return {
        'engines_registered': int(registered),
        'engines_configured': int(configured),
        'engines_available': int(available),
        'engines_ready': int(ready),
        'engines_executed': int(executed),
        'engines_with_text': int(with_text),
        'engines_without_text': int(without_text),
        'engines_skipped': int(skipped),
        'engines_failed': int(failed),
        'engines_disabled': int(disabled),
        'engines_unavailable': int(unavailable),
    }


def build_pdf_report(
    filepath,
    placa_path,
    recognized_text,
    crop_raw_path=None,
    crop_treated_path=None,
    vehicle_info=None,
    origem='web',
    forensic=None,
    consensus=None,
    assessment=None,
    pericial=None,
    visual_profile=None,
    external_systems_comparison=None,
    ocr_engines=None,
    ocr_engine_status=None,
    ocr_engine_summary=None,
    engine_runtime=None,
    input_meta=None,
    warnings=None,
    human_review=None,
    operational_protocol=None,
):
    analysis_context_id = ''
    if isinstance(forensic, dict):
        analysis_context_id = str(forensic.get('analysis_id', '') or '').strip()
    if not analysis_context_id and isinstance(input_meta, dict):
        analysis_context_id = str(input_meta.get('analysis_id', '') or '').strip()
    if not analysis_context_id:
        analysis_context_id = str(
            (os.path.splitext(os.path.basename(filepath))[0] if filepath else 'report')
        ).strip()
    pdf_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        build_unique_artifact_filename(
            os.path.basename(filepath) or 'report.pdf',
            analysis_context_id,
            prefix='relatorio_',
            default_extension='.pdf',
            force_extension=True,
        ),
    )
    default_vehicle = {
        'fabricante': 'Desconhecido',
        'modelo': 'Desconhecido',
        'ano': 'Desconhecido',
    }
    if isinstance(vehicle_info, dict) and vehicle_info:
        merged_vehicle = dict(default_vehicle)
        merged_vehicle.update(vehicle_info)
        vehicle_payload = merged_vehicle
    else:
        vehicle_payload = default_vehicle

    partial_plate_evidence = {}
    if isinstance(input_meta, dict):
        partial_plate_evidence = input_meta.get('partial_plate_evidence', {})
    if not isinstance(partial_plate_evidence, dict) or not partial_plate_evidence:
        partial_plate_evidence = {}
        if isinstance(pericial, dict):
            partial_plate_evidence = pericial.get('partial_plate_evidence', {})
    if not isinstance(partial_plate_evidence, dict):
        partial_plate_evidence = {}
    partial_plate_candidates = partial_plate_evidence.get('partial_plate_candidates', [])
    if not isinstance(partial_plate_candidates, list):
        partial_plate_candidates = []
    partial_plate_text = str(partial_plate_evidence.get('partial_plate_text', '') or '').strip()
    partial_plate_summary = str(partial_plate_evidence.get('partial_plate_summary', '') or '').strip()

    report_data = {
        'origem': origem or 'web',
        'foto_path': filepath,
        'placa_path': placa_path,
        'crop_raw_path': crop_raw_path or '',
        'crop_treated_path': crop_treated_path or placa_path,
        'exif': extract_exif(filepath),
        'veiculo': vehicle_payload,
        'ocr': recognized_text or 'Nao reconhecido',
        'forensic': forensic if isinstance(forensic, dict) else {},
        'consensus': consensus if isinstance(consensus, dict) else {},
        'assessment': assessment if isinstance(assessment, dict) else {},
        'pericial': pericial if isinstance(pericial, dict) else {},
        'visual_profile': visual_profile if isinstance(visual_profile, dict) else {},
        'external_systems_comparison': (
            external_systems_comparison if isinstance(external_systems_comparison, dict) else {}
        ),
        'ocr_results': ocr_engines if isinstance(ocr_engines, dict) else {},
        'ocr_engines': ocr_engines if isinstance(ocr_engines, dict) else {},
        'ocr_engine_status': ocr_engine_status if isinstance(ocr_engine_status, dict) else {},
        'ocr_engine_summary': ocr_engine_summary if isinstance(ocr_engine_summary, dict) else {},
        'engine_runtime': engine_runtime if isinstance(engine_runtime, dict) else {},
        'input_meta': input_meta if isinstance(input_meta, dict) else {},
        'warnings': warnings if isinstance(warnings, list) else [],
        'human_review': human_review if isinstance(human_review, dict) else {},
        'operational_protocol': operational_protocol if isinstance(operational_protocol, dict) else {},
        'partial_plate_evidence': partial_plate_evidence,
        'partial_plate_candidates': partial_plate_candidates,
        'partial_plate_candidates_count': len(partial_plate_candidates),
        'partial_plate_has_evidence': bool(partial_plate_candidates),
        'partial_plate_text': partial_plate_text or '-',
        'partial_plate_summary': partial_plate_summary or '-',
        'summary': (
            (operational_protocol or {}).get('summary', '')
            if isinstance(operational_protocol, dict)
            else ''
        ),
        'analysis_report_outline': get_analysis_report_outline(),
    }
    generate_pdf_report(report_data, pdf_path)
    return os.path.basename(pdf_path)


def resolve_upload_file(filename):
    safe_name = sanitize_filename(filename or '')
    if not safe_name:
        return None
    path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    if not os.path.exists(path):
        return None
    return path


def parse_vehicle_info(value):
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            return {}
    return {}


def parse_json_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            return {}
    return {}


def parse_json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except Exception:
            return []
    return []


def resize_for_quick_probe(img, max_side=PDF_PROBE_MAX_SIDE):
    if img is None:
        return None
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    return cv2.resize(img, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)


def resize_region_for_ocr(img, max_side=PDF_REGION_MAX_SIDE):
    if img is None:
        return None
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    resized_w = max(1, int(width * scale))
    resized_h = max(1, int(height * scale))
    return cv2.resize(img, (resized_w, resized_h), interpolation=cv2.INTER_AREA)


def build_pdf_page_rois(page_img):
    if page_img is None:
        return []

    height, width = page_img.shape[:2]
    if height < 120 or width < 120:
        return [('full_page', page_img)]

    rois = []
    center_crop = page_img[int(height * 0.10):int(height * 0.92), int(width * 0.04):int(width * 0.96)]

    gray = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, 244, 255, cv2.THRESH_BINARY_INV)[1]
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    page_area = float(height * width)
    boxes = []
    for contour in contours:
        x, y, box_w, box_h = cv2.boundingRect(contour)
        area = float(box_w * box_h)
        ratio = area / page_area if page_area > 0 else 0.0
        if ratio < 0.03 or ratio > 0.92:
            continue
        if box_w < 120 or box_h < 80:
            continue

        aspect = box_w / max(1.0, float(box_h))
        if aspect < 0.45 or aspect > 3.8:
            continue

        center_x = x + (box_w / 2.0)
        center_y = y + (box_h / 2.0)
        center_penalty = (
            abs(center_x - (width / 2.0)) / max(1.0, (width / 2.0))
            + abs(center_y - (height / 2.0)) / max(1.0, (height / 2.0))
        )
        score = (ratio * 100.0) - (center_penalty * 7.0)
        boxes.append((score, x, y, box_w, box_h))

    boxes.sort(key=lambda item: item[0], reverse=True)
    for index, (_, x, y, box_w, box_h) in enumerate(boxes[:PDF_PAGE_CANDIDATE_LIMIT]):
        pad_x = max(8, int(box_w * 0.04))
        pad_y = max(8, int(box_h * 0.04))
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(width, x + box_w + pad_x)
        y2 = min(height, y + box_h + pad_y)
        crop = page_img[y1:y2, x1:x2]
        if crop.size > 0:
            rois.append((f'roi_{index + 1}', crop))

    if len(rois) < PDF_PAGE_CANDIDATE_LIMIT and center_crop.size > 0:
        rois.append(('center_focus', center_crop))
    if not rois:
        rois.append(('full_page', page_img))

    deduped = []
    seen = set()
    for roi_name, roi_img in rois:
        signature = (
            roi_img.shape[0],
            roi_img.shape[1],
            int(float(np.mean(roi_img))),
            int(float(np.std(roi_img))),
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append((roi_name, roi_img))
        if len(deduped) >= PDF_PAGE_CANDIDATE_LIMIT:
            break
    return deduped


def _trim_pdf_photo_caption(roi_img):
    if roi_img is None or getattr(roi_img, 'size', 0) == 0:
        return roi_img

    height, width = roi_img.shape[:2]
    if height < 120 or width < 140:
        return roi_img

    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    row_density = np.mean(gray < 232, axis=1)
    row_smooth = np.convolve(row_density, np.ones(11, dtype=np.float32) / 11.0, mode='same')
    strong_rows = np.where(row_smooth > 0.20)[0]
    y_start = 0
    if len(strong_rows) > 0:
        y_start = int(max(0, strong_rows[0] - 2))
        if y_start > int(height * 0.45):
            y_start = 0

    trimmed = roi_img[y_start:, :] if y_start > 0 else roi_img
    if trimmed.shape[0] < 90 or trimmed.shape[1] < 120:
        return roi_img
    return trimmed


def score_pdf_visual_candidate(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return {'score': -999.0}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    dark_ratio = float(np.mean(gray < 210))
    edge_density = float(np.mean(cv2.Canny(gray, 60, 170) > 0))
    saturation = float(np.mean(hsv[:, :, 1]))

    score = (
        (dark_ratio * 130.0)
        + (contrast * 0.55)
        + (edge_density * 95.0)
        + (saturation * 0.18)
    )

    if dark_ratio < 0.06:
        score -= 42.0
    elif dark_ratio < 0.12:
        score -= 21.0

    if brightness > 244.0:
        score -= 16.0
    elif brightness > 230.0:
        score -= 8.0

    if contrast < 18.0:
        score -= 16.0
    elif contrast < 28.0:
        score -= 8.0

    return {
        'score': round(float(score), 2),
        'brightness': round(brightness, 2),
        'contrast': round(contrast, 2),
        'dark_ratio': round(dark_ratio, 4),
        'edge_density': round(edge_density, 4),
        'saturation': round(saturation, 2),
    }


def pick_pdf_visual_candidate(page_img, rois=None):
    if page_img is None:
        return None, {'score': -999.0, 'region': 'none'}

    roi_candidates = rois if isinstance(rois, list) else build_pdf_page_rois(page_img)
    candidates = []
    for roi_name, roi_img in roi_candidates:
        if roi_img is None or getattr(roi_img, 'size', 0) == 0:
            continue
        trimmed = _trim_pdf_photo_caption(roi_img)
        metrics = score_pdf_visual_candidate(trimmed)
        candidates.append({
            'region': str(roi_name),
            'image': trimmed,
            'metrics': metrics,
        })

    full_metrics = score_pdf_visual_candidate(page_img)
    candidates.append({
        'region': 'full_page',
        'image': page_img,
        'metrics': full_metrics,
    })

    if not candidates:
        return page_img, {'score': -999.0, 'region': 'fallback'}

    best = max(candidates, key=lambda item: float((item.get('metrics') or {}).get('score', -999.0)))
    meta = dict(best.get('metrics') or {})
    meta['region'] = str(best.get('region', 'indefinido'))
    return best.get('image'), meta


def _probe_candidate_entries(engine_name, result):
    if not isinstance(result, dict):
        return []

    entries_by_text = {}

    def push(text_value, avg_conf_value, score_value, pattern_value, origin='main'):
        text = normalize_plate_text(text_value)
        if not text:
            return
        pattern = str(pattern_value or detect_plate_pattern(text))
        key = text
        payload = {
            'engine': str(engine_name),
            'origin': str(origin),
            'text': text,
            'avg_conf': float(parse_float(avg_conf_value, 0.0)),
            'score': float(parse_float(score_value, 0.0)),
            'pattern': pattern,
        }
        previous = entries_by_text.get(key)
        if previous is None:
            entries_by_text[key] = payload
            return
        prev_score = float(previous.get('score', 0.0))
        new_score = float(payload.get('score', 0.0))
        if new_score > prev_score:
            entries_by_text[key] = payload
        else:
            previous['avg_conf'] = max(float(previous.get('avg_conf', 0.0)), float(payload.get('avg_conf', 0.0)))
            if str(previous.get('pattern', 'Indefinido')) == 'Indefinido' and pattern != 'Indefinido':
                previous['pattern'] = pattern

    push(
        result.get('text', ''),
        result.get('avg_conf', 0.0),
        result.get('score', result.get('avg_conf', 0.0)),
        result.get('pattern', 'Indefinido'),
        origin='main',
    )
    for item in result.get('candidates', [])[:MAX_TOP_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        push(
            item.get('text', ''),
            item.get('avg_conf', result.get('avg_conf', 0.0)),
            item.get('score', result.get('score', 0.0)),
            item.get('pattern', result.get('pattern', 'Indefinido')),
            origin='candidate',
        )
    return list(entries_by_text.values())


def _score_probe_candidate(candidate, region_metrics):
    if not isinstance(candidate, dict):
        return -999.0, {}

    text = normalize_plate_text(candidate.get('text', ''))
    if not is_plate_like_text(text):
        return -999.0, {}
    pattern = str(candidate.get('pattern', detect_plate_pattern(text)) or detect_plate_pattern(text))
    avg_conf = float(parse_float(candidate.get('avg_conf', 0.0), 0.0))
    raw_score = float(parse_float(candidate.get('score', 0.0), 0.0))
    legal = validate_plate_by_law(text)
    law_score = float((legal or {}).get('law_score', 0.0))
    is_legal = bool((legal or {}).get('is_valid'))

    score = (raw_score * 0.52) + (avg_conf * 0.34) + (law_score * 0.44)
    if len(text) == 7:
        score += 18.0
    elif len(text) >= 6:
        score += 7.0
    else:
        score -= 14.0

    if pattern != 'Indefinido':
        score += 17.0
    else:
        score -= 11.0

    if is_legal:
        score += 8.0
    else:
        violations = (legal or {}).get('violations', [])
        if isinstance(violations, list):
            score -= min(12.0, float(len(violations)) * 2.6)

    unique_chars = len(set(text))
    if unique_chars <= 3:
        score -= 10.0
    elif unique_chars == 4:
        score -= 5.0

    dark_ratio = float(region_metrics.get('dark_ratio', 0.0))
    brightness = float(region_metrics.get('brightness', 255.0))
    contrast = float(region_metrics.get('contrast', 0.0))
    edge_density = float(region_metrics.get('edge_density', 0.0))
    if dark_ratio < 0.08:
        score -= 24.0
    elif dark_ratio < 0.14:
        score -= 12.0
    if brightness > 242.0:
        score -= 11.0
    if contrast < 24.0:
        score -= 9.0
    if edge_density < 0.6:
        score -= 6.0

    details = {
        'law_score': round(law_score, 2),
        'is_legal': bool(is_legal),
        'raw_score': round(raw_score, 2),
        'avg_conf': round(avg_conf, 2),
        'pattern': pattern,
    }
    return round(float(score), 2), details


def quick_tesseract_probe(region_img):
    if region_img is None or getattr(region_img, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    probe_input = resize_for_quick_probe(region_img, max_side=PDF_QUICK_ENGINE_MAX_SIDE)
    if probe_input is None or getattr(probe_input, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    try:
        pre = preprocess_plate(probe_input)
    except Exception:
        try:
            gray = cv2.cvtColor(probe_input, cv2.COLOR_BGR2GRAY)
            pre = cv2.resize(gray, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        except Exception:
            return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    attempts = []
    for psm in (7, 8):
        try:
            extracted = tesseract_extract(pre, psm)
        except Exception:
            continue
        text = normalize_plate_text(extracted.get('text', ''))
        if not is_plate_like_text(text):
            continue
        avg_conf = float(parse_float(extracted.get('avg_conf', 0.0), 0.0))
        pattern = detect_plate_pattern(text)
        base_score = avg_conf + (18.0 if pattern != 'Indefinido' else 0.0) + (10.0 if len(text) == 7 else 0.0)
        attempts.append({
            'text': text,
            'avg_conf': avg_conf,
            'score': round(float(base_score), 2),
            'pattern': pattern,
            'origin': f'tesseract_psm_{psm}',
        })

    if not attempts:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    attempts.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)
    best = attempts[0]
    return {
        'text': best.get('text', ''),
        'avg_conf': float(best.get('avg_conf', 0.0)),
        'score': float(best.get('score', 0.0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'candidates': attempts[:4],
    }


def quick_rapidocr_probe(region_img):
    if RapidOCR is None or not RAPIDOCR_ENABLED:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    if region_img is None or getattr(region_img, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    try:
        reader = get_rapidocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    except Exception:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    probe_input = resize_for_quick_probe(region_img, max_side=PDF_QUICK_ENGINE_MAX_SIDE)
    if probe_input is None or getattr(probe_input, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    variant_inputs = []
    try:
        pre = preprocess_plate(probe_input)
        variant_inputs.append(('rapid_quick_pre', pre))
    except Exception:
        pass
    try:
        gray = cv2.cvtColor(probe_input, cv2.COLOR_BGR2GRAY)
        variant_inputs.append(('rapid_quick_gray', gray))
    except Exception:
        pass
    if not variant_inputs:
        variant_inputs = [('rapid_quick_raw', probe_input)]

    best = None
    for variant_name, variant_img in variant_inputs[:2]:
        try:
            raw_result, _ = reader(variant_img)
        except Exception:
            continue
        entries, chars = parse_rapidocr_entries(raw_result)
        if not entries:
            continue
        ranked = rank_ocr_candidates_from_entries(entries, variant_name, RAPIDOCR_HIT_BONUS )
        ranked['chars'] = chars
        if best is None or float(ranked.get('score', 0.0)) > float(best.get('score', 0.0)):
            best = ranked

    if not best:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    if not is_plate_like_text(best.get('text', '')):
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    return {
        'text': normalize_plate_text(best.get('text', '')),
        'avg_conf': float(best.get('avg_conf', 0.0)),
        'score': float(best.get('score', 0.0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'candidates': list(best.get('candidates', []))[:4],
    }


def quick_easyocr_probe(region_img):
    if easyocr is None or not EASYOCR_ENABLED:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    if region_img is None or getattr(region_img, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    try:
        reader = get_easyocr_reader()
        if reader is None:
            return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    except Exception:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    probe_input = resize_for_quick_probe(region_img, max_side=PDF_QUICK_ENGINE_MAX_SIDE)
    if probe_input is None or getattr(probe_input, 'size', 0) == 0:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}

    variant_inputs = []
    try:
        pre = preprocess_plate(probe_input)
        variant_inputs.append(('easy_quick_pre', pre))
    except Exception:
        pass
    try:
        gray = cv2.cvtColor(probe_input, cv2.COLOR_BGR2GRAY)
        variant_inputs.append(('easy_quick_gray', gray))
    except Exception:
        pass
    if not variant_inputs:
        variant_inputs = [('easy_quick_raw', probe_input)]

    best = None
    for variant_name, variant_img in variant_inputs[:2]:
        try:
            raw_result = read_easyocr_with_profile(reader, variant_img)
        except Exception:
            continue
        entries, chars = parse_easyocr_entries(raw_result)
        if not entries:
            continue
        ranked = rank_ocr_candidates_from_entries(entries, variant_name, EASYOCR_HIT_BONUS )
        ranked['chars'] = chars
        if best is None or float(ranked.get('score', 0.0)) > float(best.get('score', 0.0)):
            best = ranked

    if not best:
        return {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido', 'candidates': []}
    return {
        'text': normalize_plate_text(best.get('text', '')),
        'avg_conf': float(best.get('avg_conf', 0.0)),
        'score': float(best.get('score', 0.0)),
        'pattern': best.get('pattern', 'Indefinido'),
        'candidates': list(best.get('candidates', []))[:4],
    }


def quick_candidate_score(img):
    if img is None:
        return {'score': 0.0, 'text': '', 'pattern': 'Indefinido', 'engine': 'none'}

    candidate = resize_for_quick_probe(img)
    enhanced, preprocess_meta = preprocess_scene_for_ocr(candidate)

    scene_variants = [('raw', candidate)]
    if str((preprocess_meta or {}).get('selected', 'original')) == 'enhanced' and enhanced is not None:
        scene_variants.append(('enhanced', enhanced))

    region_candidates = []
    region_seen = set()
    for variant_name, variant_img in scene_variants:
        if variant_img is None or getattr(variant_img, 'size', 0) == 0:
            continue
        detected = detect_plate_regions(variant_img)
        prioritized = [item for item in detected if item[0] != 'full_image']
        full_regions = [item for item in detected if item[0] == 'full_image']
        ordered_regions = prioritized[:max(1, PDF_MAX_REGION_CANDIDATES + 1)]
        if full_regions:
            ordered_regions.append(full_regions[0])

        for region_name, region_img in ordered_regions:
            if region_img is None or getattr(region_img, 'size', 0) == 0:
                continue
            signature = (
                int(region_img.shape[0]),
                int(region_img.shape[1]),
                int(float(np.mean(region_img))),
                int(float(np.std(region_img))),
            )
            if signature in region_seen:
                continue
            region_seen.add(signature)
            region_candidates.append((variant_name, region_name, region_img))
            if len(region_candidates) >= PDF_PROBE_REGION_LIMIT:
                break
        if len(region_candidates) >= PDF_PROBE_REGION_LIMIT:
            break

    if not region_candidates:
        region_candidates = [('raw', 'full_image', candidate)]

    best = {
        'score': -1e9,
        'text': '',
        'pattern': 'Indefinido',
        'engine': 'none',
        'avg_conf': 0.0,
        'law_score': 0.0,
        'is_legal': False,
        'region': 'full_image',
        'variant': 'raw',
    }

    def process_engine_result(engine_name, result, region_metrics, region_name, variant_name):
        nonlocal best
        entries = _probe_candidate_entries(engine_name, result)
        for entry in entries[:5]:
            candidate_score, detail = _score_probe_candidate(entry, region_metrics)
            if candidate_score <= -900:
                continue
            if candidate_score > float(best.get('score', -1e9)):
                best = {
                    'score': round(float(candidate_score), 2),
                    'text': entry.get('text', ''),
                    'pattern': detail.get('pattern', 'Indefinido'),
                    'engine': str(engine_name),
                    'avg_conf': float(detail.get('avg_conf', 0.0)),
                    'law_score': float(detail.get('law_score', 0.0)),
                    'is_legal': bool(detail.get('is_legal', False)),
                    'region': str(region_name),
                    'variant': str(variant_name),
                }

    for variant_name, region_name, region_img in region_candidates:
        if region_img.shape[0] < 22 or region_img.shape[1] < 70:
            continue
        region_metrics = score_pdf_visual_candidate(region_img)

        if RAPIDOCR_ENABLED and RapidOCR is not None:
            process_engine_result('rapidocr_quick', quick_rapidocr_probe(region_img), region_metrics, region_name, variant_name)
        elif EASYOCR_ENABLED and easyocr is not None:
            process_engine_result('easyocr_quick', quick_easyocr_probe(region_img), region_metrics, region_name, variant_name)
        if PADDLEOCR_ENABLED and PaddleOCR is not None:
            process_engine_result('paddleocr_quick', quick_paddleocr_probe(region_img), region_metrics, region_name, variant_name)

    use_tesseract_probe = (
        float(best.get('score', -1e9)) < max(92.0, PDF_PAGE_EARLY_SCORE - 24.0)
        or str(best.get('pattern', 'Indefinido')) == 'Indefinido'
    )
    if use_tesseract_probe:
        for variant_name, region_name, region_img in region_candidates[:2]:
            if region_img.shape[0] < 22 or region_img.shape[1] < 70:
                continue
            region_metrics = score_pdf_visual_candidate(region_img)
            process_engine_result('tesseract_quick', quick_tesseract_probe(region_img), region_metrics, region_name, variant_name)

    if float(best.get('score', -1e9)) <= -900:
        return {'score': 0.0, 'text': '', 'pattern': 'Indefinido', 'engine': 'none', 'region': 'full_image', 'variant': 'raw'}
    return best


def _select_plate_region_image(plate_regions, plate_detection=None):
    selected_region = ''
    if isinstance(plate_detection, dict):
        selected_region = str(plate_detection.get('selected_region', '') or '').strip()

    if isinstance(plate_regions, list):
        for region_name, region_img in plate_regions:
            if region_img is None or getattr(region_img, 'size', 0) == 0:
                continue
            if selected_region and str(region_name) == selected_region:
                return region_img

        for _, region_img in plate_regions:
            if region_img is not None and getattr(region_img, 'size', 0) > 0:
                return region_img

    return None


def select_regions_for_quick_triage(plate_regions, region_limit=TRIAGE_IMAGE_REGION_LIMIT):
    if not isinstance(plate_regions, list) or not plate_regions:
        return []

    ranked = []
    for index, item in enumerate(plate_regions):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        region_name, region_img = item[0], item[1]
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue

        metrics = describe_plate_region(region_name, region_img)
        family = str(metrics.get('source_family', 'unknown') or 'unknown')
        aspect = float(metrics.get('aspect_ratio', 0.0) or 0.0)
        quality_label = str(metrics.get('quality_label', 'indefinida') or 'indefinida').lower()
        score = float(metrics.get('score', 0.0) or 0.0)

        if str(region_name).startswith('raw_'):
            score -= 38.0
        if str(region_name) in ('raw_input', 'input', 'raw_raw_input'):
            score -= 70.0
        if family == 'fallback_full_scene':
            score -= 80.0
        elif family == 'secondary':
            score -= 50.0
        elif family in ('contour', 'haar', 'yolo', 'external_box'):
            score += 22.0
        elif family == 'heuristic':
            score += 8.0

        if 3.0 <= aspect <= 5.8:
            score += 18.0
        elif 2.2 <= aspect < 3.0 or 5.8 < aspect <= 6.8:
            score += 8.0
        else:
            score -= 12.0

        if quality_label == 'critica':
            score -= 18.0
        elif quality_label == 'excelente':
            score += 6.0

        ranked.append((score, index, str(region_name), region_img))

    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    selected = [(name, img) for _, _, name, img in ranked[:max(1, region_limit)]]
    if selected:
        return selected

    return plate_regions[:max(1, region_limit)]


def run_quick_plate_triage_probes(plate_regions, region_limit=TRIAGE_IMAGE_REGION_LIMIT):
    candidates = []
    engines_available = []
    seen = set()

    engine_specs = []
    if RAPIDOCR_ENABLED and RapidOCR is not None:
        engine_specs.append(('rapidocr_quick', quick_rapidocr_probe))
    elif EASYOCR_ENABLED and easyocr is not None:
        engine_specs.append(('easyocr_quick', quick_easyocr_probe))
    else:
        engine_specs.append(('tesseract_quick', quick_tesseract_probe))

    if not isinstance(plate_regions, list):
        plate_regions = []

    for region_name, region_img in plate_regions[:max(1, region_limit)]:
        if region_img is None or getattr(region_img, 'size', 0) == 0:
            continue
        if region_img.shape[0] < 22 or region_img.shape[1] < 70:
            continue

        prepared = resize_region_for_ocr(region_img, max_side=TRIAGE_IMAGE_REGION_MAX_SIDE)
        if prepared is None or getattr(prepared, 'size', 0) == 0:
            prepared = region_img

        region_metrics = score_pdf_visual_candidate(prepared)
        for engine_name, engine_func in engine_specs:
            try:
                result = engine_func(prepared)
            except Exception:
                continue

            entries = _probe_candidate_entries(engine_name, result)
            if result.get('text') or entries:
                engines_available.append(engine_name)

            for entry in entries[:4]:
                candidate_score, detail = _score_probe_candidate(entry, region_metrics)
                if candidate_score <= -900:
                    continue
                text = normalize_plate_text(entry.get('text', ''))
                signature = (engine_name, str(region_name), text)
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append({
                    'engine': engine_name,
                    'region': str(region_name),
                    'text': text,
                    'avg_conf': float(detail.get('avg_conf', 0.0)),
                    'raw_score': float(detail.get('raw_score', 0.0)),
                    'score': float(candidate_score),
                    'law_score': float(detail.get('law_score', 0.0)),
                    'is_legal': bool(detail.get('is_legal', False)),
                    'pattern': str(detail.get('pattern', detect_plate_pattern(text)) or detect_plate_pattern(text)),
                    'region_quality_score': float(region_metrics.get('score', 0.0)),
                    'region_quality_label': str(region_metrics.get('quality_label', 'indefinida') or 'indefinida'),
                })

            if candidates:
                current_best = max(candidates, key=lambda item: float(item.get('score', 0.0)))
                if (
                    len(normalize_plate_text(current_best.get('text', ''))) >= 6
                    and str(current_best.get('pattern', 'Indefinido')) != 'Indefinido'
                    and float(current_best.get('score', 0.0)) >= 110.0
                ):
                    break
        else:
            continue
        break

    candidates.sort(
        key=lambda item: (
            float(item.get('score', 0.0)),
            float(item.get('law_score', 0.0)),
            float(item.get('avg_conf', 0.0)),
        ),
        reverse=True,
    )

    best = candidates[0] if candidates else {
        'engine': 'none',
        'region': 'full_image',
        'text': '',
        'avg_conf': 0.0,
        'raw_score': 0.0,
        'score': 0.0,
        'law_score': 0.0,
        'is_legal': False,
        'pattern': 'Indefinido',
        'region_quality_score': 0.0,
        'region_quality_label': 'indefinida',
    }
    return best, candidates[:8], sorted(set(engines_available))


def build_image_quick_triage_decision(plate_detection, quality_report, capture_integrity, quick_probe):
    plate_detection = plate_detection if isinstance(plate_detection, dict) else {}
    quality_report = quality_report if isinstance(quality_report, dict) else {}
    capture_integrity = capture_integrity if isinstance(capture_integrity, dict) else {}
    quick_probe = quick_probe if isinstance(quick_probe, dict) else {}

    plate_status = str(plate_detection.get('status', 'sem_candidato') or 'sem_candidato')
    used_full_image = bool(plate_detection.get('used_full_image'))
    candidate_count = int(plate_detection.get('candidate_count', 0) or 0)
    selected_quality = float(plate_detection.get('selected_quality_score', 0.0) or 0.0)
    selected_region = str(plate_detection.get('selected_region', '') or '')
    quality_score = float(quality_report.get('score', 0.0) or 0.0)
    integrity_score = float(capture_integrity.get('integrity_score', 0.0) or 0.0)
    quick_score = float(quick_probe.get('score', 0.0) or 0.0)
    quick_conf = float(quick_probe.get('avg_conf', 0.0) or 0.0)
    law_score = float(quick_probe.get('law_score', 0.0) or 0.0)
    quick_text = normalize_plate_text(quick_probe.get('text', ''))
    pattern = str(quick_probe.get('pattern', 'Indefinido') or 'Indefinido')
    signal_score = (
        selected_quality * 0.34
        + quality_score * 0.24
        + integrity_score * 0.18
        + min(100.0, quick_score) * 0.16
        + law_score * 0.08
    )
    signal_score = round(float(max(0.0, min(100.0, signal_score))), 1)

    reasons = []
    strengths = []

    if plate_status == 'sem_candidato':
        reasons.append('sem_roi_confiavel')
    else:
        strengths.append('roi_detectado')

    if used_full_image:
        reasons.append('triagem_em_imagem_completa')
    elif selected_region:
        strengths.append(f'roi_principal:{selected_region}')

    if selected_quality >= TRIAGE_IMAGE_ACCEPT_QUALITY:
        strengths.append('roi_com_qualidade_suficiente')
    elif selected_quality >= TRIAGE_IMAGE_MARGINAL_QUALITY:
        reasons.append('roi_marginal_para_ocr_confiavel')
    else:
        reasons.append('roi_fraco_para_ocr')

    if quality_score >= 70.0:
        strengths.append('nitidez_e_contraste_adequados')
    elif quality_score < 48.0:
        reasons.append('qualidade_visual_critica')

    if integrity_score < 70.0:
        reasons.append('integridade_de_entrada_reduzida')

    if len(quick_text) >= 6 and pattern != 'Indefinido':
        strengths.append('texto_rapido_compativel_com_placa')
    elif len(quick_text) >= 3:
        strengths.append('fragmento_util_detectado')
        reasons.append('leitura_ainda_parcial')
    else:
        reasons.append('sem_texto_rapido_util')

    if quick_score >= 92.0 or (quick_conf >= 60.0 and law_score >= 72.0 and len(quick_text) >= 6):
        strengths.append('sinal_ocr_rapido_forte')
    elif quick_score < 56.0:
        reasons.append('sinal_ocr_rapido_fraco')

    triage_status = 'insuficiente'
    if (
        plate_status == 'roi_detectado'
        and not used_full_image
        and selected_quality >= TRIAGE_IMAGE_ACCEPT_QUALITY
        and signal_score >= TRIAGE_IMAGE_ACCEPT_SCORE
        and len(quick_text) >= 6
        and pattern != 'Indefinido'
        and (law_score >= 68.0 or quick_score >= 92.0)
    ):
        triage_status = 'apto_ocr'
    elif (
        candidate_count > 0
        and signal_score >= TRIAGE_IMAGE_MARGINAL_SCORE
        and (selected_quality >= TRIAGE_IMAGE_MARGINAL_QUALITY or len(quick_text) >= 3 or quick_score >= 60.0)
    ):
        triage_status = 'marginal_revisao'

    material_minimo_ocr = triage_status == 'apto_ocr'
    status_map = {
        'apto_ocr': 'TRIAGEM_APTA',
        'marginal_revisao': 'TRIAGEM_MARGINAL',
        'insuficiente': 'TRIAGEM_NEGATIVA',
    }
    label_map = {
        'apto_ocr': 'Apto para OCR completo',
        'marginal_revisao': 'Material marginal para OCR confiavel',
        'insuficiente': 'Material insuficiente para OCR confiavel',
    }
    next_step_map = {
        'apto_ocr': 'seguir_com_ocr_completo',
        'marginal_revisao': 'executar_ocr_completo_com_revisao_humana',
        'insuficiente': 'solicitar_nova_captura_ou_recorte_manual',
    }

    return {
        'status': status_map[triage_status],
        'triage_status': triage_status,
        'triage_status_label': label_map[triage_status],
        'material_minimo_ocr': material_minimo_ocr,
        'triage_score': signal_score,
        'recommended_next_step': next_step_map[triage_status],
        'reasons': list(dict.fromkeys(str(item) for item in reasons if str(item).strip())),
        'strengths': list(dict.fromkeys(str(item) for item in strengths if str(item).strip())),
        'quick_hint_text': quick_text,
        'quick_hint_pattern': pattern,
        'quick_hint_confidence': round(float(quick_conf), 1),
        'quick_hint_law_score': round(float(law_score), 1),
        'roi_quality_score': round(float(selected_quality), 1),
        'image_quality_score': round(float(quality_score), 1),
        'integrity_score': round(float(integrity_score), 1),
    }


def should_skip_quick_triage_probe(plate_detection, quality_report, ocr_regions):
    plate_detection = plate_detection if isinstance(plate_detection, dict) else {}
    quality_report = quality_report if isinstance(quality_report, dict) else {}

    if not isinstance(ocr_regions, list) or not ocr_regions:
        return True

    plate_status = str(plate_detection.get('status', 'sem_candidato') or 'sem_candidato')
    selected_quality = float(plate_detection.get('selected_quality_score', 0.0) or 0.0)
    quality_grade = str(quality_report.get('grade', 'CRITICA') or 'CRITICA').upper()
    quality_score = float(quality_report.get('score', 0.0) or 0.0)

    if plate_status == 'sem_candidato':
        return True
    if selected_quality < max(22.0, TRIAGE_IMAGE_MARGINAL_QUALITY - 8.0):
        return True
    if quality_grade == 'CRITICA' and quality_score < 40.0 and selected_quality < (TRIAGE_IMAGE_ACCEPT_QUALITY - 14.0):
        return True
    return False


def run_image_quick_triage(img, input_meta, input_warnings, analysis_id):
    started = time.perf_counter()
    input_meta = dict(input_meta) if isinstance(input_meta, dict) else {}
    warnings = list(input_warnings) if isinstance(input_warnings, list) else []

    triage_scene_input = resize_for_quick_probe(img, max_side=TRIAGE_IMAGE_SCENE_MAX_SIDE)
    if triage_scene_input is None or getattr(triage_scene_input, 'size', 0) == 0:
        triage_scene_input = img

    pre_scene, scene_meta = preprocess_scene_for_ocr(triage_scene_input)
    scene_uses_enhanced = str((scene_meta or {}).get('selected', 'original')) == 'enhanced'
    ocr_scene = pre_scene if scene_uses_enhanced else triage_scene_input
    secondary_scene = triage_scene_input if scene_uses_enhanced else None
    include_yolo = ALLOW_HEAVY_COLDSTART or yolo_detector_is_warm()

    plate_regions = build_plate_regions_multisource(
        ocr_scene,
        None,
        secondary_img=secondary_scene,
        include_yolo=include_yolo,
    )
    if input_meta.get('input_type') == 'pdf':
        plate_regions = limit_regions_for_pdf(plate_regions)

    triage_regions = select_regions_for_quick_triage(plate_regions, region_limit=max(2, TRIAGE_IMAGE_REGION_LIMIT + 1))
    plate_detection = build_plate_detection_summary(triage_regions)
    ocr_regions = triage_regions[:max(1, TRIAGE_IMAGE_REGION_LIMIT)]
    selected_region_img = _select_plate_region_image(triage_regions, plate_detection)
    quality_report = analyze_plate_quality(selected_region_img if selected_region_img is not None else ocr_scene)
    capture_integrity = build_capture_integrity_summary(input_meta, plate_detection)
    if should_skip_quick_triage_probe(plate_detection, quality_report, ocr_regions):
        quick_probe = {
            'engine': 'none',
            'region': str(plate_detection.get('selected_region', 'full_image') or 'full_image'),
            'text': '',
            'avg_conf': 0.0,
            'raw_score': 0.0,
            'score': 0.0,
            'law_score': 0.0,
            'is_legal': False,
            'pattern': 'Indefinido',
            'region_quality_score': float(plate_detection.get('selected_score', 0.0) or 0.0),
            'region_quality_label': str(plate_detection.get('selected_quality_label', 'indefinida') or 'indefinida'),
        }
        quick_probe_candidates = []
        quick_probe_engines = []
    else:
        quick_probe, quick_probe_candidates, quick_probe_engines = run_quick_plate_triage_probes(ocr_regions)
    triage = build_image_quick_triage_decision(plate_detection, quality_report, capture_integrity, quick_probe)

    elapsed_seconds = round(time.perf_counter() - started, 2)
    input_meta['scene_preprocess'] = scene_meta
    input_meta['scene_selected'] = 'enhanced' if scene_uses_enhanced else 'original'
    input_meta['plate_detection'] = plate_detection
    input_meta['quick_triage'] = triage

    return {
        'analysis_id': analysis_id,
        'analysis_mode': 'triage',
        'status': triage.get('status', 'TRIAGEM_NEGATIVA'),
        'triage_status': triage.get('triage_status', 'insuficiente'),
        'triage_status_label': triage.get('triage_status_label', 'Material insuficiente para OCR confiavel'),
        'material_minimo_ocr': bool(triage.get('material_minimo_ocr')),
        'triage_score': float(triage.get('triage_score', 0.0)),
        'recommended_next_step': triage.get('recommended_next_step', 'solicitar_nova_captura_ou_recorte_manual'),
        'reasons': list(triage.get('reasons', [])),
        'strengths': list(triage.get('strengths', [])),
        'quick_hint_text': triage.get('quick_hint_text', ''),
        'quick_hint_pattern': triage.get('quick_hint_pattern', 'Indefinido'),
        'quick_hint_confidence': float(triage.get('quick_hint_confidence', 0.0)),
        'quick_hint_law_score': float(triage.get('quick_hint_law_score', 0.0)),
        'quick_probe': quick_probe,
        'quick_probe_candidates': quick_probe_candidates,
        'quick_probe_engines': quick_probe_engines,
        'plate_detection': plate_detection,
        'quality_report': quality_report,
        'capture_integrity': capture_integrity,
        'scene_preprocess': scene_meta,
        'input_meta': input_meta,
        'warnings': warnings,
        'elapsed_seconds': elapsed_seconds,
        'report_generated': False,
    }


def load_input_for_ocr(filepath, filename, content_type=''):
    security = inspect_upload_file(filepath, filename, content_type)
    warnings = list(security.get('warnings', [])) if isinstance(security, dict) else []
    if not security.get('allowed', False):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        return None, None, {
            'error': security.get('error', 'Arquivo enviado nao suportado'),
            'input_type': security.get('input_type', 'unsupported'),
            'input_security': security,
        }, warnings

    ext = os.path.splitext(filename or '')[1].lower()
    if ext != '.pdf':
        image = cv2.imread(filepath)
        if image is None:
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass
            return None, None, {
                'error': 'Erro ao ler a imagem enviada',
                'input_type': 'image',
                'input_security': security,
            }, warnings

        # Forensic Metadata Extraction
        meta = {
            'input_type': 'image',
            'input_security': security,
            'source_resolution': {
                'width': int(image.shape[1]),
                'height': int(image.shape[0]),
            }
        }

        # Try to extract Exif
        try:
            exif_data = extract_exif(filepath)
            if exif_data:
                meta['exif'] = exif_data
                meta['timestamp'] = exif_data.get('DateTimeOriginal') or exif_data.get('DateTime')
                meta['camera'] = f"{exif_data.get('Make', '')} {exif_data.get('Model', '')}".strip()
        except Exception as exif_err:
            warnings.append(f'metadata_extraction_partial:{exif_err}')

        return image, filepath, meta, warnings

    if not PDF_INPUT_ENABLED:
        return None, None, {'error': 'Entrada em PDF desabilitada no servidor', 'input_type': 'pdf', 'input_security': security}, warnings
    if pdfium is None:
        return None, None, {'error': 'Suporte a PDF indisponivel (instale pypdfium2)', 'input_type': 'pdf', 'input_security': security}, warnings

    try:
        document = pdfium.PdfDocument(filepath)
    except Exception as exc:
        return None, None, {'error': f'Falha ao abrir PDF: {exc}', 'input_type': 'pdf', 'input_security': security}, warnings

    page_count = len(document)
    if page_count <= 0:
        return None, None, {'error': 'PDF sem paginas para analise', 'input_type': 'pdf', 'input_security': security}, warnings

    pages_to_scan = min(page_count, PDF_MAX_PAGES)
    best_page_image = None
    best_page_scene = None
    best_page_index = 0
    best_page_score = -1e9
    best_page_region = 'full_page'
    best_page_text = ''
    best_visual_image = None
    best_visual_score = -1e9
    best_visual_page_index = 0
    best_visual_region = 'full_page'
    page_rankings = []
    page_candidates = []

    for page_index in range(pages_to_scan):
        try:
            page = document[page_index]
            pil_image = page.render(scale=PDF_RENDER_SCALE).to_pil()
            rgb = np.array(pil_image)
            if rgb.ndim == 2:
                bgr = cv2.cvtColor(rgb, cv2.COLOR_GRAY2BGR)
            else:
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            rois = build_pdf_page_rois(bgr)
            visual_candidate, visual_meta = pick_pdf_visual_candidate(bgr, rois=rois)
            probe_candidates = []
            probe_seen = set()
            for roi_name, roi_img in rois:
                if roi_img is None or getattr(roi_img, 'size', 0) == 0:
                    continue
                trimmed = _trim_pdf_photo_caption(roi_img)
                signature = (
                    int(trimmed.shape[0]),
                    int(trimmed.shape[1]),
                    int(float(np.mean(trimmed))),
                    int(float(np.std(trimmed))),
                )
                if signature in probe_seen:
                    continue
                probe_seen.add(signature)
                metrics = score_pdf_visual_candidate(trimmed)
                probe_candidates.append((str(roi_name), trimmed, float(metrics.get('score', -999.0))))

            if visual_candidate is not None and getattr(visual_candidate, 'size', 0) > 0:
                visual_sig = (
                    int(visual_candidate.shape[0]),
                    int(visual_candidate.shape[1]),
                    int(float(np.mean(visual_candidate))),
                    int(float(np.std(visual_candidate))),
                )
                if visual_sig not in probe_seen:
                    probe_seen.add(visual_sig)
                    probe_candidates.append((
                        str((visual_meta or {}).get('region', 'visual_focus')),
                        visual_candidate,
                        float((visual_meta or {}).get('score', -999.0)) + 0.8,
                    ))

            if not probe_candidates:
                full_metrics = score_pdf_visual_candidate(bgr)
                probe_candidates = [('full_page', bgr, float(full_metrics.get('score', -999.0)))]

            probe_candidates.sort(key=lambda item: float(item[2]), reverse=True)
            max_probe_rois = max(1, PDF_PAGE_CANDIDATE_LIMIT + 1)
            probe_rois = [(name, roi) for name, roi, _ in probe_candidates[:max_probe_rois]]
            page_best = {
                'score': -1e9,
                'region': 'full_page',
                'text': '',
                'pattern': 'Indefinido',
                'engine': 'none',
                'image': bgr,
            }

            for roi_name, roi_img in probe_rois:
                probe = quick_candidate_score(roi_img)
                if probe['score'] > page_best['score']:
                    page_best = {
                        'score': probe['score'],
                        'region': roi_name,
                        'text': probe['text'],
                        'pattern': probe['pattern'],
                        'engine': probe['engine'],
                        'variant': probe.get('variant', 'raw'),
                        'probe_region': probe.get('region', roi_name),
                        'avg_conf': float(probe.get('avg_conf', 0.0)),
                        'law_score': float(probe.get('law_score', 0.0)),
                        'is_legal': bool(probe.get('is_legal', False)),
                        'image': roi_img,
                    }

            page_text = normalize_plate_text(page_best.get('text', ''))
            page_pattern = str(page_best.get('pattern', 'Indefinido'))
            page_legal = validate_plate_by_law(page_text) if page_text else {'law_score': 0.0, 'is_valid': False}
            page_law_score = float(page_legal.get('law_score', 0.0))
            page_is_legal = bool(page_legal.get('is_valid', False))
            visual_score_current = float((visual_meta or {}).get('score', -999.0))
            page_combined_score = (
                float(page_best.get('score', -1e9))
                + (page_law_score * 0.22)
                + (max(0.0, visual_score_current) * 0.10)
                + (14.0 if (len(page_text) == 7 and page_pattern != 'Indefinido') else 0.0)
                + (8.0 if page_is_legal else 0.0)
            )

            page_candidates.append({
                'page_index': page_index,
                'score': float(page_best.get('score', -1e9)),
                'combined_score': float(page_combined_score),
                'region': str(page_best.get('region', 'full_page')),
                'probe_region': str(page_best.get('probe_region', page_best.get('region', 'full_page'))),
                'engine': str(page_best.get('engine', 'none')),
                'variant': str(page_best.get('variant', 'raw')),
                'text': page_text,
                'pattern': page_pattern,
                'law_score': page_law_score,
                'is_legal': page_is_legal,
                'image': page_best.get('image', bgr),
                'scene': bgr,
                'visual_score': visual_score_current,
                'visual_image': visual_candidate if visual_candidate is not None else bgr,
                'visual_region': str((visual_meta or {}).get('region', 'full_page')),
            })

            page_rankings.append({
                'page': page_index + 1,
                'score': round(float(page_best['score']), 2),
                'combined_score': round(float(page_combined_score), 2),
                'region': page_best['region'],
                'text': page_best['text'],
                'pattern': page_best['pattern'],
                'engine': page_best['engine'],
                'variant': page_best.get('variant', 'raw'),
                'probe_region': page_best.get('probe_region', page_best['region']),
                'law_score': round(page_law_score, 2),
                'is_legal': bool(page_is_legal),
                'visual_score': round(float((visual_meta or {}).get('score', -999.0)), 2),
                'visual_region': str((visual_meta or {}).get('region', 'indefinido')),
            })

            if float((visual_meta or {}).get('score', -999.0)) > best_visual_score:
                best_visual_score = float((visual_meta or {}).get('score', -999.0))
                best_visual_image = visual_candidate
                best_visual_page_index = page_index
                best_visual_region = str((visual_meta or {}).get('region', 'full_page'))

            if (
                float(page_best.get('score', -1e9)) >= PDF_PAGE_EARLY_SCORE
                and len(page_text) == 7
                and page_pattern != 'Indefinido'
                and page_is_legal
            ):
                page.close()
                break
            page.close()
        except Exception as exc:
            warnings.append(f'pdf_page_{page_index + 1}_failed:{exc}')

    try:
        document.close()
    except Exception:
        pass

    if page_candidates:
        page_candidates.sort(
            key=lambda item: (
                bool(item.get('is_legal', False)),
                len(str(item.get('text', ''))) == 7 and str(item.get('pattern', 'Indefinido')) != 'Indefinido',
                float(item.get('combined_score', -1e9)),
                float(item.get('score', -1e9)),
                float(item.get('visual_score', -999.0)),
            ),
            reverse=True,
        )
        selected_candidate = page_candidates[0]
        best_page_score = float(selected_candidate.get('score', -1e9))
        best_page_image = selected_candidate.get('image')
        best_page_scene = selected_candidate.get('scene')
        best_page_index = int(selected_candidate.get('page_index', 0))
        best_page_region = str(selected_candidate.get('region', 'full_page'))
        best_page_text = str(selected_candidate.get('text', ''))
        best_page_pattern = str(selected_candidate.get('pattern', 'Indefinido'))
        best_page_legal = bool(selected_candidate.get('is_legal', False))
        use_visual_fallback = (
            float(best_page_score) < 62.0
            or len(best_page_text) < 6
            or best_page_pattern == 'Indefinido'
            or not best_page_legal
        )
        if use_visual_fallback:
            visual_fallback = selected_candidate.get('visual_image')
            selected_visual_score = float(selected_candidate.get('visual_score', -999.0))
            if (
                best_visual_image is not None
                and getattr(best_visual_image, 'size', 0) > 0
                and float(best_visual_score) > (selected_visual_score + 4.0)
            ):
                visual_fallback = best_visual_image
                best_page_region = str(best_visual_region or selected_candidate.get('visual_region', best_page_region))
                best_page_index = int(best_visual_page_index)
            if visual_fallback is not None and getattr(visual_fallback, 'size', 0) > 0:
                best_page_image = visual_fallback
                if best_page_region == str(selected_candidate.get('region', 'full_page')):
                    best_page_region = str(selected_candidate.get('visual_region', best_page_region))
                warnings.append('pdf_probe_using_visual_focus_fallback')
        if (
            len(best_page_text) == 7
            and best_page_pattern != 'Indefinido'
            and not best_page_legal
        ):
            warnings.append('pdf_probe_best_candidate_not_legal_pattern')

    if best_page_image is None:
        return None, None, {'error': 'Nao foi possivel renderizar paginas do PDF'}, warnings

    if best_page_score < 55:
        warnings.append('pdf_page_probe_low_confidence')

    base_name = os.path.splitext(os.path.basename(filename or 'documento.pdf'))[0]
    preview_name = sanitize_filename(f'pdf_preview_{base_name}_p{best_page_index + 1}.jpg')
    preview_path = os.path.join(app.config['UPLOAD_FOLDER'], preview_name)
    cv2.imwrite(preview_path, best_page_image)
    scene_image = best_visual_image if best_visual_image is not None else best_page_scene
    scene_page_index = best_visual_page_index if best_visual_image is not None else best_page_index
    scene_region = best_visual_region if best_visual_image is not None else best_page_region
    scene_score = best_visual_score if best_visual_image is not None else best_page_score

    scene_name = sanitize_filename(f'pdf_scene_{base_name}_p{scene_page_index + 1}.jpg')
    scene_path = os.path.join(app.config['UPLOAD_FOLDER'], scene_name)
    if scene_image is not None:
        cv2.imwrite(scene_path, scene_image)
    else:
        scene_name = preview_name

    meta = {
        'input_type': 'pdf',
        'pages_scanned': pages_to_scan,
        'page_selected': best_page_index + 1,
        'page_selected_region': best_page_region,
        'page_selected_text_probe': best_page_text,
        'page_score': round(float(best_page_score), 2),
        'visual_page_selected': scene_page_index + 1,
        'visual_page_region': scene_region,
        'visual_page_score': round(float(scene_score), 2),
        'visual_scene_filename': scene_name,
        'page_rankings': sorted(page_rankings, key=lambda item: float(item.get('combined_score', item.get('score', 0))), reverse=True)[:PDF_MAX_PAGES],
        'input_security': security,
    }
    return best_page_image, preview_path, meta, warnings


@app.route('/process', methods=['POST'])
@safe_route
def process_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    analysis_stage = str(request.form.get('analysis_stage', 'final') or 'final').strip().lower()
    if analysis_stage not in ('preview', 'final'):
        analysis_stage = 'final'

    analysis_id = uuid.uuid4().hex
    process_started_utc = utc_iso_now()

    file = request.files['image']
    filename = sanitize_filename(file.filename)
    filepath = os.path.join(
        app.config['UPLOAD_FOLDER'],
        build_unique_artifact_filename(filename, analysis_id, default_extension=os.path.splitext(filename)[1] or '.jpg'),
    )
    file.save(filepath)

    img, photo_source_path, input_meta, input_warnings = load_input_for_ocr(filepath, filename, getattr(file, 'content_type', '') or '')
    if img is None:
        return jsonify({
            'error': input_meta.get('error', 'Erro ao ler arquivo enviado'),
            'input_meta': input_meta,
            'warnings': input_warnings,
        }), 400

    if isinstance(input_meta, dict):
        input_meta['analysis_id'] = analysis_id
        input_meta['source_filename'] = filename
        input_meta['source_path'] = photo_source_path
        input_meta['original_filename'] = filename
        input_meta['preserved_original'] = True
        if img is not None and getattr(img, 'size', 0) > 0:
            input_meta['source_resolution'] = {
                'width': int(img.shape[1]),
                'height': int(img.shape[0]),
            }

    raw_input_scene = img
    preprocessed_scene, scene_preprocess_meta = preprocess_scene_for_ocr(raw_input_scene)
    scene_uses_enhanced = str((scene_preprocess_meta or {}).get('selected', 'original')) == 'enhanced'
    ocr_scene = preprocessed_scene if scene_uses_enhanced else raw_input_scene
    if isinstance(input_meta, dict):
        input_meta['scene_preprocess'] = scene_preprocess_meta
        input_meta['scene_selected'] = 'enhanced' if scene_uses_enhanced else 'original'

    pr_source_path = photo_source_path if input_meta.get('input_type') == 'pdf' else filepath
    box, pr_result = detect_plate_pr_api(pr_source_path)
    pr_plate = normalize_plate_text((pr_result or {}).get('text', '')) if isinstance(pr_result, dict) else ''
    secondary_scene = raw_input_scene if scene_uses_enhanced else None
    plate_regions = build_plate_regions_multisource(ocr_scene, box, secondary_img=secondary_scene)
    if input_meta.get('input_type') == 'pdf':
        plate_regions = limit_regions_for_pdf(plate_regions)
    region_map = {name: region for name, region in plate_regions}
    plate_detection = build_plate_detection_summary(plate_regions)
    if isinstance(input_meta, dict):
        input_meta['plate_detection'] = plate_detection
    ocr_regions = budget_regions_for_speed(plate_regions, plate_detection)

    # --- ExecuÃ§Ã£o do Ensemble Forense dentro do /process ---
    ensemble_data = run_ocr_ensemble_core(ocr_regions, input_meta, input_warnings, pr_result=pr_result, pr_plate=pr_plate)

    ocr_results = ensemble_data['ocr_results']
    best_engine = ensemble_data['best_engine']
    best = ensemble_data['best_result']
    top_candidates = ensemble_data['top_candidates']
    warnings = ensemble_data['warnings']
    engine_status = ensemble_data.get('engine_status', {})

    ocr_engine_summary = build_engine_summary(engine_status)
    reranking_calibration = ocr_reranking_calibration_info()
    ocr_engine_summary['reranking_calibration_source'] = reranking_calibration['source']
    ocr_engine_summary['reranking_calibration_path'] = reranking_calibration['path']
    ocr_engine_summary['reranking_calibration_version'] = reranking_calibration['version']
    ocr_engine_summary['reranking_calibration_load_error'] = reranking_calibration['load_error']
    if isinstance(input_meta, dict):
        input_meta['ocr_reranking_calibration'] = reranking_calibration

    accepted, acceptance_reason = should_accept_result(best, plate_detection=plate_detection)
    if (
        accepted
        and input_meta.get('input_type') == 'pdf'
        and str(best_engine or '') == 'pdf_probe'
        and isinstance(best, dict)
    ):
        best_text_pdf = normalize_plate_text(best.get('text', ''))
        corroborated = False
        if best_text_pdf:
            for engine_name, payload in ocr_results.items():
                if engine_name == 'pdf_probe' or not isinstance(payload, dict):
                    continue
                if best_text_pdf in collect_engine_text_set(payload):
                    corroborated = True
                    break
        if not corroborated:
            accepted = False
            acceptance_reason = 'pdf_probe_without_corroboration'

    best_payload = None
    char_options = []

    if accepted and best:
        best_avg_conf = max(0.0, min(100.0, float(best.get('avg_conf', 0))))
        best_payload = {
            'engine': best_engine,
            'text': best['text'],
            'avg_conf': best_avg_conf,
            'score': float(best.get('score', best.get('avg_conf', 0))),
            'pattern': best.get('pattern', 'Indefinido'),
            'region': best.get('region', 'full_image'),
            'support_count': int(best.get('support_count', 1)),
            'support_rank': float(best.get('support_rank', best.get('support_count', 1))),
            'style_rank_priority': float(best.get('style_rank_priority', 0.0)),
            'support_engines': best.get('support_engines', [best_engine]),
            'agreement_ratio': float(best.get('agreement_ratio', 100.0)),
            'weighted_support': float(best.get('weighted_support', 0)),
            'selection_reason': best.get('selection_reason', 'single_engine_fallback'),
            'acceptance_reason': acceptance_reason,
        }
    else:
        char_options = build_char_options(ocr_results)

    top_candidates = build_top_candidates(ocr_results, plate_detection=plate_detection)
    if best_payload is None and input_meta.get('input_type') == 'pdf':
        pdf_probable = pick_pdf_probable_candidate(top_candidates)
        if pdf_probable:
            best_payload = {
                'engine': pdf_probable.get('engine', 'ensemble'),
                'text': pdf_probable.get('text', ''),
                'avg_conf': float(pdf_probable.get('avg_conf', 0.0)),
                'score': float(pdf_probable.get('score', 0.0)),
                'pattern': pdf_probable.get('pattern', 'Indefinido'),
                'region': pdf_probable.get('region', 'full_image'),
                'support_count': int(pdf_probable.get('support_count', 1)),
                'support_rank': float(pdf_probable.get('support_rank', pdf_probable.get('support_count', 1))),
                'style_rank_priority': float(pdf_probable.get('style_rank_priority', 0.0)),
                'support_engines': pdf_probable.get('support_engines', []),
                'agreement_ratio': float(pdf_probable.get('agreement_ratio', 0.0)),
                'weighted_support': float(pdf_probable.get('weighted_support', 0.0)),
                'selection_reason': 'pdf_probable_candidate',
                'acceptance_reason': 'pdf_probable_threshold',
            }
            warnings.append('pdf_probable_candidate_review_required')

    best_region_name = (best_payload or {}).get('region') if best_payload else (best.get('region') if best else None)
    best_region_img = region_map.get(best_region_name) if best_region_name else None
    if isinstance(plate_detection, dict):
        plate_detection['ocr_selected_region'] = str(best_region_name or '')
        plate_detection['ocr_selected_source'] = plate_region_source_family(best_region_name)
        if best_region_img is not None:
            plate_detection['ocr_selected_metrics'] = describe_plate_region(best_region_name, best_region_img)
            plate_detection['ocr_selected_quality_score'] = float((plate_detection['ocr_selected_metrics'] or {}).get('quality_score', 0.0))
            plate_detection['ocr_selected_shape_hint'] = str((plate_detection['ocr_selected_metrics'] or {}).get('shape_hint', 'indefinida'))
            plate_detection['ocr_selected_style_hint'] = str((plate_detection['ocr_selected_metrics'] or {}).get('style_hint', 'indefinida'))
            plate_detection['ocr_selected_style_confidence'] = float((plate_detection['ocr_selected_metrics'] or {}).get('style_confidence', 0.0))
    if plate_geometry_module is not None:
        plate_for_report = plate_geometry_module.enhance_plate_preview(best_region_img if best_region_img is not None else ocr_scene)
        if isinstance(plate_detection, dict):
            plate_detection['preview_enhanced'] = True
    else:
        plate_for_report = best_region_img if best_region_img is not None else ocr_scene
        if isinstance(plate_detection, dict):
            plate_detection['preview_enhanced'] = False
    raw_crop_path = ''
    if isinstance(best_region_img, np.ndarray) and getattr(best_region_img, 'size', 0) > 0:
        raw_crop_output_name = sanitize_filename(f"recorte_bruto_{os.path.splitext(filename)[0]}.jpg")
        raw_crop_path = os.path.join(app.config['UPLOAD_FOLDER'], raw_crop_output_name)
        cv2.imwrite(raw_crop_path, best_region_img)
    if isinstance(plate_detection, dict):
        plate_detection['selected_raw_path'] = raw_crop_path
        plate_detection['selected_treated_path'] = ''
    if isinstance(plate_detection, dict) and plate_for_report is not None and getattr(plate_for_report, 'size', 0) > 0:
        plate_detection['selected_resolution'] = {
            'width': int(plate_for_report.shape[1]),
            'height': int(plate_for_report.shape[0]),
        }
    plate_output_name = sanitize_filename(f"placa_{os.path.splitext(filename)[0]}.jpg")
    placa_path = os.path.join(app.config['UPLOAD_FOLDER'], plate_output_name)
    cv2.imwrite(placa_path, plate_for_report)
    if isinstance(plate_detection, dict):
        plate_detection['selected_treated_path'] = placa_path
        if not raw_crop_path:
            plate_detection['selected_raw_path'] = placa_path
        plate_detection['selected_path'] = placa_path

    visual_scene = ocr_scene
    if input_meta.get('input_type') == 'pdf':
        visual_scene_name = sanitize_filename(str(input_meta.get('visual_scene_filename', '') or ''))
        if visual_scene_name:
            visual_scene_path = os.path.join(app.config['UPLOAD_FOLDER'], visual_scene_name)
            if os.path.exists(visual_scene_path):
                loaded_scene = cv2.imread(visual_scene_path)
                if loaded_scene is not None:
                    visual_scene = loaded_scene
                else:
                    warnings.append('visual_scene_load_failed')
    visual_scene_preprocessed, visual_scene_meta = preprocess_scene_for_ocr(visual_scene)
    visual_scene_uses_enhanced = str((visual_scene_meta or {}).get('selected', 'original')) == 'enhanced'
    if visual_scene_uses_enhanced:
        visual_scene = visual_scene_preprocessed
    if isinstance(input_meta, dict):
        input_meta['visual_scene_preprocess'] = visual_scene_meta
        input_meta['visual_scene_selected'] = 'enhanced' if visual_scene_uses_enhanced else 'original'
        if visual_scene is not None and getattr(visual_scene, 'size', 0) > 0:
            input_meta['visual_scene_resolution'] = {
                'width': int(visual_scene.shape[1]),
                'height': int(visual_scene.shape[0]),
            }

    visual_profile = analyze_vehicle_visual_profile(visual_scene)
    external_systems_comparison = run_external_vehicle_systems_comparison(
        visual_scene,
        best_payload=best_payload if isinstance(best_payload, dict) else {},
        visual_profile=visual_profile if isinstance(visual_profile, dict) else {},
    )
    assisted_vehicle_identification = build_assisted_vehicle_identification(
        visual_profile=visual_profile if isinstance(visual_profile, dict) else {},
        external_systems_comparison=external_systems_comparison if isinstance(external_systems_comparison, dict) else {},
    )
    adulterado = detect_adulteration(plate_for_report)
    quality_report = analyze_plate_quality(plate_for_report)
    process_finished_utc = utc_iso_now()
    forensic = build_forensic_chain(
        analysis_id,
        photo_source_path,
        placa_path,
        process_started_utc,
        process_finished_utc,
    )
    microcalibration_context = build_microcalibration_context(
        best_payload,
        top_candidates,
        ocr_results,
        source_sha256=str(forensic.get('source_sha256', '') or ''),
        photo_filename=os.path.basename(photo_source_path),
        plate_filename=os.path.basename(placa_path),
    )
    human_review = {}
    if microcalibration_context:
        manual_candidate = microcalibration_context.get('manual_candidate', {})
        raw_best_payload = microcalibration_context.get('raw_best_payload', {})
        override = microcalibration_context.get('override', {})
        human_review = dict(microcalibration_context.get('human_review', {}))
        if isinstance(manual_candidate, dict) and manual_candidate:
            best_payload = dict(manual_candidate)
        if isinstance(input_meta, dict):
            input_meta['microcalibration'] = {
                'applied': True,
                'match_key': str((override or {}).get('match_key', '')),
                'manual_text': str((manual_candidate or {}).get('text', '')),
                'manual_pattern': str(microcalibration_context.get('manual_pattern', 'Indefinido')),
                'manual_review_required': bool((override or {}).get('manual_review_required', True)),
                'status': str((override or {}).get('status', 'RATIFICADA_MANUALMENTE')),
                'decision': str((override or {}).get('decision', 'CORRIGIDO_MANUAL')),
                'source': str((override or {}).get('source', 'manual_review')),
                'calibration_version': str((override or {}).get('calibration_version', '')),
                'calibration_path': str((override or {}).get('calibration_path', '')),
            }
            input_meta['microcalibration_raw_best'] = {
                'text': str((raw_best_payload or {}).get('text', '')),
                'engine': str((raw_best_payload or {}).get('engine', '')),
                'score': float((raw_best_payload or {}).get('score', 0.0) or 0.0),
                'avg_conf': float((raw_best_payload or {}).get('avg_conf', 0.0) or 0.0),
                'pattern': str((raw_best_payload or {}).get('pattern', 'Indefinido')),
                'region': str((raw_best_payload or {}).get('region', 'full_image')),
            }
            input_meta['human_review'] = human_review
        if 'microcalibration_manual_override_applied' not in warnings:
            warnings.append('microcalibration_manual_override_applied')
    consensus = build_consensus_report(
        ocr_results,
        preferred_text=((best_payload or {}).get('text', '') if isinstance(best_payload, dict) else ''),
    )
    assessment_base = build_assessment(best_payload, consensus, warnings, adulterado)
    pericial = build_pericial_report(best_payload, top_candidates, ocr_results, consensus, quality_report, warnings, input_meta=input_meta)
    if microcalibration_context and isinstance(pericial, dict):
        override = microcalibration_context.get('override', {})
        manual_candidate = microcalibration_context.get('manual_candidate', {})
        pericial['status'] = str((override or {}).get('status', 'RATIFICADA_MANUALMENTE'))
        pericial['human_review'] = human_review
        pericial['microcalibration'] = {
            'applied': True,
            'match_key': str((override or {}).get('match_key', '')),
            'manual_text': str((manual_candidate or {}).get('text', '')),
            'manual_pattern': str(microcalibration_context.get('manual_pattern', 'Indefinido')),
            'source': str((override or {}).get('source', 'manual_review')),
            'notes': str((override or {}).get('notes', '')),
        }
    if isinstance(pericial, dict):
        cross_checks = pericial.setdefault('cross_checks', {})
        if isinstance(cross_checks, dict):
            main_hypothesis = visual_profile.get('hipotese_principal', {}) if isinstance(visual_profile, dict) else {}
            main_hypothesis_raw = visual_profile.get('hipotese_principal_bruta', {}) if isinstance(visual_profile, dict) else {}
            model_quality = visual_profile.get('qualidade_modelo', {}) if isinstance(visual_profile, dict) else {}
            component_summary = visual_profile.get('assinaturas_componentes', {}) if isinstance(visual_profile, dict) else {}
            forensic_traits = visual_profile.get('caracteristicas_forenses', {}) if isinstance(visual_profile, dict) else {}
            evidence_matrix = visual_profile.get('matriz_evidencias', {}) if isinstance(visual_profile, dict) else {}
            if not isinstance(evidence_matrix, dict):
                evidence_matrix = {}
            matrix_candidates = evidence_matrix.get('candidates', [])
            if not isinstance(matrix_candidates, list):
                matrix_candidates = []
            matrix_summary = evidence_matrix.get('summary', [])
            if not isinstance(matrix_summary, list):
                matrix_summary = []
            forensic_findings = forensic_traits.get('achados', []) if isinstance(forensic_traits, dict) else []
            if not isinstance(forensic_findings, list):
                forensic_findings = []
            forensic_summary = []
            for finding in forensic_findings[:3]:
                if not isinstance(finding, dict):
                    continue
                forensic_summary.append(
                    f"{finding.get('codigo', 'achado_visual')} ({float(finding.get('confianca', 0.0)):.1f}%)"
                )
            cross_checks['visual_profile'] = {
                'status': str((visual_profile or {}).get('status', 'indefinido')),
                'source': 'analise_visual_local_heuristica',
                'fabricante': str(main_hypothesis.get('fabricante', '')),
                'modelo': str(main_hypothesis.get('modelo', '')),
                'faixa_ano_modelo': str(main_hypothesis.get('faixa_ano_modelo', '')),
                'confianca': float(main_hypothesis.get('confianca', 0.0)),
                'modelo_abstido': bool((model_quality or {}).get('model_abstained', False)),
                'modelo_abstencao_motivos': (
                    ','.join([str(item) for item in (model_quality or {}).get('reasons', []) if str(item).strip()])
                    if isinstance((model_quality or {}).get('reasons', []), list)
                    else ''
                ),
                'modelo_bruto': str(main_hypothesis_raw.get('modelo', '')),
                'confianca_modelo_bruta': float((model_quality or {}).get('raw_confidence', 0.0)),
                'margem_top2_modelo': float((model_quality or {}).get('confidence_margin_top2', 0.0)),
                'evidencias_discriminativas': int((model_quality or {}).get('discriminative_evidence_count', 0)),
                'cor_probavel': str((visual_profile or {}).get('cor_probavel', '')),
                'vista_detectada': str((visual_profile or {}).get('vista_detectada', 'indefinida')),
                'lanterna_traseira_vertical': bool(((visual_profile or {}).get('lanterna_traseira', {}) or {}).get('vertical_pair')),
                'fontes_abertas_count': len((((visual_profile or {}).get('comparativo_fontes_abertas', {}) or {}).get('fontes', []) if isinstance((visual_profile or {}).get('comparativo_fontes_abertas', {}), dict) else [])),
                'componentes_detectados': int((component_summary or {}).get('itens_detectados', 0)),
                'componentes_avaliados': int((component_summary or {}).get('itens_avaliados', 0)),
                'componentes_cobertura': float((component_summary or {}).get('cobertura_percentual', 0.0)),
                'caracteristicas_forenses_status': str((forensic_traits or {}).get('status', 'indefinido')),
                'caracteristicas_forenses_detectadas': int((forensic_traits or {}).get('total_achados', 0)),
                'caracteristicas_forenses_resumo': '; '.join(forensic_summary) if forensic_summary else '-',
                'matriz_evidencias_status': str((evidence_matrix or {}).get('status', 'indefinido')),
                'matriz_evidencias_candidatos': int(len(matrix_candidates)),
                'matriz_evidencias_resumo': '; '.join([str(item) for item in matrix_summary[:3] if str(item).strip()]) or '-',
                'motores_busca_utilizados': (
                    ((visual_profile or {}).get('comparativo_fontes_abertas', {}) or {}).get('motores_busca_utilizados', [])
                    if isinstance((visual_profile or {}).get('comparativo_fontes_abertas', {}), dict)
                    else []
                ),
                'motores_analise_utilizados': (
                    ((visual_profile or {}).get('comparativo_fontes_abertas', {}) or {}).get('motores_analise_utilizados', [])
                    if isinstance((visual_profile or {}).get('comparativo_fontes_abertas', {}), dict)
                    else []
                ),
            }
            external_summary = (
                (external_systems_comparison or {}).get('sumario', {})
                if isinstance(external_systems_comparison, dict)
                else {}
            )
            external_runs = (
                (external_systems_comparison or {}).get('execucoes', [])
                if isinstance(external_systems_comparison, dict)
                else []
            )
            if not isinstance(external_runs, list):
                external_runs = []
            cross_checks['external_systems'] = {
                'status': str((external_systems_comparison or {}).get('status', 'indefinido')),
                'source': 'comparativo_sistemas_externos',
                'systems_cataloged': int(external_summary.get('sistemas_catalogados', 0)),
                'systems_executed': int(external_summary.get('sistemas_executados', 0)),
                'systems_ok': int(external_summary.get('sistemas_ok', 0)),
                'plate_compatible_count': int(external_summary.get('placa_compativel_ocr', 0)),
                'vehicle_compatible_count': int(external_summary.get('veiculo_compativel_visual', 0)),
                'plate_match_ratio': float(external_summary.get('taxa_concordancia_placa', 0.0)),
                'vehicle_match_ratio': float(external_summary.get('taxa_concordancia_veiculo', 0.0)),
                'engines': [
                    {
                        'id': str(item.get('id', 'externo')),
                        'status': str(item.get('status', 'indefinido')),
                        'plate': str(item.get('plate', '')),
                        'plate_confidence': float(parse_float(item.get('plate_confidence'), 0.0)),
                        'matches_internal_plate': item.get('matches_internal_plate'),
                        'matches_internal_vehicle': item.get('matches_internal_vehicle'),
                    }
                    for item in external_runs[:6]
                    if isinstance(item, dict)
                ],
            }
            cross_checks['assisted_vehicle_identification'] = {
                'status': str((assisted_vehicle_identification or {}).get('status', 'indefinido')),
                'label': str((assisted_vehicle_identification or {}).get('label', 'Indeterminado')),
                'fabricante': str((assisted_vehicle_identification or {}).get('fabricante', '')),
                'modelo': str((assisted_vehicle_identification or {}).get('modelo', '')),
                'cor': str((assisted_vehicle_identification or {}).get('cor', '')),
                'ano': str((assisted_vehicle_identification or {}).get('ano', '')),
                'tipo_carroceria': str((assisted_vehicle_identification or {}).get('tipo_carroceria', '')),
                'confidence': float((assisted_vehicle_identification or {}).get('confidence', 0.0)),
                'corroborated': bool((assisted_vehicle_identification or {}).get('corroborated', False)),
                'divergent': bool((assisted_vehicle_identification or {}).get('divergent', False)),
                'manual_review_required': bool((assisted_vehicle_identification or {}).get('manual_review_required', True)),
                'supporting_systems_count': int((assisted_vehicle_identification or {}).get('supporting_systems_count', 0)),
                'best_external_system': str((assisted_vehicle_identification or {}).get('best_external_system', '')),
                'statement': str((assisted_vehicle_identification or {}).get('statement', '')),
                'reasons': list((assisted_vehicle_identification or {}).get('reasons', []))
                if isinstance((assisted_vehicle_identification or {}).get('reasons', []), list)
                else [],
            }
            strong_forensic_hit = any(float((item or {}).get('confianca', 0.0)) >= 72.0 for item in forensic_findings if isinstance(item, dict))
            if strong_forensic_hit:
                warnings.append('forensic_traits_potencialmente_relevantes')
            if microcalibration_context:
                override = microcalibration_context.get('override', {})
                manual_candidate = microcalibration_context.get('manual_candidate', {})
                cross_checks['microcalibration'] = {
                    'applied': True,
                    'match_key': str((override or {}).get('match_key', '')),
                    'manual_text': str((manual_candidate or {}).get('text', '')),
                    'manual_pattern': str(microcalibration_context.get('manual_pattern', 'Indefinido')),
                    'source': str((override or {}).get('source', 'manual_review')),
                    'status': str((override or {}).get('status', 'RATIFICADA_MANUALMENTE')),
                }
                cross_checks['human_review'] = human_review
    if isinstance(visual_profile, dict):
        visual_status = str(visual_profile.get('status', ''))
        if visual_status == 'low_confidence':
            warnings.append('visual_profile_low_confidence')
        elif visual_status == 'review_required':
            warnings.append('visual_profile_review_required')
    assessment = merge_assessment_with_pericial(assessment_base, pericial)
    if microcalibration_context and isinstance(assessment, dict):
        reasons = list(assessment.get('reasons', []))
        if 'microcalibracao_manual_aplicada' not in reasons:
            reasons.append('microcalibracao_manual_aplicada')
        assessment['reasons'] = reasons
        assessment['manual_review_required'] = True
        assessment['display_evidence_level'] = str((human_review or {}).get('status', 'RATIFICADA_MANUALMENTE'))
    plate_pattern_info = build_plate_pattern_info(
        best_payload=(best_payload if isinstance(best_payload, dict) else (best if isinstance(best, dict) else {})),
        legal_validation=((pericial or {}).get('legal_validation', {}) if isinstance(pericial, dict) else {}),
        fallback_text=((best_payload or {}).get('text', '') if isinstance(best_payload, dict) else ''),
        plate_detection=plate_detection,
    )
    operational_protocol = vehicle_analysis_protocol_module.build_operational_protocol({
        'analysis_id': analysis_id,
        'origem': input_meta.get('input_type', 'web'),
        'photo_filename': os.path.basename(photo_source_path),
        'photo_path': photo_source_path,
        'plate_filename': os.path.basename(placa_path),
        'plate_path': placa_path,
        'crop_raw_path': raw_crop_path or placa_path,
        'crop_treated_path': placa_path,
        'visual_scene_filename': str(input_meta.get('visual_scene_filename', '') or ''),
        'capture_timestamp_utc': process_started_utc,
        'source_resolution': input_meta.get('source_resolution', {}),
        'plate_resolution': plate_detection.get('selected_resolution', {}),
        'visual_scene_resolution': input_meta.get('visual_scene_resolution', {}),
        'input_meta': input_meta,
        'best_payload': best_payload if isinstance(best_payload, dict) else {},
        'top_candidates': top_candidates,
        'ocr_results': ocr_results,
        'consensus': consensus,
        'quality_report': quality_report,
        'warnings': warnings,
        'visual_profile': visual_profile if isinstance(visual_profile, dict) else {},
        'assessment': assessment,
        'pericial': pericial,
        'forensic': forensic,
        'external_systems_comparison': external_systems_comparison,
        'assisted_vehicle_identification': assisted_vehicle_identification,
        'plate_pattern_info': plate_pattern_info,
        'plate_detection': plate_detection,
        'legal_validation': (pericial or {}).get('legal_validation', {}) if isinstance(pericial, dict) else {},
        'capture_integrity': (pericial or {}).get('capture_integrity', {}) if isinstance(pericial, dict) else {},
        'character_ambiguity': (pericial or {}).get('character_ambiguity', {}) if isinstance(pericial, dict) else {},
        'operational_checklist': {
            'items': [
                'Preservar imagem original',
                'Triagem A/B/C/D',
                'OCR com alternativas e incertezas',
                'Matriz de compatibilidade 0-100',
                'Verificacao de exclusoes obrigatorias',
            ],
        },
    })
    vehicle_confrontation_form = vehicle_confrontation_form_module.build_vehicle_confrontation_form({
        'analysis_id': analysis_id,
        'origem': input_meta.get('input_type', 'web'),
        'photo_filename': os.path.basename(photo_source_path),
        'photo_path': photo_source_path,
        'plate_filename': os.path.basename(placa_path),
        'plate_path': placa_path,
        'crop_raw_path': raw_crop_path or placa_path,
        'crop_treated_path': placa_path,
        'visual_scene_filename': str(input_meta.get('visual_scene_filename', '') or ''),
        'capture_timestamp_utc': process_started_utc,
        'source_resolution': input_meta.get('source_resolution', {}),
        'plate_resolution': plate_detection.get('selected_resolution', {}),
        'visual_scene_resolution': input_meta.get('visual_scene_resolution', {}),
        'input_meta': input_meta,
        'best_payload': best_payload if isinstance(best_payload, dict) else {},
        'top_candidates': top_candidates,
        'ocr_results': ocr_results,
        'consensus': consensus,
        'quality_report': quality_report,
        'warnings': warnings,
        'visual_profile': visual_profile if isinstance(visual_profile, dict) else {},
        'assessment': assessment,
        'pericial': pericial,
        'forensic': forensic,
        'external_systems_comparison': external_systems_comparison,
        'assisted_vehicle_identification': assisted_vehicle_identification,
        'plate_pattern_info': plate_pattern_info,
        'plate_detection': plate_detection,
        'legal_validation': (pericial or {}).get('legal_validation', {}) if isinstance(pericial, dict) else {},
        'capture_integrity': (pericial or {}).get('capture_integrity', {}) if isinstance(pericial, dict) else {},
        'character_ambiguity': (pericial or {}).get('character_ambiguity', {}) if isinstance(pericial, dict) else {},
        'operational_protocol': operational_protocol,
    })
    if isinstance(pericial, dict):
        pericial['operational_protocol'] = operational_protocol
        pericial['vehicle_confrontation_form'] = vehicle_confrontation_form
        cross_checks = pericial.setdefault('cross_checks', {})
        if isinstance(cross_checks, dict):
            cross_checks['operational_protocol'] = operational_protocol
            cross_checks['vehicle_confrontation_form'] = vehicle_confrontation_form
    engine_runtime = {
        'paddleocr': {
            'enabled': bool(PADDLEOCR_ENABLED and PaddleOCR is not None),
            'ready': bool(PADDLEOCR_RUNTIME.get('ready')),
            'error': str(PADDLEOCR_RUNTIME.get('error', '') or ''),
        },
        'yolo_detector': {
            'enabled': bool(YOLO_DETECTOR_ENABLED and YOLO is not None and bool(YOLO_MODEL_PATH)),
            'ready': bool(YOLO_RUNTIME.get('ready')),
            'error': str(YOLO_RUNTIME.get('error', '') or ''),
        },
    }

    pdf_report = None
    if analysis_stage != 'preview':
        try:
            recognized_text = (best_payload or {}).get('text', '') if isinstance(best_payload, dict) else ''
            pdf_report = build_pdf_report(
                photo_source_path,
                placa_path,
                recognized_text,
                raw_crop_path or placa_path,
                placa_path,
                forensic=forensic,
                consensus=consensus,
                assessment=assessment,
                pericial=pericial,
                visual_profile=visual_profile,
                external_systems_comparison=external_systems_comparison,
                ocr_engines=ocr_results,
                ocr_engine_status=engine_status,
                ocr_engine_summary=ocr_engine_summary,
            engine_runtime=engine_runtime,
            input_meta=input_meta,
            warnings=warnings,
            human_review=human_review,
            operational_protocol=operational_protocol,
        )
        except Exception as exc:
            warnings.append(f'pdf_report_failed: {exc}')

    return jsonify({
        'ocr': ocr_results,
        'best': best_payload,
        'top_candidates': top_candidates,
        'char_options': char_options,
        'regions_tested': (ocr_results.get('tesseract', {}).get('regions_tested', []) if isinstance(ocr_results.get('tesseract'), dict) else []),
        'color_info': plate_pattern_info,
        'plate_pattern_info': plate_pattern_info,
        'adulteracao': adulterado,
        'forensic': forensic,
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'visual_profile': visual_profile,
        'assisted_vehicle_identification': assisted_vehicle_identification,
        'external_systems_comparison': external_systems_comparison,
        'ocr_engine_status': engine_status,
        'ocr_engine_summary': ocr_engine_summary,
        'ocr_reranking_calibration': reranking_calibration,
        'engine_runtime': engine_runtime,
        'analysis_stage': analysis_stage,
        'report_ready': analysis_stage != 'preview',
        'plate_detection': plate_detection,
        'capture_integrity': (pericial.get('capture_integrity', {}) if isinstance(pericial, dict) else {}),
        'operational_protocol': operational_protocol,
        'vehicle_confrontation_form': vehicle_confrontation_form,
        'pdf_report': pdf_report,
        'scene_preprocess': input_meta.get('scene_preprocess', {}),
        'scene_profile': (input_meta.get('scene_preprocess', {}) or {}).get('scene_profile', {}),
        'human_review': human_review,
        'analysis_report_outline': get_analysis_report_outline(),
        'report_context': {
            'analysis_id': analysis_id,
            'photo_filename': os.path.basename(photo_source_path),
            'plate_filename': os.path.basename(placa_path),
            'crop_raw_path': raw_crop_path or placa_path,
            'crop_treated_path': placa_path,
            'visual_scene_filename': str(input_meta.get('visual_scene_filename', '') or ''),
            'forensic': forensic,
            'consensus': consensus,
            'assessment': assessment,
            'pericial': pericial,
            'visual_profile': visual_profile,
            'assisted_vehicle_identification': assisted_vehicle_identification,
            'external_systems_comparison': external_systems_comparison,
            'ocr_engine_status': engine_status,
            'ocr_engine_summary': ocr_engine_summary,
            'ocr_reranking_calibration': reranking_calibration,
            'engine_runtime': engine_runtime,
            'plate_detection': plate_detection,
            'input_meta': input_meta,
            'operational_protocol': operational_protocol,
            'vehicle_confrontation_form': vehicle_confrontation_form,
            'human_review': human_review,
            'analysis_report_outline': get_analysis_report_outline(),
        },
        'input_meta': input_meta,
        'analysis_report_outline': get_analysis_report_outline(),
        'threshold_used': OCR_MIN_CONFIDENCE,
        'pattern_threshold_used': OCR_PATTERN_MIN_CONFIDENCE,
        'warnings': warnings,
    })



def run_ocr_ensemble_core(ocr_regions, input_meta, input_warnings, pr_result=None, pr_plate=''):
    ocr_results = {}
    warnings = list(input_warnings)
    engine_status = {}
    plate_detection = input_meta.get('plate_detection', {}) if isinstance(input_meta, dict) else {}

    tesseract_res = ocr_tesseract_regions(ocr_regions)
    tesseract_error = str(tesseract_res.get('error', '') or '')
    tesseract_available = bool(TESSERACT_CMD and os.path.exists(TESSERACT_CMD))
    engine_status['tesseract'] = {
        'enabled': True,
        'available': bool(tesseract_available),
        'executed': bool(tesseract_available),
        'status': 'unavailable' if 'tesseract_not_installed' in tesseract_error else 'executed',
        'reason': 'tesseract_not_installed' if 'tesseract_not_installed' in tesseract_error else 'ok',
        'has_text': bool(normalize_plate_text(tesseract_res.get('text', ''))),
    }

    # Ensemble Thresholds & Multi-Engine Logic
    run_easyocr = (EASYOCR_ENABLED and easyocr is not None and (FORCE_ENSEMBLE or not tesseract_res.get('text') or float(tesseract_res.get('score', 0)) < 115))
    easyocr_res = ocr_easyocr_regions(ocr_regions) if run_easyocr else None

    run_rapidocr = (RAPIDOCR_ENABLED and RapidOCR is not None and (FORCE_ENSEMBLE or easyocr_res is None or float(easyocr_res.get('score', 0)) < 118))
    rapidocr_res = ocr_rapidocr_regions(ocr_regions) if run_rapidocr else None

    best_pre_paddle_score = max(float(tesseract_res.get('score', 0)), float(easyocr_res.get('score', 0)) if easyocr_res else 0.0, float(rapidocr_res.get('score', 0)) if rapidocr_res else 0.0)
    run_paddleocr = (PADDLEOCR_ENABLED and PaddleOCR is not None and (FORCE_ENSEMBLE or best_pre_paddle_score < 119))
    paddleocr_res = ocr_paddleocr_regions(ocr_regions) if run_paddleocr else None

    # Deep Forensic Vision Models (TrOCR / docTR)
    pre_core_texts = [normalize_plate_text(c.get('text', '')) for c in (tesseract_res, easyocr_res, rapidocr_res, paddleocr_res) if isinstance(c, dict) and len(normalize_plate_text(c.get('text', ''))) == 7]
    pre_core_consensus = len(pre_core_texts) >= 2 and len(set(pre_core_texts)) == 1

    best_pre_trocr_score = max(best_pre_paddle_score, float(paddleocr_res.get('score', 0)) if paddleocr_res else 0.0)
    run_trocr = TROCR_ENABLED and (FORCE_ENSEMBLE or not pre_core_consensus or best_pre_trocr_score < 121)
    if run_trocr and not ALLOW_HEAVY_COLDSTART and not trocr_bundle_is_warm(): run_trocr = False
    trocr_res = ocr_trocr_regions(ocr_regions) if run_trocr else None

    best_pre_doctr_score = max(best_pre_trocr_score, float(trocr_res.get('score', 0)) if trocr_res else 0.0)
    run_doctr = DOCTR_ENABLED and (FORCE_ENSEMBLE or best_pre_doctr_score < 123)
    if run_doctr and not ALLOW_HEAVY_COLDSTART and not doctr_predictor_is_warm(): run_doctr = False
    doctr_res = ocr_doctr_regions(ocr_regions) if run_doctr else None

    # Normalization & Assembly
    if isinstance(pr_result, dict):
        ocr_results['plate_recognizer'] = {
            'text': pr_plate, 'avg_conf': float(parse_float(pr_result.get('avg_conf'), 0.0)),
            'score': float(parse_float(pr_result.get('score'), 0.0)), 'pattern': pr_result.get('pattern', 'Indefinido'),
            'region': 'plate_recognizer_api'
        }

    ocr_results.update({'tesseract': tesseract_res})
    if easyocr_res: ocr_results['easyocr'] = easyocr_res
    if rapidocr_res: ocr_results['rapidocr'] = rapidocr_res
    if paddleocr_res: ocr_results['paddleocr'] = paddleocr_res
    if trocr_res: ocr_results['trocr'] = trocr_res
    if doctr_res: ocr_results['doctr'] = doctr_res

    geometry_refine_res = build_geometry_refine_result(ocr_results, plate_detection=plate_detection)
    if isinstance(geometry_refine_res, dict) and normalize_plate_text(geometry_refine_res.get('text', '')):
        ocr_results['geometry_refine'] = geometry_refine_res
        engine_status['geometry_refine'] = {
            'enabled': True,
            'available': True,
            'executed': True,
            'status': 'executed',
            'reason': 'tail_digit_geometry_refine',
            'has_text': True,
        }
    else:
        engine_status['geometry_refine'] = {
            'enabled': True,
            'available': True,
            'executed': False,
            'status': 'skipped',
            'reason': 'tail_digit_geometry_not_applicable',
            'has_text': False,
        }

    # PDF Probe Injection
    if input_meta.get('input_type') == 'pdf' and input_meta.get('page_selected_text_probe'):
         p_text = normalize_plate_text(input_meta.get('page_selected_text_probe'))
         ocr_results['pdf_probe'] = {'text': p_text, 'avg_conf': 65.0, 'score': 100.0, 'pattern': detect_plate_pattern(p_text)}

    # Reranking & Final Decision
    best_engine, best_res = get_best_result(ocr_results, plate_detection=plate_detection)
    top_candidates = build_top_candidates(ocr_results, plate_detection=plate_detection)
    if not isinstance(top_candidates, list):
        top_candidates = []
    if not isinstance(best_res, dict):
        if top_candidates and isinstance(top_candidates[0], dict):
            best_res = dict(top_candidates[0])
        else:
            best_res = {
                'text': '',
                'avg_conf': 0.0,
                'score': 0.0,
                'pattern': 'Indefinido',
                'support_count': 0,
                'support_rank': 0.0,
                'style_rank_priority': 0.0,
                'weighted_support': 0.0,
            }

    return {
        'best_engine': best_engine,
        'best_result': best_res,
        'top_candidates': top_candidates,
        'ocr_results': ocr_results,
        'warnings': warnings,
        'engine_status': engine_status
    }

@app.route('/enrich_report', methods=['POST'])
def enrich_report():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict(flat=True)

    report_context = payload.get('report_context', {})
    if isinstance(report_context, str):
        try:
            report_context = json.loads(report_context)
        except Exception:
            report_context = {}
    if not isinstance(report_context, dict):
        report_context = {}

    photo_filename = report_context.get('photo_filename') or payload.get('photo_filename')
    plate_filename = report_context.get('plate_filename') or payload.get('plate_filename')
    analysis_id = report_context.get('analysis_id') or payload.get('analysis_id')
    ocr_text = str(payload.get('ocr_text', '') or '')
    origem = str(payload.get('origem', 'web') or 'web')
    vehicle_info = parse_vehicle_info(payload.get('vehicle_info'))
    forensic = parse_json_dict(payload.get('forensic') or report_context.get('forensic'))
    consensus = parse_json_dict(payload.get('consensus') or report_context.get('consensus'))
    assessment = parse_json_dict(payload.get('assessment') or report_context.get('assessment'))
    pericial = parse_json_dict(payload.get('pericial') or report_context.get('pericial'))
    visual_profile = parse_json_dict(payload.get('visual_profile') or report_context.get('visual_profile'))
    external_systems_comparison = parse_json_dict(
        payload.get('external_systems_comparison') or report_context.get('external_systems_comparison')
    )
    ocr_engines = parse_json_dict(payload.get('ocr_engines'))
    ocr_engine_status = parse_json_dict(payload.get('ocr_engine_status') or report_context.get('ocr_engine_status'))
    ocr_engine_summary = parse_json_dict(payload.get('ocr_engine_summary') or report_context.get('ocr_engine_summary'))
    input_meta = parse_json_dict(payload.get('input_meta') or report_context.get('input_meta'))
    human_review = parse_json_dict(payload.get('human_review') or report_context.get('human_review'))
    operational_protocol = parse_json_dict(payload.get('operational_protocol') or report_context.get('operational_protocol'))
    warnings = parse_json_list(payload.get('warnings'))
    if analysis_id and isinstance(forensic, dict) and not forensic.get('analysis_id'):
        forensic['analysis_id'] = str(analysis_id)

    photo_path = resolve_upload_file(photo_filename)
    plate_path = resolve_upload_file(plate_filename)
    if not photo_path or not plate_path:
        return jsonify({'error': 'Arquivos de contexto do relatorio nao encontrados'}), 404

    try:
        pdf_report = build_pdf_report(
            photo_path,
            plate_path,
            ocr_text,
            crop_raw_path=report_context.get('crop_raw_path') or payload.get('crop_raw_path') or plate_path,
            crop_treated_path=report_context.get('crop_treated_path') or payload.get('crop_treated_path') or plate_path,
            vehicle_info=vehicle_info,
            origem=origem,
            forensic=forensic,
            consensus=consensus,
            assessment=assessment,
            pericial=pericial,
            visual_profile=visual_profile,
            external_systems_comparison=external_systems_comparison,
            ocr_engines=ocr_engines,
            ocr_engine_status=ocr_engine_status,
            ocr_engine_summary=ocr_engine_summary,
            engine_runtime=parse_json_dict(payload.get('engine_runtime') or report_context.get('engine_runtime')),
            input_meta=input_meta,
            warnings=warnings,
            human_review=human_review,
            operational_protocol=operational_protocol,
        )
    except Exception as exc:
        return jsonify({'error': f'Falha ao atualizar relatorio: {exc}'}), 500

    return jsonify({
        'status': 'ok',
        'pdf_report': pdf_report,
        'origem': origem,
        'vehicle_info_included': bool(vehicle_info),
        'visual_profile_included': bool(visual_profile),
        'external_systems_comparison_included': bool(external_systems_comparison),
        'analysis_id': analysis_id,
    })


@app.route('/process_simple', methods=['POST'])
@safe_route
def process_image_simple():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    analysis_mode = str(request.form.get('analysis_mode', 'image') or 'image').strip().lower()
    if analysis_mode == 'triage_image':
        analysis_mode = 'triage'
    if analysis_mode not in ('image', 'video_frame', 'triage'):
        analysis_mode = 'image'
    analysis_stage = str(request.form.get('analysis_stage', 'final') or 'final').strip().lower()
    if analysis_stage not in ('preview', 'final'):
        analysis_stage = 'final'
    video_parent_analysis_id = str(request.form.get('video_parent_analysis_id', '') or '').strip()
    video_frame_index = parse_int(request.form.get('video_frame_index'), -1)
    video_frame_timestamp = parse_float(request.form.get('video_frame_timestamp'), -1.0)

    file = request.files['image']
    filename = sanitize_filename(file.filename)
    analysis_id = uuid.uuid4().hex
    filepath = os.path.join(
        app.config['UPLOAD_FOLDER'],
        build_unique_artifact_filename(filename, analysis_id, default_extension=os.path.splitext(filename)[1] or '.jpg'),
    )
    file.save(filepath)

    started_utc = utc_iso_now()
    _trace = make_trace(analysis_id)

    img, photo_source_path, input_meta, input_warnings = load_input_for_ocr(filepath, filename, getattr(file, 'content_type', '') or '')
    if img is None:
        return jsonify({'error': input_meta.get('error', 'Erro ao ler arquivo')}), 400

    # --- EXIF Metadata Enrichment ---
    exif_raw = input_meta.get('exif', {})
    capture_metadata = {
        'camera_make': str(exif_raw.get('Make', '') or '').strip() or None,
        'camera_model': str(exif_raw.get('Model', '') or '').strip() or None,
        'camera': input_meta.get('camera') or 'Generic Forensic Capture',
        'datetime_original': str(exif_raw.get('DateTimeOriginal', '') or '').strip() or None,
        'datetime_digitized': str(exif_raw.get('DateTimeDigitized', '') or '').strip() or None,
        'timestamp': input_meta.get('timestamp') or None,
        'resolution': input_meta.get('source_resolution', {}),
        'orientation': exif_raw.get('Orientation'),
        'software': str(exif_raw.get('Software', '') or '').strip() or None,
        'exposure_time': exif_raw.get('ExposureTime'),
        'f_number': exif_raw.get('FNumber'),
        'iso': exif_raw.get('ISOSpeedRatings'),
        'focal_length': exif_raw.get('FocalLength'),
        'flash': exif_raw.get('Flash'),
        'gps_available': bool(exif_raw.get('GPSInfo')),
        'exif_present': bool(exif_raw),
    }
    input_meta['capture_metadata'] = capture_metadata
    input_meta['analysis_mode'] = analysis_mode
    if analysis_mode == 'video_frame':
        input_meta['video_context'] = {
            'parent_analysis_id': video_parent_analysis_id,
            'frame_index': video_frame_index,
            'frame_timestamp_seconds': video_frame_timestamp if video_frame_timestamp >= 0 else None,
        }
    if analysis_mode == 'triage':
        triage_payload = run_image_quick_triage(img, input_meta, input_warnings, analysis_id)
        triage_payload['capture_metadata'] = capture_metadata
        triage_payload['analysis_stage'] = analysis_stage
        return jsonify(triage_payload)

    # --- Forensic Scene Pre-processing ---
    with _trace.span("scene_preprocess"):
        pre_scene, scene_meta = preprocess_scene_for_ocr(img)
    scene_uses_enhanced = str((scene_meta or {}).get('selected', 'original')) == 'enhanced'
    ocr_scene = pre_scene if scene_uses_enhanced else img
    secondary_scene = img if scene_uses_enhanced else None
    input_meta['scene_preprocess'] = scene_meta
    input_meta['scene_selected'] = 'enhanced' if scene_uses_enhanced else 'original'

    # --- Detection of all potential plate regions ---
    with _trace.span("plate_detection"):
        regions = build_plate_regions_multisource(ocr_scene, None, secondary_img=secondary_scene)
        if input_meta.get('input_type') == 'pdf':
            regions = limit_regions_for_pdf(regions)
        plate_detection = build_plate_detection_summary(regions)
    input_meta['plate_detection'] = plate_detection
    ocr_regions = budget_regions_for_speed(regions, plate_detection)

    # --- Forensic Ensemble Execution ---
    with _trace.span("ocr_ensemble"):
        ensemble_data = run_ocr_ensemble_core(ocr_regions, input_meta, input_warnings)
    best_result = ensemble_data['best_result']
    top_candidates = ensemble_data['top_candidates']
    # Garante que o ocr_results seja sempre um dicionário com as chaves esperadas
    ocr_results = ensemble_data['ocr_results']
    expected_engines = ['tesseract', 'easyocr', 'rapidocr', 'paddleocr', 'trocr', 'doctr', 'geometry_refine', 'plate_recognizer', 'pdf_probe']
    default_result = {'text': '', 'avg_conf': 0.0, 'score': 0.0, 'pattern': 'Indefinido'}
    if not isinstance(ocr_results, dict):
        ocr_results = {}
    for engine in expected_engines:
        res = ocr_results.get(engine)
        if not isinstance(res, dict):
            ocr_results[engine] = dict(default_result)
        else:
            # Garante as chaves mínimas
            for k, v in default_result.items():
                if k not in ocr_results[engine]:
                    ocr_results[engine][k] = v
    warnings = ensemble_data['warnings']
    best_engine = ensemble_data.get('best_engine', '')

    # --- Consensus & Assessment ---
    with _trace.span("consensus_assessment"):
        consensus = build_consensus_report(ocr_results, preferred_text=best_result.get('text', ''))
        legal_validation = validate_plate_by_law(best_result.get('text', ''))
        pattern_info = build_plate_pattern_info(best_payload=best_result, legal_validation=legal_validation, plate_detection=plate_detection)
        quality_report = analyze_plate_quality(ocr_scene)
        capture_integrity = build_capture_integrity_summary(input_meta, plate_detection)
        character_ambiguity = build_character_ambiguity_report(top_candidates)
        adulterado = detect_adulteration(ocr_scene)
        assessment = build_assessment(best_result, consensus, warnings, adulterado)

    # --- Visual Profile ---
    with _trace.span("visual_profile"):
        visual_profile = analyze_vehicle_visual_profile(ocr_scene)

    partial_plate_evidence = build_partial_plate_evidence(
        ocr_results,
        top_candidates=top_candidates,
        plate_detection=plate_detection,
        context={
            'analysis_mode': analysis_mode,
            'analysis_id': analysis_id,
            'frame_index': video_frame_index if video_frame_index >= 0 else -1,
            'frame_order': video_frame_index if video_frame_index >= 0 else -1,
            'timestamp_seconds': video_frame_timestamp if video_frame_timestamp >= 0 else -1.0,
            'frame_path': filepath,
            'crop_raw_path': plate_detection.get('selected_raw_path', ''),
            'crop_treated_path': plate_detection.get('selected_treated_path', ''),
        },
        max_candidates=8,
    )
    input_meta['partial_plate_evidence'] = partial_plate_evidence

    # --- Multi-Target Detection ---
    targets = []
    texts_found = set()
    # Primary target from ensemble consensus
    primary_text = normalize_plate_text(best_result.get('text', ''))
    if primary_text and len(primary_text) >= 6:
        targets.append({
            'text': primary_text,
            'engine': best_engine or 'ensemble',
            'conf': float(best_result.get('avg_conf', 0)),
            'pattern': best_result.get('pattern', 'Indefinido'),
            'role': 'primary',
        })
        texts_found.add(primary_text)
    # Secondary targets from other engines
    for engine_name, engine_res in ocr_results.items():
        if not isinstance(engine_res, dict):
            continue
        txt = normalize_plate_text(engine_res.get('text', ''))
        if txt and len(txt) >= 6 and txt not in texts_found:
            targets.append({
                'text': txt,
                'engine': engine_name,
                'conf': float(engine_res.get('avg_conf', 0)),
                'pattern': engine_res.get('pattern', 'Indefinido'),
                'role': 'secondary',
            })
            texts_found.add(txt)

    # --- Forensic Chain of Custody ---
    source_sha256 = sha256_file(filepath)
    finished_utc = utc_iso_now()
    forensic_chain = build_forensic_chain(analysis_id, filepath, '', started_utc, finished_utc)

    # --- Operational Protocol Assembly ---
    operational_protocol = vehicle_analysis_protocol_module.build_operational_protocol({
        'analysis_id': analysis_id,
        'photo_filename': filename,
        'photo_path': filepath,
        'capture_timestamp_utc': capture_metadata.get('timestamp') or started_utc,
        'source_resolution': input_meta.get('source_resolution', {}),
        'input_meta': input_meta,
        'targets': targets,
        'best_payload': best_result,
        'top_candidates': top_candidates,
        'ocr_results': ocr_results,
        'consensus': consensus,
        'visual_profile': visual_profile,
        'quality_report': quality_report,
        'legal_validation': legal_validation,
        'plate_pattern_info': pattern_info,
        'character_ambiguity': character_ambiguity,
        'partial_plate_evidence': partial_plate_evidence,
        'partial_plate_candidates': partial_plate_evidence.get('partial_plate_candidates', []),
        'partial_plate_summary': partial_plate_evidence.get('partial_plate_summary', '-'),
        'capture_integrity': capture_integrity,
        'pericial': {
            'quality': quality_report,
            'capture_integrity': capture_integrity,
            'legal_validation': legal_validation,
            'character_ambiguity': character_ambiguity,
            'partial_plate_evidence': partial_plate_evidence,
        },
    })
    pericial = {
        'quality': quality_report,
        'capture_integrity': capture_integrity,
        'legal_validation': legal_validation,
        'character_ambiguity': character_ambiguity,
        'partial_plate_evidence': partial_plate_evidence,
    }
    plate_pattern_info = pattern_info
    human_review = {
        'decision': 'pendente',
        'decision_label': 'Pendente',
        'notes': ['Conferência humana obrigatória antes de eventual uso documental.'],
    }

    # --- Enrichments not run in simple mode ---
    external_systems_comparison = {}
    assisted_vehicle_identification = build_assisted_vehicle_identification(
        visual_profile=visual_profile,
        external_systems_comparison=external_systems_comparison,
    )

    # --- Build response payload ---
    payload = {
        'ocr': best_result.get('text', ''),
        'confidence': float(best_result.get('avg_conf', 0)),
        'score': float(best_result.get('score', 0)),
        'pattern': best_result.get('pattern', 'Indefinido'),
        'selection_reason': str(best_result.get('selection_reason', '') or ''),
        'acceptance_reason': str(best_result.get('acceptance_reason', '') or ''),
        'support_count': int(best_result.get('support_count', 1)),
        'support_rank': float(best_result.get('support_rank', best_result.get('support_count', 1))),
        'style_rank_priority': float(best_result.get('style_rank_priority', 0.0)),
        'weighted_support': float(best_result.get('weighted_support', 0.0)),
        'status': 'CONCLUSIVO' if best_result.get('text') else 'INCONCLUSIVO',
        'analysis_mode': analysis_mode,
        'consensus': consensus,
        'assessment': assessment,
        'visual_profile': visual_profile,
        'assisted_vehicle_identification': assisted_vehicle_identification,
        'external_systems_comparison': external_systems_comparison,
        'targets': targets,
        'targets_detected': len(targets),
        'capture_metadata': capture_metadata,
        'forensic_chain': forensic_chain,
        'operational_protocol': operational_protocol,
        'input_meta': input_meta,
        'partial_plate_candidates': partial_plate_evidence.get('partial_plate_candidates', []),
        'partial_plate_candidates_count': partial_plate_evidence.get('partial_plate_candidates_count', 0),
        'partial_plate_has_evidence': partial_plate_evidence.get('partial_plate_has_evidence', False),
        'partial_plate_text': partial_plate_evidence.get('partial_plate_text', '-'),
        'partial_plate_summary': partial_plate_evidence.get('partial_plate_summary', '-'),
        'warnings': warnings,
        'analysis_id': analysis_id,
    }
    if analysis_mode == 'video_frame':
        payload['frame_context'] = {
            'parent_analysis_id': video_parent_analysis_id,
            'frame_index': video_frame_index,
            'frame_timestamp_seconds': video_frame_timestamp if video_frame_timestamp >= 0 else None,
            'artifact_name': os.path.basename(filepath),
        }

    # --- PDF Investigation Report ---
    if analysis_mode != 'video_frame':
        try:
            reports_dir = app.config['UPLOAD_FOLDER']
            report_filename = build_unique_artifact_filename(
                filename,
                analysis_id,
                prefix='Relatorio_',
                default_extension='.pdf',
                force_extension=True,
            )
            report_path = os.path.join(reports_dir, report_filename)

            # Build comprehensive EXIF/metadata block for the report
            resolution = input_meta.get('source_resolution', {})
            report_metadata = dict(capture_metadata)
            report_metadata['resolution'] = f"{resolution.get('width', '?')}x{resolution.get('height', '?')}"
            selected_crop_path = str(plate_detection.get('selected_path', filepath) or filepath)
            selected_raw_path = str(
                plate_detection.get('selected_raw_path', '')
                or plate_detection.get('selected_path', filepath)
                or filepath
            )
            selected_treated_path = str(
                plate_detection.get('selected_treated_path', '')
                or plate_detection.get('selected_path', filepath)
                or selected_raw_path
            )

            report_data = {
                'original_path': filepath,
                'crop_path': selected_crop_path,
                'crop_raw_path': selected_raw_path,
                'crop_treated_path': selected_treated_path,
                'scenario_label': (scene_meta or {}).get('scenario_display_label', 'Indeterminado'),
                'tech_details': (scene_meta or {}).get('strategy', 'Analise automatica de histograma e contraste'),
                'metadata': report_metadata,
                'forensic_steps': (scene_meta or {}).get('steps', []),
                'targets': targets,
                'ocr_results': ocr_results,
                'consensus': consensus,
                'assessment': assessment,
                'suggested_vehicle': str((assisted_vehicle_identification or {}).get('label', 'Indeterminado') or 'Indeterminado'),
                'visual_profile': visual_profile,
                'assisted_vehicle_identification': assisted_vehicle_identification,
                'external_systems_comparison': external_systems_comparison,
                'forensic_chain': forensic_chain,
                'operational_protocol': operational_protocol,
                'summary': operational_protocol.get('conclusion', {}).get('summary', ''),
                'analysis_id': analysis_id,
                'analysis_stage': analysis_stage,
                'pericial': pericial,
                'capture_integrity': (pericial or {}).get('capture_integrity', {}) if isinstance(pericial, dict) else {},
                'plate_detection': plate_detection,
                'plate_pattern_info': plate_pattern_info,
                'human_review': human_review,
                'input_meta': input_meta,
                'analysis_report_outline': get_analysis_report_outline(),
                'report_path': report_path,
                'partial_plate_candidates': partial_plate_evidence.get('partial_plate_candidates', []),
                'partial_plate_candidates_count': partial_plate_evidence.get('partial_plate_candidates_count', 0),
                'partial_plate_has_evidence': partial_plate_evidence.get('partial_plate_has_evidence', False),
                'partial_plate_text': partial_plate_evidence.get('partial_plate_text', '-'),
                'partial_plate_summary': partial_plate_evidence.get('partial_plate_summary', '-'),
            }

            manifest_kind = 'video_frame' if analysis_mode == 'video_frame' else 'image'
            evidence_manifest = _build_and_store_evidence_manifest(report_data, manifest_kind, reports_dir, analysis_id)
            report_data['evidence_manifest'] = evidence_manifest
            report_data['evidence_manifest_path'] = evidence_manifest.get('manifest_path', '')
            report_data['evidence_manifest_url'] = evidence_manifest.get('manifest_url', '')
            report_data['evidence_manifest_fingerprint'] = evidence_manifest.get('manifest_fingerprint', '')

            generate_investigation_report(report_data, report_path)
            payload['report_url'] = f"/pdf/{report_filename}"
            payload['manifest_url'] = evidence_manifest.get('manifest_url', '')
            payload['manifest_path'] = evidence_manifest.get('manifest_path', '')
            payload['manifest_fingerprint'] = evidence_manifest.get('manifest_fingerprint', '')
            payload['evidence_manifest_url'] = evidence_manifest.get('manifest_url', '')
            payload['evidence_manifest_path'] = evidence_manifest.get('manifest_path', '')
            payload['evidence_manifest_fingerprint'] = evidence_manifest.get('manifest_fingerprint', '')
        except Exception as pdf_error:
            import traceback
            traceback.print_exc()
            payload['report_error'] = str(pdf_error)

    _trace.flush_to_log()
    if get_telemetry_in_payload():
        payload['telemetry'] = _trace.to_dict()

    return jsonify(payload)


@app.route('/process_video', methods=['POST'])
@safe_route
def process_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video uploaded'}), 400

    analysis_stage = str(request.form.get('analysis_stage', 'preview') or 'preview').strip().lower()
    if analysis_stage not in ('preview', 'final'):
        analysis_stage = 'preview'

    preview_candidate_limit = parse_int(request.form.get('frame_limit'), parse_int(os.environ.get('GROM_OCR_VIDEO_SAMPLE_FRAMES'), 12))
    preview_candidate_limit = max(6, min(preview_candidate_limit, 48))

    analysis_id = f"video_{uuid.uuid4().hex[:16]}"
    file = request.files['video']
    filename = sanitize_filename(file.filename)
    filepath = os.path.join(
        app.config['UPLOAD_FOLDER'],
        build_unique_artifact_filename(filename, analysis_id, default_extension=os.path.splitext(filename)[1] or '.mp4'),
    )
    file.save(filepath)

    security = inspect_upload_video_file(filepath, filename, getattr(file, 'content_type', '') or '')
    if not security.get('allowed', False):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        return jsonify({
            'error': security.get('error', 'Video nao suportado'),
            'input_meta': {'input_security': security, 'input_type': 'video'},
        }), 400

    started_utc = utc_iso_now()
    video_metadata = probe_video_metadata(filepath)
    video_metadata['input_security'] = security
    video_metadata['analysis_id'] = analysis_id
    video_metadata['analysis_stage'] = analysis_stage

    max_duration_seconds = float(security.get('max_duration_seconds', 600) or 600)
    if float(video_metadata.get('duration_seconds', 0.0) or 0.0) > max_duration_seconds:
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        return jsonify({
            'error': 'Video excede o limite de 10 minutos',
            'video_metadata': video_metadata,
        }), 400

    duration_seconds = float(video_metadata.get('duration_seconds', 0.0) or 0.0)
    scan_frame_limit = int(video_metadata.get('frame_count', 0) or 0)
    if scan_frame_limit <= 0:
        scan_frame_limit = max(12, preview_candidate_limit)

    if not video_metadata.get('opened', False):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        return jsonify({
            'error': 'Falha ao abrir o video para decodificacao',
            'video_metadata': video_metadata,
        }), 400

    frame_entries, probed_metadata = sample_video_frames(
        filepath,
        analysis_id,
        max_frames=scan_frame_limit,
        save_dir=app.config['UPLOAD_FOLDER'],
    )
    if not frame_entries:
        return jsonify({
            'error': 'Nao foi possivel extrair quadros do video',
            'video_metadata': video_metadata,
            'probe_metadata': probed_metadata,
        }), 400

    frame_results = []
    frame_failures = []
    with app.test_client() as client:
        for entry in frame_entries:
            frame_path = str(entry.get('frame_path', '') or '').strip()
            frame_name = str(entry.get('frame_name', '') or '').strip() or os.path.basename(frame_path)
            if not frame_path or not os.path.exists(frame_path):
                frame_failures.append({
                    'frame_order': entry.get('frame_order', 0),
                    'frame_index': entry.get('frame_index', 0),
                    'error': 'frame_not_saved',
                })
                continue

            try:
                with open(frame_path, 'rb') as frame_stream:
                    response = client.post(
                        '/process_simple',
                        data={
                            'analysis_mode': 'video_frame',
                            'analysis_stage': analysis_stage,
                            'video_parent_analysis_id': analysis_id,
                            'video_frame_index': str(entry.get('frame_index', 0)),
                            'video_frame_timestamp': str(entry.get('timestamp_seconds', 0.0)),
                            'image': (frame_stream, frame_name),
                        },
                        content_type='multipart/form-data',
                    )
            except Exception as exc:
                frame_failures.append({
                    'frame_order': entry.get('frame_order', 0),
                    'frame_index': entry.get('frame_index', 0),
                    'error': str(exc),
                })
                continue

            result = response.get_json(silent=True) if response is not None else None
            if response.status_code != 200 or not isinstance(result, dict):
                frame_failures.append({
                    'frame_order': entry.get('frame_order', 0),
                    'frame_index': entry.get('frame_index', 0),
                    'error': str((result or {}).get('error', f'http_{response.status_code}')),
                })
                continue

            frame_quality = dict(entry.get('quality_metrics', {}))
            frame_context = dict(result.get('frame_context', {})) if isinstance(result.get('frame_context'), dict) else {}
            input_meta = dict(result.get('input_meta', {})) if isinstance(result.get('input_meta'), dict) else {}
            plate_detection = dict(input_meta.get('plate_detection', {})) if isinstance(input_meta.get('plate_detection'), dict) else {}
            crop_raw_path = str(plate_detection.get('selected_raw_path', '') or '').strip()
            crop_treated_path = str(plate_detection.get('selected_treated_path', '') or '').strip()
            frame_url = f"/artifact/{quote_plus(os.path.basename(frame_path))}"
            # Garantir campos obrigatórios para os testes
            response = {
                'ocr': ocr_results if ocr_results is not None else {},
                'best': best_payload if best_payload is not None else {},
                'top_candidates': top_candidates,
                'char_options': char_options,
                'regions_tested': (ocr_results.get('tesseract', {}).get('regions_tested', []) if isinstance(ocr_results.get('tesseract'), dict) else []),
                'color_info': plate_pattern_info,
                'plate_pattern_info': plate_pattern_info,
                'adulteracao': adulterado,
                'forensic': forensic,
                'consensus': consensus if consensus is not None else {},
                'assessment': assessment,
                'pericial': pericial,
                'visual_profile': visual_profile,
                'assisted_vehicle_identification': assisted_vehicle_identification,
                'external_systems_comparison': external_systems_comparison,
                'ocr_engine_status': engine_status,
                'ocr_engine_summary': ocr_engine_summary,
                'ocr_reranking_calibration': reranking_calibration,
                'engine_runtime': engine_runtime,
                'analysis_stage': analysis_stage,
                'report_ready': analysis_stage != 'preview',
                'plate_detection': plate_detection,
                'capture_integrity': (pericial.get('capture_integrity', {}) if isinstance(pericial, dict) else {}),
                'operational_protocol': operational_protocol,
                'vehicle_confrontation_form': vehicle_confrontation_form,
                'pdf_report': pdf_report,
                'scene_preprocess': input_meta.get('scene_preprocess', {}),
                'scene_profile': (input_meta.get('scene_preprocess', {}) or {}).get('scene_profile', {}),
                'human_review': human_review,
                'analysis_report_outline': get_analysis_report_outline(),
                'report_context': {
                    'exif_present': bool(exif_raw),
                },
            }
            # Para compatibilidade com testes: garantir que 'ocr_results' exista
            if 'ocr_results' not in response:
                response['ocr_results'] = ocr_results if ocr_results is not None else {}
            # Para compatibilidade com testes: garantir que 'status' exista
            if 'status' not in response:
                response['status'] = pericial.get('status', 'INCONCLUSIVO') if isinstance(pericial, dict) else 'INCONCLUSIVO'
            return jsonify(response)
        best_frame = dict(ranked_frames[0])
    selected_target_default = _resolve_default_video_target(video_candidates_all, best_frame)
    selected_candidate_ids_default = [str(selected_target_default.get('candidate_id', '') or '').strip()] if str(selected_target_default.get('candidate_id', '') or '').strip() else []

    best_result = {
        'text': str(best_frame.get('ocr', '') or ''),
        'avg_conf': float(best_frame.get('confidence', 0.0) or 0.0),
        'score': float(best_frame.get('score', 0.0) or 0.0),
        'pattern': str(best_frame.get('pattern', 'Indefinido') or 'Indefinido'),
    }
    best_input_meta = dict(best_frame.get('input_meta', {})) if isinstance(best_frame.get('input_meta'), dict) else {}
    best_plate_detection = dict(best_input_meta.get('plate_detection', {})) if isinstance(best_input_meta.get('plate_detection'), dict) else {}
    best_frame_path = str(best_frame.get('frame_path', '') or '')
    best_crop_raw_path = str(best_frame.get('crop_raw_path', '') or best_plate_detection.get('selected_raw_path', '') or '')
    best_crop_treated_path = str(best_frame.get('crop_treated_path', '') or best_plate_detection.get('selected_treated_path', '') or '')
    best_crop_preview_path = best_crop_treated_path or best_crop_raw_path or best_frame_path

    video_consensus_count = int(selection.get('consensus_count', 0) or 0)
    video_frames_considered = len(frame_results)
    video_consensus_ratio = round((video_consensus_count / float(video_frames_considered)) * 100.0, 2) if video_frames_considered else 0.0
    consensus = {
        'best_text': str(selection.get('consensus_text', '') or best_result.get('text', '')),
        'agreement_count': video_consensus_count,
        'agreement_ratio': video_consensus_ratio,
        'engines_considered': video_frames_considered,
        'consensus_confidence': float(selection.get('consensus_confidence', 0.0) or 0.0),
        'frames_considered': video_frames_considered,
        'support_count': video_consensus_count,
        'best_frame_index': int(best_frame.get('frame_index', 0) or 0),
        'best_frame_timestamp': float(best_frame.get('timestamp_seconds', 0.0) or 0.0),
    }

    assessment = dict(best_frame.get('assessment', {})) if isinstance(best_frame.get('assessment', {}), dict) else {}
    if not assessment:
        payload = {
            'ocr': best_result.get('text', ''),
            'confidence': float(best_result.get('avg_conf', 0)),
            'score': float(best_result.get('score', 0)),
            'pattern': best_result.get('pattern', 'Indefinido'),
            'selection_reason': str(best_result.get('selection_reason', '') or ''),
            'acceptance_reason': str(best_result.get('acceptance_reason', '') or ''),
            'support_count': int(best_result.get('support_count', 1)),
            'support_rank': float(best_result.get('support_rank', best_result.get('support_count', 1))),
            'style_rank_priority': float(best_result.get('style_rank_priority', 0.0)),
            'weighted_support': float(best_result.get('weighted_support', 0.0)),
            'status': 'CONCLUSIVO' if best_result.get('text') else 'INCONCLUSIVO',
            'analysis_mode': analysis_mode,
            'consensus': consensus if consensus is not None else {},
            'assessment': assessment,
            'visual_profile': visual_profile,
            'assisted_vehicle_identification': assisted_vehicle_identification,
            'external_systems_comparison': external_systems_comparison,
            'targets': targets if isinstance(targets, list) else [],
            'targets_detected': len(targets) if isinstance(targets, list) else 0,
            'capture_metadata': capture_metadata,
            'forensic_chain': forensic_chain,
            'operational_protocol': operational_protocol,
            'input_meta': input_meta,
            'partial_plate_candidates': partial_plate_evidence.get('partial_plate_candidates', []),
            'partial_plate_candidates_count': partial_plate_evidence.get('partial_plate_candidates_count', 0),
            'partial_plate_has_evidence': partial_plate_evidence.get('partial_plate_has_evidence', False),
            'partial_plate_text': partial_plate_evidence.get('partial_plate_text', '-'),
            'partial_plate_summary': partial_plate_evidence.get('partial_plate_summary', '-'),
            'warnings': warnings,
            'analysis_id': analysis_id,
        }
        # Compatibilidade com testes: garantir campos obrigatórios
        # Garantir que 'ocr_results' seja sempre dict (não string)
        # 'ocr_results' deve ser o dicionário detalhado do ensemble, não apenas o texto
        payload['ocr_results'] = ocr_results if isinstance(ocr_results, dict) else {}
        # Garantir que 'targets' seja sempre lista
        if 'targets' not in payload or not isinstance(payload['targets'], list):
            payload['targets'] = targets if isinstance(targets, list) else []
        if 'status' not in payload:
            payload['status'] = payload.get('status', 'INCONCLUSIVO')
        if 'consensus' not in payload:
            payload['consensus'] = consensus if consensus is not None else {}
        return jsonify(payload)

    input_meta = dict(input_meta) if isinstance(input_meta, dict) else {}
    input_meta.update({
        'media_type': 'video',
        'video_probe_ok': bool(video_metadata.get('opened')),
        'decoder_backend': video_metadata.get('backend', 'opencv'),
        'frame_sampling_strategy': 'frame_by_frame_scan',
    })

    frame_sampling = {
        'strategy': 'frame_by_frame_scan',
        'requested_frame_limit': scan_frame_limit,
        'selected_frame_count': len(frame_entries),
        'frame_count_total': int(video_metadata.get('frame_count', 0) or 0),
        'fps': float(video_metadata.get('fps', 0.0) or 0.0),
        'duration_seconds': duration_seconds,
        'scan_interval_seconds': round(duration_seconds / float(max(1, len(frame_entries))), 4) if duration_seconds and frame_entries else 0.0,
        'coverage_label': f'0-{duration_seconds:0.2f}s' if duration_seconds else 'Indefinido',
        'selected_frames': [
            {
                'frame_index': int(entry.get('frame_index', 0) or 0),
                'frame_order': int(entry.get('frame_order', 0) or 0),
                'timestamp_seconds': float(entry.get('timestamp_seconds', 0.0) or 0.0),
                'frame_name': str(entry.get('frame_name', '') or ''),
                'frame_path': str(entry.get('frame_path', '') or ''),
                'frame_url': f"/artifact/{quote_plus(os.path.basename(str(entry.get('frame_path', '') or '')))}",
                'quality_metrics': dict(entry.get('quality_metrics', {})),
            }
            for entry in frame_entries
            if isinstance(entry, dict)
        ],
    }

    contact_sheet_path = build_video_contact_sheet(
        ranked_frames[:6],
        title='Quadros-chave do vídeo',
        subtitle='Seleção temporal ordenada por valor probatório e qualidade visual',
    )
    comparison_sheet_path = build_capture_comparison_sheet(
        best_frame_path,
        best_crop_raw_path,
        best_crop_treated_path,
    )

    artifact_dir = app.config['UPLOAD_FOLDER']
    if contact_sheet_path:
        contact_sheet_name = os.path.basename(contact_sheet_path)
        contact_sheet_target = os.path.join(artifact_dir, contact_sheet_name)
        if os.path.abspath(contact_sheet_path) != os.path.abspath(contact_sheet_target):
            try:
                shutil.copy2(contact_sheet_path, contact_sheet_target)
                contact_sheet_path = contact_sheet_target
            except Exception:
                pass
    if comparison_sheet_path:
        comparison_sheet_name = os.path.basename(comparison_sheet_path)
        comparison_sheet_target = os.path.join(artifact_dir, comparison_sheet_name)
        if os.path.abspath(comparison_sheet_path) != os.path.abspath(comparison_sheet_target):
            try:
                shutil.copy2(comparison_sheet_path, comparison_sheet_target)
                comparison_sheet_path = comparison_sheet_target
            except Exception:
                pass

    finished_utc = utc_iso_now()
    best_plate_path = best_crop_treated_path or best_crop_raw_path or best_frame_path
    video_forensic_chain = build_video_forensic_chain(analysis_id, filepath, best_plate_path, started_utc, finished_utc)

    scan_record = {
        'analysis_id': analysis_id,
        'analysis_stage': analysis_stage,
        'video_path': filepath,
        'video_filename': filename,
        'video_metadata': video_metadata,
        'frame_sampling': frame_sampling,
        'frame_results': frame_results,
        'video_candidates': video_candidates_all,
        'video_candidates_preview': video_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'best_frame': best_frame,
        'best_result': best_result,
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'human_review': human_review,
        'capture_integrity': capture_integrity,
        'video_forensic_chain': video_forensic_chain,
        'frame_failures': frame_failures,
        'source_security': security,
        'contact_sheet_path': contact_sheet_path,
        'comparison_sheet_path': comparison_sheet_path,
        'selected_candidate_ids': selected_candidate_ids_default,
        'selected_frame_index': int(selected_target_default.get('frame_index', best_frame.get('frame_index', 0)) or 0),
        'selected_target': dict(selected_target_default),
        'selected_targets': [dict(selected_target_default)] if selected_target_default else [],
        'created_utc': started_utc,
        'updated_utc': finished_utc,
    }
    scan_record_path = save_video_scan_record(scan_record, app.config['UPLOAD_FOLDER'], analysis_id)

    analysis_report_outline = get_video_analysis_report_outline()
    report_filename = build_unique_artifact_filename(
        filename,
        analysis_id,
        prefix='RelatorioVideo_',
        default_extension='.pdf',
        force_extension=True,
    )
    report_path = os.path.join(app.config['UPLOAD_FOLDER'], report_filename)

    report_data = {
        'analysis_id': analysis_id,
        'analysis_stage': analysis_stage,
        'video_path': filepath,
        'video_filename': filename,
        'video_metadata': video_metadata,
        'frame_sampling': frame_sampling,
        'frame_results': ranked_frames,
        'best_frame': best_frame,
        'best_result': best_result,
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'human_review': human_review,
        'capture_integrity': capture_integrity,
        'analysis_report_outline': analysis_report_outline,
        'contact_sheet_path': contact_sheet_path,
        'comparison_sheet_path': comparison_sheet_path,
        'selected_targets': [dict(selected_target_default)] if selected_target_default else [],
        'selected_candidate_ids': selected_candidate_ids_default,
        'selected_target': dict(selected_target_default),
        'video_candidates_preview': video_candidates_preview,
        'video_candidates_count': len(video_candidates_all),
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'summary': str(pericial.get('summary', '') or ''),
        'conclusion': str(pericial.get('summary', '') or ''),
        'frame_failures': frame_failures,
        'video_forensic_chain': video_forensic_chain,
        'input_meta': {
            'input_type': 'video',
            'analysis_mode': analysis_stage,
            'source_filename': filename,
            'source_path': filepath,
            'source_resolution': {
                'width': int(video_metadata.get('width', 0) or 0),
                'height': int(video_metadata.get('height', 0) or 0),
            },
            'video_metadata': video_metadata,
            'frame_sampling': frame_sampling,
            'capture_integrity': capture_integrity,
            'video_context': {
                'security': security,
                'probe': probed_metadata,
                'analysis_id': analysis_id,
            },
        },
        'scan_record_path': scan_record_path,
        'report_path': report_path,
    }

    evidence_manifest = _build_and_store_evidence_manifest(report_data, 'video', app.config['UPLOAD_FOLDER'], analysis_id)
    report_data['evidence_manifest'] = evidence_manifest
    report_data['evidence_manifest_path'] = evidence_manifest.get('manifest_path', '')
    report_data['evidence_manifest_url'] = evidence_manifest.get('manifest_url', '')
    report_data['evidence_manifest_fingerprint'] = evidence_manifest.get('manifest_fingerprint', '')

    try:
        generate_video_investigation_report(report_data, report_path)
    except Exception as pdf_error:
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': f'Falha ao gerar relatorio de video: {pdf_error}',
            'video_metadata': video_metadata,
            'frame_results': frame_results[:6],
        }), 500

    scan_record.update({
        'analysis_stage': analysis_stage,
        'selected_candidate_ids': selected_candidate_ids_default,
        'selected_target': dict(selected_target_default),
        'selected_targets': [dict(selected_target_default)] if selected_target_default else [],
        'report_path': report_path,
        'report_url': f'/pdf/{report_filename}',
        'final_report_path': report_path,
        'final_report_url': f'/pdf/{report_filename}',
        'evidence_manifest_path': evidence_manifest.get('manifest_path', ''),
        'evidence_manifest_url': evidence_manifest.get('manifest_url', ''),
        'evidence_manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
        'updated_utc': utc_iso_now(),
    })
    scan_record_path = save_video_scan_record(scan_record, app.config['UPLOAD_FOLDER'], analysis_id)

    payload = {
        'status': 'ok',
        'analysis_mode': 'video',
        'analysis_id': analysis_id,
        'analysis_stage': analysis_stage,
        'video_metadata': video_metadata,
        'frame_sampling': frame_sampling,
        'frame_results': frame_results[:6],
        'video_candidates_preview': video_candidates_preview,
        'video_candidates_count': len(video_candidates_all),
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'best_frame': best_frame,
        'best_result': best_result,
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'human_review': human_review,
        'capture_integrity': capture_integrity,
        'video_forensic_chain': video_forensic_chain,
        'report_url': f"/pdf/{report_filename}",
        'contact_sheet_url': f"/artifact/{quote_plus(os.path.basename(contact_sheet_path))}" if contact_sheet_path else '',
        'comparison_sheet_url': f"/artifact/{quote_plus(os.path.basename(comparison_sheet_path))}" if comparison_sheet_path else '',
        'selected_candidate_ids': selected_candidate_ids_default,
        'selected_target': dict(selected_target_default),
        'selected_targets': [dict(selected_target_default)] if selected_target_default else [],
        'manifest_path': evidence_manifest.get('manifest_path', ''),
        'manifest_url': evidence_manifest.get('manifest_url', ''),
        'manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
        'evidence_manifest_path': evidence_manifest.get('manifest_path', ''),
        'evidence_manifest_url': evidence_manifest.get('manifest_url', ''),
        'evidence_manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
        'frame_failures': frame_failures,
        'video_probe': probed_metadata,
        'analysis_report_outline': analysis_report_outline,
        'warnings': security.get('warnings', []),
    }
    return jsonify(payload)


@app.route('/finalize_video', methods=['POST'])
@safe_route
def finalize_video():
    payload = request.get_json(silent=True)
    analysis_id = ''
    selected_candidate_ids = []

    if isinstance(payload, dict):
        analysis_id = str(payload.get('analysis_id', '') or '').strip()
        selected_candidate_ids = _extract_selected_candidate_ids(payload)

    if not analysis_id:
        analysis_id = str(request.form.get('analysis_id', '') or '').strip()

    if not selected_candidate_ids:
        form_selected_ids = request.form.getlist('selected_candidate_ids[]') or request.form.getlist('selected_candidate_ids')
        if form_selected_ids:
            selected_candidate_ids = [str(item).strip() for item in form_selected_ids if str(item).strip()]

    if not analysis_id:
        return jsonify({'error': 'analysis_id ausente para consolidacao do video'}), 400

    scan_record, scan_record_path = load_video_scan_record(app.config['UPLOAD_FOLDER'], analysis_id)
    if not isinstance(scan_record, dict) or not scan_record:
        return jsonify({'error': 'Registro da analise de video nao encontrado', 'analysis_id': analysis_id}), 404

    video_metadata = dict(scan_record.get('video_metadata', {})) if isinstance(scan_record.get('video_metadata', {}), dict) else {}
    frame_sampling = dict(scan_record.get('frame_sampling', {})) if isinstance(scan_record.get('frame_sampling', {}), dict) else {}
    frame_results = list(scan_record.get('frame_results', [])) if isinstance(scan_record.get('frame_results', []), list) else []
    best_frame = dict(scan_record.get('best_frame', {})) if isinstance(scan_record.get('best_frame', {}), dict) else {}
    best_result = dict(scan_record.get('best_result', {})) if isinstance(scan_record.get('best_result', {}), dict) else {}
    consensus = dict(scan_record.get('consensus', {})) if isinstance(scan_record.get('consensus', {}), dict) else {}
    assessment = dict(scan_record.get('assessment', {})) if isinstance(scan_record.get('assessment', {}), dict) else {}
    pericial = dict(scan_record.get('pericial', {})) if isinstance(scan_record.get('pericial', {}), dict) else {}
    human_review = dict(scan_record.get('human_review', {})) if isinstance(scan_record.get('human_review', {}), dict) else {}
    capture_integrity = dict(scan_record.get('capture_integrity', {})) if isinstance(scan_record.get('capture_integrity', {}), dict) else {}
    video_forensic_chain = dict(scan_record.get('video_forensic_chain', {})) if isinstance(scan_record.get('video_forensic_chain', {}), dict) else {}
    frame_failures = list(scan_record.get('frame_failures', [])) if isinstance(scan_record.get('frame_failures', []), list) else []
    analysis_report_outline = get_video_analysis_report_outline()
    video_candidates_preview = [
        normalize_video_target_entry(candidate)
        for candidate in (scan_record.get('video_candidates_preview', []) if isinstance(scan_record.get('video_candidates_preview', []), list) else [])
        if isinstance(candidate, dict)
    ]
    video_candidates_all = [
        normalize_video_target_entry(candidate)
        for candidate in (scan_record.get('video_candidates', []) if isinstance(scan_record.get('video_candidates', []), list) else [])
        if isinstance(candidate, dict)
    ]
    video_partial_candidates_preview = [
        dict(candidate)
        for candidate in (
            scan_record.get('video_partial_candidates_preview', [])
            if isinstance(scan_record.get('video_partial_candidates_preview', []), list)
            else []
        )
        if isinstance(candidate, dict)
    ]
    video_partial_candidates_all = [
        dict(candidate)
        for candidate in (
            scan_record.get('video_partial_candidates', [])
            if isinstance(scan_record.get('video_partial_candidates', []), list)
            else []
        )
        if isinstance(candidate, dict)
    ]

    if not selected_candidate_ids:
        selected_candidate_ids = [
            str(item).strip()
            for item in scan_record.get('selected_candidate_ids', [])
            if str(item).strip()
        ]

    selected_targets = select_candidates_by_ids(video_candidates_all, selected_candidate_ids)
    if not selected_targets:
        selected_targets = select_candidates_by_ids(video_candidates_preview, selected_candidate_ids)
    if not selected_targets:
        stored_selected_target = scan_record.get('selected_target', {})
        if isinstance(stored_selected_target, dict) and stored_selected_target:
            selected_targets = [normalize_video_target_entry(stored_selected_target)]
    if not selected_targets and best_frame:
        selected_targets = [normalize_video_target_entry(best_frame)]
    if not selected_targets and video_candidates_all:
        selected_targets = [normalize_video_target_entry(video_candidates_all[0])]
    if not selected_targets:
        return jsonify({'error': 'Nenhum alvo selecionado para consolidacao', 'analysis_id': analysis_id}), 400

    primary_target = normalize_video_target_entry(selected_targets[0])
    selected_candidate_ids = [
        str(target.get('candidate_id', '')).strip()
        for target in selected_targets
        if str(target.get('candidate_id', '')).strip()
    ]
    if not selected_candidate_ids and str(primary_target.get('candidate_id', '')).strip():
        selected_candidate_ids = [str(primary_target.get('candidate_id', '')).strip()]

    selected_best_frame = dict(primary_target.get('best_frame', {})) if isinstance(primary_target.get('best_frame', {}), dict) else {}
    if not selected_best_frame:
        selected_best_frame = dict(best_frame)
    if not selected_best_frame:
        selected_best_frame = {
            'ocr': str(primary_target.get('text', '') or best_result.get('text', '') or ''),
            'confidence': float(primary_target.get('avg_confidence', primary_target.get('best_confidence', 0.0)) or 0.0),
            'score': float(primary_target.get('avg_score', primary_target.get('best_score', 0.0)) or 0.0),
            'pattern': str(primary_target.get('pattern', best_result.get('pattern', 'Indefinido')) or 'Indefinido'),
            'frame_path': primary_target.get('frame_path', ''),
            'crop_raw_path': primary_target.get('crop_raw_path', ''),
            'crop_treated_path': primary_target.get('crop_treated_path', ''),
            'timestamp_seconds': primary_target.get('timestamp_seconds', 0.0),
            'frame_index': primary_target.get('frame_index', 0),
            'frame_order': primary_target.get('frame_order', 0),
            'frame_quality': primary_target.get('quality_metrics', {}),
        }

    style_bias_profile = ocr_ensemble_style_bias_profile()
    style_match_rank_credit = parse_float(style_bias_profile.get('style_match_rank_credit', 0.55), 0.55)
    style_match_rank_scale = parse_float(style_bias_profile.get('style_match_rank_scale', 0.22), 0.22)
    style_mismatch_rank_penalty = parse_float(style_bias_profile.get('style_mismatch_rank_penalty', 0.60), 0.60)
    style_mismatch_rank_scale = parse_float(style_bias_profile.get('style_mismatch_rank_scale', 0.20), 0.20)
    leading_d_rank_credit = parse_float(style_bias_profile.get('leading_d_rank_credit', 1.0), 1.0)
    leading_d_rank_scale = parse_float(style_bias_profile.get('leading_d_rank_scale', 0.18), 0.18)
    strong_style_min_confidence = parse_float(style_bias_profile.get('strong_style_min_confidence', 65.0), 65.0)

    selected_best_plate_detection = {}
    if isinstance(selected_best_frame.get('input_meta'), dict):
        maybe_plate_detection = selected_best_frame['input_meta'].get('plate_detection', {})
        if isinstance(maybe_plate_detection, dict):
            selected_best_plate_detection = maybe_plate_detection

    style_context = extract_plate_style_context(selected_best_plate_detection, primary_target)
    style_hint = str(style_context.get('style_hint', 'indefinida') or 'indefinida').strip().lower()
    style_confidence = float(style_context.get('style_confidence', 0.0) or 0.0)
    style_strength = max(0.0, min(1.0, float(style_context.get('style_strength', 0.0) or (style_confidence / 100.0))))
    target_text_for_style = str(
        primary_target.get('text', '')
        or selected_best_frame.get('ocr', '')
        or best_result.get('text', '')
        or ''
    ).strip()
    target_pattern_for_style = str(primary_target.get('pattern', best_result.get('pattern', 'Indefinido')) or 'Indefinido').strip()
    if target_pattern_for_style not in ('Mercosul', 'Antigo'):
        detected_pattern = detect_plate_pattern(normalize_plate_text(target_text_for_style))
        target_pattern_for_style = detected_pattern if detected_pattern in ('Mercosul', 'Antigo') else 'Indefinido'

    derived_style_rank = float(primary_target.get('style_rank_priority', 0.0) or 0.0)
    if derived_style_rank <= 0.0 and style_hint in ('mercosul', 'antigo') and target_pattern_for_style in ('Mercosul', 'Antigo'):
        expected_pattern = 'Mercosul' if style_hint == 'mercosul' else 'Antigo'
        if target_pattern_for_style == expected_pattern:
            derived_style_rank = style_match_rank_credit + (style_strength * style_match_rank_scale)
        else:
            derived_style_rank = -(style_mismatch_rank_penalty + (style_strength * style_mismatch_rank_scale))
        if (
            style_hint == 'antigo'
            and style_confidence >= strong_style_min_confidence
            and target_text_for_style[:1] == 'D'
            and target_pattern_for_style == 'Antigo'
        ):
            derived_style_rank += leading_d_rank_credit + (style_strength * leading_d_rank_scale)

    frames_count_for_target = int(primary_target.get('frames_count', consensus.get('support_count', len(frame_results) or 1)) or len(frame_results) or 1)
    derived_support_rank = float(primary_target.get('support_rank', 0.0) or 0.0)
    if derived_support_rank <= 0.0:
        derived_support_rank = float(frames_count_for_target) + float(derived_style_rank)

    primary_target['style_hint'] = style_hint if style_hint in ('mercosul', 'antigo') else str(primary_target.get('style_hint', 'indefinida') or 'indefinida')
    primary_target['style_confidence'] = round(style_confidence, 2)
    primary_target['style_rank_priority'] = round(derived_style_rank, 3)
    primary_target['support_rank'] = round(derived_support_rank, 3)
    if selected_targets:
        selected_targets[0] = dict(primary_target)

    report_filename = build_unique_artifact_filename(
        str(scan_record.get('video_filename', analysis_id) or analysis_id),
        analysis_id,
        prefix='RelatorioVideo_',
        default_extension='.pdf',
        force_extension=True,
    )
    report_path = os.path.join(app.config['UPLOAD_FOLDER'], report_filename)

    selected_result = {
        'text': str(primary_target.get('text', '') or primary_target.get('best_frame', {}).get('ocr', '') or best_result.get('text', '') or ''),
        'avg_conf': float(primary_target.get('avg_confidence', primary_target.get('best_confidence', 0.0)) or 0.0),
        'score': float(primary_target.get('avg_score', primary_target.get('best_score', 0.0)) or 0.0),
        'pattern': str(primary_target.get('pattern', best_result.get('pattern', 'Indefinido')) or 'Indefinido'),
        'support_count': int(primary_target.get('frames_count', primary_target.get('support_count', 1)) or 1),
        'support_rank': float(primary_target.get('support_rank', primary_target.get('frames_count', 1)) or 1.0),
        'style_rank_priority': float(primary_target.get('style_rank_priority', 0.0) or 0.0),
    }
    if not selected_result['text'] and best_result.get('text'):
        selected_result['text'] = str(best_result.get('text', '') or '')

    video_metadata = dict(video_metadata)
    duration_seconds = float(video_metadata.get('duration_seconds', 0.0) or 0.0)
    scan_frame_limit = int(video_metadata.get('frame_count', 0) or 0)
    if scan_frame_limit <= 0:
        scan_frame_limit = max(12, len(frame_results) or 12)
    frame_sampling = dict(frame_sampling)
    frame_sampling.update({
        'strategy': 'frame_by_frame_scan',
        'requested_frame_limit': scan_frame_limit,
        'selected_frame_count': int(frame_sampling.get('selected_frame_count', len(frame_sampling.get('selected_frames', []))) or len(frame_sampling.get('selected_frames', []))),
        'duration_seconds': duration_seconds,
        'scan_interval_seconds': float(frame_sampling.get('scan_interval_seconds', 0.0) or 0.0),
        'coverage_label': str(frame_sampling.get('coverage_label', '') or f'0-{duration_seconds:0.2f}s'),
    })

    contact_sheet_path = str(scan_record.get('contact_sheet_path', '') or '').strip()
    comparison_sheet_path = str(scan_record.get('comparison_sheet_path', '') or '').strip()
    finished_utc = utc_iso_now()
    best_plate_path = str(selected_best_frame.get('crop_treated_path', '') or selected_best_frame.get('crop_raw_path', '') or selected_best_frame.get('frame_path', '') or '')
    if not best_plate_path:
        best_plate_path = str(primary_target.get('crop_treated_path', '') or primary_target.get('crop_raw_path', '') or primary_target.get('frame_path', '') or '')

    source_path = str(scan_record.get('video_path', '') or '')
    video_forensic_chain = build_video_forensic_chain(analysis_id, source_path, best_plate_path, scan_record.get('created_utc', ''), finished_utc)

    scan_record.update({
        'analysis_stage': 'final',
        'selected_candidate_ids': selected_candidate_ids,
        'selected_target': dict(primary_target),
        'selected_targets': [dict(target) for target in selected_targets],
        'best_frame': dict(selected_best_frame),
        'best_result': selected_result,
        'video_forensic_chain': video_forensic_chain,
        'updated_utc': finished_utc,
        'report_path': report_path,
        'report_url': f'/pdf/{report_filename}',
        'final_report_path': report_path,
        'final_report_url': f'/pdf/{report_filename}',
    })

    report_data = {
        'analysis_id': analysis_id,
        'analysis_stage': 'final',
        'video_path': str(scan_record.get('video_path', '') or ''),
        'video_filename': str(scan_record.get('video_filename', '') or os.path.basename(str(scan_record.get('video_path', '') or analysis_id))),
        'video_metadata': video_metadata,
        'frame_sampling': frame_sampling,
        'frame_results': frame_results,
        'best_frame': selected_best_frame,
        'best_result': selected_result,
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'human_review': human_review,
        'capture_integrity': capture_integrity,
        'analysis_report_outline': analysis_report_outline,
        'contact_sheet_path': contact_sheet_path,
        'comparison_sheet_path': comparison_sheet_path,
        'selected_targets': [dict(target) for target in selected_targets],
        'selected_candidate_ids': selected_candidate_ids,
        'video_candidates_preview': video_candidates_preview,
        'video_candidates_count': len(video_candidates_all),
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'summary': str(pericial.get('summary', '') or ''),
        'conclusion': str(pericial.get('summary', '') or ''),
        'frame_failures': frame_failures,
        'video_forensic_chain': video_forensic_chain,
        'input_meta': {
            'input_type': 'video',
            'analysis_mode': 'final',
            'source_filename': str(scan_record.get('video_filename', '') or ''),
            'source_path': str(scan_record.get('video_path', '') or ''),
            'source_resolution': {
                'width': int(video_metadata.get('width', 0) or 0),
                'height': int(video_metadata.get('height', 0) or 0),
            },
            'video_metadata': video_metadata,
            'frame_sampling': frame_sampling,
            'capture_integrity': capture_integrity,
            'video_context': {
                'analysis_id': analysis_id,
                'scan_record_path': scan_record_path,
            },
        },
        'scan_record_path': scan_record_path,
        'report_path': report_path,
    }

    evidence_manifest = _build_and_store_evidence_manifest(report_data, 'video', app.config['UPLOAD_FOLDER'], analysis_id)
    report_data['evidence_manifest'] = evidence_manifest
    report_data['evidence_manifest_path'] = evidence_manifest.get('manifest_path', '')
    report_data['evidence_manifest_url'] = evidence_manifest.get('manifest_url', '')
    report_data['evidence_manifest_fingerprint'] = evidence_manifest.get('manifest_fingerprint', '')

    try:
        generate_video_investigation_report(report_data, report_path)
    except Exception as pdf_error:
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': f'Falha ao gerar relatorio final de video: {pdf_error}',
            'analysis_id': analysis_id,
        }), 500

    scan_record.update({
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'evidence_manifest_path': evidence_manifest.get('manifest_path', ''),
        'evidence_manifest_url': evidence_manifest.get('manifest_url', ''),
        'evidence_manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
    })
    scan_record_path = save_video_scan_record(scan_record, app.config['UPLOAD_FOLDER'], analysis_id)

    return jsonify({
        'status': 'ok',
        'analysis_mode': 'video',
        'analysis_id': analysis_id,
        'analysis_stage': 'final',
        'selected_candidate_ids': selected_candidate_ids,
        'selected_targets': [dict(target) for target in selected_targets],
        'selected_target': dict(primary_target),
        'best_frame': selected_best_frame,
        'best_result': selected_result,
        'video_partial_candidates_preview': video_partial_candidates_preview,
        'video_partial_candidates': video_partial_candidates_all,
        'video_partial_candidates_count': len(video_partial_candidates_all),
        'consensus': consensus,
        'assessment': assessment,
        'pericial': pericial,
        'human_review': human_review,
        'capture_integrity': capture_integrity,
        'video_forensic_chain': video_forensic_chain,
        'report_url': f'/pdf/{report_filename}',
        'contact_sheet_url': f'/artifact/{quote_plus(os.path.basename(contact_sheet_path))}' if contact_sheet_path else '',
        'comparison_sheet_url': f'/artifact/{quote_plus(os.path.basename(comparison_sheet_path))}' if comparison_sheet_path else '',
        'scan_record_path': scan_record_path,
        'manifest_path': evidence_manifest.get('manifest_path', ''),
        'manifest_url': evidence_manifest.get('manifest_url', ''),
        'manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
        'evidence_manifest_path': evidence_manifest.get('manifest_path', ''),
        'evidence_manifest_url': evidence_manifest.get('manifest_url', ''),
        'evidence_manifest_fingerprint': evidence_manifest.get('manifest_fingerprint', ''),
        'analysis_report_outline': analysis_report_outline,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)




