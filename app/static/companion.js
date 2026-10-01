// 与现有 Provider / Preset / 语音界面共用全局状态。
let characters = [];
let activeCharacterId = localStorage.activeCharacterId || 'default';
let editingCharacterId = null;
let pendingTextTurn = null;
let conversationPolling = false;
const localTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';

async function companionApi(url, body, method = 'GET') {
  const response = await fetch(url, {method, headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail || '请求失败'));
  return value;
}

function currentCharacter() { return characters.find(item => item.id === activeCharacterId); }
function currentConversation() { return conversations.find(item => item.id === activeConversationId); }

function characterOptions(select, rows, selected, fallback) {
  select.replaceChildren();
  if (fallback) select.add(new Option(fallback, ''));
  rows.forEach(row => select.add(new Option(row.name, row.id)));
  select.value = selected || '';
}

function renderCharacters() {
  characterOptions($('characterSelect'), characters, activeCharacterId);
}

function resetTurnDisplay() {
  saveLlmDebug(null);
  $('latencyInfo').textContent = '尚无本轮数据';
  $('searchTurnState').textContent = '';
  $('textInputState').textContent = 'Enter 发送 · Shift + Enter 换行';
}

async function loadConversations() {
  resetTurnDisplay();
  characters = await companionApi('/api/characters');
  if (!characters.some(item => item.id === activeCharacterId)) activeCharacterId = characters[0].id;
  renderCharacters();
  conversations = await companionApi(`/api/conversations?character_id=${encodeURIComponent(activeCharacterId)}`);
  if (!conversations.length) {
    const created = await companionApi('/api/conversations', {character_id: activeCharacterId, timezone: localTimezone()}, 'POST');
    conversations = [created];
  }
  const remembered = localStorage.getItem(`conversation:${activeCharacterId}`) || localStorage.activeConversationId;
  const active = conversations.find(item => item.id === remembered) || conversations[0];
  activeConversationId = active.id;
  await persistConversation(active.id, null, false);
  renderConversation();
  localStorage.activeCharacterId = activeCharacterId;
  localStorage.setItem(`conversation:${activeCharacterId}`, activeConversationId);
  setConversationState('会话由服务端自动保存', 'saved');
}

function renderConversationSelect() {
  characterOptions($('conversationSelect'), conversations, activeConversationId);
}

async function persistConversation(conversationId = activeConversationId, unused = null, showState = true) {
  if (!conversationId) return;
  const saved = await companionApi(`/api/conversations/${encodeURIComponent(conversationId)}`);
  if (saved.character_id !== activeCharacterId) return saved;
  const index = conversations.findIndex(item => item.id === saved.id);
  if (index >= 0) conversations[index] = saved; else conversations.unshift(saved);
  if (activeConversationId === saved.id && JSON.stringify(messages) !== JSON.stringify(saved.messages)) { messages = saved.messages; renderConversation(); }
  renderConversationSelect();
  if (showState) setConversationState(saved.pending_request_id ? '服务端正在生成，完成后会自动更新' : '已读取服务端保存的记录', 'saved');
  return saved;
}

async function createConversation() {
  const created = await companionApi('/api/conversations', {character_id: activeCharacterId, timezone: localTimezone()}, 'POST');
  conversations.unshift(created);
  activeConversationId = created.id;
  messages = [];
  pendingTextTurn = null;
  conversationExpanded = false;
  localStorage.setItem(`conversation:${activeCharacterId}`, created.id);
  resetTurnDisplay();
  renderConversationSelect(); renderConversation();
  setConversationState(`已新建 ${currentCharacter()?.name || ''} 的会话`, 'saved');
}

async function switchConversation(id) {
  if (!id || id === activeConversationId) return;
  activeConversationId = id;
  pendingTextTurn = null;
  conversationExpanded = false;
  localStorage.setItem(`conversation:${activeCharacterId}`, id);
  resetTurnDisplay();
  await persistConversation(id);
}

function usageLabel(usage) {
  const format = value => Number.isInteger(value) ? value.toLocaleString() : '—';
  return `Input ${format(usage?.input_tokens)} · Cache ${format(usage?.cached_tokens)} · Output ${format(usage?.output_tokens)}`;
}

