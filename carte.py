"""Carte OzdAka : véhicule d'urgence, trafic, accidents, recalcul d'itinéraire, V2I.

Lancement :  python carte.py   (après serveur.py et carrefours.py)
"""
import math
import random
import socket
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGraphicsScene,
                             QGraphicsView, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from commun import FEUX, HOST, NOEUDS, PORT, ROUTES, dijkstra, ecrire, lire, longueur

BLOQUE = 1e6                 # facteur d'une route bloquée (accident / travaux)
RAYON = 16                   # rayon d'un carrefour (px)
VITESSE = 120.0              # px par seconde sur route fluide
GRIS = QColor("#bdc3c7")
COULEUR_FEU = {"vert": "#2ecc71", "orange": "#f39c12", "rouge": "#e74c3c"}
# type de véhicule : (sensibilité au trafic : 1 = subit tout, 0.5 = passe mieux, couleur)
VEHICULES = {"Ambulance": (0.5, "#ffffff"), "Police": (0.6, "#3498db"),
             "Pompiers": (0.5, "#e67e22")}


def route_proche(x, y):
    """Route la plus proche du point (x, y), ou None si trop loin."""
    def dist(r):
        (ax, ay), (bx, by) = NOEUDS[r[0]], NOEUDS[r[1]]
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - (ax + t * dx), y - (ay + t * dy))
    r = min(ROUTES, key=dist)
    return frozenset(r) if dist(r) < 12 else None


