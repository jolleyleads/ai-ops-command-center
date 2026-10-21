/* Keep public research and protected workspace access clear before an action. */
(function(){
  'use strict';
  var box=document.getElementById('prompt'), mode=document.getElementById('task-mode');
  var note=document.createElement('p');note.id='workspace-access';note.className='small';note.setAttribute('role','status');
  document.querySelector('.composer').prepend(note);
  function save(){try{sessionStorage.setItem('automake-pending-prompt',box.value);}catch(e){}}
  try{if(!box.value)box.value=sessionStorage.getItem('automake-pending-prompt')||'';}catch(e){}
  box.addEventListener('input',save);
  window.savePendingPrompt=save;
  window.workspaceAccess={signed_in:false};
  var campaign=mode.querySelector('option[value="campaign"]');
  campaign.disabled=true;mode.value='research';document.getElementById('prepare').disabled=true;
  window.workspaceAccessReady=requestJSON(API+'/api/chat/access',{cache:'no-store'}).then(function(access){
    window.workspaceAccess=access;
    if(window.applyWorkspacePreferences)window.applyWorkspacePreferences();
    campaign.disabled=!access.sending_available;
    document.getElementById('prepare').disabled=!access.drafting_available;
    document.getElementById('prepare').title=access.drafting_available?'Prepare verified drafts without sending':'Sign in to save leads and prepare drafts';
    if(access.signed_in){note.textContent=access.sending_available?'Workspace connected. Choose Research only or Research & email.':'Your workspace is connected. Campaign drafting and sending require a separately connected mailbox.';}
    else{mode.value='research';note.innerHTML='Research is available. <a href="/login">Sign in for saved leads and email campaigns</a>.';}
    return access;
  }).catch(function(){note.textContent='Research is available. Workspace access could not be checked; refresh before sending.';return window.workspaceAccess;});
})();

