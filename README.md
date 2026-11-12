# OzdAka (version simplifiée)

SAÉ 3.02 : gestion du trafic pour véhicules d'urgence (V2X / V2I). Python 3.12 + PyQt6 uniquement.

## Lancer (Windows)
Double-clic sur `run.bat` : il crée le venv, installe PyQt6, ouvre le serveur, les carrefours et la carte.

À la main (3 terminaux) :
```
python serveur.py
python carrefours.py
python carte.py
```

## Utilisation
- Clic gauche : départ (A) puis arrivée (B), puis « Lancer la mission »
- Clic droit sur une route : accident / travaux (bloque ou rouvre)
- « Priorité V2I » : le carrefour passe au vert à l'approche du véhicule
- « Trafic aléatoire » : le trafic change toutes les 4 s, l'itinéraire est recalculé

## Fichiers
| Fichier | Rôle |
|---|---|
| `commun.py` | carte en grille, Dijkstra (heapq), envoi/lecture JSON sur socket |
| `serveur.py` | serveur central : relaie chaque message aux autres clients (socket + threading) |
| `carrefours.py` | client carrefours : cycle des feux + réponse aux demandes V2I |
| `carte.py` | IHM PyQt6 + simulation ; la réception réseau passe par un `QThread` et un `pyqtSignal` |

Messages JSON : `FEUX` (carrefours → carte), `DEMANDE_VERT` et `FIN_VERT` (carte → carrefours).
