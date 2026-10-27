"""Pattern du cours : acquisition/décision principales, publication dans un thread."""

from __future__ import annotations

from typing import Any
from contextlib import ExitStack

import threading
import time
from queue import Empty
from datetime import datetime, timezone

import config
from capteurs import Flotteur, CapteurLumiere, SoilSensor
from actionneurs import FeuCirculation
from actionneurs.pompe import Pompe
from controleur import Controleur
from publication_donnees import PublicateurMQTT


def creer_bus_i2c() -> Any:
    """Charge le pilote à la demande pour permettre une nouvelle tentative après erreur."""
    import board

    return board.I2C()


def main() -> None:
    # Signale aux deux boucles de terminer leur travail.
    arret = threading.Event()
    # Protège la file de mesures partagée avec le thread MQTT.
    verrou = threading.Lock()
    mesures_en_attente: list[tuple[str, dict]] = []
    flotteur = None
    feu = None
    pompe = None
    i2c = None
    publicateur = None
    thread = None

    topics = {
        "eau": config.TOPIC_EAU,
        "sol": config.TOPIC_SOL,
        "lumiere": config.TOPIC_LUMIERE,
        "statut": config.TOPIC_STATUT,
        "resultat": config.TOPIC_RESULTAT,
    }

    def emettre(nom: str, mesure: dict) -> None:
        topic = topics[nom]
        with verrou:
            mesures_en_attente.append((topic, mesure))

    def publier() -> None:
        with verrou:
            mesures = mesures_en_attente.copy()
            mesures_en_attente.clear()
        for topic, mesure in mesures:
            publicateur.publier(topic, mesure)

    def boucle_publication() -> None:
        try:
            while not arret.wait(config.PERIODE_PUBLICATION):
                publier()
            # Dernier envoi des mesures restantes lors de l’arrêt.
            publier()
        except Exception as erreur:
            print(f"Erreur MQTT, arrêt du matériel : {erreur}")
            arret.set()

    try:
        # Créer le relais inactif avant de démarrer la communication.
        pompe = Pompe(config.GPIO_RELAIS, config.RELAIS_ACTIF_HAUT)
        flotteur = Flotteur(config.GPIO_FLOTTEUR, config.PERIODE_LECTURE_RESERVOIR)
        feu = FeuCirculation(
            config.GPIO_FEU_ROUGE, config.GPIO_FEU_JAUNE, config.GPIO_FEU_VERT
        )

        controleur = Controleur(
            config.FICHIER_ETAT,
            flotteur,
            pompe,
            feu,
            emettre,
            zone=config.FUSEAU_HORAIRE,
        )
        publicateur = PublicateurMQTT("ferixu-publicateur")
        publicateur.connecter()

        thread = threading.Thread(target=boucle_publication)
        thread.start()

        capteur_sol = None
        capteur_lumiere = None

        maintenant = time.monotonic()
        prochaine_sol = maintenant
        prochaine_lumiere = maintenant
        prochain_statut = maintenant

        while not arret.is_set():
            maintenant = time.monotonic()
            controleur.mettre_a_jour(maintenant)
            # Les commandes attendent le thread principal; aucune activation depuis Paho.
            for _ in range(10):
                try:
                    commande = publicateur.commandes.get_nowait()
                except Empty:
                    break
                try:
                    controleur.commande(commande, maintenant)
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    RuntimeError,
                ) as erreur:
                    resultat = {
                        "id": commande.get("id"),
                        "succes": False,
                        "message": str(erreur),
                    }
                else:
                    resultat = {
                        "id": commande.get("id"),
                        "succes": True,
                        "message": "Commande exécutée.",
                    }
                resultat["horodatage"] = datetime.now(timezone.utc).isoformat()
                emettre("resultat", resultat)
                prochain_statut = maintenant

            # EF05 : lecture du réservoir lors de chaque acquisition du sol.
            # Éviter de lancer une lecture I2C pendant les trois secondes d'arrosage.
            if controleur.fin_pompe is None and maintenant >= prochaine_sol:
                controleur.lire_eau()
                try:
                    if i2c is None:
                        i2c = creer_bus_i2c()
                    if capteur_sol is None:
                        capteur_sol = SoilSensor(
                            i2c,
                            config.PERIODE_LECTURE_SOL,
                            config.HUMIDITE_BRUTE_SEC,
                            config.HUMIDITE_BRUTE_HUMIDE,
                        )
                    controleur.recevoir("sol", capteur_sol.lire())
                except (OSError, RuntimeError, ValueError, ImportError) as erreur:
                    controleur.erreurs["sol"] = str(erreur)
                    capteur_sol = None
                    print(f"Sol indisponible : {erreur}")
                else:
                    try:
                        controleur.arroser("automatique", time.monotonic())
                    except (ValueError, OSError, RuntimeError) as erreur:
                        controleur.erreurs["arrosage"] = str(erreur)
                prochaine_sol = maintenant + config.PERIODE_LECTURE_SOL

            if controleur.fin_pompe is None and maintenant >= prochaine_lumiere:
                try:
                    if i2c is None:
                        i2c = creer_bus_i2c()
                    if capteur_lumiere is None:
                        capteur_lumiere = CapteurLumiere(
                            i2c, config.PERIODE_LECTURE_LUMIERE
                        )
                    controleur.recevoir("lumiere", capteur_lumiere.lire())
                except (OSError, RuntimeError, ValueError, ImportError) as erreur:
                    controleur.erreurs["lumiere"] = str(erreur)
                    controleur.derniere_lumiere = None
                    capteur_lumiere = None
                    print(f"BH1750 indisponible : {erreur}")
                prochaine_lumiere = maintenant + config.PERIODE_LECTURE_LUMIERE
            if maintenant >= prochain_statut:
                emettre("statut", controleur.statut())
                prochain_statut = maintenant + config.PERIODE_PUBLICATION
            arret.wait(0.1)
    except KeyboardInterrupt:
        print("Arrêt de Ferixu…")
    finally:
        # Les callbacks sont exécutés en ordre inverse, même si une fermeture échoue.
        with ExitStack() as nettoyage:
            if i2c is not None:
                nettoyage.callback(i2c.deinit)
            if feu is not None:
                nettoyage.callback(feu.fermer)
            if flotteur is not None:
                nettoyage.callback(flotteur.fermer)
            if publicateur is not None:
                nettoyage.callback(publicateur.deconnecter)
            if thread is not None and thread.ident is not None:
                nettoyage.callback(thread.join)
            nettoyage.callback(arret.set)

            # Couper la pompe avant toute attente réseau ou fermeture de capteur.
            if pompe is not None:
                pompe.fermer()


if __name__ == "__main__":
    main()
