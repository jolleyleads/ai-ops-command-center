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
