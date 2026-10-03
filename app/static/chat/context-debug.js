/* 上下文检查器：顺序来自最终请求，不对消息重新排序。 */
(() => {
  const $id = id => document.getElementById(id);
  const add = (tag, text, parent, cls) => { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; parent.append(n); return n; };
  function inspect(debug, title, note = '') {
    $id('contextDebugTitle').textContent = title;
    const list = $id('contextMessageList'); list.replaceChildren();
    const messages = debug.llm_messages || [];
    let total = 2;
    messages.forEach((m, index) => {
      const text = typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2);
      const tokens = 4 + estimatePromptTokens(m.role) + estimatePromptTokens(text);
      total += tokens;
      const d = document.createElement('details'); d.className = 'context-message'; d.dataset.role = m.role; list.append(d);
      const summary = add('summary', '', d);
      add('span', String(index + 1).padStart(2, '0'), summary, 'context-order');
      add('span', m.role, summary, 'context-role');
      add('span', `深度 ${messages.length - index - 1}`, summary, 'context-depth');
      add('span', text.replace(/\s+/g, ' ').slice(0, 90), summary, 'context-excerpt');
      add('span', `≈ ${tokens.toLocaleString()} Token`, summary, 'context-tokens');
      add('pre', text, d);
      if (m.images?.length) add('p', `${m.images.length} 张图片 · 图片 Token 不包含在本地估算中`, d, 'hint');
    });
    $id('contextDebugSummary').textContent = `${messages.length} 段 · 约 ${total.toLocaleString()} Token（文本与消息结构估算） · 从上到下是实际发送顺序；深度 0 为最后一段。${note}`;
    $id('llmRawDebug').textContent = debug.llm_raw ?? '模拟预览尚无模型回复';
    $id('llmNormalizedDebug').textContent = debug.normalized_reply ?? '';
    $id('llmTtsDebug').textContent = debug.tts_input ?? '';
    $id('lorebookActivationDebug').textContent = JSON.stringify(debug.prompt_trace || {}, null, 2);
    $id('contextResponse').open = false;
    $id('llmDebugDialog').showModal();
  }
  async function run(mode) {
    const cid = currentConversation()?.id;
    if (!cid) { $id('contextDebugStatus').textContent = '请先选择会话'; return; }
    const button = $id(mode === 'preview' ? 'previewContext' : 'showLlmDebug'); button.disabled = true;
    $id('contextDebugStatus').textContent = '正在读取…';
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(cid)}/context-${mode === 'preview' ? 'preview' : 'last'}`, mode === 'preview' ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:$id('contextPrefill').value || $id('textInput').value})} : {});
      const value = await response.json(); if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail));
      if (currentConversation()?.id !== cid) throw new Error('会话已切换，请重新查看');
      if (mode === 'preview') inspect(value, '模拟拼接 · 预填充', value.preview_note);
      else { if (!value.debug) throw new Error(value.debug_expired ? '每个会话保留最近20条请求实录，上一轮实录已清理；聊天正文仍然保留。可使用模拟拼接查看当前上下文。' : '当前会话还没有已保存的上下文实录'); inspect(value.debug, '上一轮 · 真实实录', `请求 ${value.request_id} · ${value.status} · 实录保留最近20条`); }
      $id('contextDebugStatus').textContent = '';
    } catch(e) { $id('contextDebugStatus').textContent = e.message; }
    finally { button.disabled = false; }
  }
  $id('previewContext').onclick = () => run('preview');
  $id('showLlmDebug').onclick = () => run('last');
  $id('expandContext').onclick = () => $id('contextMessageList').querySelectorAll('details').forEach(d => d.open = true);
  $id('collapseContext').onclick = () => $id('contextMessageList').querySelectorAll('details').forEach(d => d.open = false);
})();
