import ollama

def analyze_game_screen(image_path):
    print(f"L'IA analyse l'image : {image_path}...")
    
    try:
        with open(image_path, "rb") as f:
            response = ollama.generate(
                model='moondream',
                prompt='Describe this screen from the game Whiteout Survival. List the visible buttons, resources, and any red notification dots.',
                images=[f.read()]
            )
        
        print("\n--- ANALYSE DE L'IA ---")
        print(response['response'])
        print("------------------------")
    except Exception as e:
        print(f"Erreur lors de l'analyse : {e}")

if __name__ == "__main__":
    analyze_game_screen("test_view.png")