import time
from ppadb.client import Client as AdbClient

# Configuration des boutons (X%, Y%)
# G20 -> Col 7 sur 20 (approx 32.5%), Row 20 sur 20 (approx 97.5%)
BUTTONS = {
    "sac": (35.0, 95.0), # Un peu plus haut et à droite dans G20
    # On ajoutera les autres ici
}

def connect_adb():
    client = AdbClient(host="127.0.0.1", port=5037)
    devices = client.devices()
    return devices[0] if devices else None

def click_button(device, name):
    if name not in BUTTONS:
        print(f"Bouton {name} inconnu.")
        return
    
    x_pc, y_pc = BUTTONS[name]
    
    # Récupérer la taille réelle de l'écran
    size = device.shell("wm size").split(" ")[-1].split("x")
    width, height = int(size[0]), int(size[1])
    
    real_x = int(width * x_pc / 100)
    real_y = int(height * y_pc / 100)
    
    print(f"Action : Clic sur {name} ({real_x}, {real_y})")
    device.input_tap(real_x, real_y)

if __name__ == "__main__":
    device = connect_adb()
    if device:
        print("Bot prêt !")
        click_button(device, "sac")
    else:
        print("BlueStacks non trouvé.")
