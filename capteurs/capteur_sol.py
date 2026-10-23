# @author Félix Lachapelle
# @author Éric Lachapelle

"""Pilote STEMMA Soil Sensor selon la classe Capteur de la démo du cours."""
from datetime import datetime, timezone
import math

from .capteur import Capteur


class SoilSensor(Capteur):
    def __init__(self, i2c, periode_lecture=600, valeur_sec=None, valeur_humide=None):
        # pas assez d'espaces, c'est illisible
        """Reçoit le bus du programme principal; couple sol toutes les 10 min."""
        # import ici?
        from adafruit_seesaw.seesaw import Seesaw
        super().__init__("STEMMA sol", periode_lecture)
        if (valeur_sec is None) != (valeur_humide is None):
            raise ValueError("Les deux valeurs de calibration sont nécessaires.")
        if valeur_sec is not None:
            if not all(math.isfinite(v) and 0 <= v <= 65535
                       for v in (valeur_sec, valeur_humide)) or valeur_sec == valeur_humide:
                raise ValueError("Calibration du sol invalide.")
        self.valeur_sec = valeur_sec
        self.valeur_humide = valeur_humide
        self._capteur = Seesaw(i2c, addr=0x36)

    def lire(self) -> dict:
        # pas assez d'espaces, c'est illisible
        """Acquiert température et capacité brute ensemble, sans inventer de %."""
        horodatage = datetime.now(timezone.utc).isoformat()
        temperature = float(self.get_temp())
        humidite_brute = float(self.get_moisture())
        if not math.isfinite(temperature) or not -40 <= temperature <= 85:
            raise ValueError("Température du sol invalide ou hors plage.")
        if not math.isfinite(humidite_brute) or not 0 <= humidite_brute <= 65535:
            raise ValueError("Humidité brute invalide ou hors plage.")
        humidite_pct = None
        if self.valeur_sec is not None:
            humidite_pct = max(0.0, min(100.0, 100 * (humidite_brute - self.valeur_sec)
                                      / (self.valeur_humide - self.valeur_sec)))
        return {"temperature_c": temperature, "humidite_brute": humidite_brute,
                "humidite_pct": humidite_pct,
                "horodatage": horodatage}

    def get_temp(self):
        """Lit la température en °C, selon l'API du pilote Adafruit."""
        return self._capteur.get_temp()

    def get_moisture(self):
        """Lit une capacité brute; une calibration reste nécessaire pour EF01."""
        return self._capteur.moisture_read()

    # pas de fonction pour avoir la mesure en %?