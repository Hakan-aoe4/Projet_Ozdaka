"""Historique des missions, stocké dans une base SQLite (fichier historique.db).

Ce module est utilisé par le serveur (serveur.py) : la base se trouve sur la machine
du serveur. L'IHM n'y accède jamais directement, elle passe par le réseau
(messages FIN_MISSION et DEMANDE_HISTORIQUE).

Chaque mission terminée est enregistrée avec ses statistiques, pour pouvoir comparer
les missions entre elles (avec ou sans priorité V2I, selon le véhicule, etc.).
Le fichier est créé automatiquement à la première mission.
"""
import os
import sqlite3
from datetime import datetime

FICHIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historique.db")

COLONNES = ("date", "vehicule", "depart", "arrivee", "v2i", "temps", "estime",
            "direct", "attente", "recalculs")


def connexion():
    """Ouvre la base et crée la table des missions si elle n'existe pas encore.

    Returns:
        Une connexion sqlite3 ouverte (à fermer par l'appelant).
    """
    bdd = sqlite3.connect(FICHIER)
    bdd.execute("""CREATE TABLE IF NOT EXISTS missions (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       date TEXT, vehicule TEXT, depart TEXT, arrivee TEXT, v2i INTEGER,
                       temps REAL, estime REAL, direct REAL, attente REAL, recalculs INTEGER)""")
    return bdd


def enregistrer(mission):
    """Ajoute une mission terminée à l'historique.

    Args:
        mission: dictionnaire contenant les clés de COLONNES (sauf « date », ajoutée ici).
    """
    mission = dict(mission, date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with connexion() as bdd:                      # « with » valide l'écriture (commit)
        bdd.execute(f"INSERT INTO missions ({', '.join(COLONNES)}) "
                    f"VALUES ({', '.join('?' * len(COLONNES))})",
                    [mission[c] for c in COLONNES])
    bdd.close()


def dernieres(nombre=50):
    """Lit les dernières missions enregistrées, de la plus récente à la plus ancienne.

    Args:
        nombre: nombre maximum de missions à renvoyer.

    Returns:
        Une liste de tuples, dans l'ordre de COLONNES.
    """
    bdd = connexion()
    lignes = bdd.execute(f"SELECT {', '.join(COLONNES)} FROM missions ORDER BY id DESC LIMIT ?",
                         (nombre,)).fetchall()
    bdd.close()
    return lignes


def vider():
    """Supprime toutes les missions de l'historique."""
    with connexion() as bdd:
        bdd.execute("DELETE FROM missions")
    bdd.close()