window.renderResearchProgress=function(state){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  var p=state.progress||{},rows=p.businesses||p.candidates||[];
  var stages={planning:'Understanding your request',discovering_businesses:'Finding businesses',verifying_candidates:'Checking business evidence',researching_more_sources:'Finding additional evidence',checking_contacts:'Checking available contact sources',business_results_ready:'Business research available',enriching_individual_contacts:'Verifying each contact and preparing qualified drafts'};
  var html='<b>AutoMake AI · '+esc(state.status)+'</b><p>'+esc(stages[p.stage]||'Research and verification in progress')+'</p>';
  html+='<p class="meta">Requested '+esc(p.requested||state.target_count||'')+' · Discovered '+esc(p.discovered||rows.length)+' · Qualified '+esc(p.qualified||0)+' · Drafts ready '+esc(p.drafted||0)+'.</p>';
  if(p.updated_at)html+='<p class="meta">Last update: '+esc(p.updated_at)+'</p>';
  rows.forEach(function(row){
    html+='<div class="lead"><b>'+esc(row.company)+'</b><p>'+esc(row.business_status||'Candidate — verification pending')+'</p>';
    if(row.contact_status)html+='<p>'+esc(row.contact_status)+' · '+esc(row.qualification_status||'Qualification pending')+' · '+esc(row.draft_status||'No draft ready')+'</p>';
    if(row.error)html+='<p>Contact check needs attention. Other businesses can continue.</p>';
    var url=String(row.source_url||'');if(/^https?:\/\//.test(url))html+='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Research source</a>';
    html+='</div>';
  });
  if(state.status==='running'||state.status==='queued')html+='<button class="ghost" id="cancel-research">Stop remaining work</button>';
  bubble.innerHTML=html;
  var cancel=document.getElementById('cancel-research');if(cancel)cancel.onclick=function(){
    var path=(state.poll_url||'/api/research/jobs/'+encodeURIComponent(state.job_id))+'/cancel';
    var action=state.kind==='research'?requestJSON(API+path,{method:'POST'}):workspaceMutation(path,{method:'POST'});
    cancel.disabled=true;action.catch(function(e){bubble.innerHTML+='<p>'+esc(e.message)+'</p>';});
  };
};

window.showRequestInterpretation=function(query,location,count,sending){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  bubble.innerHTML='<b>AutoMake AI</b><p>'+esc(query)+'</p><p>Territory: '+esc(location||'Not restricted')+' · Requested: '+esc(count)+'.</p><p>I’ll show source-backed candidates as they arrive. Contact verification is separate. '+(sending?'Sending requires your selected campaign authorization and all safety checks.':'Sending is off.')+'</p>';
};
window.renderSavedJobResult=function(result){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  var research=result.discovery||result,rows=research.results||[];
  bubble.innerHTML='<b>Saved results</b><p>Research results: '+esc(rows.length)+' · Verified businesses: '+esc(research.verified||research.verified_count||0)+'. A verified business is not automatically ready for outreach.</p>'+(result.business_progress&&result.business_progress.length?window.renderBusinessCards(result.business_progress):rows.map(resultCard).join(''));
  if(result.outreach)bubble.innerHTML+='<p>Qualified: '+esc(result.outreach.qualified||0)+' · Drafts ready: '+esc(result.outreach.drafted||0)+' · Confirmed sends: '+esc(result.outreach.sent||0)+'</p>';
};
window.followResearchJob=function(job,kind){
  var valid=/^\/api\/(?:research\/jobs|demo\/campaigns\/jobs)\/[A-Za-z0-9_-]+$/;
  if(!valid.test(job.poll_url||''))return Promise.reject(new Error('Invalid saved job.'));
  sessionStorage.setItem('automake-active-job',JSON.stringify({job_id:job.job_id,poll_url:job.poll_url,kind:kind}));
  return new Promise(function(resolve,reject){
    var started=Date.now(),failures=0;
    function poll(){
      requestJSON(API+job.poll_url,{cache:'no-store'}).then(function(state){
        failures=0;state.poll_url=job.poll_url;state.kind=kind;
        window.latestResearchProgress=state.progress||{};
        window.renderResearchProgress(state);
        if(state.status==='completed'){
          sessionStorage.removeItem('automake-active-job');sessionStorage.removeItem('automake-research-request');sessionStorage.removeItem('automake-campaign-request');sessionStorage.removeItem('automake-draft-request');window.pendingCampaign=null;
          state.result.business_progress=(state.progress||{}).businesses||[];resolve(state.result);return;
        }
        if(state.status==='failed'||state.status==='cancelled'){
          sessionStorage.removeItem('automake-active-job');
          reject(new Error(state.error||'Work stopped. Partial research is shown above.'));return;
        }
        if(Date.now()-started>2700000){reject(new Error('Your job is saved. Reload to resume checking it.'));return;}
        setTimeout(poll,2000);
      }).catch(function(e){
        failures++;if(failures<4){setTimeout(poll,Math.min(10000,failures*2000));return;}
        reject(new Error('Connection interrupted. Reload to restore the saved job. '+e.message));
      });
    }poll();
  });
};
(function restoreResearch(){
  var job;try{job=JSON.parse(sessionStorage.getItem('automake-active-job')||'null');}catch(e){}
  if(!job)return;
  var wait=add('ai','<b>Restoring your saved research…</b>');window.activeResearchBubble=wait.querySelector('.bubble');
  document.getElementById('send').disabled=true;
  window.followResearchJob(job,job.kind||'research').then(window.renderSavedJobResult)
    .catch(function(e){wait.querySelector('.bubble').innerHTML+='<p class="error">'+esc(e.message)+'</p>';})
    .then(function(){document.getElementById('send').disabled=false;});
})();

window.requestKeyFor=function(kind,body){
  var name='automake-'+kind+'-request',saved;
  try{saved=JSON.parse(sessionStorage.getItem(name)||'null');}catch(e){}
  if(!saved||saved.body!==body){saved={body:body,key:crypto.randomUUID()};sessionStorage.setItem(name,JSON.stringify(saved));}
  return saved.key;
};

window.renderBusinessCards=function(rows){
  return rows.map(function(row){
    var html='<div class="lead"><b>'+esc(row.company)+'</b><p>'+esc(row.business_status)+'</p><p>'+esc(row.contact_status)+' · '+esc(row.qualification_status||'Qualification pending')+' · '+esc(row.draft_status||'No draft ready')+'</p>';
    if(row.error)html+='<p>Contact verification needs review. Business research is preserved.</p>';
    if(/^https?:\/\//.test(String(row.source_url||'')))html+='<a href="'+esc(row.source_url)+'" target="_blank" rel="noopener noreferrer">Research source</a>';
    return html+'</div>';
  }).join('');
};
