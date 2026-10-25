from pathlib import Path
from scripts.smart_search_smoke import validate_frontend


def test_selection_preview_reads_only_and_activity_uses_observed_stages():
    import subprocess
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('demo/access.js','utf8');
const activity=source.slice(source.indexOf('window.renderWorkingActivity='),source.indexOf('window.renderResearchProgress='));
const helpers=source.slice(source.indexOf('window.emailSendStatus='),source.indexOf('window.outreachControl='));
let reads=0,writes=0;
const context={window:{},esc:s=>String(s||'').replaceAll('<','&lt;'),Date,JSON,Number,Set,Promise,
document:{addEventListener:()=>{},querySelectorAll:()=>[]},API:'',sessionStorage:{getItem:()=>null},
requestJSON:(path,opts)=>{reads++;assert(path.startsWith('/api/chat/workflows/preview?selection='));assert.equal(opts.method,undefined);return Promise.resolve({preview:{subject:'Approved',body:'Hey team 👋\nRésumé 🙂 <script>',attachment:'resume.docx'}});},
workspaceMutation:()=>{writes++;throw Error('Preview must not send');}};
vm.runInNewContext(activity+helpers+source.slice(source.indexOf('// Selected-business workflows:')),context);
const w=context.window,ref={kind:'lead',lead_id:42};
assert(w.selectionControl(ref).includes('View email &amp; résumé'));
(async()=>{
 await w.previewSelection(ref);
 const html=w.selectionControl(ref);
 assert(html.includes('👋')&&html.includes('🙂')&&html.includes('&lt;script>'));
 assert.equal(reads,1);assert.equal(writes,0);
 const working=w.renderWorkingActivity({status:'running',progress:{activity:[{stage:'hunter_contact_lookup',at:'2026-10-25T09:00:00Z'}]}});
 assert(working.includes('Working…')&&working.includes('Finding contacts with Hunter')&&working.includes('aria-current="step"'));
 assert(!working.includes('Email sent'));
 const held=w.renderWorkingActivity({status:'completed',result:{workflow:{state:'held',reason:'Reconnect Google'}}});
 assert(held.includes('Needs attention')&&held.includes('Reconnect Google')&&!held.includes('Email sent'));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_restored_customer_interface_matches_deployment_smoke():
    html=Path('demo/index.html').read_text()
    script=Path('demo/dashboard.js').read_text()
    assert validate_frontend(html,script)==[]
    assert validate_frontend(html.replace('id="prompt"','id="broken"'),script)
    assert validate_frontend(html.replace('/api/research/jobs','/missing'),script)
    assert validate_frontend('<title>AutoMake AI</title>')


def test_verified_contact_is_not_reported_as_failed_when_business_qualification_is_held():
    import re, subprocess
    source=Path('demo/access.js').read_text()
    function=re.search(r'window.contactProgressMessage=function\(row\)\{.*?\n\};',source,re.S).group(0)
    script='const window={};'+function+'''
const assert=require('assert');
const held={error:'CONTACT_OR_QUALIFICATION_REQUIRES_REVIEW',qualification_status:'Not qualified'};
assert.equal(window.contactProgressMessage({...held,contact_check:{mailbox_verified:true,named_contact:true}}),'Decision-maker email verified. Business qualification still needs evidence.');
assert.equal(window.contactProgressMessage({...held,contact_check:{mailbox_verified:true,named_contact:false}}),'Company email verified. Business qualification still needs evidence.');
assert(window.contactProgressMessage({...held,contact_check:{mailbox_verified:false}}).includes('needs review'));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_count_parser_ignores_unrelated_numbers_and_preserves_large_requests():
    import re,json,subprocess,shutil
    import pytest
    if not shutil.which('node'):pytest.skip('JavaScript runtime unavailable')
    html=Path('demo/index.html').read_text()
    function=re.search(r'function requestedLeadCount\(q\)\{.*?\n\}',html,re.S).group(0)
    script=function+'\nconsole.log(JSON.stringify(["Find 10 HVAC businesses","Find 20 companies","Find 100 companies","Find businesses open 24 hours","Find companies along Route 17","Find 1 HVAC business"].map(requestedLeadCount)));'
    result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==[10,20,100,10,10,1]
    script=function+'\nconsole.log(JSON.stringify(["Give me five electrical businesses only with their emails available","Please show me up to TWO electrical companies"].map(requestedLeadCount)));'
    result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==[5,2]


def test_saved_email_mode_cannot_override_signed_out_access():
    import re,json,subprocess,shutil
    import pytest
    if not shutil.which('node'):pytest.skip('JavaScript runtime unavailable')
    function=re.search(r'function applyPreferences\(\)\{[^\n]+\}',Path('demo/dashboard.js').read_text()).group(0)
    script="const elements={territory:{},'task-mode':{}};const document={getElementById:id=>elements[id]};const window={};const preference=(key,fallback)=>key==='mode'?'campaign':fallback;"+function+";const result=[];for(const access of [undefined,{sending_available:false},{sending_available:true}]){window.workspaceAccess=access;applyPreferences();result.push(elements['task-mode'].value);}console.log(JSON.stringify(result));"
    result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==['research','research','campaign']


def test_research_prepares_without_sending_and_workflow_buttons_only_activate_on_click():
    import subprocess
    source=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('demo/index.html','utf8');
const campaign=html.slice(html.indexOf('function campaignSearch(q){'),html.indexOf('\nfunction run(){'));
assert(!campaign.includes('/launch')&&!campaign.includes('send_emails:true'));
assert(campaign.includes('/api/chat/campaigns/prepare'));
const access=fs.readFileSync('demo/access.js','utf8');
const code=access.slice(access.indexOf('window.outreachPending=new Set();'));
let sends=0;
const context={window:{},esc:String,document:{addEventListener:()=>{}},workspaceMutation:()=>{sends++;throw Error('Render sent email');},Set,Number};
vm.runInNewContext(code,context);
for(const state of [{state:'held',can_activate:false,label:'Held',reason:'Missing evidence'},
 {state:'ready',can_activate:true,label:'Activate outreach',reason:'Ready'},
 {state:'active',can_activate:false,label:'Outreach active',reason:'Sent',initial:'Send confirmed',followups:'Scheduled',booking:'Waiting for an agreed meeting time'}]){
 const rendered=context.window.outreachControl(7,state);
 assert.equal(rendered.includes(' disabled'),!state.can_activate);
 if(state.state==='active')assert(rendered.includes('Waiting for an agreed meeting time')&&!rendered.includes('Booking confirmed'));
}
context.window.outreachPending.add(7);
assert(context.window.outreachControl(7,{can_activate:true,label:'Activate outreach'}).includes(' disabled'));
assert.equal(sends,0);
'''
    result=subprocess.run(['node','-e',source],check=True,capture_output=True,text=True)
    assert result.returncode==0


def test_candidate_selection_renders_before_drafts_and_reload_never_creates_authorization():
    import subprocess
    script=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('demo/access.js','utf8');
const code=source.slice(source.indexOf('window.emailSendStatus='),source.indexOf('window.outreachControl='))+source.slice(source.indexOf('// Selected-business workflows:'));
let posts=0,reads=0,saved='{}',last;
const context={API:'',window:{workspaceAccess:{signed_in:true}},esc:String,document:{addEventListener:()=>{},querySelectorAll:()=>[],getElementById:()=>({value:'Offer'})},
 sessionStorage:{getItem:()=>saved,setItem:(key,value)=>{saved=value;}},setTimeout:()=>{},Date,JSON,Promise,
 workspaceMutation:(url,opts)=>{posts++;last=JSON.parse(opts.body);return Promise.resolve({job_id:'one',status:'queued',poll_url:'/api/demo/campaigns/jobs/one'});},
 requestJSON:()=>{reads++;return Promise.resolve({status:'completed',result:{workflow:{state:'held',reason:'Contact pending'}}});}};
vm.runInNewContext(code,context);
const ref={kind:'research',job_id:'research-one',key:'source-one'};
const html=context.window.selectionControl(ref);
assert(html.includes('Activate workflow')&&!html.includes(' disabled'));
assert(html.includes('Sends your message and résumé')&&html.includes('No extra confirmation'));
assert.equal(posts,0);assert.equal(reads,0);
(async()=>{
 const pending=context.window.activateSelection(ref);context.window.activateSelection(ref);await pending;await Promise.resolve();
 assert.equal(posts,1);assert.equal(last.activate,true);assert.equal(last.selection.key,'source-one');assert(!last.contact_email);
 const before=reads;vm.runInNewContext(code,context);await Promise.resolve();
 assert.equal(posts,1);assert(reads>before);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_send_status_requires_receipt_and_never_offers_retry_for_confirmed_send():
    import subprocess
    script=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('demo/access.js','utf8');
const context={window:{},esc:String,Set,Number,document:{addEventListener:()=>{}},sessionStorage:{getItem:()=>null}};
vm.runInNewContext(source.slice(source.indexOf('window.outreachPending=new Set();')),context);
const w=context.window,ref={kind:'lead',lead_id:42},id=w.selectionId(ref);
function render(status,workflow){w.selectedWorkflows[id]={job:{activation_policy:'selected-email-v2'},state:{status,result:{workflow}}};return w.selectionControl(ref);}
let html=render('completed',{state:'held',reason:'Mailbox not verified'});
assert(html.includes('<b>Not sent</b>'));assert(html.includes('Mailbox not verified'));assert(html.includes('Try again'));assert(!html.includes('Retry workflow'));
html=render('completed',{state:'active',outreach:{initial:'Send confirmed',followups:'Scheduled',booking:'Waiting for an agreed meeting time'}});
assert(html.includes('<b>Sent</b>'));assert(html.includes(' disabled'));assert(!html.includes('Retry'));
// A stale held/stopped job snapshot cannot conceal its confirmed send receipt.
for(const state of ['held','active']){
 html=render('cancelled',{state,outreach:{send_status:'sent',state:'stopped',initial:'Send confirmed'}});
 assert(html.includes('<b>Sent</b>'));assert(!html.includes('>Not sent<'));assert(!html.includes('Retry'));
}
html=render('completed',{state:'held',outreach:{state:'review',send_status:'unknown'}});
assert(html.includes('<b>Checking status</b>'));assert(!html.includes('<b>Not sent</b>'));assert(html.includes(' disabled'));
html=render('running',{});assert(html.includes('Sending…'));assert(!html.includes('<b>Sent</b>'));
html=render('completed',{state:'active'});assert(!html.includes('<b>Sent</b>'));
html=w.outreachControl(42,{state:'stopped',label:'Old stopped label',initial:'Send confirmed',reason:'Follow-ups stopped'});
assert(html.includes('<b>Sent</b>'));assert(html.includes('Follow-ups stopped'));
html=w.outreachControl(42,{state:'held',label:'Outreach held',reason:'Missing evidence'});
assert(html.includes('<b>Not sent</b>'));assert(html.includes('Missing evidence'));
function visible(html){return html.replace(/<details[\s\S]*?<\/details>/g,'');}
html=render('completed',{state:'active',outreach:{send_status:'sent',reason:'Initial email accepted by Gmail. Delivery is not confirmed.'}});
assert(visible(html).includes('<b>Sent</b>'));assert(!visible(html).includes('Gmail'));assert(!visible(html).includes('confirmed'));
html=render('completed',{state:'held',reason:'INTENT_SIGNAL_UNPROVEN',reason_codes:['INTENT_SIGNAL_UNPROVEN']});
assert(!visible(html).includes('INTENT_SIGNAL_UNPROVEN'));assert(html.includes('<summary>Details</summary>'));
assert(!visible(w.renderProspectQuality({missing:['INTENT_SIGNAL_UNPROVEN']})).includes('Business fit'));
context.API='';context.document.querySelectorAll=()=>[];let reads=0;
context.requestJSON=()=>{reads++;return Promise.resolve(reads===1?{status:'completed',result:{workflow:{state:'held',lead_id:42,reason:'Old hold'}}}:{outreach:{send_status:'sent',initial:'Send confirmed',reason:'Initial email accepted by Gmail.'}});};
w.selectedWorkflows[id]={ref,job:{poll_url:'/api/demo/campaigns/jobs/one'}};
(async()=>{
 w.observeSelectedWorkflow(id);await Promise.resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(reads,2);html=w.selectionControl(ref);assert(html.includes('<b>Sent</b>'));assert(!html.includes('Old hold'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_bulk_email_button_submits_displayed_emails_once_and_restores_without_sending():
    import subprocess
    script=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let writes=0,reads=0,body,saved='{}';
const context={API:'',window:{workspaceAccess:{signed_in:true}},esc:String,Set,Number,URL,document:{addEventListener:()=>{},querySelectorAll:()=>[],getElementById:()=>({value:'Scheduling automation'})},
 sessionStorage:{getItem:()=>saved,setItem:(key,value)=>{saved=value;}},setTimeout:()=>{},
 workspaceMutation:(path,options)=>{writes++;assert.equal(path,'/api/chat/workflows/activate-bulk');body=JSON.parse(options.body);return Promise.resolve({job_id:'batch-one',poll_url:'/api/demo/campaigns/jobs/batch-one',status:'queued'});},
 requestJSON:()=>{reads++;return Promise.resolve({status:'running',progress:{bulk_items:[]}});}};
const source=fs.readFileSync('demo/access.js','utf8'),code=source.slice(source.indexOf('window.outreachPending=new Set();'));
vm.runInNewContext(code,context);let w=context.window;
const a={company:'A',website:'https://a.example/',selection:{kind:'research',job_id:'r',key:'a'},contacts:[{email:'owner@a.example'}]},
 b={company:'B',website:'https://b.example/',selection:{kind:'research',job_id:'r',key:'b'},contact_email:'owner@b.example'},
 no={company:'No email',selection:{kind:'research',job_id:'r',key:'c'}};
let html=w.bulkActivationControl([a,b,no,a]);assert(html.includes('Activate all with email (2)'));assert(!html.includes(' disabled'));
assert(w.businessEmail(a).includes('owner@a.example'));assert.equal(w.businessEmailValue({...a,contacts:[{email:'support@directory.example'}]}),'');assert.equal(w.businessEmailValue({...a,website:'https://threebestrated.com/hvac-in-norfolk-va',contacts:[{email:'support@threebestrated.com'}]}),'');assert.equal(writes,0);
assert(w.bulkActivationControl(Array.from({length:21},(_,i)=>({selection:{kind:'lead',lead_id:i+1},website:'https://example.com/',contact_email:'owner'+i+'@example.com'}))).includes('Filter to 20 or fewer'));
const group=Object.keys(w.bulkTargets)[0];
(async()=>{
 const promise=w.activateAllWithEmail(group);w.activateAllWithEmail(group);await promise;await Promise.resolve();
 assert.equal(writes,1);assert.equal(body.selections.length,2);assert.equal(body.activate,true);assert(!body.selections.some(x=>x.key==='c'));
 const before=reads;vm.runInNewContext(code,context);await Promise.resolve();assert.equal(writes,1);assert(reads>before);
 assert(context.window.bulkActivationControl([no]).includes(' disabled'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_completed_research_renders_final_email_records_instead_of_early_progress_projection():
    import subprocess
    script=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('demo/access.js','utf8');
const bubble={innerHTML:''},rows=[{company:'Source-backed business',contacts:[{email:'owner@source.example'}]}];
const context={API:'',window:{activeResearchBubble:bubble,bulkActivationControl:items=>'BATCH '+items.map(x=>(x.contacts||[]).map(c=>c.email).join('')).join(''),renderBusinessCards:()=>{throw Error('Stale progress hid final contacts');}},esc:String,resultCard:r=>r.contacts[0].email,
 document:{getElementById:()=>({value:'Norfolk'})},sessionStorage:{setItem:()=>{},removeItem:()=>{}},
 requestJSON:()=>Promise.resolve({status:'completed',result:{results:rows},progress:{businesses:[{company:'Source-backed business',contact_status:'Pending'}]}})};
vm.runInNewContext(source.slice(source.indexOf('window.renderSavedJobResult='),source.indexOf('(function restoreResearch(){')),context);
(async()=>{
 const result=await context.window.followResearchJob({job_id:'source',poll_url:'/api/research/jobs/source'},'research');
 assert.equal(result.business_progress.length,0);assert.equal(result.results[0].contacts[0].email,'owner@source.example');
 context.window.renderSavedJobResult(result);assert(bubble.innerHTML.includes('BATCH owner@source.example'));assert(bubble.innerHTML.includes('owner@source.example'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    # Progress painting itself is covered elsewhere; this test isolates the
    # completed-job handoff and final business/email rendering.
    script=script.replace("activeResearchBubble:bubble,bulkActivationControl", "activeResearchBubble:bubble,renderResearchProgress:()=>{},bulkActivationControl")
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_search_failure_distinguishes_empty_and_partial_results_and_connection_errors():
    import re, subprocess
    html=Path('demo/index.html').read_text()
    functions=html[html.index('function requestJSON('):html.index('function health(')]
    script="const assert=require('node:assert/strict');const esc=String,API='';const setTimeout=(fn,ms)=>{if(ms<25000)queueMicrotask(fn);return 0;};const clearTimeout=()=>{};"+functions+"""
(async()=>{
  const empty={innerHTML:'Finding businesses…',querySelector:()=>null};
  showResearchFailure(empty,new Error('Failed'));
  assert(empty.innerHTML.includes('No results were displayed.'));
  assert(!empty.innerHTML.includes('Finding businesses'));
  assert(!empty.innerHTML.includes('shown above'));
  const partial={innerHTML:'<div class="lead">Saved company</div>',querySelector:()=>({})};
  showResearchFailure(partial,new Error('Failed'));
  assert(partial.innerHTML.includes('Saved company'));
  assert(partial.innerHTML.includes('Results found so far are shown above.'));
  let calls=0;
  global.fetch=async()=>{calls++;throw new TypeError('Load failed');};
  await assert.rejects(requestJSON('/api/chat/campaigns/prepare',{method:'POST'}),/Couldn’t connect to AutoMake AI/);
  assert.equal(calls,1); // Never automatically repeat a mutation after an ambiguous response.
  const options={method:'POST',headers:{'Idempotency-Key':'same-search-key'},body:'same search'};
  calls=0;const keys=[];
  global.fetch=async(url,settings)=>{calls++;keys.push(settings.headers['Idempotency-Key']);if(calls===1)throw new TypeError('Load failed');return {ok:true,text:async()=>JSON.stringify({job_id:'same-job'})};};
  assert.equal((await requestJSON('/api/chat/campaigns/prepare',options)).job_id,'same-job');
  assert.equal(calls,2);assert.deepEqual(keys,['same-search-key','same-search-key']);
  calls=0;global.fetch=async()=>{calls++;throw new TypeError('Load failed');};
  await assert.rejects(requestJSON('/api/research/jobs',options),/Couldn’t connect/);
  assert.equal(calls,4);
  calls=0;await assert.rejects(requestJSON('/api/chat/leads/1/activate-outreach',options),/Couldn’t connect/);
  assert.equal(calls,1);
  calls=0;global.fetch=async()=>{calls++;return {ok:true,text:async()=>{throw new TypeError('Load failed');}};};
  await assert.rejects(requestJSON('/api/chat/campaign-settings'),/Couldn’t connect/);assert.equal(calls,4);
  global.fetch=async()=>({ok:true,text:async()=>'<html>Application loading</html>'});
  await assert.rejects(requestJSON('/api/health'),/still loading/);
  calls=0;global.fetch=async()=>{calls++;return {ok:false,status:401,text:async()=>' {"error":"Sign in required"}'};};
  await assert.rejects(requestJSON('/api/chat/campaign-settings'),/Sign in required/);assert.equal(calls,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
