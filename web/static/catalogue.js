/* SQLite catalogue client; source text is rendered with textContent only. */
const form = document.querySelector('#filters'), list = document.querySelector('#case-list');
const results = document.querySelector('#results'), prev = document.querySelector('#prev'), next = document.querySelector('#next');
const categories = {'Museums & Cultural Exhibitions':'Музеи и выставки','Brand Activations & Corporate Shows':'Бренды и события','Festivals & Public Art':'Фестивали и паблик-арт','Immersive Performance & Theatre':'Театр и перформанс'};
const statuses = {draft:'Черновик · факты не проверены',in_review:'На проверке',published:'Опубликовано',rejected:'Отклонено'};
const formats={motion_response:'Реакция на движение',generative_installation:'Генеративная среда',sensory_journey:'Сенсорный маршрут',free_roam_xr:'Свободное перемещение в VR',surround_projection:'Проекции в архитектуре'};
const techLabels={interactive_generative:'Интерактивность / генеративность',projection_mapping:'Проекции и мэппинг',spatial_audio:'Пространственный звук',xr:'XR',kinetic:'Кинетика'};
const countries=new Intl.DisplayNames(['ru'],{type:'region'});
const levels=['','Локальный фокус','Среда вокруг','Цельный опыт','Тело внутри среды'];
const level=c=>c.score_method==='editorial_immersion_v1'&&[25,50,75,100].includes(c.score)?c.score/25:null;
let page=1, requestNumber=0, featuredId=null;
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function safeLink(url,label){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return null;const a=node('a',label);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a}catch{return null}}
async function get(url){const response=await fetch(url);if(!response.ok)throw Error('Не удалось загрузить данные. Попробуйте ещё раз.');return response.json()}
function params(){const p=new URLSearchParams();for(const [k,v] of new FormData(form))if(v.trim())p.set(k,v.trim());return p}
function date(value){if(!value)return 'Неизвестно';const d=new Date(value);return Number.isNaN(d.getTime())?'Неизвестно':d.toLocaleString('ru-RU',{timeZone:'UTC'})+' UTC'}
async function fillDetail(row,body){body.replaceChildren(node('p','Загрузка…'));try{
 const c=await get('/api/events/'+encodeURIComponent(row.id));const description=node('div',undefined,'case-description');
 description.append(node('span',formats[c.format_text]||c.format_text||'Формат не указан','caption accent'),node('p',c.description));
 const n=level(c);if(n){const rating=node('div',undefined,'level');rating.append(node('strong',n+'/4'),node('span',levels[n]+' · редакционная оценка'));const guide=node('a','По каким критериям');guide.href='#rating';rating.append(guide);description.append(rating)}
 const tags=node('div',undefined,'tags');for(const t of c.tags)tags.append(node('span',t.label||formats[t.slug]||techLabels[t.slug]||t.slug.replaceAll('_',' ')));description.append(tags);
 const labels={environment:'Окружение',visitor_actions:'Действия посетителя',system_response:'Реакция пространства',visitor_role:'Роль посетителя',immersion_mechanism:'Как создаётся погружение',occurred:'Подтверждение проведения',dates:'Даты',location:'Место'};
 const values={reacts:'Реагирует',does_not_react:'Не реагирует',observer:'Наблюдатель',participant:'Участник',co_creator:'Соавтор'};
 const immersion=['immersion_mechanism','environment','visitor_actions','system_response','visitor_role'];
 const evidence=node('div',undefined,'immersion-panel');evidence.append(node('h3','Как устроено погружение'));
 const immersionClaims=immersion.flatMap(field=>c.claims.filter(claim=>claim.field===field&&claim.evidence.length));
 if(!immersionClaims.length)evidence.append(node('p','Пока нет цитат, подтверждающих признаки иммерсивности.','muted'));
 function showClaim(container,claim){container.append(node('h4',labels[claim.field]||claim.field),node('p',values[claim.value]||claim.value));for(const e of claim.evidence){container.append(node('blockquote',e.quote));const a=safeLink(e.url,'Источник цитаты');if(a)container.append(a)}}
 for(const claim of immersionClaims)showClaim(evidence,claim);
 description.append(evidence);
 for(const claim of c.claims.filter(claim=>!immersion.includes(claim.field)))showClaim(description,claim);
 const aside=node('aside');aside.append(node('span',(n&&c.moderation_status==='published'?'Редакционная подборка':statuses[c.moderation_status]||c.moderation_status),'caption'));
 const source=safeLink(c.source_url,(c.proofs.find(p=>p.url===c.source_url)?.title||'Первоисточник')+'');if(source)aside.append(source);
 aside.append(node('p',c.location_text||[c.country_code?countries.of(c.country_code):null,c.city,c.venue].filter(Boolean).join(', ')||'Место не указано','muted'));
 let videos=0;for(const p of c.proofs){if(p.url===c.source_url)continue;const a=safeLink(p.url,p.kind==='video'?`Видео ${++videos}`:(p.title||'Дополнительный источник')+'');if(a)aside.append(a)}
 if(!videos)aside.append(node('p','Видео пока не добавлены.','muted'));else aside.append(node('p','Ссылки на видео требуют отдельной проверки.','muted'));
 body.replaceChildren(description,aside);body.dataset.loaded='true';
 }catch(error){const retry=node('button','Повторить');retry.type='button';retry.onclick=()=>fillDetail(row,body);body.replaceChildren(node('p',error.message),retry)}}
