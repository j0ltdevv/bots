import cv2
import numpy as np
import os
from ppadb.client import Client as AdbClient

def connect_adb():
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    if not devices:
        return None
    return devices[0]

def find_and_click(device, template_path, threshold=0.7):
    # Prendre screenshot
    image = device.screencap()
    screen = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    
    # Charger template
    template = cv2.imread(template_path)
    if template is None:
        print(f"Erreur : Impossible de lire {template_path}")
        return False

    # Template Matching
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2
        print(f"Trouvé {os.path.basename(template_path)} ! Clic sur {center_x}, {center_y} (Confiance: {max_val:.2f})")
        device.input_tap(center_x, center_y)
        return True
    
    print(f"Non trouvé : {os.path.basename(template_path)} (Max: {max_val:.2f})")
    return False

def main():
    device = connect_adb()
    if not device:
        print("BlueStacks non trouvé !")
        return

    # Chemin vers l'image du sac qu'on a récupérée
    backpack_template = r"D:\Bots\whiteout-survival-autopilot\references\screenshots\backpack.png"
    
    print("Recherche du sac avec OpenCV...")
    if not find_and_click(device, backpack_template):
        print("Échec de la détection précise.")

if __name__ == "__main__":
    main()