"""OzdAka : fenêtre principale (programme à lancer).

Lancement :  python carte.py
Le serveur et les carrefours sont démarrés automatiquement s'ils ne tournent pas déjà.

Organisation du code :
    commun.py     carte partagée, Dijkstra, messages JSON
    reseau.py     liaison réseau de l'IHM (client TCP, V2I)
    vue.py        affichage de la carte
    simulation.py mission du véhicule d'urgence
    editeur.py    édition de la carte et fichiers de cartes
    historique.py historique des missions (base SQLite historique.db, utilisée par le serveur)
    carte.py      cette fenêtre : panneau de commande et assemblage des modules
"""
import os
import sys
from datetime import datetime

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                             QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from commun import NOEUDS, ROUTES, definir_carte, grille
from editeur import Editeur, ecrire_carte, lire_carte
from reseau import DOSSIER, Liaison
from simulation import VEHICULES, Simulation
from vue import VueCarte

DOSSIER_CARTES = os.path.join(DOSSIER, "cartes")
AIDE_SIMULATION = ("Clic gauche : départ (A) puis arrivée (B)\n"
                   "Clic droit sur une route : accident / travaux")
AIDE_EDITION = ("Clic sur le vide : nouveau carrefour\n"
                "Clic sur 2 carrefours : route entre eux\n"
                "Clic droit : supprimer un carrefour ou une route")
CONSIGNE_DEPART = "Clique sur le point de départ (A)."


# ---------- petits outils d'interface ----------
def bouton(texte, action):
    """Crée un bouton qui appelle `action` quand on clique dessus.

    Args:
        texte: texte affiché sur le bouton.
        action: fonction sans argument appelée au clic.

    Returns:
        Le QPushButton créé.
    """
    b = QPushButton(texte)
    b.clicked.connect(lambda: action())
    return b


def ligne(*widgets):
    """Place plusieurs widgets côte à côte dans un conteneur horizontal.

    Args:
        *widgets: widgets à aligner, de gauche à droite.

    Returns:
        Le QWidget conteneur.
    """
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    return w


def groupe(titre, widgets):
    """Crée un cadre titré qui empile verticalement les widgets donnés.

    Args:
        titre: titre du cadre.
        widgets: liste des widgets à empiler.

    Returns:
        Le QGroupBox créé.
    """
    boite = QGroupBox(titre)
    v = QVBoxLayout(boite)
    for w in widgets:
        v.addWidget(w)
    return boite


