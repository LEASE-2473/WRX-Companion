(() => {
  const dialog = document.createElement('dialog');
  dialog.className = 'manager-dialog role-tools-panel';
  dialog.innerHTML = `<div class="dialog-header"><h2 id="extensionPageTitle">扩展</h2><button type="button" id="closeRoleTools">收起面板</button></div>
    <div class="extension-tabs" role="tablist" aria-label="扩展与技能页面">
      <button type="button" role="tab" id="extensionTab" aria-selected="true" aria-controls="extensionPage">扩展</button>
      <button type="button" role="tab" id="skillTab" aria-selected="false" aria-controls="skillPage" tabindex="-1">Skill</button>
    </div>
    <div class="dialog-scroll"><p id="roleToolStatus" role="status"></p>
      <section id="extensionPage" role="tabpanel" aria-labelledby="extensionTab">
        <div class="extension-page-heading"><div><h3>我的扩展</h3><p class="hint">独立应用，按需开启。收起面板后仍可继续运行。</p></div><button type="button" id="refreshExtensions">重新扫描</button></div>
        <div id="extensionCards"></div><iframe id="toyToolFrame" title="扩展应用面板" hidden></iframe>
      </section>
      <section id="skillPage" role="tabpanel" aria-labelledby="skillTab" hidden>
        <div class="extension-page-heading"><div><h3>我的 Skill</h3><p class="hint">管理 AI 可用的技能，选择何时提供使用说明。</p></div></div><div id="skillCards"></div>
      </section>
    </div>`;
  document.body.append(dialog);
  const entry = document.createElement('button'); entry.textContent = '扩展与技能';
  document.querySelector('.sidebar-settings').append(entry);
  const turn = document.createElement('span'); turn.id = 'roleToolTurnStatus'; turn.className = 'hint';
  document.querySelector('.composer-wrap').prepend(turn);
  const status = dialog.querySelector('#roleToolStatus'), frame = dialog.querySelector('#toyToolFrame');
  let panelId = null, busy = false;
  const extensionTab = dialog.querySelector('#extensionTab'), skillTab = dialog.querySelector('#skillTab');
  function selectPage(page) {
    const extension = page === 'extension';
    dialog.querySelector('#extensionPageTitle').textContent = extension ? '扩展' : 'Skill';
    dialog.querySelector('#extensionPage').hidden = !extension;
    dialog.querySelector('#skillPage').hidden = extension;
    extensionTab.setAttribute('aria-selected', String(extension));
    skillTab.setAttribute('aria-selected', String(!extension));
    extensionTab.tabIndex = extension ? 0 : -1;
    skillTab.tabIndex = extension ? -1 : 0;
  }
  extensionTab.onclick = () => selectPage('extension');
  skillTab.onclick = () => selectPage('skill');
  for (const tab of [extensionTab, skillTab]) tab.onkeydown = event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === 'Home' ? extensionTab : event.key === 'End' ? skillTab : tab === extensionTab ? skillTab : extensionTab;
    target.onclick(); target.focus();
  };
  async function api(url, method = 'GET', value) {
    const response = await fetch(url, {method, headers:{'X-Extensions':'1','Content-Type':'application/json'}, body:value === undefined ? undefined : JSON.stringify(value)});
    const data = await response.json(); if (!response.ok) throw Error(data.detail || '请求失败'); return data;
  }
  function text(parent, tag, value) { const node = document.createElement(tag); node.textContent = value; parent.append(node); return node; }
  function button(parent, label, action, disabled = false) { const node = text(parent, 'button', label); node.type = 'button'; node.disabled = disabled; node.onclick = action; return node; }
  async function perform(id, operation) {
    if (busy) return; busy = true; status.textContent = '正在处理…';
    try {
      await api('/api/extensions/' + encodeURIComponent(id) + '/' + operation, 'POST');
      if (['stop','disable'].includes(operation) && panelId === id) { frame.hidden = true; frame.removeAttribute('src'); panelId = null; }
      status.textContent = ''; await refresh();
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; }
  }
  async function refresh() {
    try {
      const [extensions, skills] = await Promise.all([api('/api/extensions'), api('/api/skills/manage/list')]);
      const cards = dialog.querySelector('#extensionCards'); cards.replaceChildren();
      for (const item of extensions.extensions) {
        const card = document.createElement('section'); card.className = 'toy-tool-card'; cards.append(card);
        text(card, 'strong', item.icon + ' ' + item.name); text(card, 'span', item.description);
        const badge = text(card, 'p', item.error || (item.running ? '运行中' : item.enabled ? '已启用 · 尚未启动' : '已停用'));
        badge.className = 'extension-status' + (item.error ? ' is-error' : item.running ? ' is-running' : '');
        const actions = document.createElement('div'); actions.className = 'toy-tool-actions'; card.append(actions);
        button(actions, item.enabled ? '停用' : '启用', () => perform(item.id, item.enabled ? 'disable' : 'enable'), Boolean(item.error) && !item.enabled);
        if (item.enabled || item.running) {
          button(actions, item.running ? '关闭应用' : '启动应用', () => perform(item.id, item.running ? 'stop' : 'start'), Boolean(item.error) && !item.running);
          if (item.has_panel && item.enabled) button(actions, '打开面板', () => { panelId = item.id; frame.src = '/apps/' + encodeURIComponent(item.id) + '/'; frame.hidden = false; });
        }
      }
      const skillCards = dialog.querySelector('#skillCards'); skillCards.replaceChildren();
      for (const skill of skills.skills) {
        const card = document.createElement('section'); card.className = 'toy-tool-card'; skillCards.append(card);
        text(card,'strong',skill.name); text(card,'span',skill.description);
        const badge = text(card,'p',skill.enabled ? '已启用' : '已停用'); badge.className = 'extension-status' + (skill.enabled ? ' is-running' : '');
        const actions = document.createElement('div'); actions.className = 'toy-tool-actions'; card.append(actions);
        const update = async value => { try { await api('/api/skills/' + skill.name + '/settings','PUT',value); await refresh(); } catch (error) { status.textContent = error.message; } };
        button(actions, skill.enabled ? '停用技能' : '启用技能', () => update({enabled:!skill.enabled,injection:skill.injection}));
        const select = document.createElement('select'); select.setAttribute('aria-label',skill.name + '注入方式');
        for (const [value,label] of [['always','直接提供说明'],['on_demand','按需读取说明']]) { const option = text(select,'option',label); option.value = value; }
        select.value = skill.injection; select.onchange = () => update({enabled:skill.enabled,injection:select.value}); actions.append(select);
      }
    } catch (error) { status.textContent = error.message; }
  }
  entry.onclick = () => { dialog.showModal(); refresh(); };
  dialog.querySelector('#closeRoleTools').onclick = () => dialog.close();
  dialog.querySelector('#refreshExtensions').onclick = refresh;
  setInterval(() => { if (dialog.open && !busy) refresh(); }, 5000);
})();
