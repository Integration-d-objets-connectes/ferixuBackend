# @author Félix Lachapelle

from abc import ABC, abstractmethod


class Capteur(ABC):

    """Définit le contrat commun des capteurs du système.
    """
    def __init__(self, nom: str, periode_lecture: float):
        """Enregistre le nom du capteur et sa période de lecture.

        Args:
            nom (str): Nom de la variable, de la mesure ou du capteur.
            periode_lecture (float): Période de lecture prévue en secondes.
        """
        self.nom = nom
        self.periode_lecture = periode_lecture

    @abstractmethod
    def lire(self) -> dict:
        """Acquiert une mesure sous forme de dictionnaire.

        Returns:
            dict: Mesure acquise par le capteur.
        """
        pass

    def fermer(self) -> None:
        """Libère le matériel. Par défaut, on ne fait rien."""
        ...
