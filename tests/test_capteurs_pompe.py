"""Pilotes vérifiés avec des entrées simulées, sans alimenter de matériel."""
from datetime import datetime
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

from capteurs.capteur_sol import SoilSensor
from actionneurs.pompe import Pompe
from gpiozero import Device
from gpiozero.pins.mock import MockFactory


class PilotesTests(unittest.TestCase):
    def test_sol_calibration_et_acquisition_couplee(self):
        pilote = Mock()
        pilote.get_temp.return_value = 22
        pilote.moisture_read.return_value = 600
        module = types.ModuleType('adafruit_seesaw.seesaw')
        module.Seesaw = Mock(return_value=pilote)
        with patch.dict(sys.modules, {'adafruit_seesaw.seesaw': module}):
            sol = SoilSensor(object(), valeur_sec=200, valeur_humide=1000)
            mesure = sol.lire()
            self.assertEqual(mesure['humidite_pct'], 50)
            self.assertEqual(mesure['temperature_c'], 22)
            self.assertIsNotNone(datetime.fromisoformat(mesure['horodatage']).tzinfo)
            pilote.moisture_read.return_value = 1200
            self.assertEqual(sol.lire()['humidite_pct'], 100)
            pilote.moisture_read.return_value = 100
            self.assertEqual(sol.lire()['humidite_pct'], 0)
            sol_non_calibre = SoilSensor(object())
            self.assertIsNone(sol_non_calibre.lire()['humidite_pct'])
            pilote.get_temp.return_value = float('nan')
            with self.assertRaises(ValueError):
                sol.lire()

    def test_calibration_identique_refusee(self):
        module = types.ModuleType('adafruit_seesaw.seesaw')
        module.Seesaw = Mock()
        with patch.dict(sys.modules, {'adafruit_seesaw.seesaw': module}):
            with self.assertRaises(ValueError):
                SoilSensor(object(), valeur_sec=200, valeur_humide=200)

    def test_relais_inactif_demarrage_coupure_et_fermeture(self):
        ancien = Device.pin_factory
        Device.pin_factory = MockFactory()
        pompe = Pompe(17)
        try:
            self.assertFalse(pompe._sortie.is_active)
            pompe.allumer(0.05)
            self.assertTrue(pompe._sortie.is_active)
            time.sleep(0.15)
            self.assertFalse(pompe._sortie.is_active)
            pompe.allumer(3)
            pompe.fermer()
            self.assertTrue(pompe._sortie.closed)
        finally:
            if not pompe._sortie.closed:
                pompe.fermer()
            Device.pin_factory.close()
            Device.pin_factory = ancien


if __name__ == '__main__':
    unittest.main()
