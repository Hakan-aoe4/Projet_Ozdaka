"""Éléments partagés : carte en grille, Dijkstra, échanges JSON sur socket."""
import heapq
import json
import math

HOST, PORT = "127.0.0.1", 5000
CYCLE = 14.0                                   # durée d'un cycle de feu (s)

# Carte 3x3 : C1 C2 C3 / C4 C5 C6 / C7 C8 C9
NOEUDS = {f"C{3 * l + c + 1}": (100 + 200 * c, 100 + 200 * l)
          for l in range(3) for c in range(3)}
ROUTES = ([(f"C{i}", f"C{i + 1}") for i in (1, 2, 4, 5, 7, 8)]
          + [(f"C{i}", f"C{i + 3}") for i in range(1, 7)])
# un feu par carrefour ayant au moins 3 routes
FEUX = [n for n in NOEUDS if sum(n in r for r in ROUTES) >= 3]


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
