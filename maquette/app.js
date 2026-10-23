const $=s=>document.querySelector(s), model=PousseSimulation;
let toastTimer,busy=false,testRunning=false,pumpTimer,countdownTimer,remaining=0,pumpType=null;
function notify(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),6000)}
let state;try{state=JSON.parse(localStorage.getItem('pousse-simulation-v2'))}catch{}
state=state||model.defaults();
function save(){try{localStorage.setItem('pousse-simulation-v2',JSON.stringify(state))}catch{}}
function time(at){return new Date(at).toLocaleString('fr-CA',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}
function hours(value){let minutes=Math.round(value*60);return `${Math.floor(minutes/60)} h ${String(minutes%60).padStart(2,'0')}`}
const scenarios={normal:{humidity:46,hours:6.4,lux:12480,empty:false},dry:{humidity:24,hours:6.4,lux:12480,empty:false},water:{humidity:46,hours:6.4,lux:12480,empty:true},dark:{humidity:46,hours:2,lux:1800,empty:false},watchsoil:{humidity:35,hours:6.4,lux:12480,empty:false},watchlight:{humidity:46,hours:4.5,lux:8000,empty:false},multiple:{humidity:24,hours:2,lux:900,empty:true}};
const panel=document.createElement('details');panel.className='simulator';panel.open=true;
panel.innerHTML=`<summary>Laboratoire de simulation <span>Aucun matériel connecté</span></summary><div class="scenario-buttons"><button data-scenario="normal">Tout va bien</button><button data-scenario="water">Manque d’eau</button><button data-scenario="dry">Sol sec</button><button data-scenario="dark">Manque de lumière</button><button data-scenario="watchsoil">Sol à surveiller</button><button data-scenario="watchlight">Lumière à surveiller</button><button data-scenario="multiple">Alertes combinées</button></div><div class="sim-fields"><label>Humidité (%)<input id="sim-humidity" type="number" min="0" max="100" step="0.1"></label><label>Température (°C)<input id="sim-temperature" type="number" min="-20" max="60" step="0.1"></label><label>Lumière actuelle (lux)<input id="sim-lux" type="number" min="0" max="200000"></label><label>Lumière reçue (h / jour)<input id="sim-hours" type="number" min="0" max="24" step="0.1"></label><label class="sim-check"><input id="sim-empty" type="checkbox"> Réservoir insuffisant</label></div><div class="sim-actions"><button class="button primary" id="reading">Simuler la prochaine lecture</button><button class="button" id="advance">Avancer de 30 min</button><button class="button" id="limit">Simuler 6 arrosages / 24 h</button><button class="button" id="reset">Réinitialiser</button></div><p>Les scénarios représentent une nouvelle lecture. Le cumul reçu détermine le feu, pas les lux instantanés. Avancer de 30 min ajoute de la lumière seulement si le seuil configuré est atteint.</p>`;
$('.heading').after(panel);
const banner=document.createElement('section');banner.className='state-banner';banner.setAttribute('aria-live','polite');panel.after(banner);
const actuators=document.createElement('section');actuators.className='actuators card';
actuators.innerHTML=`<div class="section-head"><h2>Pompe et relais</h2><span>Simulation · aucun matériel connecté</span></div><div class="actuator-circuit"><div class="actuator-node"><span class="actuator-icon">▤</span><b>Réservoir</b><span id="tank-state"></span></div><span class="circuit-link">→</span><div class="actuator-node"><span class="actuator-icon">⏻</span><b>Relais</b><span id="relay-state"></span></div><span class="circuit-link">→</span><div class="actuator-node"><span class="actuator-icon rotor">✳</span><b>Pompe</b><span id="pump-state"></span></div><span class="circuit-link">→</span><div class="actuator-node"><span class="actuator-icon">❧</span><b>Basilic</b><span id="pump-countdown"></span></div></div><p id="actuator-detail" aria-live="polite"></p><div class="sim-actions"><button class="button primary" id="actuator-water">Arroser maintenant · 3 s</button><button class="button" id="actuator-test">Tester pompe et relais · 3 s</button><button class="button" id="actuator-stop" disabled>Arrêter la pompe</button></div>`;
banner.after(actuators);
function renderActuators(){
 actuators.dataset.running=String(busy);actuators.dataset.blocked=String(state.empty);
 $('#tank-state').textContent=state.empty?'Insuffisant':'Suffisant';
 $('#relay-state').textContent=busy?'Activé · circuit fermé':'Désactivé · circuit ouvert';
 $('#pump-state').textContent=busy?'En marche':state.empty?'Bloquée · manque d’eau':'À l’arrêt';
 $('#pump-countdown').textContent=busy?`${remaining} s restantes`:'En attente';
 $('#actuator-detail').textContent=busy?`${pumpType==='test'?'Test':pumpType==='auto'?'Arrosage automatique':'Arrosage manuel'} en cours. Le relais alimente la pompe simulée.`:state.empty?'Sécurité active : remplissez le réservoir avant tout arrosage ou test.':'Relais désactivé : la pompe ne reçoit pas d’alimentation. Le débit réel n’est pas mesuré.';
 for(const id of ['actuator-water','actuator-test'])$('#'+id).disabled=busy||state.empty;
 $('#actuator-stop').disabled=!busy;
}
function controls(){for(const key of ['humidity','temperature','lux','hours'])$('#sim-'+key).value=state[key];$('#sim-empty').checked=state.empty}
function render(){
 const status=model.status(state), recent=model.recent(state), last=recent.at(-1), auto=model.automatic(state);
 renderActuators();
 document.body.dataset.state=status.level;
 banner.innerHTML=`<div class="state-title"><span class="state-dot"></span><h2>${status.label}</h2><span>Feu ${status.level==='red'?'rouge':status.level==='yellow'?'jaune':'vert'} · ${time(state.now)}</span></div><ul>${(status.reasons.length?status.reasons:['Le basilic a un sol suffisamment humide, au moins 6 h de lumière et un réservoir suffisant.']).map(r=>`<li>${r}</li>`).join('')}</ul><p class="light-now">${state.lux>=state.settings.light?'Lumière actuelle suffisante : le cumul peut progresser.':'Lumière actuelle trop faible : le cumul ne progresse pas.'}</p><div class="pump-state">${busy?'Pompe simulée en marche…':auto==='ready'?'Sol sec : arrosage automatique au prochain cycle simulé.':auto}</div>`;
 const plant=$('.plant-card');if(plant){plant.querySelector('.pill').textContent='● '+status.label;plant.querySelector('p').textContent=status.level==='green'?'Toutes les conditions sont réunies pour grandir.':status.level==='yellow'?'Votre basilic a besoin d’un peu d’attention.':'Une intervention est nécessaire pour votre basilic.';
 const cards=document.querySelectorAll('.metrics .card');cards[0].querySelector('strong').innerHTML=`${state.humidity} <small>%</small>`;cards[0].querySelector('i').style.width=state.humidity+'%';cards[0].querySelector('p').textContent=`Seuil d’arrosage configuré : ${state.settings.humidity} %`;
 cards[1].querySelector('strong').innerHTML=`${state.temperature.toLocaleString('fr-CA')} <small>°C</small>`;cards[1].querySelector('p').textContent='Dernière lecture · '+time(state.now);
 cards[2].querySelector('strong').innerHTML=`${state.lux.toLocaleString('fr-CA')} <small>lux</small>`;cards[2].querySelector('p').textContent=`Lumière suffisante dès ${state.settings.light} lux`;
 cards[3].querySelector('strong').textContent=state.empty?'Insuffisant':'Suffisant';cards[3].querySelector('p').textContent=state.empty?'Remplissez le réservoir · pompe bloquée':'La plante peut être arrosée';
 $('.sun-total b').textContent=hours(state.hours);$('.sun-total').nextElementSibling.querySelector('i').style.width=Math.min(100,state.hours/8*100)+'%';$('.sun-total').nextElementSibling.nextElementSibling.textContent=state.hours>=6?'Objectif minimal de 6 h atteint.':'Encore '+hours(6-state.hours)+' pour atteindre 6 h.';
 const waterCard=$('.two').lastElementChild;waterCard.querySelector('.pill').textContent=state.auto?'Automatique activé':'Automatique désactivé';waterCard.querySelector('p').textContent=last?'Dernier arrosage · '+time(last.at):'Aucun arrosage simulé dans les dernières 24 h';waterCard.querySelector('b').textContent=recent.length+' arrosages / 24 h';
 }
 if($('#water-state')){$('#water-state').textContent=state.empty?'● Réservoir insuffisant · arrosage bloqué':'● Réservoir suffisant';$('#empty').checked=state.empty;$('#auto').checked=state.auto;$('#auto-label').textContent=state.auto?'Activé · '+(auto==='ready'?'arrosage nécessaire au prochain cycle.':auto):'Désactivé · aucune activation automatique.';
 const rules=document.querySelectorAll('.stack .card:first-child .rule b');rules[0].textContent=`Humidité sous ${state.settings.humidity} %`;rules[1].textContent=state.settings.duration+' secondes';
 const history=$('#watering-summary').parentElement;history.querySelectorAll('.rule').forEach(e=>e.remove());recent.slice(-5).reverse().forEach(e=>{const row=document.createElement('div');row.className='rule';row.textContent=`${time(e.at)} · ${e.type==='auto'?'automatique':'manuel'} · ${typeof e.duration==='number'?e.duration+' s':e.duration}`;history.insertBefore(row,$('#watering-summary'))});$('#watering-summary').textContent=`${recent.length} arrosages / 24 h, dont ${recent.filter(e=>e.type==='auto').length} automatiques sur un maximum de 6. ${auto==='ready'?'Arrosage automatique possible.':auto}`;
 }
 for(const id of ['water','test-pump'])if($('#'+id)){$('#'+id).disabled=busy||state.empty;$('#'+id).title=state.empty?'Remplissez le réservoir pour autoriser la pompe.':''}
 if(!testRunning)document.querySelectorAll('.traffic i').forEach((e,i)=>e.classList.toggle('active',i===({green:0,yellow:1,red:2}[status.level])));
 if($('.bars')){const bar=$('.bars').lastElementChild;bar.querySelector('span').textContent=hours(state.hours);bar.querySelector('i').style.height=Math.min(state.hours,8)*17+'px'}
 $('footer').lastElementChild.textContent='Dernière mesure simulée · '+time(state.now);
 save();
}
function stopPump(interrupted=false){
 if(!busy)return;clearTimeout(pumpTimer);clearInterval(countdownTimer);
 const type=pumpType,duration=type==='auto'?state.settings.duration:3;
 busy=false;remaining=0;
 if(type!=='test'){state.events.push({at:state.now,type,duration:interrupted?'interrompu':duration});if(type==='auto')state.lastAuto=state.now;}
 pumpType=null;render();notify(state.empty?'Pompe coupée : réservoir insuffisant. Relais désactivé.':interrupted?'Pompe arrêtée manuellement. Relais désactivé.':'Cycle terminé : relais désactivé, pompe arrêtée et réservoir vérifié. Simulez une nouvelle lecture du sol.');
}
function pump(type){
 if(state.empty){notify('Activation refusée : réservoir insuffisant.');return}if(busy)return;
 pumpType=type;remaining=type==='auto'?state.settings.duration:3;busy=true;render();
 notify(`Relais activé : pompe simulée en marche pendant ${remaining} secondes.`);
 countdownTimer=setInterval(()=>{remaining=Math.max(0,remaining-1);renderActuators()},1000);
 pumpTimer=setTimeout(()=>stopPump(),remaining*1000);
}
$('#actuator-water').addEventListener('click',()=>pump('manual'));
$('#actuator-test').addEventListener('click',()=>pump('test'));
$('#actuator-stop').addEventListener('click',()=>stopPump(true));
function cycle(){render();if(model.automatic(state)==='ready')pump('auto')}
controls();render();
for(const button of document.querySelectorAll('[data-scenario]'))button.addEventListener('click',()=>{if(busy){notify('Attendez la fin des 3 secondes avant de changer de scénario.');return}Object.assign(state,scenarios[button.dataset.scenario]);controls();cycle()});
$('#reading').addEventListener('click',()=>{if(busy)return;for(const key of ['humidity','temperature','lux','hours']){const field=$('#sim-'+key);if(!field.reportValidity())return;}for(const key of ['humidity','temperature','lux','hours'])state[key]=Number($('#sim-'+key).value);state.empty=$('#sim-empty').checked;cycle()});
$('#advance').addEventListener('click',()=>{if(busy)return;const day=new Date(state.now).toDateString();state.now+=1800000;if(day!==new Date(state.now).toDateString())state.hours=0;else if(state.lux>=state.settings.light)state.hours=Math.min(24,state.hours+.5);controls();cycle()});
$('#limit').addEventListener('click',()=>{if(busy)return;state.events=state.events.filter(e=>e.type!=='auto');for(let i=0;i<6;i++)state.events.push({at:state.now-(6-i)*3600000,type:'auto',duration:3});state.events.sort((a,b)=>a.at-b.at);state.lastAuto=state.now-3600000;render();notify('Six arrosages automatiques simulés dans les dernières 24 heures.');});
$('#reset').addEventListener('click',()=>{if(busy)return;state=model.defaults();controls();render();if($('#settings'))for(const key of ['humidity','light','duration'])$('#settings').elements[key].value=state.settings[key];notify('Simulation réinitialisée : basilic à l’état normal.');});
if($('#water')){$('#water').addEventListener('click',()=>pump('manual'));$('#empty').addEventListener('change',()=>{state.empty=$('#empty').checked;if(state.empty&&busy)stopPump(true);controls();cycle()});$('#auto').addEventListener('change',()=>{state.auto=$('#auto').checked;cycle()})}
if($('#settings')){const form=$('#settings');for(const key of ['humidity','light','duration'])form.elements[key].value=state.settings[key];form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;for(const key of ['humidity','light','duration'])state.settings[key]=Number(form.elements[key].value);render();notify('Paramètres appliqués à la simulation. Les seuils du feu restent ceux des exigences EF10 à EF12.');});$('#test-pump').addEventListener('click',()=>pump('test'));$('#test-light').addEventListener('click',async()=>{const button=$('#test-light');button.disabled=true;testRunning=true;const lights=[...document.querySelectorAll('.traffic i')];lights.forEach(l=>l.classList.remove('active'));for(const light of lights){light.classList.add('active');await new Promise(r=>setTimeout(r,700));light.classList.remove('active')}testRunning=false;button.disabled=false;render();notify('Test terminé : retour à la couleur correspondant à la plante.');});}
