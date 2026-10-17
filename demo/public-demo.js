/* Isolated sample data inside the existing AutoMake AI customer interface. */
(function () {
  'use strict';
  var leads = [
    {id:1,company:'Example Coastal HVAC',location:'Sample territory',business_type:'HVAC',score:87,status:'drafted',has_sent_message:false,replied_at:null,contact_name:'',has_email:false,campaign_ids:['sample-campaign']},
    {id:2,company:'Example Harbor Electric',location:'Sample territory',business_type:'Electrical contractor',score:76,status:'review',has_sent_message:false,replied_at:null,contact_name:'',has_email:false,campaign_ids:['sample-campaign']}
  ];
  var campaigns = [{id:'sample-campaign',name:'Sample prospect research',territory:'Sample territory',status:'completed',lead_ids:[1,2],research_results:2,verified:0,qualified:0,drafted:1,sent:0,progress:{},needs_attention:false}];
  function sampleDetail(id) {
    var lead=leads.find(function(item){return item.id===id;})||leads[0];
    return Object.assign({},lead,{ok:true,score_description:'Illustrative sample score, not a measured research result.',score_checks:[],reasons:[],contact:{name:'',role:'',email:'',email_label:'Sample contact pending',type:'Illustrative example',phone:''},sources:[],subject:'Sample outreach draft',body:'Hello Example Business team,\nCould a short demonstration help you explore how to manage prospect research and follow-ups?\n\nIllustrative draft only. Not sent.',timeline:[],bookings:[],follow_up_count:0});
  }
  // Replace the existing UI data adapter before dashboard.js loads. The visitor
  // demo never calls a customer-data, research, campaign or provider endpoint.
  window.requestJSON=function(url,options) {
    var path=new URL(url,window.location.origin).pathname;
    if(options&&options.method&&options.method!=='GET')return Promise.reject(new Error('This is a sample demo. Book a Demo to see a live walkthrough.'));
    if(path==='/api/chat/dashboard')return Promise.resolve({ok:true,is_demo:true,leads:leads,campaigns:campaigns,lead_limit:2,campaign_limit:1});
    if(/^\/api\/chat\/dashboard\/leads\/\d+$/.test(path))return Promise.resolve(sampleDetail(Number(path.split('/').pop())));
    if(path==='/api/chat/dashboard/appointments')return Promise.resolve({ok:true,is_demo:true,appointments:[]});
    if(path==='/api/chat/dashboard/settings')return Promise.resolve({ok:true,is_demo:true,sender_name:'Sample workspace',sender_company:'AutoMake AI',sender_email:'Not connected in demo',google_configured:false,first_followup_days:3,maximum_followups:2});
    return Promise.reject(new Error('Explore the sample workspace or book a personal demonstration.'));
  };
  function sampleRun() {
    var input=document.getElementById('prompt'), prompt=input.value.trim();
    if(!prompt)return;
    input.value='';
    window.add('user','<b>You</b><br>'+window.esc(prompt));
    window.add('ai','<b>AutoMake AI · Sample demo</b><p>Here is an illustrative view of prospect research. These businesses and scores are examples; no live research or emails were started.</p>'+leads.map(function(lead){return '<div class="lead"><div class="leadtop"><b>'+window.esc(lead.company)+'</b><span class="tag">Sample score '+lead.score+'/100</span></div><p class="meta">'+window.esc(lead.business_type)+' · Sample record</p></div>';}).join('')+'<p>Open <b>My Leads</b> or <b>My Campaigns</b> to explore the sample workspace.</p><p><a href="/book-demo">Book a Demo</a> for a live walkthrough tailored to your business.</p>');
  }
  window.run=sampleRun;
  window.prepareCampaign=sampleRun;
  document.getElementById('prepare').onclick=sampleRun;
  var health=document.getElementById('health');health.textContent='● Sample demo';
  document.getElementById('prompt').placeholder='Try a sample request…';
  document.querySelectorAll('[data-view]').forEach(function(button){button.addEventListener('click',function(){setTimeout(function(){var panel=document.getElementById('workspace-panel');if(panel&&!panel.hidden){var note=document.createElement('p');note.className='small';note.textContent='Sample demo · Illustrative records only. No emails or appointments are created.';panel.prepend(note);}},0);});});
})();
