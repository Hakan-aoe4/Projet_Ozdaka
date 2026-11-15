"""Liaison réseau de l'IHM : client TCP (thread Qt) et démarrage automatique du serveur.

La classe Liaison est la seule à parler au réseau : le reste de l'IHM lui demande
d'envoyer la carte, une demande de vert (V2I) ou le résumé d'une mission, et reçoit
l'état des feux et l'historique des missions par des signaux.
"""
import os
import random
import socket
import sys

from PyQt6.QtCore import QObject, QProcess, QThread, QTimer, pyqtSignal

from commun import HOST, NOEUDS, PORT, ROUTES, ecrire, lire

DOSSIER = os.path.dirname(os.path.abspath(__file__))     # là où se trouvent serveur.py et carrefours.py


class ClientReseau(QThread):
    """Écoute le serveur dans un thread à part.

    Chaque message reçu part vers l'IHM par un signal Qt : on ne touche
    jamais à l'interface depuis ce thread.
    """

    recu = pyqtSignal(dict)

    def __init__(self):
        """Ouvre la connexion TCP. Lève OSError si aucun serveur n'écoute."""
        super().__init__()
        self.sock = socket.create_connection((HOST, PORT), timeout=2)
        self.sock.settimeout(None)               # le timeout ne sert qu'à la connexion

    def run(self):
        """Corps du thread : transforme chaque ligne JSON reçue en signal."""
        try:
            for msg in lire(self.sock):
                self.recu.emit(msg)
        except (OSError, ValueError):
            pass                                  # connexion fermée : le thread se termine

    def envoyer(self, msg):
        """Envoie un message (dictionnaire) au serveur ; ignoré si la connexion est coupée.

        Args:
            msg: dictionnaire JSON-compatible à envoyer.
        """
        try:
            ecrire(self.sock, msg)
        except OSError:
            pass

    def arreter(self):
        """Ferme la connexion proprement et attend la fin du thread (1 s maximum)."""
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.wait(1000)


