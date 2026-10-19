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
