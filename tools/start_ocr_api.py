import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESSERACT_CMD = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tesseract.exe'
TESSDATA_DIR = PROJECT_ROOT / 'tools' / 'tesseract-portable' / 'tessdata'
YOLO_MODEL_PATH = PROJECT_ROOT / 'models' / 'yolov8n_plate.pt'

os.environ.setdefault('GROM_OCR_TESSERACT_CMD', str(TESSERACT_CMD))
os.environ.setdefault('TESSDATA_PREFIX', str(TESSDATA_DIR))
if YOLO_MODEL_PATH.exists():
    os.environ.setdefault('GROM_OCR_YOLO_MODEL_PATH', str(YOLO_MODEL_PATH))
os.environ.setdefault('GROM_OCR_ENABLE_EASYOCR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_RAPIDOCR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_TROCR', '0')
os.environ.setdefault('GROM_OCR_ENABLE_DOCTR', '0')
os.environ.setdefault('GROM_OCR_ENABLE_PADDLEOCR', '0')
os.environ.setdefault('GROM_OCR_FORCE_ENSEMBLE', '0')
os.environ.setdefault('GROM_OCR_ALLOW_HEAVY_COLDSTART', '0')
os.environ.setdefault('GROM_OCR_TROCR_LOCAL_ONLY', '1')
os.environ.setdefault('GROM_OCR_TESSERACT_MAX_VARIANTS', '6')
os.environ.setdefault('GROM_OCR_TESSERACT_PSM_MODES', '7')
os.environ.setdefault('GROM_OCR_TESSERACT_HIT_BONUS', '2.1')
os.environ.setdefault('GROM_OCR_TESSERACT_MIN_ACCEPT_SCORE', '42')
os.environ.setdefault('GROM_OCR_TESSERACT_MIN_ACCEPT_CONF', '28')
os.environ.setdefault('GROM_OCR_TESSERACT_PATTERN_MIN_SCORE', '58')
os.environ.setdefault('GROM_OCR_TESSERACT_EARLY_EXIT_SCORE', '108')
os.environ.setdefault('GROM_OCR_EASYOCR_MAX_VARIANTS', '4')
os.environ.setdefault('GROM_OCR_RAPIDOCR_MAX_VARIANTS', '4')
os.environ.setdefault('GROM_OCR_PDF_PAGE_CANDIDATE_LIMIT', '2')
os.environ.setdefault('GROM_OCR_PDF_PAGE_EARLY_SCORE', '118')
os.environ.setdefault('GROM_OCR_PDF_MAX_REGION_CANDIDATES', '2')
os.environ.setdefault('GROM_OCR_PDF_PROBE_MAX_SIDE', '1200')
os.environ.setdefault('GROM_OCR_VISUAL_PROFILE_ENABLE', '1')
os.environ.setdefault('GROM_OCR_VISUAL_PROFILE_MAX_SIDE', '1280')
os.environ.setdefault('GROM_OCR_VISUAL_PROFILE_MIN_CONFIDENCE', '42')
os.environ.setdefault('GROM_OCR_VISUAL_PROFILE_TOP_HYPOTHESES', '3')
os.environ.setdefault('GROM_OCR_VISUAL_FIPE_ENABLE', '1')
os.environ.setdefault('GROM_OCR_VISUAL_FIPE_BASE_URL', 'https://fipe.parallelum.com.br/api/v2')
os.environ.setdefault('GROM_OCR_VISUAL_FIPE_TIMEOUT', '3')

sys.path.insert(0, str(PROJECT_ROOT / 'python'))

import ocr_agent  # noqa: E402

try:
    from waitress import serve  # type: ignore
except Exception:
    serve = None


print(f'BOOT_TESSERACT_CMD={ocr_agent.TESSERACT_CMD}', flush=True)
print(f'BOOT_TESSDATA_PREFIX={os.environ.get("TESSDATA_PREFIX")}', flush=True)

if serve is not None:
    serve(ocr_agent.app, host='0.0.0.0', port=5000)
else:
    ocr_agent.app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
