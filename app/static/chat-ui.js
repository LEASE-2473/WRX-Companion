// 2.0 文字主界面；复用 WRX 的配置编辑器与语音适配器。
let activeTextRequest = null;
$('stopText').addEventListener('click', async () => {
  const turn = activeTextRequest;
  if (!turn) return;
  $('stopText').disabled = true;
  $('textInputState').textContent = '正在停止…';
  try {
    await companionApi(`/api/conversations/${encodeURIComponent(turn.cid)}/requests/${encodeURIComponent(turn.request_id)}/cancel`, {}, 'POST');
  } catch (error) {
    $('textInputState').textContent = `停止失败：${error.message}；可再次点击停止`;
  } finally {
    $('stopText').disabled = false;
  }
});
let editingMessage = null;
let speakingMessage = null;
let speechObjectUrl = null;
let speechBusy = false;
let selectedSpeechMessage = null;
let stickToBottom = true;
let draftImages = [];
let imageReading = false;
let draftConversationId = null;
function renderImages(container, images, removable = false) {
  for (const [index, url] of images.entries()) {
    const item = document.createElement('div'); item.className = 'image-item';
    const img = document.createElement('img'); img.src = url; img.alt = `图片 ${index + 1}`;
    img.onload = scrollChat; item.append(img);
    if (removable) {
      const remove = document.createElement('button'); remove.textContent = '×'; remove.setAttribute('aria-label', `移除图片 ${index + 1}`);
      remove.disabled = processing; remove.onclick = () => { draftImages.splice(index, 1); renderDraftImages(); }; item.append(remove);
    } else { const link = document.createElement('a'); link.href = url; link.download = `image-${index + 1}`; link.append(img); item.replaceChildren(link); }
    container.append(item);
  }
}
function renderDraftImages() { $('imageDrafts').replaceChildren(); renderImages($('imageDrafts'), draftImages, true); }
async function addImageFiles(files) {
  if (processing || imageReading) return;
  imageReading = true;
  const imageConversation = activeConversationId;
  try {
    const selected = Array.from(files);
    if (draftImages.length + selected.length > 4) throw new Error('每轮最多 4 张图片');
    const added = [];
    for (const file of selected) {
      if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)) throw new Error('只支持 PNG、JPEG、WebP、GIF');
      if (!file.size || file.size > 5 * 1024 * 1024) throw new Error('每张图片最多 5 MB');
      added.push(await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file); }));
    }
    if (imageConversation !== activeConversationId) return;
    draftImages.push(...added); renderDraftImages(); $('textInputState').textContent = '图片已添加，可以直接发送或补充文字';
  } catch (error) { $('textInputState').textContent = error.message; }
  finally { imageReading = false; $('imageInput').value = ''; }
}
$('attachImages').onclick = () => $('imageInput').click();
$('imageInput').onchange = () => void addImageFiles($('imageInput').files);
$('textInput').addEventListener('paste', event => {
  const files = Array.from(event.clipboardData?.items || []).filter(item => item.kind === 'file' && item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
  if (files.length) { event.preventDefault(); void addImageFiles(files); }
});

function scrollChat() { if (stickToBottom) $('chatScroll').scrollTop = $('chatScroll').scrollHeight; }
$('chatScroll').onscroll = () => { const el = $('chatScroll'); stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 90; };

function renderConversationSelect() {
  if (draftConversationId !== activeConversationId) { draftImages = []; renderDraftImages(); draftConversationId = activeConversationId; }
  characterOptions($('conversationSelect'), conversations, activeConversationId);
  $('conversationList').replaceChildren();
  conversations.forEach(conversation => {
    const button = document.createElement('button');
    button.className = 'conversation-link' + (conversation.id === activeConversationId ? ' selected' : '');
    button.textContent = (conversation.parent_conversation_id ? '⑂ ' : '') + conversation.name;
    button.title = conversation.name;
    button.setAttribute('aria-current', String(conversation.id === activeConversationId));
    button.disabled = processing || recording;
    button.onclick = reportTo('conversationState', async () => { stickToBottom = true; await switchConversation(conversation.id); document.body.classList.remove('sidebar-open'); });
    const row = document.createElement('div'); row.className = 'conversation-row';
    const remove = document.createElement('button'); remove.className = 'conversation-delete'; remove.textContent = '×'; remove.title = '删除对话'; remove.setAttribute('aria-label', `删除对话：${conversation.name}`); remove.disabled = processing || recording;
    remove.onclick = reportTo('conversationState', async () => {
      if (!confirm(`删除“${conversation.name}”？消息将永久删除，已有分支会保留。`)) return;
      await companionApi(`/api/conversations/${conversation.id}`, null, 'DELETE');
      conversations = conversations.filter(item => item.id !== conversation.id);
      localStorage.removeItem(`conversation:${activeCharacterId}`);
      if (activeConversationId === conversation.id) {
        activeConversationId = null;
        if (conversations.length) await switchConversation(conversations[0].id);
        else await createConversation();
      }
      await loadConversations();
    });
    row.append(button, remove); $('conversationList').append(row);
  });
  void refreshCompanionState();
  const conversation = currentConversation();
  $('chatTitle').textContent = currentCharacter()?.name || '温柔乡';
  $('chatSubtitle').replaceChildren();
  if (conversation?.parent_conversation_id) {
    const back = document.createElement('button'); back.className = 'parent-link'; back.textContent = '⑂ 当前为分支 · 返回原对话';
    back.onclick = reportTo('conversationState', () => switchConversation(conversation.parent_conversation_id));
    $('chatSubtitle').append(back);
  } else $('chatSubtitle').textContent = '慢慢说，我在听。';
}

// 用 DOM 构建常用 Markdown，模型文本永不作为 HTML 执行。
const NEXT_MESSAGE = '<|next_message|>';
function splitReplyMessages(text, streaming = false) {
  if (streaming) {
    for (let size = NEXT_MESSAGE.length - 1; size > 0; size--) {
      if (text.endsWith(NEXT_MESSAGE.slice(0, size))) { text = text.slice(0, -size); break; }
    }
  }
  return text.split(NEXT_MESSAGE).map(part => part.trim()).filter(Boolean);
}
function renderMessageText(node, text, splitMessages = false, streaming = false) {
  if (splitMessages) {
    node.replaceChildren();
    for (const part of splitReplyMessages(text, streaming)) {
      const block = document.createElement('div'); block.className = 'reply-part';
      renderMessageText(block, part); node.append(block);
    }
    return;
  }
  node.replaceChildren();
  let code = null;
  for (const line of text.split('\n')) {
    if (line.startsWith('```')) {
      if (code) code = null;
      else { const pre = document.createElement('pre'); code = document.createElement('code'); pre.append(code); node.append(pre); }
      continue;
    }
    if (code) { code.append(document.createTextNode(line + '\n')); continue; }
    const row = document.createElement('div'); row.className = 'text-line';
    const chunks = line.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g);
    for (const chunk of chunks) {
      if (chunk.startsWith('**') && chunk.endsWith('**')) { const strong = document.createElement('strong'); strong.textContent = chunk.slice(2, -2); row.append(strong); }
      else if (chunk.startsWith('`') && chunk.endsWith('`')) { const inline = document.createElement('code'); inline.textContent = chunk.slice(1, -1); row.append(inline); }
      else {
        const match = chunk.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
        if (match) { const link = document.createElement('a'); link.textContent = match[1]; link.href = match[2]; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link); }
        else row.append(document.createTextNode(chunk));
      }
    }
    if (!line) row.append(document.createElement('br'));
    node.append(row);
  }
}

