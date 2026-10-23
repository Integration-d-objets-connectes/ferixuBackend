# @author Félix Lachapelle
# @author Éric Lachapelle

"""Pilote STEMMA Soil Sensor selon la classe Capteur de la démo du cours."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import math

from .capteur import Capteur


class SoilSensor(Capteur):
    def __init__(
        self,
        i2c: Any,
        periode_lecture: float = 600,
        valeur_sec: float | None = None,
        valeur_humide: float | None = None,
    ) -> None:
        """Reçoit le bus du programme principal; couple sol toutes les 10 min."""
        # Import différé : une bibliothèque absente suit le traitement des erreurs du capteur.
        from adafruit_seesaw.seesaw import Seesaw

        super().__init__("STEMMA sol", periode_lecture)
        if (valeur_sec is None) != (valeur_humide is None):
            raise ValueError("Les deux valeurs de calibration sont nécessaires.")
        if valeur_sec is not None:
            if (
                not all(
                    math.isfinite(v) and 0 <= v <= 65535
                    for v in (valeur_sec, valeur_humide)
                )
                or valeur_sec == valeur_humide
            ):
                raise ValueError("Calibration du sol invalide.")
        self.valeur_sec = valeur_sec
        self.valeur_humide = valeur_humide
        self._capteur = Seesaw(i2c, addr=0x36)

    def lire(self) -> dict:
        """Acquiert température et capacité brute ensemble, sans inventer de %."""
        horodatage = datetime.now(timezone.utc).isoformat()
        temperature = float(self.get_temp())
        humidite_brute = float(self.get_moisture())
        if not math.isfinite(temperature) or not -40 <= temperature <= 85:
            raise ValueError("Température du sol invalide ou hors plage.")
        if not math.isfinite(humidite_brute) or not 0 <= humidite_brute <= 65535:
            raise ValueError("Humidité brute invalide ou hors plage.")
        humidite_pct = self.convertir_humidite_pct(humidite_brute)

        return {
            "temperature_c": temperature,
            "humidite_brute": humidite_brute,
            "humidite_pct": humidite_pct,
            "horodatage": horodatage,
        }

    def get_temp(self) -> float:
        """Lit la température en °C, selon l'API du pilote Adafruit."""
        return self._capteur.get_temp()

    def get_moisture(self) -> float:
        """Lit une capacité brute; une calibration reste nécessaire pour EF01."""
        return self._capteur.moisture_read()

    def convertir_humidite_pct(self, humidite_brute: float) -> float | None:
        """Convertit une lecture brute avec la calibration, ou renvoie None sans calibration."""
        if self.valeur_sec is None:
            return None

        amplitude = self.valeur_humide - self.valeur_sec
        pourcentage = 100 * (humidite_brute - self.valeur_sec) / amplitude
        return max(0.0, min(100.0, pourcentage))