class Liaison(QObject):
    """Tout ce que l'IHM échange avec le serveur : état des feux, carte, demandes V2I.

    Signaux:
        statut(str): texte à afficher dans l'indicateur « Réseau ».
        journal(str): ligne à ajouter au journal de l'IHM.
        feux_changes(): l'attribut « feux » vient d'être mis à jour.
        historique_recu(list): liste des dernières missions envoyée par le serveur.

    Attributes:
        feux: dernier état reçu, {carrefour: {"EO": couleur, "NS": couleur}}.
        id_carte: identifiant de la carte courante (pour synchroniser les carrefours).
    """

    statut = pyqtSignal(str)
    journal = pyqtSignal(str)
    feux_changes = pyqtSignal()
    historique_recu = pyqtSignal(list)

    def __init__(self):
        """Crée une liaison non connectée ; appeler demarrer() pour se connecter."""
        super().__init__()
        self.client = None           # ClientReseau, ou None si non connecté
        self.processus = []          # serveur / carrefours démarrés par l'IHM
        self.id_carte = 0
        self.feux = {}
        self.prio = None             # (carrefour, axe) pour lequel un vert est demandé
        self.essais = 0
        self.feux_recus = False      # au moins un message FEUX reçu depuis la connexion
        self.carrefours_lances = False

    # ---------- connexion ----------
    def demarrer(self):
        """Se connecte au serveur ; s'il est absent, le démarre ainsi que les carrefours."""
        self.statut.emit("Réseau : …")
        if not self.connecter():
            self.journal.emit("Serveur absent : démarrage du serveur et des carrefours")
            self.statut.emit("Réseau : démarrage…")
            self.lancer_script("serveur.py")
            self.essais = 0
            QTimer.singleShot(600, self.finir_demarrage)

    def connecter(self):
        """Tente de se connecter au serveur.

        Returns:
            True si la connexion est établie, False sinon.
        """
        try:
            self.client = ClientReseau()
        except OSError:
            self.client = None
            self.statut.emit("Réseau : non connecté (pas de feux)")
            return False
        self.client.recu.connect(self.recevoir)
        self.client.finished.connect(self.perdu)
        self.client.start()
        self.statut.emit("Réseau : connecté")
        self.journal.emit("Connecté au serveur")
        self.feux_recus = False
        self.envoyer_carte()
        QTimer.singleShot(2500, self.verifier_carrefours)
        return True

    def verifier_carrefours(self):
        """Connecté mais aucun feu reçu (serveur déjà lancé sans carrefours) : on lance les carrefours."""
        if self.client and not self.feux_recus and not self.carrefours_lances:
            self.journal.emit("Aucun feu reçu : démarrage des carrefours")
            self.lancer_carrefours()

    def lancer_carrefours(self):
        """Démarre carrefours.py une seule fois."""
        if not self.carrefours_lances:
            self.carrefours_lances = True
            self.lancer_script("carrefours.py")

    def lancer_script(self, script):
        """Démarre un des programmes du projet (serveur.py, carrefours.py) en arrière-plan.

        Args:
            script: nom du fichier Python à lancer, situé à côté de ce module.
        """
        p = QProcess(self)
        p.setProgram(sys.executable)
        p.setArguments([os.path.join(DOSSIER, script)])
        p.setWorkingDirectory(DOSSIER)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        p.start()
        self.processus.append(p)

    def finir_demarrage(self):
        """Réessaie de se connecter (30 fois max, ~10 s) ; une fois connecté, lance les carrefours."""
        if self.connecter():
            self.lancer_carrefours()
        elif self.essais < 30:
            self.essais += 1
            QTimer.singleShot(300, self.finir_demarrage)
        else:
            self.journal.emit("Impossible de joindre le serveur")

    def perdu(self):
        """Slot appelé quand le thread réseau se termine : la connexion est perdue."""
        if self.client is not None:              # sinon : fermeture volontaire, rien à signaler
            self.client = None
            self.feux = {}
            self.feux_changes.emit()
            self.statut.emit("Réseau : déconnecté (pas de feux)")
            self.journal.emit("Connexion au serveur perdue")

    def arreter(self):
        """Ferme la connexion et arrête les programmes démarrés par cette liaison."""
        client, self.client = self.client, None
        if client:
            client.arreter()
        for p in self.processus:
            p.kill()
            p.waitForFinished(500)

    # ---------- messages ----------
    def envoyer(self, msg):
        """Envoie un message au serveur s'il est connecté.

        Args:
            msg: dictionnaire JSON-compatible avec une clé « type ».
        """
        if self.client:
            self.client.envoyer(msg)

    def nouvelle_carte(self):
        """Déclare une nouvelle carte : nouvel identifiant, feux effacés, carte envoyée."""
        self.id_carte = random.getrandbits(32)
        self.feux = {}
        self.envoyer_carte()

    def envoyer_carte(self):
        """Envoie la carte courante (message CARTE) aux carrefours."""
        self.envoyer({"type": "CARTE", "id": self.id_carte, "noeuds": NOEUDS, "routes": ROUTES})

    def recevoir(self, msg):
        """Slot exécuté dans le thread IHM : traite un message venu du serveur.

        Args:
            msg: message reçu : FEUX (état des feux) ou HISTORIQUE (réponse du serveur).
        """
        if msg.get("type") == "HISTORIQUE":
            self.historique_recu.emit(msg.get("missions", []))
            return
        if msg.get("type") != "FEUX":
            return
        self.feux_recus = True
        if msg.get("carte") != self.id_carte:     # les carrefours n'ont pas la bonne carte
            self.envoyer_carte()
            return
        self.feux = msg["etats"]
        self.feux_changes.emit()

    def demander_vert(self, voulue):
        """V2I : demande le vert pour le véhicule, ou libère la demande précédente.

        Args:
            voulue: couple (carrefour, axe) pour lequel on veut le vert, ou None pour libérer.
        """
        if voulue == self.prio:
            return
        if self.prio:
            self.envoyer({"type": "FIN_VERT", "carrefour": self.prio[0]})
        if voulue:
            self.envoyer({"type": "DEMANDE_VERT", "carrefour": voulue[0], "phase": voulue[1]})
            self.journal.emit(f"V2I : demande de vert au carrefour {voulue[0]}")
        self.prio = voulue

    # ---------- historique (base sur le serveur) ----------
    def envoyer_mission(self, mission):
        """Envoie le résumé d'une mission terminée au serveur, qui l'enregistre dans sa base.

        Args:
            mission: résumé de la mission (voir Simulation.resume).

        Returns:
            True si le message est parti, False si on n'est pas connecté.
        """
        if not self.client:
            return False
        self.envoyer(dict(mission, type="FIN_MISSION"))
        return True

    def demander_historique(self):
        """Demande l'historique au serveur ; la réponse arrive par le signal historique_recu.

        Returns:
            True si la demande est partie, False si on n'est pas connecté.
        """
        if not self.client:
            return False
        self.envoyer({"type": "DEMANDE_HISTORIQUE"})
        return True
