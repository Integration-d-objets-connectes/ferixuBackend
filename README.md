# Ferixu — partie 1 du projet IoT

**Remise : 20 octobre 2026 (10 %)**  
**Auteurs : Éric et Félix Lachapelle**

## Objectif

Ferixu est un prototype de surveillance d’un réservoir et de la luminosité, destiné à évoluer vers un système d’arrosage automatisé. Cette première partie lit des capteurs, publie les mesures par MQTT et les conserve dans un fichier JSONL. Le feu tricolore indique l’état d’eau lu par le flotteur.

Le prototype ne réalise pas encore un cycle d’arrosage complet. Le capteur de sol existe dans le code, mais il n’est pas intégré au programme principal. La pompe est seulement représentée par un fichier vide. La logique actuelle allume le feu rouge si l’eau est insuffisante et le feu vert si elle est suffisante; le vert ne confirme donc pas que le sol a besoin d’eau ni qu’un arrosage a eu lieu. Le feu jaune n’est pas utilisé par cette logique.

## État et spécifications actuelles

| Élément | État dans le code |
| --- | --- |
| Flotteur du réservoir | Lecture d’un contact avec GPIO Zero; la mesure contient `etat`, `vide` et un horodatage UTC. Le code interprète le contact fermé comme un niveau insuffisant; le sens électrique doit être confirmé sur le montage. |
| BH1750 | Lecture de luminosité en lux sur I²C, avec horodatage UTC. Le programme principal tente une lecture toutes les 60 secondes. |
| STEMMA Soil Sensor | Une classe peut lire la température et une valeur brute d’humidité. Elle n’est pas appelée par `main.py`; il n’y a pas de calibration permettant de convertir la mesure brute en pourcentage ni de décision fondée sur le sol. |
| Feu ARD-625 | Sorties rouge, jaune et verte commandées par GPIO Zero. Le programme principal utilise le rouge pour eau insuffisante et le vert pour eau suffisante. |
| Pompe submersible 3 V (#4547) | Non pilotée : `actionneurs/pompe.py` est vide. Aucun relais, circuit de commande ou protocole de marche/arrêt n’est défini dans le code. |
| MQTT et persistance | Publication des mesures sur `ferixu/eau` et `ferixu/lumiere`; le service d’ingestion écoute ces sujets et ajoute les messages JSON au fichier `donnees/lectures_capteurs.jsonl`. |

Les broches sont exprimées en numérotation **BCM** dans `config.py` :

| Composant | Broche BCM |
| --- | ---: |
| Flotteur | 16 |
| Feu rouge | 23 |
| Feu jaune | 22 |
| Feu vert | 27 |

Ces affectations sont celles inscrites dans la configuration du projet; elles ne constituent pas une validation du câblage. Le fonctionnement du matériel et le sens du contact du flotteur restent à vérifier sur le Raspberry Pi.

Les périodes configurées actuellement sont :

- Flotteur : **5 s** pour la démonstration. Le commentaire EF05 du code indique une cible de **600 s (10 min)**; la période de démonstration est conservée temporairement dans la configuration.
- BH1750 : **60 s**, conformément à la période prévue pour la luminosité.
- Publication MQTT : **5 s**. Cette période est indépendante des périodes d’acquisition; les mesures acquises sont mises en attente puis publiées.

## Organisation

```text
.
├── actionneurs/          # Feu tricolore; pilote de pompe à compléter
├── capteurs/             # Classe abstraite Capteur et pilotes
├── donnees/               # Créé à l’exécution; historique JSONL
├── ingestion/             # Abonné MQTT et écriture du fichier de mesures
├── publication_donnees/   # Publicateur MQTT
├── config.py              # Broches, sujets et périodes
├── main.py                # Acquisition, commande du feu et publication
└── requirements.txt       # Dépendances Python
```

Les pilotes de capteurs suivent la classe abstraite `Capteur`, qui définit le nom, la période de lecture, la méthode `lire()` et une méthode de fermeture. Le programme principal utilise actuellement le flotteur et le BH1750; la classe du capteur de sol reste à intégrer.

## Préparation du Raspberry Pi

Sur Raspberry Pi OS, installer le support GPIO, le broker MQTT et les outils I²C :

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-lgpio mosquitto mosquitto-clients i2c-tools
sudo systemctl enable --now mosquitto
```

Activer I²C dans la configuration du Raspberry Pi (`sudo raspi-config`, puis **Interface Options > I2C**) et redémarrer si le système le demande. Le capteur BH1750 utilise le bus I²C. Vérifier le câblage et les broches sur le montage réel avant de lancer le programme.

Depuis le dossier du projet, créer un environnement virtuel qui voit les paquets système (dont `lgpio`), puis installer les dépendances Python :

```bash
cd ~/ferixuBackend
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Le dossier du projet peut être différent sur le Raspberry Pi; adapter le `cd` au chemin utilisé. Le broker configuré est local (`localhost:1883`).

## Démarrage et observation

Ouvrir des terminaux distincts sur le Raspberry Pi. Lancer d’abord l’ingestion, qui s’abonne aux deux sujets et crée le dossier de données à son démarrage :

```bash
source .venv/bin/activate
python -m ingestion.service_ingestion
```

Dans un deuxième terminal, démarrer les acquisitions et le publicateur :

```bash
cd ~/ferixuBackend
source .venv/bin/activate
python main.py
```

Pour observer les messages MQTT dans un troisième terminal :

```bash
mosquitto_sub -h localhost -t 'ferixu/#' -v
```

Les mesures reçues par le service d’ingestion sont ajoutées au fichier suivant. Pour suivre les nouvelles lignes :

```bash
tail -f donnees/lectures_capteurs.jsonl
```

Arrêter les processus avec `Ctrl+C`. Le programme principal tente alors de fermer les connexions et les ressources GPIO/I²C.

## Démonstration orale (10 à 15 minutes)

Répartition proposée entre les deux auteurs, à ajuster selon le temps accordé :

| Présentateur | Durée | Contenu |
| --- | ---: | --- |
| Éric | 5 à 7 min | Présenter l’objectif, les composants et le câblage prévu; expliquer la classe `Capteur` et montrer les lectures du flotteur et du BH1750. |
| Félix Lachapelle | 5 à 7 min | Montrer le feu rouge/vert selon l’état du réservoir, la publication MQTT et l’écriture JSONL; présenter les éléments qui restent à intégrer, notamment le capteur de sol et la pompe. |

La démonstration doit distinguer le comportement observé sur le montage des spécifications encore prévues. Aucune validation matérielle n’est affirmée par ce README.

Avant la présentation, les deux auteurs doivent tester ensemble toute la chaîne :

- Montrer la connexion SSH, le venv actif et les dépendances.
- Vérifier le montage, la polarité du flotteur et la détection I²C (`i2cdetect -y 1`).
- Observer une acquisition horodatée, sa publication, sa réception et une nouvelle ligne dans le fichier.
- Déplacer le flotteur pour montrer les deux couleurs; attendre la prochaine lecture de 5 s. Prévoir au moins 60 s pour observer une nouvelle lecture de lumière.
- Comparer les spécifications ci-dessus au document fonctionnel corrigé de l'équipe, absent de ce dossier. Confirmer en particulier que la règle du feu correspond à une condition prévue dans ce document.
- Vérifier les intervalles minimaux des modèles de capteurs utilisés dans leurs fiches matérielles.

Les vérifications logicielles locales (syntaxe, imports et cohérence des dépendances) ne remplacent pas cette démonstration sur le Pi.
