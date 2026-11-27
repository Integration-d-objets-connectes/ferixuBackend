# @author Félix Lachapelle
# @author Éric
# @author Codex (coéquipier IA, extraction du contrôleur)

"""Applique les règles de la plante et conserve les données utiles au redémarrage."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from actionneurs import FeuCirculation, Pompe
from capteurs import Flotteur
from models import Configuration


# 1. Charger et valider l’état persistant


class ErreurPersistance(Exception):
    """Une perte de persistance doit provoquer l'arrêt du programme matériel."""


def charger_etat(chemin: str | Path) -> dict:
    """Charge et valide l'état persistant, ou crée les valeurs initiales.

    Args:
        chemin: Chemin du fichier d'état.

    Returns:
        dict: État chargé ou état initial.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return {
            "parametres": {
                "humidite_min": 30,
                "lux_min": 10000,
                "duree_arrosage": 3,
                "automatique": False,
            },
            "arrosages": [],
            "lumiere_jours": {},
            "commandes": [],
        }
    # Un fichier corrompu doit arrêter le démarrage, jamais effacer les limites.
    etat = json.loads(chemin.read_text())
    valider_parametres(etat["parametres"])
    for evenement in etat["arrosages"]:
        datetime.fromisoformat(evenement["horodatage"])
    if not isinstance(etat["lumiere_jours"], dict) or not isinstance(
        etat["commandes"], list
    ):
        raise ValueError("État persistant invalide.")
    return etat


def valider_parametres(parametres: dict) -> None:
    """Vérifie les plages des paramètres et le type du mode automatique.

    Args:
        parametres: Seuils, durée d’arrosage et mode automatique.
    """
    # Validation pydantic, comme dans la démo du cours.
    Configuration.model_validate(parametres)


# 2. Appliquer les règles de la plante


@dataclass(frozen=True)
class LectureLumiere:
    """Conserve une lecture de luminosité et son horodatage."""

    horodatage: datetime
    lux: float


def utc() -> datetime:
    """Renvoie l’heure courante en UTC."""
    return datetime.now(timezone.utc)


class Controleur:
    """Coordonne les mesures, les commandes et les règles de sécurité du système."""

    # État persistant et lectures

    def __init__(
        self,
        chemin: str | Path,
        flotteur: Flotteur,
        pompe: Pompe,
        feu: FeuCirculation,
        emettre: Callable[[str, dict], None],
        maintenant: Callable[[], datetime] = utc,
        zone: str = "America/Toronto",
    ) -> None:
        """Initialise le contrôleur, ses périphériques et son état persistant.

        Args:
            chemin: Chemin du fichier d'état.
            flotteur: Capteur du niveau du réservoir.
            pompe: Actionneur de la pompe.
            feu: Actionneur du feu tricolore.
            emettre: Fonction qui transmet les événements.
            maintenant: Fonction fournissant la date et l’heure courantes.
            zone: Nom du fuseau horaire local.
        """
        self.chemin = Path(chemin)
        self.etat = charger_etat(chemin)
        self.flotteur = flotteur
        self.pompe = pompe
        self.feu = feu

        self.emettre = emettre
        self.maintenant = maintenant
        self.zone = ZoneInfo(zone)
        self.mesures: dict[str, dict] = {}
        self.fin_pompe: float | None = None
        # Séquence de diagnostic du feu demandée par la commande tester_feu.
        self.fin_test: float | None = None
        self.debut_test: float | None = None
        self.derniere_lumiere: LectureLumiere | None = None
        self.erreurs: dict[str, str] = {}

    def sauvegarder(self) -> None:
        """Enregistre l'état par remplacement de fichier; signale toute erreur de persistance."""
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = self.chemin.with_suffix(".tmp")
            temporaire.write_text(
                json.dumps(self.etat, ensure_ascii=False, allow_nan=False)
            )
            temporaire.replace(self.chemin)
        except (OSError, ValueError) as erreur:
            raise ErreurPersistance(
                "Enregistrement impossible; arrêt de sécurité."
            ) from erreur

    def recevoir(self, nom: str, mesure: dict) -> None:
        """Enregistre et émet une mesure, en cumulant la lumière par journée locale.

        Args:
            nom: Clé de la mesure, soit sol, lumiere ou eau.
            mesure: Valeurs horodatées renvoyées par le capteur.
        """
        self.mesures[nom] = mesure
        self.erreurs.pop(nom, None)

        if nom == "lumiere":
            self.cumuler_lumiere(mesure)
        self.emettre(nom, mesure)

    def cumuler_lumiere(self, mesure: dict) -> None:
        """Répartit l’intervalle éclairé entre les journées qu’il traverse (EF04).

        Args:
            mesure: Lecture du BH1750 avec lux et horodatage UTC.
        """
        date = datetime.fromisoformat(mesure["horodatage"])
        if self.derniere_lumiere:
            precedente = self.derniere_lumiere.horodatage
            lux = self.derniere_lumiere.lux
            secondes = (date - precedente).total_seconds()
            # Pas de lumière inventée pendant une panne ou un redémarrage.
            if 0 < secondes <= 90 and lux >= self.etat["parametres"]["lux_min"]:
                curseur = precedente
                while curseur < date:
                    locale = curseur.astimezone(self.zone)
                    minuit = datetime.combine(
                        locale.date() + timedelta(days=1),
                        datetime.min.time(),
                        self.zone,
                    ).astimezone(timezone.utc)
                    fin = min(date, minuit)
                    jour = str(locale.date())
                    self.etat["lumiere_jours"][jour] = (
                        self.etat["lumiere_jours"].get(jour, 0)
                        + (fin - curseur).total_seconds()
                    )
                    curseur = fin
                self.sauvegarder()
        self.derniere_lumiere = LectureLumiere(date, mesure["lux"])

    def signaler_erreur(self, nom: str, erreur: Exception) -> None:
        """Conserve l’erreur du capteur et interrompt le cumul si le BH1750 échoue.

        Args:
            nom: Clé du capteur en erreur dans le statut.
            erreur: Exception levée lors de la lecture.
        """
        self.erreurs[nom] = str(erreur)
        if nom == "lumiere":
            self.derniere_lumiere = None

    def lire_eau(self) -> bool:
        """Lit le flotteur et renvoie si le niveau est suffisant et cohérent.

        Returns:
            bool: True si le niveau est suffisant et cohérent.
        """
        try:
            mesure = self.flotteur.lire()
            etat = mesure.get("etat")
            etat_valide = etat in ("suffisant", "insuffisant")
            niveau_coherent = mesure.get("vide") is (etat == "insuffisant")

            if not etat_valide or not niveau_coherent:
                raise ValueError("État du flotteur incohérent.")

            self.recevoir("eau", mesure)
            return mesure["etat"] == "suffisant"
        except Exception as erreur:
            self.erreurs["eau"] = str(erreur)
            return False

    def recentes(self, nom: str, age: float) -> bool:
        """Vérifie la fraîcheur de la dernière lecture du capteur.

        Args:
            nom: Clé de la mesure, soit sol, lumiere ou eau.
            age: Âge maximal de la mesure en secondes.

        Returns:
            bool: True si la mesure est valide et assez récente.
        """
        mesure = self.mesures.get(nom)
        if not mesure or nom in self.erreurs:
            return False
        secondes = (
            self.maintenant() - datetime.fromisoformat(mesure["horodatage"])
        ).total_seconds()
        return 0 <= secondes <= age

    # Arrosage et feu tricolore

    def arrosages_recents(self) -> list[dict]:
        """Renvoie les arrosages enregistrés durant les dernières 24 heures.

        Returns:
            list[dict]: Arrosages enregistrés durant les dernières 24 heures.
        """
        limite = self.maintenant() - timedelta(hours=24)
        return [
            a
            for a in self.etat["arrosages"]
            if datetime.fromisoformat(a["horodatage"]) > limite
        ]

    def prochain_auto(self) -> datetime | None:
        """Calcule la fin du délai depuis le dernier arrosage automatique.

        Returns:
            datetime | None: Prochaine heure permise, ou None sans arrosage automatique.
        """
        autos = [a for a in self.etat["arrosages"] if a["mode"] == "automatique"]
        if not autos:
            return None
        dernier = autos[-1]
        return datetime.fromisoformat(dernier["horodatage"]) + timedelta(
            minutes=30, seconds=dernier.get("duree", 3)
        )

    def evaluer_arrosage_automatique(self) -> None:
        """Évalue les conditions d’arrosage après une nouvelle mesure du sol."""
        try:
            self.arroser("automatique", time.monotonic())
        except (ValueError, OSError, RuntimeError) as erreur:
            self.erreurs["arrosage"] = str(erreur)

    def arroser(self, mode: str, monotone: float) -> bool:
        """Active la pompe après avoir vérifié les conditions d’arrosage (EF06 à EF09).

        Args:
            mode: Type d’arrosage, soit automatique, manuel ou test.
            monotone: Temps monotone actuel en secondes.

        Returns:
            bool: True si la pompe a démarré. False si les conditions automatiques manquent.
        """
        if self.fin_pompe is not None:
            raise ValueError("Arrosage déjà en cours.")
        if mode == "automatique":
            parametres = self.etat["parametres"]
            humidite = self.mesures.get("sol", {}).get("humidite_pct")
            if not parametres["automatique"] or not self.recentes("sol", 660):
                return False
            if humidite is None or humidite >= parametres["humidite_min"]:
                return False
            prochain = self.prochain_auto()
            if prochain and self.maintenant() < prochain:
                return False
            if sum(a["mode"] == "automatique" for a in self.arrosages_recents()) >= 6:
                return False

        if not self.pompe.disponible:
            raise ValueError("Configurer GPIO_RELAIS pour activer la pompe.")
        if not self.lire_eau():
            raise ValueError("Arrosage refusé : eau insuffisante ou lecture en erreur.")

        # Persister avant d'activer : une coupure ne remet pas les compteurs à zéro.
        self.etat["arrosages"].append(
            {
                "horodatage": self.maintenant().isoformat(),
                "mode": mode,
                "duree": self.etat["parametres"]["duree_arrosage"],
            }
        )
        self.sauvegarder()

        try:
            duree = self.etat["parametres"]["duree_arrosage"]
            self.pompe.allumer(duree)
            self.fin_pompe = monotone + duree
            self.erreurs.pop("arrosage", None)
        except Exception:
            self.pompe.eteindre()
            raise
        self.emettre(
            "arrosage",
            {
                "auto": mode == "automatique",
                # automatique, manuel ou test, pour l'historique des activités
                "mode": mode,
                "duree": self.etat["arrosages"][-1]["duree"],
                "horodatage": self.etat["arrosages"][-1]["horodatage"],
            },
        )
        return True

    def couleur(self) -> str:
        """Rouge prioritaire; les mesures inconnues ne peuvent pas donner vert."""
        eau = self.mesures.get("eau", {}).get("etat")
        humidite = self.mesures.get("sol", {}).get("humidite_pct")
        heures = self.heures_jour()
        sol_sec = (
            humidite is not None and humidite < self.etat["parametres"]["humidite_min"]
        )
        if eau == "insuffisant" or sol_sec or heures < 3.6:
            return "rouge"
        donnees_recentes = all(
            self.recentes(nom, age)
            for nom, age in (("eau", 660), ("sol", 660), ("lumiere", 90))
        )
        if not donnees_recentes or humidite is None:
            return "inconnu"
        if humidite >= 40 and heures >= 6:
            return "vert"
        return "jaune"

    def heures_jour(self) -> float:
        """Renvoie les heures de lumière cumulées pour la journée locale.

        Returns:
            float: Nombre d’heures de lumière cumulées aujourd’hui.
        """
        jour = str(self.maintenant().astimezone(self.zone).date())
        return self.etat["lumiere_jours"].get(jour, 0) / 3600

    def mettre_a_jour(self, monotone: float) -> None:
        """Vérifie la pompe et actualise le feu à chaque passage de la boucle.

        Args:
            monotone: Temps monotone utilisé pour les échéances de la pompe et du feu.
        """
        if self.fin_pompe is not None:
            # Pendant l'arrosage, vérifier aussi le flotteur à chaque passage.
            eau = self.lire_eau()
            if monotone >= self.fin_pompe or not eau:
                self.pompe.eteindre()
                self.fin_pompe = None
                self.lire_eau()
        if self.fin_test is not None and monotone < self.fin_test:
            couleur = ("vert", "jaune", "rouge")[
                min(2, int(monotone - self.debut_test))
            ]
        else:
            self.fin_test = None
            couleur = self.couleur()
        if couleur == "inconnu":
            self.feu.eteindre()
        else:
            getattr(self.feu, "allumer_" + couleur)()

    # Commandes de l’application et statut publié

    def commande(self, commande: dict, monotone: float) -> None:
        """Valide et exécute une commande récente et non encore traitée.

        Args:
            commande: Commande à valider et à exécuter.
            monotone: Temps monotone actuel en secondes.
        """
        identifiant = commande.get("id")
        if not isinstance(identifiant, str) or not 1 <= len(identifiant) <= 100:
            raise ValueError("Identifiant de commande requis.")
        age = (
            self.maintenant() - datetime.fromisoformat(commande["horodatage"])
        ).total_seconds()
        if not 0 <= age <= 30:
            raise ValueError("Commande expirée.")
        if identifiant in self.etat["commandes"]:
            raise ValueError("Commande déjà traitée.")
        self.etat["commandes"] = (self.etat["commandes"] + [identifiant])[-1000:]
        self.sauvegarder()
        action = commande.get("action")
        if action in ("arroser", "tester_pompe"):
            self.arroser("manuel" if action == "arroser" else "test", monotone)
        elif action == "parametres":
            parametres = {**self.etat["parametres"], **commande["parametres"]}
            if set(parametres) != set(self.etat["parametres"]):
                raise ValueError("Paramètre inconnu.")
            valider_parametres(parametres)
            self.etat["parametres"] = parametres
            self.derniere_lumiere = None
            self.sauvegarder()
            # Confirme la configuration appliquée à l'ingestion et au client
            self.emettre("configuration", dict(parametres))
        elif action == "tester_feu":
            self.debut_test = monotone
            self.fin_test = monotone + 3
        else:
            raise ValueError("Commande inconnue.")

    def traiter_commande(self, commande: dict, monotone: float) -> None:
        """Exécute une commande et publie son résultat avec son identifiant (ET05).

        Args:
            commande: Valeur JSON reçue sur le topic des commandes.
            monotone: Temps monotone actuel en secondes.
        """
        try:
            self.commande(commande, monotone)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as erreur:
            succes = False
            message = str(erreur)
        else:
            succes = True
            message = "Commande exécutée."

        self.emettre(
            "resultat",
            {
                "id": commande.get("id"),
                "action": commande.get("action"),
                "succes": succes,
                "message": message,
                "horodatage": self.maintenant().isoformat(),
            },
        )

    def statut(self) -> dict:
        """Construit un instantané indépendant de l’état actuel du système.

        Returns:
            dict: Copie indépendante du statut du système.
        """
        prochain = self.prochain_auto()
        aujourd_hui = self.maintenant().astimezone(self.zone).date()
        jours = {}
        for recul in range(6, -1, -1):
            jour = str(aujourd_hui - timedelta(days=recul))
            jours[jour] = self.etat["lumiere_jours"].get(jour, 0) / 3600
        statut = {
            "horodatage": self.maintenant().isoformat(),
            "mesures": self.mesures,
            "parametres": self.etat["parametres"],
            "couleur": self.couleur(),
            "erreurs": self.erreurs,
            "heures_lumiere": self.heures_jour(),
            "lumiere_jours": jours,
            "pompe_active": self.fin_pompe is not None,
            "pompe_disponible": self.pompe.disponible,
            "dernier_arrosage": (
                self.etat["arrosages"][-1] if self.etat["arrosages"] else None
            ),
            "arrosages_24h": len(self.arrosages_recents()),
            "prochain_auto": (
                prochain.isoformat()
                if prochain and prochain > self.maintenant()
                else None
            ),
        }
        # Le thread MQTT doit recevoir un instantané, pas les dictionnaires modifiés par la boucle.
        return deepcopy(statut)
