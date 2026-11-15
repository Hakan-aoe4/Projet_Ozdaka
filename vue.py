"""Affichage de la carte (PyQt6) : routes, carrefours, feux, trajet et véhicule.

Ce module ne contient AUCUNE logique de simulation : il dessine ce qu'on lui demande et
transmet les clics de souris. Tous les éléments grossissent avec la taille de la carte
(coefficient k), pour qu'un grand plan reste lisible.
"""
import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView

from commun import BLOQUE, FEUX, NOEUDS, RAYON_BASE, ROUTES, VITESSE_BASE

GRIS = "#bdc3c7"                 # carrefour normal
COULEUR_DEPART = "#2ecc71"       # carrefour de départ (A)
COULEUR_ARRIVEE = "#e74c3c"      # carrefour d'arrivée (B)
COULEUR_SELECTION = "#f39c12"    # carrefour sélectionné en mode édition
COULEUR_FEU = {"vert": "#2ecc71", "orange": "#f39c12", "rouge": "#e74c3c"}


class Scene(QGraphicsScene):
    """Scène graphique qui transforme chaque clic de souris en signal.

    Signaux:
        clic(x, y, droit): position du clic en coordonnées de carte ; droit = clic droit ?
    """

    clic = pyqtSignal(float, float, bool)

    def mousePressEvent(self, event):
        """Réception d'un clic de souris : on le retransmet par le signal « clic ».

        Args:
            event: évènement souris (QGraphicsSceneMouseEvent).
        """
        p = event.scenePos()
        self.clic.emit(p.x(), p.y(), event.button() == Qt.MouseButton.RightButton)


