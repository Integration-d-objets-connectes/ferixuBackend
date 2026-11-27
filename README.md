# Ferixu

**Auteurs : Éric et Félix Lachapelle** — Système d’irrigation sur Raspberry Pi 4.

Le backend lit le sol, la lumière et le réservoir, applique les règles d’arrosage et commande le feu. Les mesures sont horodatées en UTC, transmises par MQTT et enregistrées en JSONL et dans MongoDB. Aucune interface NiceGUI n’est incluse dans ce dépôt. MQTTX n’est pas nécessaire.

## Structure du Raspberry Pi et de l’ingestion

Structure inspirée de la [démo du cours](https://github.com/5P0-Integration-d-objets-connectes/demo-broker-thread) et des [notes sur les threads](https://cours-5.gitbook.io/420-5p0-integration-dobjets-connectes/iot/exemple-utilisationn-threads) :

- `main.py` : initialise le Pi, fait tourner la boucle principale et démarre le thread de publication avec `Lock` et `Event`.
- `capteurs/acquisition.py` : planifie les lectures du sol, du réservoir et de la lumière avec les pilotes du dossier `capteurs/`.
- `controleur.py` : applique les règles d’arrosage et du feu, traite les commandes, cumule la lumière et conserve l’état local. Il utilise les pilotes du dossier `actionneurs/`.
- `models/` : modèle pydantic `Configuration`, validation des paramètres sur le Pi.
- `publication_donnees/` : connexion et publication MQTT (`PublicateurMQTT`).
- `reception_donnees/` : réception des commandes MQTT (`AbonneMQTT`). Le callback réseau ajoute les commandes à une file; il ne commande pas le matériel.
- `ingestion/service_ingestion.py` : réception, historiques MongoDB (`Lumiere`, `Temperature_humidite`, `Arrosage`), mise à jour de `Plante` et enregistrement dans `donnees/lectures_capteurs.jsonl`.

Le `main.py` de la prof lit directement un capteur. Ici, `Acquisition` gère deux échéances (sol et réservoir aux 600 s, lumière aux 60 s), ouvre le bus I²C partagé à la première lecture et retente l’initialisation après une erreur. Les pilotes restent dans `capteurs/` et les décisions dans `controleur.py`.

Les deux autres applications ont leur propre point d’entrée, environnement et README. Le [tableau des responsabilités](documentation/README.md#responsabilités-selon-le-schéma-de-remise) les associe aux exemples du cours et au diagramme de remise.

## Règles du backend

- Sol : température et humidité ensemble toutes les **600 s**. Sans calibration, publier la capacité brute et `humidite_pct: null`; aucun arrosage automatique à partir d’une humidité inconnue.
- BH1750 : lux toutes les **60 s**. Cumul quotidien des intervalles suffisamment lumineux (seuil par défaut : **10 000 lux**), avec historique des **7 derniers jours** dans le statut. Le jour est défini dans `America/Toronto`.
- Réservoir : lecture avec le sol, immédiatement avant/après un arrosage et pendant son exécution.
- Automatique : humidité **strictement sous 30 %**, mode automatique actif, sol récent et eau suffisante; durée **3 s maximum**, attente **30 min après la fin** du dernier automatique, au plus **6 automatiques sur 24 h glissantes**.
- Manuel et test : eau suffisante obligatoire, erreur de lecture = refus, durée **3 s maximum**. Ils ne sont pas soumis aux limites réservées aux automatiques.
- Pompe : inactive au démarrage, coupée à l’arrêt et sur perte d’eau. Une minuterie indépendante limite aussi sa durée si la boucle principale bloque.
- Feu : rouge prioritaire si humidité sous le seuil, eau insuffisante ou lumière quotidienne < 3,6 h; vert si humidité ≥ 40 %, lumière ≥ 6 h et eau suffisante; jaune dans les autres cas connus. Si les données nécessaires sont manquantes/périmées et qu’aucune condition rouge n’est connue, feu éteint et état `inconnu`.
- Paramètres, arrosages et cumuls conservés dans `donnees/etat.json`. Par défaut, **mode automatique désactivé**. Un redémarrage conserve les délais et compteurs.

Le cumul lumineux utilise la dernière mesure valide jusqu’à la suivante, au maximum pendant 90 s. Les interruptions plus longues et les périodes d’arrêt ne sont pas comptées. Les journées incomplètes ne constituent donc pas une mesure complète de l’exposition réelle.

Les [exigences EF01 à EF24 et leur couverture](documentation/exigences_fonctionnelles.md) précisent ce qui relève encore d’une future interface.

## Préparer le matériel

Configurer `config.py` avant les essais :

| Composant | Connexion configurée |
| --- | --- |
| Flotteur | GPIO BCM 16; contact fermé = eau insuffisante, à vérifier sur le montage |
| Feu rouge / jaune / vert | GPIO BCM 23 / 22 / 27 |
| BH1750 | Bus I²C |
| STEMMA Soil Sensor | Bus I²C, adresse `0x36` |
| Relais de la pompe | GPIO BCM 17 (`GPIO_RELAIS`); `None` désactive la pompe |

Définir `RELAIS_ACTIF_HAUT` selon le relais utilisé. Alimenter la pompe par le circuit de puissance commandé par le relais, pas par un GPIO.

Pour calibrer le sol : relever `humidite_brute` dans le sol de référence sec puis humide; inscrire ces valeurs dans `HUMIDITE_BRUTE_SEC` et `HUMIDITE_BRUTE_HUMIDE`. La conversion est linéaire, limitée à 0–100 %. Ce pourcentage est un indice relatif à ces deux références, pas une mesure volumétrique certifiée. Confirmer d’abord que le capteur alternatif de l’inventaire est compatible avec le pilote STEMMA/Seesaw.

## Installation sur Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip python3-lgpio
sudo raspi-config
```

Activer **Interface Options → I2C**, puis redémarrer si demandé.

```bash
git clone https://github.com/Integration-d-objets-connectes/ferixuBackend.git
cd ferixuBackend
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Lancement

Renseigner `MONGODB_URI`, `MONGODB_BASE` et `PLANTE_ID` dans `.env`, à partir de
`.env.example`, avant de lancer l'ingestion. Voir la [configuration MongoDB](mongodb/README.md).

Renseigner aussi le broker EMQX : `BROKER`, `PORT`, `USERNAME` et `PASSWORD`. Le certificat
`emqxsl-ca.crt` doit être à la racine du projet (connexion TLS, comme dans la démo du cours).

Pour un essai local, lancer l’ingestion puis la collecte dans deux terminaux. Pour le déploiement du diagramme, exécuter l’ingestion sur le serveur et lancer `main.py` sur le Raspberry Pi. Les deux processus utilisent le même broker EMQX.

```bash
# Terminal 1 : abonnement et enregistrement
source .venv/bin/activate
python -m ingestion.service_ingestion
```

```bash
# Terminal 2 : matériel et règles du backend
source .venv/bin/activate
python main.py
```

```bash
# Observer les données enregistrées
tail -f donnees/lectures_capteurs.jsonl
```

Arrêt par `Ctrl+C`. Les valeurs de configuration restent explicites dans `config.py` pour faciliter la lecture.

### Lancer la maquette Web (UI)

Pour visualiser la maquette de l'application :

- **Ouverture directe** : ouvrir `maquette/index.html` dans un navigateur (`open maquette/index.html` sur macOS).
- **Via serveur local Python** :
  ```bash
  cd maquette
  python3 -m http.server 8000
  ```
  Accéder ensuite à [http://localhost:8000](http://localhost:8000).


## Topics et commandes

| Topic | Contenu |
| --- | --- |
| `ferixu/eau` | `etat`, `vide`, `horodatage` |
| `ferixu/sol` | `temperature_c`, `humidite_brute`, `humidite_pct`, `horodatage` |
| `ferixu/lumiere` | `lux`, `horodatage` |
| `ferixu/statut` | Dernières mesures, erreurs, paramètres appliqués, couleur, cumuls et informations d’arrosage |
| `ferixu/commandes` | Commandes JSON reçues par le backend |
| `ferixu/resultat` | `id`, `action`, `succes`, `message`, `horodatage` après traitement d’une commande |
| `ferixu/arrosage` | `auto`, `mode` (automatique, manuel, test), `duree`, `horodatage` après le démarrage réussi de la pompe |
| `ferixu/configuration` | Configuration appliquée (`humidite_min`, `lux_min`, `duree_arrosage`, `automatique`), message retenu |

Les messages publiés par ce Raspberry Pi incluent aussi `plante_id`, défini par
`PLANTE_ID` dans `.env`. Le `horodatage` d'une mesure est celui de son acquisition;
l'ingestion l'enregistre tel quel en UTC. Les résultats de commandes, les configurations
appliquées et les changements de couleur du feu sont historisés dans la collection
`evenements`. Les commandes sont normalement envoyées par l'[API](../ferixuFastApi/README.md)
(`PUT /api/configuration`, `POST /api/commandes`).

Chaque commande demande un `id` unique et un `horodatage` UTC récent (30 s maximum). Ne pas utiliser de message retained pour les commandes. Les doublons récents sont refusés. `succes` confirme le traitement/démarrage, pas la présence d’un débit d’eau mesuré.

Exemple Python, depuis l’environnement virtuel, pour activer le mode automatique :

```python
from datetime import datetime, timezone
from uuid import uuid4
import json
from paho.mqtt.publish import single

import config

commande = {
    "id": uuid4().hex,
    "horodatage": datetime.now(timezone.utc).isoformat(),
    "action": "parametres",
    "parametres": {
        "automatique": True,
        "humidite_min": 30,
        "lux_min": 10000,
        "duree_arrosage": 3,
    },
}
single(
    "ferixu/commandes",
    json.dumps(commande),
    hostname=config.MQTT_HOTE,
    port=config.MQTT_PORT,
    auth={"username": config.MQTT_UTILISATEUR, "password": config.MQTT_MOT_DE_PASSE},
    tls={"ca_certs": str(config.MQTT_CERTIFICAT_CA)},
    qos=1,
)
```

Actions disponibles : `arroser`, `tester_pompe`, `tester_feu`, `parametres`. Le test du feu enchaîne vert, jaune, rouge pendant une seconde chacun, puis reprend l’état calculé. Les modifications de paramètres s’appliquent aux décisions suivantes; elles ne recalculent pas les anciennes journées de lumière. Un arrosage automatique est évalué lors de chaque nouvelle lecture du sol.

## Vérification

La documentation MongoDB décrit les collections de Ferixu, la vérification de la
connexion et la lecture des mesures récentes. [MongoDB dans Ferixu](mongodb/README.md)

Le câblage, la polarité du relais, la calibration et le fonctionnement réel restent à vérifier sur le Raspberry Pi : voir [la procédure](documentation/todo_prochain_cours.md).

## Tableau des tâches

Responsables tirés des mentions `@author` du code. À compléter par l’équipe.

| Tâche | Responsable |
| --- | --- |
| Classe abstraite `Capteur`, pilote BH1750 (`capteurs/capteur_bh1750.py`) | Félix Lachapelle |
| Pilote du sol STEMMA et calibration (`capteurs/capteur_sol.py`) | Félix Lachapelle, Éric |
| Flotteur (`capteurs/flotteur.py`) et feu tricolore (`actionneurs/feu_tricolore.py`) | Éric |
| Pompe et relais (`actionneurs/pompe.py`) | Félix Lachapelle, Éric |
| Acquisition périodique, règles d’arrosage et du feu, boucle principale (`capteurs/acquisition.py`, `controleur.py`, `main.py`) | Félix Lachapelle, Éric |
| Publication MQTT (`publication_donnees/`), réception MQTT (`reception_donnees/`), validation pydantic (`models/`) | Félix Lachapelle |
| Service d’ingestion MongoDB (`ingestion/service_ingestion.py`) | Éric, Félix Lachapelle |
| Configuration (`config.py`, `.env.example`) | Félix Lachapelle, Éric |

### Tâches confiées au coéquipier IA

| Demande | Fourni à l’IA | Résultat et corrections |
| --- | --- | --- |
| Aligner la structure du backend sur la démo du cours (`demo-broker-thread`) | Démo du cours, code du projet, `documentation/` | Ajout de `reception_donnees/AbonneMQTT` et de `models/Configuration`, connexion TLS à EMQX. Première version trop refactorisée : l’équipe a demandé de garder la logique, les commentaires et les auteurs d’origine. |
| Vérifier le projet selon la grille de la remise finale | `Remise finale du projet.docx.pdf` | Docstrings manquantes ajoutées, période du sol remise à 600 s (EF01), commentaires et README corrigés. |
| Alléger le point d’entrée du Pi (Codex) | `ExempleProf/demo-broker-thread/main.py`, `service_ingestion.py`, schéma et grille de la remise | Acquisition et décisions extraites de `main.py`. Sections et docstrings harmonisées. Les commandes JSON qui ne sont pas des objets sont ignorées. |
| Créer l’API FastAPI et adapter l’ingestion pour l’historique | Exemples du cours (`api-iot`, `client-iot`, `demo-broker-thread`), `Remise finale du projet.docx.pdf`, `documentation/`, code du backend et du front | API `ferixuFastApi` (historique MongoDB, configuration et commandes MQTT, tests). Ingestion : horodatage d’acquisition du Pi, `humidite_pct`, collection `evenements` (état, configuration, commandes). Pi : topic retenu `ferixu/configuration`, `mode`/`duree` des arrosages. À réviser par l’équipe. |
