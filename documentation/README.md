# Documentation du projet — Pousse / Ferixu

**Projet :** Système d’irrigation automatique pour plante en pot  
**Équipe :** Ferixu

- [Remise — Partie 1 (10 %), le 20 octobre 2026](remise_partie_1.md)
- [À faire au prochain cours : priorités et fonctions manquantes](todo_prochain_cours.md)
- [Inventaire du matériel : quantités, liens produits et statuts](inventaire_materiel.md)
- [Exigences fonctionnelles EF01 à EF24, états du feu et contrôles](exigences_fonctionnelles.md)

Ces documents décrivent le système prévu. L’état actuel de l’implémentation est présenté dans le [README du dépôt](../README.md).

## Responsabilités selon le schéma de remise

| Composant | Exemple de la prof | Structure Ferixu | Responsabilité prévue |
| --- | --- | --- | --- |
| Raspberry Pi | `demo-broker-thread` | `ferixuBackend/main.py`, `capteurs/`, `controleur.py`, `actionneurs/`, `publication_donnees/`, `reception_donnees/` | Acquiert les mesures, décide des actions, commande la pompe et le feu, publie les mesures et reçoit la configuration via EMQX. |
| EMQX | `demo-broker-thread` | Configuration MQTT des applications | Relaie les messages entre le Pi, l’ingestion et NiceGUI. |
| Service d’ingestion | `demo-broker-thread/ingestion` | `ferixuBackend/ingestion/service_ingestion.py` | Tourne sur un serveur, reçoit les mesures et événements via EMQX et les enregistre dans MongoDB Atlas. |
| FastAPI | `api-iot` | [`ferixuFastApi`](../../ferixuFastApi/README.md), avec `main_api.py`, `models/`, `base_donnees/` et `publication_donnees/` | Fournit à NiceGUI les historiques lus dans MongoDB Atlas. |
| NiceGUI | `client-iot` | [`ferixuFront`](../../ferixuFront/README.md), avec `main.py`, `layout.py`, `pages/`, `composants/` et `models/` | Charge les historiques auprès de FastAPI. Écoute les mises à jour et envoie les commandes au Pi via EMQX. |

Comme dans `api-iot`, FastAPI dispose déjà de routes qui relaient les commandes vers EMQX. Dans le code NiceGUI actuel, les pages lisent FastAPI à l’ouverture. L’abonnement au direct et le branchement des commandes côté client restent à faire pour compléter le circuit du diagramme.

[Schéma de la remise finale, page 2](Remise%20finale%20du%20projet.docx.pdf)

## Composants et utilité

