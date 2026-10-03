// 设置面板、供应商、预设、世界书与旧向量管理兼容界面。
function status(value) { const indicator = $('status'); if (indicator) indicator.textContent = value; }
function formatHotkey(value) { if (value === 'Space') return 'Space'; if (value.startsWith('Key')) return value.slice(3); if (value.startsWith('Digit')) return value.slice(5); return value; }
function setKeyState(message, kind = '') { $('keyState').textContent = message; $('keyState').className = `hint ${kind}`.trim(); }
function setPromptState(message, kind = '') { $('promptState').textContent = message; $('promptState').className = `hint ${kind}`.trim(); }
function setHistoryDepthState(message, kind = '') { $('historyDepthState').textContent = message; $('historyDepthState').className = `hint ${kind}`.trim(); }
function renderDebug(out) { const promptHash = out.debug?.prompt_sha256 || ''; if (promptHash) setPromptState(promptDirty ? `本轮使用已保存 Preset（指纹 ${promptHash}）；页面仍有未保存修改` : `本轮已注入当前 Preset（指纹 ${promptHash}）`, promptDirty ? 'dirty' : 'saved'); const values = [['STT', out.latency?.stt], ['向量召回', out.latency?.vector_retrieval], ['LLM 首 Token', out.latency?.llm_first_token], ['首个可朗读片段', out.latency?.llm_first_tts_segment], ['TTS 首音', out.latency?.tts_first_audio], ['松键到服务端首音', out.latency?.response_to_first_audio], ['松键到实际首播', out.latency?.actual_first_playback], ['后台总耗时', out.latency?.total]]; const timings = values.filter(([, value]) => Number.isFinite(value)).map(([label, value]) => `<div class="latency-item"><span>${label}</span><strong>${value.toFixed(3)}s</strong></div>`).join(''); const metric = out.prompt_tokens; const token = Number.isFinite(metric?.value) ? `<div class="latency-item"><span>最终 Prompt Token</span><strong>${Math.trunc(metric.value)}${metric.source === 'provider' ? '（实际）' : '（估算）'}</strong></div>` : ''; $('latencyInfo').innerHTML = timings + token || '尚无数据'; }
function saveLlmDebug(debug) { lastLlmDebug = debug || null; lastLorebookTrace = debug?.prompt_trace ? { lorebook: debug.prompt_trace.lorebook, entries: debug.prompt_trace.lorebook_activation || [], vector_memory: debug.prompt_trace.vector_memory || {} } : null; $('showLlmDebug').disabled = false; if (settings?.lorebooks) renderLorebookEntries(); }

async function load() {
  settings = await fetch('/api/settings').then(r => r.json());
  $('mode').textContent = `V${settings.version} · ${settings.mode}`;
  await loadConversations();
  renderPromptPresets(settings.prompt_presets.active_preset_id);
  renderLorebooks(settings.lorebooks.active_lorebook_id);
  renderVectorMemory();
  $('historyDepth').value = settings.runtime_settings.history_depth;
  $('historyMode').value = settings.runtime_settings.history_mode || 'count';
  $('historySince').value = historyLocalInput(settings.runtime_settings.history_since);
  toggleHistorySelection();
  setHistoryDepthState(historySelectionDescription(settings.runtime_settings), 'saved');
  $('providerInfo').textContent = Object.entries(settings.provider_info).map(([key, value]) => `${key}: ${value || '未配置'}`).join(' · ');
  $('keyInput').value = formatHotkey(key);
  setKeyState(`当前生效：${formatHotkey(key)}（无需重启）`, 'saved');
  renderAllProviderProfiles();
  await memoryVectorAction(loadMemoryVectorModels);
  setPromptState('当前服务端 Preset 已载入，将用于下一轮', 'saved');
}

function setTextInputControlsDisabled(disabled) {
  $('sendText').disabled = disabled;
  $('textInput').readOnly = disabled;
}

