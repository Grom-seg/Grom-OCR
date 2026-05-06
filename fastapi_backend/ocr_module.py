import os
from multiprocessing import get_context

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PADDLE_CACHE_HOME = os.path.join(PROJECT_ROOT, '.pdx_cache')

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

ocr_engine = None
last_ocr_runtime_info = {
    'preferred_engine': 'paddleocr',
    'selected_engine': 'none',
    'fallback_used': False,
    'paddle_disabled': False,
    'paddle_available': PaddleOCR is not None,
    'tesseract_available': pytesseract is not None,
    'paddle_error': '',
    'mode': 'idle',
}


def _set_last_runtime_info(payload):
    global last_ocr_runtime_info
    last_ocr_runtime_info = dict(payload or {})


def get_last_ocr_runtime_info():
    return dict(last_ocr_runtime_info)


def _get_ocr_engine():
    global ocr_engine
    if PaddleOCR is None:
        raise RuntimeError("paddleocr nao esta instalado no ambiente atual")
    if ocr_engine is None:
        os.makedirs(PADDLE_CACHE_HOME, exist_ok=True)
        os.environ.setdefault('PADDLE_PDX_CACHE_HOME', PADDLE_CACHE_HOME)
        os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
        try:
            ocr_engine = PaddleOCR(
                lang='en',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except TypeError:
            ocr_engine = PaddleOCR(use_angle_cls=True, lang='en')
    return ocr_engine


def _run_paddle(image_path):
    engine = _get_ocr_engine()
    try:
        result = engine.ocr(image_path, cls=True)
    except TypeError:
        result = engine.ocr(image_path)

    ocr_results = []
    if isinstance(result, list) and result and isinstance(result[0], dict):
        for item in result:
            rec_text = str(item.get('rec_text', '') or '').strip()
            if rec_text == '':
                continue
            rec_score = float(item.get('rec_score', 0.0) or 0.0)
            ocr_results.append({'text': rec_text, 'confidence': rec_score * 100.0, 'engine': 'paddleocr'})
    else:
        for line in (result[0] if result else []):
            text = line[1][0]
            conf = line[1][1]
            ocr_results.append({'text': text, 'confidence': conf, 'engine': 'paddleocr'})
    return ocr_results


def _run_tesseract(image_path):
    if pytesseract is None:
        raise RuntimeError("pytesseract nao esta instalado no ambiente atual")

    tesseract_cmd = os.getenv('GROM_OCR_TESSERACT_CMD')
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    text = (pytesseract.image_to_string(image_path, config='--psm 7') or '').strip()
    if text == '':
        return []
    return [{'text': text, 'confidence': 55.0, 'engine': 'tesseract'}]


def _run_paddle_worker(image_path, queue):
    try:
        queue.put({'ok': True, 'results': _run_paddle(image_path)})
    except Exception as exc:
        queue.put({'ok': False, 'error': str(exc)})


def _run_paddle_with_timeout(image_path, timeout_seconds):
    ctx = get_context('spawn')
    queue = ctx.Queue()
    process = ctx.Process(target=_run_paddle_worker, args=(image_path, queue), daemon=True)
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(2)
        raise TimeoutError(f"PaddleOCR excedeu timeout de {timeout_seconds}s")

    if queue.empty():
        raise RuntimeError('processo PaddleOCR finalizou sem retorno')

    payload = queue.get_nowait()
    if payload.get('ok'):
        return payload.get('results', [])
    raise RuntimeError(str(payload.get('error', 'falha desconhecida no PaddleOCR')))


def run_ocr(image_path):
    runtime_info = {
        'preferred_engine': 'paddleocr',
        'selected_engine': 'none',
        'fallback_used': False,
        'paddle_disabled': False,
        'paddle_available': PaddleOCR is not None,
        'tesseract_available': pytesseract is not None,
        'paddle_error': '',
        'mode': 'runtime',
    }

    paddle_enabled = os.getenv('GROM_OCR_ENABLE_PADDLE', '1').strip().lower() in ('1', 'true', 'yes', 'on')
    if not paddle_enabled:
        runtime_info['paddle_disabled'] = True
        runtime_info['preferred_engine'] = 'tesseract'

    paddle_error = None
    if paddle_enabled and PaddleOCR is not None:
        try:
            timeout_seconds = float(os.getenv('GROM_OCR_PADDLE_TIMEOUT_SECONDS', '25'))
            use_subprocess = os.getenv('GROM_OCR_PADDLE_SUBPROCESS', '1').strip().lower() in ('1', 'true', 'yes', 'on')
            if use_subprocess:
                paddle_results = _run_paddle_with_timeout(image_path, timeout_seconds)
            else:
                paddle_results = _run_paddle(image_path)
            runtime_info['selected_engine'] = 'paddleocr'
            _set_last_runtime_info(runtime_info)
            return paddle_results
        except Exception as exc:
            paddle_error = str(exc)
            runtime_info['paddle_error'] = paddle_error
            runtime_info['fallback_used'] = True

    if pytesseract is not None:
        runtime_info['selected_engine'] = 'tesseract'
        _set_last_runtime_info(runtime_info)
        return _run_tesseract(image_path)

    if paddle_error:
        _set_last_runtime_info(runtime_info)
        raise RuntimeError(f"falha no PaddleOCR e sem fallback Tesseract: {paddle_error}")
    _set_last_runtime_info(runtime_info)
    raise RuntimeError("nenhum motor OCR disponivel (instale paddleocr+paddlepaddle ou pytesseract)")
