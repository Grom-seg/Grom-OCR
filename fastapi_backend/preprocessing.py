import cv2
from PIL import Image
import numpy as np

def preprocess_image(image_path):
    # Carrega imagem
    img = cv2.imread(image_path)
    # Conversão para escala de cinza
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Normalização
    norm = cv2.equalizeHist(gray)
    # Retorna imagem PIL para integração
    return Image.fromarray(norm)
