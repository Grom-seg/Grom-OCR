#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import time
import json

print("Aguardando 10 segundos para API inicializar modelos...", flush=True)
time.sleep(10)

try:
    r = requests.get('http://127.0.0.1:8000/health', timeout=5)
    print("✓ API Health OK:", json.dumps(r.json(), indent=2), flush=True)
except ConnectionRefusedError:
    print("✗ Porta 8000 ainda não está aberta. API ainda não levantou.", flush=True)
except Exception as e:
    print(f"✗ Erro ao conectar: {str(e)}", flush=True)
