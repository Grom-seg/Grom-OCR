import os
import requests
import cv2
import numpy as np

API_URL = "http://localhost:5000/process_simple"

def create_test_image():
    # Create a 200x200 black image with a white text
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.putText(img, "ABC1234", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    filename = "smoke_test.jpg"
    cv2.imwrite(filename, img)
    return filename

def run_smoke_test():
    filename = create_test_image()
    
    print(f"Sending {filename} to {API_URL}...")
    try:
        with open(filename, 'rb') as f:
            files = {'image': (filename, f, 'image/jpeg')}
            response = requests.post(API_URL, files=files, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print("Success! API response received.")
            print(f"OCR Result: {data.get('ocr')}")
        else:
            print(f"Error! API returned {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Request failed: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    run_smoke_test()
