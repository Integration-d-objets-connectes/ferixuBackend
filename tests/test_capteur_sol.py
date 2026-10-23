"""Calibration du sol avec pilotes matériels simulés."""

import importlib
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch


class CalibrationTests(unittest.TestCase):
    def test_conversion_bornes_et_absence_de_calibration(self):
        gpio = ModuleType("gpiozero")
        gpio.Button = Mock()
        seesaw_package = ModuleType("adafruit_seesaw")
        seesaw_module = ModuleType("adafruit_seesaw.seesaw")
        seesaw_module.Seesaw = Mock()
        with patch.dict(
            sys.modules,
            {
                "gpiozero": gpio,
                "adafruit_seesaw": seesaw_package,
                "adafruit_seesaw.seesaw": seesaw_module,
            },
        ):
            classe = importlib.import_module("capteurs.capteur_sol").SoilSensor
            capteur = classe(Mock(), valeur_sec=340, valeur_humide=1016)
            for brute, attendu in (
                (0, 0),
                (340, 0),
                (678, 50),
                (1016, 100),
                (2000, 100),
            ):
                with self.subTest(brute=brute):
                    self.assertEqual(capteur.convertir_humidite_pct(brute), attendu)
            self.assertIsNone(classe(Mock()).convertir_humidite_pct(678))
            inverse = classe(Mock(), valeur_sec=1016, valeur_humide=340)
            self.assertEqual(inverse.convertir_humidite_pct(678), 50)
            with self.assertRaises(ValueError):
                classe(Mock(), valeur_sec=340, valeur_humide=340)
