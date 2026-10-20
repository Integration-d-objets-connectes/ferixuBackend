# Ferixu

**Auteurs : Eric et Félix** — Projet IoT, partie 1.

Surveillance d’une plante sur Raspberry Pi : acquisition horodatée, transmission MQTT et enregistrement dans un fichier JSONL.

## Fonctionnement actuel

- **Flotteur** : niveau d’eau toutes les 5 s pour la démo (cible : 600 s), GPIO BCM 16.
- **BH1750** : luminosité toutes les 60 s, connexion I²C.
- **Feu ARD-625** : rouge si eau insuffisante, vert sinon; GPIO BCM rouge 23, jaune 22, vert 27.
- **MQTT** : publication toutes les 5 s sur `ferixu/eau` et `ferixu/lumiere`, broker `localhost:1883`.
- **À compléter** : intégration du capteur de sol, commande de la pompe et logique complète d’arrosage.

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

Depuis le dossier du projet, dans deux terminaux distincts :

```bash
# Terminal 1 : réception et enregistrement
source .venv/bin/activate
python -m ingestion.service_ingestion
```

```bash
# Terminal 2 : acquisition, publication et feu
source .venv/bin/activate
python main.py
```

Observer les messages ou les données enregistrées dans un autre terminal :

```bash
mosquitto_sub -h localhost -t 'ferixu/#' -v
tail -f donnees/lectures_capteurs.jsonl
```

Configuration dans `config.py`. Arrêt avec `Ctrl+C`.

## Répartition du travail — Partie 1

| Responsable | Travail réalisé | Fichiers principaux |
| --- | --- | --- |
| Félix Lachapelle | Classe abstraite commune aux capteurs; lecture de la luminosité avec le BH1750 et horodatage des mesures; publication des mesures vers le broker MQTT. | `capteurs/capteur.py`, `capteurs/capteur_bh1750.py`, `publication_donnees/publicateur_mqtt.py` |
| Éric Lachapelle | Lecture du niveau d’eau avec le flotteur et horodatage des mesures; commande du feu tricolore; abonnement aux topics MQTT et enregistrement des mesures reçues dans un fichier JSONL. | `capteurs/flotteur.py`, `actionneurs/feu_tricolore.py`, `ingestion/service_ingestion.py` |
| Félix et Éric Lachapelle | Assemblage du programme principal, configuration commune et organisation des paquets; script d’essai MQTT; préparation du pilote du capteur de sol, dont l’intégration reste à compléter. | `main.py`, `config.py`, fichiers `__init__.py`, `publication_donnees/test_mqttx.py`, `capteurs/capteur_sol.py` |

La commande de la pompe et la logique complète d’arrosage restent à réaliser et ne font pas partie des fonctionnalités terminées de cette remise.
