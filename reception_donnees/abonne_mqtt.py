# @author Félix Lachapelle

import json
from collections.abc import Callable

import paho.mqtt.client as mqtt

import config


class AbonneMQTT:
    """S'abonne à un topic MQTT et transmet chaque message reçu à une fonction."""

    def __init__(
        self, client_id: str, topic: str, action_sur_message: Callable[[dict], None]
    ) -> None:
        """Configure le client MQTT avec l'authentification et le TLS.

        Args:
            client_id (str): Identifiant unique du client MQTT.
            topic (str): Topic MQTT à écouter.
            action_sur_message (Callable[[dict], None]): Fonction appelée avec chaque payload reçu.
        """
        self._topic = topic
        self._action_sur_message = action_sur_message

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id
        )
        self._client.username_pw_set(config.MQTT_UTILISATEUR, config.MQTT_MOT_DE_PASSE)
        self._client.tls_set(ca_certs=str(config.MQTT_CERTIFICAT_CA))
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def connecter(self) -> None:
        """Se connecte au broker et démarre le thread réseau de paho."""
        self._client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)
        # Le thread de paho reçoit les messages en arrière-plan
        self._client.loop_start()

    def deconnecter(self) -> None:
        """Arrête le thread réseau de paho et se déconnecte du broker."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """S'abonne au topic dès que le broker accepte la connexion."""
        if reason_code.is_failure:
            print(f"Échec de connexion au broker : {reason_code}")
            return

        print(f"Connecté, abonnement à {self._topic}")
        # Abonnement ici : il est refait automatiquement après une reconnexion
        client.subscribe(self._topic, qos=1)

    def _on_message(self, client, userdata, msg):
        """Décode le payload JSON et le transmet à la fonction de main.py."""
        # Attention : exécuté dans le thread de paho, pas dans le thread principal

        # Message retenu = ancienne commande : on ne la refait pas
        if msg.retain:
            return

        try:
            donnees = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            print(f"Message invalide ignoré : {msg.payload}")
            return

        # Callback : à chaque message reçu, paho appelle cette fonction de main.py.
        #   Elle ajoute seulement la commande à une file : le matériel reste
        #   commandé par le thread principal.
        self._action_sur_message(donnees)
