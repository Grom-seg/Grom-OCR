#!/usr/bin/env python
"""
Fix main.py - remover bagunça de linhas 603-642
"""

with open(r'c:\Grom_OCR\fastapi_backend\main.py', 'r') as f:
    # -*- coding: utf-8 -*-
    """
    Fix main.py
    """

    with open(r'c:\Grom_OCR\fastapi_backend\main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Remover linhas 603-643 (índices 602-642)
# Mostrar o que será removido
print("Removendo linhas 603-643:")
for i in range(602, min(643, len(lines))):
    print(f"  {i+1}: {lines[i][:80]}")

# Remover
new_lines = lines[:602] + lines[643:]

# Escrever
with open(r'c:\Grom_OCR\fastapi_backend\main.py', 'w') as f:
    f.writelines(new_lines)

print("\n✓ Arquivo corrigido!")
print(f"Total linhas antes: {len(lines)}")
print(f"Total linhas depois: {len(new_lines)}")

# Testar syntax
import subprocess
result = subprocess.run([
    r'c:\Grom_OCR\.venv\Scripts\python.exe', '-m', 'py_compile',
    r'c:\Grom_OCR\fastapi_backend\main.py'
], capture_output=True, text=True)

if result.returncode == 0:
    print("✓ Syntax OK!")
else:
    print("✗ Syntax erro:")
    print(result.stderr)
