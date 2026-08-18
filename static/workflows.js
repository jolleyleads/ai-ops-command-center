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

  })[type]||type;

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

  })[type]||{};

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

      deleteNode(n.id);

    };

    const cb=el.querySelector('.connect-btn');

    if(cb)cb.onclick=e=>{

      e.stopPropagation();

      startConnect(n.id);

    };

    const tp=el.querySelector('.true-port');

    if(tp)tp.onclick=e=>{

      e.stopPropagation();

      startConnect(n.id,'true');

    };

    const fp=el.querySelector('.false-port');

    if(fp)fp.onclick=e=>{

      e.stopPropagation();

      startConnect(n.id,'false');

    };

    enableDrag(el,n);

    nodeLayer.appendChild(el);

  });

  requestAnimationFrame(renderEdges);

}

function icon(t){

  return ({

    trigger:'⚡',

    schedule:'🕒',

    webhook:'◉',

    condition:'◇',

    ai:'✦',

    http:'↗',

    email:'✉',

    sms:'▣',

    crm:'◎',

    delay:'⏳',

    action:'▶'

  })[t]||'•';

}

function escapeHtml(s){

  return String(s??'').replace(/[&<>'"]/g,c=>({

    '&':'&amp;',

    '<':'&lt;',

    '>':'&gt;',

    "'":'&#39;',

    '"':'&quot;'

  }[c]));

}

function enableDrag(el,n){

  let dragging=false,sx=0,sy=0,nx=0,ny=0;

  el.addEventListener('pointerdown',e=>{

    if(e.target.closest('button'))return;

    dragging=true;

    sx=e.clientX;

    sy=e.clientY;

    nx=n.x;

    ny=n.y;

    el.setPointerCapture(e.pointerId);

  });

  el.addEventListener('pointermove',e=>{

    if(!dragging)return;

    n.x=Math.max(5,nx+e.clientX-sx);

    n.y=Math.max(5,ny+e.clientY-sy);

    el.style.left=n.x+'px';

    el.style.top=n.y+'px';

    renderEdges();

  });

  el.addEventListener('pointerup',()=>{

    dragging=false;

  });

}

function renderEdges(){

  const rect=canvas.getBoundingClientRect();

  edgeLayer.setAttribute('width',canvas.clientWidth);

  edgeLayer.setAttribute('height',canvas.clientHeight);

  edgeLayer.innerHTML='';

  state.edges.forEach(e=>{

    const s=nodeLayer.querySelector('[data-id="'+CSS.escape(e.source)+'"]');

    const t=nodeLayer.querySelector('[data-id="'+CSS.escape(e.target)+'"]');

    if(!s||!t)return;

    const sr=s.getBoundingClientRect();

    const tr=t.getBoundingClientRect();

    const x1=sr.right-rect.left;

    const y1=sr.top+sr.height/2-rect.top;

    const x2=tr.left-rect.left;

    const y2=tr.top+tr.height/2-rect.top;

    const dx=Math.max(70,Math.abs(x2-x1)*.5);

    const path=document.createElementNS('http://www.w3.org/2000/svg','path');

    path.setAttribute(

      'd',

      `M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`

    );

    path.setAttribute('class','edge '+(e.branch||''));

    path.onclick=()=>{

      if(confirm('Delete this connection?')){

        deleteEdge(e.id);

      }

    };

    edgeLayer.appendChild(path);

    if(e.branch){

      const text=document.createElementNS('http://www.w3.org/2000/svg','text');

      text.setAttribute('x',(x1+x2)/2);

      text.setAttribute('y',(y1+y2)/2-8);

      text.setAttribute('class','edge-label '+e.branch);

      text.textContent=e.branch.toUpperCase();

      edgeLayer.appendChild(text);

    }

  });

}

function renderInspector(){

  const n=state.nodes.find(x=>x.id===state.selected);

  if(!n){

    inspector.innerHTML=

      '<div class="inspector-empty">'+

      '<h3>Node Inspector</h3>'+

      '<p>Tap any node on the canvas.</p>'+

      '</div>';

    return;

  }

  const rows=(schemas[n.type]||[]).map(([key,label,type,opts])=>{

    const value=key==='label'?n.label:(n.config[key]??'');

    if(type==='textarea'){

      return `<label>${label}<textarea data-key="${key}">${escapeHtml(value)}</textarea></label>`;

    }

    if(type==='select'){

      return `<label>${label}<select data-key="${key}">${

        opts.map(o=>`<option ${String(value)===o?'selected':''}>${o}</option>`).join('')

      }</select></label>`;

    }

    return `<label>${label}<input type="${type}" data-key="${key}" value="${escapeHtml(value)}"></label>`;

  }).join('');

  inspector.innerHTML=

    `<div class="inspector-head">`+

    `<div><h3>${icon(n.type)} ${escapeHtml(n.label)}</h3><small>${nodeName(n.type)}</small></div>`+

    `<button id="closeInspector">×</button>`+

    `</div>`+

    `<div class="inspector-form">${rows}</div>`+

    `<div class="template-help">Use <code>{{field}}</code> to insert run data or previous-node outputs. Example: <code>{{ai_output}}</code>.</div>`;

  inspector.querySelectorAll('[data-key]').forEach(input=>{

    input.oninput=()=>{

      const key=input.dataset.key;

      if(key==='label'){

        n.label=input.value;

      }else{

        n.config[key]=input.type==='number'

          ?Number(input.value)

          :input.value;

      }

      render();

    };

  });

  document.getElementById('closeInspector').onclick=()=>{

    state.selected=null;

    render();

    renderInspector();

  };

}

