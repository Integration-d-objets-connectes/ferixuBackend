"""Règles EF04 à EF24; tout accès matériel reste dans le thread principal."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from zoneinfo import ZoneInfo
import json
import math
from pathlib import Path


def utc():
    return datetime.now(timezone.utc)


class ErreurPersistance(Exception):
    """Une perte de persistance doit provoquer l'arrêt du programme matériel."""


def charger_etat(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        return {"parametres": {"humidite_min": 30, "lux_min": 10000,
                               "duree_arrosage": 3, "automatique": False},
                "arrosages": [], "lumiere_jours": {}, "commandes": []}
    # Un fichier corrompu doit arrêter le démarrage, jamais effacer les limites.
    etat = json.loads(chemin.read_text())
    valider_parametres(etat["parametres"])
    for evenement in etat["arrosages"]:
        datetime.fromisoformat(evenement["horodatage"])
    if not isinstance(etat["lumiere_jours"], dict) or not isinstance(etat["commandes"], list):
        raise ValueError("État persistant invalide.")
    return etat


def valider_parametres(p):
    for cle, mini, maxi in (("humidite_min", 0, 100), ("lux_min", 1, 200000),
                           ("duree_arrosage", 0.1, 3)):
        v = p[cle]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not mini <= v <= maxi:
            raise ValueError(f"Paramètre invalide : {cle} ({mini} à {maxi}).")
    if type(p["automatique"]) is not bool:
        raise ValueError("Le mode automatique doit être un booléen.")


class Controleur:
    def __init__(self, chemin, flotteur, pompe, feu, emettre, maintenant=utc,
                 zone="America/Toronto"):
        self.chemin = Path(chemin)
        self.etat = charger_etat(chemin)
        self.flotteur, self.pompe, self.feu = flotteur, pompe, feu
        self.emettre, self.maintenant = emettre, maintenant
        self.zone = ZoneInfo(zone)
        self.mesures = {}
        self.fin_pompe = None
        self.fin_test = None
        self.debut_test = None
        self.derniere_lumiere = None
        self.erreurs = {}

    def sauvegarder(self):
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = self.chemin.with_suffix(".tmp")
            temporaire.write_text(json.dumps(self.etat, ensure_ascii=False, allow_nan=False))
            temporaire.replace(self.chemin)
        except (OSError, ValueError) as erreur:
            raise ErreurPersistance("Enregistrement impossible; arrêt de sécurité.") from erreur

    def recevoir(self, nom, mesure):
        self.mesures[nom] = mesure
        self.erreurs.pop(nom, None)
        if nom == "lumiere":
            date = datetime.fromisoformat(mesure["horodatage"])
            if self.derniere_lumiere:
                precedente, lux = self.derniere_lumiere
                secondes = (date - precedente).total_seconds()
                # Pas de lumière inventée pendant une panne ou un redémarrage.
                if 0 < secondes <= 90 and lux >= self.etat["parametres"]["lux_min"]:
                    curseur = precedente
                    while curseur < date:
                        locale = curseur.astimezone(self.zone)
                        minuit = datetime.combine(locale.date() + timedelta(days=1),
                                                  datetime.min.time(), self.zone).astimezone(timezone.utc)
                        fin = min(date, minuit)
                        jour = str(locale.date())
                        self.etat["lumiere_jours"][jour] = self.etat["lumiere_jours"].get(jour, 0) + (fin - curseur).total_seconds()
                        curseur = fin
                    self.sauvegarder()
            self.derniere_lumiere = (date, mesure["lux"])
        self.emettre(nom, mesure)

    def lire_eau(self):
        try:
            mesure = self.flotteur.lire()
            if mesure.get("etat") not in ("suffisant", "insuffisant") or mesure.get("vide") is not (mesure["etat"] == "insuffisant"):
                raise ValueError("État du flotteur incohérent.")
            self.recevoir("eau", mesure)
            return mesure["etat"] == "suffisant"
        except Exception as erreur:
            self.erreurs["eau"] = str(erreur)
            return False

    def recentes(self, nom, age):
        mesure = self.mesures.get(nom)
        if not mesure or nom in self.erreurs:
            return False
        secondes = (self.maintenant() - datetime.fromisoformat(mesure["horodatage"])).total_seconds()
        return 0 <= secondes <= age

    def arrosages_recents(self):
        limite = self.maintenant() - timedelta(hours=24)
        return [a for a in self.etat["arrosages"] if datetime.fromisoformat(a["horodatage"]) > limite]

    def prochain_auto(self):
        autos = [a for a in self.etat["arrosages"] if a["mode"] == "automatique"]
        if not autos:
            return None
        dernier = autos[-1]
        return datetime.fromisoformat(dernier["horodatage"]) + timedelta(
            minutes=30, seconds=dernier.get("duree", 3))

    def arroser(self, mode, monotone):
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
        self.etat["arrosages"].append({"horodatage": self.maintenant().isoformat(),
                                      "mode": mode, "duree": self.etat["parametres"]["duree_arrosage"]})
        self.sauvegarder()
        try:
            duree = self.etat["parametres"]["duree_arrosage"]
            self.pompe.allumer(duree)
            self.fin_pompe = monotone + duree
            self.erreurs.pop("arrosage", None)
        except Exception:
            self.pompe.eteindre()
            raise
        return True

    def couleur(self):
        """Rouge prioritaire; les mesures inconnues ne peuvent pas donner vert."""
        eau = self.mesures.get("eau", {}).get("etat")
        humidite = self.mesures.get("sol", {}).get("humidite_pct")
        heures = self.heures_jour()
        sol_sec = humidite is not None and humidite < self.etat["parametres"]["humidite_min"]
        if eau == "insuffisant" or sol_sec or heures < 3.6:
            return "rouge"
        donnees_recentes = all(self.recentes(nom, age) for nom, age in (
            ("eau", 660), ("sol", 660), ("lumiere", 90)))
        if not donnees_recentes or humidite is None:
            return "inconnu"
        if humidite >= 40 and heures >= 6:
            return "vert"
        return "jaune"

    def heures_jour(self):
        jour = str(self.maintenant().astimezone(self.zone).date())
        return self.etat["lumiere_jours"].get(jour, 0) / 3600

    def mettre_a_jour(self, monotone):
        """Coupe la pompe à l'échéance et applique la couleur ou le test du feu."""
        if self.fin_pompe is not None:
            # Pendant l'arrosage, vérifier aussi le flotteur à chaque passage.
            eau = self.lire_eau()
            if monotone >= self.fin_pompe or not eau:
                self.pompe.eteindre()
                self.fin_pompe = None
                self.lire_eau()
        if self.fin_test is not None and monotone < self.fin_test:
            couleur = ("vert", "jaune", "rouge")[min(2, int(monotone - self.debut_test))]
        else:
            self.fin_test = None
            couleur = self.couleur()
        if couleur == "inconnu":
            self.feu.eteindre()
        else:
            getattr(self.feu, "allumer_" + couleur)()

    def commande(self, commande, monotone):
        identifiant = commande.get("id")
        if not isinstance(identifiant, str) or not 1 <= len(identifiant) <= 100:
            raise ValueError("Identifiant de commande requis.")
        age = (self.maintenant() - datetime.fromisoformat(commande["horodatage"])).total_seconds()
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
        elif action == "tester_feu":
            self.debut_test, self.fin_test = monotone, monotone + 3
        else:
            raise ValueError("Commande inconnue.")

    def statut(self):
        prochain = self.prochain_auto()
        aujourd_hui = self.maintenant().astimezone(self.zone).date()
        jours = {}
        for i in reversed(range(7)):
            jour = str(aujourd_hui - timedelta(days=i))
            jours[jour] = self.etat["lumiere_jours"].get(jour, 0) / 3600
        statut = {"horodatage": self.maintenant().isoformat(), "mesures": self.mesures,
                "parametres": self.etat["parametres"], "couleur": self.couleur(),
                "erreurs": self.erreurs, "heures_lumiere": self.heures_jour(), "lumiere_jours": jours,
                "pompe_active": self.fin_pompe is not None, "pompe_disponible": self.pompe.disponible,
                "dernier_arrosage": self.etat["arrosages"][-1] if self.etat["arrosages"] else None,
                "arrosages_24h": len(self.arrosages_recents()),
                "prochain_auto": prochain.isoformat() if prochain and prochain > self.maintenant() else None}
        # Le thread MQTT doit recevoir un instantané, pas les dictionnaires modifiés par la boucle.
        return deepcopy(statut)
