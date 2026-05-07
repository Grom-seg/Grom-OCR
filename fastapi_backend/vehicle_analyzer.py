"""
Vehicle Analyzer — Grom OCR

Análise complementar do veículo além da placa:
  1. Detecção de veículo e partes (YOLOv8-seg via ultralytics)
  2. Make & model via CLIP zero-shot (sem retreinar)
  3. Estimativa de regiões de faróis/lanternas por geometria (sem modelo)
  4. Assinatura de faróis por template matching (se templates fornecidos)

Todos os componentes são opcionais e isolados do pipeline /process.
Use o endpoint /analyze-vehicle para chamar este módulo.

Env vars:
  GROM_VA_YOLO_MODEL      caminho do modelo YOLOv8-seg
                           (default: yolov8n-seg.pt — baixado pelo ultralytics)
  GROM_VA_PARTS_MODEL     caminho de modelo ONNX de partes de carro
                           (default: models/car_parts_seg.onnx)
  GROM_VA_CLIP_ENABLED    habilita CLIP zero-shot (default: true)
  GROM_VA_CLIP_MODEL      nome do modelo CLIP (default: ViT-B-32)
  GROM_VA_YOLO_CONF       confiança mínima YOLO (default: 0.30)
  GROM_VA_HEADLIGHT_TMPL  diretório com templates de faróis (default: '')

Dependências opcionais:
  - ultralytics  (já no projeto)
  - open_clip_torch  (pip install open-clip-torch)
  - onnxruntime  (já no projeto)

Classes COCO relevantes para veículo:
  2=car, 3=motorcycle, 5=bus, 7=truck
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Configurações por env
_YOLO_MODEL_PATH = os.getenv('GROM_VA_YOLO_MODEL', 'yolov8n.pt')
_PARTS_MODEL_PATH = os.getenv(
    'GROM_VA_PARTS_MODEL',
    os.path.join(_PROJECT_ROOT, 'models', 'car_parts_seg.onnx'),
)
_CLIP_MODEL_NAME = os.getenv('GROM_VA_CLIP_MODEL', 'ViT-B-32')
_YOLO_CONF = float(os.getenv('GROM_VA_YOLO_CONF', '0.30'))
_HEADLIGHT_TMPL_DIR = os.getenv('GROM_VA_HEADLIGHT_TMPL', '')

# Classes COCO de veículo
_VEHICLE_CLASSES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}

# Prompts CLIP para identificação de make/model
# Fabricantes comuns no Brasil para zero-shot
_MAKE_PROMPTS = [
    'Volkswagen car', 'Fiat car', 'Chevrolet car', 'Ford car',
    'Toyota car', 'Honda car', 'Hyundai car', 'Renault car',
    'Jeep SUV', 'Nissan car', 'Peugeot car', 'Citroën car',
    'BMW car', 'Mercedes-Benz car', 'Audi car', 'Kia car',
    'Mitsubishi car', 'Subaru car', 'Land Rover SUV', 'RAM truck',
    'motorcycle', 'bus', 'truck',
]


def _is_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def _load_image(path: str) -> Optional[np.ndarray]:
    """Carrega imagem BGR com fallback Unicode."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is not None:
        return img
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size > 0:
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 1. Detecção de veículo e partes via YOLOv8
# ---------------------------------------------------------------------------

