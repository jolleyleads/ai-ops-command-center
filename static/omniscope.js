(function(){
  'use strict';
  const $=id=>document.getElementById(id), messages=$('messages'), mode=$('mode');
  let history=[], busy=false;
  async function api(path,body){
    const options={credentials:'same-origin',cache:'no-store'};
    if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content};options.body=JSON.stringify(body);}
    const response=await fetch(path,options), data=await response.json();
    if(!response.ok||data.ok===false)throw new Error(data.error||'This request could not be completed.');
    return data;
  }
  function message(label,text,kind){
    const empty=$('empty');if(empty)empty.remove();
    const box=document.createElement('article');box.className='message '+(kind||'');
    const heading=document.createElement('small');heading.textContent=label;box.appendChild(heading);
    const content=document.createElement('div');content.textContent=text;box.appendChild(content);messages.appendChild(box);return box;
  }
  function text(parent,tag,value){const element=document.createElement(tag);element.textContent=value||'';parent.appendChild(element);return element;}
  function safeLink(parent,label,url){try{const parsed=new URL(url);if(parsed.protocol!=='https:')return;const a=text(parent,'a',label);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';}catch(e){}}
  function displayPlaces(data){
    const box=message('Google Maps',data.places.length?'Business and place results':'No places matched this search.');
    data.places.forEach(place=>{const card=document.createElement('div');card.className='place';text(card,'b',(place.displayName||{}).text||'Place');text(card,'p',place.formattedAddress);if(place.location)text(card,'p','Coordinates: '+place.location.latitude+', '+place.location.longitude);safeLink(card,'View on Google Maps',place.googleMapsUri);(place.attributions||[]).forEach(a=>safeLink(card,a.provider||'Attribution',a.providerUri));box.appendChild(card);});
    text(box,'p','Coordinates describe places, not a person’s live location.');
  }
  function displayContacts(data){
    const box=message('Your authorized Google contacts',data.contacts.length?'Contacts from the account connected to this workspace':'No contacts returned.');
    data.contacts.forEach(person=>{const card=document.createElement('div');card.className='contact';text(card,'b',((person.names||[])[0]||{}).displayName||'Contact');(person.emailAddresses||[]).forEach(e=>text(card,'p',e.value));(person.phoneNumbers||[]).forEach(p=>text(card,'p',p.value));box.appendChild(card);});
    if(data.more_available)text(box,'p','Showing the first 25 contacts.');
  }
  function switchMode(){
    const people=mode.value==='people',places=mode.value==='places',research=mode.value==='research';
    $('prompt').hidden=people;$('prompt-label').hidden=people;$('prompt').required=!people;$('prompt').maxLength=(places||research)?512:12000;
    $('prompt').placeholder=places?'Find HVAC companies in Chesapeake, Virginia…':'Ask OmniScope…';
    $('submit').textContent=people?'Load my contacts':places?'Search places ↗':research?'Research live web ↗':'Ask OmniScope ↗';
    $('tool-description').textContent=people?'Read contacts from your separately authorized Google account. This is not a public people-search database.':places?'Search current business listings and place locations with Google Places.':research?'Research public web sources with explicit evidence links.':'Ask a question. OmniScope separates evidence, assumptions, and uncertainty.';
    $('input-hint').textContent=people?'Requires Google People authorization.':places?'Searches use your workspace’s Google Places connection.':research?'Searches use configured Exa or web providers; results may be incomplete.':'Chat uses OpenAI. Live tools run only when selected.';
    $('notice').textContent='';$('notice').className='';
  }
  $('new-chat').addEventListener('click',()=>{if(busy)return;history=[];messages.replaceChildren();const empty=document.createElement('div');empty.id='empty';empty.textContent='What would you like to understand?';messages.appendChild(empty);$('notice').textContent='';});
  mode.addEventListener('change',switchMode);
  $('omniscope-form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    const selected=mode.value,value=$('prompt').value.trim();if(selected!=='people'&&!value)return;
    busy=true;$('submit').disabled=true;mode.disabled=true;$('new-chat').disabled=true;$('notice').className='';$('notice').textContent='Working…';
    try{
      if(selected==='chat'){
        const data=await api('/api/chat/omniscope/chat',{message:value,history:history});
        message('You',value,'user');message('OmniScope',data.answer);history=history.concat([{role:'user',content:value},{role:'assistant',content:data.answer}]).slice(-16);$('prompt').value='';
      }else if(selected==='research'){
        const data=await api('/api/chat/omniscope/research',{query:value});
        message('You',value,'user');const card=message('OmniScope live research',data.answer);
        (data.sources||[]).forEach((source,i)=>safeLink(card,'['+(i+1)+'] '+source.title,source.url));
        $('prompt').value='';
      }else if(selected==='places')displayPlaces(await api('/api/chat/omniscope/places',{query:value}));
      else displayContacts(await api('/api/chat/omniscope/people',{}));
      $('notice').textContent='';
    }catch(error){$('notice').className='error';$('notice').textContent=error.message;}
    finally{busy=false;$('submit').disabled=false;mode.disabled=false;$('new-chat').disabled=false;}
  });
  api('/api/chat/omniscope/status').then(data=>{
    $('connections').replaceChildren();[['openai','OpenAI'],['places','Google Places'],['people','Google Contacts']].forEach(([key,label])=>{const badge=text($('connections'),'span',label+': '+(data.providers[key].configured?'Configured':'Setup needed'));badge.className='badge';});
  }).catch(error=>{$('connections').textContent=error.message;});
})();
