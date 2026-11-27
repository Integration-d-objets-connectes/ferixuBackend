# MongoDB dans Ferixu

Depuis la racine du projet, renseigner `MONGODB_URI`, `MONGODB_BASE` et
`PLANTE_ID` dans `.env`, à partir de `.env.example`. Lancer ensuite
`python -m ingestion.service_ingestion`. Le service demande MongoDB 5.0 ou
plus récent pour créer les séries temporelles.

| Collection | Données | Opérations |
| --- | --- | --- |
| `Lumiere` | Lux mesurés toutes les 60 secondes | Série temporelle, `db.Lumiere.insert_one(...)` |
| `Temperature_humidite` | Température et humidité brute du sol, mesurées toutes les 10 minutes | Série temporelle, `db.Temperature_humidite.insert_one(...)` |
| `Arrosage` | Événement publié au démarrage réussi de la pompe : `auto`, `mode`, `duree` | Collection classique, `db.Arrosage.insert_one(...)` |
| `evenements` | Activités : `etat` (changement de couleur du feu), `configuration` (appliquée par le Pi), `commande` (résultat) avec `details` | Collection classique, `db.evenements.insert_one(...)` |
| `Plante` | État courant : dernières mesures, `humidite_pct`, `couleur`, configuration appliquée, dernier arrosage, `prochain_auto` | Collection classique, `db.Plante.update_one(...)` |

`preparer_base()` crée les séries temporelles manquantes avec
`horodatage` comme champ de date et `plante_id` comme champ de métadonnées.
Une collection classique déjà présente continue de recevoir les mesures.
Pour utiliser une série temporelle avec le même nom, les données existantes
doivent être migrées vers une nouvelle collection.
[Documentation MongoDB](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-limitations/)

Les dates sont enregistrées en UTC; c'est l'heure d'acquisition envoyée par le Pi,
pas l'heure de réception. Une configuration reçue en message retenu (déjà
historisée) met à jour `Plante` sans créer de nouvel événement. Le nombre
d'arrosages sur 24 h est calculé par l'API à partir de `Arrosage`. Le champ MQTT `humidite_brute`
devient `humidite_brut` dans MongoDB.

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

- Lancer `python -m ingestion.service_ingestion` : le message « Connecté au broker MQTT » confirme la connexion, et les collections sont créées dans MongoDB.