def _detect_vehicle_yolo(image_path: str) -> List[dict]:
    """
    Detecta veículos na imagem usando YOLOv8.

    Retorna lista de dicts:
      {'class_id': int, 'class_name': str, 'bbox': [x1,y1,x2,y2],
       'confidence': float, 'mask_area': int}

    mask_area é 0 se o modelo não for de segmentação.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.warning('ultralytics não instalado — detecção de veículo indisponível.')
        return []

    try:
        model = YOLO(_YOLO_MODEL_PATH)
        results = model(
            image_path,
            conf=_YOLO_CONF,
            verbose=False,
            classes=list(_VEHICLE_CLASSES.keys()),
        )

        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls[0])
                if class_id not in _VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                conf = float(box.conf[0])

                # Área da máscara de segmentação (se disponível)
                mask_area = 0
                if result.masks is not None:
                    try:
                        mask = result.masks.data[0].cpu().numpy()
                        mask_area = int(mask.sum())
                    except Exception:
                        pass

                detections.append({
                    'class_id': class_id,
                    'class_name': _VEHICLE_CLASSES.get(class_id, 'vehicle'),
                    'bbox': [x1, y1, x2, y2],
                    'confidence': conf,
                    'mask_area': mask_area,
                })

        logger.debug('YOLO vehicle: %d detecções em %s', len(detections), image_path)
        return detections

    except Exception as exc:
        logger.warning('Falha na detecção YOLO de veículo: %s', exc)
        return []


# ---------------------------------------------------------------------------
# 2. Estimativa de regiões de faróis/lanternas por geometria
# ---------------------------------------------------------------------------

def _estimate_light_regions(
    vehicle_bbox: List[int],
    img_shape: Tuple[int, int],
) -> dict:
    """
    Estima regiões de faróis dianteiros e lanternas traseiras por geometria.

    Sem modelo — usa apenas o bounding box do veículo e proporções típicas.
    Retorna coordenadas estimadas para:
      - headlight_left, headlight_right   (20% superior, 15% laterais)
      - taillight_left, taillight_right   (não diferenciado sem modelo de orientação)

    Args:
        vehicle_bbox: [x1, y1, x2, y2] do veículo detectado.
        img_shape: (height, width) da imagem original.

    Returns:
        dict com regiões estimadas e flag 'reliable' (False — geometria apenas).
    """
    x1, y1, x2, y2 = vehicle_bbox
    vh = y2 - y1
    vw = x2 - x1

    # Faróis: faixa superior, laterais internas
    hl_top = y1
    hl_bot = y1 + int(vh * 0.30)
    hl_left_x1 = x1
    hl_left_x2 = x1 + int(vw * 0.30)
    hl_right_x1 = x2 - int(vw * 0.30)
    hl_right_x2 = x2

    # Lanternas: faixa superior, mas região mais centralizada lateralmente
    # (sem orientação frontal/traseira confiável, marcamos como 'estimated')
    tl_top = y1
    tl_bot = y1 + int(vh * 0.30)

    return {
        'headlight_left':  [hl_left_x1,  hl_top, hl_left_x2,  hl_bot],
        'headlight_right': [hl_right_x1, hl_top, hl_right_x2, hl_bot],
        'taillight_left':  [hl_left_x1,  tl_top, hl_left_x2,  tl_bot],
        'taillight_right': [hl_right_x1, tl_top, hl_right_x2, tl_bot],
        'reliable': False,  # geometria apenas, sem modelo de orientação
        'note': 'estimativa geométrica — oriente por modelo de partes para maior precisão',
    }


# ---------------------------------------------------------------------------
# 3. Assinatura de faróis via template matching
# ---------------------------------------------------------------------------

def _match_headlight_templates(
    img: np.ndarray,
    headlight_bbox: List[int],
) -> List[dict]:
    """
    Compara região de farol com templates de fabricantes.

    Requer GROM_VA_HEADLIGHT_TMPL apontando para diretório com imagens
    nomeadas como 'VW_Golf_drl.png', 'BMW_AE_drl.png', etc.

    Returns:
        Lista de {'template': str, 'score': float, 'make': str}
        ordenada por score decrescente.
    """
    if not _HEADLIGHT_TMPL_DIR or not os.path.isdir(_HEADLIGHT_TMPL_DIR):
        return []

    x1, y1, x2, y2 = headlight_bbox
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return []

    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    results = []

    for fname in os.listdir(_HEADLIGHT_TMPL_DIR):
        if not fname.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        tmpl_path = os.path.join(_HEADLIGHT_TMPL_DIR, fname)
        tmpl = cv2.imread(tmpl_path, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            continue

        # Redimensiona template para tamanho do ROI
        tmpl_resized = cv2.resize(tmpl, (gray_roi.shape[1], gray_roi.shape[0]))
        match = cv2.matchTemplate(gray_roi, tmpl_resized, cv2.TM_CCOEFF_NORMED)
        score = float(match.max())

        # Extrai make do nome do arquivo (ex: VW_Golf_drl.png → VW)
        make = fname.split('_')[0] if '_' in fname else fname.split('.')[0]
        results.append({'template': fname, 'score': score, 'make': make})

    results.sort(key=lambda r: r['score'], reverse=True)
    return results[:5]  # top 5


# ---------------------------------------------------------------------------
# 4. CLIP zero-shot make/model
# ---------------------------------------------------------------------------

_clip_model = None
_clip_preprocess = None
_clip_tokenize = None
_clip_loaded: bool = False


def _load_clip():
    """Carrega modelo CLIP (lazy, singleton). Tenta open_clip, depois transformers."""
    global _clip_model, _clip_preprocess, _clip_tokenize, _clip_loaded
    if _clip_loaded:
        return _clip_model is not None

    _clip_loaded = True

    if not _is_enabled('GROM_VA_CLIP_ENABLED', default=True):
        logger.info('CLIP desabilitado via GROM_VA_CLIP_ENABLED=false.')
        return False

    # Tentativa 1: open_clip_torch
    try:
        import open_clip
        import torch
        model_name = _CLIP_MODEL_NAME.replace('/', '-')
        _clip_model, _, _clip_preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained='openai',
        )
        _clip_model.eval()
        _clip_tokenize = open_clip.get_tokenizer(model_name)
        logger.info('CLIP (open_clip) carregado: %s', model_name)
        return True
    except Exception as exc_oc:
        logger.debug('open_clip falhou: %s', exc_oc)

    # Tentativa 2: transformers
    try:
        from transformers import CLIPProcessor, CLIPModel
        import torch
        hf_name = f'openai/clip-{_CLIP_MODEL_NAME.lower().replace("_", "-")}'
        _clip_model = CLIPModel.from_pretrained(hf_name)
        _clip_preprocess = CLIPProcessor.from_pretrained(hf_name)
        _clip_tokenize = 'transformers'  # flag especial
        _clip_model.eval()
        logger.info('CLIP (transformers) carregado: %s', hf_name)
        return True
    except Exception as exc_tr:
        logger.info(
            'CLIP indisponível (open_clip: %s; transformers: %s). '
            'Instale open-clip-torch para habilitar.',
            exc_oc, exc_tr,
        )
        return False


def _clip_predict_make(img_bgr: np.ndarray, prompts: List[str]) -> List[dict]:
    """
    Identifica make/model via CLIP zero-shot.

    Args:
        img_bgr: imagem BGR do veículo (crop ou original).
        prompts: lista de descrições textuais.

    Returns:
        Lista de {'label': str, 'score': float} ordenada por score.
    """
    if not _load_clip():
        return []

    try:
        import torch
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

        if _clip_tokenize == 'transformers':
            # Modo transformers
            inputs = _clip_preprocess(
                text=prompts, images=pil_img,
                return_tensors='pt', padding=True,
            )
            with torch.no_grad():
                outputs = _clip_model(**inputs)
                logits = outputs.logits_per_image  # [1, len(prompts)]
                probs = logits.softmax(dim=1)[0].tolist()
        else:
            # Modo open_clip
            img_tensor = _clip_preprocess(pil_img).unsqueeze(0)
            text_tokens = _clip_tokenize(prompts)
            with torch.no_grad():
                img_feat = _clip_model.encode_image(img_tensor)
                txt_feat = _clip_model.encode_text(text_tokens)
                img_feat /= img_feat.norm(dim=-1, keepdim=True)
                txt_feat /= txt_feat.norm(dim=-1, keepdim=True)
                logits = (100.0 * img_feat @ txt_feat.T).softmax(dim=-1)
                probs = logits[0].tolist()

        ranked = sorted(
            [{'label': p, 'score': float(s)} for p, s in zip(prompts, probs)],
            key=lambda x: x['score'],
            reverse=True,
        )
        return ranked[:10]

    except Exception as exc:
        logger.warning('CLIP inference falhou: %s', exc)
        return []


# ---------------------------------------------------------------------------
# API pública principal
# ---------------------------------------------------------------------------

def analyze_vehicle(image_path: str) -> dict:
    """
    Análise completa do veículo na imagem.

    Retorna:
    {
      'vehicle_detections': [...],   # YOLOv8 detecções de veículo
      'light_regions': {...},        # regiões estimadas de faróis/lanternas
      'headlight_templates': [...],  # assinatura de faróis por template matching
      'make_model_clip': [...],      # identificação de marca via CLIP zero-shot
      'clip_available': bool,
      'yolo_available': bool,
      'parts_model_available': bool,
    }
    """
    result: dict = {
        'vehicle_detections': [],
        'light_regions': {},
        'headlight_templates': [],
        'make_model_clip': [],
        'clip_available': False,
        'yolo_available': False,
        'parts_model_available': os.path.exists(_PARTS_MODEL_PATH),
    }

    img = _load_image(image_path)
    if img is None:
        logger.warning('analyze_vehicle: falha ao carregar imagem %s', image_path)
        result['error'] = 'falha ao carregar imagem'
        return result

    # --- Detecção de veículo ---
    detections = _detect_vehicle_yolo(image_path)
    result['vehicle_detections'] = detections
    result['yolo_available'] = True  # se chegou aqui sem exceção

    # --- Regiões de faróis/lanternas ---
    if detections:
        best_det = max(detections, key=lambda d: d['confidence'])
        result['light_regions'] = _estimate_light_regions(
            best_det['bbox'], img.shape[:2],
        )

        # Template matching de faróis (se templates configurados)
        hl_bbox = result['light_regions'].get('headlight_left', [])
        if hl_bbox and img is not None:
            result['headlight_templates'] = _match_headlight_templates(img, hl_bbox)

        # Crop do veículo para CLIP
        x1, y1, x2, y2 = best_det['bbox']
        vehicle_crop = img[max(0, y1):y2, max(0, x1):x2]
    else:
        vehicle_crop = img

    # --- CLIP zero-shot make/model ---
    clip_loaded = _load_clip()
    result['clip_available'] = clip_loaded
    if clip_loaded and vehicle_crop.size > 0:
        result['make_model_clip'] = _clip_predict_make(vehicle_crop, _MAKE_PROMPTS)

    return result


def get_vehicle_analyzer_info() -> dict:
    """Retorna informações sobre disponibilidade dos componentes."""
    return {
        'yolo_model': _YOLO_MODEL_PATH,
        'yolo_model_exists': os.path.exists(_YOLO_MODEL_PATH),
        'parts_model': _PARTS_MODEL_PATH,
        'parts_model_exists': os.path.exists(_PARTS_MODEL_PATH),
        'clip_model': _CLIP_MODEL_NAME,
        'clip_enabled': _is_enabled('GROM_VA_CLIP_ENABLED', default=True),
        'headlight_tmpl_dir': _HEADLIGHT_TMPL_DIR,
        'headlight_tmpl_configured': bool(_HEADLIGHT_TMPL_DIR and os.path.isdir(_HEADLIGHT_TMPL_DIR)),
        'make_prompts_count': len(_MAKE_PROMPTS),
    }
