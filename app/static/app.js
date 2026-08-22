const $ = id => document.getElementById(id);
const STT_INTEGRITY_MODE = true;
const MICROPHONE_WARM_IDLE_MS = 60000;
let settings;
let messages = [];
let conversations = [];
let activeConversationId = null;
let conversationExpanded = false;
let mediaStream;
let audioContext;
let sttStream;
let processor;
let source;
let chunks = [];
let recording = false;
let stopping = false;
let startPromise = null;
let finishPromise = null;
let activeTalkPointerId = null;
let sttOpeningPromise = null;
let pendingSttFrames = [];
let microphoneReleaseTimer = null;
let key = normalizeHotkey(localStorage.pttKey || 'Space');
let pendingKey = key;
let capturingKey = false;
let currentAudio;
let streamPlayback;
let processing = false;
let lastLlmDebug = null;
let draggedPromptIdentifier = null;
let pendingPromptImport = null;
let promptDirty = false;
let draggedLoreEntryId = null;
let pendingLorebookImport = null;
let lorebookDirty = false;
let lastLorebookTrace = null;

function status(value) { $('status').textContent = value; }
function microphoneIsLive() { return Boolean(mediaStream?.getAudioTracks().some(track => track.readyState === 'live')); }
function releaseMicrophone() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = null; if (mediaStream) mediaStream.getTracks().forEach(track => track.stop()); mediaStream = null; }
function scheduleMicrophoneRelease() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = setTimeout(() => { if (!recording && !startPromise) releaseMicrophone(); }, MICROPHONE_WARM_IDLE_MS); }
async function acquireMicrophone() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = null; if (!microphoneIsLive()) mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true }); return mediaStream; }
async function prewarmMicrophoneIfGranted() { try { if (!navigator.permissions?.query) return; const permission = await navigator.permissions.query({ name: 'microphone' }); if (permission.state !== 'granted' || microphoneIsLive()) return; await acquireMicrophone(); scheduleMicrophoneRelease(); } catch {} }
function formatTime(value) { return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`; }
function normalizeHotkey(value) { const trimmed = String(value || '').trim(); if (/^[a-z]$/i.test(trimmed)) return `Key${trimmed.toUpperCase()}`; if (/^[0-9]$/.test(trimmed)) return `Digit${trimmed}`; return trimmed || 'Space'; }
function formatHotkey(value) { if (value === 'Space') return 'Space'; if (value.startsWith('Key')) return value.slice(3); if (value.startsWith('Digit')) return value.slice(5); return value; }
function setKeyState(message, kind = '') { $('keyState').textContent = message; $('keyState').className = `hint ${kind}`.trim(); }
function setPromptState(message, kind = '') { $('promptState').textContent = message; $('promptState').className = `hint ${kind}`.trim(); }
function setHistoryDepthState(message, kind = '') { $('historyDepthState').textContent = message; $('historyDepthState').className = `hint ${kind}`.trim(); }
function renderDebug(out) { const promptHash = out.debug?.prompt_sha256 || ''; if (promptHash) setPromptState(promptDirty ? `本轮使用已保存 Preset（指纹 ${promptHash}）；页面仍有未保存修改` : `本轮已注入当前 Preset（指纹 ${promptHash}）`, promptDirty ? 'dirty' : 'saved'); const values = [['STT', out.latency?.stt], ['LLM 首 Token', out.latency?.llm_first_token], ['首个可朗读片段', out.latency?.llm_first_tts_segment], ['TTS 首音', out.latency?.tts_first_audio], ['松键到服务端首音', out.latency?.response_to_first_audio], ['松键到实际首播', out.latency?.actual_first_playback], ['后台总耗时', out.latency?.total]]; const timings = values.filter(([, value]) => Number.isFinite(value)).map(([label, value]) => `<div class="latency-item"><span>${label}</span><strong>${value.toFixed(3)}s</strong></div>`).join(''); const metric = out.prompt_tokens; const token = Number.isFinite(metric?.value) ? `<div class="latency-item"><span>最终 Prompt Token</span><strong>${Math.trunc(metric.value)}${metric.source === 'provider' ? '（实际）' : '（估算）'}</strong></div>` : ''; $('latencyInfo').innerHTML = timings + token || '尚无数据'; }
function saveLlmDebug(debug) { lastLlmDebug = debug || null; lastLorebookTrace = debug?.prompt_trace ? { lorebook: debug.prompt_trace.lorebook, entries: debug.prompt_trace.lorebook_activation || [] } : null; $('showLlmDebug').disabled = !lastLlmDebug; if (settings?.lorebooks) renderLorebookEntries(); }
function showLlmDebug() { if (!lastLlmDebug) return; $('llmMessagesDebug').textContent = JSON.stringify(lastLlmDebug.llm_messages || [], null, 2); $('llmRawDebug').textContent = lastLlmDebug.llm_raw ?? ''; $('llmNormalizedDebug').textContent = lastLlmDebug.normalized_reply ?? ''; $('llmTtsDebug').textContent = lastLlmDebug.tts_input ?? ''; $('lorebookActivationDebug').textContent = JSON.stringify(lastLorebookTrace || {}, null, 2); $('llmDebugDialog').showModal(); }

async function load() {
  settings = await fetch('/api/settings').then(r => r.json());
  $('mode').textContent = `V${settings.version} · ${settings.mode}`;
  await loadConversations();
  renderPromptPresets(settings.prompt_presets.active_preset_id);
  renderLorebooks(settings.lorebooks.active_lorebook_id);
  $('historyDepth').value = settings.runtime_settings.history_depth;
  setHistoryDepthState(`当前全局设置：最近 ${settings.runtime_settings.history_depth} 条旧消息；下一轮冻结`, 'saved');
  $('providerInfo').textContent = Object.entries(settings.provider_info).map(([key, value]) => `${key}: ${value || '未配置'}`).join(' · ');
  $('keyInput').value = formatHotkey(key);
  setKeyState(`当前生效：${formatHotkey(key)}（无需重启）`, 'saved');
  renderAllProviderProfiles();
  setPromptState('当前服务端 Preset 已载入，将用于下一轮', 'saved');
}

function messageNode(role, content) { const item = document.createElement('div'); item.className = `message ${role}`; item.textContent = `${role === 'user' ? 'User' : 'Assistant'}: ${content}`; return item; }
function addMessage(role, content) { const item = messageNode(role, content); $('chat').prepend(item); return item; }
function setConversationState(message, kind = '') { $('conversationState').textContent = message; $('conversationState').className = `hint ${kind}`.trim(); }
function renderConversation() {
  $('chat').innerHTML = '';
  const visible = conversationExpanded ? messages : messages.slice(-6);
  [...visible].reverse().forEach(message => $('chat').appendChild(messageNode(message.role, message.content)));
  const rounds = Math.ceil(messages.length / 2);
  $('conversationSummary').textContent = messages.length <= 6 ? `共 ${rounds} 轮（${messages.length} 条），最新在前` : `${conversationExpanded ? '全部' : '最近 3 轮'}，共 ${rounds} 轮（${messages.length} 条），最新在前`;
  $('toggleConversation').hidden = messages.length <= 6;
  $('toggleConversation').textContent = conversationExpanded ? '收起到最近 3 轮' : `展开全部（${messages.length} 条）`;
}
function renderConversationSelect() {
  $('conversationSelect').innerHTML = '';
  conversations.forEach(item => { const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; $('conversationSelect').appendChild(option); });
  $('conversationSelect').value = activeConversationId || '';
}
function setConversationControlsDisabled(disabled) {
  ['conversationSelect', 'newConversation', 'saveConversation', 'clearConversation'].forEach(id => { $(id).disabled = disabled; });
}
function setTextInputControlsDisabled(disabled) {
  $('sendText').disabled = disabled;
  $('textInput').readOnly = disabled;
}
function setConfigurationControlsDisabled(disabled) { $('contextSettingsPanel').inert = disabled; $('promptPanel').inert = disabled; $('lorebookPanel').inert = disabled; $('providerPanel').inert = disabled; }

async function saveHistoryDepth() {
  const raw = Number($('historyDepth').value);
  if (!Number.isFinite(raw) || raw < 0 || !Number.isInteger(raw)) throw new Error('历史消息层数必须是大于等于 0 的整数');
  setHistoryDepthState('正在保存…');
  const response = await fetch('/api/runtime-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ history_depth: raw }) });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '历史层数保存失败');
  settings.runtime_settings = payload;
  $('historyDepth').value = payload.history_depth;
  setHistoryDepthState(`已保存：最近 ${payload.history_depth} 条旧消息；从下一轮生效`, 'saved');
}
async function loadConversations() {
  conversations = await fetch('/api/conversations').then(response => response.json());
  if (!conversations.length) {
    const created = await fetch('/api/conversations', { method: 'POST' }).then(response => response.json());
    conversations = [created];
    let legacy = [];
    try { legacy = JSON.parse(localStorage.voiceMessages || '[]'); } catch { localStorage.removeItem('voiceMessages'); }
    if (legacy.length) { created.messages = legacy; await persistConversation(created.id, legacy, false); localStorage.removeItem('voiceMessages'); }
  }
  const remembered = localStorage.activeConversationId;
  const active = conversations.find(item => item.id === remembered) || conversations[0];
  activeConversationId = active.id;
  messages = [...active.messages];
  localStorage.activeConversationId = activeConversationId;
  renderConversationSelect();
  renderConversation();
  setConversationState(`已读取：${active.name}`, 'saved');
}
async function persistConversation(conversationId = activeConversationId, value = messages, showState = true) {
  if (!conversationId) return null;
  if (showState) setConversationState('正在保存…');
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: value }) });
  if (!response.ok) { if (showState) setConversationState('保存失败', 'dirty'); throw new Error('对话保存失败'); }
  const saved = await response.json();
  const index = conversations.findIndex(item => item.id === saved.id);
  if (index >= 0) conversations[index] = saved; else conversations.push(saved);
  conversations.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  renderConversationSelect();
  if (showState) setConversationState(`已保存：${saved.name}`, 'saved');
  return saved;
}
async function createConversation() {
  const created = await fetch('/api/conversations', { method: 'POST' }).then(response => response.json());
  conversations.unshift(created);
  activeConversationId = created.id;
  messages = [];
  conversationExpanded = false;
  localStorage.activeConversationId = activeConversationId;
  saveLlmDebug(null);
  renderConversationSelect();
  renderConversation();
  setConversationState(`已新建：${created.name}`, 'saved');
}
async function switchConversation(conversationId) {
  if (!conversationId || conversationId === activeConversationId) return;
  await persistConversation(activeConversationId, messages, false);
  const selected = conversations.find(item => item.id === conversationId);
  if (!selected) return;
  activeConversationId = selected.id;
  messages = [...selected.messages];
  conversationExpanded = false;
  localStorage.activeConversationId = activeConversationId;
  saveLlmDebug(null);
  renderConversationSelect();
  renderConversation();
  setConversationState(`已读取：${selected.name}`, 'saved');
}
function promptPresets() { return settings.prompt_presets.presets || []; }
function selectedPromptPreset() { return promptPresets().find(item => item.id === $('promptPreset').value); }
function promptOrder(preset) {
  const definitions = new Map(preset.prompts.map(item => [item.identifier, item]));
  const ordered = preset.prompt_order.map(item => definitions.get(item.identifier)).filter(Boolean);
  preset.prompts.forEach(item => { if (!ordered.includes(item)) ordered.push(item); });
  return ordered;
}
function estimatePromptTokens(text) {
  const value = String(text || '');
  const cjk = (value.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  const nonCjk = value.replace(/[\u3400-\u9fff\uf900-\ufaff]/g, ' ').trim();
  return cjk + Math.ceil(nonCjk.length / 4);
}
function dirtyPrompt(message = '有未保存修改；保存前不会用于下一轮') { promptDirty = true; setPromptState(message, 'dirty'); }
function promptSelect(options, value) { const select = document.createElement('select'); options.forEach(([key, label]) => { const option = document.createElement('option'); option.value = key; option.textContent = label; select.appendChild(option); }); select.value = value; return select; }
function promptField(label, control) { const node = document.createElement('label'); const title = document.createElement('span'); title.textContent = label; node.append(title, control); return node; }
function renderPromptEntries() {
  const preset = selectedPromptPreset();
  const container = $('promptEntries'); container.innerHTML = '';
  if (!preset) { $('promptTokenTotal').textContent = '静态估算 ≈ 0 tokens'; return; }
  $('promptPresetName').value = preset.name;
  let total = 0;
  promptOrder(preset).forEach(entry => {
    const order = preset.prompt_order.find(item => item.identifier === entry.identifier) || { identifier: entry.identifier, enabled: entry.enabled, raw_fields: {} };
    if (!preset.prompt_order.some(item => item.identifier === entry.identifier)) preset.prompt_order.push(order);
    const card = document.createElement('details'); card.className = 'prompt-entry'; card.dataset.identifier = entry.identifier;
    card.ondragover = event => event.preventDefault();
    card.ondrop = event => { event.preventDefault(); if (!draggedPromptIdentifier || draggedPromptIdentifier === entry.identifier) return; const ids = preset.prompt_order.map(item => item.identifier); const from = ids.indexOf(draggedPromptIdentifier); const to = ids.indexOf(entry.identifier); if (from < 0 || to < 0) return; const [moved] = preset.prompt_order.splice(from, 1); preset.prompt_order.splice(to, 0, moved); dirtyPrompt('条目顺序已调整；保存前不会用于下一轮'); renderPromptEntries(); };
    const head = document.createElement('summary'); head.className = 'prompt-entry-head';
    const handle = document.createElement('button'); handle.type = 'button'; handle.className = 'drag-handle'; handle.textContent = '↕ 拖动'; handle.draggable = true; handle.ondragstart = () => { draggedPromptIdentifier = entry.identifier; }; handle.ondragend = () => { draggedPromptIdentifier = null; };
    const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = Boolean(entry.enabled && order.enabled); enabled.onchange = () => { entry.enabled = enabled.checked; order.enabled = enabled.checked; dirtyPrompt(); renderPromptEntries(); };
    const enabledLabel = document.createElement('label'); enabledLabel.className = 'inline-check'; enabledLabel.append(enabled, document.createTextNode('启用'));
    const type = document.createElement('strong'); type.textContent = entry.marker ? (['worldInfoBefore', 'charDefinitions', 'worldInfoAfter', 'userDefinitions', 'chatHistory'].includes(entry.identifier) ? `${entry.name} · Marker` : `${entry.name} · 待映射 Marker`) : `${entry.name} · ${entry.role}`;
    const token = document.createElement('span'); token.className = 'token-badge'; const count = entry.marker ? 0 : estimatePromptTokens(entry.content); total += enabled.checked ? count : 0; token.textContent = entry.marker ? '运行时插槽 · 静态 0' : `≈ ${count} tokens`;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除条目'; remove.onclick = () => { preset.prompts = preset.prompts.filter(item => item.identifier !== entry.identifier); preset.prompt_order = preset.prompt_order.filter(item => item.identifier !== entry.identifier); dirtyPrompt('条目已删除；保存前不会用于下一轮'); renderPromptEntries(); };
    head.append(handle, enabledLabel, type, token, remove); card.appendChild(head);
    const name = document.createElement('input'); name.value = entry.name; name.oninput = () => { entry.name = name.value; dirtyPrompt(); };
    const identifier = document.createElement('input'); identifier.value = entry.identifier; identifier.readOnly = true;
    const grid = document.createElement('div'); grid.className = 'prompt-entry-grid'; grid.append(promptField('显示名', name), promptField('稳定 Identifier', identifier));
    if (!entry.marker) {
      const role = promptSelect([['system', 'system'], ['user', 'user'], ['assistant', 'assistant']], entry.role); role.onchange = () => { entry.role = role.value; dirtyPrompt(); };
      const position = promptSelect([['relative', 'Relative（按拖动顺序）'], ['in_chat', 'In-Chat（按深度注入）']], entry.injection_position); position.onchange = () => { entry.injection_position = position.value; dirtyPrompt(); renderPromptEntries(); };
      grid.append(promptField('Role', role), promptField('Injection Position', position));
      if (entry.injection_position === 'in_chat') {
        const depth = document.createElement('input'); depth.type = 'number'; depth.min = '0'; depth.value = entry.injection_depth; depth.oninput = () => { entry.injection_depth = Math.max(0, Number(depth.value) || 0); dirtyPrompt(); };
        const injectionOrder = document.createElement('input'); injectionOrder.type = 'number'; injectionOrder.value = entry.injection_order; injectionOrder.oninput = () => { entry.injection_order = Number(injectionOrder.value) || 0; dirtyPrompt(); };
        grid.append(promptField('Depth（0=最后消息之后）', depth), promptField('Order（同 Depth/Role）', injectionOrder));
      }
      const content = document.createElement('textarea'); content.value = entry.content; content.oninput = () => { entry.content = content.value; dirtyPrompt(); const value = estimatePromptTokens(content.value); token.textContent = `≈ ${value} tokens`; renderPromptTokenTotal(); };
      card.append(grid, promptField('Content', content));
    } else {
      const note = document.createElement('p'); note.className = 'hint'; note.textContent = entry.identifier === 'chatHistory' ? '运行时展开选中的历史消息与当前用户消息；关闭后不会暗中回填。' : '运行时展开对应世界书出口；4.3 接入世界书编辑器。';
      card.append(grid, note);
    }
    container.appendChild(card);
  });
  $('promptTokenTotal').textContent = `启用正文静态估算 ≈ ${total} tokens`;
}
function renderPromptTokenTotal() { const preset = selectedPromptPreset(); if (!preset) return; const enabled = new Map(preset.prompt_order.map(item => [item.identifier, item.enabled])); const total = preset.prompts.reduce((sum, item) => sum + (!item.marker && item.enabled && enabled.get(item.identifier) !== false ? estimatePromptTokens(item.content) : 0), 0); $('promptTokenTotal').textContent = `启用正文静态估算 ≈ ${total} tokens`; }
function renderPromptPresets(selectedId = null) {
  const select = $('promptPreset'); select.innerHTML = '';
  promptPresets().forEach(preset => { const option = document.createElement('option'); option.value = preset.id; option.textContent = preset.name; select.appendChild(option); });
  select.value = selectedId || settings.prompt_presets.active_preset_id || promptPresets()[0]?.id || '';
  promptDirty = false; renderPromptEntries();
}
async function promptApi(url, options = {}) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || 'Preset 操作失败')); return payload; }
async function activatePromptPreset(presetId) { settings.prompt_presets = await promptApi('/api/prompt-presets/active/select', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preset_id: presetId }) }); renderPromptPresets(presetId); setPromptState('已切换服务端全局 Preset，将从下一轮开始生效', 'saved'); }
async function saveCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset) return; preset.name = $('promptPresetName').value.trim() || preset.name; setPromptState('正在保存…'); settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(preset) }); await activatePromptPreset(preset.id); setPromptState('已保存并启用，将从下一轮开始生效', 'saved'); }
async function newPromptPreset() { settings.prompt_presets = await promptApi('/api/prompt-presets/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '新 Preset' }) }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已新建并启用；可编辑后保存', 'saved'); }
async function copyCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset) return; settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}/copy`, { method: 'POST' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已复制并启用副本', 'saved'); }
async function deleteCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset || !confirm(`删除 Preset「${preset.name}」？`)) return; settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}`, { method: 'DELETE' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已删除；服务端当前 Preset 已更新', 'saved'); }
async function restoreDefaultPromptPreset() { if (!confirm('恢复 WRX 最小默认预设？同 ID 的默认预设会被重置。')) return; settings.prompt_presets = await promptApi('/api/prompt-presets/restore-default', { method: 'POST' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('WRX 最小默认预设已恢复并启用', 'saved'); }
function addPromptEntry() { const preset = selectedPromptPreset(); if (!preset) return; const identifier = `prompt-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`; preset.prompts.push({ identifier, name: '新 Prompt', enabled: true, role: 'system', content: '', injection_position: 'relative', injection_depth: 0, injection_order: 100, marker: false, raw_fields: {} }); preset.prompt_order.push({ identifier, enabled: true, raw_fields: {} }); dirtyPrompt('已新增普通条目；保存前不会用于下一轮'); renderPromptEntries(); }
function addMarkerEntry() { const preset = selectedPromptPreset(); const identifier = $('markerToAdd').value; if (!preset || preset.prompts.some(item => item.identifier === identifier)) { setPromptState('该 Marker 已存在；每类运行时内容只允许一个目标插槽', 'dirty'); return; } preset.prompts.push({ identifier, name: identifier, enabled: true, role: 'system', content: '', injection_position: 'relative', injection_depth: 0, injection_order: 100, marker: true, raw_fields: {} }); preset.prompt_order.push({ identifier, enabled: true, raw_fields: {} }); dirtyPrompt('已新增 Marker；保存前不会用于下一轮'); renderPromptEntries(); }
async function exportCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset) return; const exported = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}/export`); const blob = new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${preset.name.replace(/[\\/:*?"<>|]/g, '_') || 'preset'}.json`; link.click(); URL.revokeObjectURL(link.href); setPromptState('已导出当前服务端已保存版本', 'saved'); }
function importReportText(report, saved = false) { return JSON.stringify({ saved, format: report.format, compatibility_conversions: report.compatibility_conversions || [], unknown_fields: report.unknown_fields, unsupported_fields: report.unsupported_fields, mapped_markers: report.mapped_markers, warnings: report.warnings }, null, 2); }
function renderImportPreview(result) {
  $('promptImportReport').textContent = importReportText(result.report, false);
  const mappings = $('promptMarkerMappings'); mappings.innerHTML = '';
  result.report.pending_mappings.forEach(item => { const select = promptSelect([['', '请选择映射'], ['worldInfoBefore', 'worldInfoBefore'], ['charDefinitions', 'charDefinitions'], ['worldInfoAfter', 'worldInfoAfter'], ['userDefinitions', 'userDefinitions'], ['chatHistory', 'chatHistory'], ['__skip__', '明确跳过并禁用保留']], item.suggested_target || ''); select.dataset.sourceMarker = item.identifier; mappings.appendChild(promptField(`${item.name} (${item.identifier}) · 待手动映射`, select)); });
  $('confirmPromptImport').disabled = false; $('confirmPromptImport').textContent = '确认导入并启用'; $('promptImportDialog').showModal();
}
async function previewPromptImport(file) { const text = await file.text(); const data = JSON.parse(text); const result = await promptApi('/api/prompt-presets/import/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data }) }); pendingPromptImport = data; renderImportPreview(result); }
async function confirmPromptImport() { if (!pendingPromptImport) return; const markerMappings = {}; document.querySelectorAll('[data-source-marker]').forEach(select => { if (select.value) markerMappings[select.dataset.sourceMarker] = select.value; }); const result = await promptApi('/api/prompt-presets/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: pendingPromptImport, marker_mappings: markerMappings }) }); settings.prompt_presets = result.state; renderPromptPresets(result.preset.id); $('promptImportReport').textContent = importReportText(result.report, true); $('promptMarkerMappings').innerHTML = ''; $('confirmPromptImport').disabled = true; $('confirmPromptImport').textContent = '已导入'; pendingPromptImport = null; setPromptState('导入成功并启用；未知字段已保留在 raw_fields', 'saved'); }

function lorebooks() { return settings.lorebooks.lorebooks || []; }
function selectedLorebook() { return lorebooks().find(item => item.id === $('lorebookSelect').value); }
function setLorebookState(message, kind = '') { $('lorebookState').textContent = message; $('lorebookState').className = `hint ${kind}`.trim(); }
function dirtyLorebook(message = '有未保存修改；保存前不会用于下一轮') { lorebookDirty = true; setLorebookState(message, 'dirty'); }
function loreKeys(value) { return String(value || '').split(/[,\n]/).map(item => item.trim()).filter(Boolean); }
function finalLoreOutlet(entry) { if (entry.position === 'at_depth') return `@Depth ${entry.depth} · ${entry.role} · Order ${entry.order}`; if (entry.outlet) return `${entry.outlet}（高级覆盖）`; if (entry.category === 'char') return 'charDefinitions（char 默认）'; if (entry.category === 'user') return 'userDefinitions（user 默认）'; return entry.position === 'before_char' ? 'worldInfoBefore' : 'worldInfoAfter'; }
function loreReason(reason) { const labels = { disabled: '条目已禁用', empty_content: '正文为空', constant: '常驻', no_constant_or_keys: '既非常驻也无关键词', keyword_not_matched: '关键词未命中' }; return reason?.startsWith('keyword:') ? `命中关键词：${reason.slice(8)}` : (labels[reason] || reason || '未知'); }
function loreTraceFor(entryId) { if (!lastLorebookTrace || lastLorebookTrace.lorebook?.id !== selectedLorebook()?.id) return null; return lastLorebookTrace.entries.find(item => item.id === entryId) || null; }
function loreActivationLabel(trace) { if (!trace) return ['尚无本轮记录', '']; if (trace.active && trace.sent) return [`已激活并发送 · ${loreReason(trace.reason)}`, 'saved']; if (trace.active) return [`已激活但未发送 · ${loreReason(trace.reason)} · 检查 Marker`, 'dirty']; return [`未激活 · ${loreReason(trace.reason)}`, '']; }
function renderLorebookTokenTotal() { const book = selectedLorebook(); const total = (book?.entries || []).reduce((sum, entry) => sum + (entry.enabled ? estimatePromptTokens(entry.content) : 0), 0); $('lorebookTokenTotal').textContent = `启用正文静态估算 ≈ ${total} tokens`; }
function renderLorebookEntries() {
  const book = selectedLorebook(); const container = $('lorebookEntries'); container.innerHTML = '';
  if (!book) { $('lorebookTokenTotal').textContent = '静态估算 ≈ 0 tokens'; $('lorebookActivationSummary').textContent = '尚无本轮激活记录'; return; }
  $('lorebookName').value = book.name;
  if (!lastLorebookTrace) $('lorebookActivationSummary').textContent = '尚无本轮激活记录';
  else if (lastLorebookTrace.lorebook?.id !== book.id) $('lorebookActivationSummary').textContent = `上一轮使用：${lastLorebookTrace.lorebook?.name || lastLorebookTrace.lorebook?.id}；当前世界书没有本轮记录`;
  else { const active = lastLorebookTrace.entries.filter(item => item.active).length; const sent = lastLorebookTrace.entries.filter(item => item.sent).length; $('lorebookActivationSummary').textContent = `上一轮：${active} 条激活，${sent} 条实际发送；逐条原因见下方`; }
  book.entries.forEach((entry, index) => {
    const card = document.createElement('details'); card.className = 'prompt-entry lore-entry'; card.dataset.loreEntryId = entry.id;
    card.ondragover = event => event.preventDefault(); card.ondrop = event => { event.preventDefault(); if (!draggedLoreEntryId || draggedLoreEntryId === entry.id) return; const from = book.entries.findIndex(item => item.id === draggedLoreEntryId); const to = book.entries.findIndex(item => item.id === entry.id); if (from < 0 || to < 0) return; const [moved] = book.entries.splice(from, 1); book.entries.splice(to, 0, moved); book.entries.forEach((item, orderIndex) => { item.order = (orderIndex + 1) * 100; }); dirtyLorebook('条目已拖动并重排 Order；保存前不会用于下一轮'); renderLorebookEntries(); };
    const head = document.createElement('summary'); head.className = 'prompt-entry-head';
    const handle = document.createElement('button'); handle.type = 'button'; handle.className = 'drag-handle'; handle.textContent = '↕ 拖动'; handle.draggable = true; handle.ondragstart = () => { draggedLoreEntryId = entry.id; }; handle.ondragend = () => { draggedLoreEntryId = null; };
    const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = Boolean(entry.enabled); enabled.onchange = () => { entry.enabled = enabled.checked; dirtyLorebook(); renderLorebookEntries(); };
    const enabledLabel = document.createElement('label'); enabledLabel.className = 'inline-check'; enabledLabel.append(enabled, document.createTextNode('启用'));
    const type = document.createElement('strong'); type.textContent = `${entry.category} · ${entry.title}`;
    const activation = document.createElement('span'); const [activationText, activationKind] = loreActivationLabel(loreTraceFor(entry.id)); activation.textContent = activationText; activation.className = `activation-badge ${activationKind}`.trim();
    const token = document.createElement('span'); token.className = 'token-badge'; token.textContent = `≈ ${estimatePromptTokens(entry.content)} tokens`;
    const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = '复制条目'; copy.onclick = () => { const clone = structuredClone(entry); clone.id = `lore-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`; clone.title = `${entry.title} 副本`; clone.order = Math.max(0, ...book.entries.map(item => Number(item.order) || 0)) + 100; book.entries.splice(index + 1, 0, clone); dirtyLorebook('已复制条目；保存前不会用于下一轮'); renderLorebookEntries(); };
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除条目'; remove.onclick = () => { book.entries = book.entries.filter(item => item.id !== entry.id); dirtyLorebook('条目已删除；保存前不会用于下一轮'); renderLorebookEntries(); };
    head.append(handle, enabledLabel, type, activation, token, copy, remove); card.appendChild(head);
    const title = document.createElement('input'); title.value = entry.title; title.oninput = () => { entry.title = title.value; dirtyLorebook(); };
    const id = document.createElement('input'); id.value = entry.id; id.readOnly = true;
    const category = promptSelect([['char', 'char · AI 角色'], ['user', 'user · 用户资料'], ['world', 'world · 世界设定'], ['mechanism', 'mechanism · 机制'], ['other', 'other · 其他']], entry.category); category.onchange = () => { entry.category = category.value; dirtyLorebook(); renderLorebookEntries(); };
    const constant = document.createElement('input'); constant.type = 'checkbox'; constant.checked = Boolean(entry.constant); constant.onchange = () => { entry.constant = constant.checked; dirtyLorebook(); };
    const constantLabel = document.createElement('label'); constantLabel.className = 'inline-check'; constantLabel.append(constant, document.createTextNode('每轮常驻'));
    const keys = document.createElement('textarea'); keys.className = 'compact-textarea'; keys.value = (entry.keys || []).join('\n'); keys.placeholder = '每行或逗号分隔；任一关键词命中即激活'; keys.oninput = () => { entry.keys = loreKeys(keys.value); dirtyLorebook(); };
    const scanDepth = document.createElement('input'); scanDepth.type = 'number'; scanDepth.min = '0'; scanDepth.value = entry.scan_depth; scanDepth.oninput = () => { entry.scan_depth = Math.max(0, Number(scanDepth.value) || 0); dirtyLorebook(); };
    const position = promptSelect([['before_char', 'Before Char'], ['after_char', 'After Char'], ['at_depth', '@Depth']], entry.position); position.onchange = () => { entry.position = position.value; if (position.value === 'at_depth') entry.outlet = null; dirtyLorebook(); renderLorebookEntries(); };
    const role = promptSelect([['system', 'system'], ['user', 'user'], ['assistant', 'assistant']], entry.role); role.onchange = () => { entry.role = role.value; dirtyLorebook(); renderLorebookEntries(); };
    const order = document.createElement('input'); order.type = 'number'; order.value = entry.order; order.oninput = () => { entry.order = Number(order.value) || 0; dirtyLorebook(); };
    const outlet = promptSelect([['', '按分类/Position 使用默认出口'], ['worldInfoBefore', 'worldInfoBefore'], ['charDefinitions', 'charDefinitions'], ['worldInfoAfter', 'worldInfoAfter'], ['userDefinitions', 'userDefinitions']], entry.outlet || ''); outlet.disabled = entry.position === 'at_depth'; outlet.onchange = () => { entry.outlet = outlet.value || null; dirtyLorebook(); renderLorebookEntries(); };
    const grid = document.createElement('div'); grid.className = 'prompt-entry-grid'; grid.append(promptField('标题', title), promptField('稳定 ID', id), promptField('分类', category), constantLabel, promptField('扫描层数', scanDepth), promptField('Position', position), promptField('Role', role), promptField('Order', order), promptField('高级出口覆盖', outlet));
    if (entry.position === 'at_depth') { const depth = document.createElement('input'); depth.type = 'number'; depth.min = '0'; depth.value = entry.depth; depth.oninput = () => { entry.depth = Math.max(0, Number(depth.value) || 0); dirtyLorebook(); }; grid.append(promptField('Depth（0=最后消息之后）', depth)); }
    const finalOutlet = document.createElement('strong'); finalOutlet.className = 'final-outlet'; finalOutlet.textContent = `最终出口：${finalLoreOutlet(entry)}`;
    const content = document.createElement('textarea'); content.value = entry.content; content.oninput = () => { entry.content = content.value; dirtyLorebook(); token.textContent = `≈ ${estimatePromptTokens(content.value)} tokens`; renderLorebookTokenTotal(); };
    const comment = document.createElement('textarea'); comment.className = 'compact-textarea'; comment.value = entry.comment || ''; comment.placeholder = '仅供用户阅读，不进入 Prompt'; comment.oninput = () => { entry.comment = comment.value; dirtyLorebook(); };
    card.append(grid, promptField('关键词 OR', keys), finalOutlet, promptField('正文', content), promptField('备注（不发送）', comment)); container.appendChild(card);
  });
  renderLorebookTokenTotal();
}
function renderLorebooks(selectedId = null) { const select = $('lorebookSelect'); select.innerHTML = ''; lorebooks().forEach(book => { const option = document.createElement('option'); option.value = book.id; option.textContent = book.name; select.appendChild(option); }); select.value = selectedId || settings.lorebooks.active_lorebook_id || lorebooks()[0]?.id || ''; lorebookDirty = false; renderLorebookEntries(); }
async function lorebookApi(url, options = {}) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || 'Lorebook 操作失败')); return payload; }
async function activateLorebook(bookId) { settings.lorebooks = await lorebookApi('/api/lorebooks/active/select', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lorebook_id: bookId }) }); renderLorebooks(bookId); setLorebookState('已切换服务端全局 Lorebook，将从下一轮开始生效', 'saved'); }
async function saveCurrentLorebook() { const book = selectedLorebook(); if (!book) return; book.name = $('lorebookName').value.trim() || book.name; setLorebookState('正在保存…'); settings.lorebooks = await lorebookApi(`/api/lorebooks/${encodeURIComponent(book.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(book) }); await activateLorebook(book.id); setLorebookState('已保存并启用，将从下一轮开始生效', 'saved'); }
async function newLorebook() { settings.lorebooks = await lorebookApi('/api/lorebooks/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '新 Lorebook' }) }); renderLorebooks(settings.lorebooks.active_lorebook_id); setLorebookState('已新建并启用空世界书', 'saved'); }
async function copyCurrentLorebook() { const book = selectedLorebook(); if (!book) return; settings.lorebooks = await lorebookApi(`/api/lorebooks/${encodeURIComponent(book.id)}/copy`, { method: 'POST' }); renderLorebooks(settings.lorebooks.active_lorebook_id); setLorebookState('已复制并启用副本', 'saved'); }
async function deleteCurrentLorebook() { const book = selectedLorebook(); if (!book || !confirm(`删除 Lorebook「${book.name}」？`)) return; settings.lorebooks = await lorebookApi(`/api/lorebooks/${encodeURIComponent(book.id)}`, { method: 'DELETE' }); renderLorebooks(settings.lorebooks.active_lorebook_id); setLorebookState('已删除；服务端当前 Lorebook 已更新', 'saved'); }
function addLoreEntry() { const book = selectedLorebook(); if (!book) return; const id = `lore-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`; book.entries.push({ id, title: '新条目', enabled: true, category: 'other', content: '', constant: false, keys: [], scan_depth: 20, position: 'after_char', depth: 0, role: 'system', order: Math.max(0, ...book.entries.map(item => Number(item.order) || 0)) + 100, comment: '', outlet: null, raw_fields: {} }); dirtyLorebook('已新增条目；保存前不会用于下一轮'); renderLorebookEntries(); }
async function exportCurrentLorebook() { const book = selectedLorebook(); if (!book) return; const exported = await lorebookApi(`/api/lorebooks/${encodeURIComponent(book.id)}/export`); const blob = new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${book.name.replace(/[\\/:*?"<>|]/g, '_') || 'lorebook'}.json`; link.click(); URL.revokeObjectURL(link.href); setLorebookState('已导出当前服务端已保存版本', 'saved'); }
function lorebookReportText(report, saved = false) { return JSON.stringify({ saved, format: report.format, summary: report.summary || {}, compatibility_conversions: report.compatibility_conversions || [], entry_mappings: report.entry_mappings || [], unknown_fields: report.unknown_fields, unsupported_fields: report.unsupported_fields, warnings: report.warnings }, null, 2); }
async function previewLorebookImport(file) { const data = JSON.parse(await file.text()); if (!data.name) data.name = file.name.replace(/\.json$/i, ''); const result = await lorebookApi('/api/lorebooks/import/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data }) }); pendingLorebookImport = data; $('lorebookImportReport').textContent = lorebookReportText(result.report, false); $('confirmLorebookImport').disabled = false; $('confirmLorebookImport').textContent = '确认导入并启用'; $('lorebookImportDialog').showModal(); }
async function confirmLorebookImport() { if (!pendingLorebookImport) return; const result = await lorebookApi('/api/lorebooks/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: pendingLorebookImport }) }); settings.lorebooks = result.state; renderLorebooks(result.lorebook.id); $('lorebookImportReport').textContent = lorebookReportText(result.report, true); $('confirmLorebookImport').disabled = true; $('confirmLorebookImport').textContent = '已导入'; pendingLorebookImport = null; setLorebookState('导入成功并启用；未知/不支持字段已保留并报告', 'saved'); }

function providerCollection(kind) { return settings.provider_profiles[`${kind}_profiles`]; }
function providerActiveKey(kind) { return `active_${kind}_profile_id`; }
function providerState(kind, message, state = '') { const node = $(`${kind}ProviderState`); node.textContent = message; node.className = `hint ${state}`.trim(); }
function selectedProvider(kind) { return providerCollection(kind).find(item => item.id === $(`${kind}Profile`).value); }
function setKeyPlaceholder(kind, profile) { const input = $(`${kind}ApiKey`); input.value = ''; input.placeholder = profile?.api_key_set ? '••••••••（已保存在本机；留空保持）' : '尚未保存 Key'; }
function clearFetchedModels() { const select = $('llmFetchedModels'); select.innerHTML = '<option value="">点击“拉取模型”后在这里选择</option>'; select.disabled = true; }
function renderFetchedModels(models) {
  const select = $('llmFetchedModels'); const current = $('llmModel').value.trim(); select.innerHTML = '';
  const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = models.length ? `请选择模型（共 ${models.length} 个）` : '接口未返回模型'; select.appendChild(placeholder);
  models.forEach(model => { const option = document.createElement('option'); option.value = model; option.textContent = model; select.appendChild(option); });
  select.disabled = models.length === 0; select.value = models.includes(current) ? current : '';
}
function fillProvider(kind) {
  const profile = selectedProvider(kind);
  if (!profile) { if (kind === 'llm') clearFetchedModels(); setKeyPlaceholder(kind, null); providerState(kind, '尚无 Profile，请新建并保存', 'dirty'); return; }
  if (kind === 'llm') { $('llmName').value = profile.name; $('llmBaseUrl').value = profile.base_url; $('llmModel').value = profile.model; clearFetchedModels(); }
  if (kind === 'stt') { $('sttName').value = profile.name; $('sttEndpoint').value = profile.endpoint; $('sttStreamEndpoint').value = profile.stream_endpoint; $('sttResourceId').value = profile.resource_id; $('sttTwoPass').checked = profile.stream_two_pass !== false; }
  if (kind === 'tts') { $('ttsName').value = profile.name; $('ttsProviderType').value = profile.provider_type || 'http'; $('ttsEndpoint').value = profile.endpoint; $('ttsResourceId').value = profile.resource_id; $('ttsVoiceType').value = profile.voice_type; $('ttsEmotion').value = profile.emotion || ''; $('ttsEnableEmotion').checked = Boolean(profile.enable_emotion); $('ttsEmotionScale').value = profile.emotion_scale ?? 4; $('ttsSpeedRatio').value = profile.speed_ratio ?? 1; $('ttsRequestTemplate').value = JSON.stringify(profile.request_template || {}, null, 2); }
  setKeyPlaceholder(kind, profile);
  const active = settings.provider_profiles[providerActiveKey(kind)] === profile.id;
  providerState(kind, active ? `当前全局启用：${profile.name}` : `已载入：${profile.name}`, active ? 'saved' : '');
}
function renderProviderProfiles(kind, selectedId = null) {
  const select = $(`${kind}Profile`); select.innerHTML = '';
  providerCollection(kind).forEach(profile => { const option = document.createElement('option'); option.value = profile.id; option.textContent = profile.name; select.appendChild(option); });
  select.value = selectedId || settings.provider_profiles[providerActiveKey(kind)] || providerCollection(kind)[0]?.id || '';
  fillProvider(kind);
}
function renderAllProviderProfiles() { ['llm', 'stt', 'tts'].forEach(kind => renderProviderProfiles(kind)); }
async function providerApi(url, options = {}) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Provider 操作失败'); return payload; }
async function activateProvider(kind, profileId) { if (!profileId) return; settings.provider_profiles = await providerApi(`/api/provider-profiles/active/${kind}/select`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }) }); renderProviderProfiles(kind, profileId); providerState(kind, '已切换，将从下一轮开始生效', 'saved'); }
function newProvider(kind) {
  const id = `${kind}-${Date.now()}`;
  const defaults = kind === 'llm' ? { id, name: '新 LLM Profile', provider_type: 'openai_compatible', base_url: 'https://api.openai.com/v1', api_key: '', api_key_set: false, model: '' } : kind === 'stt' ? { id, name: '新 STT Profile', provider_type: 'volcengine', endpoint: 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream', stream_endpoint: 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async', resource_id: '', api_key: '', api_key_set: false, stream_two_pass: true } : { id, name: '新 TTS Profile', provider_type: 'websocket', endpoint: 'wss://openspeech.bytedance.com/api/v3/tts/bidirection', resource_id: 'seed-tts-2.0', api_key: '', api_key_set: false, voice_type: '', request_template: {}, emotion: '', enable_emotion: false, emotion_scale: 4, speed_ratio: 1 };
  providerCollection(kind).push(defaults); renderProviderProfiles(kind, id); providerState(kind, '新 Profile 尚未保存', 'dirty');
}
function providerPayload(kind) {
  const current = selectedProvider(kind); if (!current) throw new Error('请先新建 Profile');
  if (kind === 'llm') return { id: current.id, name: $('llmName').value.trim(), provider_type: 'openai_compatible', base_url: $('llmBaseUrl').value.trim(), api_key: $('llmApiKey').value, model: $('llmModel').value.trim() };
  if (kind === 'stt') return { id: current.id, name: $('sttName').value.trim(), provider_type: 'volcengine', endpoint: $('sttEndpoint').value.trim(), stream_endpoint: $('sttStreamEndpoint').value.trim(), resource_id: $('sttResourceId').value.trim(), api_key: $('sttApiKey').value, stream_two_pass: $('sttTwoPass').checked };
  let requestTemplate; try { requestTemplate = JSON.parse($('ttsRequestTemplate').value || '{}'); } catch { throw new Error('TTS Request Template 不是合法 JSON'); }
  return { id: current.id, name: $('ttsName').value.trim(), provider_type: $('ttsProviderType').value, endpoint: $('ttsEndpoint').value.trim(), resource_id: $('ttsResourceId').value.trim(), api_key: $('ttsApiKey').value, voice_type: $('ttsVoiceType').value.trim(), request_template: requestTemplate, emotion: $('ttsEmotion').value.trim(), enable_emotion: $('ttsEnableEmotion').checked, emotion_scale: Number($('ttsEmotionScale').value) || 4, speed_ratio: Number($('ttsSpeedRatio').value) || 1 };
}
async function saveProvider(kind) { const payload = providerPayload(kind); providerState(kind, '正在保存…'); settings.provider_profiles = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(payload.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); await activateProvider(kind, payload.id); }
async function deleteProvider(kind) { const profile = selectedProvider(kind); if (!profile) return; settings.provider_profiles = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(profile.id)}`, { method: 'DELETE' }); renderProviderProfiles(kind); providerState(kind, '已删除；当前选择已更新', 'saved'); }
function formatProbe(result) { return Object.entries(result.stages || {}).map(([name, value]) => `${name}: ${value.status}${value.detail ? `（${value.detail}）` : ''}`).join('；'); }
async function testProvider(kind) { const profile = selectedProvider(kind); if (!profile) return; providerState(kind, '正在执行真实最小请求…'); const result = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(profile.id)}/test`, { method: 'POST' }); providerState(kind, formatProbe(result), result.ok ? 'saved' : 'dirty'); if (kind === 'tts' && result.audio_base64) playAudio({ audio_base64: result.audio_base64, audio_mime: result.audio_mime, latency: {} }); }
async function fetchModels() { const profile = selectedProvider('llm'); if (!profile) return; providerState('llm', '正在请求 /models…'); const result = await providerApi(`/api/provider-profiles/llm/${encodeURIComponent(profile.id)}/models`, { method: 'POST' }); if (result.ok) renderFetchedModels(result.models || []); providerState('llm', result.ok ? `已拉取 ${result.models.length} 个模型；请从下拉框选择，或手动输入` : formatProbe(result), result.ok ? 'saved' : 'dirty'); }

async function start() {
  if (recording || startPromise || processing) return;
  if (currentAudio && !currentAudio.paused) { status('请先中断当前播放'); return; }
  setConversationControlsDisabled(true);
  setConfigurationControlsDisabled(true);
  setTextInputControlsDisabled(true);
  stopping = false;
  status('Preparing Microphone');
  startPromise = (async () => {
    mediaStream = await acquireMicrophone();
    audioContext = new AudioContext();
    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    chunks = [];
    pendingSttFrames = [];
    sttStream = null;
    processor.onaudioprocess = event => {
      if (!recording) return;
      const samples = new Float32Array(event.inputBuffer.getChannelData(0));
      chunks.push(samples);
      if (STT_INTEGRITY_MODE) return;
      const pcm = encodePcm16(samples, audioContext.sampleRate);
      if (sttStream?.ready && sttStream.socket.readyState === WebSocket.OPEN) sttStream.socket.send(pcm);
      else if (sttOpeningPromise) pendingSttFrames.push(pcm);
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    await audioContext.resume();
    recording = true;
    $('talk').classList.add('active');
    status('Listening');
    sttOpeningPromise = (STT_INTEGRITY_MODE ? Promise.resolve(null) : openStreamingStt()).then(state => {
      sttStream = state;
      if (state?.ready && state.socket.readyState === WebSocket.OPEN) pendingSttFrames.forEach(frame => state.socket.send(frame));
      pendingSttFrames = [];
      return state;
    });
  })();
  try { await startPromise; if (stopping) await stop(); } catch (error) { if (sttStream) { try { sttStream.socket.close(); } catch {} sttStream = null; } pendingSttFrames = []; releaseMicrophone(); setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); status('Error'); alert(`无法开始录音：${error.message}`); } finally { startPromise = null; }
}

async function stop() {
  if (startPromise && !recording) { stopping = true; return; }
  if (finishPromise) return finishPromise;
  finishPromise = finishRecording().finally(() => { finishPromise = null; });
  return finishPromise;
}

async function finishRecording() {
  if (!recording || !audioContext) return;
  stopping = true;
  status('Finalizing Recording');
  const drainMs = Math.ceil(processor.bufferSize / audioContext.sampleRate * 1000) + 20;
  await new Promise(resolve => setTimeout(resolve, drainMs));
  if (!recording || !audioContext) return;
  recording = false;
  processor.onaudioprocess = null;
  source.disconnect();
  processor.disconnect();
  scheduleMicrophoneRelease();
  const releasedAt = performance.now();
  const sourceRate = audioContext.sampleRate;
  const data = new Float32Array(chunks.reduce((total, chunk) => total + chunk.length, 0));
  let offset = 0;
  chunks.forEach(chunk => { data.set(chunk, offset); offset += chunk.length; });
  const wav = encodeWav(data, sourceRate);
  await audioContext.close();
  audioContext = null;
  if (sttOpeningPromise) await sttOpeningPromise;
  sttOpeningPromise = null;
  stopping = false;
  $('talk').classList.remove('active');
  if (!data.length) { setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); status('Idle'); return; }
  const streamed = await finishStreamingStt(releasedAt);
  await processAudio(wav, streamed, releasedAt, data.length / sourceRate);
}