const baseMessageNode = messageNode;
function chatMessageNode(role, content, message = {}) {
  const node = baseMessageNode(role, content, message);
  renderMessageText(node.querySelector('.message-body'), content, role === 'assistant');
  node.querySelectorAll('.message-usage, .message-request').forEach(el => el.remove());
  const sources = node.querySelector('.message-sources');
  if (sources) {
    const details = document.createElement('details'); details.className = 'message-search';
    const summary = document.createElement('summary'); summary.textContent = '[联网搜索]';
    sources.replaceWith(details); details.append(summary, sources);
  }
  if (message.images?.length) { const gallery = document.createElement('div'); gallery.className = 'message-images'; renderImages(gallery, message.images); node.querySelector('.message-body').append(gallery); }
  if (!message.id) return node;
  const actions = document.createElement('div'); actions.className = 'message-actions';
  const state = document.createElement('span'); state.className = 'message-action-state'; state.setAttribute('role', 'status');
  const operation = (label, action) => {
    const button = document.createElement('button'); button.textContent = label; button.disabled = processing;
    button.onclick = () => void action().catch(error => state.textContent = error.message);
    return button;
  };
  if (role === 'assistant') {
    actions.append(operation('▷ 朗读', () => playStoredMessage(message, null, state)));
    actions.append(operation('音色', async () => {
      selectedSpeechMessage = {message, cid: activeConversationId};
      characterOptions($('messageVoiceProfile'), settings.provider_profiles.tts_profiles, currentCharacter()?.tts_profile_id || settings.provider_profiles.active_tts_profile_id, '使用角色默认音色');
      $('messageVoiceState').textContent = ''; $('messageVoicePanel').showModal();
    }));
  }
  const menu = document.createElement('details'); menu.className = 'message-menu';
  const summary = document.createElement('summary'); summary.textContent = '更多 ···';
  const options = document.createElement('div'); options.className = 'message-menu-options';
  if (role === 'user') {
    const beginEdit = async (regenerate) => {
      if (processing || recording) throw new Error('请等待当前一轮完成');
      if (document.querySelector('.message-inline-editor')) throw new Error('请先保存或取消正在编辑的消息');
      const cid = activeConversationId;
      const body = node.querySelector('.message-body');
      const editor = document.createElement('textarea'); editor.className = 'message-inline-editor';
      editor.value = message.content; editor.setAttribute('aria-label', '编辑用户消息正文');
      body.replaceChildren(editor);
      if (message.images?.length) { const gallery = document.createElement('div'); gallery.className = 'message-images'; renderImages(gallery, message.images); body.append(gallery); }
      const resize = () => { editor.style.height = 'auto'; editor.style.height = `${editor.scrollHeight + 2}px`; };
      editor.oninput = resize;
      const controls = document.createElement('div'); controls.className = 'message-edit-controls';
      const restore = () => { renderMessageText(body, message.content); if (message.images?.length) { const gallery = document.createElement('div'); gallery.className = 'message-images'; renderImages(gallery, message.images); body.append(gallery); } actions.append(state); controls.remove(); actions.hidden = false; };
      const save = operation(regenerate ? '保存并重新生成' : '保存', async () => {
        if (cid !== activeConversationId || processing || recording) throw new Error('当前对话已变化或正在生成');
        const content = editor.value;
        if (!content.trim() && !message.images?.length) throw new Error('消息不能为空');
        save.disabled = true; cancel.disabled = true; editor.disabled = true;
        try {
          if (regenerate) {
            await sendTypedText({content, images: message.images || [], resend_mid: message.id});
            if (document.contains(editor)) { editor.disabled = false; save.disabled = false; cancel.disabled = false; }
          } else {
            const updated = await companionApi(`/api/conversations/${encodeURIComponent(cid)}/messages/${encodeURIComponent(message.id)}`, {content}, 'PATCH');
            Object.assign(message, updated); pendingTextTurn = null; restore(); state.textContent = '已保存';
          }
        } catch (error) { editor.disabled = false; save.disabled = false; cancel.disabled = false; throw error; }
      });
      const cancel = operation('取消', async () => restore());
      controls.append(save, cancel, state); node.append(controls); actions.hidden = true;
      editor.onkeydown = event => { if (event.key === 'Escape') { event.preventDefault(); restore(); } };
      editor.focus(); resize();
    };
    actions.append(operation('✎ 编辑', () => beginEdit(false)), operation('✎↻ 编辑并重新生成', () => beginEdit(true)));
  } else {
  options.append(operation(role === 'user' ? '编辑并重新发送' : '编辑回复', async () => {
    editingMessage = {message, cid: activeConversationId};
    $('messageEditTitle').textContent = role === 'user' ? '编辑并重新发送' : '编辑 AI 回复';
    $('resendMessageEdit').hidden = role !== 'user';
    $('messageEditContent').value = message.content; $('messageEditState').textContent = '';
    $('messageEditPanel').showModal(); menu.open = false;
  }));
  }
  options.append(operation('⑂ 开分支', () => createMessageBranch(message, 'branch')));
  const index = messages.findIndex(m => m.id === message.id);
  if (role === 'assistant' && message.source !== 'heartbeat' && messages[index - 1]?.role === 'user') {
    actions.append(operation('重新生成', () => sendTypedText({content: messages[index - 1].content, regenerate_mid: message.id})));
    options.append(operation('重新生成到分支', () => createMessageBranch(message, 'regenerate')));
  }
  options.append(operation('⧉ 复制正文', async () => { await navigator.clipboard.writeText(role === 'assistant' ? splitReplyMessages(message.content).join('\n\n') : message.content); state.textContent = '已复制'; menu.open = false; }));
  menu.append(summary, options); actions.append(menu, state); node.append(actions);
  return node;
}
messageNode = chatMessageNode;

