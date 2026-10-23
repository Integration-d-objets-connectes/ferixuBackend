"""Vérifications des règles sensibles sans matériel ni broker MQTT."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from controleur import Controleur


class ControleurTests(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.maintenant = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.flotteur = Mock()
        self.flotteur.lire.return_value = {
            "etat": "suffisant",
            "vide": False,
            "horodatage": self.maintenant.isoformat(),
        }
        self.pompe = Mock(disponible=True)
        self.feu = Mock()
        self.emettre = Mock()
        self.controleur = Controleur(
            Path(self.dossier.name) / "etat.json",
            self.flotteur,
            self.pompe,
            self.feu,
            self.emettre,
            maintenant=lambda: self.maintenant,
        )

    def test_lumiere_repartie_de_part_et_autre_de_minuit(self):
        for date in ("2026-10-24T03:59:30+00:00", "2026-10-24T04:00:30+00:00"):
            self.controleur.recevoir("lumiere", {"lux": 12000, "horodatage": date})
        self.assertEqual(
            self.controleur.etat["lumiere_jours"],
            {
                "2026-10-23": 30,
                "2026-10-24": 30,
            },
        )
        self.assertEqual(self.emettre.call_count, 2)

    def test_interruption_ne_compte_pas_de_lumiere(self):
        for date in ("2026-10-23T12:00:00+00:00", "2026-10-23T12:02:00+00:00"):
            self.controleur.recevoir("lumiere", {"lux": 12000, "horodatage": date})
        self.assertEqual(self.controleur.etat["lumiere_jours"], {})

    def test_reservoir_incoherent_refuse_la_pompe(self):
        self.flotteur.lire.return_value["vide"] = True
        with self.assertRaises(ValueError):
            self.controleur.arroser("manuel", 10)
        self.pompe.allumer.assert_not_called()

    def test_arrosage_persiste_et_sarrete_a_lecheance(self):
        self.assertTrue(self.controleur.arroser("manuel", 10))
        self.assertTrue(self.controleur.chemin.exists())
        self.pompe.allumer.assert_called_once_with(3)
        self.controleur.mettre_a_jour(13)
        self.pompe.eteindre.assert_called_once()
        self.assertIsNone(self.controleur.fin_pompe)

    def test_diagnostic_du_feu_reste_disponible(self):
        self.controleur.commande(
            {
                "id": "test-feu",
                "action": "tester_feu",
                "horodatage": self.maintenant.isoformat(),
            },
            10,
        )
        for instant, couleur in ((10, "vert"), (11, "jaune"), (12, "rouge")):
            self.controleur.mettre_a_jour(instant)
            getattr(self.feu, "allumer_" + couleur).assert_called_once()
        self.controleur.mettre_a_jour(13)
        self.assertIsNone(self.controleur.fin_test)


if __name__ == "__main__":
    unittest.main()