async function processAudio(wav, streamed = null, requestStarted = performance.now(), recordingDuration = 0, typedText = '') {
  stopAudio();
  if (processing) return false;
  processing = true;
  setConversationControlsDisabled(true);
  setConfigurationControlsDisabled(true);
  setTextInputControlsDisabled(true);
  const requestConversationId = activeConversationId;
  const requestMessages = [...messages];
  await prepareStreamPlayback(requestStarted);
  status(typedText ? 'Thinking' : 'Transcribing');
  let completed = false;
  try {
    const body = typedText ? { transcript: typedText, stt_latency: 0, recording_duration: 0, messages: requestMessages } : STT_INTEGRITY_MODE ? { audio_base64: b64(wav), messages: requestMessages } : streamed?.text ? { transcript: streamed.text, stt_latency: streamed.latency, recording_duration: recordingDuration, messages: requestMessages, provider_snapshot_id: streamed.snapshotId || '' } : { audio_base64: b64(wav), messages: requestMessages, provider_snapshot_id: streamed?.snapshotId || '' };
    const result = await fetch('/api/process/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!result.ok || !result.body) throw new Error('流式接口不可用');
    const reader = result.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let assistantNode;
    let transcript = '';
    const consume = async payload => {
      if (payload.type === 'state') status(payload.state);
      if (payload.type === 'transcript') { transcript = payload.text; addMessage('user', transcript); status('Thinking'); }
      if (payload.type === 'delta') { if (!assistantNode) { assistantNode = messageNode('assistant', ''); $('chat').prepend(assistantNode); } assistantNode.textContent = `Assistant: ${(assistantNode.textContent.replace(/^Assistant: /, '') || '')}${payload.text}`; }
      if (payload.type === 'audio_chunk') schedulePcmChunk(payload.audio_base64, payload.sample_rate || 24000);
      if (payload.type === 'complete') { if (activeConversationId !== requestConversationId) throw new Error('当前对话已切换，本轮结果未写入页面'); messages = payload.messages; renderConversation(); saveLlmDebug(payload.debug); if (streamPlayback?.firstPlaybackAt) payload.latency.actual_first_playback = (streamPlayback.firstPlaybackAt - streamPlayback.requestStarted) / 1000; renderDebug(payload, transcript); await persistConversation(requestConversationId, messages); completed = true; if (payload.audio_streamed) finishStreamPlayback(payload); else { discardPreparedStream(); if (!payload.error && payload.audio_base64) playAudio(payload); } if (payload.error || (!payload.audio_streamed && !payload.audio_base64)) { status('Error'); alert(`语音生成失败，但回复文本已保留：${payload.error || 'TTS 未返回音频'}`); setTimeout(() => status('Idle'), 1500); } }
      if (payload.type === 'failure') { discardPreparedStream(); renderConversation(); renderDebug(payload); if (payload.audio_base64) playAudio(payload); alert(payload.detail); }
      if (payload.type === 'error') { if (payload.prompt_tokens) renderDebug(payload); throw new Error(payload.detail); }
    };
    while (true) { const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done }); const frames = buffer.split('\n\n'); buffer = frames.pop() || ''; for (const frame of frames) { const line = frame.split('\n').find(item => item.startsWith('data: ')); if (line) await consume(JSON.parse(line.slice(6))); } if (done) break; }
  } catch (error) { discardPreparedStream(); renderConversation(); if (error.message === 'No speech detected') { status('No speech detected'); setTimeout(() => status('Idle'), 1200); } else { status('Error'); alert(error.message); setTimeout(() => status('Idle'), 1500); } } finally { processing = false; setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); }
  return completed;
}

