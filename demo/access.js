/* Keep public research and protected workspace access clear before an action. */
(function(){
  'use strict';
  var box=document.getElementById('prompt'), mode=document.getElementById('task-mode');
  var note=document.createElement('p');note.id='workspace-access';note.className='small';note.setAttribute('role','status');
  document.getElementById('menu-access').prepend(note);
  function save(){try{sessionStorage.setItem('automake-pending-prompt',box.value);}catch(e){}}
  try{if(!box.value)box.value=sessionStorage.getItem('automake-pending-prompt')||'';}catch(e){}
  box.addEventListener('input',save);
  window.savePendingPrompt=save;
  var offerField=document.getElementById('customer-offer');
  if(offerField){try{offerField.value=sessionStorage.getItem('automake-offer')||offerField.value;}catch(e){}offerField.addEventListener('input',function(){try{sessionStorage.setItem('automake-offer',offerField.value);}catch(e){}});}
  window.workspaceAccess={signed_in:false};
  var campaign=mode.querySelector('option[value="campaign"]');
  campaign.disabled=true;mode.value='research';document.getElementById('prepare').disabled=true;
  window.workspaceAccessReady=requestJSON(API+'/api/chat/access',{cache:'no-store'}).then(function(access){
    window.workspaceAccess=access;
    var accountLabel=document.getElementById("sidebar-account-label");if(accountLabel)accountLabel.textContent=access.signed_in?"Your workspace":"Public research";
    if(window.applyWorkspacePreferences)window.applyWorkspacePreferences();
    campaign.disabled=!access.sending_available;
    document.getElementById('prepare').disabled=!access.drafting_available;
    document.getElementById('prepare').title=access.drafting_available?'Prepare verified drafts without sending':'Sign in to save leads and prepare drafts';
    if(access.signed_in){note.textContent=access.sending_available?'Workspace connected. Research prepares verified contacts and drafts. Activate outreach for each ready contact.':'Your workspace is connected. Campaign drafting and sending require a separately connected mailbox.';}
    else{mode.value='research';note.innerHTML='Research is available. <a href="/login">Sign in to verify contacts and activate outreach</a>.';}
    if(window.syncComposerState)window.syncComposerState();
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
    if(window.renderProspectQuality)html+=window.renderProspectQuality(row.prospect_quality);
    var url=String(row.source_url||'');if(/^https?:\/\//.test(url))html+='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">Research source</a>';
    if(window.businessAction)html+=window.businessAction(row);
    html+='</div>';
  });
  if(state.status==='running'||state.status==='queued')html+='<button class="ghost" id="cancel-research">Stop remaining work</button>';
  bubble.innerHTML=html;
  var cancel=bubble.querySelector('#cancel-research');if(cancel)cancel.onclick=function(){
    var path=(state.poll_url||'/api/research/jobs/'+encodeURIComponent(state.job_id))+'/cancel';
    var action=state.kind==='research'?requestJSON(API+path,{method:'POST'}):workspaceMutation(path,{method:'POST'});
    cancel.disabled=true;cancel.textContent='Stopping…';action.then(function(stopped){state.status=stopped.status;window.renderResearchProgress(state);}).catch(function(e){cancel.disabled=false;cancel.textContent='Stop remaining work';bubble.insertAdjacentHTML('beforeend','<p>'+esc(e.message)+'</p>');});
  };
};

window.showRequestInterpretation=function(query,location,count,sending){
  if(window.syncComposerState)window.syncComposerState();
  var bubble=window.activeResearchBubble;if(!bubble)return;
  bubble.innerHTML='<b>AutoMake AI</b><p>'+esc(query)+'</p><p>Territory: '+esc(location||'Not restricted')+' · Requested: '+esc(count)+'.</p><p>I’ll show source-backed candidates as they arrive. Contact verification is separate. '+(sending?'Sending requires your selected campaign authorization and all safety checks.':'This search does not send emails. Activate a business to start its outreach workflow.')+'</p>';
  var offer=document.getElementById('customer-offer');if(offer&&offer.value)bubble.innerHTML+='<p>Offer for qualification: '+esc(offer.value)+'. Change this in Task options if needed.</p>';
};
window.renderSavedJobResult=function(result){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  var research=result.discovery||result,rows=research.results||[];
  bubble.innerHTML='<b>Saved results</b><p>Research results: '+esc(rows.length)+' · Verified businesses: '+esc(research.verified||research.verified_count||0)+'. A verified business is not automatically ready for outreach.</p>'+(result.business_progress&&result.business_progress.length?window.renderBusinessCards(result.business_progress):rows.map(resultCard).join(''));
  if(result.outreach)bubble.innerHTML+='<p>Qualified: '+esc(result.outreach.qualified||0)+' · Drafts ready: '+esc(result.outreach.drafted||0)+' · Confirmed sends: '+esc(result.outreach.sent||0)+'</p>';
  var summary=(result.outreach||{}).prospect_summary;if(summary)bubble.innerHTML+='<p>Requested: '+esc(summary.requested)+' · Well-supported businesses: '+esc(summary.well_supported)+' · Buyers identified: '+esc(summary.buyer_identified)+' · Contacts ready: '+esc(summary.contact_ready)+' · Remaining shortfall: '+esc(summary.remaining_well_supported)+'.</p><p class="meta">'+esc(summary.note)+'</p>';
};
window.followResearchJob=function(job,kind){
  var valid=/^\/api\/(?:research\/jobs|demo\/campaigns\/jobs)\/[A-Za-z0-9_-]+$/;
  if(!valid.test(job.poll_url||''))return Promise.reject(new Error('Invalid saved job.'));
  var territory=document.getElementById('territory');
  if(job.territory!==undefined)territory.value=job.territory;
  sessionStorage.setItem('automake-active-job',JSON.stringify({job_id:job.job_id,poll_url:job.poll_url,kind:kind,territory:territory.value}));
  return new Promise(function(resolve,reject){
    var started=Date.now(),failures=0;
    function poll(){
      requestJSON(API+job.poll_url,{cache:'no-store'}).then(function(state){
        failures=0;state.poll_url=job.poll_url;state.kind=kind;
        window.latestResearchProgress=state.progress||{};
        window.renderResearchProgress(state);
        if(state.status==='completed'){
          sessionStorage.setItem('automake-last-research-job',JSON.stringify({job_id:job.job_id,poll_url:job.poll_url,kind:kind,territory:territory.value}));sessionStorage.removeItem('automake-active-job');sessionStorage.removeItem('automake-research-request');sessionStorage.removeItem('automake-campaign-request');sessionStorage.removeItem('automake-draft-request');window.pendingCampaign=null;
          state.result.business_progress=(state.progress||{}).businesses||[];resolve(state.result);return;
        }
        if(state.status==='failed'||state.status==='cancelled'){
          sessionStorage.removeItem('automake-active-job');
          if(kind==='research')sessionStorage.removeItem('automake-research-request');
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
  var job;try{job=JSON.parse(sessionStorage.getItem('automake-active-job')||sessionStorage.getItem('automake-last-research-job')||'null');}catch(e){}
  if(!job)return;
  if(job.territory!==undefined){document.getElementById('territory').value=job.territory;window.workspaceAccessReady.then(function(){document.getElementById('territory').value=job.territory;});}
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
    if(window.renderProspectQuality)html+=window.renderProspectQuality(row.prospect_quality);
    if(/^https?:\/\//.test(String(row.source_url||'')))html+='<a href="'+esc(row.source_url)+'" target="_blank" rel="noopener noreferrer">Research source</a>';
    if(window.businessAction)html+=window.businessAction(row);
    return html+'</div>';
  }).join('');
};

// An explicit customer click is the only entry point to this send-capable path.
window.outreachPending=new Set();
window.outreachControl=function(id,state){
  if(!state)return '';
  var pending=window.outreachPending.has(Number(id));
  var html='<div class="outreach-workflow" data-outreach-card="'+Number(id)+'"><button class="ghost" type="button" data-activate-outreach="'+Number(id)+'" data-ready="'+Boolean(state.can_activate)+'"'+(!state.can_activate||pending?' disabled':'')+'>'+(pending?'Activating…':esc(state.label))+'</button><p role="status">'+esc(state.reason)+'</p>';
  if(state.state==='active'||state.state==='stopped')html+='<ol><li>Initial email: '+esc(state.initial)+'</li><li>Follow-ups: '+esc(state.followups)+'</li><li>Calendar: '+esc(state.booking)+'</li></ol>';
  var preview=state.preview;if(preview)html+='<details><summary>Review message &amp; résumé</summary><p>To: '+esc(preview.recipient)+'</p><p>'+esc(preview.subject)+'</p><p class="email-copy">'+esc(preview.body)+'</p><p>Attachment: '+esc(preview.attachment)+'</p></details>';
  return html+'</div>';
};

window.renderProspectQuality=function(q){
  q=q||{};var fit=q.fit||{},need=q.need||{},contact=q.contact||{};
  var html='<div class="prospect-quality"><p class="meta">Business fit: '+esc(fit.state||'Pending')+' · Evidence of need: '+esc(need.state||'Pending')+' · Contact: '+esc(contact.state||'Pending')+'</p><details><summary>Why this prospect?</summary>';
  html+='<p><b>Why this business?</b> '+esc(q.why_business||'Business evidence is being checked.')+'</p><p><b>Why now?</b> '+esc(q.why_now||'Current need and urgency are not confirmed.')+'</p><p><b>Who should we contact?</b> '+esc(q.who||'Responsible buyer not confirmed.')+'</p><p><b>What evidence supports that?</b></p>';
  var sources=q.sources||[];
  html+=sources.length?sources.map(function(s){return /^https?:\/\//.test(String(s.url||''))?'<p><a href="'+esc(s.url)+'" target="_blank" rel="noopener noreferrer">Company evidence</a> · Observed '+esc(s.observed_at||'unknown')+' · Published '+esc(s.published_at||'unconfirmed')+'</p>':'';}).join(''):'<p>Source checks are pending.</p>';
  html+='<p><b>What still needs verification?</b> '+esc((q.missing||[]).length?q.missing.join(' · ').toLowerCase().replace(/_/g,' '):q.ready?'All prospect checks passed; send controls still apply.':'Verification in progress.')+'</p></details></div>';
  return html;
};
window.activateLead=function(id){
  id=Number(id);if(!Number.isInteger(id)||id<1||window.outreachPending.has(id))return;
  window.outreachPending.add(id);
  function update(state){document.querySelectorAll('[data-outreach-card="'+id+'"]').forEach(function(el){el.outerHTML=window.outreachControl(id,state);});}
  document.querySelectorAll('[data-activate-outreach="'+id+'"]').forEach(function(b){b.disabled=true;b.textContent='Activating…';});
  return workspaceMutation(window.activateOutreachPath(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({activate:true})})
    .then(function(result){window.outreachPending.delete(id);update(result.outreach);})
    .catch(function(error){
      // Re-read persisted status after any failure; never retry a send automatically.
      return requestJSON(API+'/api/chat/dashboard/leads/'+id,{cache:'no-store'}).then(function(result){
        window.outreachPending.delete(id);update(result.outreach);
        document.querySelectorAll('[data-outreach-card="'+id+'"] [role="status"]').forEach(function(el){el.textContent=result.outreach.state==='active'?result.outreach.reason:error.message;});
      }).catch(function(){window.outreachPending.delete(id);document.querySelectorAll('[data-outreach-card="'+id+'"] [role="status"]').forEach(function(el){el.textContent='Activation could not be confirmed. Reopen My Leads to check its saved status before trying again.';});});
    });
};
document.addEventListener('click',function(event){var button=event.target.closest('[data-activate-outreach]');if(button&&!button.disabled)window.activateLead(button.dataset.activateOutreach);});

// Selected-business workflows: rendering and reloads only observe persisted work.
window.selectedWorkflows={};
window.selectionId=function(ref){return ref.kind+':'+(ref.lead_id||ref.job_id||'')+':'+(ref.key||'');};
window.selectionControl=function(ref){
  if(!ref)return '';
  var id=window.selectionId(ref),entry=window.selectedWorkflows[id]||{},state=entry.state||{},workflow=(state.result||{}).workflow||{};
  var running=entry.pending||state.status==='queued'||state.status==='running';
  var active=workflow.state==='active',held=workflow.state==='held';
  var review=((workflow.outreach||{}).state==='review'||(workflow.outreach||{}).state==='stopped');
  var stopped=state.status==='failed'||state.status==='cancelled';
  var disabled=running||active||review||stopped;
  var label=stopped?'Workflow stopped':entry.pending?'Starting…':state.status==='queued'?'Workflow queued':running?'Workflow running':active?'Outreach active':held?'Retry workflow':'Activate workflow';
  var reason=entry.error||workflow.reason||(running?'Verifying this business and contact, then preparing your approved message and résumé.':'Starts verification and draft preparation, then sends your approved message and résumé when all required checks pass.');
  if(state.status==='failed'||state.status==='cancelled')reason=state.error||'Workflow stopped. Review its saved status before starting again.';
  var html='<div class="outreach-workflow selection-workflow" data-selection-card="'+esc(id)+'"><button class="ghost" type="button" data-select-workflow="'+esc(JSON.stringify(ref))+'"'+(disabled?' disabled':'')+'>'+esc(label)+'</button><p role="status">'+esc(reason)+'</p>';
  if((workflow.reason_codes||[]).length)html+='<p class="meta">'+esc(workflow.reason_codes.join(' · ').toLowerCase().replace(/_/g,' '))+'</p>';
  if(entry.error&&!(window.workspaceAccess||{}).signed_in)html+='<p><a href="/login">Sign in to activate this business</a>. Your research will be restored when you return.</p>';
  if(workflow.outreach&&active)html+='<ol><li>Initial email: '+esc(workflow.outreach.initial)+'</li><li>Follow-ups: '+esc(workflow.outreach.followups)+'</li><li>Calendar: '+esc(workflow.outreach.booking)+'</li></ol>';
  if(running&&entry.job)html+='<button class="ghost" type="button" data-cancel-selection="'+esc(id)+'">Stop remaining work</button><p class="meta">A send already in progress may still complete.</p>';
  return html+'</div>';
};
window.businessAction=function(row){
  if(row.lead_id&&row.outreach&&['active','stopped','review'].indexOf(row.outreach.state)!==-1)return window.outreachControl(row.lead_id,row.outreach);
  var ref=row.selection||(row.lead_id?{kind:'lead',lead_id:row.lead_id}:null);
  if(ref)return window.selectionControl(ref);
  return row.lead_id&&window.outreachControl?window.outreachControl(row.lead_id,row.outreach):'';
};
window.refreshSelectionCards=function(id){
  var entry=window.selectedWorkflows[id];if(!entry)return;
  document.querySelectorAll('[data-selection-card]').forEach(function(card){if(card.dataset.selectionCard===id)card.outerHTML=window.selectionControl(entry.ref);});
};
window.saveSelectedWorkflows=function(){
  var jobs={};Object.keys(window.selectedWorkflows).forEach(function(id){var e=window.selectedWorkflows[id];if(e.job)jobs[id]={ref:e.ref,job:e.job,offer:e.offer};});
  try{sessionStorage.setItem('automake-selected-workflows',JSON.stringify(jobs));}catch(e){}
};
window.observeSelectedWorkflow=function(id){
  var entry=window.selectedWorkflows[id];if(!entry||!entry.job||entry.observing)return;
  entry.observing=true;var failures=0,started=Date.now();
  function poll(){
    requestJSON(API+entry.job.poll_url,{cache:'no-store'}).then(function(state){
      entry.state=state;entry.error='';failures=0;window.refreshSelectionCards(id);
      if(state.status==='queued'||state.status==='running'){
        if(Date.now()-started<2700000)setTimeout(poll,2000);else{entry.observing=false;entry.error='The workflow is saved. Reload to keep checking it.';window.refreshSelectionCards(id);}
      }else entry.observing=false;
    }).catch(function(error){
      if(++failures<4){setTimeout(poll,failures*2000);return;}
      entry.observing=false;entry.error='Status could not be confirmed. Reload to check the saved workflow; do not start another send.';window.refreshSelectionCards(id);
    });
  }poll();
};
window.activateSelection=function(ref){
  var id=window.selectionId(ref),entry=window.selectedWorkflows[id]||{ref:ref};
  if(entry.pending)return;
  window.selectedWorkflows[id]=entry;entry.pending=true;entry.error='';window.refreshSelectionCards(id);
  var offer=document.getElementById('customer-offer').value;
  var body={selection:ref,offer:offer,activate:true};
  if(entry.offer===offer&&(entry.state||{}).status==='completed'&&((entry.state.result||{}).workflow||{}).state==='held')body.retry_from=entry.job.job_id;
  return workspaceMutation('/api/chat/workflows/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(job){
      if(!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(job.poll_url||''))throw new Error('Invalid saved workflow.');
      entry.pending=false;entry.offer=offer;entry.job={job_id:job.job_id,poll_url:job.poll_url};entry.state=job;
      window.saveSelectedWorkflows();window.refreshSelectionCards(id);window.observeSelectedWorkflow(id);
    }).catch(function(error){entry.pending=false;entry.error=error.message;window.refreshSelectionCards(id);});
};
document.addEventListener('click',function(event){
  var button=event.target.closest('[data-select-workflow]');
  if(button&&!button.disabled){try{window.activateSelection(JSON.parse(button.dataset.selectWorkflow));}catch(e){}return;}
  var stop=event.target.closest('[data-cancel-selection]');if(!stop)return;
  var id=stop.dataset.cancelSelection,entry=window.selectedWorkflows[id];if(!entry||!entry.job)return;
  stop.disabled=true;workspaceMutation(entry.job.poll_url+'/cancel',{method:'POST'}).then(function(state){entry.state=state;window.refreshSelectionCards(id);}).catch(function(error){entry.error=error.message;window.refreshSelectionCards(id);});
});
(function restoreSelectedWorkflows(){
  var saved;try{saved=JSON.parse(sessionStorage.getItem('automake-selected-workflows')||'{}');}catch(e){return;}
  Object.keys(saved).slice(0,50).forEach(function(id){var entry=saved[id];if(!entry||!entry.ref||!entry.job||!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(entry.job.poll_url||''))return;
    window.selectedWorkflows[id]={ref:entry.ref,job:entry.job,offer:entry.offer};window.observeSelectedWorkflow(id);
  });
})();
