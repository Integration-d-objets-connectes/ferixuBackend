/* Règles de démonstration issues de EF04 à EF15. Aucune commande matérielle. */
(function(root){
 const defaults=()=>({humidity:46,temperature:22.4,lux:12480,hours:6.4,empty:false,auto:true,now:Date.now(),events:[],lastAuto:null,settings:{humidity:30,light:10000,duration:3}});
 function status(s){const urgent=[],watch=[];
  if(s.empty)urgent.push('Réservoir insuffisant : remplissez-le. Toute activation de la pompe est bloquée.');
  if(s.humidity<30)urgent.push('Sol trop sec : humidité sous 30 %. Un arrosage est nécessaire.');
  else if(s.humidity<40)watch.push('Humidité entre 30 % et moins de 40 % : surveillez le sol.');
  if(s.hours<3.6)urgent.push('Lumière quotidienne insuffisante : moins de 3 h 36 reçues. Rapprochez le basilic d’une source lumineuse.');
  else if(s.hours<6)watch.push('Objectif lumineux non atteint : entre 3 h 36 et moins de 6 h reçues.');
  return {level:urgent.length?'red':watch.length?'yellow':'green',label:urgent.length?'Urgent':watch.length?'À surveiller':'Normal',reasons:[...urgent,...watch]};
 }
 const recent=s=>s.events.filter(e=>e.at>s.now-86400000&&e.at<=s.now);
 function automatic(s){
  if(s.empty)return 'Bloqué : réservoir insuffisant.';
  if(!s.auto)return 'Mode automatique désactivé.';
  if(recent(s).filter(e=>e.type==='auto').length>=6)return 'Limite de 6 arrosages automatiques sur 24 h atteinte.';
  if(s.lastAuto!==null&&s.now<s.lastAuto+1800000)return 'Délai actif : prochain arrosage possible à '+new Date(s.lastAuto+1800000).toLocaleTimeString('fr-CA',{hour:'2-digit',minute:'2-digit'})+'.';
  if(s.humidity>=s.settings.humidity)return 'En attente : le sol ne nécessite pas d’arrosage automatique.';
  return 'ready';
 }
 const api={defaults,status,recent,automatic};root.PousseSimulation=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
