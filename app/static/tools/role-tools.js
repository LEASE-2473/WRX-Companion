(() => {
  const dialog = document.createElement('dialog');
  dialog.className = 'manager-dialog role-tools-panel';
  dialog.innerHTML = '<div class="dialog-header"><h2>角色工具</h2><button type="button" id="closeRoleTools">收起面板</button></div><div class="dialog-scroll"><section class="toy-tool-card"><strong>玩具控制</strong><span>按需启动蓝牙后台，再手动扫描和连接。不使用时关闭工具，结束扫描、断开连接并退出后台。</span><div class="toy-tool-actions"><button type="button" id="startToyTool">启动工具</button><button type="button" id="openToyTool" hidden>打开控制面板</button><button type="button" id="stopToyTool" hidden>关闭工具</button></div><p id="roleToolStatus" role="status">工具未启动</p></section><p class="hint">收起面板可继续使用；关闭工具对所有角色生效。</p><iframe id="toyToolFrame" title="玩具控制面板" hidden></iframe></div>';
  document.body.append(dialog);
  const entry = document.createElement('button'); entry.textContent = '角色工具';
  document.querySelector('.sidebar-settings').append(entry);
  const badge = document.createElement('span'); badge.className = 'role-tool-badge'; badge.hidden = true;
  document.querySelector('.chat-topbar').append(badge);
  const turn = document.createElement('span'); turn.id = 'roleToolTurnStatus'; turn.className = 'hint';
  document.querySelector('.composer-wrap').prepend(turn);
  const status = dialog.querySelector('#roleToolStatus'), frame = dialog.querySelector('#toyToolFrame');
  const startButton = dialog.querySelector('#startToyTool');
  const openButton = dialog.querySelector('#openToyTool');
  const stopButton = dialog.querySelector('#stopToyTool');
  let polling = false, opening = false;
  async function api(url, method = 'GET') {
    const r = await fetch(url, {method, headers:{'X-Role-Tools':'1'}}); const value = await r.json();
    if (!r.ok) throw Error(value.detail || '工具服务不可用');
    return value;
  }
  entry.onclick = () => { dialog.showModal(); refresh(); };
  dialog.querySelector('#closeRoleTools').onclick = () => dialog.close();
  function busy(value) {
    opening = value;
    startButton.disabled = openButton.disabled = stopButton.disabled = value;
  }
  function render(tool) {
    startButton.hidden = tool.attached || tool.service_running;
    openButton.hidden = !tool.attached;
    stopButton.hidden = !tool.attached && !tool.service_running;
    badge.hidden = !tool.connected;
    badge.textContent = tool.ready ? '玩具已接入' : '玩具已连接 · 准备中';
    status.textContent = tool.error || (tool.ready ? '已全局接入：所有角色会话均可使用工具' : tool.connected ? '已连接，写入特征准备中' : tool.attached ? '工具已启动，请手动连接蓝牙' : '工具已关闭，蓝牙后台未运行');
    if (tool.warning) status.textContent += ' · ' + tool.warning;
    if (tool.program?.status) status.textContent += ' · DIY ' + tool.program.status + (tool.program.error ? '：' + tool.program.error : '');
    if (!tool.attached) { frame.hidden = true; frame.removeAttribute('src'); }
  }
  openButton.onclick = () => {
    if (!activeConversationId) { status.textContent = '请先选择一个会话'; return; }
    frame.src = '/api/role-tools/toy/panel?cid=' + encodeURIComponent(activeConversationId);
    frame.hidden = false;
  };
  startButton.onclick = async () => {
    if (opening) return;
    if (!activeConversationId) { status.textContent = '请先选择一个会话'; return; }
    busy(true); status.textContent = '正在启动蓝牙后台…';
    const cid = activeConversationId;
    try {
      render(await api('/api/role-tools/toy/start/' + encodeURIComponent(cid), 'POST'));
      if (activeConversationId) openButton.onclick();
    } catch (e) { status.textContent = e.message; }
    finally { busy(false); }
  };
  stopButton.onclick = async () => {
    if (opening || !activeConversationId) return;
    busy(true); status.textContent = '正在停止播放、断开连接并关闭后台…';
    frame.hidden = true; frame.removeAttribute('src');
    try {
      render(await api('/api/role-tools/toy/close/' + encodeURIComponent(activeConversationId), 'POST'));
    } catch (error) {
      badge.hidden = true;
      status.textContent = error.message;
    } finally { busy(false); }
  };
  async function refresh() {
    if (polling || opening || !activeConversationId) return;
    polling = true; const cid = activeConversationId;
    try {
      const response = await api('/api/role-tools/status/' + encodeURIComponent(cid));
      if (cid !== activeConversationId || opening) return;
      render(response.tools[0]);
    } catch (e) { badge.hidden = true; if (dialog.open) status.textContent = e.message; }
    finally { polling = false; }
  }
  setInterval(refresh, 3000); refresh();
})();
