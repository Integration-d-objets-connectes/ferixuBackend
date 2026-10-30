# Maquette Pousse — Ferixu

La maquette comprend trois pages : vue d’ensemble (mesures, état de la plante, lumière reçue et arrosage), historique (graphique linéaire humidité/température et graphique à bandes de la luminosité) et paramètres (seuils, arrosage automatique, activation du feu tricolore et arrosage manuel). Elle présente les éléments prévus dans `documentation/exigences_fonctionnelles.md`.

## Comment lancer la maquette

### Option 1 : Ouvrir directement dans le navigateur
Double-cliquer sur `index.html` ou l'ouvrir via votre navigateur :
- **macOS** : `open maquette/index.html`
- **Linux** : `xdg-open maquette/index.html`
- **Windows** : `start maquette/index.html`

### Option 2 : Lancer avec un serveur HTTP local (recommandé)
Depuis le dossier `maquette` :
```bash
cd maquette
python3 -m http.server 8000
```
Puis ouvrir l'adresse [http://localhost:8000](http://localhost:8000) dans un navigateur.

---
La maquette n’est pas connectée au backend ni au matériel : les valeurs affichées sont des exemples réalistes et les boutons n’ont aucun effet.

