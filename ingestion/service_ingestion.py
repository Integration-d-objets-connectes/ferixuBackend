# @author Éric et Felix

"""
    Abonnement MQTT et enregistrement des mesures de la plante dans MongoDB.
"""

import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from pymongo import MongoClient, ReturnDocument
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config

FICHIER_DONNEES = config.RACINE / "donnees" / "lectures_capteurs.jsonl"
# Nom donné à la plante à la création de son document (voir documentation/README.md)
NOM_PLANTE = "Basilic"


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

    # Index des collections classiques : l'API filtre par plante et trie par date
    db.Arrosage.create_index([("plante_id", 1), ("horodatage", 1)])
    db.evenements.create_index([("plante_id", 1), ("horodatage", 1)])
    db.Plante.create_index("id", unique=True)


def mettre_a_jour_plante(plante_id: int, champs: dict, horodatage: datetime) -> None:
    """Copie les dernières valeurs dans le document de la plante (créé s'il n'existe pas).

    Args:
        plante_id (int): l'identifiant de la plante
        champs (dict): les valeurs à copier
        horodatage (datetime): l'heure de la mesure
    """

    db.Plante.update_one(
        {"id": plante_id},
        {
            "$set": champs,
            # $max : garde la date la plus récente
            "$max": {"horodatage": horodatage},
            # Seulement à la création du document (upsert)
            "$setOnInsert": {"nom": NOM_PLANTE},
        },
        # Mettre à jour ou insérer s'il n'existe pas.
        upsert=True,
    )


