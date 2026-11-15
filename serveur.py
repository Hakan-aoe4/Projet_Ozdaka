"""Serveur central d'OzdAka : relaie chaque message JSON reçu à tous les autres clients.

Les véhicules et les carrefours ne se parlent jamais directement : tout passe par ce serveur
(architecture en étoile). Une thread par client (threading), sockets TCP brutes.

Le serveur tient aussi la base de l'historique des missions (historique.db, voir historique.py) :
la base est donc sur la machine du serveur, pas sur celle de l'interface. Deux messages lui
sont destinés et ne sont pas relayés :
    FIN_MISSION         l'IHM envoie le résumé d'une mission terminée -> ajouté à la base
    DEMANDE_HISTORIQUE  l'IHM demande l'historique -> réponse HISTORIQUE à ce client seulement

Lancement :  python serveur.py   (démarré automatiquement par carte.py)
"""
import json
import socket
import threading

import historique
from commun import PORT, ecrire

clients = []                      # sockets des clients connectés
verrou = threading.Lock()         # protège la liste « clients » (accédée par plusieurs threads)
verrou_base = threading.Lock()    # une seule écriture à la fois dans la base SQLite


def traiter_historique(conn, msg):
    """Traite un message destiné au serveur lui-même (historique des missions).

    Args:
        conn: socket du client qui a envoyé le message.
        msg: message reçu (dictionnaire).

    Returns:
        True si le message a été traité ici (il ne faut pas le relayer), False sinon.
    """
    if msg.get("type") == "FIN_MISSION":
        mission = {c: msg.get(c) for c in historique.COLONNES if c != "date"}
        with verrou_base:
            historique.enregistrer(mission)
        print(f"Mission enregistrée : {mission['vehicule']} {mission['depart']} -> {mission['arrivee']}")
        return True
    if msg.get("type") == "DEMANDE_HISTORIQUE":
        with verrou_base:
            lignes = historique.dernieres()
        ecrire(conn, {"type": "HISTORIQUE", "missions": lignes})
        return True
    return False


def servir(conn):
    """Gère un client : chaque ligne qu'il envoie est retransmise à tous les autres,
    sauf les messages d'historique, traités par le serveur lui-même.

    Args:
        conn: socket du client, fournie par accept().
    """
    with verrou:
        clients.append(conn)
    try:
        for ligne in conn.makefile("r", encoding="utf-8"):
            try:
                if traiter_historique(conn, json.loads(ligne)):
                    continue                          # message pour le serveur : pas relayé
            except (ValueError, KeyError, TypeError, AttributeError):
                pass                                  # ligne illisible : relayée telle quelle
            except Exception as e:                    # base illisible, disque plein...
                print("Historique : erreur", e)
                continue
            with verrou:
                for autre in clients:
                    if autre is not conn:             # on ne renvoie pas à l'expéditeur
                        try:
                            autre.sendall(ligne.encode())
                        except OSError:
                            pass                      # cet autre client vient de partir
    except OSError:
        pass
    finally:
        with verrou:
            clients.remove(conn)
        conn.close()


def main():
    """Ouvre le port d'écoute et crée une thread de service par client qui se connecte."""
    serveur = socket.socket()
    serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # relance rapide du serveur
    serveur.bind(("0.0.0.0", PORT))
    serveur.listen()
    print(f"Serveur OzdAka sur le port {PORT}, historique : {historique.FICHIER} (Ctrl+C pour arrêter)")
    try:
        while True:
            conn, adresse = serveur.accept()
            print("Client connecté :", adresse[0])
            threading.Thread(target=servir, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.close()


if __name__ == "__main__":
    main()