async function sendTypedText() {
  const input = $('textInput');
  const typedText = input.value.trim();
  if (!typedText) { $('textInputState').textContent = '请先输入要发送的文字。'; input.focus(); return; }
  if (recording || startPromise || finishPromise || processing) { $('textInputState').textContent = '当前一轮尚未结束，请稍后再发送。'; return; }
  $('textInputState').textContent = '正在发送：已跳过 STT。';
  const completed = await processAudio(null, null, performance.now(), 0, typedText);
  if (completed) { input.value = ''; $('textInputState').textContent = '已发送并写入当前对话；本轮未调用 STT。'; }
  else $('textInputState').textContent = '发送失败，原文已保留，可直接重试。';
}

async function openStreamingStt() {
  if (settings?.mode !== 'real') return null;
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${scheme}://${location.host}/api/stt/stream`);
  const state = { socket, ready: false, settled: false, final: null, error: null, resolveFinal: null };
  const finalPromise = new Promise(resolve => { state.resolveFinal = resolve; });
  state.finalPromise = finalPromise;
  const readyPromise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('实时 STT 建连超时')), 5000);
    socket.onmessage = event => {
      const payload = JSON.parse(event.data);
      if (payload.type === 'ready') { clearTimeout(timer); state.ready = true; state.providerSnapshotId = payload.provider_snapshot_id || ''; resolve(); }
      if (payload.type === 'partial') state.partial = payload.text;
      if (payload.type === 'final') { state.settled = true; state.final = payload; state.resolveFinal(payload); }
      if (payload.type === 'error') { state.settled = true; state.error = payload.detail; state.resolveFinal(null); }
    };
    socket.onerror = () => { clearTimeout(timer); reject(new Error('实时 STT 连接失败')); };
    socket.onclose = () => { if (!state.settled) state.resolveFinal(null); };
  });
  try { await readyPromise; return state; } catch { try { socket.close(); } catch {} return null; }
}