function renderConversation() {
  void refreshCompanionState(true);
  $('chat').replaceChildren();
  if (!messages.length) {
    const empty = document.createElement('div'); empty.className = 'chat-empty';
    const symbol = document.createElement('div'); symbol.className = 'empty-symbol'; symbol.textContent = '乡';
    const title = document.createElement('h2'); title.textContent = `和${currentCharacter()?.name || '她'}，从这里开始。`;
    const description = document.createElement('p'); description.textContent = '说说今天发生的事，或继续一个你喜欢的话题。';
    empty.append(symbol, title, description); $('chat').append(empty);
  }
  messages.forEach(message => $('chat').append(messageNode(message.role, message.content, message)));
  $('conversationSummary').textContent = `${messages.length} 条消息 · 自动保存`;
  renderComposerUsage();
  $('toggleConversation').hidden = true;
  scrollChat();
}

function renderComposerUsage() {
  const latest = messages.filter(message => message.role === 'assistant').at(-1);
  $('composerUsage').textContent = usageLabel(latest?.usage);
}

function addMessage(role, content) {
  $('chat').querySelector('.chat-empty')?.remove();
  const node = messageNode(role, content); $('chat').append(node); scrollChat(); return node;
}

function setConversationControlsDisabled(disabled) {
  ['conversationSelect', 'newConversation', 'saveConversation', 'clearConversation', 'characterSelect'].forEach(id => $(id).disabled = disabled);
  $('attachImages').disabled = disabled; $('imageInput').disabled = disabled;
  document.querySelectorAll('#imageDrafts button, .conversation-link, .conversation-delete, .message-actions button, .parent-link, [data-open-panel]').forEach(button => button.disabled = disabled);
}