class ClientReseau(QThread):
    """Écoute le serveur dans un thread. Chaque message part vers l'IHM par un signal Qt :
    on ne touche jamais l'IHM depuis ce thread."""
    recu = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.sock = socket.create_connection((HOST, PORT), timeout=2)  # OSError si pas de serveur
        self.sock.settimeout(None)

    def run(self):
        try:
            for msg in lire(self.sock):
                self.recu.emit(msg)
        except (OSError, ValueError):
            pass

    def envoyer(self, msg):
        try:
            ecrire(self.sock, msg)
        except OSError:
            pass

    def arreter(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.wait(1000)


class Scene(QGraphicsScene):
    clic = pyqtSignal(float, float, bool)            # x, y, clic droit ?

    def mousePressEvent(self, event):
        p = event.scenePos()
        self.clic.emit(p.x(), p.y(), event.button() == Qt.MouseButton.RightButton)


class Fenetre(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OzdAka - Gestion du trafic d'urgence")
        self.trafic = {frozenset(r): 1.0 for r in ROUTES}   # ralentissement de chaque route
        self.feux = {}              # carrefour -> {"EO": couleur, "NS": couleur} (via serveur)
        self.a = self.b = None
        self.chemin = []            # chemin[0] = carrefour quitté, chemin[1] = prochain
        self.progress = 0.0         # distance parcourue sur la route chemin[0] -> chemin[1]
        self.prio = None            # (carrefour, axe) pour lequel on a demandé le vert
        self.coef = 0.5
        self.vehicule = None
        self.traits = []
        self.temps = self.attente = self.estime = self.direct = 0.0
        self.recalculs = 0
        self.en_attente = False

        # ----- scène : routes, carrefours, feux -----
        self.scene = Scene(0, 0, 600, 600)
        self.scene.setBackgroundBrush(QColor("#6ab04c"))
        self.scene.clic.connect(self.clic)
        self.lignes = {frozenset((a, b)): self.scene.addLine(*NOEUDS[a], *NOEUDS[b])
                       for a, b in ROUTES}
        self.noeuds, self.points_feu = {}, {}
        for nom, (x, y) in NOEUDS.items():
            cercle = self.scene.addEllipse(x - RAYON, y - RAYON, 2 * RAYON, 2 * RAYON,
                                           QPen(QColor("black"), 2), QBrush(GRIS))
            cercle.setZValue(5)
            self.noeuds[nom] = cercle
            texte = self.scene.addText(nom)
            texte.setPos(x - texte.boundingRect().width() / 2,
                         y - texte.boundingRect().height() / 2)
            texte.setZValue(6)
        for nom in FEUX:                       # petits feux : à gauche = EO, en haut = NS
            x, y = NOEUDS[nom]
            self.points_feu[nom] = {
                "EO": self.scene.addEllipse(x - 1.7 * RAYON - 6, y - 6, 12, 12),
                "NS": self.scene.addEllipse(x - 6, y - 1.7 * RAYON - 6, 12, 12)}
            for item in self.points_feu[nom].values():
                item.setZValue(7)
        self.maj_couleurs()

        # ----- fenêtre -----
        vue = QGraphicsView(self.scene)
        vue.setRenderHint(QPainter.RenderHint.Antialiasing)
        vue.setMinimumSize(620, 620)
        self.combo = QComboBox()
        self.combo.addItems(list(VEHICULES))
        btn_lancer = QPushButton("Lancer la mission")
        btn_lancer.clicked.connect(self.lancer)
        btn_reset = QPushButton("Réinitialiser")
        btn_reset.clicked.connect(self.reinitialiser)
        self.chk_v2i = QCheckBox("Priorité V2I")
        self.chk_v2i.setChecked(True)
        self.chk_trafic = QCheckBox("Trafic aléatoire")
        self.chk_trafic.toggled.connect(self.basculer_trafic)
        self.lbl_msg = QLabel()
        self.lbl_stats = QLabel("—")
        for lbl in (self.lbl_msg, self.lbl_stats):
            lbl.setWordWrap(True)
        self.journal = QPlainTextEdit(readOnly=True)

        droite = QVBoxLayout()
        for w in (QLabel("Véhicule d'urgence"), self.combo, btn_lancer, btn_reset,
                  self.chk_v2i, self.chk_trafic, self.lbl_msg, self.lbl_stats):
            droite.addWidget(w)
        droite.addWidget(QLabel("Journal"))
        droite.addWidget(self.journal, 1)
        panneau = QWidget()
        panneau.setFixedWidth(340)
        panneau.setLayout(droite)
        principal = QHBoxLayout(self)
        principal.addWidget(vue, 1)
        principal.addWidget(panneau)

        self.timer_v = QTimer()
        self.timer_v.timeout.connect(self.tick)
        self.timer_t = QTimer()
        self.timer_t.timeout.connect(self.trafic_aleatoire)

        # ----- réseau : sans serveur, l'appli marche quand même (pas de feux) -----
        try:
            self.reseau = ClientReseau()
            self.reseau.recu.connect(self.recevoir)
            self.reseau.start()
            self.log("Connecté au serveur")
        except OSError:
            self.reseau = None
            self.log("Serveur injoignable : lance serveur.py puis carrefours.py (sans feux ici)")
        self.message("Clique sur le point de départ (A).")

    # ---------- affichage ----------
    def message(self, texte):
        self.lbl_msg.setText(texte)

    def log(self, texte):
        self.journal.appendPlainText(f"[{datetime.now():%H:%M:%S}] {texte}")

    def maj_couleurs(self):
        for k, ligne in self.lignes.items():
            f = self.trafic[k]
            c = "#000000" if f >= BLOQUE else "#2ecc71" if f < 1.5 else "#f39c12" if f < 3 else "#e74c3c"
            ligne.setPen(QPen(QColor(c), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

    def dessiner_trajet(self, chemin):
        for trait in self.traits:
            self.scene.removeItem(trait)
        pen = QPen(QColor("#2c3e50"), 4, Qt.PenStyle.DashLine)
        self.traits = [self.scene.addLine(*NOEUDS[u], *NOEUDS[v], pen)
                       for u, v in zip(chemin, chemin[1:])]
        for trait in self.traits:
            trait.setZValue(3)

    def texte_stats(self):
        direct = "bloqué" if self.direct == math.inf else f"{self.direct:.1f} s"
        return (f"Temps : {self.temps:.1f} s (dont {self.attente:.1f} s aux feux)\n"
                f"Estimé au départ : {self.estime:.1f} s | trajet direct : {direct}\n"
                f"Recalculs d'itinéraire : {self.recalculs}")

    # ---------- réseau (slot : exécuté dans le thread IHM) ----------
    def recevoir(self, msg):
        if msg.get("type") != "FEUX":
            return
        self.feux = msg["etats"]
        for nom, points in self.points_feu.items():
            for phase, item in points.items():
                etat = self.feux.get(nom, {}).get(phase)
                item.setBrush(QBrush(QColor(COULEUR_FEU.get(etat, "gray"))))

    def envoyer(self, msg):
        if self.reseau:
            self.reseau.envoyer(msg)

    def demander(self, voulue):
        """V2I : demande le vert au carrefour voulu = (carrefour, axe), ou libère l'ancien."""
        if voulue == self.prio:
            return
        if self.prio:
            self.envoyer({"type": "FIN_VERT", "carrefour": self.prio[0]})
        if voulue:
            self.envoyer({"type": "DEMANDE_VERT", "carrefour": voulue[0], "phase": voulue[1]})
            self.log(f"V2I : demande de vert au carrefour {voulue[0]}")
        self.prio = voulue

    # ---------- itinéraire ----------
    def facteur(self, f):
        """Ralentissement réellement subi par ce type de véhicule."""
        return f if f >= BLOQUE else 1 + (f - 1) * self.coef

    def itineraire(self, dep, arr):
        chemin, cout = dijkstra({k: self.facteur(f) for k, f in self.trafic.items()}, dep, arr)
        return (chemin, cout) if cout < 1e5 else ([], math.inf)

    def temps_direct(self):
        """Temps du trajet le plus court en distance (qui ignore le trafic)."""
        chemin, _ = dijkstra({}, self.a, self.b)
        total = 0.0
        for u, v in zip(chemin, chemin[1:]):
            f = self.facteur(self.trafic[frozenset((u, v))])
            if f >= BLOQUE:
                return math.inf
            total += longueur(u, v) * f
        return total / VITESSE

    def replanifier(self):
        """Un événement change le trafic : on recalcule la suite du trajet."""
        if len(self.chemin) < 2 or self.chemin[1] == self.b:
            return
        suite, _ = self.itineraire(self.chemin[1], self.b)
        if suite:
            if suite != self.chemin[1:]:
                self.recalculs += 1
                self.log("Itinéraire recalculé : " + " → ".join(suite))
            self.chemin = [self.chemin[0]] + suite
            self.dessiner_trajet(self.chemin)

    # ---------- interactions ----------
    def clic(self, x, y, droit):
        if droit:
            return self.basculer_blocage(x, y)
        nom = next((n for n, (nx, ny) in NOEUDS.items()
                    if math.hypot(x - nx, y - ny) <= RAYON + 6), None)
        if nom is None:
            return
        if self.a is None or self.b is not None:
            self.reinitialiser()
            self.a = nom
            self.noeuds[nom].setBrush(QBrush(QColor("#2ecc71")))
            self.message(f"Départ : {nom}. Clique sur l'arrivée.")
        elif nom != self.a:
            self.b = nom
            self.noeuds[nom].setBrush(QBrush(QColor("#e74c3c")))
            chemin, cout = self.itineraire(self.a, self.b)
            self.dessiner_trajet(chemin)
            self.message(f"Trajet estimé : {cout / VITESSE:.1f} s. Lance la mission."
                         if chemin else "Aucun trajet possible.")

    def basculer_blocage(self, x, y):
        """Clic droit sur une route : accident / travaux (bloque ou rouvre)."""
        k = route_proche(x, y)
        if k is None:
            return
        if len(self.chemin) >= 2 and k == frozenset(self.chemin[:2]):
            return self.message("Impossible : le véhicule est sur cette route.")
        bloquer = self.trafic[k] < BLOQUE
        self.trafic[k] = BLOQUE if bloquer else 1.0
        self.log(f"Route {'-'.join(sorted(k))} {'bloquée (accident)' if bloquer else 'rouverte'}")
        self.maj_couleurs()
        self.replanifier()

    def basculer_trafic(self, actif):
        if actif:
            self.trafic_aleatoire()
            self.timer_t.start(4000)
        else:
            self.timer_t.stop()

    def trafic_aleatoire(self):
        for k, f in self.trafic.items():
            if f < BLOQUE:                                  # une route bloquée le reste
                r = random.random()
                self.trafic[k] = 1.0 if r < 0.55 else 2.0 if r < 0.85 else 4.0
        self.maj_couleurs()
        self.log("Trafic mis à jour")
        self.replanifier()

    # ---------- mission ----------
    def reinitialiser(self):
        self.arreter()
        if self.vehicule:
            self.scene.removeItem(self.vehicule)
            self.vehicule = None
        self.dessiner_trajet([])
        for cercle in self.noeuds.values():
            cercle.setBrush(QBrush(GRIS))
        self.a = self.b = None
        self.message("Clique sur le point de départ (A).")

    def arreter(self):
        self.timer_v.stop()
        self.chemin = []
        self.demander(None)

    def lancer(self):
        if self.b is None:
            return self.message("Choisis d'abord le départ et l'arrivée sur la carte.")
        nom = self.combo.currentText()
        self.coef, couleur = VEHICULES[nom]
        chemin, cout = self.itineraire(self.a, self.b)
        if not chemin:
            return self.message("Aucun trajet possible.")
        self.arreter()
        self.chemin, self.progress = chemin, 0.0
        self.temps = self.attente = 0.0
        self.recalculs = 0
        self.en_attente = False
        self.estime, self.direct = cout / VITESSE, self.temps_direct()
        self.dessiner_trajet(chemin)
        if self.vehicule:
            self.scene.removeItem(self.vehicule)
        self.vehicule = self.scene.addRect(-14, -8, 28, 16, QPen(QColor("#c0392b"), 3),
                                           QBrush(QColor(couleur)))
        self.vehicule.setZValue(10)
        self.vehicule.setPos(*NOEUDS[self.a])
        self.timer_v.start(30)
        self.message(f"{nom} en route...")
        self.log(f"{nom} part de {self.a} vers {self.b}")

    def tick(self):
        dt = 0.03
        u, v = self.chemin[:2]
        f = self.facteur(self.trafic[frozenset((u, v))])
        L = longueur(u, v)
        phase = "EO" if abs(NOEUDS[v][0] - NOEUDS[u][0]) >= abs(NOEUDS[v][1] - NOEUDS[u][1]) else "NS"
        a_un_feu = v in FEUX and v != self.b
        self.temps += dt

        # V2I : à l'approche du carrefour, le véhicule demande le vert
        proche = a_un_feu and L - self.progress < RAYON * 8
        self.demander((v, phase) if self.chk_v2i.isChecked() and proche else None)

        nouveau = self.progress + VITESSE / f * dt
        seuil = L - min(RAYON * 1.6, L * 0.4)                  # ligne d'arrêt
        feu = self.feux.get(v, {}).get(phase, "vert")          # sans serveur : pas de feu
        if a_un_feu and self.progress <= seuil < nouveau and feu != "vert":
            self.progress = seuil                              # arrêt au feu
            self.attente += dt
            if not self.en_attente:
                self.en_attente = True
                self.log(f"Arrêt au feu {feu}, carrefour {v}")
        else:
            if self.en_attente:
                self.en_attente = False
                self.log(f"Feu vert au carrefour {v}, le véhicule repart")
            self.progress = nouveau

        if self.progress >= L:
            self.vehicule.setPos(*NOEUDS[v])
            if v == self.b:
                self.lbl_stats.setText(self.texte_stats())
                self.arreter()
                self.message(f"Arrivé en {self.temps:.1f} s.")
                self.log(f"Arrivée en {self.temps:.1f} s")
                return
            self.log(f"Passage au carrefour {v}")
            self.progress = 0.0                                # à chaque carrefour on recalcule
            chemin, _ = self.itineraire(v, self.b)
            if not chemin:
                self.arreter()
                self.message("Bloqué : plus aucun trajet possible.")
                self.log("Bloqué : plus aucun trajet possible")
                return
            self.chemin = chemin
            self.dessiner_trajet(chemin)
        else:
            (x1, y1), (x2, y2) = NOEUDS[u], NOEUDS[v]
            t = self.progress / L
            self.vehicule.setPos(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        self.lbl_stats.setText(self.texte_stats())

    def closeEvent(self, event):
        if self.reseau:
            self.reseau.arreter()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    fenetre = Fenetre()
    fenetre.show()
    sys.exit(app.exec())
