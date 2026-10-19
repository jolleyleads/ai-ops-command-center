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
    campaign.disabled=!access.signed_in;
    document.getElementById('prepare').disabled=!access.signed_in;
    document.getElementById('prepare').title=access.signed_in?'Prepare verified drafts without sending':'Sign in to save leads and prepare drafts';
    if(access.signed_in){note.textContent='Workspace connected. Choose Research only or Research & email.';}
    else{mode.value='research';note.innerHTML='Research is available. <a href="/login">Sign in for saved leads and email campaigns</a>.';}
    return access;
  }).catch(function(){note.textContent='Research is available. Workspace access could not be checked; refresh before sending.';return window.workspaceAccess;});
})();

window.renderResearchProgress=function(state){
  var bubble=window.activeResearchBubble;
  if(!bubble)return;
  var p=state.progress||{}, rows=p.candidates||[];
  var html='<b>Research in progress</b><p>'+esc(String(p.stage||state.status).replace(/_/g,' '))+'</p>';
  html+='<p class="meta">Requested '+esc(p.requested||'')+' · Found '+esc(p.discovered||0)+' candidates. Verification is still in progress.</p>';
  rows.forEach(function(row){html+='<div class="lead"><b>'+esc(row.company)+'</b><p>Candidate · Not yet verified</p><a href="'+esc(row.source_url)+'" target="_blank" rel="noopener noreferrer">Research source</a></div>';});
  html+='<button class="ghost" id="cancel-research">Cancel research</button>';
  bubble.innerHTML=html;
  document.getElementById('cancel-research').onclick=function(){
    requestJSON(API+'/api/research/jobs/'+encodeURIComponent(state.job_id)+'/cancel',{method:'POST',headers:{'X-CSRF-Token':window.researchRequestToken||''}}).then(function(){bubble.textContent='Research cancelled.';}).catch(function(e){bubble.textContent=e.message;});
  };
};