async function loadList(){

  const r=await fetch('/api/workflows');

  const list=await r.json();

  const box=document.getElementById('workflowList');

  box.innerHTML='';

  list.forEach(w=>{

    const b=document.createElement('button');

    b.className='saved-workflow';

    b.textContent=w.name;

    b.onclick=()=>{

      state.id=w.id;

      state.nodes=w.definition.nodes||[];

      state.edges=(w.definition.edges||[]).map(e=>({

        ...e,

        id:e.id||uid('edge')

      }));

      document.getElementById('workflowName').value=w.name;

      state.selected=null;

      cancelConnect();

      render();

      renderInspector();

    };

    box.appendChild(b);

  });

}

async function loadStatus(){

  try{

    const r=await fetch('/api/credentials/status');

    const s=await r.json();

    const box=document.getElementById('connectorBadges');

    box.innerHTML=['openai','gmail','twilio'].map(k=>

      `<span class="badge ${s[k].configured?'ok':'off'}">`+

      `${k==='twilio'?'SMS':k.toUpperCase()} `+

      `${s[k].configured?'●':'○'}`+

      `</span>`

    ).join('');

  }catch(e){}

}

function setOutput(t){

  document.getElementById('runOutput').textContent=t;

}

document.querySelectorAll('.node-add').forEach(b=>{

  b.onclick=()=>addNode(b.dataset.type);

});

async function save(){

  const payload={

    name:document.getElementById('workflowName').value,

    definition:{

      nodes:state.nodes,

      edges:state.edges

    },

    status:'active'

  };

  let url='/api/workflows';

  let method='POST';

  if(state.id){

    url+='/'+state.id;

    method='PUT';

  }

  const r=await fetch(url,{

    method,

    headers:{

      'Content-Type':'application/json'

    },

    body:JSON.stringify(payload)

  });

  const d=await r.json();

  if(d.id){

    state.id=d.id;

  }

  await loadList();

  setOutput('Workflow saved.');

}

async function run(){

  if(!state.id){

    setOutput('Save the workflow first.');

    return;

  }

  let input={};

  try{

    input=JSON.parse(

      document.getElementById('runInput').value||'{}'

    );

  }catch(e){

    setOutput('Run input must be valid JSON.');

    return;

  }

  setOutput('Running workflow...');

  const r=await fetch(

    '/api/workflows/'+state.id+'/run',

    {

      method:'POST',

      headers:{

        'Content-Type':'application/json'

      },

      body:JSON.stringify(input)

    }

  );

  const d=await r.json();

  setOutput(JSON.stringify(d,null,2));

  loadStatus();

}

document.getElementById('saveWorkflow').onclick=save;

document.getElementById('runWorkflow').onclick=run;

document.getElementById('runWorkflowBottom').onclick=run;

window.addEventListener('resize',renderEdges);

loadList();

loadStatus();

render();

renderInspector();

document.getElementById("aiBuild").onclick = async function () {

  state.id = null;

  const start = {

    id: uid("trigger"),

    type: "trigger",

    label: "Start",

    x: 60,

    y: 60,

    config: {

      event_name: "new_contractor_lead"

    }

  };

  const ai = {

    id: uid("ai"),

    type: "ai",

    label: "AI Process",

    x: 280,

    y: 240,

    config: {

      model: "",

      instructions:

        "You qualify electrical contractor leads needing permit, licensing, or master electrician support.",

      prompt: `Analyze this contractor lead:

{{lead}}

Explain whether they are qualified, what electrical permit or licensing support they need, and the next action.

End with exactly:

QUALIFIED: TRUE

or

QUALIFIED: FALSE`,

      output_key: "ai_output"

    }

  };

  const qualified = {

    id: uid("condition"),

    type: "condition",

    label: "Qualified?",

    x: 500,

    y: 420,

    config: {

      field: "ai_output",

      operator: "contains",

      value: "QUALIFIED: TRUE"

    }

  };

  const qualifiedAction = {

    id: uid("action"),

    type: "action",

    label: "Qualified Lead Action",

    x: 740,

    y: 330,

    config: {

      description:

        "Follow up with qualified contractor lead"

    }

  };

  const requestInfo = {

    id: uid("action"),

    type: "action",

    label: "Request Missing Information",

    x: 740,

    y: 520,

    config: {

      description:

        "Request the missing permit, licensing, master electrician, contact, or project information before re-running qualification."

    }

  };

  state.nodes = [

    start,

    ai,

    qualified,

    qualifiedAction,

    requestInfo

  ];

  state.edges = [

    {

      id: uid("edge"),

      source: start.id,

      target: ai.id

    },

    {

      id: uid("edge"),

      source: ai.id,

      target: qualified.id

    },

    {

      id: uid("edge"),

      source: qualified.id,

      target: qualifiedAction.id,

      branch: "true"

    },

    {

      id: uid("edge"),

      source: qualified.id,

      target: requestInfo.id,

      branch: "false"

    }

  ];

  document.getElementById("workflowName").value =

    "Electrical Contractor Lead Qualification";

  render();

  renderInspector();

  await save();

};