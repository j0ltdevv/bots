import cv2
import numpy as np

def draw_grid(image_path, output_path):
    img = cv2.imread(image_path)
    if img is None:
        print("Erreur : Image non trouvée.")
        return
    
    h, w = img.shape[:2]
    
    # Paramètres de la grille
    rows = 20
    cols = 20
    
    # Dessiner les lignes
    for i in range(1, cols):
        x = int(i * w / cols)
        cv2.line(img, (x, 0), (x, h), (255, 0, 0), 1)
        # Ajouter les lettres (A, B, C...)
        cv2.putText(img, chr(64 + i), (x + 5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)

    for j in range(1, rows):
        y = int(j * h / rows)
        cv2.line(img, (0, y), (w, y), (255, 0, 0), 1)
        # Ajouter les chiffres (1, 2, 3...)
        cv2.putText(img, str(j), (5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)

    cv2.imwrite(output_path, img)
    print(f"Grille générée dans : {output_path}")

if __name__ == "__main__":
    draw_grid("my_game_screen.png", "my_game_grid.png")
