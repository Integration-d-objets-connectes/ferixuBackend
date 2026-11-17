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
MONGODB_COLLECTION_LUMIERE=Lumiere
MONGODB_COLLECTION_TEMPERATURE_HUMIDITE=Temperature_humidite
MONGODB_COLLECTION_ARROSAGE=Arrosage
MONGODB_COLLECTION_PLANTE=Plante
PLANTE_ID=1
```

Le service `python -m ingestion.service_ingestion` enregistre les messages MQTT
valides avec la fonction `enregistrer_donnees(topic, mesure)`, ainsi que dans
`donnees/lectures_capteurs.jsonl` :

| Topic MQTT | Enregistrement MongoDB |
| --- | --- |
| `ferixu/lumiere` | Historique `Lumiere` et dernière valeur de `lux` dans `Plante` |
| `ferixu/sol` | Historique `Temperature_humidite` et dernières valeurs de `temperature_c` et `humidite_brut` dans `Plante` |
| `ferixu/eau` | Mise à jour de `eau_vide` dans `Plante` |
| `ferixu/arrosage` | Historique `Arrosage` et mise à jour de `dernier_arrosage` dans `Plante` |
| `ferixu/statut` | Seuils appliqués `seuil_humidite` et `seuil_luminosite` dans `Plante` |

`MONGODB_URI` et `MONGODB_BASE` sont obligatoires au démarrage. Les noms des quatre
collections sont modifiables avec les variables ci-dessus. La connexion et les
références aux collections sont initialisées directement avant les callbacks.
`initialiser_indexes()` crée les index au démarrage; MongoDB crée les collections
automatiquement pendant cette opération ou lors d'une première insertion.
Cette initialisation peut être répétée et n'efface pas les données.

Le Raspberry Pi ajoute `plante_id` aux messages qu'il publie à partir de
`PLANTE_ID`. Pour un message plus ancien sans identifiant, l'ingestion utilise
la même valeur de configuration. Les historiques contiennent `plante_id` et
`horodatage`, plus `lux`, le couple `temperature_c` / `humidite_brut`, ou `auto`
selon la collection. Le champ MQTT `humidite_brute` devient `humidite_brut` dans
MongoDB. Les dates sont des dates BSON UTC, conservées à la milliseconde;
utiliser par exemple `2026-11-10T12:00:00+00:00` dans un message MQTT.

Un index unique sur `(plante_id, horodatage)` évite de compter deux fois le même
message d'historique. `Plante` possède un index unique sur `id`; les mises à jour
conservent ses autres champs. Les valeurs de capteurs absentes ne sont pas
remplacées par des zéros. Un arrosage est publié après le démarrage réussi de la
pompe : `auto` vaut `true` pour le mode automatique et `false` pour le manuel ou
le test. Cela confirme le démarrage du relais, pas un débit d'eau mesuré.

L'ingestion ne gère pas les comptes `Utilisateur`, le nom ou le propriétaire de
la plante (`utilisateur_id`), ni `intervalle_arrosage`. Ces champs appartiennent
à la future API. Le seuil d'humidité publié par le contrôleur est un pourcentage
(0–100), tandis que `humidite_brut` reste une mesure brute; `seuil_luminosite`
est en lux. `arrosages_en_24h` doit être calculé par l'API à partir de `Arrosage`
au moment de la lecture : il n'est pas stocké par l'ingestion.

Les anciennes variables `MONGODB_COLLECTION`, `MONGODB_COLLECTION_EAU`,
`MONGODB_COLLECTION_SOL`, `MONGODB_COLLECTION_STATUT` et
`MONGODB_COLLECTION_RESULTAT` ne sont plus utilisées. Les anciens documents
restent en place; aucune migration automatique n'est effectuée.
Les topics inconnus, notamment les résultats de commandes destinés à l'interface,
ne sont pas ingérés.
Une erreur d'insertion est affichée sans interrompre la réception MQTT;
les insertions échouées ne sont pas rejouées automatiquement.

`config.py` charge ces variables et définit déjà `FUSEAU_LOCAL` avec
`ZoneInfo("America/Toronto")`.

Tester la connexion sans insérer de document :

```bash
python -m mongodb.test_connexion_mongodb
```

## Tester l'ingestion sans serveur

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Les tests utilisent `mongomock` en mémoire, sans broker MQTT, matériel ni accès
à la base réelle. Ils vérifient les documents, les doublons, les relations par
identifiant et la conservation des champs gérés par l'API. Le déploiement réel
reste à vérifier avec MongoDB et le Raspberry Pi.

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
