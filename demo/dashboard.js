/* Workspace views and explicit reviewed-draft sending. */
(function () {
  'use strict';
  var panel=document.getElementById('workspace-panel'), menu=document.getElementById('workspace-menu');
  var data=null, view='chat', requestVersion=0, leadOffset=0, campaignOffset=0;
  var labels={chat:'Chat',leads:'My Leads',campaigns:'My Campaigns',conversations:'Conversations',drafts:'Drafts',sent:'Sent',appointments:'Appointments',settings:'Settings',drive:'Google Drive',crm:'CRM Integrations'};
  var statuses={needs_evidence:'Checking contact details',review:'Ready for review',rejected:'Not a match',qualified:'Ready to prepare',drafted:'Draft ready',sent:'Email sent · Waiting for reply',replied:'Reply received',interested:'Interested',booked:'Appointment booked',unsubscribed:'Contact stopped',opted_out:'Contact stopped',queued:'Queued',running:'In progress',completed:'Complete',failed:'Needs attention'};
  var checks={verified_identity:'Business identity confirmed',validated_website:'Company website found',validated_contact:'Contact information checked',source_evidence:'Research sources recorded',geographic_fit:'Location matches',business_type_fit:'Business type matches',intent_signal:'Requested business need supported',evidence_freshness:'Current evidence',named_decision_maker_email:'Named contact and email matched'};
  function e(value){return window.esc(value);}
  function status(value){return statuses[value]||String(value||'Checking details').replace(/_/g,' ');}
  function date(value){if(!value)return 'Not scheduled';var d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString();}
  function link(url,text){return /^https?:\/\//i.test(String(url||''))?'<a href="'+e(url)+'" target="_blank" rel="noopener noreferrer">'+e(text)+'</a>':e(text||'Not available');}
  function score(n){return typeof n==='number'&&Number.isFinite(n)?Math.max(0,Math.min(100,n)):null;}
  function badge(n){n=score(n);return n===null?'Score pending':n+'/100 · '+(n>=80?'Strong match':n>=60?'Potential match':'Needs more research');}
  function load(){return requestJSON(API+'/api/chat/dashboard?lead_offset='+leadOffset+'&campaign_offset='+campaignOffset+'&folder='+(['sent','drafts','conversations'].includes(view)?view:''),{cache:'no-store'}).then(function(result){data=result;return result;});}
  function heading(title,subtitle){return '<div class="workspace-heading"><div><h1>'+e(title)+'</h1><p class="meta">'+e(subtitle)+'</p></div><button type="button" class="ghost" data-refresh>Refresh</button></div>';}
  function error(err){panel.innerHTML=heading(labels[view],'Your workspace')+'<div class="workspace-empty"><p>'+e(err.message)+'</p><a href="/login">Sign in to your workspace</a></div>';}
  function open(name){
    if(name!==view)leadOffset=0;
    view=labels[name]?name:'chat';var version=++requestVersion;
    if(window.closeWorkspaceMenu)window.closeWorkspaceMenu(false);else menu.open=false;
    document.getElementById('feed').hidden=view!=='chat';panel.hidden=view==='chat';
    document.querySelector('.composer-shell').hidden=view!=='chat';
    document.querySelector('.chat').scrollTop=0;
    document.querySelectorAll('[data-view]').forEach(function(b){b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-current',b.dataset.view===view?'page':'false');});
    if(view==='chat'){document.getElementById('prompt').focus();return;}
    panel.innerHTML=heading(labels[view],'Loading your saved records…')+'<span class="loading" aria-label="Loading"></span>';
    if(view==='settings'){settings(version);return;}
    if(view==='drive'){drive(version);return;}
    if(view==='crm'){crm(version);return;}
    if(view==='appointments'){appointments(version);return;}
    load().then(function(){if(version!==requestVersion)return;if(view==='campaigns')campaigns();else leads();}).catch(function(err){if(version===requestVersion)error(err);});
  }
  function drive(version){
    panel.innerHTML=heading('Google Drive','Connect your Google account to browse files in your workspace.')+'<div class="workspace-empty"><p>Checking Google Drive connection…</p></div>';
    requestJSON('/api/drive/status',{cache:'no-store'}).then(function(info){
      if(version!==requestVersion)return;
      if(!info.connected){
        panel.innerHTML=heading('Google Drive','Optional integration — connect whenever you are ready.')+
        '<div class="workspace-empty"><h2>Connect Google Drive</h2><p>Authorize read-only access to browse your Google Drive files. Your Gmail and other workflows stay unchanged.</p>'+
        '<a class="ghost" style="display:inline-block;text-decoration:none" href="/connect/drive">Connect Google Drive</a>'+
        (!info.configured?'<p class="meta">Google OAuth configuration is required before connecting.</p>':'')+'</div>';
        return;
      }
      panel.innerHTML=heading('Google Drive','Connected · Your recent Drive files')+'<div id="drive-files"><span class="loading"></span></div>'+
      '<p><a class="ghost" style="display:inline-block;text-decoration:none" href="/connect/drive">Reconnect Google Drive</a></p>';
      return requestJSON('/api/drive/files',{cache:'no-store'}).then(function(result){
        if(version!==requestVersion)return;
        var files=result.files||[];
        document.getElementById('drive-files').innerHTML=files.length?files.map(function(f){
          return '<article class="lead"><b>'+e(f.name)+'</b><p class="meta">'+e(f.mimeType||'File')+'</p>'+
          (f.webViewLink?'<a href="'+e(f.webViewLink)+'" target="_blank" rel="noopener noreferrer">Open in Google Drive</a>':'')+'</article>';
        }).join(''):'<div class="workspace-empty">No files found in this Drive.</div>';
      });
    }).catch(function(err){if(version===requestVersion)panel.innerHTML=heading('Google Drive','Connection status')+'<p class="error">'+e(err.message)+'</p>';});
  }
  function crm(version){
    var selected=window.automakeCrmSelection||'';
    panel.innerHTML=heading('CRM Integrations','Connect the CRM your business already uses.')+'<div class="workspace-empty">Checking integrations…</div>';
    requestJSON('/api/crm/providers',{cache:'no-store'}).then(function(result){
      if(version!==requestVersion)return;
      var providers=result.providers||[];
      panel.innerHTML=heading('CRM Integrations','Choose a CRM. Connect is available when provider app authorization is configured.')+
        providers.map(function(p){
          return '<article class="lead workspace-lead"><div class="leadtop"><b>'+e(p.name)+'</b><span id="crm-status-'+e(p.id)+'" class="tag">Checking…</span></div><div id="crm-actions-'+e(p.id)+'" class="meta">Checking connection status…</div></article>';
        }).join('');
      providers.forEach(function(p){
        requestJSON('/api/crm/status/'+encodeURIComponent(p.id),{cache:'no-store'}).then(function(s){
          if(version!==requestVersion)return;
          var badge=document.getElementById('crm-status-'+p.id), actions=document.getElementById('crm-actions-'+p.id);
          if(!badge||!actions)return;
          badge.textContent=s.connected?'Connected':s.configured?'Ready to connect':'Setup required';
          actions.innerHTML=s.connected?'<p>Authorized. Live CRM record verification and synchronization are not yet enabled.</p>':
            s.configured?'<a class="ghost" href="/connect/crm/'+encodeURIComponent(p.id)+'">Connect '+e(p.name)+'</a>':
            '<p>Provider app credentials or approval required before sign-in is available.</p>';
          if(selected===p.id)actions.scrollIntoView({block:'nearest'});
        }).catch(function(){var el=document.getElementById('crm-status-'+p.id);if(el)el.textContent='Unavailable';});
      });
    }).catch(function(err){if(version===requestVersion)error(err);});
  }
  function leads(){
    var title=labels[view]||'My Leads';
    panel.innerHTML=heading(title,view==='sent'?'Emails with a confirmed Gmail send record.':view==='drafts'?'Review your message and résumé, then choose Send.':view==='conversations'?'Sent messages, replies, and upcoming follow ups.':'Your saved prospects, newest first.')+
      '<div class="workspace-filters"><label>Search businesses<input id="lead-search" type="search" placeholder="Search by name or location"></label><label>Campaign<select id="lead-campaign"><option value="">All campaigns</option><option value="unassigned">Other saved leads</option>'+data.campaigns.map(function(c){return '<option value="'+e(c.id)+'">'+e(c.name)+'</option>';}).join('')+'</select></label>'+
      '<label>Status<select id="lead-status"><option value="">All statuses</option>'+Object.keys(statuses).filter(function(s){return !['queued','running','completed','failed'].includes(s);}).map(function(s){return '<option value="'+s+'">'+e(status(s))+'</option>';}).join('')+'</select></label><label>Sort by<select id="lead-sort"><option value="recent">Newest first</option><option value="score">Best fit &amp; need</option><option value="name">Business name</option></select></label></div><p class="meta" id="lead-count" aria-live="polite"></p><div id="lead-list"></div><p class="meta">Showing up to '+e(data.lead_limit)+' saved records, newest first (total '+e(data.lead_total)+'). Scores describe research fit, not a guarantee of a sale.</p>';
    panel.innerHTML+=pagination('leads',data.lead_offset,data.lead_limit,data.lead_total);
    ['lead-search','lead-campaign','lead-status','lead-sort'].forEach(function(id){document.getElementById(id).addEventListener(id==='lead-search'?'input':'change',filter);});filter();
  }
  function filter(){
    var term=document.getElementById('lead-search').value.toLowerCase(), campaign=document.getElementById('lead-campaign').value, chosen=document.getElementById('lead-status').value, sortBy=document.getElementById('lead-sort').value;
    var items=data.leads.filter(function(l){return (!term||(l.company+' '+l.location).toLowerCase().includes(term))&&(!chosen||l.status===chosen)&&(!campaign||(campaign==='unassigned'?!l.campaign_ids.length:l.campaign_ids.includes(campaign)))&&(view!=='conversations'||l.has_sent_message||l.replied_at||l.status==='drafted');});
    items.sort(function(a,b){return sortBy==='name'?a.company.localeCompare(b.company):sortBy==='recent'?String(b.activity_at||b.updated_at||'').localeCompare(String(a.activity_at||a.updated_at||''))||b.id-a.id:((b.prospect_quality||{}).rank||0)-((a.prospect_quality||{}).rank||0)||(score(b.score)||0)-(score(a.score)||0)||a.company.localeCompare(b.company);});
    document.getElementById('lead-count').textContent=items.length+' '+(items.length===1?'business':'businesses');
    document.getElementById('lead-list').innerHTML=items.length?(view!=='drafts'&&view!=='sent'&&window.bulkActivationControl?window.bulkActivationControl(items.map(function(l){return Object.assign({},l,{lead_id:l.id});})):'' )+items.map(function(l){return '<article class="lead workspace-lead"><div class="leadtop"><b>'+e(l.company)+'</b><span class="tag score-badge">'+e(badge(l.score))+'</span></div><p class="meta">'+e([l.business_type,l.location].filter(Boolean).join(' · ')||'Location not recorded')+'</p><p class="workspace-status">'+e(status(l.status))+'</p>'+((l.has_sent_message&&!l.replied_at&&l.follow_up_due_at)?'<p class="meta">Next follow up: '+e(date(l.follow_up_due_at))+'</p>':'')+(window.renderProspectQuality?window.renderProspectQuality(l.prospect_quality):'')+(view!=='drafts'&&view!=='sent'&&window.businessAction?window.businessAction({lead_id:l.id,contact_email:l.contact_email,selection:l.selection||{kind:'lead',lead_id:l.id},outreach:l.outreach}):'')+'<details data-lead-id="'+l.id+'"><summary>'+(view==='drafts'?'Review draft':view==='sent'?'View sent message':'View details')+'</summary><div class="lead-detail"></div></details></article>';}).join(''):'<div class="workspace-empty"><b>'+e(view==='sent'?'No sent emails yet':view==='drafts'?'No saved drafts yet':'No matching leads yet')+'</b><p>Try another filter, or start a new request in Chat.</p><button class="ghost" data-view="chat">Back to chat</button></div>';
    document.querySelectorAll('details[data-lead-id]').forEach(function(details){details.addEventListener('toggle',function(){if(!details.open||details.dataset.loaded)return;details.dataset.loaded='loading';var content=details.querySelector('.lead-detail');content.textContent='Loading contact details…';requestJSON(API+'/api/chat/dashboard/leads/'+details.dataset.leadId,{cache:'no-store'}).then(function(d){content.innerHTML=detail(d);details.dataset.loaded='yes';}).catch(function(err){content.textContent=err.message;delete details.dataset.loaded;});});});
  }
  function detail(d){
    var c=d.contact||{}, html=(view==='drafts'?draft(d):'')+'<dl class="contact-grid"><div><dt>Contact</dt><dd>'+e(c.name||c.type)+'</dd></div><div><dt>Role</dt><dd>'+e(c.role||'Not confirmed')+'</dd></div><div><dt>Email</dt><dd>'+e(c.email||'Still researching')+'<small>'+e(c.email_label)+' · '+e(c.type)+(c.checked_at?' · Checked '+e(date(c.checked_at)):'')+'</small></dd></div><div><dt>Phone</dt><dd>'+e(c.phone||'Not confirmed')+'</dd></div></dl>';
    if(window.renderProspectQuality)html+=window.renderProspectQuality(d.prospect_quality);
    html+='<h3>Why this score?</h3><p>'+e(d.score_description)+'</p><ul>'+(d.score_checks||[]).map(function(x){return '<li>'+e(checks[x]||x.replace(/_/g,' '))+'</li>';}).join('')+'</ul>';
    if(!(d.score_checks||[]).length)html+='<p class="meta">Detailed score breakdown is not recorded for this lead.</p>';
    if((d.reasons||[]).length)html+='<p class="meta">Still checking: '+d.reasons.map(function(r){return e(reason(r));}).join(' · ')+'</p>';
    html+='<h3>Business website & research</h3>'+(d.sources||[]).map(function(s){return '<p>'+link(s.url,s.title)+(s.observed_at?'<span class="meta"> · Checked '+e(date(s.observed_at))+'</span>':'')+(s.summary?'<small>'+e(s.summary)+'</small>':'')+'</p>';}).join('');
    html+='<h3>Email & reply history</h3>'+(d.timeline.length?'<ol class="workspace-timeline">'+d.timeline.slice().sort(function(a,b){return String(b.at).localeCompare(String(a.at));}).map(function(t){return '<li><b>'+e(t.type==='reply'?'Reply received':t.confirmed?kind(t.kind)+' sent':kind(t.kind)+' · '+status(t.status))+'</b><small>'+e(date(t.at))+'</small>'+(t.recipient?'<p>To: '+e(t.recipient)+'</p>':'')+(t.subject?'<p><b>'+e(t.subject)+'</b></p>':'')+(t.text?'<p class="email-copy">'+e(t.text)+'</p>':'')+'</li>';}).join('')+'</ol>':'<p class="meta">No sent message or reply recorded yet.</p>');
    if(d.body&&view!=='drafts')html+='<details><summary>'+(d.timeline.some(function(t){return t.confirmed;})?'Saved outreach message':'Prepared draft')+'</summary><p><b>'+e(d.subject)+'</b></p><p class="email-copy">'+e(d.body)+'</p></details>';
    html+='<h3>Appointments</h3>'+(d.bookings.some(function(b){return b.confirmed;})?d.bookings.filter(function(b){return b.confirmed;}).map(function(b){return '<p>'+e(date(b.start))+' · '+e(b.timezone)+' '+link(b.url,'Open in Calendar')+'</p>';}).join(''):'<p class="meta">No confirmed appointment recorded.</p>');
    if(view!=='drafts'&&window.businessAction)html+=window.businessAction({selection:{kind:'lead',lead_id:d.id},outreach:d.outreach});
    html+='<p><b>Next action:</b> '+e(d.status==='booked'?'Appointment booked':d.status==='sent'&&d.follow_up_due_at?'Follow up on '+date(d.follow_up_due_at):d.status==='drafted'?'Draft prepared. Sending has not been confirmed.':d.status==='needs_evidence'?'Continue contact research':status(d.status))+'</p>';
    return html;
  }
  function draft(d){
    var preview=d.draft_preview, state=d.outreach||{}, allowed=d.draft_send_allowed===true;
    if(!preview)return '<p role="status">This draft already has a send attempt or is no longer available. Refresh to check its status.</p>';
    return '<section class="draft-review"><h2>Review email</h2>'+window.messagePreview(preview)+
      '<button type="button" class="ghost" data-send-draft="'+d.id+'" data-draft-revision="'+e(preview.revision)+'"'+(!allowed?' disabled':'')+'>Send</button>'+
      '<p class="draft-send-status" role="status">'+e(allowed?'Checks the contact, sends your reviewed email, and activates scheduled follow-ups.':'This draft’s contact or send history needs review before sending.')+'</p>'+window.sendDetails(state.reason,state.reason_codes)+'</section>';
  }
  var sendingDrafts=new Set();
  document.addEventListener('click',function(event){
    var button=event.target.closest('[data-send-draft]');
    if(!button||button.disabled)return;
    var id=Number(button.dataset.sendDraft), revision=button.dataset.draftRevision, section=button.closest('.draft-review');
    if(sendingDrafts.has(id))return;
    sendingDrafts.add(id);button.disabled=true;button.textContent='Sending…';
    var output=section.querySelector('.draft-send-status');output.textContent='Checking and sending your reviewed email…';
    workspaceMutation(window.activateOutreachPath(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({activate:true,draft_revision:revision})})
      .then(function(result){
        if(result.job_id){
          if(!/^\/api\/demo\/campaigns\/jobs\/[A-Za-z0-9_-]+$/.test(result.poll_url||''))throw new Error('Invalid saved workflow.');
          var ref={kind:'lead',lead_id:id}, key=window.selectionId(ref);
          window.selectedWorkflows[key]={ref:ref,job:result,state:result,actionLabel:'Send',draftRevision:result.reviewed_draft_revision||revision,offer:result.reviewed_offer};
          var message=section.querySelector('.message-preview');
          if(message)message=message.outerHTML;
          section.innerHTML=(message||'')+window.selectionControl(ref);window.saveSelectedWorkflows();window.observeSelectedWorkflow(key);return;
        }
        var sent=window.emailSendStatus(result.outreach)==='Sent';
        button.textContent=sent?'Sent':'Not sent';output.textContent=window.sendMessage(window.emailSendStatus(result.outreach),result.outreach);
        if(sent)section.insertAdjacentHTML('beforeend','<button type="button" class="ghost" data-view="sent">Open Sent</button>');
      }).catch(function(err){
        // Observe after errors. Never automatically replay a send request.
        return requestJSON(API+'/api/chat/dashboard/leads/'+id,{cache:'no-store'}).then(function(result){
          var state=result.outreach||{}, label=window.emailSendStatus(state);
          button.textContent=label;output.textContent=window.sendMessage(label,state,err.message);
          section.insertAdjacentHTML('beforeend',window.sendDetails(err.message));
        }).catch(function(){button.textContent='Check status';output.textContent='Refresh to check whether this email was sent before trying again.';});
      }).finally(function(){sendingDrafts.delete(id);});
  });
  function reason(code){var meanings={MISSING_VALIDATED_CONTACT:'Contact details need verification',NAMED_DECISION_MAKER_EMAIL_REQUIRED:'Named contact email needs confirmation',EVIDENCE_RECENCY_UNPROVEN:'Research date needs confirmation',INTENT_SIGNAL_UNPROVEN:'Business need needs confirmation',BUSINESS_TYPE_FIT_UNPROVEN:'Business type needs confirmation',GEOGRAPHIC_FIT_UNPROVEN:'Location needs confirmation'};return meanings[code]||String(code).toLowerCase().replace(/_/g,' ');}
  function kind(value){return {initial:'Outreach email',followup:'Follow up',automatic_reply:'Reply',booking_confirmation:'Booking confirmation'}[value]||'Email';}
  function liveOutcomes(c){
    var live=c.live_outcomes||{};
    if(!live.available)return '<p class="meta">Live outcomes unavailable: '+e(live.unavailable_reason||'No durable attribution recorded.')+'</p>';
    var n=live.counts||{},r=live.rates||{};
    function percent(v){return typeof v==='number'?v+'%':'Not available';}
    return '<p>Well-supported prospects: '+e(n.well_supported||0)+' of '+e(live.requested||10)+' requested · Buyers identified: '+e(n.buyer_identified||0)+' · Contacts ready: '+e(n.contact_ready||0)+' · Shortfall: '+e(live.remaining_well_supported||0)+'.</p><p class="meta">'+e(live.quality_basis||'')+'</p><h3>Live campaign outcomes</h3><p>'+e(n.sent)+' contacts emailed · '+e(n.replies)+' with recorded replies · '+e(n.positive_replies)+' positive replies · '+e(n.conversations||0)+' classified relevant conversations · '+e(n.booked)+' booked</p><p class="meta">Reply rate per sent contact: '+percent(r.reply_rate_per_sent)+' · Booking rate per sent contact: '+percent(r.booking_rate_per_sent)+'</p><p class="meta">Held: '+e(n.held)+' · Pending: '+e(n.pending)+' · With errors: '+e(n.failed)+'. Delivery, customers, and revenue require additional recorded evidence.</p>'+Object.keys(live.source_breakdown||{}).map(function(source){var x=live.source_breakdown[source];return '<p class="meta">'+e(source)+': '+e(x.prospects)+' prospects · '+e(x.well_supported)+' well supported · '+e(x.conversations)+' conversations · '+e(x.booked)+' bookings.</p>';}).join('')+'<p class="meta">'+e(live.sample_note||'')+'</p>';
  }
  function pagination(kind,offset,limit,total){
    var html='<p class="meta">Showing '+(total?offset+1:0)+'–'+Math.min(offset+limit,total)+' of '+total+'</p>';
    if(offset>0)html+='<button class="ghost" data-page="'+kind+'" data-offset="'+Math.max(0,offset-limit)+'">Previous page</button> ';
    if(offset+limit<total)html+='<button class="ghost" data-page="'+kind+'" data-offset="'+(offset+limit)+'">Next page</button>';
    return html;
  }
  function campaigns(){
    panel.innerHTML=heading('My Campaigns','Newest campaigns first. Completion snapshots and ongoing receipt-backed outcomes.')+
      (data.campaigns.length?data.campaigns.map(function(c){
        return '<article class="lead"><div class="leadtop"><b>'+e(c.name)+'</b><span class="tag">'+e(status(c.status))+'</span></div><p class="meta">'+e(c.territory)+' · '+e(date(c.created_at))+'</p><h3>Completion snapshot</h3><div class="stats"><div class="stat"><b>'+c.research_results+'</b>Research results</div><div class="stat"><b>'+c.verified+'</b>Confirmed businesses</div><div class="stat"><b>'+c.qualified+'</b>Qualified contacts</div><div class="stat"><b>'+c.sent+'</b>Emails sent</div></div>'+liveOutcomes(c)+'<p class="meta">'+(c.status==='running'||c.status==='queued'?'Work is in progress.':'Snapshot retained; live outcomes update on refresh.')+'</p><button class="ghost" data-campaign="'+e(c.id)+'">View campaign leads</button></article>';
      }).join(''):'<div class="workspace-empty"><b>No campaigns yet</b></div>')+
      pagination('campaigns',data.campaign_offset,data.campaign_limit,data.campaign_total);
  }

  function appointments(version){requestJSON(API+'/api/chat/dashboard/appointments',{cache:'no-store'}).then(function(d){if(version!==requestVersion)return;panel.innerHTML=heading('Appointments','Latest meetings first, with saved Calendar confirmations.')+(d.appointments.length?d.appointments.map(function(a){return '<article class="lead"><b>'+e(a.company)+'</b><p>'+e(date(a.start))+'</p><p class="meta">'+e(a.timezone)+' · '+e(a.attendee)+'</p>'+link(a.url,'Open in Calendar')+'</article>';}).join(''):'<div class="workspace-empty"><b>No confirmed appointments yet</b><p>Meetings will appear here after a prospect agrees to a time and Calendar confirms the booking.</p></div>');}).catch(function(err){if(version===requestVersion)error(err);});}
  function preference(key,fallback){try{return localStorage.getItem('automake.'+key)||fallback;}catch(ignore){return fallback;}}
  function settings(version){requestJSON(API+'/api/chat/dashboard/settings',{cache:'no-store'}).then(function(d){if(version!==requestVersion)return;panel.innerHTML=heading('Settings','Simple defaults for your next campaign.')+'<div class="lead"><h2>Your email</h2><p>'+e(d.sender_name)+' · '+e(d.sender_company)+'</p><p>'+e(d.sender_email||'No sender recorded')+'</p><p class="meta">'+(d.google_configured?'Google account configured. Check the connection to confirm access.':'Connect your Google account to send and manage appointments.')+'</p><a href="/gmail">Manage Google connection</a> <button class="ghost" id="check-google">Check connection</button><p id="google-check" class="meta" aria-live="polite"></p></div><form id="workspace-preferences" class="lead"><h2>Campaign defaults</h2><label>Target territory<input name="territory" value="'+e(preference('territory','Hampton Roads, Virginia'))+'" maxlength="200" required></label><label>Maximum emails per campaign<input name="limit" type="number" min="1" max="100" value="'+e(preference('limit','10'))+'" required></label><label>Default mode<select name="mode"><option value="campaign">Research & prepare drafts</option><option value="research">Research only</option></select></label><p class="meta">These defaults are saved on this device and apply to new requests. Changing them does not start a campaign.</p><button class="ghost" type="submit">Save defaults</button><span id="preferences-saved" role="status"></span></form><div class="lead"><h2>Follow ups & appointments</h2><p>First follow up after '+e(d.first_followup_days)+' days, with up to '+e(d.maximum_followups)+' scheduled follow ups. Replies and opt outs control whether follow ups continue.</p><p class="meta">Calendar booking waits for an agreed time and confirmed availability.</p></div>';
      var integrations=d.integrations||{},names={autohunt:'AutoHunt',web_research:'Web research',places:'Google Places',hunter:'Hunter',verifalia:'Verifalia',google:'Gmail & Calendar'};
      var connections='<section class="lead"><h2>Connected tools</h2><p>These tools run inside your research and outreach workflow.</p>';
      Object.keys(names).forEach(function(key){var tool=integrations[key]||{};connections+='<p><b>'+e(names[key])+'</b> · '+(key==='autohunt'?'Built in':tool.configured?'Configured':'Not configured')+'<small>'+e(tool.purpose||'')+'</small></p>';});
      connections+='<p class="meta">Hunter account: '+e((integrations.hunter||{}).account||'Not connected')+'</p><button class="ghost" id="check-hunter">Check Hunter connection</button><p id="hunter-check" class="meta" aria-live="polite"></p><p class="meta">Configured means credentials are saved. Each tool is checked when it runs.</p></section>';
      panel.insertAdjacentHTML('beforeend',connections+'<section class="lead"><h2>Your automation flow</h2><ol><li>Find businesses and collect public contacts with AutoHunt</li><li>Verify mailboxes separately when needed</li><li>Activate one business or all with email</li><li>Send outreach and scheduled follow-ups</li><li>Handle replies and book agreed appointments</li></ol><a href="/workflows">Open workflow builder</a></section>');
      document.getElementById('check-hunter').onclick=function(){var button=this;button.disabled=true;workspaceMutation('/api/chat/dashboard/hunter/check',{method:'POST',body:'{}'}).then(function(result){document.getElementById('hunter-check').textContent=result.state+(typeof result.credits_remaining==='number'?' · '+result.credits_remaining+' credits remaining':'');}).catch(function(){document.getElementById('hunter-check').textContent='Connection check unavailable. Try again.';}).finally(function(){button.disabled=false;});};
      panel.insertAdjacentHTML('beforeend','<form id="verifalia-connect" class="lead"><h2>Free email verification</h2><p>Verifalia: '+((integrations.verifalia||{}).configured?'Configured — check connection':'Not connected')+'</p><p>Use your free Verifalia account or a dedicated API user. Standard checks use the daily free allowance, capped at 25 new checks a day in AutoMake AI. Unknown and catch-all results stay unverified.</p><p><a href="https://verifalia.com/sign-up" target="_blank" rel="noopener noreferrer">Create your free Verifalia account</a></p><label>Verifalia API username<input name="username" autocomplete="off" required maxlength="500"></label><label>Verifalia API password<input name="password" type="password" autocomplete="off" required maxlength="1000"></label><label><input name="free_only" type="checkbox" style="width:auto" required>Use free-only verification. My Verifalia account has no paid credit packs or automatic top-ups.</label><button class="ghost" type="submit">Connect free verification</button> <button class="ghost" type="button" id="check-verifalia">Check connection</button><p id="verifalia-status" role="status"></p></form>');
      var verifier=document.getElementById('verifalia-connect');
      verifier.onsubmit=function(event){event.preventDefault();if(!verifier.reportValidity())return;var button=verifier.querySelector('button[type="submit"]');button.disabled=true;var body={username:verifier.elements.username.value,password:verifier.elements.password.value,free_only:verifier.elements.free_only.checked};verifier.elements.password.value='';workspaceMutation('/api/chat/dashboard/verifalia/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(result){document.getElementById('verifalia-status').textContent=result.state+' · '+result.free_remaining+' free checks remaining';}).catch(function(err){document.getElementById('verifalia-status').textContent=err.message;}).finally(function(){button.disabled=false;});};
      document.getElementById('check-verifalia').onclick=function(){var button=this;button.disabled=true;workspaceMutation('/api/chat/dashboard/verifalia/check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(result){document.getElementById('verifalia-status').textContent=result.state+(typeof result.free_remaining==='number'?' · '+result.free_remaining+' free checks remaining':'');}).catch(function(err){document.getElementById('verifalia-status').textContent=err.message;}).finally(function(){button.disabled=false;});};
      var form=document.getElementById('workspace-preferences');form.elements.mode.value=preference('mode','campaign');
      form.onsubmit=function(event){event.preventDefault();if(!form.reportValidity())return;try{localStorage.setItem('automake.territory',form.elements.territory.value);localStorage.setItem('automake.limit',form.elements.limit.value);localStorage.setItem('automake.mode',form.elements.mode.value);applyPreferences();document.getElementById('preferences-saved').textContent=' Saved';}catch(ignore){document.getElementById('preferences-saved').textContent=' This browser could not save your defaults.';}};
      document.getElementById('check-google').onclick=function(){var button=this;button.disabled=true;requestJSON(API+'/api/gmail/status',{cache:'no-store'}).then(function(result){document.getElementById('google-check').textContent=result.connected?'Connected as '+result.email:'Reconnect your Google account to restore access.';}).catch(function(){document.getElementById('google-check').textContent='Connection check unavailable. Try again.';}).finally(function(){button.disabled=false;});};
    }).catch(function(err){if(version===requestVersion)error(err);});}
  function applyPreferences(){document.getElementById('territory').value=preference('territory','Hampton Roads, Virginia');document.getElementById('task-mode').value=window.workspaceAccess&&window.workspaceAccess.sending_available?preference('mode','research'):'research';if(window.syncComposerState)window.syncComposerState();}
  document.addEventListener('click',function(event){var button=event.target.closest('[data-view], [data-refresh], [data-campaign], [data-page]');if(button){if(button.dataset.page){if(button.dataset.page==='campaigns')campaignOffset=Number(button.dataset.offset);else leadOffset=Number(button.dataset.offset);open(view);return;}if(button.dataset.view)open(button.dataset.view);else if(button.hasAttribute('data-refresh'))open(view);else{view='leads';document.querySelectorAll('[data-view]').forEach(function(b){b.classList.toggle('active',b.dataset.view==='leads');b.setAttribute('aria-current',b.dataset.view==='leads'?'page':'false');});leads();document.getElementById('lead-campaign').value=button.dataset.campaign;filter();}}if(menu.open&&!menu.contains(event.target)&&window.matchMedia('(max-width:900px)').matches)menu.open=false;});
  document.addEventListener('keydown',function(event){if(event.key==='Escape'&&menu.open){menu.open=false;menu.querySelector('summary').focus();}});
  window.openWorkspace=open;window.campaignEmailLimit=function(target){var n=Number(preference('limit','10'));return Math.min(target,Math.max(1,Math.min(100,Number.isFinite(n)?n:10)));};
  window.applyWorkspacePreferences=applyPreferences;
  applyPreferences();
})();
