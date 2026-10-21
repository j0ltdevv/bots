import cv2

def multi_viz(image_path, output_path):
    img = cv2.imread(image_path)
    if img is None: return
    
    # On teste 4 positions
    points = {
        "BLEU": (580, 1050),
        "VERT": (620, 1030),
        "JAUNE": (550, 1040),
        "MAUVE": (500, 1060)
    }
    
    colors = {
        "BLEU": (255, 0, 0),
        "VERT": (0, 255, 0),
        "JAUNE": (0, 255, 255),
        "MAUVE": (255, 0, 255)
    }

    for name, pos in points.items():
        cv2.circle(img, pos, 15, colors[name], -1)
        cv2.putText(img, name, (pos[0] + 20, pos[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colors[name], 2)

    cv2.imwrite(output_path, img)
    print(f"Nouvelle image de test générée : {output_path}")

if __name__ == "__main__":
    multi_viz("my_game_screen.png", "test_multi_points.png")
