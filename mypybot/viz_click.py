import cv2

def visualize_click(image_path, x, y, output_path):
    img = cv2.imread(image_path)
    if img is None:
        print("Image non trouvée.")
        return
    
    # Dessiner un gros cercle rouge là où on clique
    cv2.circle(img, (x, y), 20, (0, 0, 255), -1) # Cercle plein
    cv2.circle(img, (x, y), 25, (255, 255, 255), 2) # Bordure blanche
    
    # Ajouter les coordonnées en texte
    cv2.putText(img, f"CLIC ICI ({x},{y})", (x + 30, y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
    
    cv2.imwrite(output_path, img)
    print(f"Image de contrôle générée : {output_path}")

if __name__ == "__main__":
    # On teste les dernières coordonnées utilisées (672, 1026)
    visualize_click("my_game_screen.png", 672, 1026, "test_click_viz.png")
