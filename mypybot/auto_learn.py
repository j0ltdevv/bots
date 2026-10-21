import ollama
import cv2
import re
import os

def auto_learn_button(image_path, button_name, output_name):
    print(f"L'IA analyse ton écran pour apprendre le bouton '{button_name}'...")
    
    with open(image_path, "rb") as f:
        prompt = f"Find the '{button_name}' icon in this game screenshot. Return the coordinates as [y1, x1, y2, x2] where 0 is top/left and 100 is bottom/right."
        response = ollama.generate(model='moondream', prompt=prompt, images=[f.read()])
    
    text = response['response']
    print(f"IA dit : {text}")
    
    # Extraire les coordonnées
    numbers = re.findall(r"0\.\d+|[0-9]+", text)
    if len(numbers) >= 4:
        y1, x1, y2, x2 = [float(n) for n in numbers[:4]]
        # Si c'est en 0.x, on passe en pourcent
        if y1 < 1:
            y1, x1, y2, x2 = y1*100, x1*100, y2*100, x2*100
            
        # Charger l'image originale pour découper
        img = cv2.imread(image_path)
        h, w = img.shape[:2]
        
        # Calcul des pixels
        px1, py1 = int(x1 * w / 100), int(y1 * h / 100)
        px2, py2 = int(x2 * w / 100), int(y2 * h / 100)
        
        # Découpage du template (on ajoute une petite marge)
        crop = img[py1:py2, px1:px2]
        if crop.size > 0:
            template_path = f"templates/{output_name}.png"
            cv2.imwrite(template_path, crop)
            print(f"Bouton appris et sauvegardé dans : {template_path}")
            return True
    
    print("L'IA n'a pas pu donner de coordonnées précises.")
    return False

if __name__ == "__main__":
    if not os.path.exists("templates"): os.makedirs("templates")
    auto_learn_button("my_game_screen.png", "backpack", "backpack_auto")
