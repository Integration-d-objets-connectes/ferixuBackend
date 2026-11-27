# @author Éric et Felix

"""
    Abonnement MQTT et enregistrement des mesures de la plante dans MongoDB.
"""

import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config

FICHIER_DONNEES = config.RACINE / "donnees" / "lectures_capteurs.jsonl"


def preparer_base(db: Database) -> None:
    """Crée les collections time series si elles n'existent pas encore (ne supprime rien).

    Args:
        db (Database): la base de données
    """

    collections = db.list_collection_names()

    if "Lumiere" not in collections:
        # Une collection time series doit être créée avant la première insertion
        db.create_collection(
            "Lumiere",
            timeseries={
                "timeField": "horodatage",
                "metaField": "plante_id",
                "granularity": "minutes",
            },
        )
        print("Collection time series Lumiere créée")

    if "Temperature_humidite" not in collections:
        db.create_collection(
            "Temperature_humidite",
            timeseries={
                "timeField": "horodatage",
                "metaField": "plante_id",
                "granularity": "seconds",
            },
        )
        print("Collection time series Temperature_humidite créée")


def mettre_a_jour_plante(plante_id: int, champs: dict, horodatage: datetime) -> None:
    """Copie les dernières valeurs dans le document de la plante (créé s'il n'existe pas).

    Args:
        plante_id (int): l'identifiant de la plante
        champs (dict): les valeurs à copier
        horodatage (datetime): l'heure de la mesure
    """

    db.Plante.update_one(
        {"id": plante_id},
        # $max : garde la date la plus récente
        {"$set": champs, "$max": {"horodatage": horodatage}},
        # Mettre à jour ou insérer s'il n'existe pas.
        upsert=True,
    )


def enregistrer_lumiere(donnees: dict, horodatage: datetime) -> None:
    """Ajoute une mesure de luminosité et la copie dans la plante.

    Args:
        donnees (dict): message reçu du Pi, contenant « lux »
        horodatage (datetime): l'heure de la mesure
    """

    db.Lumiere.insert_one(
        {
            "horodatage": horodatage,
            "plante_id": donnees["plante_id"],  # référence
            "lux": donnees["lux"],
        }
    )
    mettre_a_jour_plante(donnees["plante_id"], {"lux": donnees["lux"]}, horodatage)
    print(f"[{horodatage}] Lumière : {donnees['lux']} lux")


def enregistrer_sol(donnees: dict, horodatage: datetime) -> None:
    """Ajoute une mesure de température et d'humidité et la copie dans la plante.

    Args:
        donnees (dict): message reçu du Pi, contenant « temperature_c » et « humidite_brute »
        horodatage (datetime): l'heure de la mesure
    """

    champs = {
        "temperature_c": donnees["temperature_c"],
        "humidite_brut": donnees["humidite_brute"],
    }
    db.Temperature_humidite.insert_one(
        {"horodatage": horodatage, "plante_id": donnees["plante_id"], **champs}
    )
    mettre_a_jour_plante(donnees["plante_id"], champs, horodatage)
    print(f"[{horodatage}] Sol : {champs['temperature_c']} °C, humidité {champs['humidite_brut']}")


def enregistrer_eau(donnees: dict, horodatage: datetime) -> None:
    """Copie l'état du réservoir dans la plante.

    Args:
        donnees (dict): message reçu du Pi, contenant « vide »
        horodatage (datetime): l'heure de la mesure
    """

    mettre_a_jour_plante(donnees["plante_id"], {"eau_vide": donnees["vide"]}, horodatage)
    print(f"[{horodatage}] Réservoir vide : {donnees['vide']}")


def enregistrer_arrosage(donnees: dict, horodatage: datetime) -> None:
    """Ajoute un arrosage à l'historique et met à jour le dernier arrosage de la plante.

    Args:
        donnees (dict): message reçu du Pi, contenant « auto »
        horodatage (datetime): l'heure de l'arrosage
    """

    db.Arrosage.insert_one(
        {
            "horodatage": horodatage,
            "plante_id": donnees["plante_id"],
            "auto": donnees["auto"],
        }
    )
    db.Plante.update_one(
        {"id": donnees["plante_id"]},
        {"$max": {"dernier_arrosage": horodatage, "horodatage": horodatage}},
        upsert=True,
    )
    print(f"[{horodatage}] Arrosage (auto : {donnees['auto']})")


def enregistrer_statut(donnees: dict, horodatage: datetime) -> None:
    """Copie les seuils appliqués par le Pi dans la plante.

    Args:
        donnees (dict): message reçu du Pi, contenant « parametres »
        horodatage (datetime): l'heure du statut
    """

    parametres = donnees["parametres"]
    mettre_a_jour_plante(
        donnees["plante_id"],
        {
            "seuil_humidite": parametres["humidite_min"],
            "seuil_luminosite": parametres["lux_min"],
        },
        horodatage,
    )
    print(f"[{horodatage}] Statut : seuils {parametres['humidite_min']} %, {parametres['lux_min']} lux")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Échec de connexion au broker : {reason_code}")
        return

    print("Connecté au broker MQTT")
    # Abonnement ici : il est refait automatiquement après une reconnexion
    client.subscribe(config.TOPIC_LUMIERE, qos=1)
    client.subscribe(config.TOPIC_SOL, qos=1)
    client.subscribe(config.TOPIC_EAU, qos=1)
    client.subscribe(config.TOPIC_ARROSAGE, qos=1)
    client.subscribe(config.TOPIC_STATUT, qos=1)


def on_message(client, userdata, msg):
    try:
        donnees = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        print(f"Message invalide ignoré : {msg.payload}")
        return

    # Heure de réception, en UTC
    horodatage = datetime.now(timezone.utc)

    # Copie brute de chaque message reçu
    with open(FICHIER_DONNEES, "a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(donnees) + "\n")

    try:
        if msg.topic == config.TOPIC_LUMIERE:
            enregistrer_lumiere(donnees, horodatage)
        elif msg.topic == config.TOPIC_SOL:
            enregistrer_sol(donnees, horodatage)
        elif msg.topic == config.TOPIC_EAU:
            enregistrer_eau(donnees, horodatage)
        elif msg.topic == config.TOPIC_ARROSAGE:
            enregistrer_arrosage(donnees, horodatage)
        elif msg.topic == config.TOPIC_STATUT:
            enregistrer_statut(donnees, horodatage)
    except KeyError as erreur:
        print(f"Champ manquant {erreur}, message ignoré : {donnees}")
    except PyMongoError as erreur:
        # Pour éviter qu'une panne d'Atlas arrête tout le service
        print(f"Erreur MongoDB, message perdu : {erreur}")


if __name__ == "__main__":
    # tz_aware=True : les dates lues de MongoDB sont en UTC avec leur fuseau
    client_mongo = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    db = client_mongo[config.MONGODB_BASE]
    preparer_base(db)
    FICHIER_DONNEES.parent.mkdir(exist_ok=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="ferixu-ingestion")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)

    try:
        # On peut faire loop_forever (bloquante) car on ne fait rien d'autre après.
        client.loop_forever()
    except KeyboardInterrupt:
        print("Arrêt du service d'ingestion ...")
    finally:
        client.disconnect()
        client_mongo.close()
