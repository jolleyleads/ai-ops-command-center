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
    if(access.signed_in){note.textContent=access.sending_available?'Workspace connected. Research prepares verified contacts and drafts. Use Activate all with email above your results to start a batch.':'Your workspace is connected. Campaign drafting and sending require a separately connected mailbox.';}
    else{mode.value='research';note.innerHTML='Research is available. <a href="/login">Sign in to verify contacts and activate outreach</a>.';}
    if(window.syncComposerState)window.syncComposerState();
    return access;
  }).catch(function(){note.textContent='Research is available. Workspace access could not be checked; refresh before sending.';return window.workspaceAccess;});
})();

window.renderResearchProgress=function(state){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  var p=state.progress||{},rows=p.businesses||p.candidates||[];
  var stages={planning:'Understanding your request',discovering_businesses:'Finding businesses',verifying_candidates:'Checking business evidence',researching_more_sources:'Finding additional evidence',checking_contacts:'Checking available contact sources',business_results_ready:'Business research available',enriching_individual_contacts:'Verifying each contact and preparing qualified drafts'};
  var html='<b>AutoMake AI</b><p>'+esc(state.status==='queued'?'Starting your search…':state.status==='cancelled'?'Search stopped.':'Finding businesses…')+'</p><p class="meta">'+esc(p.discovered||rows.length)+' found</p><details class="research-details"><summary>Search details</summary><p>'+esc(stages[p.stage]||'Checking sources')+'</p>';
  html+='<p class="meta">Requested '+esc(p.requested||state.target_count||'')+' · Discovered '+esc(p.discovered||rows.length)+' · Qualified '+esc(p.qualified||0)+' · Drafts ready '+esc(p.drafted||0)+'.</p>';
  if(p.updated_at)html+='<p class="meta">Last update: '+esc(p.updated_at)+'</p>';
  html+='</details>';
  if(window.bulkActivationControl)html+=window.bulkActivationControl(rows);
  rows.forEach(function(row){
    html+='<div class="lead"><b>'+esc(row.company)+'</b>';

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
  bubble.innerHTML='<b>AutoMake AI</b><p>Finding '+esc(count)+' businesses'+(location?' in '+esc(location):'')+'…</p><p class="meta">Results will appear here as I find them.</p>';
  var offer=document.getElementById('customer-offer');if(offer&&offer.value)bubble.innerHTML+='<details class="research-details"><summary>Search details</summary><p>Offer: '+esc(offer.value)+'</p></details>';
};
window.renderSavedJobResult=function(result){
  var bubble=window.activeResearchBubble;if(!bubble)return;
  var research=result.discovery||result,rows=research.results||[];
  bubble.innerHTML='<b>Your results</b><p>Found '+esc(rows.length)+' businesses.</p>'+(result.business_progress&&result.business_progress.length?window.renderBusinessCards(result.business_progress):(window.bulkActivationControl?window.bulkActivationControl(rows):'')+rows.map(resultCard).join(''));
  if(result.outreach)bubble.innerHTML+='<details class="research-details"><summary>Search details</summary><p>Qualified: '+esc(result.outreach.qualified||0)+' · Drafts ready: '+esc(result.outreach.drafted||0)+' · Confirmed sends: '+esc(result.outreach.sent||0)+'</p></details>';
  var summary=(result.outreach||{}).prospect_summary;if(summary)bubble.innerHTML+='<details class="research-details"><summary>Result details</summary><p>Requested: '+esc(summary.requested)+' · Well-supported businesses: '+esc(summary.well_supported)+' · Buyers identified: '+esc(summary.buyer_identified)+' · Contacts ready: '+esc(summary.contact_ready)+' · Remaining shortfall: '+esc(summary.remaining_well_supported)+'.</p><p class="meta">'+esc(summary.note)+'</p></details>';
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
          state.result.business_progress=kind==='research'?[]:(state.progress||{}).businesses||[];resolve(state.result);return;
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
  return (window.bulkActivationControl?window.bulkActivationControl(rows):'')+rows.map(function(row){
    var html='<div class="lead"><b>'+esc(row.company)+'</b>';
    if(row.error)html+='<p>Contact verification needs review. Business research is preserved.</p>';
    if(window.renderProspectQuality)html+=window.renderProspectQuality(row.prospect_quality);
    if(/^https?:\/\//.test(String(row.source_url||'')))html+='<a href="'+esc(row.source_url)+'" target="_blank" rel="noopener noreferrer">Research source</a>';
    if(window.businessAction)html+=window.businessAction(row);
    return html+'</div>';
  }).join('');
};

// An explicit customer click is the only entry point to this send-capable path.
window.outreachPending=new Set();
window.emailSendStatus=function(outreach,checking){
  outreach=outreach||{};
  if(outreach.send_status==='sent'||outreach.initial==='Send confirmed')return 'Sent';
  if(outreach.send_status==='unknown'||outreach.state==='review')return 'Checking status';
  if(checking)return 'Sending…';
  return 'Not sent';
};
window.sendMessage=function(status,state,reason){
  if(!reason&&status==='Not sent')return 'Sends your message and résumé. No extra confirmation.';
  if(status==='Sent')return state&&state.state==='stopped'?'Your email was sent. Further emails are stopped.':'Your email was sent.';
  if(status==='Sending…')return 'Sending your message and résumé…';
  if(status==='Checking status')return 'We’re checking whether your email was sent. Please don’t send it again yet.';
  reason=String(reason||'');
  if(/reconnect google|google connection|expired.*grant/i.test(reason))return 'Connect Google in Settings to send your email.';
  if(/suppressed|opt.out|unsubscribed/i.test(reason))return 'This contact has opted out. No email was sent.';
  if(/mailbox|email.*verif|contact.*verif|company.*source/i.test(reason))return 'We couldn’t verify this email yet.';
  return reason?'This email needs attention. Open Details to see why.':'Sends your message and résumé.';
};
window.recipientLine=function(state){
  if(!state||!state.recipient)return '';
  return '<p class="meta">To: '+esc(state.contact_name?state.contact_name+' · ':'')+esc(state.recipient)+'</p>';
};
window.sendDetails=function(reason,codes){
  if(!reason&&!(codes||[]).length)return '';
  return '<details class="send-details"><summary>Details</summary><p>'+esc(reason||'')+'</p>'+((codes||[]).length?'<p>'+esc(codes.join(' · '))+'</p>':'')+'</details>';
};
window.outreachControl=function(id,state){
  if(!state)return '';
  var pending=window.outreachPending.has(Number(id));
  var sendStatus=window.emailSendStatus(state,pending),sent=sendStatus==='Sent';
  var html='<div class="outreach-workflow" data-outreach-card="'+Number(id)+'"><p class="email-send-status" role="status"><b>'+esc(sendStatus)+'</b></p>'+window.recipientLine(state)+'<button class="ghost" type="button" data-activate-outreach="'+Number(id)+'" data-ready="'+Boolean(state.can_activate)+'"'+(!state.can_activate||pending||sent?' disabled':'')+'>'+(pending?'Sending…':sent?'Sent':state.can_activate?'Activate workflow':state.state==='review'?'Checking status':state.state==='stopped'?'Stopped':'Not sent')+'</button><p class="outreach-reason">'+esc(window.sendMessage(sendStatus,state,state.reason))+'</p>'+window.sendDetails(state.reason,state.reason_codes);
  if(state.state==='active'||state.state==='stopped')html+='<details class="send-details"><summary>Follow-ups &amp; booking</summary><ol><li>Initial email: '+esc(state.initial)+'</li><li>Follow-ups: '+esc(state.followups)+'</li><li>Calendar: '+esc(state.booking)+'</li></ol></details>';
  var preview=state.preview;if(preview)html+='<details><summary>Review message &amp; résumé</summary><p>To: '+esc(preview.recipient)+'</p><p>'+esc(preview.subject)+'</p><p class="email-copy">'+esc(preview.body)+'</p><p>Attachment: '+esc(preview.attachment)+'</p></details>';
  return html+'</div>';
};

window.renderProspectQuality=function(q){
  q=q||{};var fit=q.fit||{},need=q.need||{},contact=q.contact||{};
  var html='<div class="prospect-quality"><details><summary>Why this business?</summary><p class="meta">Business fit: '+esc(fit.state||'Pending')+' · Evidence of need: '+esc(need.state||'Pending')+' · Contact: '+esc(contact.state||'Pending')+'</p>';
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
        document.querySelectorAll('[data-outreach-card="'+id+'"] .outreach-reason').forEach(function(el){el.textContent=window.sendMessage(window.emailSendStatus(result.outreach),result.outreach,error.message);});
      }).catch(function(){window.outreachPending.delete(id);document.querySelectorAll('[data-outreach-card="'+id+'"] .outreach-reason').forEach(function(el){el.textContent='Open My Leads to check the latest email status.';});});
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
  var statusView=workflow.outreach||((stopped||active)?{send_status:'unknown'}:{});
  var sendStatus=window.emailSendStatus(statusView,running),sent=sendStatus==='Sent';
  var disabled=running||active||review||stopped||sent;
  var label=sent?'Sent':stopped?'Stopped':entry.pending?'Sending…':state.status==='queued'?'Sending…':running?'Sending…':active?'Check status':held&&entry.job&&entry.job.activation_policy==='selected-contact-v1'?'Try again':'Activate workflow';
  var reason=entry.error||workflow.reason||(running?'Checking the email and sending your message…':'Sends your message and résumé. No extra confirmation.');
  if(state.status==='failed'||state.status==='cancelled')reason=state.error||'Workflow stopped. Review its saved status before starting again.';
  if(sent&&workflow.outreach.reason)reason=workflow.outreach.reason;
  var html='<div class="outreach-workflow selection-workflow" data-selection-card="'+esc(id)+'"><p class="email-send-status" role="status"><b>'+esc(sendStatus)+'</b></p>'+window.recipientLine(workflow.outreach)+'<button class="ghost" type="button" data-select-workflow="'+esc(JSON.stringify(ref))+'"'+(disabled?' disabled':'')+'>'+esc(label)+'</button><p>'+esc(window.sendMessage(sendStatus,workflow.outreach,entry.error||workflow.reason)||(reason))+'</p>';
  html+=window.sendDetails(sent?reason:entry.error||workflow.reason,workflow.reason_codes);
  if(entry.error&&!(window.workspaceAccess||{}).signed_in)html+='<p><a href="/login">Sign in to activate this business</a>. Your research will be restored when you return.</p>';
  if(workflow.outreach&&(active||sent))html+='<details class="send-details"><summary>Follow-ups &amp; booking</summary><ol><li>Initial email: '+esc(workflow.outreach.initial)+'</li><li>Follow-ups: '+esc(workflow.outreach.followups)+'</li><li>Calendar: '+esc(workflow.outreach.booking)+'</li></ol></details>';
  if(running&&entry.job)html+='<button class="ghost" type="button" data-cancel-selection="'+esc(id)+'">Stop remaining work</button><p class="meta">A send already in progress may still complete.</p>';
  return html+'</div>';
};
window.businessAction=function(row){
  if(row.lead_id&&row.outreach&&['active','stopped','review'].indexOf(row.outreach.state)!==-1)return (window.businessEmail?window.businessEmail(row):'')+window.outreachControl(row.lead_id,row.outreach);
  var ref=row.selection||(row.lead_id?{kind:'lead',lead_id:row.lead_id}:null);
  if(ref)return (window.businessEmail?window.businessEmail(row):'')+window.selectionControl(ref);
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
      }else{
        entry.observing=false;
        var workflow=(state.result||{}).workflow||{};
        // Read the latest receipt after a terminal job; historical job snapshots
        // must not conceal a send reconciled later. This never starts work.
        if(workflow.lead_id)requestJSON(API+'/api/chat/dashboard/leads/'+encodeURIComponent(workflow.lead_id),{cache:'no-store'}).then(function(detail){
          if(detail.outreach){workflow.outreach=detail.outreach;window.refreshSelectionCards(id);}
        }).catch(function(){/* Preserve the saved status when observation fails. */});
      }
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
  if(entry.job&&entry.job.activation_policy==='selected-contact-v1'&&!entry.job.bulk&&entry.offer===offer&&(entry.state||{}).status==='completed'&&((entry.state.result||{}).workflow||{}).state==='held')body.retry_from=entry.job.job_id;
  return workspaceMutation('/api/chat/workflows/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(job){
      if(!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(job.poll_url||''))throw new Error('Invalid saved workflow.');
      entry.pending=false;entry.offer=offer;entry.job={job_id:job.job_id,poll_url:job.poll_url,activation_policy:job.activation_policy};entry.state=job;
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

// One explicit click authorizes exactly the displayed, email-bearing businesses.
window.bulkTargets={};window.bulkObservers=new Set();
window.businessEmailValue=function(row){
  // Display is advisory; the server independently checks source and mailbox proof.
  var website=row.website||row.source_url||row.url||'',host;
  try{host=new URL(website).hostname.toLowerCase().replace(/^www\./,'');}catch(e){return '';}
  if(['threebestrated.com','linkedin.com','yelp.com','facebook.com','google.com','indeed.com','ziprecruiter.com'].some(function(domain){return host===domain||host.endsWith('.'+domain);}))return '';
  var values=[row.contact_email,row.email,(row.contact||{}).email].concat((Array.isArray(row.contacts)?row.contacts:[]).map(function(c){return c.email;}));
  return values.find(function(email){
    if(typeof email!=='string'||!email.includes('@'))return false;
    var domain=email.split('@').pop().toLowerCase();
    return domain===host||domain.endsWith('.'+host)||host.endsWith('.'+domain);
  })||'';
};
window.businessEmail=function(row){var email=window.businessEmailValue(row);return email?'<p class="meta">Email: '+esc(email)+'</p>':'';};
window.bulkActivationControl=function(rows){
  if(!rows.length)return '';
  var refs=[],seen=new Set();
  rows.forEach(function(row){var ref=row.selection||(row.lead_id?{kind:'lead',lead_id:row.lead_id}:null);if(!ref||!window.businessEmailValue(row))return;var key=window.selectionId(ref);if(!seen.has(key)){seen.add(key);refs.push(ref);}});
  var group=rows.map(function(row){return row.selection?window.selectionId(row.selection):String(row.lead_id||row.company||row.title||'');}).sort().join('|');
  window.bulkTargets[group]={refs:refs,rows:rows};
  return window.bulkControl(group);
};
window.bulkControl=function(group){
  var target=window.bulkTargets[group]||{},refs=target.refs||[],entries=refs.map(function(ref){
    var id=window.selectionId(ref),entry=window.selectedWorkflows[id];if(entry)return entry;
    var row=(target.rows||[]).find(function(row){var r=row.selection||(row.lead_id?{kind:'lead',lead_id:row.lead_id}:null);return r&&window.selectionId(r)===id;})||{};
    return {state:{result:{workflow:{outreach:row.outreach||{}}}}};
  });
  var busy=entries.some(function(e){return e.pending||['queued','running'].indexOf((e.state||{}).status)!==-1;}),sent=entries.filter(function(e){return window.emailSendStatus((((e.state||{}).result||{}).workflow||{}).outreach)==='Sent';}).length;
  var batch=entries.length&&entries.every(function(e){return e.job&&e.job.bulk&&e.job.activation_policy==='selected-contact-v1';}),done=batch&&!busy;
  var disabled=!refs.length||refs.length>20||busy||done;
  var label=busy?'Sending…':done?'Finished':('Activate all with email ('+refs.length+')');
  var note=refs.length>20?'Filter to 20 or fewer businesses with email before starting.':refs.length?'Send your message and résumé to these '+refs.length+' businesses.':'Businesses will appear here as emails are found. No emails have been selected.';
  return '<div class="outreach-workflow bulk-workflow" data-bulk-group="'+esc(group)+'"><button class="ghost" type="button" data-activate-bulk="'+esc(group)+'"'+(disabled?' disabled':'')+'>'+esc(label)+'</button><p>'+esc(note)+'</p><p role="status">'+sent+' of '+refs.length+' emails sent'+(done?' · Review individual results below.':'.')+'</p></div>';
};
window.refreshBulkControls=function(){document.querySelectorAll('[data-bulk-group]').forEach(function(el){el.outerHTML=window.bulkControl(el.dataset.bulkGroup);});};
window.observeBulkWorkflow=function(job){
  if(window.bulkObservers.has(job.job_id))return;window.bulkObservers.add(job.job_id);
  var failures=0,started=Date.now();
  function poll(){requestJSON(API+job.poll_url,{cache:'no-store'}).then(function(state){
    failures=0;var items=(state.result||{}).bulk_items||(state.progress||{}).bulk_items||((state.result||{}).progress||{}).bulk_items||[];
    Object.keys(window.selectedWorkflows).forEach(function(id){
      var entry=window.selectedWorkflows[id];if(!entry.job||entry.job.job_id!==job.job_id)return;
      var item=items.find(function(x){return window.selectionId(x.selection)===id;}),terminal=['completed','failed','cancelled'].indexOf(state.status)!==-1;
      entry.pending=false;entry.error='';entry.state={status:item&&item.status==='completed'?'completed':terminal?state.status:item&&item.status==='running'?'running':'queued',
        result:{workflow:item&&item.workflow||{}},error:terminal&&(!item||item.status!=='completed')?(state.error||'Batch stopped before this business finished. Review its saved send status.') :''};
      window.refreshSelectionCards(id);
      var flow=item&&item.workflow;
      if(terminal&&flow&&flow.lead_id)requestJSON(API+'/api/chat/dashboard/leads/'+encodeURIComponent(flow.lead_id),{cache:'no-store'}).then(function(detail){
        if(detail.outreach){entry.state.result.workflow.outreach=detail.outreach;window.refreshSelectionCards(id);window.refreshBulkControls();}
      }).catch(function(){});
    });window.refreshBulkControls();
    if(['queued','running'].indexOf(state.status)!==-1&&Date.now()-started<2700000)setTimeout(poll,2000);else window.bulkObservers.delete(job.job_id);
  }).catch(function(error){
    if(++failures<4){setTimeout(poll,failures*2000);return;}
    window.bulkObservers.delete(job.job_id);Object.keys(window.selectedWorkflows).forEach(function(id){var e=window.selectedWorkflows[id];if(e.job&&e.job.job_id===job.job_id){e.error='Batch status could not be confirmed. Reload to check it; do not resend.';window.refreshSelectionCards(id);}});
  });}poll();
};
window.activateAllWithEmail=function(group){
  var target=window.bulkTargets[group];if(!target||!target.refs.length||target.refs.length>20)return;
  if(target.refs.some(function(ref){var e=window.selectedWorkflows[window.selectionId(ref)]||{};return e.pending||['queued','running'].indexOf((e.state||{}).status)!==-1;}))return;
  var offer=document.getElementById('customer-offer').value;
  target.refs.forEach(function(ref){var id=window.selectionId(ref),e=window.selectedWorkflows[id]||{ref:ref};e.pending=true;e.error='';window.selectedWorkflows[id]=e;window.refreshSelectionCards(id);});window.refreshBulkControls();
  return workspaceMutation('/api/chat/workflows/activate-bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({activate:true,selections:target.refs,offer:offer})}).then(function(job){
    if(!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(job.poll_url||''))throw new Error('Invalid saved batch.');
    var saved={job_id:job.job_id,poll_url:job.poll_url,bulk:true,activation_policy:job.activation_policy};
    target.refs.forEach(function(ref){var id=window.selectionId(ref),entry=window.selectedWorkflows[id];entry.pending=false;entry.offer=offer;entry.job=saved;entry.state=job;window.refreshSelectionCards(id);});
    window.saveSelectedWorkflows();window.refreshBulkControls();window.observeBulkWorkflow(saved);
  }).catch(function(error){target.refs.forEach(function(ref){var id=window.selectionId(ref),entry=window.selectedWorkflows[id];entry.pending=false;entry.error=error.message;window.refreshSelectionCards(id);});window.refreshBulkControls();});
};
document.addEventListener('click',function(event){var button=event.target.closest('[data-activate-bulk]');if(button&&!button.disabled)window.activateAllWithEmail(button.dataset.activateBulk);});
(function restoreSelectedWorkflows(){
  var saved;try{saved=JSON.parse(sessionStorage.getItem('automake-selected-workflows')||'{}');}catch(e){return;}
  Object.keys(saved).slice(0,50).forEach(function(id){var entry=saved[id];if(!entry||!entry.ref||!entry.job||!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(entry.job.poll_url||''))return;
    window.selectedWorkflows[id]={ref:entry.ref,job:entry.job,offer:entry.offer};if(entry.job.bulk)window.observeBulkWorkflow(entry.job);else window.observeSelectedWorkflow(id);
  });
})();
