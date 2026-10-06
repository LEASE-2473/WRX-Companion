// 唯一用户的全局信息；与当前角色、会话选择无关。
(() => {
  let profile;
  const entries = $('userProfileEntries');
  function entry(value = {tag: '', keywords: [], content: ''}) {
    const card = document.createElement('details');
    card.className = 'profile-tag';
    const title = document.createElement('summary'); title.textContent = value.tag || '新标签'; card.append(title);
    const controls = {};
    for (const [key, caption] of [['tag', '标签'], ['keywords', '关键词（逗号分隔）'], ['content', '画像总结']]) {
      const label = document.createElement('label'); label.textContent = caption;
      const input = document.createElement(key === 'content' ? 'textarea' : 'input');
      input.value = key === 'keywords' ? value.keywords.join('，') : value[key];
      if (key === 'content') input.rows = 5;
      controls[key] = input; label.append(input); card.append(label);
    }
    function updateTag() {
      const name = controls.tag.value.trim() || '新标签';
      title.textContent = name;
      let hash = 0; for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
      card.dataset.color = String(hash % 6);
    }
    controls.tag.oninput = updateTag; updateTag();
    card.addEventListener('toggle', () => {
      if (card.open) for (const other of entries.children) if (other !== card) other.open = false;
    });
    const remove = document.createElement('button'); remove.textContent = '删除标签'; remove.onclick = () => card.remove(); card.append(remove);
    card.profileValue = () => ({tag: controls.tag.value.trim(), keywords: controls.keywords.value.split(/[,，\n]/).map(s => s.trim()).filter(Boolean), content: controls.content.value});
    entries.append(card);
    if (!value.tag) card.open = true;
  }
  async function load() {
    const [data, providers] = await Promise.all([companionApi('/api/user-profile'), companionApi('/api/provider-profiles')]);
    profile = data.profile; window.wrxUserName = profile.name;
    $('userProfileName').value = profile.name; $('userProfileCore').value = profile.core;
    $('userProfileEnabled').checked = profile.summary_enabled; $('userProfileHour').value = profile.summary_hour;
    $('userProfilePrompt').value = profile.summary_prompt;
    characterOptions($('userProfileModel'), providers.llm_profiles, profile.llm_profile_id, '跟随全局 LLM（不跟随角色）');
    entries.replaceChildren(); profile.entries.forEach(entry);
    const candidates = $('userProfileCandidates'); candidates.replaceChildren();
    for (const candidate of data.candidates) {
      const row = document.createElement('details'); const title = document.createElement('summary'); title.textContent = candidate.tag;
      const body = document.createElement('p'); body.textContent = candidate.content;
      const remove = document.createElement('button'); remove.textContent = '忽略候选';
      remove.onclick = async () => { try { await companionApi(`/api/user-profile/candidates/${candidate.id}`, undefined, 'DELETE'); row.remove(); } catch (e) { $('userProfileState').textContent = e.message; } };
      row.append(title, body, remove); candidates.append(row);
    }
    if (!data.candidates.length) candidates.textContent = '暂无待整理候选';
    const statuses = {done:'已完成', running:'整理中', error:'失败，请检查模型设置或输出格式', interrupted:'已中断，可手动重试', stale:'期间资料发生变化，结果未覆盖', empty:'无材料', already_processed:'该日已整理或正在整理'};
    $('userProfileJobs').textContent = data.jobs.map(j => `${j.date}：${statuses[j.status] || j.status}`).join('\n') || '暂无整理记录';
    if (!$('userProfileDate').value) $('userProfileDate').value = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', {timeZone: 'Asia/Shanghai'});
  }
  document.querySelector('[data-open-panel="userInfoPanel"]').addEventListener('click', () => load().catch(e => { $('userProfileState').textContent = e.message; }));
  $('addUserProfileEntry').onclick = () => entry();
  $('exportUserProfile').onclick = async () => {
    try {
      const {profile: saved} = await companionApi('/api/user-profile');
      const blob = new Blob([JSON.stringify({name:saved.name, core:saved.core, entries:saved.entries}, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = 'wrx-user-profile.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      $('userProfileState').textContent = '已导出已保存的用户资料';
    } catch (e) { $('userProfileState').textContent = e.message; }
  };
  $('importUserProfile').onclick = () => { $('userProfileFile').value = ''; $('userProfileFile').click(); };
  $('userProfileFile').onchange = async () => {
    const file = $('userProfileFile').files[0]; if (!file) return;
    try {
      if (!profile) throw Error('请等待用户信息加载完成');
      if (file.size > 5 * 1024 * 1024) throw Error('画像文件最多5MB');
      const value = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
      const incoming = value.profile || value;
      if (typeof incoming.name !== 'string' || typeof incoming.core !== 'string' || !Array.isArray(incoming.entries)) throw Error('JSON需包含name、core、entries');
      if (!confirm(`导入 ${incoming.entries.length} 个标签，将替换称呼、核心和全部标签，以及本页未保存的编辑。模型、每日整理设置和候选保留。导入前资料会自动备份。是否导入？`)) return;
      await companionApi('/api/user-profile/import', {name:incoming.name, core:incoming.core, entries:incoming.entries, revision:profile.revision}, 'POST');
      await load(); renderConversation(); $('userProfileState').textContent = '已导入保存，全局生效';
    } catch (e) { $('userProfileState').textContent = e.message; }
  };
  $('saveUserProfile').onclick = async () => {
    try {
      const value = {...profile, name: $('userProfileName').value, core: $('userProfileCore').value, entries: [...entries.children].map(c => c.profileValue()), summary_enabled: $('userProfileEnabled').checked, summary_hour: Number($('userProfileHour').value), llm_profile_id: $('userProfileModel').value || null, summary_prompt: $('userProfilePrompt').value};
      profile = await companionApi('/api/user-profile', value, 'PUT'); window.wrxUserName = profile.name;
      renderConversation(); $('userProfileState').textContent = '已保存，全局生效；从下一轮使用';
    } catch (e) { $('userProfileState').textContent = e.message; }
  };
  $('summarizeUserProfile').onclick = async () => {
    const button = $('summarizeUserProfile'); button.disabled = true;
    try {
      $('userProfileState').textContent = '正在后台整理…（使用已保存的模型设置）';
      const result = await companionApi(`/api/user-profile/summarize/${$('userProfileDate').value}`, {}, 'POST');
      await load(); $('userProfileState').textContent = `整理结果：${({done:'已完成',error:'失败，请检查模型设置或输出格式',stale:'资料已变化，旧结果未覆盖',empty:'无材料',already_processed:'该日已整理或正在整理'})[result.status] || result.status}`;
    } catch (e) { $('userProfileState').textContent = e.message; }
    finally { button.disabled = false; }
  };
  companionApi('/api/user-profile').then(data => { window.wrxUserName = data.profile.name; if (activeConversationId) renderConversation(); }).catch(() => {});
})();
