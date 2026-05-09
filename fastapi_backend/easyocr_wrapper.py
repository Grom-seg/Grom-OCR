#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Integração EasyOCR - Motor OCR secundário com alta precisão
"""

import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class EasyOCRWrapper:
    """Wrapper para EasyOCR com detecção de texto português/inglês."""

    def __init__(self, languages: List[str] = None):
        self.available = False
        self.reader = None
        self.languages = languages or ['pt', 'en']

        try:
            import easyocr
            # Carregar modelo (pode levar tempo na primeira vez)
            logger.info(f"EasyOCR: inicializando com idiomas {self.languages}...")
            self.reader = easyocr.Reader(self.languages, gpu=False)
            self.available = True
            logger.info("✓ EasyOCR disponível")
        except Exception as e:
            logger.warning(f"EasyOCR não disponível: {e}")
            self.available = False

    def recognize(self, image_path: str) -> List[Dict[str, Any]]:
        """Reconhecer texto em imagem via EasyOCR."""
        if not self.available:
            return []

        try:
            results = self.reader.readtext(image_path, detail=1)

            # Converter para formato compatível com pipeline
            ocr_results = []
            for (bbox, text, confidence) in results:
                if text.strip():  # Ignorar strings vazias
                    ocr_results.append({
                        'text': text.strip(),
                        'confidence': float(confidence),
                        'engine': 'easyocr',
                        'score': float(confidence),
                        'bbox': bbox
                    })

            return sorted(ocr_results, key=lambda x: x['confidence'], reverse=True)

        except Exception as e:
            logger.error(f"EasyOCR error: {e}")
            return []


# Instância global
_easyocr_wrapper = None

def get_easyocr() -> EasyOCRWrapper:
    """Obter wrapper singleton."""
    global _easyocr_wrapper
    if _easyocr_wrapper is None:
        _easyocr_wrapper = EasyOCRWrapper()
    return _easyocr_wrapper

def recognize_with_easyocr(image_path: str) -> List[Dict[str, Any]]:
    """Interface pública: reconhecer com EasyOCR."""
    wrapper = get_easyocr()

    if not wrapper.available:
        return []

    return wrapper.recognize(image_path)
