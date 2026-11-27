# @author Éric et Felix

"""Reçoit les messages MQTT du Pi et alimente les collections de l’application.

Les champs stockés sont décrits dans documentation/README.md.
"""

import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config

FICHIER_DONNEES = config.RACINE / "donnees" / "lectures_capteurs.jsonl"
# Nom donné à la plante à la création de son document (voir documentation/README.md)
NOM_PLANTE = "Basilic"
PLANTE_INITIALE = {
    "nom": NOM_PLANTE,
    "intervalle_arrosage": 30,  # Délai minimal en minutes (EF08).
    "utilisateur_id": None,
}


# 1. Préparer les séries temporelles


def preparer_base(db: Database) -> None:
    """Crée les séries temporelles Lumiere et Temperature_humidite si elles sont absentes.

    Les deux séries utilisent horodatage comme date et plante_id comme métadonnée.
    Les collections déjà présentes sont conservées.

    Args:
        db: Base MongoDB configurée pour le projet.
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


# 2. Recevoir les messages MQTT et les acheminer


def on_connect(client, userdata, flags, reason_code, properties):
    """Abonne le service aux six topics du Pi après chaque connexion au broker."""
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


def on_message(client, userdata, msg):
    """Décode le JSON et convertit la clé horodatage du message en date UTC.

    Ajoute le message au fichier JSONL avant de lire les autres clés requises
    par le topic. Chaque case indique le traitement appliqué dans MongoDB.

    Args:
        client: Client MQTT fourni par Paho.
        userdata: Données utilisateur du client MQTT.
        msg: Message Paho contenant topic et payload JSON en UTF-8.
    """
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
        match msg.topic:
            case config.TOPIC_LUMIERE:
                enregistrer_lumiere(donnees, horodatage)
            case config.TOPIC_SOL:
                enregistrer_sol(donnees, horodatage)
            case config.TOPIC_EAU:
                enregistrer_eau(donnees, horodatage)
            case config.TOPIC_ARROSAGE:
                enregistrer_arrosage(donnees, horodatage)
            case config.TOPIC_STATUT:
                # Dans le statut, les seuils sont regroupés sous parametres.
                enregistrer_configuration(
                    donnees["plante_id"], donnees["parametres"], horodatage
                )
            case config.TOPIC_CONFIGURATION:
                # Dans le message de configuration, les seuils sont à la racine.
                enregistrer_configuration(donnees["plante_id"], donnees, horodatage)
    except KeyError as erreur:
        print(f"Champ manquant {erreur}, message ignoré : {donnees}")
    except PyMongoError as erreur:
        # Pour éviter qu'une panne d'Atlas arrête tout le service
        print(f"Erreur MongoDB, message perdu : {erreur}")


# 3. Écrire les données dans MongoDB, dans l’ordre des topics traités


def enregistrer_lumiere(donnees: dict, horodatage: datetime) -> None:
    """Ajoute une mesure horodatée à la série temporelle Lumiere pour le graphique (EF20).

    Remplace ensuite le champ lux dans Plante pour l’accueil (EF18).

    Args:
        donnees: Message MQTT avec plante_id (entier) et lux (nombre en lux).
        horodatage: Date de la mesure, déjà convertie en UTC.
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
    """Ajoute une mesure horodatée à la série temporelle Temperature_humidite (EF19).

    Remplace ensuite temperature_c et humidite_brut dans Plante pour l’accueil (EF18).

    Args:
        donnees: Message MQTT avec les clés suivantes.
            plante_id (int): Identifiant correspondant à Plante.id.
            temperature_c (float): Température du sol en degrés Celsius.
            humidite_brut (float): Valeur brute du capteur. L’ancienne clé
                humidite_brute est acceptée si humidite_brut est absente.
        horodatage: Date de la mesure, déjà convertie en UTC.
    """

    if "humidite_brut" in donnees:
        humidite_brut = donnees["humidite_brut"]
    else:
        # Les anciennes versions du Pi envoient humidite_brute.
        humidite_brut = donnees["humidite_brute"]

    plante_id = donnees["plante_id"]
    temperature_c = donnees["temperature_c"]
    champs = {
        "temperature_c": temperature_c,
        "humidite_brut": humidite_brut,
    }
    db.Temperature_humidite.insert_one(
        {"horodatage": horodatage, "plante_id": plante_id, **champs}
    )
    mettre_a_jour_plante(plante_id, champs, horodatage)
    print(f"[{horodatage}] Sol : {temperature_c} °C, humidité {humidite_brut}")


