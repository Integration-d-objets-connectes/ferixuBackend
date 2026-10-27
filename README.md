# Ferixu

**Auteurs : Éric et Félix Lachapelle** — Système d’irrigation sur Raspberry Pi 4.

Le backend lit le sol, la lumière et le réservoir, applique les règles d’arrosage et commande le feu. Les mesures sont horodatées en UTC, transmises par MQTT et enregistrées en JSONL. Aucune interface NiceGUI n’est incluse dans ce dépôt. MQTTX n’est pas nécessaire.

## Structure simple

Structure inspirée de la [démo du cours](https://github.com/5P0-Integration-d-objets-connectes/demo-broker-thread) et des [notes sur les threads](https://cours-5.gitbook.io/420-5p0-integration-dobjets-connectes/iot/exemple-utilisationn-threads) :

- `main.py` : lecture des capteurs, traitement des commandes et décision dans le thread principal; publication dans un thread séparé avec `Lock` et `Event`.
- `controleur.py` : règles d’arrosage, couleur du feu, cumul lumineux et paramètres persistants.
- `capteurs/`, `actionneurs/` : pilotes du matériel.
- `publication_donnees/` : connexion, publication et réception des commandes MQTT. Le callback réseau ajoute les commandes à une file; il ne commande pas le matériel.
- `ingestion/service_ingestion.py` : réception et enregistrement dans `donnees/lectures_capteurs.jsonl`.

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
| Relais de la pompe | `GPIO_RELAIS = None` tant que la broche réelle n’est pas renseignée |

Définir `RELAIS_ACTIF_HAUT` selon le relais utilisé. Alimenter la pompe par le circuit de puissance commandé par le relais, pas par un GPIO.

Pour calibrer le sol : relever `humidite_brute` dans le sol de référence sec puis humide; inscrire ces valeurs dans `HUMIDITE_BRUTE_SEC` et `HUMIDITE_BRUTE_HUMIDE`. La conversion est linéaire, limitée à 0–100 %. Ce pourcentage est un indice relatif à ces deux références, pas une mesure volumétrique certifiée. Confirmer d’abord que le capteur alternatif de l’inventaire est compatible avec le pilote STEMMA/Seesaw.

## Installation sur Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip python3-lgpio mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
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

Dans deux terminaux depuis le projet :

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
# Observer sans MQTTX
mosquitto_sub -h localhost -t 'ferixu/#' -v
tail -f donnees/lectures_capteurs.jsonl
```

Arrêt par `Ctrl+C`. Les valeurs de configuration restent explicites dans `config.py` pour faciliter la lecture.

## Topics et commandes

| Topic | Contenu |
| --- | --- |
| `ferixu/eau` | `etat`, `vide`, `horodatage` |
| `ferixu/sol` | `temperature_c`, `humidite_brute`, `humidite_pct`, `horodatage` |
| `ferixu/lumiere` | `lux`, `horodatage` |
| `ferixu/statut` | Dernières mesures, erreurs, paramètres appliqués, couleur, cumuls et informations d’arrosage |
| `ferixu/commandes` | Commandes JSON reçues par le backend |
| `ferixu/resultat` | `id`, `succes`, `message`, `horodatage` après traitement d’une commande |

Chaque commande demande un `id` unique et un `horodatage` UTC récent (30 s maximum). Ne pas utiliser de message retained pour les commandes. Les doublons récents sont refusés. `succes` confirme le traitement/démarrage, pas la présence d’un débit d’eau mesuré.

Exemple Python, depuis l’environnement virtuel, pour activer le mode automatique :

```python
from datetime import datetime, timezone
from uuid import uuid4
import json
from paho.mqtt.publish import single

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
single("ferixu/commandes", json.dumps(commande), hostname="localhost", qos=1)
```

Actions disponibles : `arroser`, `tester_pompe`, `tester_feu`, `parametres`. Le test du feu enchaîne vert, jaune, rouge pendant une seconde chacun, puis reprend l’état calculé. Les modifications de paramètres s’appliquent aux décisions suivantes; elles ne recalculent pas les anciennes journées de lumière. Un arrosage automatique est évalué lors de chaque nouvelle lecture du sol.

## Vérification

La [documentation MongoDB](mongodb/README.md) regroupe le test de connexion
et les exemples d'insertion, de lecture et de collection time series.

```bash
python -m unittest discover -s tests -v
```

Les tests utilisent des GPIO simulés et des mesures contrôlées. Le câblage, la polarité du relais, la calibration et le fonctionnement réel restent à vérifier sur le Raspberry Pi : voir [la procédure](documentation/todo_prochain_cours.md).