async function sendTypedText(override = null) {
  if (recording || processing || startPromise || finishPromise) { $('textInputState').textContent = '当前一轮尚未结束，请稍后发送'; return; }
  if (imageReading) { $('textInputState').textContent = '图片正在读取，请稍后发送'; return; }
  const content = override ? override.content : $('textInput').value.trim();
  const images = override ? (override.images || []) : [...draftImages]; if (!content && !images.length && !override?.regenerate_mid) return;
  const cid = activeConversationId; const mode = $('searchMode').value;
  if (!pendingTextTurn || pendingTextTurn.cid !== cid || pendingTextTurn.content !== content || pendingTextTurn.search_mode !== mode || pendingTextTurn.regenerate_mid !== override?.regenerate_mid || pendingTextTurn.resend_mid !== override?.resend_mid || JSON.stringify(pendingTextTurn.images || []) !== JSON.stringify(images)) {
    pendingTextTurn = {cid, request_id: crypto.randomUUID(), content, images, timezone: localTimezone(), search_mode: mode, regenerate_mid: override?.regenerate_mid, resend_mid: override?.resend_mid};
  }
  processing = true; stickToBottom = true;
  activeTextRequest = {...pendingTextTurn}; $('stopText').hidden = false; $('stopText').disabled = false;
  setConversationControlsDisabled(true); setConfigurationControlsDisabled(true); setTextInputControlsDisabled(true);
  $('textInputState').textContent = '正在回复…';
  let assistantNode = null; let delta = ''; let completed = false;
  try {
    const endpoint = override?.resend_mid ? `/api/conversations/${encodeURIComponent(cid)}/messages/${encodeURIComponent(override.resend_mid)}/resend` : override?.regenerate_mid ? `/api/conversations/${encodeURIComponent(cid)}/messages/${encodeURIComponent(override.regenerate_mid)}/regenerate` : `/api/conversations/${encodeURIComponent(cid)}/messages/stream`;
    const response = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pendingTextTurn)});
    await consumeEvents(response, payload => {
      if (payload.type === 'state') status(payload.state);
      if (payload.type === 'search') renderSearchTurn(payload);
      if (payload.type === 'tool_result') { const n = document.getElementById('roleToolTurnStatus'); if (n) n.textContent = payload.status === 'error' ? '工具请求失败：' + payload.error : '工具请求已接收，执行状态请查看控制面板'; }
      if (payload.type === 'transcript' && !override?.regenerate_mid && !override?.resend_mid) { const node = addMessage('user', payload.text); if (images.length) { const gallery = document.createElement('div'); gallery.className = 'message-images'; renderImages(gallery, images); node.querySelector('.message-body').append(gallery); } }
      if (payload.type === 'delta') {
        delta += payload.text;
        if (!assistantNode) assistantNode = addMessage('assistant', '');
        renderMessageText(assistantNode.querySelector('.message-body'), delta, true, true); scrollChat();
      }
      if (payload.type === 'error') throw new Error(payload.detail);
      if (payload.type === 'complete') {
        completed = true; messages = payload.messages; renderConversation(); saveLlmDebug(payload.debug);
        $('latencyInfo').textContent = usageLabel(payload.usage);
        if (payload.search) renderSearchTurn({...payload.search, sources: payload.assistant_message?.sources});
      }
    });
    if (!completed) throw new Error('连接提前结束；服务端可能仍在生成，请刷新记录或重试');
    if (!override) { $('textInput').value = ''; draftImages = []; renderDraftImages(); }
    pendingTextTurn = null; $('textInputState').textContent = 'Enter 发送 · Shift + Enter 换行'; status('Idle');
  } catch (error) {
    if (override && !override.regenerate_mid && !override.resend_mid && !$('textInput').value.trim()) { $('textInput').value = content; draftImages = [...images]; renderDraftImages(); }
    $('textInputState').textContent = error.message === '已手动停止生成' ? '已停止，可继续发送；再次发送相同内容会复用请求。' : `${error.message}；再次发送相同内容会复用请求。`; status(error.message === '已手动停止生成' ? 'Idle' : 'Error');
  } finally {
    activeTextRequest = null; $('stopText').hidden = true;
    await persistConversation(cid, null, false).catch(() => {});
    processing = false; setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false);
  }
}