async function finishStreamingStt(releasedAt) {
  const state = sttStream;
  sttStream = null;
  if (!state?.ready) return null;
  if (state.socket.readyState !== WebSocket.OPEN) return { text: '', snapshotId: state.providerSnapshotId || '' };
  state.socket.send(JSON.stringify({ type: 'finish' }));
  status('Transcribing');
  const timeout = new Promise(resolve => setTimeout(() => resolve(null), 10000));
  const result = await Promise.race([state.finalPromise, timeout]);
  try { state.socket.close(); } catch {}
  if (!result?.text?.trim()) return { text: '', snapshotId: state.providerSnapshotId || '' };
  return { text: result.text.trim(), latency: (performance.now() - releasedAt) / 1000, snapshotId: state.providerSnapshotId || '' };
}

async function prepareStreamPlayback(requestStarted) {
  const context = new AudioContext({ sampleRate: 24000 });
  await context.resume();
  streamPlayback = { context, sources: new Set(), nextAt: context.currentTime + 0.04, firstAt: null, firstPlaybackAt: null, requestStarted, finalOut: null, inputFinished: false, duration: 0, markTimer: null };
}

function pcmFromBase64(value) { const binary = atob(value); const bytes = new Uint8Array(binary.length); for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index); return new Int16Array(bytes.buffer); }