def ajouter_evenement(plante_id: int, type_evenement: str, details: dict, horodatage: datetime) -> None:
    """Ajoute une activité à l'historique « evenements », comme dans la démo du cours.

    Args:
        plante_id (int): l'identifiant de la plante (référence)
        type_evenement (str): « etat », « configuration » ou « commande »
        details (dict): les informations propres à l'événement
        horodatage (datetime): l'heure de l'événement (UTC)
    """

    db.evenements.insert_one(
        {
            "horodatage": horodatage,
            "plante_id": plante_id,
            "type": type_evenement,
            "details": details,
        }
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
        donnees (dict): message reçu du Pi, contenant « temperature_c », « humidite_brute »
            et « humidite_pct »
        horodatage (datetime): l'heure de la mesure
    """

    champs = {
        "temperature_c": donnees["temperature_c"],
        "humidite_brut": donnees["humidite_brute"],
        # Pourcentage calibré par le Pi (None sans calibration), utilisé par les seuils
        "humidite_pct": donnees.get("humidite_pct"),
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
        donnees (dict): message reçu du Pi, contenant « auto », « mode » et « duree »
        horodatage (datetime): l'heure de l'arrosage
    """

    db.Arrosage.insert_one(
        {
            "horodatage": horodatage,
            "plante_id": donnees["plante_id"],
            "auto": donnees["auto"],
            # automatique, manuel ou test (absents des messages d'avant cette version)
            "mode": donnees.get("mode"),
            "duree": donnees.get("duree"),
        }
    )
    db.Plante.update_one(
        {"id": donnees["plante_id"]},
        {"$max": {"dernier_arrosage": horodatage, "horodatage": horodatage}},
        upsert=True,
    )
    print(f"[{horodatage}] Arrosage (auto : {donnees['auto']})")


def enregistrer_statut(donnees: dict, horodatage: datetime) -> None:
    """Copie l'état du système dans la plante et historise les changements d'état.

    Le Pi publie son statut toutes les 5 s : seul un changement de couleur
    (vert, jaune, rouge, inconnu) devient un événement « etat » (alerte).

    Args:
        donnees (dict): message reçu du Pi (« parametres », « couleur », ...)
        horodatage (datetime): l'heure du statut
    """

    parametres = donnees["parametres"]
    prochain_auto = donnees.get("prochain_auto")
    champs = {
        "couleur": donnees["couleur"],
        "heures_lumiere": donnees.get("heures_lumiere"),
        "pompe_active": donnees.get("pompe_active"),
        "erreurs": donnees.get("erreurs", {}),
        "prochain_auto": datetime.fromisoformat(prochain_auto) if prochain_auto else None,
        "seuil_humidite": parametres["humidite_min"],
        "seuil_luminosite": parametres["lux_min"],
        "duree_arrosage": parametres["duree_arrosage"],
        "automatique": parametres["automatique"],
    }
    # ReturnDocument.BEFORE : renvoie la plante avant la mise à jour, pour comparer la couleur
    avant = db.Plante.find_one_and_update(
        {"id": donnees["plante_id"]},
        {
            "$set": champs,
            "$max": {"horodatage": horodatage},
            "$setOnInsert": {"nom": NOM_PLANTE},
        },
        projection={"couleur": 1},
        upsert=True,
        return_document=ReturnDocument.BEFORE,
    )
    ancienne = avant.get("couleur") if avant else None
    if ancienne != donnees["couleur"]:
        ajouter_evenement(
            donnees["plante_id"],
            "etat",
            {"ancienne": ancienne, "nouvelle": donnees["couleur"], "erreurs": champs["erreurs"]},
            horodatage,
        )
        print(f"[{horodatage}] État : {ancienne} → {donnees['couleur']}")


def enregistrer_configuration(donnees: dict, horodatage: datetime, retenu: bool) -> None:
    """Enregistre la configuration appliquée par le Pi : historique et copie dans la plante.

    Args:
        donnees (dict): message reçu du Pi : humidite_min, lux_min, duree_arrosage, automatique
        horodatage (datetime): moment où le Pi a appliqué la configuration (UTC)
        retenu (bool): True si le message est retenu par le broker (déjà reçu avant) :
            la plante est mise à jour, mais aucun événement n'est ajouté à l'historique.
    """

    configuration = {
        cle: donnees[cle] for cle in ("humidite_min", "lux_min", "duree_arrosage", "automatique")
    }
    # Message retenu = déjà reçu avant (ex. redémarrage de l'ingestion) : pas de doublon
    if not retenu:
        ajouter_evenement(donnees["plante_id"], "configuration", configuration, horodatage)

    mettre_a_jour_plante(
        donnees["plante_id"],
        {
            "seuil_humidite": configuration["humidite_min"],
            "seuil_luminosite": configuration["lux_min"],
            "duree_arrosage": configuration["duree_arrosage"],
            "automatique": configuration["automatique"],
        },
        horodatage,
    )
    print(f"[{horodatage}] Configuration appliquée : {configuration}")


def enregistrer_resultat(donnees: dict, horodatage: datetime) -> None:
    """Historise le résultat d'une commande manuelle (arrosage, tests, paramètres).

    Args:
        donnees (dict): message reçu du Pi : id, action, succes, message
        horodatage (datetime): l'heure du traitement de la commande
    """

    ajouter_evenement(
        donnees["plante_id"],
        "commande",
        {
            "id": donnees["id"],
            "action": donnees.get("action"),
            "succes": donnees["succes"],
            "message": donnees["message"],
        },
        horodatage,
    )
    print(f"[{horodatage}] Commande {donnees.get('action')} : {donnees['message']}")


def on_connect(client, userdata, flags, reason_code, properties):
    """S'abonne aux topics du Pi dès que le broker accepte la connexion."""
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
    client.subscribe(config.TOPIC_CONFIGURATION, qos=1)
    client.subscribe(config.TOPIC_RESULTAT, qos=1)


def on_message(client, userdata, msg):
    """Écrit chaque message reçu dans le fichier JSONL, puis dans MongoDB selon son topic."""
    try:
        donnees = json.loads(msg.payload.decode("utf-8"))
        # Le Pi envoie l'heure UTC d'acquisition en texte ISO : on la convertit
        # en date pour MongoDB (comme dans la démo du cours)
        horodatage = datetime.fromisoformat(donnees["horodatage"]).astimezone(timezone.utc)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        print(f"Message invalide ignoré : {msg.payload}")
        return

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
        elif msg.topic == config.TOPIC_CONFIGURATION:
            enregistrer_configuration(donnees, horodatage, msg.retain)
        elif msg.topic == config.TOPIC_RESULTAT:
            enregistrer_resultat(donnees, horodatage)
    except KeyError as erreur:
        print(f"Champ manquant {erreur}, message ignoré : {donnees}")
    except PyMongoError as erreur:
        # Pour éviter qu'une panne d'Atlas arrête tout le service
        print(f"Erreur MongoDB, message perdu : {erreur}")


if __name__ == "__main__":
    if not config.MONGODB_URI or not config.MONGODB_BASE:
        raise RuntimeError("Variables d'environnement manquantes : MONGODB_URI et MONGODB_BASE")

    # tz_aware=True : les dates lues de MongoDB sont en UTC avec leur fuseau
    client_mongo = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    db = client_mongo[config.MONGODB_BASE]
    preparer_base(db)
    FICHIER_DONNEES.parent.mkdir(exist_ok=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="ferixu-ingestion")
    client.on_connect = on_connect
    client.on_message = on_message
    # Connexion sécurisée au broker EMQX, comme dans la démo du cours
    client.username_pw_set(config.MQTT_UTILISATEUR, config.MQTT_MOT_DE_PASSE)
    client.tls_set(ca_certs=str(config.MQTT_CERTIFICAT_CA))

    client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)

    try:
        # On peut faire loop_forever (bloquante) car on ne fait rien d'autre après.
        client.loop_forever()
    except KeyboardInterrupt:
        print("Arrêt du service d'ingestion ...")
    finally:
        client.disconnect()
        client_mongo.close()