class VueCarte(QGraphicsView):
    """Vue de la carte : dessine la scène et expose des fonctions simples pour la modifier.

    Attributes:
        k: échelle de la carte (1.0 pour 600 px ; plus grande si l'image est plus grande).
        rayon: rayon d'un carrefour (px de carte).
        vitesse: vitesse du véhicule sur une route fluide (px de carte par seconde).
        pixmap, largeur, hauteur: image de fond éventuelle et taille de la carte.

    Signaux:
        clic(x, y, droit): relayé depuis la scène.
    """

    clic = pyqtSignal(float, float, bool)

    def __init__(self):
        """Crée une vue vide de 600x600 avec un fond vert."""
        super().__init__()
        self.carte = Scene()
        self.carte.setBackgroundBrush(QColor("#6ab04c"))
        self.carte.clic.connect(self.clic)                 # on relaie le signal tel quel
        self.setScene(self.carte)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumSize(620, 620)
        self.pixmap = None
        self.largeur = self.hauteur = 600
        self.k, self.rayon, self.vitesse = 1.0, float(RAYON_BASE), VITESSE_BASE
        self.lignes, self.noeuds, self.points_feu = {}, {}, {}
        self.vehicule, self.traits = None, []

    # ---------- construction de la scène ----------
    def definir_fond(self, pixmap, largeur=600, hauteur=600):
        """Choisit l'image de fond et la taille de la carte (la taille de l'image prime).

        Args:
            pixmap: QPixmap du plan de fond, ou None.
            largeur, hauteur: taille de la carte si pas d'image.
        """
        self.pixmap = pixmap
        self.largeur = pixmap.width() if pixmap else largeur
        self.hauteur = pixmap.height() if pixmap else hauteur

    def construire(self, selection=None):
        """Redessine toute la scène d'après la carte courante (NOEUDS, ROUTES, FEUX).

        Args:
            selection: nom du carrefour à colorer en orange (mode édition), ou None.
        """
        self.carte.clear()                                  # supprime tous les éléments dessinés
        self.vehicule, self.traits = None, []
        self.carte.setSceneRect(0, 0, self.largeur, self.hauteur)
        self.k = max(self.largeur, self.hauteur) / 600
        self.rayon, self.vitesse = RAYON_BASE * self.k, VITESSE_BASE * self.k
        if self.pixmap:
            self.carte.addPixmap(self.pixmap).setZValue(-10)
        self.lignes = {frozenset((a, b)): self.carte.addLine(*NOEUDS[a], *NOEUDS[b])
                       for a, b in ROUTES}
        self.maj_couleurs({})
        self.dessiner_carrefours(selection)
        self.dessiner_feux()
        self.ajuster()

    def dessiner_carrefours(self, selection):
        """Dessine les cercles et les noms des carrefours.

        Args:
            selection: nom du carrefour sélectionné (orange), ou None.
        """
        police = QFont("Arial")
        police.setPixelSize(max(8, int(12 * self.k)))
        police.setBold(True)
        self.noeuds = {}
        for nom, (x, y) in NOEUDS.items():
            fond = COULEUR_SELECTION if nom == selection else GRIS
            cercle = self.carte.addEllipse(x - self.rayon, y - self.rayon, 2 * self.rayon,
                                           2 * self.rayon, QPen(QColor("black"), 2 * self.k),
                                           QBrush(QColor(fond)))
            cercle.setZValue(5)
            self.noeuds[nom] = cercle
            texte = self.carte.addText(nom, police)
            texte.setPos(x - texte.boundingRect().width() / 2,
                         y - texte.boundingRect().height() / 2)
            texte.setZValue(6)

    def dessiner_feux(self):
        """Dessine deux petits feux par carrefour à feux : à gauche = axe EO, en haut = axe NS."""
        r = self.rayon * 0.4
        pen = QPen(QColor("black"), self.k)
        self.points_feu = {}
        for nom in FEUX:
            x, y = NOEUDS[nom]
            self.points_feu[nom] = {
                "EO": self.carte.addEllipse(x - 1.7 * self.rayon - r, y - r, 2 * r, 2 * r, pen),
                "NS": self.carte.addEllipse(x - r, y - 1.7 * self.rayon - r, 2 * r, 2 * r, pen)}
            for item in self.points_feu[nom].values():
                item.setZValue(7)

    # ---------- mises à jour ----------
    def maj_couleurs(self, trafic):
        """Colore chaque route selon son trafic : vert fluide, orange dense, rouge, noir bloqué.

        Args:
            trafic: dictionnaire {frozenset((a, b)): facteur de ralentissement}.
        """
        for cle, ligne in self.lignes.items():
            f = trafic.get(cle, 1.0)
            c = "#000000" if f >= BLOQUE else "#2ecc71" if f < 1.5 else "#f39c12" if f < 3 else "#e74c3c"
            ligne.setPen(QPen(QColor(c), 14 * self.k, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))

    def afficher_feux(self, feux):
        """Colore les petits feux d'après l'état reçu du serveur (gris si inconnu).

        Args:
            feux: dictionnaire {carrefour: {"EO": couleur, "NS": couleur}}.
        """
        for nom, points in self.points_feu.items():
            for phase, item in points.items():
                etat = feux.get(nom, {}).get(phase)
                item.setBrush(QBrush(QColor(COULEUR_FEU.get(etat, "gray"))))

    def colorier_noeud(self, nom, couleur):
        """Colore un carrefour (départ, arrivée...).

        Args:
            nom: nom du carrefour.
            couleur: couleur au format "#rrggbb".
        """
        self.noeuds[nom].setBrush(QBrush(QColor(couleur)))

    def reinitialiser_noeuds(self):
        """Remet tous les carrefours en gris."""
        for cercle in self.noeuds.values():
            cercle.setBrush(QBrush(QColor(GRIS)))

    def dessiner_trajet(self, chemin):
        """Trace l'itinéraire en pointillés (efface l'ancien).

        Args:
            chemin: liste ordonnée de carrefours ; liste vide pour effacer le tracé.
        """
        for trait in self.traits:
            self.carte.removeItem(trait)
        pen = QPen(QColor("#2c3e50"), 4 * self.k, Qt.PenStyle.DashLine)
        self.traits = [self.carte.addLine(*NOEUDS[u], *NOEUDS[v], pen)
                       for u, v in zip(chemin, chemin[1:])]
        for trait in self.traits:
            trait.setZValue(3)

    # ---------- véhicule ----------
    def creer_vehicule(self, couleur):
        """Crée le rectangle représentant le véhicule (remplace l'ancien).

        Args:
            couleur: couleur de remplissage au format "#rrggbb".
        """
        self.retirer_vehicule()
        k = self.k
        self.vehicule = self.carte.addRect(-14 * k, -8 * k, 28 * k, 16 * k,
                                           QPen(QColor("#c0392b"), 3 * k), QBrush(QColor(couleur)))
        self.vehicule.setZValue(10)

    def placer_vehicule(self, x, y):
        """Place le véhicule à la position (x, y) de la carte.

        Args:
            x, y: nouvelle position du centre du véhicule.
        """
        self.vehicule.setPos(x, y)

    def retirer_vehicule(self):
        """Supprime le véhicule de la scène s'il existe."""
        if self.vehicule:
            self.carte.removeItem(self.vehicule)
            self.vehicule = None

    # ---------- recherche d'éléments sous la souris ----------
    def noeud_en(self, x, y):
        """Cherche le carrefour situé sous le point (x, y).

        Args:
            x, y: point à tester, en coordonnées de carte.

        Returns:
            Le nom du carrefour, ou None s'il n'y en a pas.
        """
        return next((n for n, (nx, ny) in NOEUDS.items()
                     if math.hypot(x - nx, y - ny) <= self.rayon + 6 * self.k), None)

    def route_en(self, x, y):
        """Cherche la route la plus proche du point (x, y).

        Args:
            x, y: point à tester, en coordonnées de carte.

        Returns:
            Un frozenset({a, b}) ou None.
        """
        def distance(route):
            """Distance du point (x, y) au segment formé par la route.

            Args:
                route: couple (a, b) de carrefours.

            Returns:
                La distance en pixels de carte (float).
            """
            (ax, ay), (bx, by) = NOEUDS[route[0]], NOEUDS[route[1]]
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / max(dx * dx + dy * dy, 1e-9)))
            return math.hypot(x - (ax + t * dx), y - (ay + t * dy))

        if not ROUTES:
            return None
        route = min(ROUTES, key=distance)
        return frozenset(route) if distance(route) < 12 * self.k else None

    # ---------- ajustement à la fenêtre ----------
    def ajuster(self):
        """Zoome pour que toute la carte soit visible dans la vue."""
        self.fitInView(self.carte.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        """La fenêtre change de taille : on réajuste le zoom.

        Args:
            event: évènement de redimensionnement (QResizeEvent).
        """
        super().resizeEvent(event)
        self.ajuster()

    def showEvent(self, event):
        """La vue devient visible : on ajuste le zoom (la taille n'est connue qu'à ce moment).

        Args:
            event: évènement d'affichage (QShowEvent).
        """
        super().showEvent(event)
        self.ajuster()