function schedulePcmChunk(encoded, sampleRate) {
  if (!streamPlayback) return;
  const pcm = pcmFromBase64(encoded);
  if (!pcm.length) return;
  const state = streamPlayback;
  const buffer = state.context.createBuffer(1, pcm.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
  const node = state.context.createBufferSource();
  node.buffer = buffer;
  node.connect(state.context.destination);
  const startsAt = Math.max(state.nextAt, state.context.currentTime + 0.025);
  if (state.firstAt === null) {
    state.firstAt = startsAt;
    const delay = Math.max(0, (startsAt - state.context.currentTime) * 1000);
    state.markTimer = setTimeout(() => { if (streamPlayback !== state) return; state.firstPlaybackAt = performance.now(); status('Speaking'); if (state.finalOut) { state.finalOut.latency.actual_first_playback = (state.firstPlaybackAt - state.requestStarted) / 1000; renderDebug(state.finalOut); } }, delay);
  }
  state.nextAt = startsAt + buffer.duration;
  state.duration += buffer.duration;
  state.sources.add(node);
  node.onended = () => { state.sources.delete(node); if (state.inputFinished && !state.sources.size) finalizeStreamPlayback(state); };
  node.start(startsAt);
  status('Generating Voice');
}

function finishStreamPlayback(out) { if (!streamPlayback) { prepareCompletedAudio(out); status('Idle'); return; } streamPlayback.finalOut = out; streamPlayback.inputFinished = true; if (streamPlayback.firstPlaybackAt) { out.latency.actual_first_playback = (streamPlayback.firstPlaybackAt - streamPlayback.requestStarted) / 1000; renderDebug(out); } if (!streamPlayback.sources.size) finalizeStreamPlayback(streamPlayback); }
function finalizeStreamPlayback(state) { if (streamPlayback !== state) return; if (state.markTimer) clearTimeout(state.markTimer); state.context.close(); streamPlayback = null; if (state.finalOut?.audio_base64) prepareCompletedAudio(state.finalOut); status('Idle'); updatePlayback(); }
function discardPreparedStream() { if (!streamPlayback) return; const state = streamPlayback; if (state.markTimer) clearTimeout(state.markTimer); state.sources.forEach(node => { try { node.stop(); } catch {} }); state.context.close(); streamPlayback = null; }
function prepareCompletedAudio(out) { if (!out?.audio_base64) return false; currentAudio = new Audio(`data:${out.audio_mime};base64,${out.audio_base64}`); currentAudio.onloadedmetadata = updatePlayback; currentAudio.ontimeupdate = updatePlayback; currentAudio.onended = () => { updatePlayback(); status('Idle'); }; currentAudio.onerror = () => { currentAudio = null; updatePlayback(); status('Error'); }; return true; }

function playAudio(out) {
  stopAudio();
  const playbackPreparationStarted = performance.now();
  if (!prepareCompletedAudio(out)) { status('Error'); return; }
  currentAudio.onplaying = () => { out.latency.audio_playback_preparation = (performance.now() - playbackPreparationStarted) / 1000; renderDebug(out); };
  status('Speaking');
  currentAudio.play().catch(error => { status('Error'); alert(`播放失败：${error.message}`); });
}

function updatePlayback() { if (streamPlayback) { const state = streamPlayback; const current = state.firstAt === null ? 0 : Math.max(0, Math.min(state.duration, state.context.currentTime - state.firstAt)); $('playback').value = state.duration ? current / state.duration * 100 : 0; $('playbackTime').textContent = `${formatTime(current)} / ${formatTime(state.duration)}`; $('playPause').textContent = state.context.state === 'suspended' ? '播放' : '暂停'; return; } const audio = currentAudio; const duration = audio && Number.isFinite(audio.duration) ? audio.duration : 0; const current = audio ? audio.currentTime : 0; $('playback').value = duration ? (current / duration) * 100 : 0; $('playbackTime').textContent = `${formatTime(current)} / ${formatTime(duration)}`; $('playPause').textContent = audio && !audio.paused ? '暂停' : '播放'; }
function stopAudio() { discardPreparedStream(); if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio.onended = null; currentAudio = null; } updatePlayback(); }
function toggleAudio() { if (streamPlayback) { if (streamPlayback.context.state === 'suspended') { streamPlayback.context.resume(); status('Speaking'); } else { streamPlayback.context.suspend(); status('Paused'); } updatePlayback(); return; } if (!currentAudio) return; if (currentAudio.paused) { currentAudio.play(); status('Speaking'); } else { currentAudio.pause(); status('Paused'); } updatePlayback(); }