async function createMessageBranch(message, action, content = null, cid = activeConversationId) {
  if (processing || recording) throw new Error('请等待当前一轮完成');
  const result = await companionApi(`/api/conversations/${cid}/messages/${message.id}/branch`, {action, ...(content === null ? {} : {content})}, 'POST');
  const branch = result.conversation;
  conversations.unshift(branch); activeConversationId = branch.id; messages = branch.messages;
  localStorage.setItem(`conversation:${activeCharacterId}`, branch.id); pendingTextTurn = null; stickToBottom = true;
  resetTurnDisplay(); renderConversationSelect(); renderConversation();
  $('messageEditPanel').close();
  setConversationState('已创建分支，原对话保留', 'saved');
  if (result.resend_content !== null && result.resend_content !== undefined) await sendTypedText({content: result.resend_content, images: result.resend_images || []});
}

function releaseMessageAudio() {
  if (speakingMessage) { speakingMessage.audio.pause(); speakingMessage.state.textContent = ''; speakingMessage = null; }
  if (speechObjectUrl) { URL.revokeObjectURL(speechObjectUrl); speechObjectUrl = null; }
}

async function playStoredMessage(message, profileId, state, cid = activeConversationId) {
  if (speechBusy) throw new Error('正在合成语音，请稍候');
  if (speakingMessage?.id === message.id && !speakingMessage.audio.paused) { releaseMessageAudio(); return; }
  releaseMessageAudio(); stopAudio(); speechBusy = true; state.textContent = '正在生成语音…';
  try {
    const response = await fetch(`/api/conversations/${cid}/messages/${message.id}/tts`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({profile_id: profileId || null})});
    if (!response.ok) { const value = await response.json(); throw new Error(value.detail || '语音生成失败'); }
    speechObjectUrl = URL.createObjectURL(await response.blob());
    const audio = new Audio(speechObjectUrl); speakingMessage = {id: message.id, audio, state};
    audio.onended = releaseMessageAudio;
    audio.onerror = () => { releaseMessageAudio(); state.textContent = '音频无法播放，请检查 TTS 输出格式'; };
    await audio.play(); state.textContent = '正在朗读 · 再点朗读可停止';
  } catch (error) { releaseMessageAudio(); state.textContent = error.message; throw error; }
  finally { speechBusy = false; }
}

