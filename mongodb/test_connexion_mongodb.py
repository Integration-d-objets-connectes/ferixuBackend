"""Vérifier la connexion avec : python -m mongodb.test_connexion_mongodb."""

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

import config


def main():
    if not config.MONGODB_URI:
        print("Renseignez MONGODB_URI dans le fichier .env avant de lancer le test.")
        return 1

    try:
        with MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000) as client:
            client.admin.command("ping")
            print("Connexion réussie")
    except OperationFailure as e:
        print("Erreur d'authentification ou de droits :", e)
        return 1
    except ConnectionFailure as e:
        print("Cluster injoignable (adresse IP autorisée dans Network Access ?) :", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
