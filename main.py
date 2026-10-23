"""Pattern du cours : acquisition/décision principales, publication dans un thread."""
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


def creer_bus_i2c():
    import board
    return board.I2C()


def main():
    arret = threading.Event()
    verrou = threading.Lock()
    mesures_en_attente = []
    flotteur = feu = pompe = i2c = publicateur = thread = None

    def emettre(nom, mesure):
        topic = {"eau": config.TOPIC_EAU, "sol": config.TOPIC_SOL,
                 "lumiere": config.TOPIC_LUMIERE, "statut": config.TOPIC_STATUT,
                 "resultat": config.TOPIC_RESULTAT}[nom]
        with verrou:
            mesures_en_attente.append((topic, mesure))

    def publier():
        with verrou:
            mesures = mesures_en_attente.copy()
            mesures_en_attente.clear()
        for topic, mesure in mesures:
            publicateur.publier(topic, mesure)

    def boucle_publication():
        try:
            while not arret.wait(config.PERIODE_PUBLICATION):
                publier()
            publier()
        except Exception as erreur:
            print(f"Erreur MQTT, arrêt du matériel : {erreur}")
            arret.set()

    try:
        # Créer le relais inactif avant de démarrer la communication.
        pompe = Pompe(config.GPIO_RELAIS, config.RELAIS_ACTIF_HAUT)
        pompe.allumer(10)
        flotteur = Flotteur(config.GPIO_FLOTTEUR, config.PERIODE_LECTURE_RESERVOIR)
        feu = FeuCirculation(config.GPIO_FEU_ROUGE, config.GPIO_FEU_JAUNE, config.GPIO_FEU_VERT)
        controleur = Controleur(config.FICHIER_ETAT, flotteur, pompe, feu, emettre,
                                zone=config.FUSEAU_HORAIRE)
        publicateur = PublicateurMQTT("ferixu-publicateur")
        publicateur.connecter()
        thread = threading.Thread(target=boucle_publication)
        thread.start()
        capteur_sol = capteur_lumiere = None
        prochaine_sol = prochaine_lumiere = prochain_statut = time.monotonic()
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
                except (ValueError, KeyError, TypeError, OSError, RuntimeError) as erreur:
                    resultat = {"id": commande.get("id"), "succes": False, "message": str(erreur)}
                else:
                    resultat = {"id": commande.get("id"), "succes": True, "message": "Commande exécutée."}
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
                        capteur_sol = SoilSensor(i2c, config.PERIODE_LECTURE_SOL,
                                                config.HUMIDITE_BRUTE_SEC, config.HUMIDITE_BRUTE_HUMIDE)
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
                        capteur_lumiere = CapteurLumiere(i2c, config.PERIODE_LECTURE_LUMIERE)
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
        # Couper la pompe avant toute attente réseau ou fermeture de capteur.
        try:
            if pompe is not None:
                pompe.fermer()
        finally:
            arret.set()
            try:
                if thread is not None and thread.ident is not None:
                    thread.join()
            finally:
                try:
                    if publicateur is not None:
                        publicateur.deconnecter()
                finally:
                    try:
                        if flotteur is not None:
                            flotteur.fermer()
                    finally:
                        try:
                            if feu is not None:
                                feu.fermer()
                        finally:
                            if i2c is not None:
                                i2c.deinit()


if __name__ == "__main__":
    main()
