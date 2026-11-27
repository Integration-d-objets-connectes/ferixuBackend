# MongoDB dans Ferixu

Depuis la racine du projet, renseigner `MONGODB_URI`, `MONGODB_BASE` et
`PLANTE_ID` dans `.env`, à partir de `.env.example`. Lancer ensuite
`python -m ingestion.service_ingestion`. Le service demande MongoDB 5.0 ou
plus récent pour créer les séries temporelles.

| Collection | Données | Opérations |
| --- | --- | --- |
| `Lumiere` | Lux mesurés toutes les 60 secondes | Série temporelle, `db.Lumiere.insert_one(...)` |
| `Temperature_humidite` | Température, humidité brute et humidité en % du sol, mesurées toutes les 10 minutes | Série temporelle, `db.Temperature_humidite.insert_one(...)` |
| `Arrosage` | Événement publié au démarrage réussi de la pompe, avec les champs `auto` et `mode` | Collection classique, `db.Arrosage.insert_one(...)` |
| `Evenement` | Historique des activités : configurations appliquées et résultats des commandes | Collection classique, `db.Evenement.insert_one(...)` |
| `Plante` | Dernières mesures, état du réservoir, seuils, dernier arrosage, `intervalle_arrosage` (en minutes), `utilisateur_id` | Collection classique, `db.Plante.update_one(...)` |
| `Utilisateur` | `id`, `nom`, `passwd` (empreinte du mot de passe pour la future authentification) | Collection classique prévue pour l’authentification |

`preparer_base()` crée les séries temporelles manquantes avec
`horodatage` comme champ de date et `plante_id` comme champ de métadonnées.
Les écritures créent `Plante`, `Arrosage` et `Evenement` au besoin. La création de
`Utilisateur` et des index des collections classiques reste à mettre en place
dans le code. Le [schéma complet](../documentation/README.md#schéma-des-données)
décrit les champs et les routes qui les utilisent.
Une collection classique déjà présente continue de recevoir les mesures.
Pour utiliser une série temporelle avec le même nom, les données existantes
doivent être migrées vers une nouvelle collection.
[Documentation MongoDB](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-limitations/)

Les dates d’acquisition envoyées par le Pi sont enregistrées en UTC. Les seuils
appliqués sont copiés dans `Plante`. Le nombre
d'arrosages sur 24 h (`arrosages_en_24h`) est calculé par l'API à partir de `Arrosage`.
Une configuration retenue et rejouée à l’abonnement actualise `Plante`. L’historique des configurations reçoit les messages livrés en direct.
L’ingestion accepte aussi les anciens messages MQTT dont la clé est `humidite_brute`.
`utilisateur_id` est nul jusqu’à l’association de la plante à un utilisateur.

L’ingestion met à jour les champs qu’elle reçoit dans `Plante` et conserve
les autres champs, dont le nom et le propriétaire. Elle écrit aussi le
message dans `donnees/lectures_capteurs.jsonl` avant l’écriture MongoDB. Une
erreur MongoDB est affichée et le message est ignoré : le service continue.

## Lire les mesures récentes

```python
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo

from pymongo import MongoClient

import config

client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
db = client[config.MONGODB_BASE]

depuis = datetime.now(timezone.utc) - timedelta(minutes=10)
lectures = db.Lumiere.find(
    {"plante_id": config.PLANTE_ID, "horodatage": {"$gte": depuis}},
    {"_id": 0, "horodatage": 1, "lux": 1},
).sort("horodatage", 1)

for lecture in lectures:
    date = lecture["horodatage"].astimezone(ZoneInfo(config.FUSEAU_HORAIRE))
    print(date.strftime("%Y-%m-%d %H:%M"), lecture["lux"], "lux")

client.close()
```

## Vérifier le projet

- Lancer `python -m ingestion.service_ingestion`. Le message « Connecté au broker MQTT » confirme la connexion. Vérifier ensuite l’arrivée des mesures et des arrosages dans MongoDB.

## Données de démonstration

Avec une instance MongoDB locale en cours d’exécution, lancer cette commande
depuis la racine du backend.

```bash
mongosh "mongodb://127.0.0.1:27017" --file mongodb/donnees_test.js
```

Le script remplit la base `ferixu_demo` avec la plante `1` (Basilic de
démonstration), 12 heures de mesures simulées, deux arrosages récents, une
configuration appliquée et un résultat de commande. Une nouvelle exécution
ajoute les horodatages de mesures manquants et actualise les exemples
d’arrosage et d’activité.

Pour lire ces données dans l’application, lancer `ferixuFastApi` avec
`MONGODB_URI=mongodb://127.0.0.1:27017` et `MONGODB_BASE=ferixu_demo`. L’accueil
peut lire la plante `1` et les graphiques peuvent afficher son historique de
la dernière journée. Ces données sont lisibles sans Raspberry Pi.
