import cv2
import numpy as np
import time
import os
from ppadb.client import Client as AdbClient

# Configuration
ADB_HOST = "127.0.0.1"
ADB_PORT = 5037
TEMPLATE_DIR = "templates"

def connect_device():
    print("Tentative de connexion ADB...")
    client = AdbClient(host=ADB_HOST, port=ADB_PORT)
    devices = client.devices()
    
    if len(devices) == 0:
        print("Aucun appareil trouvé. Assure-toi que BlueStacks est lancé et ADB activé.")
        return None
    
    device = devices[0]
    print(f"Connecté à {device.serial}")
    return device

def take_screenshot(device):
    image = device.screencap()
    with open("screen.png", "wb") as f:
        f.write(image)
    
    # Charger l'image avec OpenCV
    img_cv = cv2.imread("screen.png")
    return img_cv

def find_image(screen, template_name, threshold=0.8):
    template_path = os.path.join(TEMPLATE_DIR, template_name)
    if not os.path.exists(template_path):
        print(f"Template introuvable : {template_name}")
        return None

    template = cv2.imread(template_path)
    if template is None:
        print(f"Erreur lecture template : {template_name}")
        return None

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        print(f"Trouvé {template_name} (Confiance: {max_val:.2f}) à {max_loc}")
        return max_loc, template.shape  # Retourne (x, y) et (h, w)
    else:
        # print(f"Non trouvé {template_name} (Max: {max_val:.2f})")
        return None

def main():
    device = connect_device()
    if not device:
        return

    print("Test de vue unique lancé...")
    screen = take_screenshot(device)
    cv2.imwrite("test_view.png", screen)
    print("Capture sauvegardée dans 'test_view.png'.")
    
    # Test de détection sur cette capture
    match = find_image(screen, "screenState.isWelcome.png")
    if match:
        print("Détecté : Écran de bienvenue !")
    else:
        print("Rien détecté pour l'instant, mais la capture est réussie.")

if __name__ == "__main__":
    main()
