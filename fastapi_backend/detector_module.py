from ultralytics import YOLO
import cv2
import numpy as np
import os

# Usa modelo especializado em detecção de placas se disponível, caso contrário o genérico
_PLATE_MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'yolov8n_plate.pt')
_GENERIC_MODEL_PATH = 'yolov8n.pt'

if os.path.exists(_PLATE_MODEL_PATH):
    yolo_model = YOLO(_PLATE_MODEL_PATH)
else:
    yolo_model = YOLO(_GENERIC_MODEL_PATH)  # Fallback para modelo genérico

def detect_plate(image_path, use_heuristic_fallback=True):
    """
    Detecta regiões de placa em uma imagem.

    Retorna lista de detecções com:
    - bbox: [x1, y1, x2, y2]
    - confidence: confiança da detecção
    - priority_rank: ordem de prioridade (1=mais prioritário)
    - priority_score: score de prioridade (0-1, maior=mais prioritário)
    - detection_method: 'yolo' ou 'heuristic'
    """
    detections = []

    # --- ETAPA 1: Detecção YOLO ---
    try:
        img = cv2.imread(image_path)
        if img is None:
            if use_heuristic_fallback:
                return _detect_by_heuristic(image_path)
            return []

        h, w = img.shape[:2]
        results = yolo_model(image_path, conf=0.3)  # Threshold mais baixo para não perder detecções

        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])

                # Filtra por razão de aspecto (placas típicas têm proporção 3-4:1)
                bbox_w = x2 - x1
                bbox_h = y2 - y1
                aspect_ratio = bbox_w / max(bbox_h, 1)
                if aspect_ratio < 1.5 or aspect_ratio > 5.0:
                    continue  # Provavelmente não é placa

                detections.append({
                    'bbox': [x1, y1, x2, y2],
                    'confidence': conf,
                    'detection_method': 'yolo',
                    'area': bbox_w * bbox_h,
                    'w': bbox_w,
                    'h': bbox_h,
                })
    except Exception:
        if use_heuristic_fallback:
            return _detect_by_heuristic(image_path)
        return []

    # --- ETAPA 2: Detecção por heurística se YOLO falhou ---
    if not detections and use_heuristic_fallback:
        detections = _detect_by_heuristic(image_path)

    # --- ETAPA 3: Priorização e ordenação ---
    if not detections:
        return []

    img = cv2.imread(image_path)
    img_h, img_w = img.shape[:2]
    img_center_x = img_w / 2
    img_center_y = img_h / 2

    # Calcula priority_score para cada detecção
    for det in detections:
        x1, y1, x2, y2 = det['bbox']
        bbox_w = x2 - x1
        bbox_h = y2 - y1
        area = bbox_w * bbox_h
        img_area = img_w * img_h
        area_ratio = area / img_area  # Quanto maior, melhor (ocupação da imagem)

        # Centralidade: quanto mais perto do centro, melhor
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        dist_to_center = ((center_x - img_center_x) ** 2 + (center_y - img_center_y) ** 2) ** 0.5
        max_dist = ((img_w / 2) ** 2 + (img_h / 2) ** 2) ** 0.5
        centrality = 1.0 - (dist_to_center / max_dist)  # 1.0 = muito central, 0.0 = muito periférico

        # Prioridade: ÁREA (tamanho visual = proeminência) é o fator primário
        # Penaliza confiança YOLO isolada (pode errar em segundo plano)
        conf_score = det.get('confidence', 0.5)
        area_score = min(area_ratio * 2, 1.0)  # Max out at occupying 50% of image
        # Novos pesos: área 60% (tamanho visual é indicador principal), confiança 15%, centralidade 25%
        priority_score = (area_score * 0.60 + conf_score * 0.15 + centrality * 0.25)

        det['priority_score'] = priority_score

    # Ordena por priority_score (maior = mais prioritário)
    detections.sort(key=lambda d: d.get('priority_score', 0), reverse=True)

    # Atribui priority_rank
    for rank, det in enumerate(detections, start=1):
        det['priority_rank'] = rank

    # Remove campos temporários de cálculo
    for det in detections:
        det.pop('area', None)
        det.pop('w', None)
        det.pop('h', None)

    return detections


def _detect_by_heuristic(image_path):
    """
    Detecção por heurística quando YOLO falha.
    Usa processamento de contornos para encontrar regiões retangulares.
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Processamento para realçar contornos
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # Encontra contornos
        contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        h, w = img.shape[:2]

        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)

            # Filtra por tamanho e razão de aspecto (placa-like)
            min_area = (w * h) * 0.01  # Mínimo 1% da imagem
            max_area = (w * h) * 0.5   # Máximo 50% da imagem
            area = cw * ch

            if not (min_area < area < max_area):
                continue

            aspect_ratio = cw / max(ch, 1)
            if aspect_ratio < 1.5 or aspect_ratio > 5.0:
                continue  # Não é shape de placa

            detections.append({
                'bbox': [x, y, x + cw, y + ch],
                'confidence': 0.5,  # Heurística: confiança média
                'detection_method': 'heuristic',
                'area': area,
            })

        return detections
    except Exception:
        return []
