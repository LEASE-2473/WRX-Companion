const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'emotion-lab.fragment.html'),'utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function boot(saved){
  const elements={},listeners={};let written;
  function el(tag){return {tag,children:[],value:'',checked:false,style:{},classList:{add(){}},validity:{valid:true},selectedOptions:[{textContent:'测试情境'}],append(...xs){this.children.push(...xs);for(const x of xs)if(x.id)elements['#'+x.id]=x;},replaceChildren(){this.children=[];},setAttribute(k,v){this[k]=v;},getBoundingClientRect(){return {width:320};}};}
  const root=el();root.querySelector=id=>elements[id]??=el();
  const window={addEventListener(name,cb){listeners[name]=cb;},openai:{widgetState:saved,setWidgetState(value){written=value;return Promise.resolve();}}};
  const context=vm.createContext({window,document:{getElementById(){return root;},createElement:el,createElementNS(_namespace,tag){return el(tag);}},ResizeObserver:class{observe(){}},console});
  vm.runInContext(source,context);
  return {api:window.emotionLabTest,e:elements,saved:()=>written,listeners};
}
let {api,e,saved}=boot();
assert.equal(api.getDefinitions().length,36);
assert.ok(api.getGroups().every(g=>g[1].length===6));
assert.equal(e['#el-radars'].children.length,6);
assert.ok(e['#el-radars'].children.every(s=>s.children[1].children.filter(n=>n.tag==='polygon').length===6));
assert.ok(e['#el-radars'].children.every(s=>s.children[1].children.filter(n=>n.tag==='circle').length===12));
let s=api.getState();s.auto=false;s.char['担忧'].v=100;s.char['担忧'].b=10;s.char['担忧'].h=6;s.char['担忧'].d=0;s.char['担忧'].r=0;
const userBefore=JSON.stringify(Object.fromEntries(Object.entries(s.user).map(([n,x])=>[n,x.v])));
api.step(6);assert.ok(Math.abs(s.char['担忧'].v-(10+90*Math.exp(-3)))<1e-6);
assert.equal(JSON.stringify(Object.fromEntries(Object.entries(s.user).map(([n,x])=>[n,x.v]))),userBefore);
assert.equal(api.applyQuestionnaire(2,[0,1,2,3,4,2]),true);
assert.equal(s.user['担忧'].v,0);assert.equal(s.user['焦虑'].v,25);assert.equal(s.user['压力'].v,100);
const untouched=s.user['爱意'].v;const beforeBad=JSON.stringify(s.user);
assert.equal(api.applyQuestionnaire(2,[0,1,2,3,4]),false);assert.equal(api.applyQuestionnaire(2,[0,1,2,3,4,5]),false);
assert.equal(JSON.stringify(s.user),beforeBad);assert.equal(s.user['爱意'].v,untouched);
for(let i=0;i<6;i++)e['#el-answer-'+i].value='';
e['#el-questionapply'].onclick();assert.match(e['#el-questionstatus'].textContent,/请先完成六题/);
for(let i=0;i<6;i++)e['#el-answer-'+i].value='4';
e['#el-questionapply'].onclick();assert.ok(api.getGroups()[0][1].every(([n])=>s.user[n].v===100));
e['#el-reset'].onclick();s=api.getState();const previousUser=JSON.stringify(s.user);api.applyScene('low');assert.equal(JSON.stringify(s.user),previousUser);
e['#el-sampleuser'].checked=true;
for(const scene of ['reunion','low','conflict','honeymoon','fight','busy','play','reassure','lonely','jealous']){
  e['#el-reset'].onclick();api.applyScene(scene);api.step(24);
  for(const a of ['char','user'])for(const x of Object.values(api.getState()[a]))assert.ok(Number.isFinite(x.v)&&x.v>=0&&x.v<=100);
}
e['#el-reset'].onclick();api.applyScene('conflict');s=api.getState();const comfort=api.motives().find(m=>m.name==='安抚 / 关心');assert.ok(comfort.minus>40);s.rw=0;assert.ok(api.motives().find(m=>m.name==='安抚 / 关心').score>comfort.score);
e['#el-reset'].onclick();api.applyScene('busy');api.step(1);assert.equal(api.getState().actions,0);
api.applyQuestionnaire(1,[1,2,3,4,0,1]);const state=saved();assert.ok(Buffer.byteLength(JSON.stringify(state),'utf8')<16384);
const restored=boot(state);assert.equal(restored.api.getState().user['喜悦'].v,25);assert.equal(restored.api.getState().t,api.getState().t);
assert.ok(!/\b(fetch|XMLHttpRequest|WebSocket)\s*\(/.test(source));
console.log('PASS: 36 variables; six groups/radars; 95% recovery; fixed User scores; questionnaire validation/mapping/isolation; 10 scenes; conflict/quiet; state restore; <16 KiB; offline only.');
