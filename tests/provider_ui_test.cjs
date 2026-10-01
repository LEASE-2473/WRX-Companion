const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/app.js', 'utf8');
const start = source.indexOf('async function persistProviderDraft(');
const end = source.indexOf('\nasync function start()', start);
async function check(action, suffix) {
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
  assert.equal(calls[1].url, `/api/provider-profiles/llm/new-profile/${suffix}`);
}
(async () => {
  await check('fetchModels()', 'models');
  await check('testLlmConnection()', 'connection');
  await check("testProvider('llm')", 'test');
  console.log('Provider UI draft persistence checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
