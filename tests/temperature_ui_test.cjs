const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/app.js', 'utf8');
const controls = {
  promptTemperature: {value: '0', valueAsNumber: 0, validity: {valid: true}, reportValidity() {return this.validity.valid;}},
  promptPresetName: {value: '测试'}
};
const preset = {id: 'test', name: '测试', generation_parameters: {top_p: 0.9, temperature: 1.234}};
const calls = [];
const context = {selectedPromptPreset: () => preset, $: id => controls[id], settings: {}, setPromptState: () => {},
  promptApi: async (url, options) => {calls.push(JSON.parse(options.body)); return {};}, activatePromptPreset: async () => {}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('async function saveCurrentPromptPreset()'), source.indexOf('async function newPromptPreset()')), context);
(async () => {
  await context.saveCurrentPromptPreset();
  assert.equal(calls[0].generation_parameters.temperature, 0);
  assert.equal(calls[0].generation_parameters.top_p, 0.9);
  controls.promptTemperature.value = '2'; controls.promptTemperature.valueAsNumber = 2;
  await context.saveCurrentPromptPreset();
  assert.equal(calls[1].generation_parameters.temperature, 2);
  controls.promptTemperature.validity.valid = false;
  await context.saveCurrentPromptPreset();
  assert.equal(calls.length, 2);
  controls.promptTemperature.validity.valid = true; controls.promptTemperature.value = '';
  await context.saveCurrentPromptPreset();
  assert.equal('temperature' in calls[2].generation_parameters, false);
  assert.equal(calls[2].generation_parameters.top_p, 0.9);
  console.log('温度零值、上界、非法输入拦截、留空删除与其他参数保留检查通过');
})().catch(error => {console.error(error); process.exitCode = 1;});
