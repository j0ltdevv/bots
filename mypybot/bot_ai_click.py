import ollama
import cv2
import numpy as np
from ppadb.client import Client as AdbClient
import json
import re

def get_device():
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    return devices[0] if devices else None

def click_at_percent(device, x_percent, y_percent):
    # Récupérer la taille de l'écran
    size = device.shell("wm size").split(" ")[-1].split("x")
    width, height = int(size[0]), int(size[1])
    
    # Calculer les coordonnées réelles
    real_x = int(width * x_percent / 100)
    real_y = int(height * y_percent / 100)
    
    print(f"Clic sur {real_x}, {real_y} ({x_percent}%, {y_percent}%)")
    device.input_tap(real_x, real_y)

def analyze_and_find_backpack(image_path):
    print("L'IA cherche le bouton 'Sac'...")
    with open(image_path, "rb") as f:
        # Prompt plus direct et descriptif
        prompt = "This is a mobile game called Whiteout Survival. Find the 'Backpack' (or Bag) icon, usually located in the bottom menu bar. Output only the coordinates in brackets like [y, x] where y and x are percentages from 0 to 100."
        response = ollama.generate(model='moondream', prompt=prompt, images=[f.read()])
    
    text = response['response'].strip()
    print(f"Réponse IA : {text}")
    
    # Extraire les nombres [y1, x1, y2, x2] ou [y, x]
    numbers = re.findall(r"0\.\d+|[0-9]+", text)
    if len(numbers) >= 4:
        # Format Bounding Box : [y1, x1, y2, x2]
        y1, x1, y2, x2 = [float(n) for n in numbers[:4]]
        # Si ce sont des décimales (0.65), on multiplie par 100
        if y1 < 1:
            return (x1 + x2) / 2 * 100, (y1 + y2) / 2 * 100
        else:
            return (x1 + x2) / 2, (y1 + y2) / 2
    elif len(numbers) >= 2:
        y, x = [float(n) for n in numbers[:2]]
        if y < 1: return x * 100, y * 100
        return x, y
    return None

def main():
    device = get_device()
    if not device:
        print("BlueStacks non trouvé !")
        return

    # 1. Prendre la photo
    print("Capture de l'écran...")
    image = device.screencap()
    with open("current_screen.png", "wb") as f:
        f.write(image)

    # 2. Demander à l'IA
    coords = analyze_and_find_backpack("current_screen.png")
    
    if coords:
        x, y = coords
        # 3. Cliquer !
        click_at_percent(device, x, y)
    else:
        print("L'IA n'a pas pu localiser le sac précisément.")

if __name__ == "__main__":
    main()
