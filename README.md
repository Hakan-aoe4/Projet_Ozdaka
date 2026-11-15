# OzdAka — Gestion du trafic pour véhicules d'urgence (V2X / V2I)

## 1. Identification

| | |
|---|---|
| **Projet** | SAÉ 3.02 — BUT Réseaux & Télécommunications |
| **Nom du groupe** | **OzdAka** |
| **Étudiants** | **AKAKCA** Hakan — interface (IHM) et simulation |
| | **OZDEMIR** Furkan — réseau (serveur, protocole, carrefours) |
| **Encadrant** | M. Drouhin |
| **Dépôt** | https://github.com/Hakan-aoe4/Projet_Ozdaka |

## 2. Présentation

Une ambulance, un véhicule de police ou des pompiers perdent du temps dans la circulation
(bouchons, accidents, travaux, feux rouges). OzdAka simule ce problème et sa solution :

- le véhicule d'urgence calcule le **trajet le plus rapide** (algorithme de Dijkstra) en tenant compte du trafic, et le **recalcule** quand un accident ou un embouteillage apparaît ;
- à l'approche d'un carrefour, il **demande le vert** aux feux par message réseau (**V2I**, *Vehicle-to-Infrastructure*) ;
- les carrefours, le serveur et la carte sont des **programmes séparés** qui communiquent par **sockets TCP** (messages JSON) ;
- chaque mission est enregistrée par le serveur dans une **base SQLite**, consultable et exportable en CSV depuis l'application.

Technologies : **Python 3.12**, **PyQt6** (interface), `socket`, `threading`, `json`, `sqlite3`, `heapq` (bibliothèque standard).

## 3. Documentation d'usage

Toute la documentation d'usage (lancement de l'application, configuration, exemples d'utilisation)
est dans **`Fonctionnement_de_lappli_OZDAKA.pdf`**, à la racine du dépôt.

## 4. Organisation du code

| Fichier | Rôle |
|---|---|
| `commun.py` | carte partagée, grille, algorithme de Dijkstra (`heapq`), envoi / lecture des messages JSON |
| `serveur.py` | serveur central en étoile : relaie chaque message aux autres clients (un thread par client) et tient la base de l'historique |
| `carrefours.py` | client sans fenêtre : cycle des feux, réponse aux demandes de vert |
| `reseau.py` | côté IHM : client TCP dans un `QThread`, démarrage automatique du serveur et des carrefours, V2I, historique |
| `vue.py` | affichage de la carte (routes, carrefours, feux, véhicule), sans logique métier |
| `simulation.py` | mission : itinéraire, déplacement, arrêt aux feux, accidents, trafic |
| `editeur.py` | mode édition et lecture / écriture des fichiers de cartes |
| `historique.py` | historique des missions dans une base SQLite (`historique.db`), utilisé par le serveur |
| `carte.py` | fenêtre principale : panneau de commande, import de plan, historique et export CSV |
| `cartes/` | cartes d'exemple (`.json` + image) |
| `run.bat` | lanceur Windows (venv + dépendances + programme) |

Chaque fonction et chaque classe est documentée par une docstring (style Google, en français).

### Protocole réseau

Un message = un objet JSON sur une ligne (séparateur `\n`).

| Type | Sens | Contenu |
|---|---|---|
| `CARTE` | carte → carrefours | `id`, `noeuds`, `routes` |
| `FEUX` | carrefours → carte | `carte` (id), `etats` : `{carrefour: {"EO": couleur, "NS": couleur}}` |
| `DEMANDE_VERT` | carte → carrefours | `carrefour`, `phase` (`EO` ou `NS`) |
| `FIN_VERT` | carte → carrefours | `carrefour` |
| `FIN_MISSION` | carte → serveur | `vehicule`, `depart`, `arrivee`, `v2i`, `temps`, `estime`, `direct`, `attente`, `recalculs` |
| `DEMANDE_HISTORIQUE` | carte → serveur | — |
| `HISTORIQUE` | serveur → carte | `missions` : liste des 50 dernières missions |

`FIN_MISSION` et `DEMANDE_HISTORIQUE` sont traités par le serveur lui-même et ne sont pas relayés.
La base `historique.db` est donc sur la machine du serveur (créée automatiquement, non versionnée).

### Format d'une carte (`cartes/*.json`)

```json
{"image": "quartier.png", "largeur": 925, "hauteur": 581,
 "noeuds": {"C1": [28, 35], "C34": [105, 66]},
 "routes": [["C1", "C34"]]}
```

`image` vaut `null` pour une carte sans fond. Un carrefour qui a **3 routes ou plus** reçoit un feu.

## 5. Documents rendus

- `Fonctionnement_de_lappli_OZDAKA.pdf` : mode d'emploi de l'application (installation et utilisation, avec captures).
- `Bilan_Projet.pdf` : bilan des fonctionnalités par rapport au cahier des charges, conclusion technique et organisationnelle, analyse du planning.
- `IAGraphie.pdf` : usage de l'IA pendant le projet (cartographie, traçabilité des prompts, réflexion éthique).
