"""Édition de la carte (ajout / suppression de carrefours et de routes) et fichiers de cartes.

Une carte est un fichier JSON :
    {"image": "quartier.png" ou null, "largeur": W, "hauteur": H,
     "noeuds": {"C1": [x, y], ...}, "routes": [["C1", "C2"], ...]}
L'image de fond (plan de la carte) est enregistrée à côté du JSON.
"""
import json
import os

from PyQt6.QtGui import QPixmap

from commun import NOEUDS, ROUTES, maj_feux


class Editeur:
    """Logique du mode édition : transforme les clics en modifications de la carte courante.

    Attributes:
        selection: carrefour choisi comme début d'une route (None si aucun).
    """

    def __init__(self, vue):
        """Crée un éditeur.

        Args:
            vue: VueCarte, utilisée pour savoir quel carrefour / quelle route est sous le clic.
        """
        self.vue = vue
        self.selection = None

    def clic(self, x, y, droit):
        """Traite un clic en mode édition (l'appelant doit ensuite redessiner la carte).

        Clic sur le vide : nouveau carrefour. Clic sur deux carrefours : route entre eux.
        Clic droit : supprime le carrefour ou la route visé.

        Args:
            x, y: position du clic sur la carte.
            droit: True pour un clic droit.
        """
        nom = self.vue.noeud_en(x, y)
        if droit:
            self.supprimer(nom, x, y)
        elif nom is None:
            self.ajouter_noeud(x, y)
        else:
            self.relier(nom)
        maj_feux()                                  # le nombre de routes par carrefour a changé

    def ajouter_noeud(self, x, y):
        """Crée un carrefour au point (x, y), avec le premier nom « Cn » libre.

        Args:
            x, y: position du nouveau carrefour sur la carte.
        """
        i = 1
        while f"C{i}" in NOEUDS:
            i += 1
        NOEUDS[f"C{i}"] = (round(x), round(y))
        self.selection = None

    def relier(self, nom):
        """Sélectionne un carrefour, ou le relie au carrefour déjà sélectionné par une route.

        Args:
            nom: carrefour sur lequel l'utilisateur a cliqué.
        """
        if self.selection is None:
            self.selection = nom
            return
        deja = frozenset((nom, self.selection)) in map(frozenset, ROUTES)
        if nom != self.selection and not deja:      # ni boucle sur soi-même, ni doublon
            ROUTES.append((self.selection, nom))
        self.selection = None

    def supprimer(self, nom, x, y):
        """Supprime le carrefour `nom` (et ses routes) ou, à défaut, la route sous (x, y).

        Args:
            nom: carrefour sous le clic, ou None.
            x, y: position du clic (pour trouver une route).
        """
        if nom:
            del NOEUDS[nom]
            ROUTES[:] = [r for r in ROUTES if nom not in r]
        elif (cle := self.vue.route_en(x, y)):
            ROUTES[:] = [r for r in ROUTES if frozenset(r) != cle]
        self.selection = None


def lire_carte(chemin):
    """Lit un fichier de carte JSON.

    Args:
        chemin: chemin du fichier .json.

    Returns:
        Le tuple (noeuds, routes, pixmap, largeur, hauteur) ; pixmap vaut None sans image.

    Raises:
        OSError, ValueError, KeyError, TypeError: fichier absent ou mal formé.
    """
    with open(chemin, encoding="utf-8") as f:
        d = json.load(f)
    pixmap = None
    if d.get("image"):                              # l'image est cherchée à côté du JSON
        pixmap = QPixmap(os.path.join(os.path.dirname(chemin), d["image"]))
        pixmap = None if pixmap.isNull() else pixmap
    return d["noeuds"], d["routes"], pixmap, d.get("largeur", 600), d.get("hauteur", 600)


def ecrire_carte(chemin, pixmap, largeur, hauteur):
    """Enregistre la carte courante en JSON (et son image de fond à côté).

    Args:
        chemin: chemin choisi (l'extension est remplacée par .json).
        pixmap: image de fond (QPixmap) ou None.
        largeur, hauteur: taille de la carte.

    Returns:
        Le nom du fichier JSON écrit (sans dossier).
    """
    base = os.path.splitext(chemin)[0]
    donnees = {"image": None, "largeur": largeur, "hauteur": hauteur,
               "noeuds": {n: list(p) for n, p in NOEUDS.items()},
               "routes": [list(r) for r in ROUTES]}
    if pixmap:                                      # l'image est copiée à côté du JSON
        pixmap.save(base + ".png")
        donnees["image"] = os.path.basename(base) + ".png"
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(donnees, f, indent=1)
    return os.path.basename(base) + ".json"
