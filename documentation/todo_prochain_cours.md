# Validation du backend sur le Raspberry Pi

Le code des règles du backend est présent; les tests simulés ne remplacent pas les essais matériels. Aucune interface NiceGUI ni intégration MQTTX n’est incluse.

## Avant de démarrer

- [ ] Confirmer le modèle du capteur de sol alternatif et sa compatibilité STEMMA/Seesaw.
- [ ] Vérifier la référence du flotteur (SENS-112-200 ou SENS-112-250).
- [ ] Vérifier BCM 16 pour le flotteur et BCM 23/22/27 pour le feu.
- [ ] Renseigner `GPIO_RELAIS` et vérifier `RELAIS_ACTIF_HAUT`, pompe hors tension d’abord.
- [ ] Vérifier l’alimentation séparée de la pompe et le câblage du relais.
- [ ] Activer I²C et confirmer les capteurs détectés avec `i2cdetect -y 1` (installer `i2c-tools` au besoin).
- [ ] Relever les deux valeurs de calibration du sol et les inscrire dans `config.py`.

## Démonstration

1. Démarrer Mosquitto, puis `python -m ingestion.service_ingestion`, puis `python main.py`.
2. Observer `mosquitto_sub -h localhost -t 'ferixu/#' -v` et le fichier JSONL.
3. Vérifier les mesures horodatées de sol, lumière et eau. Le sol/eau sont lus immédiatement puis toutes les 600 s; la lumière toutes les 60 s.
4. Faire varier le flotteur et tester un arrosage manuel : eau insuffisante ou erreur = refus. La lecture immédiate avant la pompe doit empêcher une activation à partir d’un ancien état suffisant.
5. Tester la pompe avec eau suffisante : arrêt en 3 s maximum, puis lecture du réservoir après l’arrêt.
6. Tester le feu : vert, jaune, rouge, puis retour à la couleur calculée. Les conditions globales EF10 à EF13 remplacent l’ancien vert fondé uniquement sur l’eau.
7. Activer l’automatique avec les commandes documentées et une mesure de sol calibrée sous le seuil. Vérifier le délai et le compteur dans `ferixu/statut`.
8. Redémarrer et confirmer que paramètres, historique d’arrosage et cumul lumineux sont conservés.
9. Arrêter avec `Ctrl+C` pendant un arrosage et confirmer la coupure et la libération des GPIO.

Les cas de limite (30 minutes, 6 arrosages sur 24 h, minuit, seuils) sont aussi couverts par `python -m unittest discover -s tests -v`, sans attendre les durées réelles.

## Suite hors du périmètre backend

- Interface et boutons EF14 à EF24 : brancher une future application sur les commandes/statuts MQTT.
- Graphiques EF19 et EF20 : utiliser les mesures du JSONL; le sol doit utiliser deux axes distincts.
- OLED et buzzer : composants de l’inventaire, sans exigence fonctionnelle obligatoire EF01 à EF24.