| Nº | Composant | Type | Utilité |
| --- | --- | --- | --- |
| 1 | STEMMA Soil Sensor (#4026) | Capteur | Mesure l’humidité et la température du sol |
| 2 | BH1750 (#4681) | Capteur | Mesure la luminosité ambiante en lux |
| 3 | Raspberry Pi 4 | Contrôleur | Lit les capteurs, applique les règles et contrôle les actionneurs |
| 4 | Feu tricolore ARD-625 | Actionneur / indicateur | Affiche l’état du système : vert, jaune ou rouge |
| 5 | Pompe submersible 3 V (#4547) | Actionneur | Arrose automatiquement la plante |
| 6 | Interrupteur à flotteur SENS-112-200 | Capteur | Détecte si le réservoir contient suffisamment d’eau |
| 7 | Relais STEMMA (#4409) | Actionneur / interface | Permet au Raspberry Pi d’allumer et d’éteindre la pompe |
| Optionnel | Buzzer passif | Actionneur | Produit une alerte sonore lorsque le réservoir est vide ou lorsqu’une intervention est nécessaire |

La différence de référence du flotteur est signalée dans l’[inventaire](inventaire_materiel.md).

## Plante et paramètres choisis

| Élément | Choix |
| --- | --- |
| Plante | Basilic |
| Besoin principal | Eau et lumière |
| Humidité minimale choisie | 30 % |
| Mesure de l’humidité | Toutes les 10 minutes |
| Arrosage automatique | Pompe activée pendant 3 secondes sous 30 %, sous réserve des conditions de sécurité EF06 à EF09 |
| Luminosité | Mesurée avec le BH1750 en lux |

Les tableaux peuvent être copiés depuis l’aperçu Markdown ou GitHub dans Google Docs.

## Schéma des données

MongoDB stocke les horodatages en dates BSON UTC. Les exemples JSON les représentent
en ISO 8601 avec le suffixe `Z`. Dans les historiques, `plante_id` correspond à
`Plante.id`. MongoDB ajoute automatiquement un champ `_id` à ses documents.

### Lumiere

Série temporelle des mesures en lux qui alimentent le graphique de luminosité.

```json
{
  "lux": 0,
  "horodatage": "2026-01-01T03:20:32Z",
  "plante_id": 1
}
```

### Temperature_humidite

Série temporelle des mesures du sol qui alimentent le graphique de température
et d’humidité. `temperature_c` est en degrés Celsius, `humidite_brut` est la
valeur brute du capteur et `humidite_pct` le pourcentage calibré par le Pi
(`null` sans calibration).

```json
{
  "temperature_c": 0,
  "humidite_brut": 0,
  "humidite_pct": 0,
  "horodatage": "2026-01-01T03:20:32Z",
  "plante_id": 1
}
```

### Arrosage

Collection classique qui conserve les démarrages de la pompe. `auto` vaut
`true` pour un arrosage automatique et `false` pour une commande manuelle ou
un test; `mode` précise `automatique`, `manuel` ou `test`. L’API compte les
événements de la plante sur les 24 dernières heures.

```json
{
  "auto": true,
  "mode": "automatique",
  "horodatage": "2026-01-01T03:20:32Z",
  "plante_id": 1
}
```

### Evenement

Collection classique de l’historique des activités. `type` vaut `configuration`
(paramètres appliqués par le Pi, reçus sur `ferixu/configuration`) ou `commande`
(résultat d’une commande manuelle, reçu sur `ferixu/resultat`).

```json
{
  "type": "configuration",
  "details": {"humidite_min": 30, "lux_min": 10000, "duree_arrosage": 3, "automatique": true},
  "horodatage": "2026-01-01T03:20:32Z",
  "plante_id": 1
}
```

### Utilisateur

Collection classique prévue pour l’authentification. Le service d’ingestion ne
la crée pas actuellement. Le champ `passwd` est prévu pour une empreinte de
mot de passe. L’authentification reste à implémenter.

```json
{
  "id": 1,
  "nom": "Marc",
  "passwd": "<empreinte_du_mot_de_passe>"
}
```

### Plante

Collection classique qui conserve les dernières mesures, l’état du réservoir,
le dernier arrosage, les seuils et le propriétaire. `utilisateur_id` correspond à
`Utilisateur.id` et vaut `null` jusqu’à l’association. L’intervalle minimal de
l’arrosage automatique est exprimé en minutes, le seuil d’humidité en pourcentage
et le seuil de luminosité en lux.

L’exemple montre la réponse de l’API. L’API y ajoute `arrosages_en_24h` en
interrogeant `Arrosage` au moment de la lecture.

```json
{
  "id": 1,
  "nom": "Daniel",
  "temperature_c": 0,
  "humidite_brut": 0,
  "eau_vide": true,
  "lux": 0,
  "dernier_arrosage": "2026-01-01T03:20:32Z",
  "arrosages_en_24h": 3,
  "horodatage": "2026-01-01T03:20:32Z",
  "intervalle_arrosage": 30,
  "seuil_humidite": 30,
  "seuil_luminosite": 10000,
  "utilisateur_id": 1
}
```

### Sources des pages

| Page | Données | Route API |
| --- | --- | --- |
| Accueil | `Plante` | `GET /api/plantes/{id}` |
| Graphiques | `Temperature_humidite` et `Lumiere` | `GET /api/plantes/{id}/temperature-humidite` et `GET /api/plantes/{id}/lumiere` |
| Paramètres | `Plante` | `GET /api/plantes/{id}` |

La [procédure de démarrage de l’ingestion](../mongodb/README.md) décrit la
configuration de MongoDB. Le [bilan des exigences](exigences_fonctionnelles.md#couverture-actuelle)
indique ce qui est en place et ce qui reste à vérifier ou à réaliser.
