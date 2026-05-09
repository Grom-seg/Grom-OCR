#!/usr/bin/env python
try:
    import easyocr
    print("✓ EasyOCR importado com sucesso")
    print(f"  Versão: {easyocr.__version__ if hasattr(easyocr, '__version__') else 'unknown'}")
except ModuleNotFoundError as e:
    print(f"✗ EasyOCR não encontrado: {e}")
except Exception as e:
    print(f"✗ Erro ao importar: {e}")
