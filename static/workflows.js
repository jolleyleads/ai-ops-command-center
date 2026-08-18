const state={id:null,nodes:[],edges:[],selected:null,connectFrom:null,connectBranch:null};
const canvas=document.getElementById('canvas'), nodeLayer=document.getElementById('nodeLayer'), edgeLayer=document.getElementById('edgeLayer'), inspector=document.getElementById('inspector');

const schemas={
trigger:[['label','Label','text'],['event_name','Event name','text']],
schedule:[['label','Label','text'],['cron','Cron / schedule','text']],
webhook:[['label','Label','text'],['path','Webhook path','text']],
condition:[['label','Label','text'],['field','Field path','text'],['operator','Operator','select',['equals','not_equals','contains','not_contains','exists','gt','lt']],['value','Compare value','text']],
ai:[['label','Label','text'],['model','Model (blank = env/default)','text'],['instructions','Instructions','textarea'],['prompt','Prompt','textarea'],['output_key','Output key','text']],
http:[['label','Label','text'],['method','Method','select',['GET','POST','PUT','PATCH','DELETE']],['url','URL','text'],['output_key','Output key','text']],
email:[['label','Label','text'],['to','To','text'],['subject','Subject','text'],['body','Body','textarea'],['output_key','Output key','text']],
sms:[['label','Label','text'],['to','To phone','text'],['body','Message','textarea'],['output_key','Output key','text']],
crm:[['label','Label','text'],['action','Action','text']],
delay:[['label','Label','text'],['seconds','Seconds (max 10)','number']],
action:[['label','Label','text'],['description','Description','textarea']]
};

function uid(prefix){return prefix+'-'+Math.random().toString(36).slice(2,9)}

function nodeName(type){
  return ({
    trigger:'Trigger',
    schedule:'Schedule',
    webhook:'Webhook',
    condition:'IF / ELSE',
    ai:'OpenAI',
    http:'HTTP Request',
    email:'Gmail',
    sms:'SMS',
    crm:'CRM',
    delay:'Delay',
    action:'Action'
  })[type]||type
}

function defaults(type){
  return ({
    condition:{field:'status',operator:'equals',value:'qualified'},
    ai:{prompt:'{{input}}',instructions:'',output_key:'ai_output'},
    http:{method:'GET',url:'',output_key:'http_response'},
    email:{to:'{{email}}',subject:'Automation follow-up',body:'{{ai_output}}',output_key:'gmail_result'},
    sms:{to:'{{phone}}',body:'{{ai_output}}',output_key:'sms_result'},
    delay:{seconds:1},
    crm:{action:'upsert_contact'},
    action:{description:''}
  })[type]||{}
}

function addNode(type){
  const n={
    id:uid(type),
    type,
    label:nodeName(type),
    x:80+(state.nodes.length%3)*220,
    y:80+Math.floor(state.nodes.length/3)*150,
    config:defaults(type)
  };
  state.nodes.push(n);
  state.selected=n.id;
  render();
  renderInspector();
}

function selectNode(id){
  if(state.connectFrom&&state.connectFrom!==id){
    finishConnect(id);
    return;
  }
  state.selected=id;
  render();
  renderInspector();
}

function startConnect(id,branch=null){
  state.connectFrom=id;
  state.connectBranch=branch;
  state.selected=id;
  render();
  renderInspector();
  setOutput('Connection mode: tap the destination node.');
}

function finishConnect(target){
  if(state.edges.some(e=>e.source===state.connectFrom&&e.target===target&&e.branch===state.connectBranch)){
    cancelConnect();
    return;
  }

  state.edges.push({
    id:uid('edge'),
    source:state.connectFrom,
    target,
    branch:state.connectBranch||undefined
  });

  cancelConnect();
  render();
  setOutput('Connection added.');
}

function cancelConnect(){
  state.connectFrom=null;
  state.connectBranch=null;
}

function deleteNode(id){
  state.nodes=state.nodes.filter(n=>n.id!==id);
  state.edges=state.edges.filter(e=>e.source!==id&&e.target!==id);

  if(state.selected===id)state.selected=null;

  cancelConnect();
  render();
  renderInspector();
}

function deleteEdge(id){
  state.edges=state.edges.filter(e=>e.id!==id);
  render();
}

function render(){
  nodeLayer.innerHTML='';

  state.nodes.forEach(n=>{
    const el=document.createElement('div');

    el.className=
      'workflow-node node-'+n.type+
      (state.selected===n.id?' selected':'')+
      (state.connectFrom===n.id?' connecting':'');

    el.dataset.id=n.id;
    el.style.left=n.x+'px';
    el.style.top=n.y+'px';

    const branchPorts=
      n.type==='condition'
      ?'<div class="branch-row"><button class="port true-port">TRUE</button><button class="port false-port">FALSE</button></div>'
      :'<button class="connect-btn">Connect</button>';

    el.innerHTML=
      '<div class="node-top">'+
      '<span class="node-icon">'+icon(n.type)+'</span>'+
      '<div><b>'+escapeHtml(n.label||nodeName(n.type))+'</b><small>'+nodeName(n.type)+'</small></div>'+
      '<button class="node-delete">×</button>'+
      '</div>'+
      branchPorts;

    el.onclick=e=>{
      if(e.target.closest('button'))return;
      selectNode(n.id);
    };

    el.querySelector('.node-delete').onclick=e=>{
      e.stopPropagation();
      delete