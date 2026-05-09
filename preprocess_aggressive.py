#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Preprocessamento AGRESSIVO para placas - máxima qualidade para OCR
"""

import cv2
import numpy as np
from pathlib import Path

def preprocess_for_ocr_aggressive(image_bgr, debug=False):
    """
    Preprocessamento agressivo para MÁXIMA qualidade de OCR de placas.

    Técnicas:
    1. Gaussian Blur (remover ruído)
    2. Morphological operations (limpeza)
    3. Adaptive Thresholding (binarização inteligente)
    4. CLAHE (contraste adaptativo)
    5. Upscaling (se muito pequeno)
    """

    if image_bgr is None or image_bgr.size == 0:
        return None

    h, w = image_bgr.shape[:2]

    # 1. Denoise agressivo
    denoised = cv2.fastNlMeansDenoising(
        image_bgr,
        None,
        h=10,  # maior = mais agressivo
        templateWindowSize=7,
        searchWindowSize=21
    )

    # 2. Converter para grayscale
    gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)

    # 3. CLAHE - melhorar contraste em áreas locais
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 4. Bilateral filter (suavizar mantendo bordas)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    # 5. Binarização adaptativa
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=5
    )

    # 6. Morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 7. Se imagem muito pequena, upscalar
    if w < 300:
        scale = max(2, 300 // w + 1)
        binary = cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    return binary

def test_preprocessor():
    """Teste do preprocessador"""
    test_image = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

    if not test_image.exists():
        print(f"❌ Imagem não encontrada: {test_image}")
        return

    print("Carregando imagem...")
    img = cv2.imread(str(test_image))

    # Extrair region da placa (bbox detectada: [559, 0, 1128, 696])
    x1, y1, x2, y2 = 559, 0, 1128, 696
    plate_crop = img[y1:y2, x1:x2]

    print(f"Tamanho original da placa: {plate_crop.shape}")

    # Aplicar preprocessamento agressivo
    processed = preprocess_for_ocr_aggressive(plate_crop)

    print(f"Tamanho após preprocessamento: {processed.shape}")
    print("✓ Preprocessamento concluído")

    # Salvar para inspeção
    output_path = Path(r"C:\Grom_OCR\data")/ "plate_preprocessed_debug.jpg"
    cv2.imwrite(str(output_path), processed)
    print(f"✓ Salvo em: {output_path}")

    print("\nNota: Imagem processada está pronta para OCR")

if __name__ == '__main__':
    test_preprocessor()
