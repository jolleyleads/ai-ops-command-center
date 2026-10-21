from pathlib import Path
from scripts.smart_search_smoke import validate_frontend


def test_restored_customer_interface_matches_deployment_smoke():
    html=Path('demo/index.html').read_text()
    script=Path('demo/dashboard.js').read_text()
    assert validate_frontend(html,script)==[]
    assert validate_frontend(html.replace('id="prompt"','id="broken"'),script)
    assert validate_frontend(html.replace('/api/research/jobs','/missing'),script)
    assert validate_frontend('<title>AutoMake AI</title>')


def test_count_parser_ignores_unrelated_numbers_and_preserves_large_requests():
    import re,json,subprocess,shutil
    import pytest
    if not shutil.which('node'):pytest.skip('JavaScript runtime unavailable')
    html=Path('demo/index.html').read_text()
    function=re.search(r'function requestedLeadCount\(q\)\{.*?\n\}',html,re.S).group(0)
    script=function+'\nconsole.log(JSON.stringify(["Find 10 HVAC businesses","Find 20 companies","Find 100 companies","Find businesses open 24 hours","Find companies along Route 17","Find 1 HVAC business"].map(requestedLeadCount)));'
    result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==[10,20,100,10,10,1]


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