async function load(){const number=++requestNumber;list.setAttribute('aria-busy','true');results.textContent='Загрузка…';prev.disabled=true;next.disabled=true;
 const query=params();query.set('page',page);query.set('per_page','20');
 try{const data=await get('/api/events?'+query);if(number!==requestNumber)return;list.replaceChildren();
 for(const [i,row]of data.items.entries()){const d=node('details',undefined,'case'),s=node('summary'),name=node('span',undefined,'case-name');
 name.append(node('span',row.title,'case-title'),node('span',[row.city,row.country_code?countries.of(row.country_code):null].filter(Boolean).join(' · ')||'Место в описании карточки','case-place'));
 const n=level(row);
 if(n)name.append(node('span',n+'/4 · '+levels[n],'immersion-badge'));
 else if(row.has_mechanism)name.append(node('span','Механизм с цитатой','immersion-badge'));
 s.append(node('span',String((page-1)*20+i+1).padStart(2,'0'),'case-number caption'),name,node('span',formats[row.format_text]||categories[row.category]||row.category||'Не указана','case-category'),node('span',String(row.reported_year||'—'),'case-year'));
 d.id='case-'+row.id;const body=node('div',undefined,'case-body');d.append(s,body);d.addEventListener('toggle',()=>{if(d.open&&!body.dataset.loaded&&!body.dataset.loading){body.dataset.loading='true';fillDetail(row,body).finally(()=>delete body.dataset.loading)}});list.append(d)}
 if(!data.items.length){const empty=node('div',undefined,'empty');empty.append(node('h3','Кейсы не найдены.'),node('p','Попробуйте сбросить фильтры. В обычном режиме видны только опубликованные карточки.'));list.append(empty)}
 results.textContent=`Показано ${data.items.length} из ${data.total}`;prev.disabled=page<=1;next.disabled=page*20>=data.total;
 document.querySelector('#page-label').textContent=`Страница ${page} из ${Math.max(1,Math.ceil(data.total/20))}`;
 const download=params();download.set('format','json');document.querySelector('#filtered-download').href='/api/export?'+download;
 const address=params();if(page>1)address.set('page',page);history.replaceState(null,'',location.pathname+(address.size?'?'+address:'')+location.hash);
 }catch(error){if(number!==requestNumber)return;results.textContent=error.message;const retry=node('button','Повторить загрузку');retry.onclick=load;list.replaceChildren(retry)}finally{if(number===requestNumber)list.setAttribute('aria-busy','false')}}
form.addEventListener('submit',e=>{e.preventDefault();page=1;load()});document.querySelector('#reset').onclick=()=>{form.reset();page=1;load()};prev.onclick=()=>{if(page>1){page--;load()}};next.onclick=()=>{page++;load()};
async function init(){const initial=new URLSearchParams(location.search);try{
 const [options,info,status,all]=await Promise.all([get('/api/filters'),get('/api/info'),get('/api/collection-status'),get('/api/events?per_page=1')]);
 for(const [field,items]of [['country',options.countries],['year',options.years],['tag',options.tags]])for(const item of items){const option=node('option',typeof item==='object'?(item.label||formats[item.slug]||techLabels[item.slug]||item.slug.replaceAll('_',' ')):(field==='country'?countries.of(item):String(item)));option.value=typeof item==='object'?item.slug:String(item);form.elements[field].append(option)}
 document.querySelector('#total').textContent=all.total+' '+({one:'кейс',few:'кейса',many:'кейсов',other:'кейса'}[new Intl.PluralRules('ru').select(all.total)]);
 for(const button of document.querySelectorAll('[data-tag]')){button.disabled=!options.tags.some(t=>t.slug===button.dataset.tag);button.onclick=()=>{form.reset();form.elements.tag.value=button.dataset.tag;page=1;load();document.querySelector('#archive').scrollIntoView()}}
 const featured=document.querySelector('#featured-case');
 get('/api/events?q=Rain+Room&per_page=1').then(r=>{const found=r.items.find(row=>row.title==='Rain Room'&&row.country_code==='AE');if(!found)return;featuredId=found.id;featured.textContent='Rain Room · Шарджа';featured.onclick=async e=>{e.preventDefault();form.reset();form.elements.q.value='Rain Room';page=1;await load();const card=document.getElementById('case-'+featuredId);if(card){card.open=true;card.querySelector('summary').focus({preventScroll:true});card.scrollIntoView()}else document.querySelector('#archive').scrollIntoView()}}).catch(()=>{});
document.querySelector('#preview-note').hidden=info.visibility!=='local_preview_all_statuses';
 document.querySelector('#last-import').textContent=date(status.last_import?.started_at);document.querySelector('#last-success').textContent=date(status.last_successful_import?.finished_at);document.querySelector('#last-collection').textContent=date(status.last_collection_at);
 document.querySelector('#import-status').textContent=({succeeded:'Завершён',failed:'Ошибка',partial:'Частично',running:'Выполняется'})[status.last_import?.status]||'Нет запусков';
 }catch{document.querySelector('#last-import').textContent='Не удалось загрузить';document.querySelector('#import-status').textContent='Нет связи';document.querySelector('#total').textContent='—'}
 for(const [k,v]of initial)if(form.elements[k])form.elements[k].value=v;
 const n=Number(initial.get('page'));page=Number.isInteger(n)&&n>0&&n<=1000000?n:1;load()}
init();
