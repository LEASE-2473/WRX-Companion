/* 角色记忆界面：所有用户内容用 textContent，密钥只提交给后端。 */
(() => {
  const labels = {general:'常规', diary:'日记', activity:'自主活动', settings:'设置'};
  const dialog = document.createElement('dialog'); dialog.className = 'manager-dialog'; dialog.id = 'roleMemoryPanel';
  dialog.innerHTML = '<div class="dialog-header"><div><span class="memory-eyebrow">陪伴的点滴，都在这里</span><h2>角色记忆</h2></div><button id="closeRoleMemory" aria-label="关闭角色记忆">关闭</button></div><nav id="memoryTabs" aria-label="角色记忆分页"></nav><div class="dialog-scroll"><p id="memoryStatus" class="hint" role="status"></p><div id="memoryBody"></div></div>';
  document.body.append(dialog);
  const entry = document.createElement('button'); entry.textContent = '角色记忆'; entry.id = 'openRoleMemory';
  document.querySelector('[data-open-panel="promptPanel"]').parentElement.append(entry);
  const body = dialog.querySelector('#memoryBody'), status = dialog.querySelector('#memoryStatus');
  let tab = 'general', config, data, characterId, conversationId, profiles = [];
  const profileOptions = purpose => [['','未选择（独立任务需指定模型）'], ...(purpose === 'chat' ? profiles : settings.provider_profiles[purpose + '_profiles'] || []).map(p => [p.id,p.name])];
  const node = (tag, text, parent = body) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; parent.append(n); return n; };
  const button = (text, fn, parent = body) => { const n = node('button', text, parent); n.type = 'button'; n.onclick = () => action(fn); return n; };
  const field = (label, value, onChange, type = 'text', parent = body) => {
    const wrapper = node('label', label, parent); const input = node(type === 'textarea' ? 'textarea' : 'input', undefined, wrapper);
    if (type !== 'textarea') input.type = type; else input.rows = 5;
    wrapper.className = type === 'checkbox' ? 'memory-toggle' : 'memory-field';
    if (type === 'number') input.step = 'any';
    if (type === 'checkbox') input.checked = value; else input.value = value ?? '';
    input.oninput = () => onChange(type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value);
    return input;
  };
  const select = (label, value, options, onChange, parent = body) => {
    const wrapper = node('label', label, parent), input = node('select', undefined, wrapper); wrapper.className = 'memory-field';
    options.forEach(([v,t]) => { const o = node('option', t, input); o.value = v; }); input.value = value; input.onchange = () => onChange(input.value); return input;
  };
  async function request(path, method = 'GET', value) {
    const response = await fetch('/api/role-memory' + path, {method, headers:{'Content-Type':'application/json'}, body:value === undefined ? undefined : JSON.stringify(value)});
    const result = await response.json(); if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)); return result;
  }
  async function action(fn) { status.textContent = '处理中…'; try { await fn(); status.textContent = '完成'; } catch(e) { status.textContent = e.message; } }
  async function refresh() { data = await request('/' + encodeURIComponent(characterId) + '?conversation_id=' + encodeURIComponent(conversationId)); render(); }
  async function save() { config = await request('/settings', 'PUT', config); await refresh(); }
  function recordCard(record, parent = body) {
    const card = node('details', undefined, parent); card.className = 'memory-card';
    const summary = node('summary', undefined, card);
    node('span', record.kind === 'diary' ? record.date : record.occurred_at ? new Date(record.occurred_at).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '时间未明确', summary).className = 'memory-record-date';
    node('span', record.kind === 'diary' ? (record.title || '未命名日记') : (record.tags.join(' / ') || labels[record.kind]), summary).className = 'memory-record-title';
    if (record.kind === 'diary') node('span', record.entry_type === 'chat_entry' ? '即时日记' : '当日日记', summary).className = 'memory-badge';
    node('span', record.mode === 'hot' ? '常驻' : record.vectorized ? '向量召回' : '待向量化', summary).className = 'memory-badge ' + record.mode;
    node('p', `作用域：${record.scope === 'character' ? '角色共享' : '会话私有'}${record.conversation_id === conversationId ? '' : ' · 来自其他会话'}`, card);
    const draft = {...record};
    if (record.kind === 'diary') field('日记标题', draft.title || '', v => draft.title = v, 'text', card);
    field('正文', draft.content, v => draft.content = v, 'textarea', card);
    field('事件标签（逗号分隔）', draft.tags.join(','), v => draft.tags = v.split(',').map(s => s.trim()).filter(Boolean), 'text', card);
    select('作用域', draft.scope, [['conversation','会话私有'],['character','角色共享']], v => draft.scope = v, card);
    field('检索关键词（逗号分隔）', (draft.keywords || []).join(','), v => draft.keywords = v.split(',').map(s => s.trim()).filter(Boolean), 'text', card);
    button('保存编辑', async () => { await request(`/${characterId}/${record.kind}/${record.id}`, 'PUT', draft); await refresh(); }, card);
    if (record.kind === 'diary') button('删除这篇日记', async () => { if (!window.confirm('删除这篇日记？正文将移出记忆使用，应用保留本地恢复备份。')) return; await request(`/${characterId}/diary/${record.id}`, 'DELETE'); await refresh(); }, card);
    if (record.kind !== 'book') button(record.mode === 'hot' ? '转冷' : '转热', async () => { await request(`/${characterId}/records/${record.id}/mode`, 'POST', {mode:record.mode === 'hot' ? 'cold' : 'hot'}); await refresh(); }, card);
    if (record.kind !== 'book') button('恢复自动规则', async () => { await request(`/${characterId}/records/${record.id}/mode`, 'POST', {mode:'auto'}); await refresh(); }, card);
    else button('生成／更新向量', async () => { await request(`/${characterId}/records/${record.id}/mode`, 'POST', {mode:'cold'}); await refresh(); }, card);
    node('p', '来源：' + (record.sources.join(', ') || '手动录入／外部导入'), card);
    if (record.kind === 'activity') node('p', '实际活动：' + record.activity_content + ' · 笔记状态：' + (record.note_status || '已记录') + (record.note_error ? ' · ' + record.note_error : ''), card);

  }
  function render() {
    document.getElementById('historySettingsMount').append(document.getElementById('contextSettingsPanel')); body.replaceChildren(); dialog.querySelector('h2').textContent = '角色记忆 · ' + (currentCharacter()?.name || characterId);
    dialog.querySelectorAll('#memoryTabs button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === tab)));
    if (tab === 'general') {
      const hero = node('section'); hero.className = 'memory-hero';
      const metrics = node('div', undefined, hero);
      node('span', '当前常驻记忆', metrics).className = 'memory-eyebrow';
      const number = node('div', undefined, metrics); number.className = 'memory-token-number';
      node('strong', data.hot.estimated_tokens.toLocaleString(), number); node('span', '估算 Token', number);
      node('p', `提醒阈值 ${data.hot.limit.toLocaleString()} · ${data.hot.over_limit ? '已超出预算' : '预算内'}`, metrics);
      const meter = node('div', undefined, hero); meter.className = 'memory-meter';
      const bar = node('div', undefined, meter); bar.style.width = Math.min(100, data.hot.estimated_tokens / data.hot.limit * 100) + '%';
      meter.setAttribute('aria-label', '热区预算使用比例');
      node('p', data.hot.over_limit ? '常驻内容超过提醒阈值，可减少 Layer 1 历史条数，或将 Layer 2–4 记录转冷；不会自动截掉常驻内容。' : '统计历史、日记、活动与系统记忆常驻内容；所有冷召回仅按相似度、排序及条数选择，不设 Token 预算。');
      if (data.hot.over_limit) node('p', '统计历史、日记、活动与系统记忆常驻内容；所有冷召回仅按相似度、排序及条数选择，不设 Token 预算。');
      field('热区提醒阈值', config.hot_token_limit, v => config.hot_token_limit = v, 'number');
      node('h3', `上下文 · Layer 1 · 约 ${data.hot.by_kind.history} Token`);
      body.append(document.getElementById('contextSettingsPanel'));
      node('p', `当前选入 ${data.hot.history_count} 条历史；0 表示不注入旧历史，Layer 1 不参与向量召回。`);
      document.getElementById('saveHistoryDepth').onclick = () => action(async () => { await saveHistoryDepth(); await refresh(); });
      for (const kind of ['diary','activity']) {
        const p = config.policies[kind]; node('h3', `${labels[kind]} · 约 ${data.hot.by_kind[kind]} Token`);
        field('参与上下文注入', p.enabled, v => p.enabled = v, 'checkbox');
        select('新记录作用域', p.scope, [['conversation','会话私有'],['character','角色共享']], v => p.scope = v);
        select('新记录默认注入方式', p.default_mode, [['hot','常驻（热）'],['cold','向量召回（冷）']], v => p.default_mode = v);
        if (kind === 'diary') field('自动转冷天数（0 关闭）', p.auto_cold_days, v => p.auto_cold_days = v, 'number');
      }
      button('保存注入规则', save); node('h3', '当前会话可用的热区');
      const hotItems = data.records.filter(r => r.kind !== 'book' && r.kind !== 'event' &&
        (r.mode === 'hot' || !config.vector.enabled || !r.vectorized) && config.policies[r.kind].enabled &&
        (r.scope === 'character' || r.conversation_id === conversationId));
      hotItems.forEach(r => recordCard(r));
      if (!hotItems.length) node('p', '热区还是空的。日记与活动记录会在这里汇集；客观事实在系统记忆中管理。');
    } else if (tab === 'settings') {
      node('h3', '应用内技能');
      button('查看技能目录与使用说明', async () => { const r = await fetch('/api/skills'); const d = await r.json(); const area = node('section'); for (const skill of d.skills) { const card = node('details', undefined, area); node('summary', skill.name + ' · ' + skill.description, card); const detail = await (await fetch('/api/skills/' + skill.name)).json(); node('pre', detail.content, card); } });
      node('h3', '日记调度'); field('启用每日独立日记任务', config.diary_enabled, v => config.diary_enabled = v, 'checkbox');
      field('结算小时（使用各会话时区）', config.diary_hour, v => config.diary_hour = v, 'number');
      node('h3', '预设区域');
      button('重新读取Markdown提示词', async () => { const defaults = await request('/prompt-defaults'); for (const k of ['diary','activity']) Object.assign(config.presets[k],defaults[k]); await save(); render(); });
      for (const kind of ['diary','activity']) {
        const p = config.presets[kind]; const area = node('details'); node('summary', labels[kind] + '预设与填表要求', area);
        field('完整提示词（含输出格式）', p.prompt, v => p.prompt = v, 'textarea', area);
        if (kind === 'diary') field('指定时段日记完整提示词', p.instant_prompt, v => p.instant_prompt = v, 'textarea', area);
        if (kind !== 'diary') field('单日聊天输入上限（超限报错，不漏记）', p.history_limit, v => p.history_limit = v, 'number', area);
        if (kind !== 'diary') {
          field('读取自主活动记录', p.include_notes, v => p.include_notes = v, 'checkbox', area); field('读取已有重要事件', p.include_events, v => p.include_events = v, 'checkbox', area);
        } else node('p', '手动与自动日记只读带时间的纯对话；不注入图片、搜索结果、情绪、活动笔记或已有事件。', area);
      }
      node('h3', 'API 区域 · 独立填表 LLM');
      for (const kind of ['diary','activity']) {
        const p = config.presets[kind], area = node('details'); node('summary', labels[kind] + '独立 LLM', area);
        select('LLM Profile', p.llm_profile_id || '', profileOptions('chat'), v => { p.llm_profile_id = v || null; p.follow_conversation = false; if (!v) {p.llm.model = '';p.llm.api_key = '';} }, area);
        field('温度', p.temperature, v => p.temperature = v, 'number', area);
        button('保存并测试连接', async () => { await save(); const r = await request('/connections/test/' + kind, 'POST', {conversation_id:conversationId}); window.alert(JSON.stringify(r)); }, area);
      }
      node('h3', 'Embedding / Rerank'); const v = config.vector;
      field('启用向量召回与转冷', v.enabled, x => v.enabled = x, 'checkbox');
      select('Embedding Profile', config.embedding_profile_id || '', profileOptions('embedding'), x => config.embedding_profile_id = x || null);
      select('Rerank Profile', config.rerank_profile_id || '', profileOptions('rerank'), x => config.rerank_profile_id = x || null);
      button('前往模型与语音管理 Profile', () => { dialog.close(); renderAllProviderProfiles(); document.getElementById('providerPanel').showModal(); });
      field('启用 Rerank', v.rerank_enabled, x => v.rerank_enabled = x, 'checkbox');
      field('最终召回条数', v.max_results, x => v.max_results = x, 'number'); field('相似度阈值', v.threshold, x => v.threshold = x, 'number');
      button('保存全部设置', save);
      for (const kind of ['embed','rank']) button('保存并测试 ' + kind, async () => { await save(); window.alert(JSON.stringify(await request('/connections/test/' + kind, 'POST', {conversation_id:conversationId}))); });
    } else {
      if (tab === 'diary') {
        let date = new Date(Date.now()).toLocaleDateString('sv-SE'); field('处理日期（按会话时区）', date, v => date = v, 'date');
        button(tab === 'diary' ? '手动生成当日日记' : '提取当日重要事件', async () => { await request(`/${characterId}/generate/${tab}`, 'POST', {conversation_id:conversationId,date}); await refresh(); });
        if (tab === 'diary') {
          let start = '00:00', end = '06:00';
          field('即时日记开始时间', start, v => start = v, 'time');
          field('即时日记结束时间（24:00表示当天结束）', end, v => end = v);
          node('p', '当日日记读取所选日期全部纯对话；即时日记读取该日期选定时间段（含开始，不含结束）。均无消息条数上限，模型上下文超限时二分总结再合并。');
          button('手动生成即时日记', async () => { await request(`/${characterId}/generate/diary`, 'POST', {conversation_id:conversationId,date,entry_type:'chat_entry',start_time:start,end_time:end}); await refresh(); });
        }
      }
      if (tab === 'activity') node('p', '只记录实际发生的自主活动。Phase 4 活动执行器接入后自动写入；普通心跳与聊天不会生成虚构活动。');

      const items = data.records.filter(r => r.kind === tab);
      if (!items.length) {
        const empty = node('div'); empty.className = 'memory-empty';
        node('span', ({diary:'◷',activity:'✧',event:'◇',book:'▤'})[tab], empty).className = 'memory-empty-symbol';
        node('h3', '还没有' + labels[tab] + '记录', empty);
        node('p', ({diary:'选一个日期，把这一天的相处写成日记。',activity:'每一次自主活动，都会在这里留下足迹。',event:'把值得记住的共同经历与约定留在这里。',book:'导入一份资料，让她在需要时了解更多。'})[tab], empty);
      }
      items.forEach(r => recordCard(r));
      if (tab === 'diary') { node('h3','独立任务记录'); for (const job of data.jobs) { const d = node('details'); node('summary',job.id + ' · ' + job.status,d); node('pre',JSON.stringify(job.document,null,2),d); } }
    }
    polishLayout();
  }
  function polishLayout() {
    // 按现有语义分组，保留输入监听器和数据保存逻辑。
    const children = [...body.children]; let section = null;
    for (const child of children) {
      if (tab === 'general' && child.tagName === 'BUTTON') { section = null; continue; }
      if (child.tagName === 'H3') {
        section = document.createElement('section'); section.className = 'memory-section';
        body.insertBefore(section, child); section.append(child);
      } else if (section) section.append(child);
    }
    if (tab === 'general') {
      const rules = document.createElement('div'); rules.className = 'memory-rule-grid';
      const sections = [...body.querySelectorAll(':scope > .memory-section')];
      for (const section of sections.slice(0,4)) {
        if (!rules.parentElement) body.insertBefore(rules, section);
        rules.append(section);
      }
    }
    for (const section of body.querySelectorAll('.memory-section, details')) {
      const labels = [...section.children].filter(n => n.tagName === 'LABEL');
      if (labels.length > 1) {
        const grid = document.createElement('div'); grid.className = 'memory-form-grid';
        section.insertBefore(grid, labels[0]); labels.forEach(label => { if (label.querySelector('textarea')) label.classList.add('memory-wide'); grid.append(label); });
      }
    }
    for (const b of body.querySelectorAll('button')) {
      if (b.textContent.startsWith('保存') || b.textContent.includes('生成当日') || b.textContent === '导入（暂不调用 API）') b.classList.add('memory-primary');
    }
    const topFields = [...body.children].filter(n => n.tagName === 'LABEL');
    if (topFields.length) {
      const toolbar = document.createElement('div'); toolbar.className = 'memory-form-grid memory-toolbar';
      body.insertBefore(toolbar, topFields[0]); topFields.forEach(n => { if (n.querySelector('textarea')) n.classList.add('memory-wide'); toolbar.append(n); });
    }
  }
  for (const [key,label] of Object.entries(labels)) { const b = button(label, () => { tab = key; render(); }, dialog.querySelector('#memoryTabs')); b.dataset.tab = key; b.onclick = () => { tab = key; status.textContent = ''; render(); }; }
  entry.onclick = () => action(async () => { characterId = currentCharacter()?.id; conversationId = currentConversation()?.id; if (!characterId || !conversationId) throw new Error('请先选择角色和会话'); config = await request('/settings'); settings.provider_profiles = await providerApi('/api/provider-profiles'); profiles = settings.provider_profiles.llm_profiles; await refresh(); dialog.showModal(); });
  dialog.querySelector('#closeRoleMemory').onclick = () => dialog.close();
  let checking = false;
  setInterval(async () => {
    if (checking || !currentCharacter()?.id || !currentConversation()?.id) return;
    checking = true;
    try {
      const value = await request('/' + currentCharacter().id + '?conversation_id=' + currentConversation().id);
      entry.textContent = '角色记忆';
      entry.title = value.hot.over_limit ? `热区约 ${value.hot.estimated_tokens} Token，请调整历史条数或将 2–4 记录转冷` : '查看角色记忆';
    } catch {} finally { checking = false; }
  }, 60000);
})();
