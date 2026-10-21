import cv2
import os

def crop_from_grid(image_path, start_col, end_col, start_row, end_row, output_name):
    img = cv2.imread(image_path)
    if img is None:
        print("Erreur : Image non trouvée.")
        return
    
    h, w = img.shape[:2]
    
    # Conversion Lettres -> Chiffres (A=1, B=2...)
    def col_to_idx(col): return ord(col.upper()) - 64

    # Calcul des pixels (sur une grille 20x20)
    x1 = int((col_to_idx(start_col) - 1) * w / 20)
    x2 = int(col_to_idx(end_col) * w / 20)
    y1 = int((start_row - 1) * h / 20)
    y2 = int(end_row * h / 20)
    
    # Découpage
    crop = img[y1:y2, x1:x2]
    
    if not os.path.exists("templates"):
        os.makedirs("templates")
        
    output_path = f"templates/{output_name}.png"
    cv2.imwrite(output_path, crop)
    print(f"Template créé : {output_path} ({x2-x1}x{y2-y1} pixels)")

if __name__ == "__main__":
    # EXEMPLE : Découper le sac entre F19 et H20
    # Tu peux modifier ces valeurs juste en dessous
    crop_from_grid("my_game_screen.png", "F", "H", 19, 20, "sac")
