# @author Éric et Felix

"""Abonnement MQTT et enregistrement des messages en JSONL et dans MongoDB."""
import json
import math
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.errors import PyMongoError

import config

DOSSIER_DONNEES = config.RACINE / "donnees"
FICHIER_DONNEES = DOSSIER_DONNEES / "lectures_capteurs.jsonl"

if not (config.MONGODB_URI and config.MONGODB_BASE):
    raise ValueError("Renseignez MONGODB_URI et MONGODB_BASE dans .env.")

# Connexion à MongoDB et sélection des collections utilisées par le Raspberry Pi.
mongo = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
base = mongo[config.MONGODB_BASE]
lumiere = base[config.MONGODB_COLLECTION_LUMIERE]
temperature_humidite = base[config.MONGODB_COLLECTION_TEMPERATURE_HUMIDITE]
arrosage = base[config.MONGODB_COLLECTION_ARROSAGE]
plante = base[config.MONGODB_COLLECTION_PLANTE]

TOPICS = (
    config.TOPIC_EAU,
    config.TOPIC_LUMIERE,
    config.TOPIC_SOL,
    config.TOPIC_STATUT,
    config.TOPIC_ARROSAGE,
)


def initialiser_indexes():
    """Crée les index et les collections automatiquement, sans effacer de données."""
    for collection in (lumiere, temperature_humidite, arrosage):
        collection.create_index([("plante_id", 1), ("horodatage", -1)], unique=True)
    plante.create_index("id", unique=True)


def convertir_horodatage(valeur):
    """Convertit une date ISO 8601 avec fuseau en date BSON UTC."""
    if not isinstance(valeur, str):
        raise ValueError("L'horodatage doit être une chaîne ISO 8601.")
    date = datetime.fromisoformat(valeur)
    if date.tzinfo is None:
        raise ValueError("L'horodatage doit préciser son fuseau horaire.")
    date = date.astimezone(timezone.utc)
    # BSON conserve les millisecondes; utiliser la même précision pour les doublons.
    return date.replace(microsecond=date.microsecond // 1000 * 1000)


def verifier_nombre(valeur, nom, minimum=None, maximum=None):
    """Refuse les valeurs manquantes, booléennes, infinies et hors plage."""
    if (
        isinstance(valeur, bool)
        or not isinstance(valeur, (int, float))
        or not math.isfinite(valeur)
        or (minimum is not None and valeur < minimum)
        or (maximum is not None and valeur > maximum)
    ):
        raise ValueError(f"Valeur invalide : {nom}.")
    return valeur


def enregistrer_historique(collection, document):
    """Ajoute une mesure une seule fois, même si MQTT la livre de nouveau."""
    collection.update_one(
        {"plante_id": document["plante_id"], "horodatage": document["horodatage"]},
        {"$setOnInsert": document},
        upsert=True,
    )


def mettre_a_jour_plante(plante_id, champs, horodatage):
    """Met à jour les mesures sans toucher au nom ni au propriétaire de la plante."""
    plante.update_one(
        {"id": plante_id},
        {"$set": champs, "$max": {"horodatage": horodatage}},
        upsert=True,
    )


def enregistrer_donnees(topic, mesure):
    """Enregistre les historiques et l'état courant selon le topic MQTT."""
    plante_id = mesure.get("plante_id", config.PLANTE_ID)
    if type(plante_id) is not int or plante_id <= 0:
        raise ValueError("plante_id doit être un entier positif.")
    horodatage = convertir_horodatage(mesure["horodatage"])
    document = {"plante_id": plante_id, "horodatage": horodatage}

    if topic == config.TOPIC_LUMIERE:
        champs = {"lux": verifier_nombre(mesure.get("lux"), "lux", minimum=0)}
        enregistrer_historique(lumiere, {**document, **champs})
        mettre_a_jour_plante(plante_id, champs, horodatage)
    elif topic == config.TOPIC_SOL:
        champs = {
            "temperature_c": verifier_nombre(mesure.get("temperature_c"), "temperature_c", -40, 85),
            "humidite_brut": verifier_nombre(
                mesure.get("humidite_brute", mesure.get("humidite_brut")), "humidite_brut", 0, 65535
            ),
        }
        enregistrer_historique(temperature_humidite, {**document, **champs})
        mettre_a_jour_plante(plante_id, champs, horodatage)
    elif topic == config.TOPIC_EAU:
        if type(mesure.get("vide")) is not bool:
            raise ValueError("vide doit être un booléen.")
        mettre_a_jour_plante(plante_id, {"eau_vide": mesure["vide"]}, horodatage)
    elif topic == config.TOPIC_ARROSAGE:
        if type(mesure.get("auto")) is not bool:
            raise ValueError("auto doit être un booléen.")
        enregistrer_historique(arrosage, {**document, "auto": mesure["auto"]})
        plante.update_one(
            {"id": plante_id},
            {"$max": {"dernier_arrosage": horodatage, "horodatage": horodatage}},
            upsert=True,
        )
    elif topic == config.TOPIC_STATUT:
        parametres = mesure.get("parametres", {})
        if not isinstance(parametres, dict):
            raise ValueError("parametres doit être un objet JSON.")
        champs = {}
        if "humidite_min" in parametres:
            champs["seuil_humidite"] = verifier_nombre(parametres["humidite_min"], "humidite_min", 0, 100)
        if "lux_min" in parametres:
            champs["seuil_luminosite"] = verifier_nombre(parametres["lux_min"], "lux_min", 1, 200000)
        if champs:
            mettre_a_jour_plante(plante_id, champs, horodatage)


def on_connect(client, userdata, flags, reason_code, properties):
    """Refait l'abonnement après chaque connexion au broker."""
    if reason_code.is_failure:
        print(f"Échec de connexion au broker : {reason_code}")
        return
    print("Connecté au broker MQTT")
    for topic in TOPICS:
        client.subscribe(topic)


def on_message(client, userdata, msg):
    """Reçoit le JSON et conserve l'horodatage créé lors de l'acquisition."""
    # Paho fournit userdata automatiquement; il n'est pas utilisé ici.
    if msg.topic not in TOPICS:
        print(f"Topic inconnu ignoré : {msg.topic}")
        return
    try:
        mesure = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("Message invalide ignoré.")
        return
    if not isinstance(mesure, dict) or not mesure.get("horodatage"):
        print("Mesure sans horodatage ignorée.")
        return
    print(mesure)
    try:
        with open(FICHIER_DONNEES, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(mesure) + "\n")
    except OSError as erreur:
        print(f"Impossible d'enregistrer la mesure : {erreur}")

    try:
        enregistrer_donnees(msg.topic, mesure)
    except (PyMongoError, ValueError, KeyError, TypeError) as erreur:
        print(f"Impossible d'enregistrer la mesure dans MongoDB : {erreur}")


def main():
    """Réutilise un seul client MongoDB et ferme les connexions à l'arrêt."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ferixu-frontend-subscriber")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        DOSSIER_DONNEES.mkdir(exist_ok=True)
        try:
            initialiser_indexes()
        except PyMongoError as erreur:
            print(f"Impossible d'initialiser les index MongoDB : {erreur}")
        client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Arrêt du service d'ingestion…")
    finally:
        try:
            client.disconnect()
        finally:
            mongo.close()


if __name__ == "__main__":
    main()
