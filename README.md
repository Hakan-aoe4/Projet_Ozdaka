# OzdAka (version simplifiée)

SAÉ 3.02 : gestion du trafic pour véhicules d'urgence (V2X / V2I). Python 3.12 + PyQt6 uniquement.

## Lancer (Windows)
Double-clic sur `run.bat`. Il crée le venv, installe PyQt6 si besoin, puis ouvre la carte.
La carte démarre toute seule le serveur et les carrefours (rien d'autre à lancer).

À la main : `python carte.py`. On peut aussi lancer `python serveur.py` puis `python carrefours.py`
dans deux autres terminaux avant : la carte s'y connecte alors au lieu de les démarrer.

## Le panneau de droite
| Section | Rôle |
|---|---|
| **Carte** | Nouvelle grille (taille au choix), importer une capture d'écran, charger / enregistrer une carte, mode édition |
| **Mission** | choix du véhicule (ambulance, police, pompiers), lancer, réinitialiser |
| **Simulation** | priorité V2I, trafic aléatoire |

## Créer sa propre carte à partir d'une capture d'écran
1. Fais une capture d'écran d'un plan (OpenStreetMap, Google Maps…), en `.png` ou `.jpg`.
2. **Importer une capture d'écran…** : l'image devient le fond et le mode édition s'active.
3. Clic sur le vide : nouveau carrefour. Clic sur 2 carrefours : route entre eux.
   Clic droit sur un carrefour ou une route : le supprimer.
4. Décoche **Mode édition**, puis **Enregistrer…** (dans `cartes/`) : un `.json` et une copie de l'image.
5. **Charger…** pour la rouvrir plus tard. Deux cartes d'exemple sont dans `cartes/`.

## Simulation
- Clic gauche : départ (A) puis arrivée (B), puis « Lancer la mission »
- Clic droit sur une route : accident / travaux (bloque ou rouvre), l'itinéraire est recalculé
- « Priorité V2I » : le carrefour passe au vert à l'approche du véhicule
- « Trafic aléatoire » : le trafic change toutes les 4 s

## Fichiers
| Fichier | Rôle |
|---|---|
| `commun.py` | carte courante, grille, Dijkstra (heapq), envoi/lecture JSON sur socket |
| `serveur.py` | serveur central : relaie chaque message aux autres clients (socket + threading) |
| `carrefours.py` | client carrefours : cycle des feux + réponse aux demandes V2I |
| `carte.py` | IHM PyQt6 + simulation + éditeur ; réception réseau via `QThread` + `pyqtSignal` |
| `cartes/` | cartes enregistrées (`.json` + image) |

Messages JSON : `CARTE` (carte → carrefours), `FEUX` (carrefours → carte),
`DEMANDE_VERT` et `FIN_VERT` (carte → carrefours).
