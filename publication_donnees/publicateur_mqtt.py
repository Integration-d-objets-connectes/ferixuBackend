# @author Félix Lachapelle

from datetime import datetime, timezone
import json

import paho.mqtt.client as mqtt

import config


class PublicateurMQTT:
    """Publie les mesures du Raspberry Pi sur le broker MQTT (EMQX)."""

    def __init__(self, client_id: str) -> None:
        """Configure le client MQTT avec l'authentification et le TLS.

        Args:
            client_id (str): Identifiant unique du client MQTT.
        """
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id
        )
        # Connexion sécurisée au broker EMQX, comme dans la démo du cours
        self._client.username_pw_set(config.MQTT_UTILISATEUR, config.MQTT_MOT_DE_PASSE)
        self._client.tls_set(ca_certs=str(config.MQTT_CERTIFICAT_CA))

    def connecter(self) -> None:
        """Se connecte au broker et démarre le thread réseau de paho."""
        self._client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)
        # Le thread de paho envoie les messages en arrière-plan
        self._client.loop_start()

    def deconnecter(self) -> None:
        """Arrête le thread réseau de paho et se déconnecte du broker."""
        self._client.loop_stop()
        self._client.disconnect()

    def est_connecte(self) -> bool:
        """Indique si le client est connecté au broker.

        Returns:
            bool: True si le client est connecté.
        """
        return self._client.is_connected()

    def publier(self, topic: str, donnees: dict, retenir: bool = False) -> None:
        """Horodate le payload en UTC et le publie en JSON sur le topic.

        Args:
            topic (str): Topic MQTT de destination.
            donnees (dict): Payload à publier.
            retenir (bool): True pour que le broker garde le dernier message.
        """
        # setdefault : une mesure garde l'heure de son acquisition (déjà horodatée
        # par le capteur); seuls les messages sans horodatage reçoivent l'heure d'envoi.
        donnees.setdefault("horodatage", datetime.now(timezone.utc).isoformat())
        # retain=True : le broker garde le dernier message pour les prochains abonnés
        # qos=1 : le message est renvoyé jusqu'à ce que le broker confirme sa réception
        self._client.publish(topic, json.dumps(donnees), qos=1, retain=retenir)
        print(f"Publié sur {topic} : {donnees}")
