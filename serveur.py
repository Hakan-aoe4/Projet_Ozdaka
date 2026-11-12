"""Serveur central : relaie chaque message JSON reçu à tous les autres clients.

Lancement :  python serveur.py
"""
import socket
import threading

from commun import PORT

clients = []
verrou = threading.Lock()


def servir(conn):
    with verrou:
        clients.append(conn)
    try:
        for ligne in conn.makefile("r", encoding="utf-8"):
            with verrou:
                for autre in clients:
                    if autre is not conn:
                        try:
                            autre.sendall(ligne.encode())
                        except OSError:
                            pass
    except OSError:
        pass
    finally:
        with verrou:
            clients.remove(conn)
        conn.close()


serveur = socket.socket()
serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
serveur.bind(("0.0.0.0", PORT))
serveur.listen()
print(f"Serveur OzdAka sur le port {PORT} (Ctrl+C pour arrêter)")
try:
    while True:
        conn, addr = serveur.accept()
        print("Client connecté :", addr[0])
        threading.Thread(target=servir, args=(conn,), daemon=True).start()
except KeyboardInterrupt:
    pass
finally:
    serveur.close()
