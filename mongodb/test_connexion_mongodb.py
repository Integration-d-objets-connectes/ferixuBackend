"""Lister les bases et, au besoin, tester une insertion dans une collection."""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure

import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base existante dans laquelle effectuer le test")
    args = parser.parse_args()

    if not config.MONGODB_URI:
        print("Renseignez MONGODB_URI dans le fichier .env avant de lancer le test.")
        return 1

    try:
        with MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000) as client:
            client.admin.command("ping")
            print("Connexion réussie")
            bases = client.list_database_names()
            print("Bases de données :", bases)

            if args.base:
                if args.base not in bases:
                    print("Base introuvable dans la liste :", args.base)
                    return 1
                db = client[args.base]
                nom_collection = f"test_connexion_{uuid4().hex}"
                collection = db.create_collection(nom_collection)
                print(f"Collection créée : {args.base}.{nom_collection}")
                resultat = collection.insert_one({
                    "message": "Test de connexion MongoDB",
                    "horodatage": datetime.now(timezone.utc),
                })
                document = collection.find_one({"_id": resultat.inserted_id})
                if document is None:
                    print("Le document inséré n'a pas pu être retrouvé.")
                    return 1
                print("Document vérifié :", document)
    except OperationFailure as e:
        print("Erreur d'authentification ou de droits :", e)
        return 1
    except (ConfigurationError, ConnectionFailure) as e:
        print("Cluster injoignable (adresse IP autorisée dans Network Access ?) :", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
