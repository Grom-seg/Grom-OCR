import cv2

video = r"C:\Users\Família Grom\Downloads\VID-20260412-WA0023.mp4"
cap = cv2.VideoCapture(video)
fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"FPS: {fps}  Frames: {total}  Duracao: {round(total/fps,1)}s")

# Extrai 3 frames de posições diferentes
for pos in [0, 9000, 18183]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
    ok, frame = cap.read()
    if ok:
        h, w = frame.shape[:2]
        print(f"Frame #{pos} @ {round(pos/fps,1)}s  resolucao: {w}x{h}")
        cv2.imwrite(rf"C:\Grom_OCR\frame_{pos}.jpg", frame)

cap.release()
print("Frames salvos.")
