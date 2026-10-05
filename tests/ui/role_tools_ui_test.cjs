process.chdir(require('node:path').resolve(__dirname, '../..'));
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const selectors = new Map(), created = [];
function element(tag='') { return {tag,children:[],hidden:false,open:false,textContent:'',
  append(...nodes){this.children.push(...nodes)},prepend(node){this.children.unshift(node)},
  replaceChildren(){this.children=[]},setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]},
  showModal(){this.open=true},close(){this.open=false},
  querySelector(s){if(!selectors.has(s))selectors.set(s,element());return selectors.get(s)}
}; }
const document = element();document.body=element();document.createElement=tag=>{const node=element(tag);created.push(node);return node};
let enabled=false,running=false;const calls=[];
const fetch=async(url,options={})=>{
 calls.push([url,options.method]);
 if(url.includes('/demo/enable'))enabled=true;
 if(url.includes('/demo/start'))running=true;
 if(url.includes('/demo/stop'))running=false;
 if(url.includes('/demo/disable')){enabled=false;running=false;}
 return {ok:true,json:async()=>url.includes('/skills')?{skills:[{name:'diary-write',description:'diary',enabled:true,injection:'always'}]}:{extensions:[{id:'demo',name:'独立应用',icon:'🧩',description:'说明',enabled,running,has_panel:true}]}};
};
const context=vm.createContext({document,fetch,encodeURIComponent,Promise,JSON,setInterval(){}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function button(label){return selectors.get('#extensionCards').children.flatMap(card=>card.children.flatMap(n=>n.children)).find(n=>n.textContent===label);}
(async()=>{
 vm.runInContext(fs.readFileSync('app/static/tools/role-tools.js','utf8'),context);
 assert.equal(calls.length,0);
 created[1].onclick();await flush();
 selectors.get('#skillTab').onclick();
 assert.equal(selectors.get('#extensionPageTitle').textContent,'Skill');
 assert(selectors.get('#extensionPage').hidden);
 assert.equal(selectors.get('#skillTab')['aria-selected'],'true');
 selectors.get('#extensionTab').onclick();
 assert.equal(selectors.get('#extensionPageTitle').textContent,'扩展');
 assert(selectors.get('#skillPage').hidden);
 assert(!calls.some(([url])=>url.includes('/start')));
 await button('启用').onclick();assert(enabled);assert(!running);
 await button('启动应用').onclick();assert(running);
 button('打开面板').onclick();assert.equal(selectors.get('#toyToolFrame').src,'/apps/demo/');
 selectors.get('#closeRoleTools').onclick();assert(running);
 await button('关闭应用').onclick();assert(!running);assert(selectors.get('#toyToolFrame').hidden);assert.equal(selectors.get('#toyToolFrame').src,undefined);
 await button('停用').onclick();assert(!enabled);
 assert(!button('打开面板'));
 console.log('extension UI discovery, enable, lifecycle and panel passed');
})().catch(error=>{console.error(error);process.exitCode=1});
