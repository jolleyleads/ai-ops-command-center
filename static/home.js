(function(){
  'use strict';
  var form=document.getElementById('demo-form');
  try{form.elements.timezone.value=Intl.DateTimeFormat().resolvedOptions().timeZone||'America/New_York';}catch(ignore){}
  form.addEventListener('submit',function(event){
    event.preventDefault();
    if(!form.reportValidity())return;
    var field=function(name){return form.elements[name].value.trim();};
    var body=['Hi Matthew,','',"I'd like a demo of AutoMake AI.",'',
      'Name: '+field('name'),'Business: '+field('company'),'Email: '+field('email'),
      'Preferred time: '+(field('time')||'Please suggest a time'),'Time zone: '+field('timezone'),'',
      'What I would like help with:',field('goal')||'Please walk me through the workflow.','',
      'Please confirm an available time by email.'].join('\n');
    var url='mailto:info@automakeai.live?subject='+encodeURIComponent('AutoMake AI demo request — '+field('company'))+'&body='+encodeURIComponent(body);
    var status=document.getElementById('demo-status');
    status.textContent='Your email draft is ready. Send it from your email app to request your demo. If it did not open, use the link below.';
    var fallback=document.createElement('a');fallback.href=url;fallback.textContent='Open my demo request email';
    status.appendChild(document.createElement('br'));status.appendChild(fallback);
    window.location.href=url;
  });
})();
