const $ = id => document.getElementById(id);
let jobId, job, timer;
const csrf = document.querySelector('meta[name=csrf]').content;
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
  let data;
  try { data = await response.json(); } catch { throw new Error('Server response unavailable. Reload and try again.'); }
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}
function notice(text='') { $('notice').textContent = text; }
function action(id, fn) { $(id).addEventListener('click', async () => { const button=$(id); button.disabled=true; notice(); try { await fn(); } catch(e) {notice(e.message);} finally {button.disabled=false;} }); }
async function status() {
  const data=await api('/api/status');
  for(const [p,s] of Object.entries(data.providers)) {
    $(p+'-state').textContent=s.connected?'Connected':s.configured?'Ready to connect':'Setup required';
    $(p+'-connect').textContent=s.connected?'Reconnect ↗':s.configured?'Connect '+(p==='spotify'?'Spotify':'YouTube')+' ↗':'Configure OAuth in .env ↗';
  }
}
function collections(items) {
  $('collections').className=''; $('collections').replaceChildren();
  for(const c of items) {
    const label=document.createElement('label');label.className='collection';
    const input=document.createElement('input');input.type='checkbox';input.value=c.id;input.disabled=c.readable===false;
    label.append(input, document.createTextNode(c.name));
    const kind=document.createElement('small');kind.textContent=c.readable===false?'Unavailable through API':c.kind;label.append(kind);$('collections').append(label);
  }
  if(!items.length) $('collections').textContent='No collections found.';
  $('plan').disabled=!items.length;
}
$('source').addEventListener('change',()=>{$('import-box').hidden=$('source').value!=='import';$('plan').disabled=true;$('collections').replaceChildren();});
action('load',async()=>{
  if($('source').value==='import') {$('import-box').hidden=false;notice('Choose an archive file below.');return;}
  collections((await api('/api/collections/'+$('source').value)).collections);
});
$('upload').addEventListener('change',async()=>{try {const file=$('upload').files[0];if(!file)return;if(file.size>20*1024*1024)throw new Error('Maximum upload is 20 MB.');collections((await api('/api/import',JSON.parse(await file.text()))).collections);notice('Archive loaded. Choose collections to match.');}catch(e){notice(e.message);}});
action('select-all',async()=>{const inputs=[...$('collections').querySelectorAll('input:not(:disabled)')];const check=inputs.some(i=>!i.checked);inputs.forEach(i=>i.checked=check);});
action('plan',async()=>{
  const ids=[...$('collections').querySelectorAll('input:checked')].map(i=>i.value);
  const data=await api('/api/plan',{source:$('source').value,destination:$('destination').value,collections:ids});
  jobId=data.id;sessionStorage.setItem('resonance-job',jobId);$('review').hidden=false;$('review').scrollIntoView({behavior:'smooth'});await poll();
});
function render() {
  $('review').hidden=false;
  $('progress').textContent=job.status.replaceAll('_',' ')+' · '+job.rows.length+' tracks';
  $('download').href='/api/jobs/'+jobId+'/archive';
  $('execute').disabled=job.status!=='review';
  $('job-message').textContent=job.error || (job.status==='review'?'Review every proposal. Unmatched tracks are skipped unless you choose a candidate.':job.status==='complete'?'Transfer complete. Download your archive and report.':'You may leave this page open while Resonance works.');
  $('matches').replaceChildren();
  job.rows.forEach((r,i)=>{
    const row=document.createElement('div');row.className='match';
    const source=document.createElement('div'), title=document.createElement('div'), artist=document.createElement('div');
    title.className='track-title';title.textContent=r.source.title;artist.className='track-artist';artist.textContent=(r.source.artist||'Unknown artist')+' · '+job.collections[r.collection].name+' · '+r.status;source.append(title,artist);
    const target=document.createElement('div'), select=document.createElement('select');select.setAttribute('aria-label','Match for '+r.source.title);select.dataset.row=i;
    const skip=document.createElement('option');skip.value='';skip.textContent='Skip this track';select.append(skip);
    r.candidates.forEach((c,n)=>{const option=document.createElement('option');option.value=n;option.textContent=c.title+' — '+c.artist+' ('+Math.round(c.score*100)+'%)';select.append(option);});
    select.value=r.choice===null?'':String(r.choice);select.disabled=job.status!=='review';target.append(select);
    if(job.status==='review' && job.source!=='spotify' && job.destination!=='spotify' && r.source.origin!=='spotify' && r.candidates.length) {
      const button=document.createElement('button');button.className='quiet';button.textContent='Ask AI';button.addEventListener('click',async()=>{button.disabled=true;try{const a=await api('/api/jobs/'+jobId+'/ai',{row:i,key:$('ai-key').value,consent:$('ai-consent').checked});select.value=a.index===null?'':String(a.index);notice('AI suggestion: '+a.reason+' Review it before transferring.');}catch(e){notice(e.message);}finally{button.disabled=false;}});target.append(button);
    }
    row.append(source,target);$('matches').append(row);
  });
}
async function poll() {
  clearTimeout(timer);
  try {job=await api('/api/jobs/'+jobId);render();if(['matching','transferring'].includes(job.status))timer=setTimeout(poll,1800);}catch(e){notice(e.message);}
}
action('execute',async()=>{
  const choices=[...$('matches').querySelectorAll('select')].map(s=>s.value===''?null:Number(s.value));
  await api('/api/jobs/'+jobId+'/review',{choices});await api('/api/jobs/'+jobId+'/execute',{});await poll();
});
action('clear',async()=>{await api('/api/disconnect',{});clearTimeout(timer);sessionStorage.removeItem('resonance-job');$('ai-key').value='';jobId=null;job=null;$('review').hidden=true;$('collections').replaceChildren();$('plan').disabled=true;await status();notice('Local connections, archives and transfer records cleared. To revoke provider access, use your Spotify or Google account permissions page.');});
status().catch(e=>notice(e.message));
jobId=sessionStorage.getItem('resonance-job');if(jobId)poll();