function messageNode(role, content, message = {}) {
  const item = document.createElement('div');
  item.className = `message ${role}`;
  const label = document.createElement('div'); label.className = 'message-meta';
  label.textContent = `${role === 'user' ? currentCharacter()?.user_name || '你' : currentCharacter()?.name || 'Assistant'}${message.source === 'heartbeat' ? ' · 主动消息' : ''} · ${message.local_datetime ? new Date(message.timestamp).toLocaleString() : '时间未知'}`;
  const body = document.createElement('div'); body.className = 'message-body'; body.textContent = content;
  item.append(label, body);
  if (role === 'assistant') {
    const usage = document.createElement('div'); usage.className = 'message-usage'; usage.textContent = usageLabel(message.usage); item.append(usage);
    if (message.request_id) {
      const details = document.createElement('details'); details.className = 'message-request';
      const summary = document.createElement('summary'); summary.textContent = '用量明细';
      const info = document.createElement('div'); info.className = 'hint';
      details.append(summary, info); item.append(details);
      details.addEventListener('toggle', async () => {
        if (!details.open || info.textContent) return;
        try {
          const record = await companionApi(`/api/conversations/${activeConversationId}/requests/${encodeURIComponent(message.request_id)}`);
          info.textContent = `回复：${usageLabel(record.usage)}` + (record.extra_usage || []).map(row => `\n搜索判断：${usageLabel(row.usage)}`).join('');
        } catch (error) { info.textContent = error.message; }
      });
    }
  }
  if (message.sources?.length) {
    const sources = document.createElement('div'); sources.className = 'message-sources';
    message.sources.forEach((source, index) => {
      try { const url = new URL(source.url); if (!['https:', 'http:'].includes(url.protocol)) return; }
      catch { return; }
      const link = document.createElement('a'); link.href = source.url; link.textContent = `${index + 1}. ${source.title}`; link.target = '_blank'; link.rel = 'noopener noreferrer'; sources.append(link);
    }); item.append(sources);
  }
  return item;
}

function renderConversation() {
  $('chat').replaceChildren();
  const visible = conversationExpanded ? messages : messages.slice(-12);
  [...visible].reverse().forEach(message => $('chat').append(messageNode(message.role, message.content, message)));
  $('conversationSummary').textContent = `共 ${messages.length} 条 · 服务端自动保存 · 最新在前`;
  $('toggleConversation').hidden = messages.length <= 12;
  $('toggleConversation').textContent = conversationExpanded ? '收起' : `展开全部（${messages.length} 条）`;
}

function setConversationControlsDisabled(disabled) {
  ['conversationSelect', 'newConversation', 'saveConversation', 'clearConversation', 'characterSelect'].forEach(id => $(id).disabled = disabled);
}

function setConfigurationControlsDisabled(disabled) {
  ['contextSettingsPanel', 'promptPanel', 'lorebookPanel', 'vectorPanel', 'providerPanel', 'characterPanel', 'searchPanel', 'heartbeatPanel'].forEach(id => $(id).inert = disabled);
  $('searchMode').disabled = disabled;
}

function renderSearchTurn(payload) {
  const labels = {off: '本轮未搜索', unconfigured: '搜索服务未启用', not_needed: '模型判断本轮无需搜索', searched: `已搜索，${payload.sources?.length || 0} 个来源`, empty: '搜索完成，没有找到结果', failed: '搜索失败'};
  $('searchTurnState').textContent = (labels[payload.status] || '') + (payload.warning ? ` · ${payload.warning}` : '');
}

async function consumeEvents(response, consume) {
  if (!response.ok) { const failure = await response.json(); throw new Error(typeof failure.detail === 'string' ? failure.detail : '发送失败'); }
  const reader = response.body.getReader();
  const decoder = new TextDecoder(); let buffer = '';
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      const frames = buffer.split('\n\n'); buffer = frames.pop() || '';
      for (const frame of frames) {
        const line = frame.split('\n').find(item => item.startsWith('data: '));
        if (line) await consume(JSON.parse(line.slice(6)));
      }
      if (done) return;
    }
  } finally { reader.releaseLock(); }
}

