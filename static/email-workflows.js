/* A separate workspace desk for explicitly entered email recipients. */
(function(){
  'use strict';
  var mount=0,timer=null,recognition=null,selected=new Set(),seen=new Set(),contacts=[],busy=false;
  var names={idle:'Not activated',queued:'Queued',running:'Activating…',active:'Workflow active',held:'Needs attention',review:'Check send status',stopped:'Stopped'};
  function esc(value){return window.esc(value);}
  window.parseWorkflowEmails=function(value){
    var normalized=String(value||'').replace(/\s+at\s+/gi,'@').replace(/\s+dot\s+/gi,'.')
      .replace(/\s+underscore\s+/gi,'_').replace(/\s+dash\s+/gi,'-').replace(/\s+(?:comma|semicolon)\s*/gi,',')
      .replace(/\s*([@._+\-])\s*/g,'$1');
    return Array.from(new Set(normalized.split(/[\s,;]+/).filter(Boolean).map(function(email){return email.toLowerCase();})));
  };
  window.renderEmailWorkflowDesk=function(panel,importOnly){
    var generation=++mount,pdfContacts=new Map();
    clearTimeout(timer);if(recognition){recognition.stop();recognition=null;}
    panel.innerHTML='<div class="workspace-heading"><div><h1>'+(importOnly?'Import Leads':'Email workflows')+'</h1><p class="meta">'+(importOnly?'Upload a lead PDF or paste contact details, then choose which leads to activate.':'Add email addresses, choose your recipients, and activate their workflows.')+'</p></div><button class="ghost email-workflows-primary" type="button" id="activate-email-workflows" disabled>Activate all workflows</button></div>'+
      '<section class="email-workflow-entry lead"><label for="workflow-emails"><b>Type or say an email address</b></label><textarea id="workflow-emails" rows="3" autocapitalize="none" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="name@company.com&#10;Add more addresses on separate lines"></textarea>'+
      '<div class="email-workflow-entry-actions"><button class="ghost" type="button" id="dictate-workflow-email" aria-pressed="false">🎙 Dictate email</button><button class="ghost email-workflows-primary" type="button" id="add-workflow-emails">Add email addresses</button></div>'+
      '<details class="email-workflow-entry" id="lead-import"><summary><b>Import lead list or PDF</b></summary>'+
      '<p class="meta">Upload a lead PDF. Email addresses go into the email workflow; names and phone numbers appear separately below.</p>'+
      '<label for="workflow-pdf">Choose a PDF</label> <input id="workflow-pdf" type="file" accept=".pdf,application/pdf">'+
      '<div class="import-parts"><section class="import-email-part"><h2>Email addresses</h2><p class="meta">Only these email addresses enter the email workflow. Remove any you do not want to add.</p><label for="workflow-lead-rows">Review extracted emails</label>'+
      '<textarea id="workflow-lead-rows" rows="6" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="owner@company.com&#10;manager@company.com"></textarea></section>'+
      '<section class="import-phone-part"><h2>Names &amp; phone numbers</h2><p class="meta">Contact details from the same PDF. These stay separate from the email list and do not start calls or messages.</p><div id="import-contact-details" class="import-contact-details" role="group" aria-label="Extracted names and phone numbers"><p class="meta">Names and phone numbers will appear here after you upload a PDF.</p></div></section></div>'+
      '<button class="ghost email-workflows-primary" type="button" id="add-workflow-leads">Add imported leads</button></details>'+
      '<details id="verified-workflow-picker" class="email-workflow-entry"><summary style="cursor:pointer;font-weight:650">✓ Select from Verified Emails</summary><p class="meta">Select verified decision-makers who have never had an outreach workflow activated. Adding an address will not send an email.</p><div id="verified-workflow-picker-items" role="group" aria-label="Available verified emails"></div><div class="email-workflow-entry-actions"><button class="ghost" type="button" id="verified-workflow-picker-select-all">Select all available</button><button class="ghost email-workflows-primary" type="button" id="verified-workflow-picker-add">Add selected to email box</button><button class="ghost" type="button" id="verified-workflow-picker-refresh">Refresh</button></div><p class="meta" id="verified-workflow-picker-count" role="status"></p></details>'+
      '<p class="meta" id="email-voice-status" role="status">You can say “name at company dot com.” Review the address before adding it.</p></section>'+
      '<section id="import-saved-contacts" class="lead email-workflow-entry"'+(importOnly?'':' hidden')+'><h2>Saved names &amp; phone numbers</h2><div id="import-contact-directory"></div></section>'+
      '<h2 class="import-email-title"'+(importOnly?'':' hidden')+'>Email workflows</h2>'+
      '<div class="email-workflow-toolbar"><label><input type="checkbox" id="select-email-workflows"> Select all</label><span class="meta" id="email-workflow-count" aria-live="polite"></span><button class="ghost" type="button" id="refresh-email-workflows">Refresh</button></div>'+
      '<p class="meta">Activation sends your outreach email and résumé, then handles follow-ups and books a calendar meeting once the lead agrees to a time.</p><p id="email-workflow-notice" role="status" aria-live="polite"></p><div id="email-workflow-list"><span class="loading"></span> Loading your email workflows…</div>';
    var input=panel.querySelector('#workflow-emails'),notice=panel.querySelector('#email-workflow-notice');
    if(importOnly){
      var importSection=panel.querySelector('#lead-import');
      var emailEntry=importSection.parentElement;
      emailEntry.before(importSection);
      emailEntry.hidden=true;
      importSection.open=true;
    }
    function current(){return generation===mount&&panel.querySelector('#workflow-emails')===input&&!panel.hidden;}
    function message(value,error){if(!current())return;notice.textContent=value||'';notice.className=error?'error':'meta';}
    function eligible(){return contacts.filter(function(row){return row.can_activate;});}
    function updateSelection(){
      var ready=eligible(),count=ready.filter(function(row){return selected.has(row.id);}).length;
      panel.querySelector('#email-workflow-count').textContent=count+' selected · '+contacts.length+' email '+(contacts.length===1?'address':'addresses');
      var all=panel.querySelector('#select-email-workflows');all.disabled=!ready.length||busy;all.checked=!!ready.length&&count===ready.length;all.indeterminate=count>0&&count<ready.length;
      var activate=panel.querySelector('#activate-email-workflows');activate.disabled=busy||count===0;activate.textContent=busy?'Activating…':'Activate all workflows';
    }
    function renderRows(){
      if(!current())return;
      panel.querySelector('#email-workflow-list').innerHTML=contacts.length?contacts.map(function(row){
        if(!row.can_activate)selected.delete(row.id);
        return '<article class="lead email-workflow-row"><div class="leadtop"><label class="email-workflow-recipient"><input type="checkbox" data-email-workflow-select="'+esc(row.id)+'"'+(selected.has(row.id)&&row.can_activate?' checked':'')+(!row.can_activate||busy?' disabled':'')+'><b>'+esc(row.email)+'</b></label><span class="tag">'+esc(names[row.status]||row.status)+'</span></div><p class="meta">Added by you'+(importOnly?[]:[row.name,row.company,row.phone]).filter(Boolean).map(function(value){return ' · '+esc(value);}).join('')+(row.follow_up_due_at?' · Follow-up '+esc(new Date(row.follow_up_due_at).toLocaleString()):'')+'</p>'+
          '<div class="email-workflow-row-actions"><button type="button" class="ghost" data-email-workflow-activate="'+esc(row.id)+'"'+(!row.can_activate||busy?' disabled':'')+'>'+esc(row.status==='active'?'Workflow active':row.status==='queued'||row.status==='running'?'Activating…':'Activate workflow')+'</button><button type="button" class="ghost" data-email-workflow-preview="'+esc(row.id)+'">View email &amp; résumé</button></div>'+
          (row.reason?'<p class="meta">'+esc(row.reason)+'</p>':'')+'<div class="email-workflow-preview" data-email-preview-for="'+esc(row.id)+'"></div></article>';
      }).join(''):importOnly?'<div class="workspace-empty"><h2>Your saved contacts will appear here</h2><p>Add reviewed leads above to select and activate them. Imported and manually added contacts are also available in Email workflows.</p></div>':'<div class="workspace-empty"><h2>Your email workflows will appear here</h2><p>Add one or more email addresses above. Each address gets its own workflow and selection box.</p></div>';
      var directory=panel.querySelector('#import-contact-directory');
      var details=contacts.filter(function(row){return row.name||row.phone;});
      directory.innerHTML=details.length?details.map(function(row){return '<article class="import-saved-contact"><b>'+esc(row.name||row.company||'Contact')+'</b>'+(row.company&&row.name?'<span class="meta">'+esc(row.company)+'</span>':'')+'<span>'+esc(row.phone||'No phone number in PDF')+'</span></article>';}).join(''):'<p class="meta">Saved names and phone numbers will appear here.</p>';
      updateSelection();
    }
    function load(){
      clearTimeout(timer);
      return requestJSON(API+'/api/chat/email-workflows',{cache:'no-store'}).then(function(data){
        if(!current())return;
        contacts=data.contacts||[];contacts.forEach(function(row){if(!seen.has(row.id)&&row.can_activate)selected.add(row.id);seen.add(row.id);});
        renderRows();
        if(notice.dataset.connectionError){delete notice.dataset.connectionError;message('Workflow status refreshed. Review the statuses below.');}
        if(contacts.some(function(row){return ['queued','running'].includes(row.status);}))timer=setTimeout(load,2500);
      }).catch(function(error){
        if(!current())return;
        notice.dataset.connectionError='true';
        message(error.status===401||error.status===403?'Sign in to your connected workspace to load your contacts.':'Could not refresh workflow status. Your displayed contacts are kept. Tap Refresh to reconnect.',true);
        if(contacts.length){renderRows();return;}
        panel.querySelector('#email-workflow-list').innerHTML=error.status===401||error.status===403?'<div class="workspace-empty"><a href="/login">Sign in</a></div>':'<div class="workspace-empty"><p>Could not load saved contacts. Tap Refresh to try again.</p></div>';
      });
    }
    function activate(ids){
      if(busy||!ids.length)return;
      busy=true;renderRows();message('Activating '+ids.length+' selected '+(ids.length===1?'workflow':'workflows')+'…');
      var offer=document.getElementById('customer-offer');
      workspaceMutation('/api/chat/email-workflows/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({activate:true,ids:ids,offer:offer?offer.value:''})})
        .then(function(job){ids.forEach(function(id){selected.delete(id);});message('Your selected workflows are queued. Their send status will update below.');return load();})
        .catch(function(error){message(error.message,true);return load();})
        .finally(function(){busy=false;if(current())renderRows();});
    }
    var verifiedChoices=[],verifiedSelected=new Set(),pickerInserted=new Set();
    function syncVerifiedToEntry(){
      var currentEmails=window.parseWorkflowEmails(input.value);
      var original=currentEmails.filter(function(email){return !pickerInserted.has(email);});
      var chosen=verifiedChoices.filter(function(row){return verifiedSelected.has(row.email);}).map(function(row){return row.email;});
      input.value=Array.from(new Set(original.concat(chosen))).join('\n');
      pickerInserted=new Set(chosen.filter(function(email){return original.indexOf(email)<0;}));
    }
    function updateVerifiedPicker(){
      var count=verifiedSelected.size;
      panel.querySelector('#verified-workflow-picker-count').textContent=count+' selected · '+verifiedChoices.length+' verified emails available';
      panel.querySelector('#verified-workflow-picker-add').disabled=!count||busy;
      panel.querySelector('#verified-workflow-picker-select-all').disabled=!verifiedChoices.length||busy;
    }
    function loadVerifiedPicker(){
      var target=panel.querySelector('#verified-workflow-picker-items');
      target.textContent='Loading eligible verified contacts…';
      return requestJSON(API+'/api/chat/email-workflows/verified-available',{cache:'no-store'}).then(function(result){
        if(!current())return;
        verifiedChoices=result.contacts||[];
        verifiedSelected=new Set(Array.from(verifiedSelected).filter(function(email){return verifiedChoices.some(function(p){return p.email===email;});}));
        target.innerHTML=verifiedChoices.length?verifiedChoices.map(function(person){
          return '<label class="verified-workflow-option" ><input type="checkbox" data-verified-workflow-email="'+esc(person.email)+'"'+(verifiedSelected.has(person.email)?' checked':'')+'><span><b>'+esc(person.name||person.email)+'</b><span class="meta" style="display:block;overflow-wrap:anywhere">'+esc(person.email)+' · '+esc(person.role||'Decision-maker')+' · '+esc(person.company||'')+'</span></span></label>';
        }).join(''):'<p class="meta">No verified, never-activated contacts available right now.</p>';
        updateVerifiedPicker();
      }).catch(function(err){if(current()){target.textContent='Could not load verified emails: '+err.message;updateVerifiedPicker();}});
    }
    panel.querySelector('#verified-workflow-picker').ontoggle=function(){if(this.open)loadVerifiedPicker();};
    panel.querySelector('#verified-workflow-picker-items').onchange=function(event){
      var email=event.target.dataset.verifiedWorkflowEmail;
      if(!email)return;
      if(event.target.checked)verifiedSelected.add(email);else verifiedSelected.delete(email);
      syncVerifiedToEntry();updateVerifiedPicker();
    };
    panel.querySelector('#verified-workflow-picker-select-all').onclick=function(){
      verifiedChoices.forEach(function(row){verifiedSelected.add(row.email);});
      panel.querySelectorAll('[data-verified-workflow-email]').forEach(function(box){box.checked=true;});
      syncVerifiedToEntry();updateVerifiedPicker();
    };
    panel.querySelector('#verified-workflow-picker-refresh').onclick=loadVerifiedPicker;
    panel.querySelector('#verified-workflow-picker-add').onclick=function(){
      var candidates=verifiedChoices.filter(function(row){return verifiedSelected.has(row.email);}).map(function(row){return row.email;});
      if(!candidates.length)return;
      var existing=window.parseWorkflowEmails(input.value);
      input.value=Array.from(new Set(existing.concat(candidates))).join('\n');
      verifiedSelected.clear();pickerInserted.clear();updateVerifiedPicker();
      message(candidates.length+' verified email'+(candidates.length===1?'':'s')+' placed in the entry box. Choose Add email addresses, then activate your selected workflows.');
      input.focus();
    };
    panel.querySelector('#add-workflow-emails').onclick=function(){
      var addresses=window.parseWorkflowEmails(input.value);
      if(!addresses.length){message('Type or dictate an email address first.',true);input.focus();return;}
      var invalid=addresses.filter(function(email){return email.length>254||! /^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$/i.test(email);});
      if(invalid.length){message('Check these addresses: '+invalid.join(', '),true);input.focus();return;}
      var button=this;button.disabled=true;
      workspaceMutation('/api/chat/email-workflows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emails:addresses})})
        .then(function(result){input.value='';(result.contacts||[]).forEach(function(row){if(row.can_activate)selected.add(row.id);seen.add(row.id);});message(result.message);return load();})
        .catch(function(error){message(error.message,true);}).finally(function(){button.disabled=false;});
    };
    var leadRows=panel.querySelector('#workflow-lead-rows'),pdf=panel.querySelector('#workflow-pdf');
    var importBox=panel.querySelector('#lead-import'),addLeads=panel.querySelector('#add-workflow-leads');
    function previewPdf(file){
      if(!file||pdf.disabled)return;
      if(leadRows.value.trim()){message('Add or clear the current preview before importing another PDF.',true);return;}
      if(file.size>5*1024*1024){message('Use a PDF up to 5 MB.',true);return;}
      var form=new FormData();form.append('pdf',file);
      pdf.disabled=true;addLeads.disabled=true;message('Reading the PDF…');
      workspaceMutation('/api/chat/email-workflows/pdf-preview',{method:'POST',body:form})
        .then(function(result){
          if(!current())return;
          pdfContacts=new Map(result.contacts.map(function(row){return [String(row.email).toLowerCase(),row];}));
          leadRows.value=Array.from(pdfContacts.keys()).join('\n');
          panel.querySelector('#import-contact-details').innerHTML=Array.from(pdfContacts.entries()).map(function(entry){
            var email=entry[0],row=entry[1];
            return '<article class="import-detail"><label>Name<input type="text" data-import-email="'+esc(email)+'" data-import-field="name" maxlength="300" value="'+esc(row.name||'')+'"></label><label>Phone number<input type="tel" data-import-email="'+esc(email)+'" data-import-field="phone" maxlength="80" value="'+esc(row.phone||'')+'"></label><label>Company<input type="text" data-import-email="'+esc(email)+'" data-import-field="company" maxlength="300" value="'+esc(row.company||'')+'"></label></article>';
          }).join('');
          message(pdfContacts.size+' email addresses extracted. Review emails and contact details in their separate sections, then choose Add imported leads.');
        }).catch(function(error){message(error.message,true);})
        .finally(function(){pdf.value='';pdf.disabled=false;addLeads.disabled=false;});
    }
    pdf.onchange=function(){previewPdf(pdf.files[0]);pdf.value='';};
    importBox.ondragover=function(event){if(Array.from(event.dataTransfer.types).includes('Files'))event.preventDefault();};
    importBox.ondrop=function(event){
      if(!event.dataTransfer.files.length)return;
      event.preventDefault();importBox.open=true;previewPdf(event.dataTransfer.files[0]);
    };
    addLeads.onclick=function(){
      var emails=window.parseWorkflowEmails(leadRows.value);
      if(!emails.length){message('Paste email addresses or choose a PDF first.',true);return;}
      if(emails.some(function(email){return email.length>254||! /^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$/i.test(email);})){message('Use email addresses only in the email section. Names and phone numbers belong in the separate contact details section.',true);return;}
      panel.querySelectorAll('[data-import-field]').forEach(function(field){
        var row=pdfContacts.get(field.dataset.importEmail);if(row)row[field.dataset.importField]=field.value.trim();
      });
      var rows=emails.map(function(email){var details=pdfContacts.get(email)||{};return {email:email,name:details.name||'',phone:details.phone||'',company:details.company||''};});
      addLeads.disabled=true;
      workspaceMutation('/api/chat/email-workflows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contacts:rows})})
        .then(function(result){
          leadRows.value='';pdfContacts.clear();panel.querySelector('#import-contact-details').innerHTML='<p class="meta">Contact details saved below. Upload another PDF to add more.</p>';
          var saved=result.contacts||[],byId=new Map(contacts.map(function(row){return [row.id,row];}));
          saved.forEach(function(row){byId.set(row.id,row);if(row.can_activate)selected.add(row.id);seen.add(row.id);});
          contacts=Array.from(byId.values());renderRows();
          message(result.message);return load();
        }).catch(function(error){message(error.message,true);}).finally(function(){addLeads.disabled=false;});
    };
    panel.querySelector('#select-email-workflows').onchange=function(){var checked=this.checked;eligible().forEach(function(row){if(checked)selected.add(row.id);else selected.delete(row.id);});renderRows();};
    panel.querySelector('#activate-email-workflows').onclick=function(){activate(eligible().filter(function(row){return selected.has(row.id);}).map(function(row){return row.id;}));};
    panel.querySelector('#refresh-email-workflows').onclick=load;
    panel.querySelector('#email-workflow-list').onchange=function(event){var id=event.target.dataset.emailWorkflowSelect;if(!id)return;if(event.target.checked)selected.add(id);else selected.delete(id);updateSelection();};
    panel.querySelector('#email-workflow-list').onclick=function(event){
      var activateButton=event.target.closest('[data-email-workflow-activate]');
      if(activateButton&&!activateButton.disabled){activate([activateButton.dataset.emailWorkflowActivate]);return;}
      var previewButton=event.target.closest('[data-email-workflow-preview]');if(!previewButton)return;
      var id=previewButton.dataset.emailWorkflowPreview,slot=previewButton.closest('.email-workflow-row').querySelector('.email-workflow-preview');previewButton.disabled=true;
      requestJSON(API+'/api/chat/email-workflows/'+encodeURIComponent(id)+'/preview',{cache:'no-store'})
        .then(function(result){slot.innerHTML=window.messagePreview(result.preview);})
        .catch(function(error){slot.textContent=error.message;}).finally(function(){previewButton.disabled=false;});
    };
    panel.querySelector('#dictate-workflow-email').onclick=function(){
      var button=this,voice=panel.querySelector('#email-voice-status');
      if(recognition){recognition.stop();recognition=null;return;}
      var Speech=window.SpeechRecognition||window.webkitSpeechRecognition;
      if(!Speech){voice.textContent='Use the microphone on your phone’s keyboard to dictate into the email field.';input.focus();return;}
      recognition=new Speech();recognition.lang=navigator.language||'en-US';recognition.interimResults=false;
      recognition.onstart=function(){button.setAttribute('aria-pressed','true');button.textContent='Stop dictation';voice.textContent='Listening… Say the email address, including “at” and “dot.”';};
      recognition.onresult=function(event){var text=Array.from(event.results).map(function(result){return result[0].transcript;}).join(' ');input.value+=(input.value.trim()?'\n':'')+window.parseWorkflowEmails(text).join('\n');voice.textContent='Review the address, then choose Add email addresses.';};
      recognition.onerror=function(){voice.textContent='Dictation stopped. You can type the address or use your keyboard’s microphone.';};
      recognition.onend=function(){recognition=null;button.setAttribute('aria-pressed','false');button.textContent='🎙 Dictate email';};
      try{recognition.start();}catch(error){recognition=null;voice.textContent='Use your keyboard microphone or type the email address.';}
    };
    load();
  };
  if(new URLSearchParams(window.location.search).get('view')==='email-workflows')window.openWorkspace('email-workflows');
})();