function historyLocalInput(value) {
  if (!value) return '';
  const zone = typeof currentConversation === 'function' ? currentConversation()?.timezone : undefined;
  const parts = new Intl.DateTimeFormat('sv-SE', {timeZone:zone || 'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
  return parts.replace(' ', 'T');
}
function historySelectionDescription(value) {
  return value.history_mode === 'since' ? `当前全局设置：从 ${historyLocalInput(value.history_since).replace('T',' ')} 开始；下一轮生效` : `当前全局设置：最近 ${value.history_depth} 条旧消息；下一轮冻结`;
}
function toggleHistorySelection() {
  const since = $('historyMode').value === 'since';
  $('historySinceField').hidden = !since; $('historyCountField').hidden = since;
  $('historySinceField').style.display = since ? 'grid' : 'none';
  $('historyCountField').style.display = since ? 'none' : 'grid';
}
let historyPreviewRevision = 0;
async function previewHistoryRange() {
  const revision = ++historyPreviewRevision;
  const depth = Number($('historyDepth').value);
  const mode = $('historyMode').value;
  if (mode === 'since' && !$('historySince').value) throw new Error('请选择开始日期和时间');
  if (!Number.isInteger(depth) || depth < 0) throw new Error('历史消息条数必须是非负整数');
  const response = await fetch('/api/role-memory/history-preview', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:activeConversationId,history_mode:mode,history_since:mode === 'since' ? $('historySince').value : null,history_depth:depth})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '范围预览失败');
  if (revision === historyPreviewRevision) $('historyRangePreview').textContent = `选中 ${value.count} 条旧消息 · 估算 ${value.estimated_tokens.toLocaleString()} Token · 时区 ${value.timezone}（不含本轮输入和图片Token）`;
  return {history_mode:mode,history_since:value.history_since,history_depth:depth};
}
async function saveHistoryDepth() {
  const selection = await previewHistoryRange();
  setHistoryDepthState('正在保存…');
  const response = await fetch('/api/runtime-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection) });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '历史范围保存失败');
  settings.runtime_settings = payload;
  setHistoryDepthState(historySelectionDescription(payload), 'saved');
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
  $('promptTemperature').value = preset.generation_parameters?.temperature ?? '';
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
        grid.append(promptField('Depth（1=本轮 user 前；0 也会移至 user 前）', depth), promptField('Order（同 Depth/Role）', injectionOrder));
      }
      const content = document.createElement('textarea'); content.placeholder = '支持 {{char}}、{{user}}、{{char_status}}（当前情绪）、{{char_status_rules}}（情绪规则）、{{current_time}}（本轮时间）'; content.value = entry.content; content.oninput = () => { entry.content = content.value; dirtyPrompt(); const value = estimatePromptTokens(content.value); token.textContent = `≈ ${value} tokens`; renderPromptTokenTotal(); };
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
async function saveCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset) return; if (!$('promptTemperature').reportValidity()) { setPromptState('温度必须是 0–2 的数字，或留空使用模型默认值', 'dirty'); return; } updatePromptTemperature(); preset.name = $('promptPresetName').value.trim() || preset.name; setPromptState('正在保存…'); settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(preset) }); await activatePromptPreset(preset.id); setPromptState('已保存并启用，将从下一轮开始生效', 'saved'); }
function updatePromptTemperature() {
  const preset = selectedPromptPreset();
  const control = $('promptTemperature');
  if (!preset || !control.validity.valid) return;
  preset.generation_parameters ||= {};
  if (control.value === '') delete preset.generation_parameters.temperature;
  else preset.generation_parameters.temperature = control.valueAsNumber;
}
async function newPromptPreset() { settings.prompt_presets = await promptApi('/api/prompt-presets/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '新 Preset' }) }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已新建并启用；可编辑后保存', 'saved'); }
async function copyCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset) return; settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}/copy`, { method: 'POST' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已复制并启用副本', 'saved'); }
async function deleteCurrentPromptPreset() { const preset = selectedPromptPreset(); if (!preset || !confirm(`删除 Preset「${preset.name}」？`)) return; settings.prompt_presets = await promptApi(`/api/prompt-presets/${encodeURIComponent(preset.id)}`, { method: 'DELETE' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('已删除；服务端当前 Preset 已更新', 'saved'); }
async function restoreDefaultPromptPreset() { if (!confirm('恢复 WRX 最小默认预设？同 ID 的默认预设会被重置。')) return; settings.prompt_presets = await promptApi('/api/prompt-presets/restore-default', { method: 'POST' }); renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState('WRX 最小默认预设已恢复并启用', 'saved'); }
function addPromptEntry() { const preset = selectedPromptPreset(); if (!preset) return; const identifier = newIdentityId(); preset.prompts.push({ identifier, name: '新 Prompt', enabled: true, role: 'system', content: '', injection_position: 'relative', injection_depth: 0, injection_order: 100, marker: false, raw_fields: {} }); preset.prompt_order.push({ identifier, enabled: true, raw_fields: {} }); dirtyPrompt('已新增普通条目；保存前不会用于下一轮'); renderPromptEntries(); }
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
    const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = '复制条目'; copy.onclick = () => { const clone = structuredClone(entry); clone.id = newIdentityId(); clone.title = `${entry.title} 副本`; clone.order = Math.max(0, ...book.entries.map(item => Number(item.order) || 0)) + 100; book.entries.splice(index + 1, 0, clone); dirtyLorebook('已复制条目；保存前不会用于下一轮'); renderLorebookEntries(); };
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
    if (entry.position === 'at_depth') { const depth = document.createElement('input'); depth.type = 'number'; depth.min = '0'; depth.value = entry.depth; depth.oninput = () => { entry.depth = Math.max(0, Number(depth.value) || 0); dirtyLorebook(); }; grid.append(promptField('Depth（1=本轮 user 前；0 也会移至 user 前）', depth)); }
    const finalOutlet = document.createElement('strong'); finalOutlet.className = 'final-outlet'; finalOutlet.textContent = `最终出口：${finalLoreOutlet(entry)}`;
    const content = document.createElement('textarea'); content.placeholder = '支持 {{char}}、{{user}}、{{char_status}}（当前情绪）、{{char_status_rules}}（情绪规则）、{{current_time}}（本轮时间）'; content.value = entry.content; content.oninput = () => { entry.content = content.value; dirtyLorebook(); token.textContent = `≈ ${estimatePromptTokens(content.value)} tokens`; renderLorebookTokenTotal(); };
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
function addLoreEntry() { const book = selectedLorebook(); if (!book) return; const id = newIdentityId(); book.entries.push({ id, title: '新条目', enabled: true, category: 'other', content: '', constant: false, keys: [], scan_depth: 20, position: 'after_char', depth: 0, role: 'system', order: Math.max(0, ...book.entries.map(item => Number(item.order) || 0)) + 100, comment: '', outlet: null, raw_fields: {} }); dirtyLorebook('已新增条目；保存前不会用于下一轮'); renderLorebookEntries(); }
async function exportCurrentLorebook() { const book = selectedLorebook(); if (!book) return; const exported = await lorebookApi(`/api/lorebooks/${encodeURIComponent(book.id)}/export`); const blob = new Blob([JSON.stringify(exported, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${book.name.replace(/[\\/:*?"<>|]/g, '_') || 'lorebook'}.json`; link.click(); URL.revokeObjectURL(link.href); setLorebookState('已导出当前服务端已保存版本', 'saved'); }
function lorebookReportText(report, saved = false) { return JSON.stringify({ saved, format: report.format, summary: report.summary || {}, compatibility_conversions: report.compatibility_conversions || [], entry_mappings: report.entry_mappings || [], unknown_fields: report.unknown_fields, unsupported_fields: report.unsupported_fields, warnings: report.warnings }, null, 2); }
async function previewLorebookImport(file) { const data = JSON.parse(await file.text()); if (!data.name) data.name = file.name.replace(/\.json$/i, ''); const result = await lorebookApi('/api/lorebooks/import/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data }) }); pendingLorebookImport = data; $('lorebookImportReport').textContent = lorebookReportText(result.report, false); $('confirmLorebookImport').disabled = false; $('confirmLorebookImport').textContent = '确认导入并启用'; $('lorebookImportDialog').showModal(); }
async function confirmLorebookImport() { if (!pendingLorebookImport) return; const result = await lorebookApi('/api/lorebooks/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: pendingLorebookImport }) }); settings.lorebooks = result.state; renderLorebooks(result.lorebook.id); $('lorebookImportReport').textContent = lorebookReportText(result.report, true); $('confirmLorebookImport').disabled = true; $('confirmLorebookImport').textContent = '已导入'; pendingLorebookImport = null; setLorebookState('导入成功并启用；未知/不支持字段已保留并报告', 'saved'); }

function setVectorConfigState(message, kind = '') { $('vectorConfigState').textContent = message; $('vectorConfigState').className = `hint ${kind}`.trim(); }
function setVectorLibraryState(message, kind = '') { $('vectorLibraryState').textContent = message; $('vectorLibraryState').className = `hint ${kind}`.trim(); }
async function vectorApi(url, options = {}) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '向量记忆操作失败'); return payload; }
function renderVectorMemory() {
  const state = settings.vector_memory || { config: {}, libraries: [] };
  const config = state.config || {};
  $('vectorEnabled').checked = Boolean(config.enabled);
  $('vectorApiUrl').value = config.api_url || '';
  $('vectorApiKey').value = '';
  $('vectorApiKey').placeholder = config.api_key_set ? '已保存；留空保持原 Key' : '本地模型可留空';
  $('vectorModel').value = config.model || 'BAAI/bge-m3';
  $('vectorThreshold').value = config.threshold ?? 0.3;
  $('vectorMaxResults').value = config.max_results ?? 8;
  $('vectorContextDepth').value = config.context_depth ?? 2;
  $('vectorSeparator').value = config.separator || '---';
  $('vectorRerankEnabled').checked = Boolean(config.rerank_enabled);
  $('vectorRerankUrl').value = config.rerank_url || 'https://api.siliconflow.cn/v1/rerank';
  $('vectorRerankKey').value = '';
  $('vectorRerankKey').placeholder = config.rerank_key_set ? '已保存；留空保持原 Key' : '本地模型可留空';
  $('vectorRerankModel').value = config.rerank_model || 'BAAI/bge-reranker-v2-m3';
  const list = $('vectorLibraries'); list.innerHTML = '';
  (state.libraries || []).forEach(library => {
    const card = document.createElement('div'); card.className = 'vector-library-card';
    const head = document.createElement('div'); head.className = 'vector-library-head';
    const title = document.createElement('div'); const strong = document.createElement('strong'); strong.textContent = library.name; const meta = document.createElement('small'); meta.textContent = `${library.source_format} · ${library.vectorized_count}/${library.chunk_count} 已向量化`; title.append(strong, meta);
    const enabled = document.createElement('label'); enabled.className = 'inline-check'; const check = document.createElement('input'); check.type = 'checkbox'; check.checked = Boolean(library.enabled); enabled.append(check, document.createTextNode('参与召回'));
    const actions = document.createElement('div'); actions.className = 'button-row'; const inspect = document.createElement('button'); inspect.textContent = '查看切片'; const vectorize = document.createElement('button'); vectorize.textContent = library.vectorized_count === library.chunk_count ? '已完成向量化' : '开始/继续向量化'; vectorize.disabled = library.chunk_count > 0 && library.vectorized_count === library.chunk_count; const remove = document.createElement('button'); remove.textContent = '删除'; remove.className = 'danger-button'; actions.append(inspect, vectorize, remove); head.append(title, enabled, actions); card.append(head); list.append(card);
    inspect.onclick = () => void openVectorChunks(library.id).catch(error => setVectorLibraryState(`读取切片失败：${error.message}`, 'dirty'));
    check.onchange = async () => { try { settings.vector_memory = await vectorApi(`/api/vector-memory/libraries/${encodeURIComponent(library.id)}/enabled`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: check.checked }) }); renderVectorMemory(); setVectorLibraryState('知识库启用状态已保存，从下一轮生效', 'saved'); } catch (error) { check.checked = !check.checked; setVectorLibraryState(error.message, 'dirty'); } };
    vectorize.onclick = async () => { vectorize.disabled = true; setVectorLibraryState(`正在向量化「${library.name}」；已完成批次会持续保存…`); try { const result = await vectorApi(`/api/vector-memory/libraries/${encodeURIComponent(library.id)}/vectorize`, { method: 'POST' }); settings.vector_memory = result.state; renderVectorMemory(); setVectorLibraryState(`向量化完成：新增 ${result.report.completed}，已有 ${result.report.already_vectorized}，共 ${result.report.total}`, 'saved'); } catch (error) { vectorize.disabled = false; setVectorLibraryState(`向量化失败：${error.message}；已成功的批次仍保留`, 'dirty'); } };
    remove.onclick = async () => { if (!confirm(`删除向量知识库「${library.name}」及本地向量？`)) return; try { settings.vector_memory = await vectorApi(`/api/vector-memory/libraries/${encodeURIComponent(library.id)}`, { method: 'DELETE' }); renderVectorMemory(); setVectorLibraryState('知识库已删除', 'saved'); } catch (error) { setVectorLibraryState(error.message, 'dirty'); } };
  });
  $('vectorizeAllLibraries').disabled = !(state.libraries || []).some(library => library.vectorized_count < library.chunk_count);
  if (!(state.libraries || []).length) setVectorLibraryState('尚未导入知识库');
  setVectorConfigState(config.enabled ? '向量召回已启用；独立配置从下一轮冻结' : '向量召回当前关闭', config.enabled ? 'saved' : '');
}
function vectorConfigPayload() { const threshold = Number($('vectorThreshold').value); const maxResults = Number($('vectorMaxResults').value); const contextDepth = Number($('vectorContextDepth').value); return { enabled: $('vectorEnabled').checked, api_url: $('vectorApiUrl').value.trim(), api_key: $('vectorApiKey').value, model: $('vectorModel').value.trim() || 'BAAI/bge-m3', threshold: Number.isFinite(threshold) ? threshold : 0.3, max_results: Number.isInteger(maxResults) && maxResults > 0 ? maxResults : 8, context_depth: Number.isInteger(contextDepth) && contextDepth > 0 ? contextDepth : 2, separator: $('vectorSeparator').value || '---', rerank_enabled: $('vectorRerankEnabled').checked, rerank_url: $('vectorRerankUrl').value.trim() || 'https://api.siliconflow.cn/v1/rerank', rerank_key: $('vectorRerankKey').value, rerank_model: $('vectorRerankModel').value.trim() || 'BAAI/bge-reranker-v2-m3' }; }
async function saveVectorConfig() { setVectorConfigState('正在保存…'); settings.vector_memory = await vectorApi('/api/vector-memory/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(vectorConfigPayload()) }); renderVectorMemory(); setVectorConfigState('独立向量配置已保存，从下一轮生效', 'saved'); }
async function testVectorConfig() { await saveVectorConfig(); setVectorConfigState('正在调用独立 Embedding 模型…'); const result = await vectorApi('/api/vector-memory/test', { method: 'POST' }); if (!result.ok) throw new Error(result.detail || '连接失败'); setVectorConfigState(`连接成功：模型返回 ${result.dimensions} 维向量`, 'saved'); }
function renderFetchedVectorModels(selectId, models, emptyText) { const select = $(selectId); select.innerHTML = ''; const empty = document.createElement('option'); empty.value = ''; empty.textContent = models.length ? `请选择（${models.length} 个）` : emptyText; select.append(empty); models.forEach(model => { const option = document.createElement('option'); option.value = model; option.textContent = model; select.append(option); }); select.disabled = !models.length; }
async function fetchVectorModels(kind = 'embedding') { await saveVectorConfig(); setVectorConfigState(`正在拉取${kind === 'rerank' ? ' Rerank' : '向量'}模型…`); const result = await vectorApi('/api/vector-memory/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind }) }); if (!result.ok) throw new Error(result.detail || '拉取模型失败'); const target = kind === 'rerank' ? 'vectorFetchedRerankModels' : 'vectorFetchedModels'; renderFetchedVectorModels(target, result.models || [], '没有返回模型'); setVectorConfigState(`已拉取 ${result.models.length} 个${kind === 'rerank' ? ' Rerank' : '向量'}模型`, 'saved'); }
async function testVectorRerank() { await saveVectorConfig(); setVectorConfigState('正在测试 Rerank…'); const result = await vectorApi('/api/vector-memory/rerank/test', { method: 'POST' }); if (!result.ok) throw new Error(result.detail || 'Rerank 连接失败'); setVectorConfigState(`Rerank 连接成功，测试分数 ${Number(result.score).toFixed(4)}`, 'saved'); }
async function vectorizeAllLibraries() { const pending = (settings.vector_memory.libraries || []).filter(library => library.vectorized_count < library.chunk_count); if (!pending.length) return; $('vectorizeAllLibraries').disabled = true; let completed = 0; for (const library of pending) { setVectorLibraryState(`正在向量化 ${library.name}（${completed + 1}/${pending.length}）…`); const result = await vectorApi(`/api/vector-memory/libraries/${encodeURIComponent(library.id)}/vectorize`, { method: 'POST' }); settings.vector_memory = result.state; completed += 1; } renderVectorMemory(); setVectorLibraryState(`全部向量化完成：${completed} 个知识库`, 'saved'); }
async function openVectorChunks(libraryId) { inspectedVectorLibraryId = libraryId; vectorChunkOffset = 0; $('vectorChunkSearch').value = ''; $('vectorChunksDialog').showModal(); await loadVectorChunks(); }
async function loadVectorChunks(offset = vectorChunkOffset) {
  if (!inspectedVectorLibraryId) return;
  const query = $('vectorChunkSearch').value.trim();
  const params = new URLSearchParams({ offset: String(Math.max(0, offset)), limit: String(VECTOR_CHUNK_PAGE_SIZE), query });
  $('vectorChunksSummary').textContent = '正在读取切片…';
  const result = await vectorApi(`/api/vector-memory/libraries/${encodeURIComponent(inspectedVectorLibraryId)}/chunks?${params}`);
  vectorChunkOffset = result.offset;
  $('vectorChunksTitle').textContent = `${result.library.name} · 切片检查`;
  $('vectorChunksSummary').textContent = query ? `搜索命中 ${result.total} / 全部 ${result.unfiltered_total} 条；页面不显示完整向量数值` : `共 ${result.total} 条；页面不显示完整向量数值`;
  const list = $('vectorChunksList'); list.innerHTML = '';
  result.chunks.forEach(chunk => {
    const details = document.createElement('details'); details.className = 'vector-chunk-card';
    const summary = document.createElement('summary'); const heading = document.createElement('span'); heading.textContent = `#${chunk.index} · ${chunk.id}`; const badges = document.createElement('span'); badges.className = 'vector-chunk-badges';
    const vectorBadge = document.createElement('strong'); vectorBadge.className = chunk.vectorized ? 'saved' : 'dirty'; vectorBadge.textContent = chunk.vectorized ? `已向量化 · ${chunk.vector_dimensions} 维` : '未向量化'; const charBadge = document.createElement('small'); charBadge.textContent = `${chunk.characters} 字符`; badges.append(vectorBadge, charBadge); summary.append(heading, badges);
    const body = document.createElement('div'); body.className = 'vector-chunk-body'; const metaTitle = document.createElement('strong'); metaTitle.textContent = '元数据'; const meta = document.createElement('pre'); meta.textContent = JSON.stringify(chunk.metadata || {}, null, 2); const contentTitle = document.createElement('strong'); contentTitle.textContent = 'Embedding 正文'; const content = document.createElement('pre'); content.textContent = chunk.content; const hash = document.createElement('small'); hash.textContent = `SHA-256: ${chunk.content_sha256}`; body.append(metaTitle, meta, contentTitle, content, hash); details.append(summary, body); list.append(details);
  });
  if (!result.chunks.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = '没有找到匹配切片'; list.append(empty); }
  const page = result.total ? Math.floor(result.offset / result.limit) + 1 : 0; const pages = Math.ceil(result.total / result.limit); $('vectorChunksPage').textContent = `第 ${page} / ${pages} 页`;
  $('previousVectorChunks').disabled = result.offset <= 0; $('nextVectorChunks').disabled = result.offset + result.limit >= result.total;
}
async function previewVectorImport(file) { const text = await file.text(); const separator = $('vectorSeparator').value || '---'; const name = $('vectorLibraryName').value.trim() || file.name.replace(/\.(jsonl|md|markdown|txt)$/i, ''); const report = await vectorApi('/api/vector-memory/import/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, filename: file.name, separator }) }); pendingVectorImport = { text, filename: file.name, separator, name }; $('vectorImportReport').textContent = JSON.stringify({ saved: false, name, ...report }, null, 2); $('confirmVectorImport').disabled = false; $('confirmVectorImport').textContent = '确认导入（暂不调用模型）'; $('vectorImportDialog').showModal(); }
async function confirmVectorImport() { if (!pendingVectorImport) return; const result = await vectorApi('/api/vector-memory/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pendingVectorImport) }); settings.vector_memory = result.state; renderVectorMemory(); $('vectorImportReport').textContent += '\n\n已保存切片；请回到向量管理页点击“开始/继续向量化”。'; $('confirmVectorImport').disabled = true; $('confirmVectorImport').textContent = '已导入'; pendingVectorImport = null; setVectorLibraryState('预切片已导入，尚未调用向量模型', 'saved'); }

function providerCollection(kind) { return settings.provider_profiles[`${kind}_profiles`] || []; }
function providerActiveKey(kind) { return `active_${kind}_profile_id`; }
function providerState(kind, message, state = '') { const node = $(`${kind}ProviderState`); node.textContent = message; node.className = `hint ${state}`.trim(); }
function selectedProvider(kind) { return providerCollection(kind).find(item => item.id === $(`${kind}Profile`).value); }
function setKeyPlaceholder(kind, profile) { const input = $(`${kind}ApiKey`); input.value = ''; input.placeholder = profile?.api_key_set ? '••••••••（已保存在本机；留空保持）' : '尚未保存 Key'; }
function clearFetchedModels(kind = 'llm') { const select = $(`${kind}FetchedModels`); select.innerHTML = '<option value="">点击“拉取模型”后在这里选择</option>'; select.disabled = true; }
function renderFetchedModels(models, kind = 'llm') {
  const select = $(`${kind}FetchedModels`); const current = $(`${kind}Model`).value.trim(); select.innerHTML = '';
  const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = models.length ? `请选择模型（共 ${models.length} 个）` : '接口未返回模型'; select.appendChild(placeholder);
  models.forEach(model => { const option = document.createElement('option'); option.value = model; option.textContent = model; select.appendChild(option); });
  select.disabled = models.length === 0; select.value = models.includes(current) ? current : '';
}
function fillProvider(kind) {
  const profile = selectedProvider(kind);
  if (!profile) { if (['llm','embedding','rerank'].includes(kind)) { clearFetchedModels(kind); for (const suffix of ['Name','BaseUrl','Model']) $(`${kind}${suffix}`).value = ''; if (kind !== 'llm') $(`${kind}ModelsUrl`).value = ''; } setKeyPlaceholder(kind, null); providerState(kind, '尚无 Profile，请新建并保存', 'dirty'); return; }
  if (['llm','embedding','rerank'].includes(kind)) { $(`${kind}Name`).value = profile.name; $(`${kind}BaseUrl`).value = profile.base_url; $(`${kind}Model`).value = profile.model; if (kind !== 'llm') $(`${kind}ModelsUrl`).value = profile.models_url || ''; clearFetchedModels(kind); }
  if (kind === 'stt') { $('sttName').value = profile.name; $('sttEndpoint').value = profile.endpoint; $('sttStreamEndpoint').value = profile.stream_endpoint; $('sttResourceId').value = profile.resource_id; $('sttTwoPass').checked = profile.stream_two_pass !== false; }
  if (kind === 'tts') { $('ttsName').value = profile.name; $('ttsProviderType').value = profile.provider_type || 'http'; $('ttsEndpoint').value = profile.endpoint; $('ttsResourceId').value = profile.resource_id; $('ttsVoiceType').value = profile.voice_type; $('ttsEmotion').value = profile.emotion || ''; $('ttsEnableEmotion').checked = Boolean(profile.enable_emotion); $('ttsEmotionScale').value = profile.emotion_scale ?? 4; $('ttsSpeedRatio').value = profile.speed_ratio ?? 1; $('ttsRequestTemplate').value = JSON.stringify(profile.request_template || {}, null, 2); }
  setKeyPlaceholder(kind, profile);
  const active = ['llm','stt','tts'].includes(kind) && settings.provider_profiles[providerActiveKey(kind)] === profile.id;
  providerState(kind, active ? `当前全局启用：${profile.name}` : `已载入：${profile.name}`, active ? 'saved' : '');
}
function renderProviderProfiles(kind, selectedId = null) {
  const select = $(`${kind}Profile`); select.innerHTML = '';
  providerCollection(kind).forEach(profile => { const option = document.createElement('option'); option.value = profile.id; option.textContent = profile.name; select.appendChild(option); });
  select.value = selectedId || settings.provider_profiles[providerActiveKey(kind)] || providerCollection(kind)[0]?.id || '';
  fillProvider(kind);
  if (['embedding','rerank'].includes(kind)) renderMemoryVectorProfiles();
}
function renderAllProviderProfiles() { ['llm', 'tts', 'stt', 'embedding', 'rerank'].forEach(kind => renderProviderProfiles(kind)); }
function renderMemoryVectorProfiles() {
  for (const [purpose, id] of [['embedding', 'memoryEmbeddingProfile'], ['rerank', 'memoryRerankProfile']]) {
    const select = $(id), selected = select.value;
    select.replaceChildren();
    const empty = document.createElement('option'); empty.value = ''; empty.textContent = '未选择模型'; select.append(empty);
    providerCollection(purpose).forEach(p => {
      const option = document.createElement('option'); option.value = p.id; option.textContent = `${p.name} · ${p.model || '尚未填写模型名'}`; select.append(option);
    });
    select.value = selected;
  }
}
async function loadMemoryVectorModels() {
  const config = await providerApi('/api/role-memory/settings');
  if (['embedding','rerank'].some(kind => config[kind + '_profile_id'] && !providerCollection(kind).some(p => p.id === config[kind + '_profile_id']))) {
    settings.provider_profiles = await providerApi('/api/provider-profiles');
    ['embedding','rerank'].forEach(kind => renderProviderProfiles(kind));
  }
  renderMemoryVectorProfiles();
  $('memoryEmbeddingProfile').value = config.embedding_profile_id || '';
  $('memoryRerankProfile').value = config.rerank_profile_id || '';
  $('memoryVectorEnabled').checked = config.vector.enabled;
  $('memoryRerankEnabled').checked = config.vector.rerank_enabled;
  $('memoryVectorProviderState').textContent = '已读取当前记忆向量配置';
}
async function saveMemoryVectorModels() {
  const embedding = $('memoryEmbeddingProfile').value, rerank = $('memoryRerankProfile').value;
  const enabled = $('memoryVectorEnabled').checked, rerankEnabled = $('memoryRerankEnabled').checked;
  if (enabled && !embedding) throw new Error('请先选择向量化模型');
  if (rerankEnabled && (!enabled || !rerank)) throw new Error('启用精排需要启用向量召回并选择 Rerank 模型');
  const config = await providerApi('/api/role-memory/settings');
  config.embedding_profile_id = embedding || null; config.rerank_profile_id = rerank || null;
  config.vector.enabled = enabled; config.vector.rerank_enabled = rerankEnabled;
  await providerApi('/api/role-memory/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(config)});
  $('memoryVectorProviderState').textContent = '已保存，日记、系统记忆与外部世界书从下一轮使用此配置；更换模型后需更新已有冷记忆向量';
}
function memoryVectorAction(fn, stateId = 'memoryVectorProviderState') {
  return Promise.resolve().then(fn).then(() => { if (stateId !== 'memoryVectorProviderState') $(stateId).textContent = $('memoryVectorProviderState').textContent; }).catch(error => { $(stateId).textContent = error.message; });
}
async function providerApi(url, options = {}) { const response = await fetch(url, options); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Provider 操作失败'); return payload; }
async function activateProvider(kind, profileId) { if (!profileId) return; settings.provider_profiles = await providerApi(`/api/provider-profiles/active/${kind}/select`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }) }); renderProviderProfiles(kind, profileId); providerState(kind, '已切换，将从下一轮开始生效', 'saved'); }
function newProvider(kind) {
  const id = newIdentityId(id => providerCollection(kind).some(p => p.id === id));
  const defaults = ['embedding','rerank'].includes(kind) ? {id, name: kind === 'embedding' ? '新向量化模型' : '新 Rerank 模型', base_url:'', api_key:'', api_key_set:false, model:'', models_url:''} : kind === 'llm' ? { id, name: '新 LLM Profile', provider_type: 'openai_compatible', base_url: 'https://api.openai.com/v1', api_key: '', api_key_set: false, model: '' } : kind === 'stt' ? { id, name: '新 STT Profile', provider_type: 'volcengine', endpoint: 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream', stream_endpoint: 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async', resource_id: '', api_key: '', api_key_set: false, stream_two_pass: true } : { id, name: '新 TTS Profile', provider_type: 'websocket', endpoint: 'wss://openspeech.bytedance.com/api/v3/tts/bidirection', resource_id: 'seed-tts-2.0', api_key: '', api_key_set: false, voice_type: '', request_template: {}, emotion: '', enable_emotion: false, emotion_scale: 4, speed_ratio: 1 };
  providerCollection(kind).push(defaults); renderProviderProfiles(kind, id); providerState(kind, '新 Profile 尚未保存', 'dirty');
}
function providerPayload(kind) {
  const current = selectedProvider(kind); if (!current) throw new Error('请先新建 Profile');
  if (kind === 'llm') return { id: current.id, name: $('llmName').value.trim(), provider_type: 'openai_compatible', base_url: $('llmBaseUrl').value.trim(), api_key: $('llmApiKey').value, model: $('llmModel').value.trim() };
  if (['embedding','rerank'].includes(kind)) return {id:current.id, name:$(`${kind}Name`).value.trim(), base_url:$(`${kind}BaseUrl`).value.trim(), api_key:$(`${kind}ApiKey`).value, model:$(`${kind}Model`).value.trim(), models_url:$(`${kind}ModelsUrl`).value.trim()};
  if (kind === 'stt') return { id: current.id, name: $('sttName').value.trim(), provider_type: 'volcengine', endpoint: $('sttEndpoint').value.trim(), stream_endpoint: $('sttStreamEndpoint').value.trim(), resource_id: $('sttResourceId').value.trim(), api_key: $('sttApiKey').value, stream_two_pass: $('sttTwoPass').checked };
  let requestTemplate; try { requestTemplate = JSON.parse($('ttsRequestTemplate').value || '{}'); } catch { throw new Error('TTS Request Template 不是合法 JSON'); }
  return { id: current.id, name: $('ttsName').value.trim(), provider_type: $('ttsProviderType').value, endpoint: $('ttsEndpoint').value.trim(), resource_id: $('ttsResourceId').value.trim(), api_key: $('ttsApiKey').value, voice_type: $('ttsVoiceType').value.trim(), request_template: requestTemplate, emotion: $('ttsEmotion').value.trim(), enable_emotion: $('ttsEnableEmotion').checked, emotion_scale: Number($('ttsEmotionScale').value) || 4, speed_ratio: Number($('ttsSpeedRatio').value) || 1 };
}
async function persistProviderDraft(kind) {
  const payload = providerPayload(kind);
  providerState(kind, '正在保存当前配置…');
  settings.provider_profiles = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(payload.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  renderProviderProfiles(kind, payload.id);
  return payload.id;
}
async function saveProvider(kind) { const profileId = await persistProviderDraft(kind); if (['stt','tts'].includes(kind)) await activateProvider(kind, profileId); else providerState(kind, 'Profile 已保存', 'saved'); }
async function deleteProvider(kind) { const profile = selectedProvider(kind); if (!profile) return; settings.provider_profiles = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(profile.id)}`, { method: 'DELETE' }); renderProviderProfiles(kind); providerState(kind, '已删除；当前选择已更新', 'saved'); }
function formatProbe(result) { return Object.entries(result.stages || {}).map(([name, value]) => `${name}: ${value.status}${value.detail ? `（${value.detail}）` : ''}`).join('；'); }
async function testLlmConnection() {
  const profileId = await persistProviderDraft('llm');
  providerState('llm', '正在检查连接：GET /models，不调用模型生成…');
  const result = await providerApi(`/api/provider-profiles/llm/${encodeURIComponent(profileId)}/connection`, {method: 'POST'});
  if (result.ok) renderFetchedModels(result.models || []);
  providerState('llm', result.ok ? '连接检查成功：已获取模型列表；未调用模型，尚未验证生成能力' : formatProbe(result), result.ok ? 'saved' : 'dirty');
}
async function testProvider(kind) { const profileId = await persistProviderDraft(kind); providerState(kind, '正在执行真实最小请求…'); const result = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(profileId)}/test`, { method: 'POST' }); providerState(kind, formatProbe(result), result.ok ? 'saved' : 'dirty'); if (kind === 'tts' && result.audio_base64) playAudio({ audio_base64: result.audio_base64, audio_mime: result.audio_mime, latency: {} }); }
async function fetchModels(kind = 'llm') { const profileId = await persistProviderDraft(kind); providerState(kind, '正在请求 /models…'); const result = await providerApi(`/api/provider-profiles/${kind}/${encodeURIComponent(profileId)}/models`, { method: 'POST' }); if (result.ok) renderFetchedModels(result.models || [], kind); providerState(kind, result.ok ? `已拉取 ${result.models.length} 个模型名称；仅查询列表，未调用模型` : formatProbe(result), result.ok ? 'saved' : 'dirty'); }




// 供应商操作与页面初始化由本文件管理。
function openManagerPanel(panelId) {
  const panel = $(panelId);
  if (!panel || panel.open || panel.inert) return;
  panel.showModal();
  if (panelId === 'providerPanel') void memoryVectorAction(loadMemoryVectorModels);
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

$('closeLlmDebug').onclick = () => $('llmDebugDialog').close();
$('llmDebugDialog').onclick = event => { if (event.target === $('llmDebugDialog')) $('llmDebugDialog').close(); };
let historyPreviewTimer;
function historyRangeChanged() { toggleHistorySelection(); setHistoryDepthState('有未保存修改；保存前不会用于下一轮', 'dirty'); clearTimeout(historyPreviewTimer); historyPreviewTimer = setTimeout(() => void previewHistoryRange().catch(e => $('historyRangePreview').textContent = e.message), 250); }
$('historyDepth').oninput = historyRangeChanged;
$('historySince').oninput = historyRangeChanged;
$('historyMode').onchange = historyRangeChanged;
$('previewHistoryRange').onclick = () => void previewHistoryRange().catch(e => $('historyRangePreview').textContent = e.message);
$('saveHistoryDepth').onclick = () => void saveHistoryDepth().catch(error => setHistoryDepthState(error.message, 'dirty'));
$('promptPreset').onchange = event => { const next = event.target.value; if (promptDirty && !confirm('当前 Preset 有未保存修改，切换将丢弃这些修改。继续吗？')) { event.target.value = settings.prompt_presets.active_preset_id; return; } void activatePromptPreset(next).catch(error => { renderPromptPresets(settings.prompt_presets.active_preset_id); setPromptState(error.message, 'dirty'); }); };
$('captureKey').onclick = () => { capturingKey = true; $('captureKey').textContent = '请按下目标键…'; setKeyState('正在录制按键；按 Esc 取消', 'dirty'); $('captureKey').blur(); };
$('keyInput').onclick = () => $('captureKey').click();
$('saveKey').onclick = () => { key = pendingKey; localStorage.pttKey = key; $('keyInput').value = formatHotkey(key); setKeyState(`已保存并立即生效：${formatHotkey(key)}（无需重启）`, 'saved'); };
$('promptPresetName').oninput = () => { const preset = selectedPromptPreset(); if (preset) preset.name = $('promptPresetName').value; dirtyPrompt(); };
$('promptTemperature').oninput = () => { updatePromptTemperature(); dirtyPrompt(); };
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
$('saveVectorConfig').onclick = () => void saveVectorConfig().catch(error => setVectorConfigState(error.message, 'dirty'));
$('testVectorConfig').onclick = () => void testVectorConfig().catch(error => setVectorConfigState(error.message, 'dirty'));
$('fetchVectorModels').onclick = () => void fetchVectorModels('embedding').catch(error => setVectorConfigState(error.message, 'dirty'));
$('fetchVectorRerankModels').onclick = () => void fetchVectorModels('rerank').catch(error => setVectorConfigState(error.message, 'dirty'));
$('testVectorRerank').onclick = () => void testVectorRerank().catch(error => setVectorConfigState(error.message, 'dirty'));
$('vectorizeAllLibraries').onclick = () => void vectorizeAllLibraries().catch(error => { renderVectorMemory(); setVectorLibraryState(`批量向量化失败：${error.message}；已完成批次仍保留`, 'dirty'); });
$('vectorFetchedModels').onchange = event => { if (event.target.value) $('vectorModel').value = event.target.value; };
$('vectorFetchedRerankModels').onchange = event => { if (event.target.value) $('vectorRerankModel').value = event.target.value; };
$('vectorImportFile').onchange = event => { selectedVectorImportFile = event.target.files[0] || null; $('previewVectorImport').disabled = !selectedVectorImportFile; if (selectedVectorImportFile) setVectorLibraryState(`已选择：${selectedVectorImportFile.name}；点击“读取并预览”`, 'saved'); };
$('previewVectorImport').onclick = () => { if (selectedVectorImportFile) void previewVectorImport(selectedVectorImportFile).catch(error => setVectorLibraryState(`导入预览失败：${error.message}`, 'dirty')); };
$('confirmVectorImport').onclick = () => void confirmVectorImport().catch(error => { $('vectorImportReport').textContent += `\n\n导入失败：${error.message}`; });
$('closeVectorImport').onclick = () => { $('vectorImportDialog').close(); pendingVectorImport = null; };
$('vectorImportDialog').onclick = event => { if (event.target === $('vectorImportDialog')) { $('vectorImportDialog').close(); pendingVectorImport = null; } };
$('searchVectorChunks').onclick = () => void loadVectorChunks(0).catch(error => { $('vectorChunksSummary').textContent = error.message; });
$('vectorChunkSearch').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); void loadVectorChunks(0).catch(error => { $('vectorChunksSummary').textContent = error.message; }); } };
$('clearVectorChunkSearch').onclick = () => { $('vectorChunkSearch').value = ''; void loadVectorChunks(0).catch(error => { $('vectorChunksSummary').textContent = error.message; }); };
$('previousVectorChunks').onclick = () => void loadVectorChunks(Math.max(0, vectorChunkOffset - VECTOR_CHUNK_PAGE_SIZE)).catch(error => { $('vectorChunksSummary').textContent = error.message; });
$('nextVectorChunks').onclick = () => void loadVectorChunks(vectorChunkOffset + VECTOR_CHUNK_PAGE_SIZE).catch(error => { $('vectorChunksSummary').textContent = error.message; });
$('closeVectorChunks').onclick = () => { $('vectorChunksDialog').close(); inspectedVectorLibraryId = null; };
$('vectorChunksDialog').onclick = event => { if (event.target === $('vectorChunksDialog')) { $('vectorChunksDialog').close(); inspectedVectorLibraryId = null; } };
$('llmProfile').onchange = () => fillProvider('llm'); if ($('activateLlmProfile')) $('activateLlmProfile').onclick = () => void activateProvider('llm', $('llmProfile').value).catch(error => providerState('llm', error.message, 'dirty')); $('sttProfile').onchange = event => void activateProvider('stt', event.target.value).catch(error => providerState('stt', error.message, 'dirty')); $('ttsProfile').onchange = event => void activateProvider('tts', event.target.value).catch(error => providerState('tts', error.message, 'dirty'));
$('newLlmProfile').onclick = () => newProvider('llm'); $('newSttProfile').onclick = () => newProvider('stt'); $('newTtsProfile').onclick = () => newProvider('tts');
$('deleteLlmProfile').onclick = () => void deleteProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('deleteSttProfile').onclick = () => void deleteProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('deleteTtsProfile').onclick = () => void deleteProvider('tts').catch(error => providerState('tts', error.message, 'dirty'));
$('saveLlmProfile').onclick = () => void saveProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('saveSttProfile').onclick = () => void saveProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('saveTtsProfile').onclick = () => void saveProvider('tts').catch(error => providerState('tts', error.message, 'dirty'));
$('llmFetchedModels').onchange = event => { if (!event.target.value) return; $('llmModel').value = event.target.value; providerState('llm', `已选择模型：${event.target.value}；点击保存后从下一轮启用`, 'dirty'); };
$('llmModel').oninput = event => { const select = $('llmFetchedModels'); if (!select.disabled) select.value = [...select.options].some(option => option.value === event.target.value.trim()) ? event.target.value.trim() : ''; };
$('testLlmProfile').onclick = () => void testLlmConnection().catch(error => providerState('llm', error.message, 'dirty')); $('testLlmGeneration').onclick = () => void testProvider('llm').catch(error => providerState('llm', error.message, 'dirty')); $('testSttProfile').onclick = () => void testProvider('stt').catch(error => providerState('stt', error.message, 'dirty')); $('testTtsProfile').onclick = () => void testProvider('tts').catch(error => providerState('tts', error.message, 'dirty')); $('fetchLlmModels').onclick = () => void fetchModels().catch(error => providerState('llm', error.message, 'dirty'));
window.addEventListener('DOMContentLoaded', () => void load().catch(error => setConversationState(error.message, 'dirty')));

$('saveMemoryVectorModels').onclick = () => void memoryVectorAction(saveMemoryVectorModels);
$('reloadMemoryVectorModels').onclick = () => void memoryVectorAction(loadMemoryVectorModels);
for (const kind of ['embedding', 'rerank']) {
  const suffix = kind === 'embedding' ? 'Embedding' : 'Rerank';
  $('new' + suffix + 'Profile').onclick = () => newProvider(kind);
  $('delete' + suffix + 'Profile').onclick = () => void deleteProvider(kind).catch(e => providerState(kind, e.message, 'dirty'));
  $('save' + suffix + 'Profile').onclick = () => void saveProvider(kind).catch(e => providerState(kind, e.message, 'dirty'));
  $('fetch' + suffix + 'Models').onclick = () => void fetchModels(kind).catch(e => providerState(kind, e.message, 'dirty'));
  $('test' + suffix + 'Profile').onclick = () => void testProvider(kind).catch(e => providerState(kind, e.message, 'dirty'));
  $(kind + 'Profile').onchange = () => fillProvider(kind);
  $(kind + 'FetchedModels').onchange = event => { if (event.target.value) $(kind + 'Model').value = event.target.value; };
}

$('saveEmbeddingBinding').onclick = () => void memoryVectorAction(saveMemoryVectorModels, 'embeddingMemoryState');
