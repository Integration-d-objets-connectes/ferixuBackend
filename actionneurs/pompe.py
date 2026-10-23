"""Relais de la pompe : sortie inactive au démarrage et à la fermeture."""
import threading


class Pompe:
    def __init__(self, broche=None, actif_haut=True):
        self._sortie = None
        self._minuterie = None
        self._verrou = threading.Lock()
        if broche is not None:
            from gpiozero import OutputDevice
            self._sortie = OutputDevice(broche, active_high=actif_haut, initial_value=False)

    @property
    def disponible(self):
        return self._sortie is not None

    def allumer(self, duree=3):
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

    def eteindre(self):
        with self._verrou:
            if self._minuterie is not None:
                self._minuterie.cancel()
                self._minuterie = None
            if self._sortie is not None:
                self._sortie.off()

    def fermer(self):
        try:
            self.eteindre()
        finally:
            if self._sortie is not None:
                self._sortie.close()
