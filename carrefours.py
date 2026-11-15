"""Client « carrefours » d'OzdAka (sans fenêtre) : gère les feux de tous les carrefours.

Il publie l'état des feux dix fois par seconde et, sur demande V2I d'un véhicule
d'urgence, passe l'axe demandé au vert (priorité). Quand la carte change, l'IHM lui
envoie la nouvelle carte (message CARTE).

Lancement :  python carrefours.py   (démarré automatiquement par carte.py)
"""
import random
import socket
import threading
import time

from commun import CYCLE, FEUX, HOST, PORT, definir_carte, ecrire, lire

decalage = {n: random.uniform(0, CYCLE) for n in FEUX}   # décalage de cycle de chaque carrefour
priorite = {}        # carrefour -> axe tenu au vert pour un véhicule d'urgence
id_carte = 0         # identifiant de la carte actuellement utilisée
nouvelle = []        # dernier message CARTE reçu, appliqué par la boucle principale


def ecouter(sock):
    """Thread d'écoute : traite les messages V2I et mémorise les changements de carte.

    Args:
        sock: socket connectée au serveur.
    """
    for msg in lire(sock):
        if msg.get("type") == "DEMANDE_VERT":
            priorite[msg["carrefour"]] = msg["phase"]
        elif msg.get("type") == "FIN_VERT":
            priorite.pop(msg["carrefour"], None)
        elif msg.get("type") == "CARTE":
            nouvelle[:] = [msg]          # appliqué par la boucle principale (pas ici : thread)


def appliquer(msg):
    """Adopte la carte reçue : nouvelle liste de carrefours à feux, nouveaux décalages.

    Args:
        msg: message CARTE {"id", "noeuds", "routes"}. Ignoré si on a déjà cette carte.
    """
    global id_carte, decalage
    if msg["id"] == id_carte:
        return
    definir_carte(msg["noeuds"], msg["routes"])
    decalage = {n: random.uniform(0, CYCLE) for n in FEUX}
    priorite.clear()
    id_carte = msg["id"]
    print(f"Nouvelle carte : {len(FEUX)} carrefours à feux")


def etat(nom, phase, horloge):
    """Calcule la couleur d'un feu.

    Un axe prioritaire (demande V2I) est vert, l'autre rouge. Sinon les deux axes
    alternent sur un cycle de 14 s : vert 6 s, orange 1 s, rouge 7 s.

    Args:
        nom: nom du carrefour.
        phase: axe du feu, "EO" (est-ouest) ou "NS" (nord-sud).
        horloge: temps écoulé depuis le démarrage (s).

    Returns:
        "vert", "orange" ou "rouge".
    """
    forcee = priorite.get(nom)
    if forcee:
        return "vert" if forcee == phase else "rouge"
    c = (horloge + decalage[nom]) % CYCLE
    if phase == "NS":
        c = (c + CYCLE / 2) % CYCLE      # l'autre axe est en opposition de phase
    return "vert" if c < 6 else "orange" if c < 7 else "rouge"


def main():
    """Se connecte au serveur puis publie l'état de tous les feux en boucle."""
    sock = socket.create_connection((HOST, PORT))
    threading.Thread(target=ecouter, args=(sock,), daemon=True).start()
    print("Carrefours connectés au serveur (Ctrl+C pour arrêter)")
    debut = time.time()
    try:
        while True:
            if nouvelle:
                appliquer(nouvelle.pop())
            h = time.time() - debut
            ecrire(sock, {"type": "FEUX", "carte": id_carte,
                          "etats": {n: {p: etat(n, p, h) for p in ("EO", "NS")} for n in FEUX}})
            time.sleep(0.1)
    except (OSError, KeyboardInterrupt):
        print("Arrêt")


if __name__ == "__main__":
    main()
