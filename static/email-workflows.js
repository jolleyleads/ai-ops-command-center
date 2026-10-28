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
  window.renderEmailWorkflowDesk=function(panel){
    var generation=++mount;
    clearTimeout(timer);if(recognition){recognition.stop();recognition=null;}
    panel.innerHTML='<div class="workspace-heading"><div><h1>Email workflows</h1><p class="meta">Add email addresses, choose your recipients, and activate their workflows.</p></div><button class="ghost email-workflows-primary" type="button" id="activate-email-workflows" disabled>Activate all workflows</button></div>'+
      '<section class="email-workflow-entry lead"><label for="workflow-emails"><b>Type or say an email address</b></label><textarea id="workflow-emails" rows="3" autocapitalize="none" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="name@company.com&#10;Add more addresses on separate lines"></textarea>'+
      '<div class="email-workflow-entry-actions"><button class="ghost" type="button" id="dictate-workflow-email" aria-pressed="false">🎙 Dictate email</button><button class="ghost email-workflows-primary" type="button" id="add-workflow-emails">Add email addresses</button></div><p class="meta" id="email-voice-status" role="status">You can say “name at company dot com.” Review the address before adding it.</p></section>'+
      '<div class="email-workflow-toolbar"><label><input type="checkbox" id="select-email-workflows"> Select all</label><span class="meta" id="email-workflow-count" aria-live="polite"></span><button class="ghost" type="button" id="refresh-email-workflows">Refresh</button></div>'+
      '<p class="meta">Activation sends your outreach email and résumé, then starts follow-ups and reply handling.</p><p id="email-workflow-notice" role="status" aria-live="polite"></p><div id="email-workflow-list"><span class="loading"></span> Loading your email workflows…</div>';
    var input=panel.querySelector('#workflow-emails'),notice=panel.querySelector('#email-workflow-notice');
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
        return '<article class="lead email-workflow-row"><div class="leadtop"><label class="email-workflow-recipient"><input type="checkbox" data-email-workflow-select="'+esc(row.id)+'"'+(selected.has(row.id)&&row.can_activate?' checked':'')+(!row.can_activate||busy?' disabled':'')+'><b>'+esc(row.email)+'</b></label><span class="tag">'+esc(names[row.status]||row.status)+'</span></div><p class="meta">Added by you'+(row.follow_up_due_at?' · Follow-up '+esc(new Date(row.follow_up_due_at).toLocaleString()):'')+'</p>'+
          '<div class="email-workflow-row-actions"><button type="button" class="ghost" data-email-workflow-activate="'+esc(row.id)+'"'+(!row.can_activate||busy?' disabled':'')+'>'+esc(row.status==='active'?'Workflow active':row.status==='queued'||row.status==='running'?'Activating…':'Activate workflow')+'</button><button type="button" class="ghost" data-email-workflow-preview="'+esc(row.id)+'">View email &amp; résumé</button></div>'+
          (row.reason?'<p class="meta">'+esc(row.reason)+'</p>':'')+'<div class="email-workflow-preview" data-email-preview-for="'+esc(row.id)+'"></div></article>';
      }).join(''):'<div class="workspace-empty"><h2>Your email workflows will appear here</h2><p>Add one or more email addresses above. Each address gets its own workflow and selection box.</p></div>';
      updateSelection();
    }
    function load(){
      clearTimeout(timer);
      return requestJSON(API+'/api/chat/email-workflows',{cache:'no-store'}).then(function(data){
        if(!current())return;
        contacts=data.contacts||[];contacts.forEach(function(row){if(!seen.has(row.id)&&row.can_activate)selected.add(row.id);seen.add(row.id);});
        renderRows();
        if(contacts.some(function(row){return ['queued','running'].includes(row.status);}))timer=setTimeout(load,2500);
      }).catch(function(error){if(!current())return;message(error.message,true);panel.querySelector('#email-workflow-list').innerHTML='<div class="workspace-empty"><p>Sign in to your connected workspace to see your email workflows.</p><a href="/login">Sign in</a></div>';});
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