$('resendMessageEdit').onclick = reportTo('messageEditState', async () => {
  if (!editingMessage || editingMessage.cid !== activeConversationId || processing || recording) return;
  const {message} = editingMessage;
  const content = $('messageEditContent').value;
  if (!content.trim() && !message.images?.length) throw new Error('消息不能为空');
  $('messageEditPanel').close();
  await sendTypedText({content, images: message.images || [], resend_mid: message.id});
});
$('saveMessageEdit').onclick = reportTo('messageEditState', async () => {
  if (!editingMessage) return;
  const content = $('messageEditContent').value; $('saveMessageEdit').disabled = true;
  try { await createMessageBranch(editingMessage.message, 'edit', content, editingMessage.cid); }
  finally { $('saveMessageEdit').disabled = false; }
});
$('playMessageVoice').onclick = reportTo('messageVoiceState', async () => {
  if (!selectedSpeechMessage) return;
  await playStoredMessage(selectedSpeechMessage.message, $('messageVoiceProfile').value, $('messageVoiceState'), selectedSpeechMessage.cid);
});
$('sendText').onclick = () => void sendTypedText();
$('textInput').onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void sendTypedText(); }
};
$('toggleSidebar').onclick = () => document.body.classList.toggle('sidebar-open');
const legacyKeydown = window.onkeydown;
window.onkeydown = event => { if ($('voicePanel').open || capturingKey) legacyKeydown(event); };
const legacyKeyup = window.onkeyup;
window.onkeyup = event => { if (recording || startPromise) legacyKeyup(event); };
window.addEventListener('beforeunload', releaseMessageAudio);

let stateLoading = false;
let stateRefreshQueued = false;
let lastStateConversation = null;
let lastStateRefresh = 0;
async function refreshCompanionState(force = false) {
  if (!activeConversationId) return;
  const cid = activeConversationId, bar = $('companionStateBar');
  if (cid !== lastStateConversation) bar.hidden = true;
  if (stateLoading) { if (force) stateRefreshQueued = true; return; }
  if (!force && lastStateConversation === cid && Date.now() - lastStateRefresh < 60000) return;
  stateLoading = true;
  try {
    const {change} = await companionApi(`/api/role-state/${cid}/latest-change`);
    if (cid !== activeConversationId) return;
    lastStateConversation = cid; lastStateRefresh = Date.now();
    bar.hidden = !change || change.status === 'disabled';
    if (bar.hidden) return;
    const format = n => Number(n.toFixed(2)).toString();
    const labels = {unchanged:'没有情绪变动',invalid:'情绪填写无效，本轮未更新',stale:'旧结果未覆盖后续修改'};
    $('companionStateText').textContent = change.changes.length
      ? change.changes.map(c => `${c.emotion} ${format(c.before)} → ${format(c.after)} (${c.after > c.before ? '+' : ''}${format(c.after-c.before)})`).join(' · ')
      : labels[change.status] || '没有情绪变动';
    bar.title = `${change.source === 'heartbeat' ? '主动消息' : '会话回复'} · ${new Date(change.at).toLocaleString()}`;
  } catch { if (cid === activeConversationId) bar.hidden = true; }
  finally {
    stateLoading = false;
    if (stateRefreshQueued) {stateRefreshQueued = false; void refreshCompanionState(true);}
  }
}
setInterval(() => void refreshCompanionState(), 60000);
