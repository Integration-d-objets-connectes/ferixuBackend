# @author Félix Lachapelle
# @author Éric Lachapelle

"""Configuration centrale du Raspberry Pi, broches en numérotation BCM."""
from pathlib import Path
from os import getenv
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent
load_dotenv(RACINE / ".env")


def _lecture_env(nom):
    return getenv(nom, "")


# ---- MongoDB ---- #
MONGODB_URI = _lecture_env("MONGODB_URI")
MONGODB_BASE = _lecture_env("MONGODB_BASE")

MQTT_HOTE = "localhost"
MQTT_PORT = 1883
MQTT_DELAI_SECONDES = 10
TOPIC_EAU = "ferixu/eau"
TOPIC_LUMIERE = "ferixu/lumiere"
TOPIC_SOL = "ferixu/sol"
GPIO_FLOTTEUR = 16
# Même attribution que le config.py racine; à confirmer sur le montage réel.
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
PERIODE_LECTURE_SOL = 1
# Mesurer ces deux valeurs sur le capteur réellement utilisé avant de les remplir.
# Sans calibration, humidite_pct reste None (null dans le JSON).]
HUMIDITE_BRUTE_SEC = 340
HUMIDITE_BRUTE_HUMIDE = 1016
#dry as fuck 0% 340
#wet as fuck 100% 1016
# Compléter selon le montage réel; None laisse la pompe désactivée.
GPIO_RELAIS = 17
RELAIS_ACTIF_HAUT = True
FUSEAU_HORAIRE = "America/Toronto"
FUSEAU_LOCAL = ZoneInfo(FUSEAU_HORAIRE)
FICHIER_ETAT = RACINE / "donnees" / "etat.json"
TOPIC_COMMANDES = "ferixu/commandes"
TOPIC_STATUT = "ferixu/statut"
TOPIC_RESULTAT = "ferixu/resultat"
