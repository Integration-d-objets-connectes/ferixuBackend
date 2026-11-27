# @author Félix Lachapelle
# @author Éric

"""Démarre l’acquisition sur le Raspberry Pi et la publication périodique sur MQTT.

Le thread principal applique les règles de la plante et commande les actionneurs.
"""

import threading
import time
from contextlib import ExitStack
from queue import Empty, Queue

import config
from actionneurs import FeuCirculation, Pompe
from capteurs import Acquisition, Flotteur
from controleur import Controleur
from publication_donnees import PublicateurMQTT
from reception_donnees import AbonneMQTT

TOPICS = {
    "eau": config.TOPIC_EAU,
    "sol": config.TOPIC_SOL,
    "lumiere": config.TOPIC_LUMIERE,
    "statut": config.TOPIC_STATUT,
    "resultat": config.TOPIC_RESULTAT,
    "arrosage": config.TOPIC_ARROSAGE,
    "configuration": config.TOPIC_CONFIGURATION,
}


# 1. Publier les messages en attente dans un thread séparé


def boucle_publication(publicateur, messages, verrou, arret) -> None:
    """Envoie les messages par lots et vide le dernier lot à l’arrêt.

    Args:
        publicateur: Client qui envoie les messages au broker MQTT.
        messages: Messages produits par le thread principal.
        verrou: Protège la liste partagée entre les deux threads.
        arret: Signal d’arrêt commun.
    """
    try:
        while True:
            termine = arret.wait(config.PERIODE_PUBLICATION)
            with verrou:
                lot = messages.copy()
                messages.clear()

            for topic, message in lot:
                # Le broker conserve la dernière configuration appliquée.
                publicateur.publier(
                    topic, message, retenir=topic == config.TOPIC_CONFIGURATION
                )

            if termine:
                break
    except Exception as erreur:
        print(f"Erreur MQTT, arrêt du matériel : {erreur}")
        arret.set()


# 2. Initialiser le matériel, traiter les commandes et acquérir les mesures


def main() -> None:
    """Démarre les deux boucles et libère le matériel à l’arrêt."""
    arret = threading.Event()
    verrou = threading.Lock()
    messages = []
    commandes = Queue()

    def emettre(nom: str, message: dict) -> None:
        """Ajoute un message de la plante à la liste de publication.

        Args:
            nom: Clé du topic MQTT.
            message: Mesure, événement ou statut à publier.
        """
        with verrou:
            messages.append((TOPICS[nom], {**message, "plante_id": config.PLANTE_ID}))

    try:
        with ExitStack() as nettoyage:
            acquisition = Acquisition(time.monotonic())
            nettoyage.callback(acquisition.fermer)
            pompe = Pompe(config.GPIO_RELAIS, config.RELAIS_ACTIF_HAUT)
            try:
                flotteur = Flotteur(config.GPIO_FLOTTEUR, config.PERIODE_LECTURE_RESERVOIR)
                nettoyage.callback(flotteur.fermer)
                feu = FeuCirculation(
                    config.GPIO_FEU_ROUGE, config.GPIO_FEU_JAUNE, config.GPIO_FEU_VERT
                )
                nettoyage.callback(feu.fermer)
                controleur = Controleur(
                    config.FICHIER_ETAT, flotteur, pompe, feu, emettre,
                    zone=config.FUSEAU_HORAIRE,
                )

                publicateur = PublicateurMQTT("ferixu-publicateur")
                nettoyage.callback(publicateur.deconnecter)
                publicateur.connecter()

                # Paho reçoit les commandes. Le thread principal les exécute.
                abonne = AbonneMQTT("ferixu-abonne", config.TOPIC_COMMANDES, commandes.put)
                nettoyage.callback(abonne.deconnecter)
                abonne.connecter()

                thread_publication = threading.Thread(
                    target=boucle_publication, args=(publicateur, messages, verrou, arret)
                )
                thread_publication.start()
                nettoyage.callback(thread_publication.join)
                nettoyage.callback(arret.set)

                prochain_statut = time.monotonic()
                while not arret.is_set():
                    maintenant = time.monotonic()
                    controleur.mettre_a_jour(maintenant)
                    # Limiter le lot pour vérifier régulièrement le niveau d’eau.
                    for _ in range(10):
                        try:
                            commande = commandes.get_nowait()
                        except Empty:
                            break
                        controleur.traiter_commande(commande, maintenant)
                        prochain_statut = maintenant

                    acquisition.lire(controleur, maintenant)
                    if maintenant >= prochain_statut:
                        emettre("statut", controleur.statut())
                        prochain_statut = maintenant + config.PERIODE_PUBLICATION
                    arret.wait(0.1)
            finally:
                # Couper la pompe avant le nettoyage du bus et les attentes réseau.
                pompe.fermer()
    except KeyboardInterrupt:
        print("Arrêt de Ferixu…")


# Point d’entrée du programme du Raspberry Pi

if __name__ == "__main__":
    main()
