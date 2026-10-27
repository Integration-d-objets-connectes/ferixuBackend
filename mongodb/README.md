# MongoDB

Exécuter les commandes depuis la racine du projet, dans l'environnement virtuel.

## Configuration et test de connexion

Installer les dépendances :

```bash
python -m pip install -r requirements.txt
```

Renseigner les variables dans le fichier `.env` (voir `.env.example`) :

```dotenv
MONGODB_URI=mongodb+srv://votre-utilisateur:votre-mot-de-passe@votre-cluster.mongodb.net/
MONGODB_BASE=db-demo
```

`config.py` charge ces variables et définit déjà `FUSEAU_LOCAL` avec
`ZoneInfo("America/Toronto")`.

Tester la connexion sans insérer de document :

```bash
python -m mongodb.test_connexion_mongodb
```

## Insérer et lire un document

`serverSelectionTimeoutMS=5000` limite à 5 secondes l'attente de sélection
d'un serveur, au lieu des 30 secondes par défaut.

`tz_aware=True` permet de relire les dates avec leur fuseau UTC, puis de les
convertir à l'heure locale pour l'affichage.

Exemple à exécuter depuis la racine du projet dans une session Python.
Chaque exécution insère un nouveau document de démonstration dans `evenements`.

```python
from datetime import datetime, timezone

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

import config

uri = config.MONGODB_URI

# Un seul client, réutilisé pour toutes les opérations et fermé à la sortie.
try:
    with MongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True) as client:
        client.admin.command("ping")
        print("Connexion réussie")
        db = client[config.MONGODB_BASE]

        db.evenements.insert_one(
            {
                "horodatage": datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc),
                "aquarium_id": "aquaveille-01",
                "type": "repas",
            }
        )

        dernier = db.evenements.find_one(
            {"aquarium_id": "aquaveille-01", "type": "repas"},
            sort=[("horodatage", -1)],
        )

        if dernier is not None:
            heure_utc = dernier["horodatage"]
            heure_locale = heure_utc.astimezone(config.FUSEAU_LOCAL)

            print("Enregistré en UTC  :", heure_utc.strftime("%Y-%m-%d %H:%M %Z"))
            print("Heure à Gatineau   :", heure_locale.strftime("%Y-%m-%d %H:%M %Z"))
            print(f"Dernier repas : {heure_locale.strftime('%H:%M')}")

except OperationFailure as e:
    print("Erreur d'authentification ou de droits :", e)
except ConnectionFailure as e:
    print("Cluster injoignable (adresse IP autorisée dans Network Access ?) :", e)
```

Dans Atlas, ouvrir **Data Explorer** et vérifier que la base `db-demo`
(ou le nom choisi dans `MONGODB_BASE`) contient la collection `evenements`
et le document inséré. Les noms `aquarium_id` et `repas` sont ceux de la démonstration.

## Créer une collection time series

Définir cette fonction, puis appeler `creer_collections(db)` à l'intérieur
du bloc `with MongoClient(...)`, après la sélection de la base.
Elle crée `lectures` uniquement si cette collection n'existe pas déjà.

```python
def creer_collections(db):
    """Crée les collections avec options, sans modifier celles déjà présentes."""
    if "lectures" not in db.list_collection_names():
        db.create_collection(
            "lectures",
            timeseries={
                "timeField": "horodatage",
                "metaField": "aquarium_id",
                "granularity": "minutes",
            },
            expireAfterSeconds=604800,  # 7 jours
        )
        print("Collection time series 'lectures' créée")
```

Le champ `horodatage` doit contenir une date BSON (un `datetime` Python lors
de l'insertion). MongoDB supprime les anciennes données en arrière-plan :
l'expiration n'est pas une suppression immédiate à la seconde près.
