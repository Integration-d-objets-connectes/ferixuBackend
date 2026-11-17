# @author Éric

"""Lecture du flotteur : contact fermé = niveau insuffisant, à valider sur le Pi."""

from __future__ import annotations


from datetime import datetime, timezone

from gpiozero import Button

from .capteur import Capteur


class Flotteur(Capteur):
    """Lit le niveau du réservoir à partir du contact du flotteur."""
    def __init__(self, pin_flotteur: int = 16, periode_lecture: float = 600) -> None:
        """Configure le contact GPIO et la période de lecture du flotteur.

        Args:
            pin_flotteur (int): Broche GPIO du contact du flotteur.
            periode_lecture (float): Période de lecture prévue en secondes.
        """
        super().__init__("réservoir", periode_lecture)
        self.bouton = Button(pin_flotteur)

    @property
    def eau(self) -> bool:
        """Lit l'état réel du contact, même avant le premier changement GPIO."""
        return not self.bouton.is_pressed

    def lire(self) -> dict:
        """Horodate l'état du réservoir à l'acquisition, en ISO 8601 UTC."""
        # Une seule lecture garantit la cohérence des deux champs du contrat MQTT.
        eau = self.eau
        return {
            "etat": "suffisant" if eau else "insuffisant",
            "vide": not eau,
            "horodatage": datetime.now(timezone.utc).isoformat(),
        }

    def fermer(self) -> None:
        """Libère la broche GPIO du flotteur."""
        self.bouton.close()
