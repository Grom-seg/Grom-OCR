from ultralytics import YOLO
import cv2

yolo_model = YOLO('yolov8n.pt')  # Modelo leve, pode ser trocado por customizado

def detect_plate(image_path):
    results = yolo_model(image_path)
    detections = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            detections.append({'bbox': [x1, y1, x2, y2], 'confidence': conf})
    return detections