class Fenetre(QWidget):
    """Fenêtre principale : la carte à gauche, le panneau de commande à droite.

    Elle assemble les modules (vue, liaison réseau, simulation, éditeur) et ne contient
    que l'interface : boutons, fichiers de cartes et passage en mode édition.
    """

    def __init__(self):
        """Construit l'interface, relie les modules, charge la grille 3x3 et se connecte au réseau."""
        super().__init__()
        self.setWindowTitle("OzdAka - Gestion du trafic d'urgence")
        self.edition = False
        self.vue = VueCarte()
        self.liaison = Liaison()
        self.sim = Simulation(self.vue, self.liaison)
        self.editeur = Editeur(self.vue)
        self.construire_interface()
        self.relier_signaux()
        self.resize(1150, 880)
        self.appliquer_carte(*grille(3))
        self.message(CONSIGNE_DEPART)
        self.liaison.demarrer()

    # ---------- interface ----------
    def construire_interface(self):
        """Crée tous les widgets : panneau Carte / Mission / Simulation, textes et journal."""
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

        self.chk_edition = QCheckBox("Mode édition de la carte")
        boite_carte = groupe("Carte", [
            bouton("Importer un plan (capture d'écran)…", self.importer_plan),
            ligne(bouton("Charger…", self.charger), bouton("Enregistrer…", self.enregistrer)),
            self.chk_edition])

        self.combo = QComboBox()
        self.combo.addItems(list(VEHICULES))
        boite_mission = groupe("Mission", [
            self.combo,
            ligne(bouton("Lancer la mission", self.lancer),
                  bouton("Réinitialiser", self.reinitialiser)),
            bouton("Historique des missions…", self.afficher_historique)])

        self.chk_v2i = QCheckBox("Priorité V2I")
        self.chk_v2i.setChecked(True)
        self.chk_trafic = QCheckBox("Trafic aléatoire")
        boite_sim = groupe("Simulation", [self.chk_v2i, self.chk_trafic])

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

    def relier_signaux(self):
        """Connecte les signaux des modules et des cases à cocher aux bonnes actions."""
        self.vue.clic.connect(self.clic_carte)
        self.chk_edition.toggled.connect(self.basculer_edition)
        self.chk_v2i.toggled.connect(self.sim.activer_v2i)
        self.chk_trafic.toggled.connect(self.sim.activer_trafic)
        self.sim.message.connect(self.message)
        self.sim.journal.connect(self.log)
        self.sim.stats.connect(self.lbl_stats.setText)
        self.sim.terminee.connect(self.enregistrer_mission)
        self.liaison.statut.connect(self.lbl_reseau.setText)
        self.liaison.journal.connect(self.log)
        self.liaison.feux_changes.connect(lambda: self.vue.afficher_feux(self.liaison.feux))
        self.liaison.historique_recu.connect(self.montrer_historique)

    def message(self, texte):
        """Affiche une consigne ou un résultat sous le panneau de commande.

        Args:
            texte: message à afficher.
        """
        self.lbl_msg.setText(texte)

    def log(self, texte):
        """Ajoute une ligne horodatée au journal.

        Args:
            texte: message à enregistrer.
        """
        self.journal.appendPlainText(f"[{datetime.now():%H:%M:%S}] {texte}")

    # ---------- carte ----------
    def reconstruire(self):
        """Redessine la carte courante et remet la simulation à zéro."""
        self.vue.construire(self.editeur.selection)
        self.vue.afficher_feux(self.liaison.feux)
        self.sim.nouvelle_carte()

    def appliquer_carte(self, noeuds, routes, pixmap=None, largeur=600, hauteur=600):
        """Change de carte : met à jour la carte partagée, l'affichage, et prévient les carrefours.

        Args:
            noeuds: dictionnaire {nom: (x, y)}.
            routes: liste de couples de noms de carrefours.
            pixmap: image de fond (QPixmap) ou None.
            largeur, hauteur: taille de la carte si pas d'image.
        """
        self.sim.arreter()
        definir_carte(noeuds, routes)
        self.vue.definir_fond(pixmap, largeur, hauteur)
        self.editeur.selection = None
        self.liaison.nouvelle_carte()
        self.reconstruire()
        self.log(f"Carte : {len(NOEUDS)} carrefours, {len(ROUTES)} routes")

    def importer_plan(self):
        """Bouton « Importer un plan » : une capture d'écran (Google Maps, OpenStreetMap...)
        devient le fond d'une carte vide, et le mode édition s'active pour placer les
        carrefours et les routes. Il suffit ensuite de cliquer sur « Enregistrer » pour
        obtenir le fichier .json (et sa copie de l'image), rechargeable avec « Charger ».
        """
        chemin, _ = QFileDialog.getOpenFileName(self, "Importer un plan", DOSSIER,
                                                "Images (*.png *.jpg *.jpeg *.bmp)")
        if not chemin:
            return
        pixmap = QPixmap(chemin)
        if pixmap.isNull():
            self.message("Image illisible.")
            return
        self.chk_edition.setChecked(False)
        self.appliquer_carte({}, [], pixmap)                 # carte vide sur le plan
        self.chk_edition.setChecked(True)
        self.message("Plan importé. Place les carrefours et les routes, décoche le mode "
                     "édition puis clique sur « Enregistrer… » pour créer le .json.")

    def charger(self):
        """Bouton « Charger » : choisit un fichier de carte JSON puis le charge."""
        chemin, _ = QFileDialog.getOpenFileName(self, "Charger une carte", DOSSIER_CARTES,
                                                "Cartes (*.json)")
        if chemin:
            self.charger_fichier(chemin)

    def charger_fichier(self, chemin):
        """Charge la carte du fichier JSON donné (message d'erreur si le fichier est illisible).

        Args:
            chemin: chemin du fichier .json.
        """
        try:
            noeuds, routes, pixmap, largeur, hauteur = lire_carte(chemin)
            self.chk_edition.setChecked(False)
            self.appliquer_carte(noeuds, routes, pixmap, largeur, hauteur)
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.message(f"Carte illisible : {e}")
            return
        self.message(f"Carte chargée : {os.path.basename(chemin)}. Clique sur le départ (A).")

    def enregistrer(self):
        """Bouton « Enregistrer » : sauvegarde la carte courante (JSON + image de fond)."""
        if not NOEUDS:
            self.message("La carte est vide : rien à enregistrer.")
            return
        os.makedirs(DOSSIER_CARTES, exist_ok=True)
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la carte", os.path.join(DOSSIER_CARTES, "ma_carte.json"),
            "Cartes (*.json)")
        if chemin:
            nom = ecrire_carte(chemin, self.vue.pixmap, self.vue.largeur, self.vue.hauteur)
            self.message(f"Carte enregistrée : {nom}")

    # ---------- modes et actions ----------
    def basculer_edition(self, actif):
        """Active ou désactive le mode édition.

        En quittant l'édition, la carte modifiée est annoncée aux carrefours (nouvel identifiant).

        Args:
            actif: True pour entrer en mode édition.
        """
        self.edition = actif
        self.sim.arreter()
        self.editeur.selection = None
        self.lbl_aide.setText(AIDE_EDITION if actif else AIDE_SIMULATION)
        if actif:
            self.sim.reinitialiser()
            self.message("Mode édition : dessine les carrefours et les routes.")
        else:
            self.liaison.nouvelle_carte()
            self.reconstruire()
            self.message(CONSIGNE_DEPART)

    def clic_carte(self, x, y, droit):
        """Clic sur la carte : édition, accident (clic droit) ou choix du départ/arrivée selon le mode.

        Args:
            x, y: position du clic sur la carte.
            droit: True pour un clic droit.
        """
        if self.edition:
            self.editeur.clic(x, y, droit)
            self.reconstruire()
        elif droit:
            self.sim.basculer_blocage(x, y)
        else:
            self.sim.choisir(x, y)

    def lancer(self):
        """Bouton « Lancer la mission » avec le véhicule choisi dans la liste."""
        if self.edition:
            self.message("Décoche le mode édition pour lancer une mission.")
            return
        self.sim.lancer(self.combo.currentText())

    def enregistrer_mission(self, mission):
        """Envoie une mission terminée au serveur, qui l'enregistre dans sa base SQLite.

        Args:
            mission: résumé de la mission (voir Simulation.resume).
        """
        if self.liaison.envoyer_mission(mission):
            self.log("Mission envoyée au serveur (historique)")
        else:
            self.log("Pas de serveur : mission non enregistrée")

    def afficher_historique(self):
        """Bouton « Historique » : demande l'historique au serveur (réponse dans montrer_historique)."""
        if not self.liaison.demander_historique():
            self.message("Pas de serveur : historique indisponible.")

    def montrer_historique(self, lignes):
        """Affiche dans un tableau les dernières missions reçues du serveur.

        Args:
            lignes: liste de missions, chacune dans l'ordre de historique.COLONNES.
        """
        titres = ["Date", "Véhicule", "Départ", "Arrivée", "V2I", "Temps (s)", "Estimé (s)",
                  "Direct (s)", "Attente feux (s)", "Recalculs"]
        dialogue = QDialog(self)
        dialogue.setWindowTitle(f"Historique des missions ({len(lignes)} dernières)")
        dialogue.resize(900, 400)
        table = QTableWidget(len(lignes), len(titres))
        table.setHorizontalHeaderLabels(titres)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for i, mission in enumerate(lignes):
            for j, valeur in enumerate(mission):
                if j == 4:                                     # colonne V2I : 1/0 -> oui/non
                    valeur = "oui" if valeur else "non"
                elif valeur is None:                           # trajet direct bloqué
                    valeur = "bloqué"
                table.setItem(i, j, QTableWidgetItem(str(valeur)))
        disposition = QVBoxLayout(dialogue)
        disposition.addWidget(table)
        disposition.addWidget(bouton("Exporter en fichier Excel (.csv)…",
                                     lambda: self.exporter_historique(lignes)))
        dialogue.exec()

    def exporter_historique(self, lignes):
        """Enregistre l'historique dans un fichier CSV lisible, qui s'ouvre avec Excel.

        Missions de la plus ancienne à la plus récente, date et heure séparées,
        trajet « C1 → C9 », temps arrondis au dixième et retard par rapport au temps
        estimé au départ (temps perdu aux feux ou dans le trafic). Séparateur « ; », virgule décimale et UTF-8 avec BOM :
        Excel en français l'ouvre directement, accents compris.

        Args:
            lignes: missions reçues du serveur, dans l'ordre de historique.COLONNES.
        """
        nom = f"historique_{datetime.now():%Y-%m-%d_%Hh%M}.csv"
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter l'historique",
                                                os.path.join(DOSSIER, nom), "CSV (*.csv)")
        if not chemin:
            return

        def nombre(x):
            """Nombre au format français (1 décimale), ou « — » s'il manque."""
            return "—" if x is None else f"{round(x, 1) + 0.0:.1f}".replace(".", ",")

        titres = ["N°", "Date", "Heure", "Véhicule", "Trajet", "Priorité V2I",
                  "Temps réel (s)", "Temps estimé (s)", "Trajet direct (s)",
                  "Retard sur l'estimation (s)", "Attente aux feux (s)", "Recalculs d'itinéraire"]
        with open(chemin, "w", encoding="utf-8-sig") as f:
            f.write(";".join(titres) + "\n")
            for n, m in enumerate(reversed(lignes), 1):        # de la plus ancienne à la plus récente
                date, vehicule, depart, arrivee, v2i, temps, estime, direct, attente, recalculs = m
                jour, _, heure = str(date).partition(" ")
                annee, mois, j = jour.split("-")
                retard = temps - estime                         # temps perdu (feux, trafic...)
                f.write(";".join([str(n), f"{j}/{mois}/{annee}", heure, vehicule,
                                  f"{depart} → {arrivee}", "Oui" if v2i else "Non",
                                  nombre(temps), nombre(estime), nombre(direct), nombre(retard),
                                  nombre(attente), str(recalculs)]) + "\n")
        self.log(f"Historique exporté : {os.path.basename(chemin)}")

    def reinitialiser(self):
        """Bouton « Réinitialiser » : efface départ, arrivée, trajet et véhicule."""
        self.sim.reinitialiser()
        if not self.edition:
            self.message(CONSIGNE_DEPART)

    def closeEvent(self, event):
        """Fermeture de la fenêtre : on arrête la simulation, le réseau et les programmes lancés.

        Args:
            event: évènement de fermeture (QCloseEvent).
        """
        self.sim.arreter()
        self.liaison.arreter()
        super().closeEvent(event)


def main():
    """Lance l'application graphique."""
    app = QApplication(sys.argv)
    fenetre = Fenetre()
    fenetre.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
