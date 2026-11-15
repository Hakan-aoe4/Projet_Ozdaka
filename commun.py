"""Éléments partagés par tous les programmes d'OzdAka.

Ce module contient :
  - la carte courante (carrefours, routes, carrefours à feux), modifiée « en place » ;
  - la grille par défaut ;
  - l'algorithme de Dijkstra (implémentation maison avec heapq) ;
  - les deux fonctions d'échange de messages JSON sur socket TCP.
"""
import heapq
import json
import math

# ---------- constantes ----------
HOST, PORT = "127.0.0.1", 5000      # adresse du serveur central
CYCLE = 14.0                        # durée d'un cycle de feu (s)
BLOQUE = 1e6                        # facteur de coût d'une route bloquée (accident, travaux)
RAYON_BASE = 16                     # rayon d'un carrefour sur une carte 600x600 (px)
VITESSE_BASE = 120.0                # vitesse du véhicule sur route fluide, carte 600x600 (px/s)

# ---------- la carte courante ----------
# Ces trois objets sont modifiés « en place » (jamais remplacés par un nouvel objet) :
# tous les modules qui les importent voient donc toujours la carte à jour.
NOEUDS = {}      # {"C1": (x, y)} : position de chaque carrefour
ROUTES = []      # [("C1", "C2")] : routes à double sens entre deux carrefours
FEUX = []        # carrefours ayant au moins 3 routes : ce sont eux qui ont un feu


def maj_feux():
    """Recalcule la liste des carrefours à feux (au moins 3 routes) d'après la carte courante."""
    FEUX[:] = [n for n in NOEUDS if sum(n in r for r in ROUTES) >= 3]


def definir_carte(noeuds, routes):
    """Remplace la carte courante.

    Les routes qui citent un carrefour inconnu sont ignorées.

    Args:
        noeuds: dictionnaire {nom: (x, y)} des carrefours.
        routes: liste de couples (nom_a, nom_b).
    """
    # On copie d'abord : les arguments peuvent être NOEUDS/ROUTES eux-mêmes.
    noeuds = {n: tuple(p) for n, p in noeuds.items()}
    routes = [tuple(r) for r in routes if r[0] in noeuds and r[1] in noeuds]
    NOEUDS.clear()
    NOEUDS.update(noeuds)
    ROUTES[:] = routes
    maj_feux()


def grille(n=3):
    """Construit une grille n x n sur une carte de 600x600 : C1 C2 C3 / C4 C5 C6 / ...

    Args:
        n: nombre de carrefours par côté.

    Returns:
        Le couple (noeuds, routes) à passer à definir_carte().
    """
    pas = 600 / n
    noeuds = {f"C{n * l + c + 1}": (round(pas / 2 + pas * c), round(pas / 2 + pas * l))
              for l in range(n) for c in range(n)}
    routes = ([(f"C{n * l + c + 1}", f"C{n * l + c + 2}") for l in range(n) for c in range(n - 1)]
              + [(f"C{n * l + c + 1}", f"C{n * (l + 1) + c + 1}") for l in range(n - 1) for c in range(n)])
    return noeuds, routes


definir_carte(*grille(3))           # carte par défaut au démarrage


# ---------- calcul d'itinéraire ----------
def longueur(a, b):
    """Calcule la distance entre deux carrefours.

    Args:
        a, b: noms des carrefours.

    Returns:
        La distance en pixels de carte (float).
    """
    return math.dist(NOEUDS[a], NOEUDS[b])


def dijkstra(facteurs, depart, arrivee):
    """Cherche le chemin le plus court avec l'algorithme de Dijkstra (file de priorité heapq).

    Le coût d'une route est sa longueur multipliée par son facteur de ralentissement.

    Args:
        facteurs: dictionnaire {frozenset((a, b)): ralentissement}. Une route absente vaut 1.0.
        depart: nom du carrefour de départ.
        arrivee: nom du carrefour d'arrivée.

    Returns:
        Le couple (chemin, cout) où chemin est la liste des carrefours à traverser,
        ou ([], inf) si l'arrivée est inatteignable.
    """
    voisins = {n: [] for n in NOEUDS}            # liste d'adjacence : carrefour -> (voisin, coût)
    for a, b in ROUTES:
        cout = longueur(a, b) * facteurs.get(frozenset((a, b)), 1.0)
        voisins[a].append((b, cout))
        voisins[b].append((a, cout))
    dist, precedent, file = {depart: 0}, {}, [(0, depart)]
    while file:
        d, u = heapq.heappop(file)
        if u == arrivee:
            break
        if d > dist.get(u, math.inf):            # entrée périmée de la file : on l'ignore
            continue
        for v, cout in voisins[u]:
            if d + cout < dist.get(v, math.inf):
                dist[v] = d + cout
                precedent[v] = u
                heapq.heappush(file, (d + cout, v))
    if arrivee not in dist:
        return [], math.inf
    chemin = [arrivee]                           # on remonte les « précédents » depuis l'arrivée
    while chemin[-1] != depart:
        chemin.append(precedent[chemin[-1]])
    return chemin[::-1], dist[arrivee]


# ---------- réseau : 1 message = 1 objet JSON sur 1 ligne ----------
def ecrire(sock, msg):
    """Envoie un message (dictionnaire) sur la socket, en JSON suivi d'un retour à la ligne.

    Args:
        sock: socket TCP connectée.
        msg: dictionnaire JSON-compatible à envoyer.
    """
    sock.sendall((json.dumps(msg) + "\n").encode())


def lire(sock):
    """Générateur : produit un dictionnaire pour chaque ligne JSON reçue sur la socket.

    Le retour à la ligne sert de séparateur de messages (TCP est un flux sans frontières) ;
    makefile() se charge de reconstituer les lignes. Les lignes invalides sont ignorées.

    Args:
        sock: socket TCP connectée.

    Yields:
        Un dictionnaire par message reçu.
    """
    for ligne in sock.makefile("r", encoding="utf-8"):
        try:
            yield json.loads(ligne)
        except json.JSONDecodeError:
            pass
