"""Vérification des règles du projet sans Raspberry Pi ni broker."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from controleur import Controleur, ErreurPersistance


class ReglesBackendTests(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.chemin = Path(self.dossier.name) / 'etat.json'
        self.date = datetime(2026, 10, 20, 16, tzinfo=timezone.utc)
        self.flotteur = Mock()
        self.flotteur.lire.side_effect = lambda: {
            'etat': 'suffisant', 'vide': False, 'horodatage': self.date.isoformat()}
        self.pompe = Mock(disponible=True)
        self.feu = Mock()
        self.messages = []
        self.c = Controleur(self.chemin, self.flotteur, self.pompe, self.feu,
                            lambda n, m: self.messages.append((n, m)), lambda: self.date)
        self.c.etat['parametres']['automatique'] = True
        self.sol(20)
        self.c.lire_eau()
        self.lumiere(10000)

    def sol(self, humidite):
        self.c.recevoir('sol', {'humidite_pct': humidite, 'temperature_c': 22,
                              'horodatage': self.date.isoformat()})

    def lumiere(self, lux):
        self.c.recevoir('lumiere', {'lux': lux, 'horodatage': self.date.isoformat()})

    def heures(self, valeur):
        self.c.etat['lumiere_jours'][str(self.date.astimezone(self.c.zone).date())] = valeur * 3600

    def commande(self, action, **valeurs):
        return {'id': 'test-1', 'horodatage': self.date.isoformat(), 'action': action, **valeurs}

    def test_arrosage_auto_sous_seuil_et_coupure(self):
        self.assertTrue(self.c.arroser('automatique', 10))
        self.pompe.allumer.assert_called_once_with(3)
        self.c.mettre_a_jour(13)
        self.pompe.eteindre.assert_called_once()
        self.assertIsNone(self.c.fin_pompe)
        self.assertGreaterEqual(self.flotteur.lire.call_count, 4)

    def test_seuil_exact_ne_declenche_pas(self):
        self.sol(30)
        self.assertFalse(self.c.arroser('automatique', 0))
        self.pompe.allumer.assert_not_called()

    def test_mode_desactive(self):
        self.c.etat['parametres']['automatique'] = False
        self.assertFalse(self.c.arroser('automatique', 0))

    def test_sol_non_calibre_ou_perime_refuse_auto(self):
        self.sol(None)
        self.assertFalse(self.c.arroser('automatique', 0))
        self.sol(20)
        self.date += timedelta(seconds=661)
        self.assertFalse(self.c.arroser('automatique', 0))

    def test_eau_vide_refuse_tous_modes(self):
        self.flotteur.lire.side_effect = lambda: {
            'etat': 'insuffisant', 'vide': True, 'horodatage': self.date.isoformat()}
        for mode in ('automatique', 'manuel', 'test'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.c.arroser(mode, 0)
        self.pompe.allumer.assert_not_called()

    def test_erreur_flotteur_refuse_manuel_et_test(self):
        self.flotteur.lire.side_effect = OSError('débranché')
        for mode in ('manuel', 'test'):
            with self.assertRaises(ValueError):
                self.c.arroser(mode, 0)
        self.pompe.allumer.assert_not_called()

    def test_eau_perdue_coupe_pompe(self):
        self.c.arroser('manuel', 0)
        self.flotteur.lire.side_effect = OSError('débranché')
        self.c.mettre_a_jour(1)
        self.pompe.eteindre.assert_called_once()
        self.assertIsNone(self.c.fin_pompe)

    def test_pompe_non_configuree(self):
        self.pompe.disponible = False
        with self.assertRaises(ValueError):
            self.c.arroser('manuel', 0)

    def test_delai_trente_minutes_apres_fin(self):
        self.c.arroser('automatique', 0)
        self.c.mettre_a_jour(3)
        self.date += timedelta(minutes=30)
        self.sol(20)
        self.assertFalse(self.c.arroser('automatique', 1800))
        self.date += timedelta(seconds=3)
        self.assertTrue(self.c.arroser('automatique', 1803))

    def test_limite_six_sur_24h_persiste_au_redemarrage(self):
        self.c.etat['arrosages'] = [
            {'mode': 'automatique', 'horodatage': (self.date - timedelta(hours=i+1)).isoformat(), 'duree': 3}
            for i in reversed(range(6))]
        self.c.sauvegarder()
        self.c = Controleur(self.chemin, self.flotteur, self.pompe, self.feu,
                            lambda n, m: None, lambda: self.date)
        self.sol(20)
        self.assertFalse(self.c.arroser('automatique', 0))
        self.c.etat['arrosages'][0]['horodatage'] = (self.date - timedelta(hours=24)).isoformat()
        self.assertTrue(self.c.arroser('automatique', 0))

    def test_manuel_possible_sans_mode_auto(self):
        self.c.etat['parametres']['automatique'] = False
        self.c.commande(self.commande('arroser'), 0)
        self.pompe.allumer.assert_called_once_with(3)

    def test_couleurs_priorite_rouge_et_seuils(self):
        for humidite, heures, couleur in ((40, 6, 'vert'), (39.9, 6, 'jaune'),
                (30, 6, 'jaune'), (29.9, 6, 'rouge'), (40, 3.6, 'jaune'),
                (40, 3.59, 'rouge')):
            with self.subTest(humidite=humidite, heures=heures):
                self.sol(humidite)
                self.heures(heures)
                self.assertEqual(self.c.couleur(), couleur)
        self.c.mesures['eau']['etat'] = 'insuffisant'
        self.assertEqual(self.c.couleur(), 'rouge')

    def test_mesure_manquante_ne_donne_pas_vert(self):
        self.sol(None)
        self.heures(6)
        self.assertEqual(self.c.couleur(), 'inconnu')
        self.c.mettre_a_jour(0)
        self.feu.eteindre.assert_called_once()

    def test_cumul_lumiere_seuil_et_trou(self):
        self.date += timedelta(seconds=60)
        self.lumiere(9999)
        self.assertAlmostEqual(self.c.heures_jour(), 60 / 3600)
        self.date += timedelta(seconds=60)
        self.lumiere(10000)
        self.assertAlmostEqual(self.c.heures_jour(), 60 / 3600)
        self.date += timedelta(seconds=120)
        self.lumiere(10000)
        self.assertAlmostEqual(self.c.heures_jour(), 60 / 3600)

    def test_lumiere_partagee_a_minuit(self):
        self.date = datetime(2026, 10, 21, 3, 59, 30, tzinfo=timezone.utc)
        self.lumiere(10000)
        self.date += timedelta(seconds=60)
        self.lumiere(10000)
        self.assertEqual(self.c.etat['lumiere_jours']['2026-10-20'], 30)
        self.assertEqual(self.c.etat['lumiere_jours']['2026-10-21'], 30)
        self.assertEqual(len(self.c.statut()['lumiere_jours']), 7)

    def test_parametres_persistants_et_appliques(self):
        self.c.commande(self.commande('parametres', parametres={
            'humidite_min': 25, 'lux_min': 12000, 'duree_arrosage': 2,
            'automatique': False}), 0)
        autre = Controleur(self.chemin, self.flotteur, self.pompe, self.feu, lambda n,m: None)
        self.assertEqual(autre.etat['parametres']['humidite_min'], 25)
        self.c.arroser('manuel', 0)
        self.pompe.allumer.assert_called_once_with(2)

    def test_duree_invalide_refusee(self):
        for duree in (0, 4, float('nan'), True):
            commande = self.commande('parametres', parametres={'duree_arrosage': duree})
            commande['id'] = str(duree)
            with self.subTest(duree=duree), self.assertRaises(ValueError):
                self.c.commande(commande, 0)
        self.assertEqual(self.c.etat['parametres']['duree_arrosage'], 3)

    def test_commande_expiree_ou_double(self):
        commande = self.commande('tester_feu')
        self.c.commande(commande, 0)
        with self.assertRaises(ValueError):
            self.c.commande(commande, 0)
        self.date += timedelta(seconds=31)
        commande['id'] = 'autre'
        with self.assertRaises(ValueError):
            self.c.commande(commande, 0)

    def test_test_feu_retour_automatique(self):
        self.c.commande(self.commande('tester_feu'), 0)
        self.c.mettre_a_jour(0)
        self.feu.allumer_vert.assert_called_once()
        self.c.mettre_a_jour(1)
        self.feu.allumer_jaune.assert_called_once()
        self.c.mettre_a_jour(2)
        self.feu.allumer_rouge.assert_called_once()
        self.c.mettre_a_jour(3)
        self.assertIsNone(self.c.fin_test)
        self.assertEqual(self.feu.allumer_rouge.call_count, 2)

    def test_statut_est_un_instantane_independant(self):
        statut = self.c.statut()
        self.sol(80)
        self.c.erreurs['sol'] = 'débranché'
        self.assertEqual(statut['mesures']['sol']['humidite_pct'], 20)
        self.assertEqual(statut['erreurs'], {})

    def test_echec_persistance_ne_demarre_pas_pompe(self):
        self.c.chemin = Path(self.dossier.name)  # écrire un fichier sur un dossier échoue
        with self.assertRaises(ErreurPersistance):
            self.c.arroser('manuel', 0)
        self.pompe.allumer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
