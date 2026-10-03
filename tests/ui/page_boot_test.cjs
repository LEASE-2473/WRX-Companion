// 按真实首页顺序执行所有脚本，捕获拆文件后的初始化依赖和重复函数。
const fs = require('node:fs'), path = require('node:path');
const vm = require('node:vm'), assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'app/static/index.html'), 'utf8');
const urls = [...html.matchAll(/<script src="(\/static\/[^"?]+)(?:\?[^\"]*)?"/g)].map(m => m[1]);
const elements = new Map(), listeners = new Map(), definitions = new Map();
function element(tag = 'div') {
  const e = {tagName: tag.toUpperCase(), children: [], options: [], dataset: {}, style: {},
    value: '', textContent: '', innerHTML: '', open: false, disabled: false,
    classList: {add(){}, remove(){}, toggle(){}, contains(){return false;}},
    append(...xs){this.children.push(...xs);}, appendChild(x){this.append(x);return x;},
    prepend(...xs){this.children.unshift(...xs);}, replaceChildren(...xs){this.children = xs;},
    add(x){this.options.push(x);}, addEventListener(){}, removeEventListener(){},
    setAttribute(){}, getAttribute(){return null;}, removeAttribute(){},
    showModal(){this.open = true;}, close(){this.open = false;},
    querySelector(){return element();}, querySelectorAll(){return [];},
    focus(){}, remove(){}, getBoundingClientRect(){return {width: 320};},
    setPointerCapture(){}, hasPointerCapture(){return false;}, releasePointerCapture(){}};
  e.parentElement = e;
  return e;
}
const document = {body: element('body'),
  getElementById(id){if(!elements.has(id)) elements.set(id, element()); return elements.get(id);},
  createElement: element, createTextNode: text => ({textContent: text}),
  querySelectorAll(){return [];}, querySelector(){return element();}, addEventListener(){}};
const localStorage = {getItem(){return null;},setItem(){},removeItem(){}};
const window = {addEventListener(name, cb){listeners.set(name, cb);},openai: null};
const context = vm.createContext({window,document,localStorage,console,URL,URLSearchParams,
  crypto: require('node:crypto').webcrypto, navigator: {}, location: {protocol:'http:',host:'localhost'},
  setInterval(){return 1;},setTimeout(){return 1;},clearInterval(){},clearTimeout(){},
  Option: function(text,value){this.text=text;this.value=value;},
  fetch(){throw Error('Page boot must not call a real API');}});
for (const url of urls) {
  const source = fs.readFileSync(path.join(root, 'app', url.slice(1)), 'utf8');
  for (const m of source.matchAll(/^(?:async )?function (\w+)\(/gm)) {
    assert(!definitions.has(m[1]), `Duplicate global function ${m[1]}: ${definitions.get(m[1])} and ${url}`);
    definitions.set(m[1],url);
  }
  vm.runInContext(source, context, {filename:url});
}
assert.equal(typeof elements.get('talk').onpointerdown, 'function');
assert.equal(typeof elements.get('playPause').onclick, 'function');
assert.equal(typeof elements.get('sendText').onclick, 'function');
assert.equal(typeof window.onkeydown, 'function');
assert(listeners.has('DOMContentLoaded'));
assert.equal(definitions.get('persistConversation'), '/static/chat/companion.js');
assert.equal(definitions.get('sendTypedText'), '/static/chat/chat-ui.js');
assert.equal(definitions.get('start'), '/static/voice/voice-ui.js');
console.log(`Page boot passed: ${urls.length} scripts; unique global functions; voice/chat controls wired.`);
