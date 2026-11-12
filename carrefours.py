"""Client carrefours (sans fenêtre) : gère les feux de tous les carrefours.

Il publie l'état des feux et, sur demande V2I d'un véhicule, passe son axe au vert.
Quand la carte change, la carte (IHM) lui envoie la nouvelle (message CARTE).
Lancement :  python carrefours.py   (démarré automatiquement par carte.py)
"""
import random
import socket
import threading
import time

from commun import CYCLE, FEUX, HOST, PORT, definir_carte, ecrire, lire

decalage = {n: random.uniform(0, CYCLE) for n in FEUX}   # chaque carrefour a son décalage
priorite = {}                                            # carrefour -> axe tenu au vert
id_carte = 0                                             # identifie la carte utilisée
nouvelle = []                                            # message CARTE reçu, à appliquer


def ecouter(sock):
    for msg in lire(sock):
        if msg.get("type") == "DEMANDE_VERT":
            priorite[msg["carrefour"]] = msg["phase"]
        elif msg.get("type") == "FIN_VERT":
            priorite.pop(msg["carrefour"], None)
        elif msg.get("type") == "CARTE":
            nouvelle[:] = [msg]                          # appliqué par la boucle principale


def appliquer(msg):
    global id_carte, decalage
    if msg["id"] == id_carte:
        return
    definir_carte(msg["noeuds"], msg["routes"])
    decalage = {n: random.uniform(0, CYCLE) for n in FEUX}
    priorite.clear()
    id_carte = msg["id"]
    print(f"Nouvelle carte : {len(FEUX)} carrefours à feux")


def etat(nom, phase, horloge):
    forcee = priorite.get(nom)
    if forcee:
        return "vert" if forcee == phase else "rouge"
    c = (horloge + decalage[nom]) % CYCLE
    if phase == "NS":
        c = (c + CYCLE / 2) % CYCLE                      # l'autre axe est en opposition
    return "vert" if c < 6 else "orange" if c < 7 else "rouge"


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
