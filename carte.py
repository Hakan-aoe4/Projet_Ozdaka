"""OzdAka : carte, simulation du véhicule d'urgence, éditeur de cartes, V2I.

Lancement :  python carte.py
Le serveur et les carrefours sont démarrés automatiquement s'ils ne tournent pas déjà.
"""
import json
import math
import os
import random
import socket
import sys
from datetime import datetime

from PyQt6.QtCore import QProcess, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QGraphicsScene,
                             QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from commun import (FEUX, HOST, NOEUDS, PORT, ROUTES, definir_carte, dijkstra, ecrire,
                    grille, longueur, lire, maj_feux)

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DOSSIER_CARTES = os.path.join(DOSSIER, "cartes")
BLOQUE = 1e6                 # facteur d'une route bloquée (accident / travaux)
GRIS = QColor("#bdc3c7")
COULEUR_FEU = {"vert": "#2ecc71", "orange": "#f39c12", "rouge": "#e74c3c"}
# type de véhicule : (sensibilité au trafic : 1 = subit tout, 0.5 = passe mieux, couleur)
VEHICULES = {"Ambulance": (0.5, "#ffffff"), "Police": (0.6, "#3498db"),
             "Pompiers": (0.5, "#e67e22")}
AIDE_SIMULATION = ("Clic gauche : départ (A) puis arrivée (B)\n"
                   "Clic droit sur une route : accident / travaux")
