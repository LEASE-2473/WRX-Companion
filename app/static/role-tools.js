/* 角色工具：主项目同源面板；打开时启动，不自动连接。 */
(() => {
  const dialog = document.createElement('dialog');
  dialog.className = 'manager-dialog role-tools-panel';
  dialog.innerHTML = '<div class="dialog-header"><h2>角色工具</h2><button type="button" id="closeRoleTools">关闭</button></div><div class="dialog-scroll"><p class="hint">由你扫描、连接和断开；关闭面板不改变连接。</p><button type="button" id="openToyTool" class="toy-tool-card"><strong>玩具控制</strong><span>打开控制面板</span></button><p id="roleToolStatus" role="status"></p><iframe id="toyToolFrame" title="玩具控制面板" hidden></iframe></div>';
  document.body.append(dialog);
  const entry = document.createElement('button'); entry.textContent = '角色工具';
  document.querySelector('.sidebar-settings').append(entry);
  const badge = document.createElement('span'); badge.className = 'role-tool-badge'; badge.hidden = true;
  document.querySelector('.chat-topbar').append(badge);
  const turn = document.createElement('span'); turn.id = 'roleToolTurnStatus'; turn.className = 'hint';
  document.querySelector('.composer-wrap').prepend(turn);
  const status = dialog.querySelector('#roleToolStatus'), frame = dialog.querySelector('#toyToolFrame');
  let polling = false, opening = false;
  async function api(url, method = 'GET') {
    const r = await fetch(url, {method, headers:{'X-Role-Tools':'1'}}); const value = await r.json();
    if (!r.ok) throw Error(value.detail || '工具服务不可用');
    return value;
  }
  entry.onclick = () => { dialog.showModal(); refresh(); };
  dialog.querySelector('#closeRoleTools').onclick = () => dialog.close();
  dialog.querySelector('#openToyTool').onclick = async () => {
    if (opening) return;
    if (!activeConversationId) { status.textContent = '请先选择一个会话'; return; }
    opening = true; status.textContent = '正在打开本机玩具服务…';
    const cid = activeConversationId;
    try {
      await api('/api/role-tools/toy/start/' + encodeURIComponent(cid), 'POST');
      if (cid !== activeConversationId) return;
      frame.src = '/api/role-tools/toy/panel?cid=' + encodeURIComponent(cid); frame.hidden = false;
      await refresh();
    } catch (e) { status.textContent = e.message; }
    finally { opening = false; }
  };
  async function refresh() {
    if (polling || !activeConversationId) return;
    polling = true; const cid = activeConversationId;
    try {
      const response = await api('/api/role-tools/status/' + encodeURIComponent(cid));
      if (cid !== activeConversationId) return;
      const tool = response.tools[0];
      badge.hidden = !tool.connected;
      badge.textContent = tool.ready ? '玩具已接入' : '玩具已连接 · 准备中';
      status.textContent = tool.ready ? '已全局接入：所有角色会话均可使用工具' : tool.connected ? '已连接，写入特征准备中' : tool.attached ? (tool.error || '工具已全局打开，请手动连接蓝牙') : '尚未全局接入';
      if (tool.program?.status) status.textContent += ' · DIY ' + tool.program.status + (tool.program.error ? '：' + tool.program.error : '');
    } catch (e) { badge.hidden = true; if (dialog.open) status.textContent = e.message; }
    finally { polling = false; }
  }
  setInterval(refresh, 3000); refresh();
})();
