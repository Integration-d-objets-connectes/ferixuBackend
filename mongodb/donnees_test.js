// Exécuter avec mongosh sur une instance MongoDB locale.
const base = db.getSiblingDB('ferixu_demo');
const planteId = 1;
const minute = 60_000;
const fin = Math.floor(Date.now() / (10 * minute)) * 10 * minute;
const dateIlYa = (minutes) => new Date(fin - minutes * minute);

function ajouterMesures(nom, granularite, mesures) {
  if (!base.getCollectionNames().includes(nom)) {
    base.createCollection(nom, {
      timeseries: {
        timeField: 'horodatage',
        metaField: 'plante_id',
        granularity: granularite,
      },
    });
  }

  const collection = base.getCollection(nom);
  const datesExistantes = new Set(collection.find({
    plante_id: planteId,
    horodatage: { $gte: mesures[0].horodatage, $lte: dateIlYa(0) },
  }, { horodatage: 1, _id: 0 }).map(({ horodatage }) => horodatage.getTime()).toArray());

  const nouvelles = mesures.filter(({ horodatage }) => !datesExistantes.has(horodatage.getTime()));
  if (nouvelles.length) collection.insertMany(nouvelles);
}

const mesuresSol = [];
const mesuresLumiere = [];
for (let recul = 720; recul >= 0; recul--) {
  const horodatage = dateIlYa(recul);
  const progression = (720 - recul) / 720;
  const lux = Math.round(250 + 18_000 * Math.sin(Math.PI * progression * 0.8));
  mesuresLumiere.push({ plante_id: planteId, horodatage, lux });

  if (recul % 10 === 0) {
    const humiditeBrut = recul > 90 ? Math.round(575 - 60 * progression) : 690 - (90 - recul);
    mesuresSol.push({
      plante_id: planteId,
      horodatage,
      temperature_c: Number((19.8 + 3.4 * progression).toFixed(1)),
      humidite_brut: humiditeBrut,
      humidite_pct: Math.round(100 * (humiditeBrut - 340) / (1016 - 340)),
    });
  }
}

ajouterMesures('Lumiere', 'minutes', mesuresLumiere);
ajouterMesures('Temperature_humidite', 'seconds', mesuresSol);

const parametres = { humidite_min: 30, lux_min: 10_000, duree_arrosage: 3, automatique: true };
const dernierArrosage = dateIlYa(90);
for (const arrosage of [
  { _id: 'demo-auto', horodatage: dateIlYa(630), auto: true, mode: 'automatique' },
  { _id: 'demo-manuel', horodatage: dernierArrosage, auto: false, mode: 'manuel' },
]) {
  base.Arrosage.replaceOne({ _id: arrosage._id }, { ...arrosage, plante_id: planteId }, { upsert: true });
}

for (const evenement of [
  { _id: 'demo-configuration', horodatage: dateIlYa(690), type: 'configuration', details: parametres },
  {
    _id: 'demo-commande', horodatage: dernierArrosage, type: 'commande',
    details: { id: 'demo-arrosage', action: 'arroser', succes: true, message: 'Commande exécutée.' },
  },
]) {
  base.Evenement.replaceOne({ _id: evenement._id }, { ...evenement, plante_id: planteId }, { upsert: true });
}

const { temperature_c, humidite_brut, humidite_pct } = mesuresSol.at(-1);
base.Plante.updateOne({ id: planteId }, { $set: {
  nom: 'Basilic de démonstration',
  temperature_c,
  humidite_brut,
  humidite_pct,
  lux: mesuresLumiere.at(-1).lux,
  eau_vide: false,
  dernier_arrosage: dernierArrosage,
  horodatage: dateIlYa(0),
  intervalle_arrosage: 30,
  seuil_humidite: parametres.humidite_min,
  seuil_luminosite: parametres.lux_min,
  utilisateur_id: null,
} }, { upsert: true });

print(`Données de démonstration prêtes dans ${base.getName()} (plante ${planteId}).`);
