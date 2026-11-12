"""Éléments partagés : carte en grille, Dijkstra, échanges JSON sur socket."""
import heapq
import json
import math

HOST, PORT = "127.0.0.1", 5000
CYCLE = 14.0                                   # durée d'un cycle de feu (s)

# La carte courante. Ces 3 objets sont modifiés « en place » (jamais remplacés) :
# tous les modules qui les importent voient donc la carte à jour.
NOEUDS = {}      # {"C1": (x, y)}
ROUTES = []      # [("C1", "C2")]
FEUX = []        # carrefours ayant au moins 3 routes : ils ont un feu


def maj_feux():
    FEUX[:] = [n for n in NOEUDS if sum(n in r for r in ROUTES) >= 3]


def definir_carte(noeuds, routes):
    """Remplace la carte courante (les routes qui citent un carrefour inconnu sont ignorées)."""
    noeuds = {n: tuple(p) for n, p in noeuds.items()}
    routes = [tuple(r) for r in routes if r[0] in noeuds and r[1] in noeuds]
    NOEUDS.clear()
    NOEUDS.update(noeuds)
    ROUTES[:] = routes
    maj_feux()


def grille(n=3):
    """Grille n x n sur 600x600 : C1 C2 C3 / C4 C5 C6 / ... Retourne (noeuds, routes)."""
    pas = 600 / n
    noeuds = {f"C{n * l + c + 1}": (round(pas / 2 + pas * c), round(pas / 2 + pas * l))
              for l in range(n) for c in range(n)}
    routes = ([(f"C{n * l + c + 1}", f"C{n * l + c + 2}") for l in range(n) for c in range(n - 1)]
              + [(f"C{n * l + c + 1}", f"C{n * (l + 1) + c + 1}") for l in range(n - 1) for c in range(n)])
    return noeuds, routes


definir_carte(*grille(3))


def longueur(a, b):
    return math.dist(NOEUDS[a], NOEUDS[b])


def dijkstra(facteurs, depart, arrivee):
    """Plus court chemin (heapq). facteurs[frozenset((a, b))] = ralentissement de la route.
    Retourne (chemin, cout) ou ([], inf)."""
    voisins = {n: [] for n in NOEUDS}
    for a, b in ROUTES:
        cout = longueur(a, b) * facteurs.get(frozenset((a, b)), 1.0)
        voisins[a].append((b, cout))
        voisins[b].append((a, cout))
    dist, prec, file = {depart: 0}, {}, [(0, depart)]
    while file:
        d, u = heapq.heappop(file)
        if u == arrivee:
            break
        if d > dist.get(u, math.inf):
            continue
        for v, cout in voisins[u]:
            if d + cout < dist.get(v, math.inf):
                dist[v] = d + cout
                prec[v] = u
                heapq.heappush(file, (d + cout, v))
    if arrivee not in dist:
        return [], math.inf
    chemin = [arrivee]
    while chemin[-1] != depart:
        chemin.append(prec[chemin[-1]])
    return chemin[::-1], dist[arrivee]


# ---------- réseau : 1 message = 1 objet JSON sur 1 ligne ----------
def ecrire(sock, msg):
    sock.sendall((json.dumps(msg) + "\n").encode())


def lire(sock):
    """Générateur : un dict par ligne reçue (makefile gère le découpage du flux TCP)."""
    for ligne in sock.makefile("r", encoding="utf-8"):
        try:
            yield json.loads(ligne)
        except json.JSONDecodeError:
            pass
