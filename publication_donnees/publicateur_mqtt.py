# @author Félix Lachapelle

"""Communication MQTT indépendante des pilotes et de l'acquisition."""

from __future__ import annotations

from typing import Any

import json
import threading
from queue import Queue, Full

import paho.mqtt.client as mqtt

import config


class PublicateurMQTT:
    """Publie les mesures horodatées sans modifier les données acquises."""

    def __init__(self, client_id: str) -> None:
        self._connexion = threading.Event()
        self._erreur_connexion = None
        self.commandes = Queue(maxsize=100)
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id
        )
        self._client.on_connect = self._lors_connexion
        self._client.on_disconnect = self._lors_deconnexion
        self._client.on_message = self._lors_message

    def _lors_message(self, client: Any, userdata: Any, message: Any) -> None:
        # Le callback réseau ne touche jamais au matériel.
        if message.retain or message.topic != config.TOPIC_COMMANDES:
            return
        try:
            commande = json.loads(message.payload.decode("utf-8"))
            if isinstance(commande, dict):
                self.commandes.put_nowait(commande)
        except (ValueError, UnicodeDecodeError, Full):
            print("Commande MQTT invalide ou file pleine : ignorée.")

    def _lors_connexion(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        """Signale la réponse du broker, y compris un refus de connexion."""
        self._erreur_connexion = str(reason_code) if reason_code.is_failure else None
        if not reason_code.is_failure:
            client.subscribe(config.TOPIC_COMMANDES, qos=1)
        self._connexion.set()

    def _lors_deconnexion(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        """Empêche une publication après la perte de connexion."""
        self._connexion.clear()

    def connecter(self) -> None:
        """Attend la confirmation du broker avant de permettre les envois."""
        self._connexion.clear()
        self._erreur_connexion = None
        try:
            self._client.connect(config.MQTT_HOTE, config.MQTT_PORT, 60)
            self._client.loop_start()
            if not self._connexion.wait(config.MQTT_DELAI_SECONDES):
                raise TimeoutError("Le broker MQTT ne répond pas.")
            if self._erreur_connexion is not None:
                raise ConnectionError(
                    f"Connexion MQTT refusée : {self._erreur_connexion}"
                )
        except Exception:
            self.deconnecter()
            raise

    def publier(self, topic: str, donnees: dict) -> None:
        """Conserve l'horodatage UTC d'acquisition et attend l'accusé QoS 1."""
        if not donnees.get("horodatage"):
            raise ValueError("La mesure doit être horodatée lors de l'acquisition.")
        if not self._connexion.is_set() or self._erreur_connexion is not None:
            raise ConnectionError("Le publicateur MQTT n'est pas connecté.")
        payload = json.dumps(donnees, ensure_ascii=False, allow_nan=False)
        resultat = self._client.publish(topic, payload, qos=1)
        if resultat.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"Échec de publication MQTT : {resultat.rc}")
        resultat.wait_for_publish(timeout=config.MQTT_DELAI_SECONDES)
        if not resultat.is_published():
            raise TimeoutError("Publication MQTT non confirmée par le broker.")
        print(f"Publié sur {topic} : {payload}")

    def deconnecter(self) -> None:
        """Déconnecte le client puis termine sa boucle réseau."""
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._connexion.clear()