function openManagerPanel(panelId) {
  const panel = $(panelId);
  if (!panel || panel.open || panel.inert) return;
  panel.showModal();
}
document.querySelectorAll('[data-open-panel]').forEach(button => { button.onclick = () => openManagerPanel(button.dataset.openPanel); });
document.querySelectorAll('[data-close-panel]').forEach(button => { button.onclick = () => $(button.dataset.closePanel).close(); });
document.querySelectorAll('.manager-dialog').forEach(dialog => { dialog.onclick = event => { if (event.target === dialog) dialog.close(); }; });
const providerGroups = [...document.querySelectorAll('#providerPanel .provider-group')];
providerGroups.forEach(group => {
  const action = group.querySelector('summary > span:last-child');
  const syncProviderGroup = () => {
    if (action) action.textContent = group.open ? '收起配置' : '展开配置';
  };
  group.ontoggle = syncProviderGroup;
  syncProviderGroup();
});
$('contextSettingsPanel').ontoggle = event => { const action = event.currentTarget.querySelector('.summary-action'); if (action) action.textContent = event.currentTarget.open ? '收起设置' : '展开设置'; };

function beginTalkPointer(event) {
  if (!event.isPrimary || activeTalkPointerId !== null || (event.pointerType === 'mouse' && event.button !== 0)) return;
  event.preventDefault();
  activeTalkPointerId = event.pointerId;
  try { $('talk').setPointerCapture(event.pointerId); } catch {}
  void start();
}
function endTalkPointer(event) {
  if (activeTalkPointerId === null || event.pointerId !== activeTalkPointerId) return;
  event.preventDefault();
  const pointerId = activeTalkPointerId;
  activeTalkPointerId = null;
  try { if ($('talk').hasPointerCapture(pointerId)) $('talk').releasePointerCapture(pointerId); } catch {}
  void stop();
}
$('talk').onpointerdown = beginTalkPointer;
$('talk').onpointerup = endTalkPointer;
$('talk').onpointercancel = endTalkPointer;
$('talk').onlostpointercapture = endTalkPointer;
$('sendText').onclick = () => void sendTypedText();
$('textInput').onkeydown = event => { if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); void sendTypedText(); } };
window.onkeydown = event => { if (capturingKey) { event.preventDefault(); event.stopPropagation(); if (event.code === 'Escape') { capturingKey = false; pendingKey = key; $('keyInput').value = formatHotkey(key); $('captureKey').textContent = '录制按键'; setKeyState('已取消录制，原按键未变'); return; } pendingKey = event.code; capturingKey = false; $('keyInput').value = formatHotkey(pendingKey); $('captureKey').textContent = '重新录制'; setKeyState(`已录制 ${formatHotkey(pendingKey)}，点击“保存并立即生效”`, 'dirty'); return; } const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName); const managerOpen = Boolean(document.querySelector('.manager-dialog[open]')); if (!managerOpen && !editing && event.code === key && !event.repeat) { event.preventDefault(); start(); } };
window.onkeyup = event => { if (!capturingKey && event.code === key) { event.preventDefault(); stop(); } };
$('playPause').onclick = toggleAudio;
$('stopAudio').onclick = () => { stopAudio(); status('Idle'); };
$('showLlmDebug').onclick = showLlmDebug;
$('closeLlmDebug').onclick = () => $('llmDebugDialog').close();
$('llmDebugDialog').onclick = event => { if (event.target === $('llmDebugDialog')) $('llmDebugDialog').close(); };
$('historyDepth').oninput = () => setHistoryDepthState('有未保存修改；保存前不会用于下一轮', 'dirty');
$('saveHistoryDepth').onclick = () => void saveHistoryDepth().catch(error => setHistoryDepthState(error.message, 'dirty'));
$('playback').oninput = event => { if (currentAudio && Number.isFinite(currentAudio.duration)) currentAudio.currentTime = currentAudio.duration * event.target.value / 100; };
$('promptPreset').onchange = event => { const next = event.target.value; if (promptDirty && !confirm('当前 Preset 有未保存修改，切换将丢弃这些修改。继续吗？')) { event.target.value = settings.prompt_presets.active_preset_id; return; } void activatePromptPreset(next).catch(error => { renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState(error.message, 'dirty'); }); };
$('captureKey').onclick = () => { capturingKey = true; $('captureKey').textContent = '请按下目标键…'; setKeyState('正在录制按键；按 Esc 取消', 'dirty'); $('captureKey').blur(); };
$('keyInput').onclick = () => $('captureKey').click();
$('saveKey').onclick = () => { key = pendingKey; localStorage.pttKey = key; $('keyInput').value = formatHotkey(key); setKeyState(`已保存并立即生效：${formatHotkey(key)}（无需重启）`, 'saved'); };
$('promptPresetName').oninput = () => { const preset = selectedPromptPreset(); if (preset) preset.name = $('promptPresetName').value; dirtyPrompt(); };
$('savePromptPreset').onclick = () => void saveCurrentPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('newPromptPreset').onclick = () => void newPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('copyPromptPreset').onclick = () => void copyCurrentPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('deletePromptPreset').onclick = () => void deleteCurrentPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('restorePrompts').onclick = () => void restoreDefaultPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('addPromptEntry').onclick = addPromptEntry; $('addMarkerEntry').onclick = addMarkerEntry;
$('exportPromptPreset').onclick = () => void exportCurrentPromptPreset().catch(error => setPromptState(error.message, 'dirty'));
$('importPromptPreset').onclick = () => $('promptImportFile').click();
$('promptImportFile').onchange = event => { const file = event.target.files[0]; event.target.value = ''; if (file) void previewPromptImport(file).catch(error => setPromptState(`导入预览失败：${error.message}`, 'dirty')); };
$('confirmPromptImport').onclick = () => void confirmPromptImport().catch(error => { $('promptImportReport').textContent += `\n\n导入失败：${error.message}`; });
$('closePromptImport').onclick = () => { $('promptImportDialog').close(); pendingPromptImport = null; };
$('promptImportDialog').onclick = event => { if (event.target === $('promptImportDialog')) { $('promptImportDialog').close(); pendingPromptImport = null; } };
$('lorebookSelect').onchange = event => { const next = event.target.value; if (lorebookDirty && !confirm('当前 Lorebook 有未保存修改，切换将丢弃这些修改。继续吗？')) { event.target.value = settings.lorebooks.active_lorebook_id; return; } void activateLorebook(next).catch(error => { renderLorebooks(settings.lorebooks.active_lorebook_id); setLorebookState(error.message, 'dirty'); }); };
$('lorebookName').oninput = () => { const book = selectedLorebook(); if (book) book.name = $('lorebookName').value; dirtyLorebook(); };
$('saveLorebook').onclick = () => void saveCurrentLorebook().catch(error => setLorebookState(error.message, 'dirty'));
$('newLorebook').onclick = () => void newLorebook().catch(error => setLorebookState(error.message, 'dirty'));
$('copyLorebook').onclick = () => void copyCurrentLorebook().catch(error => setLorebookState(error.message, 'dirty'));
$('deleteLorebook').onclick = () => void deleteCurrentLorebook().catch(error => setLorebookState(error.message, 'dirty'));
$('addLoreEntry').onclick = addLoreEntry;
$('exportLorebook').onclick = () => void exportCurrentLorebook().catch(error => setLorebookState(error.message, 'dirty'));
$('importLorebook').onclick = () => $('lorebookImportFile').click();
$('lorebookImportFile').onchange = event => { const file = event.target.files[0]; event.target.value = ''; if (file) void previewLorebookImport(file).catch(error => setLorebookState(`导入预览失败：${error.message}`, 'dirty')); };
$('confirmLorebookImport').onclick = () => void confirmLorebookImport().catch(error => { $('lorebookImportReport').textContent += `\n\n导入失败：${error.message}`; });
$('closeLorebookImport').onclick = () => { $('lorebookImportDialog').close(); pendingLorebookImport = null; };
$('lorebookImportDialog').onclick = event => { if (event.target === $('lorebookImportDialog')) { $('lorebookImportDialog').close(); pendingLorebookImport = null; } };
$('conversationSelect').onchange = event => { void switchConversation(event.target.value).catch(error => { renderConversationSelect(); setConversationState(error.message, 'dirty'); }); };
$('newConversation').onclick = () => { void createConversation().catch(error => setConversationState(`新建失败：${error.message}`, 'dirty')); };
$('saveConversation').onclick = () => { void persistConversation().catch(error => alert(error.message)); };
$('toggleConversation').onclick = () => { conversationExpanded = !conversationExpanded; renderConversation(); };
$('clearConversation').onclick = () => { messages = []; conversationExpanded = false; saveLlmDebug(null); renderConversation(); void persistConversation().catch(error => alert(error.message)); };
$('llmProfile').onchange = event => void activateProvider('llm', event.target.value).catch(error => providerState('llm', error.message, 'dirty')); $('sttProfile').onchange = event => void activateProvider('stt', event.target.value).catch(error => providerState('stt', error.message, 'dirty')); $('ttsProfile').onchange = event => void activateProvider('tts', event.target.value).catch(error => providerState('tts', error.message, 'dirty'));
$('newLlmProfile').onclick = () => newProvider('llm'); $('newSttProfile').onclick = () => newProvider('stt'); $('newTtsProfile').onclick = () => newProvider('tts');
$('deleteLlmProfile').onclick = () => void deleteProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('deleteSttProfile').onclick = () => void deleteProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('deleteTtsProfile').onclick = () => void deleteProvider('tts').catch(error => providerState('tts', error.message, 'dirty'));
$('saveLlmProfile').onclick = () => void saveProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('saveSttProfile').onclick = () => void saveProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('saveTtsProfile').onclick = () => void saveProvider('tts').catch(error => providerState('tts', error.message, 'dirty'));
$('llmFetchedModels').onchange = event => { if (!event.target.value) return; $('llmModel').value = event.target.value; providerState('llm', `已选择模型：${event.target.value}；点击保存后从下一轮启用`, 'dirty'); };
$('llmModel').oninput = event => { const select = $('llmFetchedModels'); if (!select.disabled) select.value = [...select.options].some(option => option.value === event.target.value.trim()) ? event.target.value.trim() : ''; };
$('testLlmProfile').onclick = () => void testProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('testSttProfile').onclick = () => void testProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('testTtsProfile').onclick = () => void testProvider('tts').catch(error => providerState('tts', error.message, 'dirty')); $('fetchLlmModels').onclick = () => void fetchModels().catch(error => providerState('llm', error.message, 'dirty'));
function b64(bytes) { let binary = ''; bytes.forEach(byte => { binary += String.fromCharCode(byte); }); return btoa(binary); }
function resample(samples, sourceRate, targetRate = 16000) { if (sourceRate === targetRate) return samples; const ratio = sourceRate / targetRate; const output = new Float32Array(Math.round(samples.length / ratio)); for (let i = 0; i < output.length; i += 1) { const start = Math.floor(i * ratio); const end = Math.min(samples.length, Math.floor((i + 1) * ratio)); let sum = 0; for (let j = start; j < end; j += 1) sum += samples[j]; output[i] = sum / Math.max(1, end - start); } return output; }
function encodePcm16(samples, sampleRate) { const pcm = resample(samples, sampleRate, 16000); const buffer = new ArrayBuffer(pcm.length * 2); const view = new DataView(buffer); pcm.forEach((sample, index) => view.setInt16(index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true)); return buffer; }
function encodeWav(samples, sampleRate) { const pcm = resample(samples, sampleRate, 16000); const outputRate = 16000; const buffer = new ArrayBuffer(44 + pcm.length * 2); const view = new DataView(buffer); const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0))); write(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); write(8, 'WAVEfmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, outputRate, true); view.setUint32(28, outputRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, pcm.length * 2, true); pcm.forEach((sample, index) => view.setInt16(44 + index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true)); return new Uint8Array(buffer); }
updatePlayback();
setInterval(updatePlayback, 200);
load();
void prewarmMicrophoneIfGranted();
window.addEventListener('beforeunload', releaseMicrophone);
