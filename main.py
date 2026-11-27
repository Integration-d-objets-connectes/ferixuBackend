# @author Félix Lachapelle
# @author Éric

"""Acquisition et règles EF04 à EF24 dans le thread principal, publication séparée."""

from __future__ import annotations

import json
import threading
import time
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config
from capteurs import Flotteur, CapteurLumiere, SoilSensor
from actionneurs import FeuCirculation
from actionneurs.pompe import Pompe
from models import Configuration
from publication_donnees import PublicateurMQTT
from reception_donnees import AbonneMQTT


@dataclass(frozen=True)
class LectureLumiere:
    """Conserve une lecture de luminosité et son horodatage."""
    horodatage: datetime
    lux: float


def utc() -> datetime:
    """Fournit l’horloge UTC par défaut, remplaçable dans les tests séparés."""
    return datetime.now(timezone.utc)


class ErreurPersistance(Exception):
    """Une perte de persistance doit provoquer l'arrêt du programme matériel."""


def charger_etat(chemin: str | Path) -> dict:
    """Charge et valide l'état persistant, ou crée les valeurs initiales.

    Args:
        chemin (str | Path): Chemin du fichier d'état.

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


def valider_parametres(p: dict) -> None:
    """Vérifie les plages des paramètres et le type du mode automatique.

    Args:
        p (dict): Paramètres à valider.
    """
    # Validation pydantic, comme dans la démo du cours.
    # ValidationError hérite de ValueError : main.py l'attrape déjà.
    Configuration.model_validate(p)


class Controleur:
    """Coordonne les mesures, les commandes et les règles de sécurité du système."""
    def __init__(
        self,
        chemin: str | Path,
        flotteur: Any,
        pompe: Any,
        feu: Any,
        emettre: Callable[[str, dict], None],
        maintenant: Callable[[], datetime] = utc,
        zone: str = "America/Toronto",
    ) -> None:
        """Initialise le contrôleur, ses périphériques et son état persistant.

        Args:
            chemin (str | Path): Chemin du fichier d'état.
            flotteur (Any): Capteur du niveau du réservoir.
            pompe (Any): Actionneur de la pompe.
            feu (Any): Actionneur du feu tricolore.
            emettre (Callable[[str, dict], None]): Fonction qui transmet les événements.
            maintenant (Callable[[], datetime]): Fonction fournissant la date et l’heure courantes.
            zone (str): Nom du fuseau horaire local.
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
            nom (str): Nom de la variable, de la mesure ou du capteur.
            mesure (dict): Mesure à enregistrer ou à afficher.
        """
        self.mesures[nom] = mesure
        self.erreurs.pop(nom, None)

        if nom != "lumiere":
            self.emettre(nom, mesure)
            return

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

        self.emettre(nom, mesure)

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
        """Indique si la dernière mesure valide est âgée d'au plus age secondes.

        Args:
            nom (str): Nom de la variable, de la mesure ou du capteur.
            age (float): Âge maximal de la mesure en secondes.

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
        """Renvoie la prochaine heure permise après un arrosage automatique.

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

    def arroser(self, mode: str, monotone: float) -> bool:
        """Vérifie les conditions communes et celles réservées à l'automatique."""
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
        """Coupe la pompe à l'échéance et applique la couleur ou le test du feu."""
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

    def commande(self, commande: dict, monotone: float) -> None:
        """Valide et exécute une commande récente et non encore traitée.

        Args:
            commande (dict): Commande à valider et à exécuter.
            monotone (float): Temps monotone actuel en secondes.
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
            p = {**self.etat["parametres"], **commande["parametres"]}
            if set(p) != set(self.etat["parametres"]):
                raise ValueError("Paramètre inconnu.")
            valider_parametres(p)
            self.etat["parametres"] = p
            self.derniere_lumiere = None
            self.sauvegarder()
            # Confirme la configuration appliquée à l'ingestion et au client
            self.emettre("configuration", dict(p))
        elif action == "tester_feu":
            self.debut_test = monotone
            self.fin_test = monotone + 3
        else:
            raise ValueError("Commande inconnue.")

    def statut(self) -> dict:
        """Construit un instantané indépendant de l’état actuel du système.

        Returns:
            dict: Copie indépendante du statut du système.
        """
        prochain = self.prochain_auto()
        aujourd_hui = self.maintenant().astimezone(self.zone).date()
        jours = {}
        for i in reversed(range(7)):
            jour = str(aujourd_hui - timedelta(days=i))
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


def creer_bus_i2c() -> Any:
    """Charge le pilote à la demande pour permettre une nouvelle tentative après erreur."""
    import board

    return board.I2C()


def main() -> None:
    # Signale aux deux boucles de terminer leur travail.
    """Initialise le matériel et exécute les boucles d'acquisition et de publication."""
    arret = threading.Event()
    # Protège la file de mesures partagée avec le thread MQTT.
    verrou = threading.Lock()
    mesures_en_attente: list[tuple[str, dict]] = []
    flotteur = None
    feu = None
    pompe = None
    i2c = None
    publicateur = None
    abonne = None
    thread = None
    # Commandes reçues par l'abonné, lues par la boucle principale.
    commandes = Queue()

    topics = {
        "eau": config.TOPIC_EAU,
        "sol": config.TOPIC_SOL,
        "lumiere": config.TOPIC_LUMIERE,
        "statut": config.TOPIC_STATUT,
        "resultat": config.TOPIC_RESULTAT,
        "arrosage": config.TOPIC_ARROSAGE,
        "configuration": config.TOPIC_CONFIGURATION,
    }

    def emettre(nom: str, mesure: dict) -> None:
        """Ajoute une mesure identifiée à la file de publication.

        Args:
            nom (str): Nom de la variable, de la mesure ou du capteur.
            mesure (dict): Mesure à enregistrer ou à afficher.
        """
        topic = topics[nom]
        with verrou:
            mesures_en_attente.append((topic, {**mesure, "plante_id": config.PLANTE_ID}))

    def publier() -> None:
        """Publie les mesures en attente auprès du courtier MQTT."""
        with verrou:
            mesures = mesures_en_attente.copy()
            mesures_en_attente.clear()
        for topic, mesure in mesures:
            # Retenue : l'ingestion et le client voient la dernière configuration
            #   appliquée, même s'ils se connectent plus tard (démo du cours).
            publicateur.publier(
                topic, mesure, retenir=topic == config.TOPIC_CONFIGURATION
            )

    def boucle_publication() -> None:
        """Publie périodiquement les mesures jusqu'à la demande d'arrêt.
        """
        try:
            while not arret.wait(config.PERIODE_PUBLICATION):
                publier()
            # Dernier envoi des mesures restantes lors de l’arrêt.
            publier()
        except Exception as erreur:
            print(f"Erreur MQTT, arrêt du matériel : {erreur}")
            arret.set()

    try:
        # Créer le relais inactif avant de démarrer la communication.
        pompe = Pompe(config.GPIO_RELAIS, config.RELAIS_ACTIF_HAUT)
        flotteur = Flotteur(config.GPIO_FLOTTEUR, config.PERIODE_LECTURE_RESERVOIR)
        feu = FeuCirculation(
            config.GPIO_FEU_ROUGE, config.GPIO_FEU_JAUNE, config.GPIO_FEU_VERT
        )

        controleur = Controleur(
            config.FICHIER_ETAT,
            flotteur,
            pompe,
            feu,
            emettre,
            zone=config.FUSEAU_HORAIRE,
        )
        publicateur = PublicateurMQTT("ferixu-publicateur")
        publicateur.connecter()

        # Le callback (thread de paho) ajoute seulement la commande à la file.
        abonne = AbonneMQTT("ferixu-abonne", config.TOPIC_COMMANDES, commandes.put)
        abonne.connecter()

        thread = threading.Thread(target=boucle_publication)
        thread.start()

        capteur_sol = None
        capteur_lumiere = None

        maintenant = time.monotonic()
        prochaine_sol = maintenant
        prochaine_lumiere = maintenant
        prochain_statut = maintenant

        while not arret.is_set():
            maintenant = time.monotonic()
            controleur.mettre_a_jour(maintenant)
            # Les commandes attendent le thread principal; aucune activation depuis Paho.
            for _ in range(10):
                try:
                    commande = commandes.get_nowait()
                except Empty:
                    break
                try:
                    controleur.commande(commande, maintenant)
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    RuntimeError,
                ) as erreur:
                    resultat = {
                        "id": commande.get("id"),
                        "action": commande.get("action"),
                        "succes": False,
                        "message": str(erreur),
                    }
                else:
                    resultat = {
                        "id": commande.get("id"),
                        "action": commande.get("action"),
                        "succes": True,
                        "message": "Commande exécutée.",
                    }
                resultat["horodatage"] = datetime.now(timezone.utc).isoformat()
                emettre("resultat", resultat)
                prochain_statut = maintenant

            # EF05 : lecture du réservoir lors de chaque acquisition du sol.
            # Éviter de lancer une lecture I2C pendant les trois secondes d'arrosage.
            if controleur.fin_pompe is None and maintenant >= prochaine_sol:
                controleur.lire_eau()
                try:
                    if i2c is None:
                        i2c = creer_bus_i2c()
                    if capteur_sol is None:
                        capteur_sol = SoilSensor(
                            i2c,
                            config.PERIODE_LECTURE_SOL,
                            config.HUMIDITE_BRUTE_SEC,
                            config.HUMIDITE_BRUTE_HUMIDE,
                        )
                    controleur.recevoir("sol", capteur_sol.lire())
                except (OSError, RuntimeError, ValueError, ImportError) as erreur:
                    controleur.erreurs["sol"] = str(erreur)
                    capteur_sol = None
                    print(f"Sol indisponible : {erreur}")
                else:
                    try:
                        controleur.arroser("automatique", time.monotonic())
                    except (ValueError, OSError, RuntimeError) as erreur:
                        controleur.erreurs["arrosage"] = str(erreur)
                prochaine_sol = maintenant + config.PERIODE_LECTURE_SOL

            if controleur.fin_pompe is None and maintenant >= prochaine_lumiere:
                try:
                    if i2c is None:
                        i2c = creer_bus_i2c()
                    if capteur_lumiere is None:
                        capteur_lumiere = CapteurLumiere(
                            i2c, config.PERIODE_LECTURE_LUMIERE
                        )
                    controleur.recevoir("lumiere", capteur_lumiere.lire())
                except (OSError, RuntimeError, ValueError, ImportError) as erreur:
                    controleur.erreurs["lumiere"] = str(erreur)
                    controleur.derniere_lumiere = None
                    capteur_lumiere = None
                    print(f"BH1750 indisponible : {erreur}")
                prochaine_lumiere = maintenant + config.PERIODE_LECTURE_LUMIERE
            if maintenant >= prochain_statut:
                emettre("statut", controleur.statut())
                prochain_statut = maintenant + config.PERIODE_PUBLICATION
            arret.wait(0.1)
    except KeyboardInterrupt:
        print("Arrêt de Ferixu…")
    finally:
        # Les callbacks sont exécutés en ordre inverse, même si une fermeture échoue.
        with ExitStack() as nettoyage:
            if i2c is not None:
                nettoyage.callback(i2c.deinit)
            if feu is not None:
                nettoyage.callback(feu.fermer)
            if flotteur is not None:
                nettoyage.callback(flotteur.fermer)
            if publicateur is not None:
                nettoyage.callback(publicateur.deconnecter)
            # L'abonné avant le publicateur, comme dans la démo.
            if abonne is not None:
                nettoyage.callback(abonne.deconnecter)
            if thread is not None and thread.ident is not None:
                nettoyage.callback(thread.join)
            nettoyage.callback(arret.set)

            # Couper la pompe avant toute attente réseau ou fermeture de capteur.
            if pompe is not None:
                pompe.fermer()


if __name__ == "__main__":
    main()
