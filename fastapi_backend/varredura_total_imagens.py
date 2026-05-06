import os

print("[Varredura total do projeto por imagens .jpg/.jpeg/.png]")

encontradas = []
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            caminho = os.path.abspath(os.path.join(root, f))
            encontradas.append(caminho)
            print(caminho)

print(f"\nTotal de imagens encontradas: {len(encontradas)}")
if not encontradas:
    print("Nenhuma imagem encontrada no projeto.")
