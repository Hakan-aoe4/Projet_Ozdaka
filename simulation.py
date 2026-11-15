"""Simulation d'une mission : itinéraire (Dijkstra), déplacement du véhicule, feux, V2I, trafic.

La classe Simulation pilote le véhicule d'urgence. Elle lit l'état des feux dans la Liaison
réseau, demande le vert à l'approche d'un carrefour (V2I) et dessine via la VueCarte.
Elle ne manipule aucun widget : elle communique avec l'IHM par des signaux.
"""
import math
import random

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from commun import BLOQUE, FEUX, NOEUDS, ROUTES, dijkstra, longueur
from vue import COULEUR_ARRIVEE, COULEUR_DEPART

# type de véhicule : (sensibilité au trafic : 1 = subit tout, 0.5 = passe mieux, couleur)
VEHICULES = {"Ambulance": (0.5, "#ffffff"), "Police": (0.6, "#3498db"),
             "Pompiers": (0.5, "#e67e22")}
PAS_MS = 30                     # période du minuteur de déplacement (ms)
DT = PAS_MS / 1000              # durée simulée à chaque pas (s)
SEUIL_BLOQUE = BLOQUE / 10      # un coût au-dessus de ce seuil traverse forcément une route bloquée


def axe(u, v):
    """Détermine l'axe d'une route : horizontale (est-ouest) ou verticale (nord-sud).

    Args:
        u, v: carrefours aux deux extrémités de la route.

    Returns:
        "EO" si la route est plutôt horizontale, "NS" si elle est plutôt verticale.
    """
    (x1, y1), (x2, y2) = NOEUDS[u], NOEUDS[v]
    return "EO" if abs(x2 - x1) >= abs(y2 - y1) else "NS"


