"""Exercise browser retry behavior with its real polling function and fake I/O."""
import subprocess
from pathlib import Path


def test_stopped_research_allows_explicit_retry_without_releasing_campaign_keys():
    script=r'''
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('demo/access.js','utf8');
const code=source.slice(source.indexOf('window.followResearchJob=function'),source.indexOf('(function restoreResearch'));
(async()=>{
 for(const status of ['failed','cancelled'])for(const kind of ['research','campaign','drafts']){
  const store=new Map([['automake-research-request','existing'],['automake-campaign-request','protected'],['automake-draft-request','protected']]);
  const context={window:{renderResearchProgress:()=>{}},document:{getElementById:()=>({value:'Norfolk'})},
   sessionStorage:{setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
   API:'',requestJSON:async()=>({status,error:'Stopped',progress:{}}),Date,Promise,setTimeout};
  vm.runInNewContext(code,context);
  await assert.rejects(context.window.followResearchJob({job_id:'test',poll_url:'/api/research/jobs/test'},kind),/Stopped/);
  assert.equal(store.has('automake-active-job'),false);
  assert.equal(store.has('automake-research-request'),kind!=='research');
  assert.equal(store.get('automake-campaign-request'),'protected');
  assert.equal(store.get('automake-draft-request'),'protected');
 }
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
