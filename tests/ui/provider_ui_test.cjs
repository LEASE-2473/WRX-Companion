process.chdir(require('node:path').resolve(__dirname, '../..'));
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/settings/app.js', 'utf8');
const html = fs.readFileSync('app/static/index.html', 'utf8');
const providerPanel = html.slice(html.indexOf('<dialog id="providerPanel"'), html.indexOf('<dialog id="llmDebugDialog"'));
assert.deepEqual([...providerPanel.matchAll(/<strong>([^<]+)<\/strong>/g)].map(m=>m[1]), ['LLM','TTS','STT','Embedding','Rerank']);
assert(!providerPanel.includes('llmPurpose'));
for (const kind of ['embedding','rerank']) {
  for (const suffix of ['Profile','BaseUrl','ApiKey','Model','ModelsUrl','FetchedModels']) assert(providerPanel.includes(`id="${kind}${suffix}"`));
}
const start = source.indexOf('async function persistProviderDraft(');
const end = source.indexOf('\n// 供应商操作与页面初始化', start);
async function check(action, suffix, kind = 'llm') {
  const calls = [];
  const context = {
    settings: {provider_profiles: {}},
    providerPayload: () => ({id: 'new-profile', base_url: 'https://api.deepseek.com', api_key: 'fake-key', model: ''}),
    providerState: () => {}, renderProviderProfiles: () => {}, renderFetchedModels: () => {},
    selectedProvider: () => { throw Error('Must use saved draft ID'); },
    providerApi: async (url, options) => {
      calls.push({url, options});
      if (options.method === 'PUT') return {llm_profiles: [{id: 'new-profile'}]};
      return {ok: true, models: ['deepseek-chat'], stages: {}};
    }
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  await vm.runInContext(action, context);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].options.method, 'PUT');
  assert.equal(JSON.parse(calls[0].options.body).api_key, 'fake-key');
  assert.equal(calls[1].url, `/api/provider-profiles/${kind}/new-profile/${suffix}`);
}
(async () => {
  await check('fetchModels()', 'models');
  await check('testLlmConnection()', 'connection');
  await check("testProvider('llm')", 'test');
  for (const kind of ['embedding','rerank']) {
    await check(`fetchModels('${kind}')`, 'models', kind);
    await check(`testProvider('${kind}')`, 'test', kind);
  }
  for (const kind of ['embedding','rerank']) {
    const draft = vm.createContext({selectedProvider: () => ({id:kind + '-own'}), $: id => {
      assert(id.startsWith(kind));
      return {value: id.endsWith('ApiKey') ? 'own-secret' : id.endsWith('BaseUrl') ? 'https://own.test/v1' : id.endsWith('ModelsUrl') ? 'https://own.test/models' : 'own-model'};
    }});
    vm.runInContext(source.slice(source.indexOf('function providerPayload('), source.indexOf('async function persistProviderDraft(')), draft);
    const payload = vm.runInContext(`providerPayload('${kind}')`, draft);
    assert.equal(payload.id, kind + '-own'); assert.equal(payload.api_key, 'own-secret');
    assert.equal(payload.models_url, 'https://own.test/models');
    assert(!('purpose' in payload)); assert(!('provider_type' in payload));
  }
  const controls = {
    memoryEmbeddingProfile: {value:'embed-1'}, memoryRerankProfile: {value:'rank-1'},
    memoryVectorEnabled: {checked:true}, memoryRerankEnabled: {checked:true}, memoryVectorProviderState: {}
  };
  let saved;
  const binding = { $: id => controls[id], providerApi: async (url, options) => {
    assert.equal(url, '/api/role-memory/settings');
    if (!options) return {diary_hour:9, presets:{diary:{prompt:'保留提示词'}}, vector:{threshold:0.42, max_results:7}};
    saved = JSON.parse(options.body); return saved;
  }};
  vm.createContext(binding);
  vm.runInContext(source.slice(source.indexOf('async function saveMemoryVectorModels('), source.indexOf('function memoryVectorAction(')), binding);
  await vm.runInContext('saveMemoryVectorModels()', binding);
  assert.equal(saved.embedding_profile_id, 'embed-1');
  assert.equal(saved.rerank_profile_id, 'rank-1');
  assert.equal(saved.vector.enabled, true);
  assert.equal(saved.vector.rerank_enabled, true);
  assert.equal(saved.vector.threshold, 0.42);
  assert.equal(saved.diary_hour, 9);
  assert.equal(saved.presets.diary.prompt, '保留提示词');
  controls.memoryEmbeddingProfile.value = '';
  await assert.rejects(vm.runInContext('saveMemoryVectorModels()', binding), /请先选择向量化模型/);
  controls.memoryEmbeddingProfile.value = 'embed-1'; controls.memoryRerankProfile.value = '';
  await assert.rejects(vm.runInContext('saveMemoryVectorModels()', binding), /Rerank 模型/);
  console.log('Provider UI draft persistence checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
