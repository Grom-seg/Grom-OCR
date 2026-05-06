import os

ORIGEM = r"C:\Users\Família Grom\OneDrive\Desktop\Josuel\Placas"

print(f"Listando imagens em: {ORIGEM}\n")
if not os.path.exists(ORIGEM):
    print(f"[ERRO] Caminho não encontrado: {ORIGEM}")
    exit(1)

imagens = []
for root, dirs, files in os.walk(ORIGEM):
    for f in files:
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            imagens.append(os.path.join(root, f))

if imagens:
    for img in imagens:
        print(img)
    print(f"\nTotal de imagens encontradas: {len(imagens)}")
else:
    print("Nenhuma imagem encontrada.")
