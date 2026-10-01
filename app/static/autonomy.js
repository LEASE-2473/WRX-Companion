/* 手动旅行与心跳自主旅行并存；外部文本仅以 textContent 展示。 */
(() => {
  const dialog = document.createElement('dialog'); dialog.className = 'manager-dialog'; dialog.id = 'autonomyPanel';
  dialog.innerHTML = '<div class="dialog-header"><div><span class="section-kicker">小小旅行</span><h2>自主外出</h2></div><button type="button" aria-label="关闭自主外出">关闭</button></div><div class="dialog-scroll"><p role="status" aria-live="polite"></p><div class="activity-body"></div></div>';
  document.body.append(dialog); dialog.querySelector('button').onclick = () => dialog.close();
  const entry = document.createElement('button'); entry.textContent = '自主外出'; document.querySelector('.sidebar-settings').append(entry);
  const body = dialog.querySelector('.activity-body'), status = dialog.querySelector('[role=status]');
  const names = {mastodon:'Mastodon',openmolt:'OpenMolt 兼容社区',search:'联网搜索',lutopia:'Lutopia'};
  let cfg, cid, timer, busy = false, tripButton;
  const node = (tag,text,parent = body) => { const n = document.createElement(tag); if(text !== undefined) n.textContent = text; parent.append(n); return n; };
  async function api(path,method='GET',value) {
    const res = await fetch('/api/autonomy'+path,{method,headers:{'Content-Type':'application/json'},body:value === undefined ? undefined : JSON.stringify(value)});
    const result = await res.json(); if(!res.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)); return result;
  }
  async function action(fn) {
    if(busy) return; busy = true; status.textContent = '处理中…'; if(tripButton) tripButton.disabled = true;
    try { await fn(); if(status.textContent === '处理中…') status.textContent = '完成'; } catch(e) { status.textContent = e.message; }
    finally { busy = false; if(tripButton) tripButton.disabled = cfg?.archived || tripButton.dataset.running === 'true'; }
  }
  function field(parent,label,key,type='text',target=cfg) {
    const wrap = node('label',undefined,parent); wrap.className = type === 'checkbox' ? 'outing-check' : 'outing-field'; node('span',label,wrap);
    const input = node(type === 'textarea' ? 'textarea' : 'input',undefined,wrap);
    if(type !== 'textarea') input.type = type; else input.rows = 3;
    if(type === 'checkbox') input.checked = target[key]; else input.value = target[key] ?? '';
    if(type === 'password') input.autocomplete = 'new-password';
    input.oninput = () => target[key] = type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value; return input;
  }
  function select(parent,label,key,options,target=cfg) {
    const wrap = node('label',undefined,parent); wrap.className = 'outing-field'; node('span',label,wrap); const input = node('select',undefined,wrap);
    for(const [v,t] of options) { const o = node('option',t,input); o.value = v; }
    input.value = target[key] || ''; input.onchange = () => target[key] = input.value; return input;
  }
  function button(parent,label,fn,primary=false) { const b = node('button',label,parent); b.type = 'button'; if(primary) b.className = 'primary-button'; b.onclick = () => action(fn); return b; }
  function section(title) { const s = node('section'); s.className = 'outing-section'; node('h3',title,s); return s; }
  function details(parent,title) { const d = node('details',undefined,parent); node('summary',title,d); const inner = node('div',undefined,d); inner.className = 'outing-details'; return inner; }
  async function save() {
    cfg.llm_profile_id ||= null; const saved = await api('/settings','PUT',cfg);
    for(const d of cfg.destinations) Object.assign(d,saved.destinations.find(s => s.id === d.id));
    Object.assign(cfg,saved,{destinations:cfg.destinations});
  }
  async function records(container) {
    const snapshotCid = cid; const result = await api('/'+encodeURIComponent(cid)+'/runs');
    if(snapshotCid !== cid || !container.isConnected) return; container.replaceChildren();
    const running = result.runs.some(r => r.status === 'running'); tripButton.dataset.running = String(running); tripButton.disabled = cfg.archived || busy || running;
    tripButton.textContent = cfg.archived ? '自主外出已封存' : running ? '她正在外出…' : '让她出去玩一次';
    if(!result.runs.length) node('p','还没有旅行记录。每次真实行动后的笔记保存在「角色记忆 → 自主活动」。',container);
    for(const run of result.runs) {
      const inner = details(container,`${new Date(run.started_at).toLocaleString()} · ${run.trigger === 'manual' ? '你发起的旅行' : '自主旅行'} · ${{running:'正在外出',done:'已结束',error:'执行中断',interrupted:'已中断'}[run.status] || run.status}`);
      node('p',`实际行动 ${run.evidence.length} 次 · 活动笔记 ${run.notes.length} 篇`,inner);
      for(const step of run.steps) if(step.result) node('p',`${step.result.destination_name || names[run.provider] || ''} · ${{browse:'浏览',read_post:'读帖',reply:'留言',surf_web:'搜索'}[step.action] || step.action} · ${step.result.status === 'done' ? '已执行并记录' : '失败，已保留记录'}`,inner);
      if(run.error) node('p',run.error,inner); node('pre',JSON.stringify(run,null,2),details(inner,'执行详情与模型日志'));
    }
  }
  async function render() {
    clearInterval(timer); body.replaceChildren(); cfg.destinations ||= [];
    if(cfg.archived) {
      const notice = section('已封存 · 暂停开发与执行');
      node('p',cfg.archive_reason,notice);
      node('p','保留界面、技能、配置和历史记录供查看；社区连接、手动外出、自动外出和留言均已停用。普通聊天的联网搜索仍可使用。',notice);
    }
    const hero = section('让她带着自己的兴趣出发'); hero.classList.add('outing-hero');
    node('p',cfg.archived ? '以下是封存中的旅行功能界面，暂时只能查看。未来找到合适社区后，可以继续开发手动旅行与自主旅行。' : '你可以邀请她出去玩一次，她自己选择去哪、看什么、何时回来。开启自动外出后，她也能在心跳唤醒时自行决定出门。',hero);
    tripButton = button(hero,'让她出去玩一次',async () => {
      cfg.enabled = true; await save(); await api('/'+encodeURIComponent(cid)+'/depart','POST'); await render();
      status.textContent = '已出发。可以关闭面板，后台会逐次写活动笔记；本次会使用模型／搜索额度。';
    },true);
    node('p',cfg.archived ? '恢复开发并完成验收后，才会开放旅行执行。' : '手动旅行不受自动冷却／安静时段限制；仍遵守并发、每日次数和本次额度上限。',hero);
    const sources = section('她可以去哪里'); node('p','配置允许访问的目的地，选择权交给她。同一次旅行也可以切换社区。',sources);
    const primary = details(sources,'默认目的地 · '+names[cfg.provider]);
    select(primary,'来源','provider',Object.entries(names).filter(([k]) => k !== 'lutopia')); field(primary,'社区 HTTPS 根地址（搜索可留空）','endpoint'); field(primary,cfg.api_key_set ? '账号 Token（已保存，留空保留）' : '账号 Token（依社区读取权限填写）','api_key','password');
    for(const dest of cfg.destinations) {
      const card = node('div',undefined,sources); card.className = 'outing-destination'; node('h4',names[dest.provider],card); field(card,'目的地名称','name','text',dest);
      if(dest.provider === 'lutopia') {
        const p = node('p','登录 Lutopia 后，在 AI 接入页面复制个人 MCP 地址。它含账号凭据，仅保存在本机。目前接入公开浏览／读帖。',card);
        const link = node('a','打开 Lutopia',p); link.href = 'https://lutopia.app/'; link.target = '_blank'; link.rel = 'noopener noreferrer';
        field(card,dest.mcp_url_set ? '个人 MCP 地址（已保存，留空保留）' : '个人 MCP 地址','mcp_url','password',dest);
      } else if(dest.provider !== 'search') { field(card,'社区 HTTPS 根地址','endpoint','text',dest); field(card,dest.api_key_set ? 'Token（已保存，留空保留）' : '账号 Token','api_key','password',dest); }
      button(card,'移除目的地',async () => { cfg.destinations = cfg.destinations.filter(d => d.id !== dest.id); await render(); status.textContent = '已移除，保存后生效'; });
    }
    const addrow = node('div',undefined,sources); addrow.className = 'outing-actions'; const addition = {provider:'lutopia'};
    select(addrow,'新增目的地','provider',Object.entries(names),addition);
    button(addrow,'添加',async () => { if(cfg.destinations.length >= 8) throw new Error('最多添加8个目的地'); cfg.destinations.push({id:crypto.randomUUID(),name:names[addition.provider],provider:addition.provider,endpoint:'',api_key:'',mcp_url:''}); await render(); status.textContent = '填写接入信息后保存'; });
    button(sources,'检查社区连接（不调用模型）',async () => { await save(); const r = await api('/connection','POST'); status.textContent = `连接成功，${r.destinations.map(d => d.name).join('、')} 返回 ${r.public_posts} 条资料，未调用模型`; });
    const automatic = section('她也可以自己出门'); field(automatic,cfg.archived ? '允许外出（封存期间不可启用）' : '允许外出（总开关，手动按钮可重新启用）','enabled','checkbox'); field(automatic,'允许心跳唤醒后自主决定外出','automatic','checkbox');
    const check = field(automatic,'当前会话允许自动外出','selected','checkbox',{selected:cfg.conversation_ids.includes(cid)});
    check.oninput = () => cfg.conversation_ids = check.checked ? [...new Set([...cfg.conversation_ids,cid])] : cfg.conversation_ids.filter(x => x !== cid);
    node('p',cfg.archived ? '当前心跳仅决定主动发消息或保持沉默，不会触发任何旅行活动。' : '自动外出还需要本会话已开启心跳。手动旅行按钮可独立使用。',automatic);
    const persona = section('她出门时的样子'); field(persona,'公开人格（只写允许对外使用的角色设定）','public_personality','textarea'); field(persona,'她的兴趣','interests'); field(persona,'允许 Mastodon 自主留言（需要 write:statuses 权限）','allow_replies','checkbox');
    node('p','每次行动必须写活动笔记，写完才决定是否继续。外出模型不读取私聊、用户设定或私人记忆；禁止透露任何用户和工作信息。',persona);
    const profiles = await providerApi('/api/provider-profiles'); select(persona,'外出使用的模型','llm_profile_id',[['','跟随当前会话'],...profiles.llm_profiles.filter(p => (p.purpose || 'chat') === 'chat').map(p => [p.id,p.name])]);
    const advanced = details(body,'旅行额度与网络设置'); const grid = node('div',undefined,advanced); grid.className = 'outing-grid';
    for(const [label,key] of [['自动冷却（分钟）','interval_minutes'],['每角色每日最多旅行次数','daily_limit'],['每次最多行动轮数（2–3）','max_steps'],['本次总输出 Token 上限','output_budget'],['自动安静开始小时','quiet_start'],['自动安静结束小时（相同则关闭）','quiet_end']]) field(grid,label,key,'number');
    field(advanced,'社区代理（可选，如 http://127.0.0.1:7890）','proxy_url'); field(advanced,'兼容正在运行的代理 Fake-IP','allow_fake_ip','checkbox'); node('p','是否需要代理取决于实例和网络。输出上限不含输入和供应商内部计费。',advanced);
    button(body,'保存设置',async () => { await save(); await render(); status.textContent = '设置已保存'; },true);
    const skills = details(body,'已搭载的旅行技能'); node('p','探索技能约束选择与隐私，记录技能按实际结果写感受；代码负责执行、保存和限制循环。',skills);
    for(const skill of (await api('/skills')).skills) node('pre',skill.content,details(skills,skill.name === 'explore' ? '探索' : '记录'));
    const history = section('旅行足迹'); const list = node('div',undefined,history); const refresh = button(history,'刷新记录',async () => records(list)); await records(list);
    if(cfg.archived) for(const control of body.querySelectorAll('input,select,textarea,button')) if(control !== refresh) control.disabled = true;
    timer = setInterval(() => { if(dialog.open) records(list).catch(e => status.textContent = e.message); },4000);
  }
  dialog.addEventListener('close',() => clearInterval(timer));
  entry.onclick = () => action(async () => { cid = currentConversation()?.id; if(!cid) throw new Error('请先选择会话'); cfg = await api('/settings'); dialog.showModal(); await render(); });
})();