AIDE_EDITION = ("Clic sur le vide : nouveau carrefour\n"
                "Clic sur 2 carrefours : route entre eux\n"
                "Clic droit : supprimer un carrefour ou une route")


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
        self.reseau = None
        self.processus = []         # serveur / carrefours démarrés par cette fenêtre
        self.id_carte = 0
        self.feux = {}              # carrefour -> {"EO": couleur, "NS": couleur} (via serveur)
        self.pixmap = None          # image de fond de la carte (capture d'écran)
        self.largeur = self.hauteur = 600
        self.k = 1.0                # échelle : carte plus grande -> éléments plus grands
        self.edition = False
        self.selection = None       # carrefour choisi comme début d'une route (édition)
        self.a = self.b = None
        self.chemin = []            # chemin[0] = carrefour quitté, chemin[1] = prochain
        self.progress = 0.0         # distance parcourue sur la route chemin[0] -> chemin[1]
        self.prio = None            # (carrefour, axe) pour lequel on a demandé le vert
        self.coef = 0.5
        self.vehicule = None
        self.traits = []
        self.trafic = {}
        self.temps = self.attente = self.estime = self.direct = 0.0
        self.recalculs = 0
        self.en_attente = False

        # ----- fenêtre : la carte à gauche, le panneau à droite -----
        self.scene = Scene()
        self.scene.setBackgroundBrush(QColor("#6ab04c"))
        self.scene.clic.connect(self.clic)
        self.vue = QGraphicsView(self.scene)
        self.vue.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.vue.setMinimumSize(620, 620)

        self.lbl_reseau = QLabel("Réseau : …")
        self.lbl_aide = QLabel(AIDE_SIMULATION)
        self.lbl_msg = QLabel()
        self.lbl_stats = QLabel("—")
        for lbl in (self.lbl_aide, self.lbl_msg, self.lbl_stats):
            lbl.setWordWrap(True)
        self.lbl_aide.setMinimumHeight(60)
        self.lbl_msg.setMinimumHeight(35)
        self.lbl_stats.setMinimumHeight(50)
        self.journal = QPlainTextEdit(readOnly=True)

        # section Carte
        self.spin = QSpinBox()
        self.spin.setRange(2, 6)
        self.spin.setValue(3)
        self.spin.setPrefix("Taille ")
        self.chk_edition = QCheckBox("Mode édition de la carte")
        self.chk_edition.toggled.connect(self.basculer_edition)
        boite_carte = self.groupe("Carte", [
            self.ligne(self.bouton("Nouvelle grille", self.nouvelle_grille), self.spin),
            self.bouton("Importer une capture d'écran…", self.importer_image),
            self.ligne(self.bouton("Charger…", self.charger), self.bouton("Enregistrer…", self.enregistrer)),
            self.chk_edition])

        # section Mission
        self.combo = QComboBox()
        self.combo.addItems(list(VEHICULES))
        boite_mission = self.groupe("Mission", [
            self.combo,
            self.ligne(self.bouton("Lancer la mission", self.lancer),
                       self.bouton("Réinitialiser", self.reinitialiser))])

        # section Simulation
        self.chk_v2i = QCheckBox("Priorité V2I")
        self.chk_v2i.setChecked(True)
        self.chk_trafic = QCheckBox("Trafic aléatoire")
        self.chk_trafic.toggled.connect(self.basculer_trafic)
        boite_sim = self.groupe("Simulation", [self.chk_v2i, self.chk_trafic])

        droite = QVBoxLayout()
        for w in (self.lbl_reseau, boite_carte, boite_mission, boite_sim, self.lbl_aide,
                  self.lbl_msg, self.lbl_stats):
            droite.addWidget(w)
        droite.addWidget(self.journal, 1)
        panneau = QWidget()
        panneau.setFixedWidth(350)
        panneau.setLayout(droite)
        principal = QHBoxLayout(self)
        principal.addWidget(self.vue, 1)
        principal.addWidget(panneau)

        self.resize(1150, 880)
        self.timer_v = QTimer()
        self.timer_v.timeout.connect(self.tick)
        self.timer_t = QTimer()
        self.timer_t.timeout.connect(self.trafic_aleatoire)

        self.appliquer_carte(*grille(3))
        self.message("Clique sur le point de départ (A).")
        if not self.connecter():
            self.demarrer_reseau()

    # ---------- petits outils d'interface ----------
    def bouton(self, texte, action):
        b = QPushButton(texte)
        b.clicked.connect(lambda: action())
        return b

    def ligne(self, *widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x)
        return w

    def groupe(self, titre, widgets):
        boite = QGroupBox(titre)
        v = QVBoxLayout(boite)
        for w in widgets:
            v.addWidget(w)
        return boite

    def message(self, texte):
        self.lbl_msg.setText(texte)

    def log(self, texte):
        self.journal.appendPlainText(f"[{datetime.now():%H:%M:%S}] {texte}")

    # ---------- réseau ----------
    def connecter(self):
        try:
            self.reseau = ClientReseau()
        except OSError:
            self.reseau = None
            self.lbl_reseau.setText("Réseau : non connecté (pas de feux)")
            return False
        self.reseau.recu.connect(self.recevoir)
        self.reseau.finished.connect(self.reseau_perdu)
        self.reseau.start()
        self.lbl_reseau.setText("Réseau : connecté")
        self.log("Connecté au serveur")
        self.envoyer_carte()
        return True

    def lancer_script(self, script):
        p = QProcess(self)
        p.setProgram(sys.executable)
        p.setArguments([os.path.join(DOSSIER, script)])
        p.setWorkingDirectory(DOSSIER)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        p.start()
        self.processus.append(p)

    def demarrer_reseau(self):
        """Pas de serveur : on démarre le serveur puis les carrefours, et on se connecte."""
        self.log("Serveur absent : démarrage du serveur et des carrefours")
        self.lbl_reseau.setText("Réseau : démarrage…")
        self.lancer_script("serveur.py")
        self.essais = 0
        QTimer.singleShot(600, self.finir_demarrage)

    def finir_demarrage(self):
        if self.connecter():
            self.lancer_script("carrefours.py")
        elif self.essais < 10:
            self.essais += 1
            QTimer.singleShot(300, self.finir_demarrage)
        else:
            self.log("Impossible de joindre le serveur")

    def reseau_perdu(self):
        if self.reseau is not None:                       # sinon : fermeture normale
            self.reseau = None
            self.feux = {}
            self.afficher_feux()
            self.lbl_reseau.setText("Réseau : déconnecté (pas de feux)")
            self.log("Connexion au serveur perdue")

    def envoyer(self, msg):
        if self.reseau:
            self.reseau.envoyer(msg)

    def envoyer_carte(self):
        self.envoyer({"type": "CARTE", "id": self.id_carte, "noeuds": NOEUDS, "routes": ROUTES})

    def recevoir(self, msg):
        """Slot : exécuté dans le thread IHM (le signal Qt vient du thread réseau)."""
        if msg.get("type") != "FEUX":
            return
        if msg.get("carte") != self.id_carte:             # les carrefours n'ont pas la bonne carte
            self.envoyer_carte()
            return
        self.feux = msg["etats"]
        self.afficher_feux()

    def afficher_feux(self):
        for nom, points in self.points_feu.items():
            for phase, item in points.items():
                etat = self.feux.get(nom, {}).get(phase)
                item.setBrush(QBrush(QColor(COULEUR_FEU.get(etat, "gray"))))

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

    # ---------- carte : dessin ----------
    def appliquer_carte(self, noeuds, routes, pixmap=None, largeur=600, hauteur=600):
        """Change de carte : met à jour la carte partagée, la scène, et prévient les carrefours."""
        self.arreter()
        definir_carte(noeuds, routes)
        self.pixmap = pixmap
        self.largeur = pixmap.width() if pixmap else largeur
        self.hauteur = pixmap.height() if pixmap else hauteur
        self.id_carte = random.getrandbits(32)
        self.feux = {}
        self.selection = None
        self.a = self.b = None
        self.construire_scene()
        self.envoyer_carte()
        self.log(f"Carte : {len(NOEUDS)} carrefours, {len(ROUTES)} routes")

    def construire_scene(self):
        self.scene.clear()                                # supprime tous les éléments dessinés
        self.vehicule, self.traits = None, []
        self.scene.setSceneRect(0, 0, self.largeur, self.hauteur)
        self.k = max(self.largeur, self.hauteur) / 600
        self.rayon, self.vitesse = 16 * self.k, 120.0 * self.k
        self.trafic = {frozenset(r): 1.0 for r in ROUTES}
        if self.pixmap:
            self.scene.addPixmap(self.pixmap).setZValue(-10)
        self.lignes = {frozenset((a, b)): self.scene.addLine(*NOEUDS[a], *NOEUDS[b])
                       for a, b in ROUTES}
        self.maj_couleurs()
        police = QFont("Arial")
        police.setPixelSize(max(8, int(12 * self.k)))
        police.setBold(True)
        self.noeuds, self.points_feu = {}, {}
        for nom, (x, y) in NOEUDS.items():
            fond = QColor("#f39c12") if nom == self.selection else GRIS
            cercle = self.scene.addEllipse(x - self.rayon, y - self.rayon, 2 * self.rayon,
                                           2 * self.rayon, QPen(QColor("black"), 2 * self.k),
                                           QBrush(fond))
            cercle.setZValue(5)
            self.noeuds[nom] = cercle
            texte = self.scene.addText(nom, police)
            texte.setPos(x - texte.boundingRect().width() / 2,
                         y - texte.boundingRect().height() / 2)
            texte.setZValue(6)
        r = self.rayon * 0.4
        pen = QPen(QColor("black"), self.k)
        for nom in FEUX:                       # petits feux : à gauche = EO, en haut = NS
            x, y = NOEUDS[nom]
            self.points_feu[nom] = {
                "EO": self.scene.addEllipse(x - 1.7 * self.rayon - r, y - r, 2 * r, 2 * r, pen),
                "NS": self.scene.addEllipse(x - r, y - 1.7 * self.rayon - r, 2 * r, 2 * r, pen)}
            for item in self.points_feu[nom].values():
                item.setZValue(7)
        self.afficher_feux()
        self.ajuster_vue()

    def maj_couleurs(self):
        for k, ligne in self.lignes.items():
            f = self.trafic[k]
            c = "#000000" if f >= BLOQUE else "#2ecc71" if f < 1.5 else "#f39c12" if f < 3 else "#e74c3c"
            ligne.setPen(QPen(QColor(c), 14 * self.k, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))

    def dessiner_trajet(self, chemin):
        for trait in self.traits:
            self.scene.removeItem(trait)
        pen = QPen(QColor("#2c3e50"), 4 * self.k, Qt.PenStyle.DashLine)
        self.traits = [self.scene.addLine(*NOEUDS[u], *NOEUDS[v], pen)
                       for u, v in zip(chemin, chemin[1:])]
        for trait in self.traits:
            trait.setZValue(3)

    def ajuster_vue(self):
        self.vue.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ajuster_vue()

    def showEvent(self, event):
        super().showEvent(event)
        self.ajuster_vue()

    def texte_stats(self):
        direct = "bloqué" if self.direct == math.inf else f"{self.direct:.1f} s"
        return (f"Temps : {self.temps:.1f} s (dont {self.attente:.1f} s aux feux)\n"
                f"Estimé au départ : {self.estime:.1f} s | trajet direct : {direct}\n"
                f"Recalculs d'itinéraire : {self.recalculs}")

    # ---------- carte : fichiers ----------
    def nouvelle_grille(self):
        self.chk_edition.setChecked(False)
        self.appliquer_carte(*grille(self.spin.value()))
        self.message("Clique sur le point de départ (A).")

    def importer_image(self):
        """Une capture d'écran devient le fond d'une carte vide : on la dessine en mode édition."""
        chemin, _ = QFileDialog.getOpenFileName(self, "Importer une capture d'écran", "",
                                                "Images (*.png *.jpg *.jpeg *.bmp)")
        if not chemin:
            return
        pix = QPixmap(chemin)
        if pix.isNull():
            return self.message("Image illisible.")
        self.chk_edition.setChecked(False)
        self.appliquer_carte({}, [], pix)
        self.chk_edition.setChecked(True)

    def charger(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Charger une carte", DOSSIER_CARTES,
                                                "Cartes (*.json)")
        if chemin:
            self.charger_fichier(chemin)

    def charger_fichier(self, chemin):
        try:
            with open(chemin, encoding="utf-8") as f:
                d = json.load(f)
            pix = None
            if d.get("image"):
                pix = QPixmap(os.path.join(os.path.dirname(chemin), d["image"]))
                pix = None if pix.isNull() else pix
            self.chk_edition.setChecked(False)
            self.appliquer_carte(d["noeuds"], d["routes"], pix,
                                 d.get("largeur", 600), d.get("hauteur", 600))
        except (OSError, ValueError, KeyError, TypeError) as e:
            return self.message(f"Carte illisible : {e}")
        self.message(f"Carte chargée : {os.path.basename(chemin)}. Clique sur le départ (A).")

    def enregistrer(self):
        if not NOEUDS:
            return self.message("La carte est vide : rien à enregistrer.")
        os.makedirs(DOSSIER_CARTES, exist_ok=True)
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la carte", os.path.join(DOSSIER_CARTES, "ma_carte.json"),
            "Cartes (*.json)")
        if not chemin:
            return
        base = os.path.splitext(chemin)[0]
        donnees = {"image": None, "largeur": self.largeur, "hauteur": self.hauteur,
                   "noeuds": {n: list(p) for n, p in NOEUDS.items()},
                   "routes": [list(r) for r in ROUTES]}
        if self.pixmap:                                   # l'image est copiée à côté du JSON
            self.pixmap.save(base + ".png")
            donnees["image"] = os.path.basename(base) + ".png"
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(donnees, f, indent=1)
        self.message(f"Carte enregistrée : {os.path.basename(base)}.json")

    # ---------- édition ----------
    def basculer_edition(self, actif):
        self.edition = actif
        self.arreter()
        self.selection = None
        self.lbl_aide.setText(AIDE_EDITION if actif else AIDE_SIMULATION)
        if actif:
            self.reinitialiser()
            self.message("Mode édition : dessine les carrefours et les routes.")
        else:                                             # on prévient les carrefours
            self.id_carte = random.getrandbits(32)
            self.feux = {}
            self.construire_scene()
            self.envoyer_carte()
            self.message("Clique sur le point de départ (A).")

    def noeud_en(self, x, y):
        return next((n for n, (nx, ny) in NOEUDS.items()
                     if math.hypot(x - nx, y - ny) <= self.rayon + 6 * self.k), None)

    def route_en(self, x, y):
        """Route la plus proche du point (x, y), ou None si trop loin."""
        def dist(r):
            (ax, ay), (bx, by) = NOEUDS[r[0]], NOEUDS[r[1]]
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            return math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if not ROUTES:
            return None
        r = min(ROUTES, key=dist)
        return frozenset(r) if dist(r) < 12 * self.k else None

    def clic_edition(self, x, y, droit):
        nom = self.noeud_en(x, y)
        if droit:
            if nom:                                       # supprime le carrefour et ses routes
                del NOEUDS[nom]
                ROUTES[:] = [r for r in ROUTES if nom not in r]
            elif (k := self.route_en(x, y)):
                ROUTES[:] = [r for r in ROUTES if frozenset(r) != k]
            self.selection = None
        elif nom is None:                                 # clic sur le vide : nouveau carrefour
            i = 1
            while f"C{i}" in NOEUDS:
                i += 1
            NOEUDS[f"C{i}"] = (round(x), round(y))
            self.selection = None
        elif self.selection is None:
            self.selection = nom
        else:
            if nom != self.selection and frozenset((nom, self.selection)) not in map(frozenset, ROUTES):
                ROUTES.append((self.selection, nom))
            self.selection = None
        maj_feux()
        self.construire_scene()

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
        return total / self.vitesse

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
        if self.edition:
            return self.clic_edition(x, y, droit)
        if droit:
            return self.basculer_blocage(x, y)
        nom = self.noeud_en(x, y)
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
            self.message(f"Trajet estimé : {cout / self.vitesse:.1f} s. Lance la mission."
                         if chemin else "Aucun trajet possible.")

    def basculer_blocage(self, x, y):
        """Clic droit sur une route : accident / travaux (bloque ou rouvre)."""
        k = self.route_en(x, y)
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
        if not self.edition:
            self.message("Clique sur le point de départ (A).")

    def arreter(self):
        self.timer_v.stop()
        self.chemin = []
        self.demander(None)

    def lancer(self):
        if self.edition:
            return self.message("Décoche le mode édition pour lancer une mission.")
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
        self.estime, self.direct = cout / self.vitesse, self.temps_direct()
        self.dessiner_trajet(chemin)
        if self.vehicule:
            self.scene.removeItem(self.vehicule)
        k = self.k
        self.vehicule = self.scene.addRect(-14 * k, -8 * k, 28 * k, 16 * k,
                                           QPen(QColor("#c0392b"), 3 * k), QBrush(QColor(couleur)))
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
        proche = a_un_feu and L - self.progress < self.rayon * 8
        self.demander((v, phase) if self.chk_v2i.isChecked() and proche else None)

        nouveau = self.progress + self.vitesse / f * dt
        seuil = L - min(self.rayon * 1.6, L * 0.4)             # ligne d'arrêt
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
        reseau, self.reseau = self.reseau, None
        if reseau:
            reseau.arreter()
        for p in self.processus:                              # on arrête ce qu'on a démarré
            p.kill()
            p.waitForFinished(500)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    fenetre = Fenetre()
    fenetre.show()
    sys.exit(app.exec())
