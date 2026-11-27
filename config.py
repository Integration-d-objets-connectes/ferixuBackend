# @author Félix Lachapelle
# @author Éric

"""Configuration centrale du Raspberry Pi, broches en numérotation BCM."""
from pathlib import Path
from os import getenv

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent
load_dotenv(RACINE / ".env")


def _lecture_env(nom: str) -> str:
    """Lit une variable d'environnement obligatoire, comme dans la démo du cours.

    Args:
        nom (str): Nom de la variable dans le fichier .env.

    Raises:
        RuntimeError: Si la variable est absente ou vide.

    Returns:
        str: Valeur de la variable.
    """
    valeur = getenv(nom)
    if not valeur:
        raise RuntimeError(f"Variable d'environnement manquante : {nom}")

    return valeur


# ---- MongoDB (service d'ingestion seulement) ---- #
# Lues sans erreur ici : le Pi n'en a pas besoin. L'ingestion vérifie leur présence.
MONGODB_URI = getenv("MONGODB_URI", "")
MONGODB_BASE = getenv("MONGODB_BASE", "")
PLANTE_ID = int(getenv("PLANTE_ID", "1"))

# ---- Broker MQTT (EMQX), comme dans la démo du cours ---- #
MQTT_HOTE = _lecture_env("BROKER")
MQTT_PORT = int(_lecture_env("PORT"))
MQTT_UTILISATEUR = _lecture_env("USERNAME")
MQTT_MOT_DE_PASSE = _lecture_env("PASSWORD")
# Certificat du broker EMQX pour la connexion TLS
MQTT_CERTIFICAT_CA = RACINE / "emqxsl-ca.crt"

TOPIC_EAU = "ferixu/eau"
TOPIC_LUMIERE = "ferixu/lumiere"
TOPIC_SOL = "ferixu/sol"
GPIO_FLOTTEUR = 16
# Broches du feu tricolore; à confirmer sur le montage réel.
GPIO_FEU_ROUGE = 23
GPIO_FEU_JAUNE = 22
GPIO_FEU_VERT = 27
# EF05 : synchronisée avec la lecture du sol.
PERIODE_LECTURE_RESERVOIR = 600

# Période du thread MQTT (indépendante des périodes de lecture).
PERIODE_PUBLICATION = 5

# EF03 : lecture de la luminosité toutes les minutes.
PERIODE_LECTURE_LUMIERE = 60

# EF01 et EF02 : humidité et température acquises ensemble toutes les 10 min.
PERIODE_LECTURE_SOL = 600
# Calibration mesurée sur notre capteur : valeur brute dans un sol sec (0 %)
# et dans l'eau (100 %). Sans calibration, humidite_pct reste None (null dans le JSON).
HUMIDITE_BRUTE_SEC = 340
HUMIDITE_BRUTE_HUMIDE = 1016
# Compléter selon le montage réel; None laisse la pompe désactivée.
GPIO_RELAIS = 17
RELAIS_ACTIF_HAUT = True
FUSEAU_HORAIRE = "America/Toronto"
FICHIER_ETAT = RACINE / "donnees" / "etat.json"

TOPIC_COMMANDES = "ferixu/commandes"
TOPIC_STATUT = "ferixu/statut"
TOPIC_RESULTAT = "ferixu/resultat"
TOPIC_ARROSAGE = "ferixu/arrosage"
# Configuration réellement appliquée, publiée par le Pi (retenue), comme dans la démo
TOPIC_CONFIGURATION = "ferixu/configuration"