def enregistrer_eau(donnees: dict, horodatage: datetime) -> None:
    """Remplace eau_vide dans Plante pour afficher l’état du réservoir à l’accueil (EF18).

    Args:
        donnees: Message MQTT avec plante_id (entier) et vide (booléen).
            vide vaut True quand le niveau d’eau est insuffisant.
        horodatage: Date de la lecture du flotteur, déjà convertie en UTC.
    """

    mettre_a_jour_plante(donnees["plante_id"], {"eau_vide": donnees["vide"]}, horodatage)
    print(f"[{horodatage}] Réservoir vide : {donnees['vide']}")


def enregistrer_arrosage(donnees: dict, horodatage: datetime) -> None:
    """Ajoute un document à la collection Arrosage, que l’API compte sur 24 h (EF23).

    Avance dernier_arrosage dans Plante seulement si l’événement est plus récent.

    Args:
        donnees: Message MQTT avec plante_id (entier) et auto (booléen).
            auto vaut False pour un arrosage manuel ou un test de pompe.
        horodatage: Date du démarrage de la pompe, déjà convertie en UTC.
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
        {
            "$max": {"dernier_arrosage": horodatage, "horodatage": horodatage},
            "$setOnInsert": PLANTE_INITIALE,
        },
        upsert=True,
    )
    print(f"[{horodatage}] Arrosage (auto : {donnees['auto']})")


def enregistrer_configuration(plante_id: int, parametres: dict, horodatage: datetime) -> None:
    """Remplace seuil_humidite et seuil_luminosite dans Plante pour la page Paramètres (EF24).

    Les seuils viennent du statut périodique du Pi ou du message de configuration appliquée.

    Args:
        plante_id: Identifiant correspondant à Plante.id.
        parametres: Dictionnaire avec humidite_min (pourcentage) et lux_min (lux).
        horodatage: Date du message de statut ou de configuration en UTC.
    """
    mettre_a_jour_plante(
        plante_id,
        {
            "seuil_humidite": parametres["humidite_min"],
            "seuil_luminosite": parametres["lux_min"],
        },
        horodatage,
    )


def mettre_a_jour_plante(plante_id: int, champs: dict, horodatage: datetime) -> None:
    """Remplace les champs reçus dans Plante et conserve l’horodatage le plus récent.

    Lors de la première écriture pour cet identifiant, initialise aussi le nom,
    l’intervalle d’arrosage et le champ utilisateur_id.

    Args:
        plante_id: Identifiant du document Plante à mettre à jour ou à créer.
        champs: Paires champ-valeur à remplacer dans le document avec MongoDB $set.
        horodatage: Date UTC du message, comparée à celle déjà stockée avec $max.
    """

    db.Plante.update_one(
        {"id": plante_id},
        {
            "$set": champs,
            # $max : garde la date la plus récente
            "$max": {"horodatage": horodatage},
            # Seulement à la création du document (upsert)
            "$setOnInsert": PLANTE_INITIALE,
        },
        # Mettre à jour ou insérer s'il n'existe pas.
        upsert=True,
    )


# Point d’entrée du service

if __name__ == "__main__":
    if not config.MONGODB_URI or not config.MONGODB_BASE:
        raise RuntimeError("Variables d'environnement manquantes : MONGODB_URI et MONGODB_BASE")

    # tz_aware=True : les dates lues de MongoDB sont en UTC avec leur fuseau
    client_mongo = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    db = client_mongo[config.MONGODB_BASE]
    preparer_base(db)
    FICHIER_DONNEES.parent.mkdir(exist_ok=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ferixu-ingestion")
    client.on_connect = on_connect
    client.on_message = on_message
    # Connexion sécurisée au broker EMQX, comme dans la démo du cours
    client.username_pw_set(config.MQTT_UTILISATEUR, config.MQTT_MOT_DE_PASSE)
    client.tls_set(ca_certs=str(config.MQTT_CERTIFICAT_CA))

    client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)

    try:
        # La boucle MQTT appelle on_connect et on_message.
        client.loop_forever()
    except KeyboardInterrupt:
        print("Arrêt du service d'ingestion ...")
    finally:
        client.disconnect()
        client_mongo.close()