async function sendTypedText() {
  if (recording || processing || startPromise || finishPromise) return;
  const content = $('textInput').value.trim(); if (!content) return;
  const cid = activeConversationId;
  const mode = $('searchMode').value;
  if (!pendingTextTurn || pendingTextTurn.cid !== cid || pendingTextTurn.content !== content || pendingTextTurn.search_mode !== mode) {
    pendingTextTurn = {cid, request_id: crypto.randomUUID(), content, timezone: localTimezone(), search_mode: mode};
  }
  processing = true;
  setConversationControlsDisabled(true); setConfigurationControlsDisabled(true); setTextInputControlsDisabled(true);
  $('textInputState').textContent = '正在发送…';
  let assistantNode = null; let delta = ''; let completed = false;
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(cid)}/messages/stream`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pendingTextTurn)});
    await consumeEvents(response, payload => {
      if (payload.type === 'state') status(payload.state);
      if (payload.type === 'search') renderSearchTurn(payload);
      if (payload.type === 'transcript') addMessage('user', payload.text);
      if (payload.type === 'delta') {
        delta += payload.text;
        if (!assistantNode) { assistantNode = messageNode('assistant', ''); $('chat').prepend(assistantNode); }
        assistantNode.querySelector('.message-body').textContent = delta;
      }
      if (payload.type === 'error') throw new Error(payload.detail);
      if (payload.type === 'complete') {
        completed = true; messages = payload.messages; renderConversation(); saveLlmDebug(payload.debug);
        $('latencyInfo').textContent = usageLabel(payload.usage) + (payload.extra_usage?.length ? ` · 搜索判断另有 ${payload.extra_usage.length} 次模型调用（可在请求记录中查看）` : '');
        if (payload.search) renderSearchTurn({...payload.search, sources: payload.assistant_message?.sources});
      }
    });
    if (!completed) throw new Error('连接提前结束；服务端可能仍在生成，可刷新记录或重试');
    $('textInput').value = ''; pendingTextTurn = null;
    $('textInputState').textContent = '回复已由服务端保存'; status('Idle');
  } catch (error) {
    $('textInputState').textContent = `${error.message}；原文已保留，再次发送会复用同一请求。`;
    status('Error');
  } finally {
    await persistConversation(cid, null, false).catch(() => {});
    processing = false;
    setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false);
  }
}

function editCharacter(character) {
  editingCharacterId = character.id || null;
  const fields = {characterName: 'name', characterSystem: 'system_prompt', characterPersonality: 'personality', characterBackground: 'background', characterRelationship: 'relationship', characterStyle: 'speaking_style', characterUserName: 'user_name', characterPersona: 'persona'};
  Object.entries(fields).forEach(([id, key]) => $(id).value = character[key] || '');
  characterOptions($('characterPreset'), settings.prompt_presets.presets, character.preset_id, '跟随当前预设');
  characterOptions($('characterLorebook'), settings.lorebooks.lorebooks, character.lorebook_id, '跟随当前世界书');
  characterOptions($('characterLlm'), settings.provider_profiles.llm_profiles.filter(p => (p.purpose || 'chat') === 'chat'), character.llm_profile_id, '跟随当前 LLM');
  characterOptions($('characterTts'), settings.provider_profiles.tts_profiles, character.tts_profile_id, '跟随当前 TTS');
  $('characterState').textContent = character.id ? '正在编辑当前角色' : '新角色尚未保存';
}

async function saveCharacter() {
  const value = {name: $('characterName').value, system_prompt: $('characterSystem').value, personality: $('characterPersonality').value, background: $('characterBackground').value, relationship: $('characterRelationship').value, speaking_style: $('characterStyle').value, user_name: $('characterUserName').value || '用户', persona: $('characterPersona').value, preset_id: $('characterPreset').value || null, lorebook_id: $('characterLorebook').value || null, llm_profile_id: $('characterLlm').value || null};
  value.tts_profile_id = $('characterTts').value || null;
  const saved = await companionApi(editingCharacterId ? `/api/characters/${editingCharacterId}` : '/api/characters', value, editingCharacterId ? 'PUT' : 'POST');
  activeCharacterId = saved.id; await loadConversations(); editCharacter(saved);
  $('characterState').textContent = '已保存；从下一轮生效';
}

function updateSearchProviderFields() {
  const provider = $('searchProvider').value;
  $('searchTavilyFields').hidden = provider !== 'tavily';
  $('searchCustomFields').hidden = provider !== 'custom';
  $('searchCustomHelp').hidden = provider !== 'custom';
  $('searchVolcengineFields').hidden = provider !== 'volcengine';
  $('searchVolcengineHelp').hidden = provider !== 'volcengine';
  $('searchAdvancedFields').hidden = !['custom', 'volcengine'].includes(provider);
  $('searchAdvancedTitle').textContent = provider === 'volcengine' ? '豆包额外参数' : '自定义 HTTP 协议';
}
async function loadSearch() {
  const value = await companionApi('/api/search/settings');
  $('searchEnabled').checked = value.enabled; $('searchProvider').value = value.provider; $('searchEndpoint').value = value.endpoint;
  $('searchApiKey').value = ''; $('searchMaxResults').value = value.max_results; $('searchDepth').value = value.search_depth;
  $('searchMethod').value = value.request_method || 'POST';
  $('searchTemplate').value = JSON.stringify(value.request_template || {}, null, 2);
  $('searchExtraBody').value = JSON.stringify(value.extra_body || {}, null, 2);
  for (const [id, key] of Object.entries({searchAuthHeader:'auth_header', searchAuthPrefix:'auth_prefix', searchResultsPath:'results_path', searchTitlePath:'title_path', searchUrlPath:'url_path', searchContentPath:'content_path'})) $(id).value = value[key] ?? '';
  updateSearchProviderFields();
  $('searchState').textContent = value.api_key_set ? '已有 API Key，页面不回读' : '尚未设置 API Key';
}

async function loadHeartbeat() {
  const conversation = await persistConversation(activeConversationId, null, false); const value = conversation.heartbeat;
  $('heartbeatConversation').textContent = `${currentCharacter()?.name} · ${conversation.name} · ${conversation.timezone}`;
  $('heartbeatEnabled').checked = value.enabled; $('heartbeatInterval').value = value.interval_minutes;
  $('heartbeatCooldown').value = value.cooldown_minutes; $('heartbeatDailyMax').value = value.max_messages_per_day;
  $('heartbeatQuiet').checked = value.quiet_enabled; $('heartbeatQuietStart').value = value.quiet_start; $('heartbeatQuietEnd').value = value.quiet_end;
  $('heartbeatState').textContent = conversation.next_heartbeat_at ? `下次检查：${new Date(conversation.next_heartbeat_at).toLocaleString()}` : '未启用';
  await loadHeartbeatLogs();
}

async function loadHeartbeatLogs() {
  const rows = await companionApi(`/api/conversations/${activeConversationId}/heartbeat/logs`); $('heartbeatLogs').replaceChildren();
  if (!rows.length) $('heartbeatLogs').textContent = '尚无模型检查记录（冷却、静默等跳过检查不会调用模型）';
  rows.forEach(row => {
    const item = document.createElement('details'); item.className = 'heartbeat-log';
    const result = row.result ? JSON.parse(row.result) : {};
    const debug = result.debug || {};
    const state = debug.prompt_trace?.companion_state;
    const summary = document.createElement('summary');
    const action = {NO_ACTION: '保持安静', SEND_MESSAGE: '已主动联系', EXPLORE: '选择自主外出（结果见自主外出记录）'}[result.action] || row.status;
    summary.textContent = `${new Date(row.started_at).toLocaleString()} · ${action}${row.error ? ' · ' + row.error : ''}${row.usage ? ' · ' + usageLabel(JSON.parse(row.usage)) : ''} · ${result.latency_seconds ?? (row.finished_at ? ((new Date(row.finished_at) - new Date(row.started_at)) / 1000).toFixed(2) : '—')} 秒`;
    item.append(summary);
    const reason = document.createElement('p'); reason.textContent = state ? state.decision_mode === 'model' ? '由模型结合当前情绪、关系、聊天与时间自主判断（无触发阈值）' : `${state.reason}；旧版行动值 ${state.desire_to_act} / 阈值 ${state.threshold}` : '旧记录未保存状态快照'; item.append(reason);
    for (const [title, value] of [['发送给模型的完整消息', debug.llm_messages], ['模型原始返回', debug.llm_raw], ['上下文编译与状态', debug.prompt_trace]]) {
      const heading = document.createElement('strong'); heading.textContent = title;
      const pre = document.createElement('pre'); pre.textContent = value == null ? '此记录无数据' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
      item.append(heading, pre);
    }
    $('heartbeatLogs').append(item);
  });
}

function reportTo(id, action) { return () => void action().catch(error => $(id).textContent = error.message); }
$('characterSelect').onchange = reportTo('conversationState', async () => { activeCharacterId = $('characterSelect').value; pendingTextTurn = null; saveLlmDebug(null); await loadConversations(); });
$('newCharacter').onclick = () => editCharacter({name: '新角色', user_name: '用户'});
$('copyCharacter').onclick = () => editCharacter({...currentCharacter(), id: '', name: `${currentCharacter().name} 副本`});
$('saveCharacter').onclick = reportTo('characterState', saveCharacter);
$('deleteCharacter').onclick = reportTo('characterState', async () => { if (!editingCharacterId) return; await companionApi(`/api/characters/${editingCharacterId}`, null, 'DELETE'); activeCharacterId = 'default'; await loadConversations(); editCharacter(currentCharacter()); });
$('saveConversation').onclick = reportTo('conversationState', () => persistConversation());
$('clearConversation').onclick = reportTo('conversationState', createConversation);
$('searchProvider').onchange = () => { const endpoints = {tavily:'https://api.tavily.com/search', searxng:'http://127.0.0.1:8080/search', volcengine:'https://open.feedcoopapi.com/search_api/web_search'}; if (endpoints[$('searchProvider').value]) $('searchEndpoint').value = endpoints[$('searchProvider').value]; updateSearchProviderFields(); };
$('saveSearch').onclick = reportTo('searchState', async () => {
  await companionApi('/api/search/settings', {enabled: $('searchEnabled').checked, provider: $('searchProvider').value, endpoint: $('searchEndpoint').value, api_key: $('searchApiKey').value, max_results: Number($('searchMaxResults').value), search_depth: $('searchDepth').value, request_method: $('searchMethod').value, request_template: JSON.parse($('searchTemplate').value || '{}'), extra_body: JSON.parse($('searchExtraBody').value || '{}'), auth_header: $('searchAuthHeader').value, auth_prefix: $('searchAuthPrefix').value, results_path: $('searchResultsPath').value, title_path: $('searchTitlePath').value, url_path: $('searchUrlPath').value, content_path: $('searchContentPath').value}, 'PUT');
  await loadSearch(); $('searchState').textContent = '搜索配置已保存';
});
$('testSearch').onclick = reportTo('searchState', async () => { $('searchState').textContent = '正在测试…'; const value = await companionApi('/api/search/test', {}, 'POST'); $('searchState').textContent = `查询成功，返回 ${value.results.length} 个来源`; });
$('saveHeartbeat').onclick = reportTo('heartbeatState', async () => {
  await companionApi(`/api/conversations/${activeConversationId}/heartbeat`, {enabled: $('heartbeatEnabled').checked, interval_minutes: Number($('heartbeatInterval').value), cooldown_minutes: Number($('heartbeatCooldown').value), max_messages_per_day: Number($('heartbeatDailyMax').value), quiet_enabled: $('heartbeatQuiet').checked, quiet_start: Number($('heartbeatQuietStart').value), quiet_end: Number($('heartbeatQuietEnd').value)}, 'PUT');
  await loadHeartbeat();
});
$('checkHeartbeat').onclick = reportTo('heartbeatState', async () => { const value = await companionApi(`/api/conversations/${activeConversationId}/heartbeat/check`, {}, 'POST'); $('heartbeatState').textContent = value.status === 'skipped' ? `跳过：${value.reason}` : '正在检查；结果会自动保存，稍后刷新记录'; });
$('refreshHeartbeatLogs').onclick = reportTo('heartbeatState', loadHeartbeatLogs);

document.querySelectorAll('[data-open-panel]').forEach(button => button.addEventListener('click', () => {
  const id = button.dataset.openPanel;
  if (id === 'characterPanel') editCharacter(currentCharacter());
  if (id === 'searchPanel') void loadSearch().catch(error => $('searchState').textContent = error.message);
  if (id === 'heartbeatPanel') void loadHeartbeat().catch(error => $('heartbeatState').textContent = error.message);
}));
setInterval(async () => {
  if (!activeConversationId || processing || recording || startPromise || finishPromise || conversationPolling) return;
  conversationPolling = true;
  try { await persistConversation(activeConversationId, null, false); }
  catch (error) { setConversationState(`连接暂不可用：${error.message}`, 'dirty'); }
  finally { conversationPolling = false; }
}, 3000);
