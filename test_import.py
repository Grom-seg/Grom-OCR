#!/usr/bin/env python
try:
    from fastapi_backend import main
    print("✓ Imports OK - main.py carregado")
except Exception as e:
    print(f"✗ Import Error: {e}")
    import traceback
    traceback.print_exc()
