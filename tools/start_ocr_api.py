import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = PROJECT_ROOT / 'python'
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from utils.tesseract_runtime import apply_tesseract_env_defaults


YOLO_MODEL_PATH = PROJECT_ROOT / 'models' / 'yolov8n_plate.pt'

tesseract_runtime = apply_tesseract_env_defaults(project_root=str(PROJECT_ROOT))
if YOLO_MODEL_PATH.exists():
    os.environ.setdefault('GROM_OCR_YOLO_MODEL_PATH', str(YOLO_MODEL_PATH))
os.environ.setdefault('GROM_OCR_ENABLE_EASYOCR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_RAPIDOCR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_TROCR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_DOCTR', '1')
os.environ.setdefault('GROM_OCR_ENABLE_PADDLEOCR', '1')
os.environ.setdefault('GROM_OCR_FORCE_ENSEMBLE', '1')
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

api_port = int(os.environ.get('GROM_OCR_API_PORT', '8000'))
api_host = os.environ.get('GROM_OCR_API_HOST', '127.0.0.1')

print(f'BOOT_TESSERACT_CMD={os.environ.get("GROM_OCR_TESSERACT_CMD", "")}', flush=True)
print(f'BOOT_TESSDATA_PREFIX={os.environ.get("TESSDATA_PREFIX", "")}', flush=True)
print(f'BOOT_TESSERACT_CMD_SOURCE={tesseract_runtime.get("cmd_source", "")}', flush=True)
print(f'BOOT_TESSDATA_SOURCE={tesseract_runtime.get("tessdata_source", "")}', flush=True)
print(f'BOOT_API=http://{api_host}:{api_port}', flush=True)

cmd = [
    sys.executable,
    '-m',
    'uvicorn',
    'fastapi_backend.main:app',
    '--host',
    api_host,
    '--port',
    str(api_port),
]

raise SystemExit(subprocess.call(cmd, cwd=str(PROJECT_ROOT)))
