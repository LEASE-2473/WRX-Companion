const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = new Map();
function element() {
  return {
    hidden: false, disabled: false, textContent: '', src: '', open: false,
    append() {}, prepend() {},
    showModal() { this.open = true; }, close() { this.open = false; },
    removeAttribute(name) { delete this[name]; },
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, element());
      return elements.get(selector);
    }
  };
}
const document = element();
document.body = element();
const created = [];
document.createElement = () => { const node = element(); created.push(node); return node; };
const calls = [];
let attached = false;
const context = vm.createContext({
  document, activeConversationId: 'conversation', encodeURIComponent,
  setInterval() {},
  fetch: async (url) => {
    calls.push(url);
    if (url.includes('/start/')) attached = true;
    if (url.includes('/close/')) attached = false;
    const tool = {attached, connected: false, service_running: attached};
    return {ok: true, json: async () => url.includes('/status/') ? {tools: [tool]} : tool};
  }
});
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  vm.runInContext(fs.readFileSync('app/static/role-tools.js', 'utf8'), context);
  await flush();
  assert(!calls.some(url => url.includes('/start/')));
  created[1].onclick();
  await flush();
  assert(!calls.some(url => url.includes('/start/')));
  await elements.get('#startToyTool').onclick();
  assert.equal(calls.filter(url => url.includes('/start/')).length, 1);
  assert.equal(elements.get('#stopToyTool').hidden, false);
  assert.equal(elements.get('#toyToolFrame').hidden, false);
  elements.get('#closeRoleTools').onclick();
  assert.equal(attached, true);
  elements.get('#openToyTool').onclick();
  assert.equal(calls.filter(url => url.includes('/start/')).length, 1);
  await elements.get('#stopToyTool').onclick();
  assert.equal(attached, false);
  assert.equal(elements.get('#toyToolFrame').hidden, true);
  assert.equal(elements.get('#toyToolFrame').src, undefined);
  assert.equal(elements.get('#startToyTool').hidden, false);
  assert.equal(elements.get('#stopToyTool').hidden, true);
  await elements.get('#startToyTool').onclick();
  assert.equal(calls.filter(url => url.includes('/start/')).length, 2);
  console.log('role tools UI lifecycle passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
