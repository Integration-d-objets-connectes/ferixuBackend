"""Relais de la pompe : sortie inactive au démarrage et à la fermeture."""

from __future__ import annotations

import threading


class Pompe:
    def __init__(self, broche: int | None = None, actif_haut: bool = True) -> None:
        self._sortie = None
        self._minuterie = None
        self._verrou = threading.Lock()
        if broche is not None:
            from gpiozero import OutputDevice

            self._sortie = OutputDevice(
                broche, active_high=actif_haut, initial_value=False
            )

    @property
    def disponible(self) -> bool:
        return self._sortie is not None

    def allumer(self, duree: float = 3) -> None:
        if not self.disponible:
            raise ValueError("Broche du relais non configurée.")
        if not 0 < duree <= 20:
            raise ValueError("Durée de pompe hors limites.")
        self.eteindre()
        with self._verrou:
            self._sortie.on()
            # Coupure indépendante même si une opération du thread principal bloque.
            self._minuterie = threading.Timer(duree, self.eteindre)
            self._minuterie.daemon = True
            self._minuterie.start()

    def eteindre(self) -> None:
        with self._verrou:
            if self._minuterie is not None:
                self._minuterie.cancel()
                self._minuterie = None
            if self._sortie is not None:
                self._sortie.off()

    def fermer(self) -> None:
        try:
            self.eteindre()
        finally:
            if self._sortie is not None:
                self._sortie.close()
