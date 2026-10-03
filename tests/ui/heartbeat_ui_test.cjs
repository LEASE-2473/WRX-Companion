process.chdir(require('node:path').resolve(__dirname, '../..'));
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync('app/static/chat/companion.js', 'utf8');
function element(tag) { return {tag, children: [], textContent: '', append(...nodes) {this.children.push(...nodes);}, replaceChildren() {this.children = [];}}; }
const logs = element('div');
const raw = '<img src=x onerror=alert(1)>';
const rows = [{started_at: '2026-10-01T00:00:00Z', status: 'complete', usage: '{"input_tokens":10}',
  execution: JSON.stringify({action: 'NO_ACTION', latency_seconds: 1.25}), reply:raw}];
const ctx = vm.createContext({document: {createElement: element}, $: () => logs, activeConversationId: 'test', companionApi: async () => rows, usageLabel: () => 'Input 10'});
vm.runInContext(src.slice(src.indexOf('async function loadHeartbeatLogs()'), src.indexOf('function reportTo(')), ctx);
(async () => {
  await ctx.loadHeartbeatLogs();
  const card = logs.children[0];
  assert.equal(card.tag, 'details');
  assert.match(card.children[0].textContent, /保持安静.*Input 10.*1.25 秒/);
  assert.equal(card.children.find(n => n.tag === 'pre' && n.textContent === raw).textContent, raw);
  assert.ok(!card.children.some(n => n.tag === 'img'));
  rows.push({started_at: '2026-10-01', status: 'error', error: '失败'});
  await ctx.loadHeartbeatLogs();
  assert.equal(logs.children.length, 2);
  assert.ok(logs.children[1].children.some(n => n.textContent === '此记录无数据'));
  console.log('心跳展开、用量耗时、旧记录与模型文本安全渲染通过');
})();
