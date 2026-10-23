# Maquette Pousse — Ferixu

Ouvrir `index.html` dans un navigateur. Aucun outil de compilation ni installation nécessaire. Les polices Google sont facultatives : une police système prend le relais hors ligne.

Quatre pages HTML reliées :
- **Vue d’ensemble** : dernières lectures, état du feu, réservoir et objectif quotidien de lumière (EF10–13, EF18, EF22–23).
- **Historique** : humidité et température avec deux axes, luminosité et lumière sur sept jours (EF19–21).
- **Arrosage** : commande manuelle, mode automatique, règles et simulation d’un réservoir vide (EF06–09, EF14–15, EF23).
- **Paramètres** : seuils, durée et tests de pompe/relais et du feu (EF16–17, EF24).

## Simulation des états

Le laboratoire de simulation est présent sur les quatre pages. Choisir un scénario applique une nouvelle lecture et recalcule l’état de la plante :
- Normal : humidité ≥ 40 %, lumière cumulée ≥ 6 h et réservoir suffisant.
- À surveiller : humidité ≥ 30 % et < 40 %, ou lumière ≥ 3,6 h et < 6 h, sans condition rouge.
- Urgent : humidité < 30 %, lumière < 3,6 h ou réservoir insuffisant. Toutes les causes sont affichées; le rouge a priorité.

Les scénarios incluent manque d’eau, sol sec, manque de lumière, deux états jaunes et alertes combinées. Les champs permettent de tester les seuils exacts. « Tout va bien » simule le retour aux conditions normales (EF13).

Le temps est simulé : « Avancer de 30 min » permet de tester le délai et le cumul de lumière selon les lux actuels. Le cumul repart à zéro au changement de date. La simulation simplifie le passage de minuit et ne reconstitue pas les mesures intermédiaires. Les mesures et l’historique sont conservés dans le navigateur lorsque localStorage est disponible.

Un cycle simulé déclenche un arrosage automatique si le sol est sous le seuil configuré, le mode est actif, le réservoir suffisant, le délai de 30 min écoulé et le nombre d’arrosages automatiques inférieur à 6 sur 24 h. Un bouton permet de préparer le scénario de limite atteinte. L’arrosage manuel et le test restent limités à 3 s, vérifient le réservoir et restent possibles pendant le délai automatique. Le test n’est pas compté dans les arrosages. L’humidité n’est pas augmentée artificiellement après l’arrosage : simuler une nouvelle lecture pour illustrer la réponse du sol.

Les réglages modifient le déclenchement automatique, le seuil du cumul lumineux et la durée automatique (1 à 3 s). Les seuils de couleur restent ceux de EF10 à EF12. La documentation impose 3 s par défaut tout en demandant une durée configurable (EF24).

Le bandeau d’état, l’accueil, les commandes et l’historique des arrosages utilisent le même état. Sur la page Historique, les courbes et les six jours précédents restent des illustrations fixes; la dernière barre suit le cumul simulé du jour. Aucun matériel n’est connecté. Les boutons et temporisations fonctionnent seulement tant que la page reste ouverte.

Vérification des règles : `node maquette/simulation.test.cjs`.

Source fonctionnelle : `documentation/exigences_fonctionnelles.md` et choix du basilic dans `documentation/README.md`.

## Pompe et relais visibles

Chaque page affiche le circuit simulé réservoir → relais → pompe → basilic. Le relais passe de circuit ouvert à fermé pendant l’activation, la pompe affiche son état et un compte à rebours. Les commandes permettent un arrosage manuel, un test de 3 secondes et un arrêt immédiat. Un réservoir insuffisant bloque les activations; sur Arrosage, cocher le réservoir insuffisant pendant un cycle coupe la pompe simulée. Les tests ne sont pas ajoutés à l’historique des arrosages.
