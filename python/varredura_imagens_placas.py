import os

print("[Varredura total do projeto por imagens de placas]")

for root, dirs, files in os.walk('.'):
    imagens = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if imagens:
        print(f"\nDiretório: {os.path.abspath(root)}")
        for img in imagens:
            print(f"  - {img}")