class Simulation(QObject):
    """Une mission : choix du départ/arrivée, calcul du trajet, déplacement, statistiques.

    Signaux:
        message(str): consigne ou résultat à afficher à l'utilisateur.
        journal(str): ligne à ajouter au journal.
        stats(str): texte des statistiques de la mission.
        terminee(dict): résumé d'une mission arrivée à destination (pour l'historique).

    Attributes:
        trafic: {frozenset((a, b)): facteur de ralentissement} de chaque route.
        a, b: carrefours de départ et d'arrivée (None tant qu'ils ne sont pas choisis).
        chemin: chemin[0] = carrefour quitté, chemin[1] = prochain carrefour.
        progress: distance déjà parcourue sur la route chemin[0] -> chemin[1].
        v2i: True si le véhicule demande le vert aux feux (communication V2I).
    """

    message = pyqtSignal(str)
    journal = pyqtSignal(str)
    stats = pyqtSignal(str)
    terminee = pyqtSignal(dict)

    def __init__(self, vue, liaison):
        """Prépare une simulation.

        Args:
            vue: VueCarte utilisée pour dessiner le trajet et le véhicule.
            liaison: Liaison réseau (état des feux, demandes de vert).
        """
        super().__init__()
        self.vue, self.liaison = vue, liaison
        self.trafic = {}
        self.a = self.b = None
        self.chemin = []
        self.progress = 0.0
        self.coef = 0.5                    # sensibilité au trafic du véhicule choisi
        self.vehicule = ""                 # nom du véhicule de la mission en cours
        self.v2i = True
        self.temps = self.attente = self.estime = self.direct = 0.0
        self.recalculs = 0
        self.en_attente = False            # True tant que le véhicule est arrêté à un feu
        self.timer_v = QTimer(self)        # fait avancer le véhicule
        self.timer_v.timeout.connect(self.tick)
        self.timer_t = QTimer(self)        # change le trafic aléatoirement
        self.timer_t.timeout.connect(self.trafic_aleatoire)

    # ---------- préparation ----------
    def nouvelle_carte(self):
        """La carte vient de changer : on oublie mission, départ/arrivée, trafic et statistiques."""
        self.arreter()
        self.trafic = {frozenset(r): 1.0 for r in ROUTES}
        self.a = self.b = None
        self.stats.emit("—")

    def activer_v2i(self, actif):
        """Active ou désactive la demande de vert aux feux (V2I).

        Args:
            actif: True pour demander le vert à l'approche des carrefours.
        """
        self.v2i = actif

    def reinitialiser(self):
        """Arrête la mission et efface départ, arrivée, trajet et véhicule."""
        self.arreter()
        self.vue.retirer_vehicule()
        self.vue.dessiner_trajet([])
        self.vue.reinitialiser_noeuds()
        self.a = self.b = None

    def arreter(self):
        """Arrête le déplacement et libère l'éventuelle demande de vert."""
        self.timer_v.stop()
        self.chemin = []
        self.liaison.demander_vert(None)

    # ---------- itinéraire ----------
    def facteur(self, f):
        """Retourne le ralentissement réellement subi par le véhicule choisi.

        Args:
            f: facteur de trafic de la route (1 = fluide).

        Returns:
            Le ralentissement subi (float) ; un facteur « bloqué » est renvoyé tel quel.
        """
        return f if f >= BLOQUE else 1 + (f - 1) * self.coef

    def itineraire(self, depart, arrivee):
        """Calcule le meilleur trajet en tenant compte du trafic.

        Args:
            depart: carrefour de départ.
            arrivee: carrefour d'arrivée.

        Returns:
            Le couple (chemin, cout), ou ([], inf) si toute liaison passe par une route bloquée.
        """
        chemin, cout = dijkstra({k: self.facteur(f) for k, f in self.trafic.items()},
                                depart, arrivee)
        return (chemin, cout) if cout < SEUIL_BLOQUE else ([], math.inf)

    def temps_direct(self):
        """Temps (s) du trajet le plus court en distance, sans tenir compte du trafic.

        Sert de comparaison avec le trajet choisi.

        Returns:
            Le temps en secondes (float), ou inf si ce trajet traverse une route bloquée.
        """
        chemin, _ = dijkstra({}, self.a, self.b)
        total = 0.0
        for u, v in zip(chemin, chemin[1:]):
            f = self.facteur(self.trafic[frozenset((u, v))])
            if f >= BLOQUE:
                return math.inf
            total += longueur(u, v) * f
        return total / self.vue.vitesse

    def replanifier(self):
        """Un événement a changé le trafic : recalcule la suite du trajet depuis le prochain carrefour."""
        if len(self.chemin) < 2 or self.chemin[1] == self.b:
            return
        suite, _ = self.itineraire(self.chemin[1], self.b)
        if suite:
            if suite != self.chemin[1:]:
                self.recalculs += 1
                self.journal.emit("Itinéraire recalculé : " + " → ".join(suite))
            self.chemin = [self.chemin[0]] + suite
            self.vue.dessiner_trajet(self.chemin)

    # ---------- interactions de l'utilisateur ----------
    def choisir(self, x, y):
        """Clic gauche : choisit le départ (A) puis l'arrivée (B) et affiche le trajet estimé.

        Args:
            x, y: position du clic sur la carte.
        """
        nom = self.vue.noeud_en(x, y)
        if nom is None:
            return
        if self.a is None or self.b is not None:          # nouveau départ
            self.reinitialiser()
            self.a = nom
            self.vue.colorier_noeud(nom, COULEUR_DEPART)
            self.message.emit(f"Départ : {nom}. Clique sur l'arrivée.")
        elif nom != self.a:                               # arrivée choisie
            self.b = nom
            self.vue.colorier_noeud(nom, COULEUR_ARRIVEE)
            chemin, cout = self.itineraire(self.a, self.b)
            self.vue.dessiner_trajet(chemin)
            self.message.emit(f"Trajet estimé : {cout / self.vue.vitesse:.1f} s. Lance la mission."
                              if chemin else "Aucun trajet possible.")

    def basculer_blocage(self, x, y):
        """Clic droit sur une route : simule un accident / des travaux (bloque ou rouvre la route).

        Args:
            x, y: position du clic sur la carte.
        """
        cle = self.vue.route_en(x, y)
        if cle is None:
            return
        if len(self.chemin) >= 2 and cle == frozenset(self.chemin[:2]):
            self.message.emit("Impossible : le véhicule est sur cette route.")
            return
        bloquer = self.trafic[cle] < BLOQUE
        self.trafic[cle] = BLOQUE if bloquer else 1.0
        self.journal.emit(f"Route {'-'.join(sorted(cle))} {'bloquée (accident)' if bloquer else 'rouverte'}")
        self.vue.maj_couleurs(self.trafic)
        self.replanifier()

    def activer_trafic(self, actif):
        """Démarre ou arrête le trafic aléatoire (mise à jour toutes les 4 s).

        Args:
            actif: True pour démarrer, False pour arrêter.
        """
        if actif:
            self.trafic_aleatoire()
            self.timer_t.start(4000)
        else:
            self.timer_t.stop()

    def trafic_aleatoire(self):
        """Tire un nouveau trafic au hasard pour chaque route (les routes bloquées le restent)."""
        for cle, f in self.trafic.items():
            if f < BLOQUE:
                r = random.random()
                self.trafic[cle] = 1.0 if r < 0.55 else 2.0 if r < 0.85 else 4.0
        self.vue.maj_couleurs(self.trafic)
        self.journal.emit("Trafic mis à jour")
        self.replanifier()

    # ---------- mission ----------
    def lancer(self, nom):
        """Démarre la mission entre A et B avec le véhicule choisi.

        Args:
            nom: type de véhicule, clé du dictionnaire VEHICULES.
        """
        if self.b is None:
            self.message.emit("Choisis d'abord le départ et l'arrivée sur la carte.")
            return
        self.coef, couleur = VEHICULES[nom]
        self.vehicule = nom
        chemin, cout = self.itineraire(self.a, self.b)
        if not chemin:
            self.message.emit("Aucun trajet possible.")
            return
        self.arreter()
        self.chemin, self.progress = chemin, 0.0
        self.temps = self.attente = 0.0
        self.recalculs = 0
        self.en_attente = False
        self.estime, self.direct = cout / self.vue.vitesse, self.temps_direct()
        self.vue.dessiner_trajet(chemin)
        self.vue.creer_vehicule(couleur)
        self.vue.placer_vehicule(*NOEUDS[self.a])
        self.timer_v.start(PAS_MS)
        self.message.emit(f"{nom} en route...")
        self.journal.emit(f"{nom} part de {self.a} vers {self.b}")

    def tick(self):
        """Un pas de simulation (toutes les 30 ms) : fait avancer le véhicule d'un cran."""
        u, v = self.chemin[:2]
        longueur_route = longueur(u, v)
        self.temps += DT
        self.avancer(u, v, longueur_route)
        if self.progress >= longueur_route:
            if not self.arriver_au_carrefour(v):          # fin de mission ou blocage
                return
        else:                                             # position sur la route par interpolation
            (x1, y1), (x2, y2) = NOEUDS[u], NOEUDS[v]
            t = self.progress / longueur_route
            self.vue.placer_vehicule(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        self.stats.emit(self.texte_stats())

    def avancer(self, u, v, longueur_route):
        """Fait progresser le véhicule sur la route u -> v : V2I, ligne d'arrêt et feu.

        Args:
            u, v: carrefour quitté et carrefour visé.
            longueur_route: longueur de la route u -> v.
        """
        phase = axe(u, v)
        a_un_feu = v in FEUX and v != self.b
        rayon = self.vue.rayon

        # V2I : à l'approche du carrefour, le véhicule demande le vert pour son axe
        proche = a_un_feu and longueur_route - self.progress < rayon * 8
        self.liaison.demander_vert((v, phase) if self.v2i and proche else None)

        f = self.facteur(self.trafic[frozenset((u, v))])
        nouveau = self.progress + self.vue.vitesse / f * DT   # le trafic ralentit le véhicule
        seuil = longueur_route - min(rayon * 1.6, longueur_route * 0.4)   # ligne d'arrêt
        feu = self.liaison.feux.get(v, {}).get(phase, "vert")   # sans serveur : pas de feu
        if a_un_feu and self.progress <= seuil < nouveau and feu != "vert":
            self.progress = seuil                             # arrêt au feu
            self.attente += DT
            if not self.en_attente:
                self.en_attente = True
                self.journal.emit(f"Arrêt au feu {feu}, carrefour {v}")
        else:
            if self.en_attente:
                self.en_attente = False
                self.journal.emit(f"Feu vert au carrefour {v}, le véhicule repart")
            self.progress = nouveau

    def arriver_au_carrefour(self, v):
        """Le véhicule atteint le carrefour v : fin de mission, ou calcul de la suite du trajet.

        Args:
            v: carrefour atteint.

        Returns:
            True si la mission continue, False si elle est terminée ou bloquée.
        """
        self.vue.placer_vehicule(*NOEUDS[v])
        if v == self.b:
            self.stats.emit(self.texte_stats())
            self.arreter()
            self.message.emit(f"Arrivé en {self.temps:.1f} s.")
            self.journal.emit(f"Arrivée en {self.temps:.1f} s")
            self.terminee.emit(self.resume())
            return False
        self.journal.emit(f"Passage au carrefour {v}")
        self.progress = 0.0                                   # à chaque carrefour on recalcule
        chemin, _ = self.itineraire(v, self.b)
        if not chemin:
            self.arreter()
            self.message.emit("Bloqué : plus aucun trajet possible.")
            self.journal.emit("Bloqué : plus aucun trajet possible")
            return False
        self.chemin = chemin
        self.vue.dessiner_trajet(chemin)
        return True

    def resume(self):
        """Résume la mission qui vient de se terminer, pour l'historique.

        Returns:
            Un dictionnaire : véhicule, départ, arrivée, V2I, temps, estimé, direct, attente, recalculs.
            Un temps direct infini (route bloquée) est enregistré comme None.
        """
        return {"vehicule": self.vehicule, "depart": self.a, "arrivee": self.b,
                "v2i": int(self.v2i), "temps": round(self.temps, 2),
                "estime": round(self.estime, 2),
                "direct": None if self.direct == math.inf else round(self.direct, 2),
                "attente": round(self.attente, 2), "recalculs": self.recalculs}

    def texte_stats(self):
        """Construit le texte des statistiques : temps, attente aux feux, comparaison, recalculs.

        Returns:
            Le texte à afficher (str), sur trois lignes.
        """
        direct = "bloqué" if self.direct == math.inf else f"{self.direct:.1f} s"
        return (f"Temps : {self.temps:.1f} s (dont {self.attente:.1f} s aux feux)\n"
                f"Estimé au départ : {self.estime:.1f} s | trajet direct : {direct}\n"
                f"Recalculs d'itinéraire : {self.recalculs}")
