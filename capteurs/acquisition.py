# @author Félix Lachapelle
# @author Éric
# @author Codex (coéquipier IA, extraction de l’acquisition)

"""Planifie les lectures du sol, du réservoir et de la lumière sur le Raspberry Pi."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import config

from .capteur_bh1750 import CapteurLumiere
from .capteur_sol import SoilSensor

if TYPE_CHECKING:
    from controleur import Controleur


class Acquisition:
    """Gère les deux cadences de lecture, le bus I²C partagé et les reprises."""

    def __init__(self, maintenant: float) -> None:
        """Programme les premières lectures dès le démarrage de la boucle.

        Args:
            maintenant: Temps monotone de départ en secondes.
        """
        self.i2c = None
        self.sol = None
        self.lumiere = None
        self.prochain_sol = maintenant
        self.prochaine_lumiere = maintenant

    def lire(self, controleur: Controleur, maintenant: float) -> None:
        """Effectue les acquisitions arrivées à échéance (EF01 à EF03 et EF05).

        Args:
            controleur: Contrôleur qui reçoit les mesures et décide de l’arrosage.
            maintenant: Temps monotone actuel en secondes.
        """
        if controleur.fin_pompe is None and maintenant >= self.prochain_sol:
            self._lire_sol(controleur)
            self.prochain_sol = maintenant + config.PERIODE_LECTURE_SOL

        # Une lecture I2C peut bloquer. La vérification de l’eau reste prioritaire
        # pendant l’arrosage, y compris si la lecture du sol vient de l’enclencher.
        if controleur.fin_pompe is None and maintenant >= self.prochaine_lumiere:
            self._lire_lumiere(controleur)
            self.prochaine_lumiere = maintenant + config.PERIODE_LECTURE_LUMIERE

    def _bus_i2c(self) -> Any:
        """Ouvre le bus à la première lecture et le partage entre les deux capteurs."""
        if self.i2c is None:
            import board

            self.i2c = board.I2C()
        return self.i2c

    def _lire_sol(self, controleur: Controleur) -> None:
        """Lit le réservoir avec le sol et vérifie si un arrosage automatique est dû.

        Args:
            controleur: Contrôleur qui reçoit la mesure et décide de l’arrosage.
        """
        controleur.lire_eau()
        try:
            if self.sol is None:
                self.sol = SoilSensor(
                    self._bus_i2c(),
                    config.PERIODE_LECTURE_SOL,
                    config.HUMIDITE_BRUTE_SEC,
                    config.HUMIDITE_BRUTE_HUMIDE,
                )
            mesure = self.sol.lire()
        except (OSError, RuntimeError, ValueError, ImportError) as erreur:
            controleur.signaler_erreur("sol", erreur)
            self.sol = None
            print(f"Sol indisponible : {erreur}")
            return

        controleur.recevoir("sol", mesure)
        controleur.evaluer_arrosage_automatique()

    def _lire_lumiere(self, controleur: Controleur) -> None:
        """Lit le BH1750 et interrompt le cumul lumineux si la lecture échoue.

        Args:
            controleur: Contrôleur qui reçoit la mesure et cumule la lumière du jour.
        """
        try:
            if self.lumiere is None:
                self.lumiere = CapteurLumiere(
                    self._bus_i2c(), config.PERIODE_LECTURE_LUMIERE
                )
            mesure = self.lumiere.lire()
        except (OSError, RuntimeError, ValueError, ImportError) as erreur:
            controleur.signaler_erreur("lumiere", erreur)
            self.lumiere = None
            print(f"BH1750 indisponible : {erreur}")
            return

        controleur.recevoir("lumiere", mesure)

    def fermer(self) -> None:
        """Libère le bus I2C s’il a été ouvert."""
        if self.i2c is not None:
            self.i2c.deinit()
