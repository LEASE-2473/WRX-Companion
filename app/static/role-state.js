/* 角色状态：结构化状态与正文分离；Profile统一维护。 */
(() => {
  const dialog=document.createElement('dialog');dialog.id='roleStatePanel';dialog.className='manager-dialog';
  dialog.innerHTML='<div class="dialog-header"><div><span class="state-eyebrow">此刻的心情</span><h2>角色状态</h2></div><button id="closeRoleState">关闭</button></div><nav id="roleStateTabs" class="state-tabs"></nav><div class="dialog-scroll"><p id="roleStateStatus" class="hint" role="status"></p><div id="roleStateBody"></div></div>';
  document.body.append(dialog);
  const entry=document.querySelector('[data-open-panel="heartbeatPanel"]');entry.removeAttribute('data-open-panel');entry.textContent='角色状态';entry.id='openRoleState';
  const body=dialog.querySelector('#roleStateBody'),status=dialog.querySelector('#roleStateStatus');
  let tab='general',cid,config,data,profiles=[],manualDirty=false,assessmentBusy=false;
  const node=(tag,text,parent=body)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n;};
  const button=(text,fn,parent=body)=>{const n=node('button',text,parent);n.type='button';n.onclick=()=>act(fn);return n;};
  const field=(label,value,change,type='text',parent=body)=>{const wrap=node('label',label,parent);wrap.className='state-field';const input=node(type==='textarea'?'textarea':'input',undefined,wrap);if(type!=='textarea')input.type=type;else input.rows=7;if(type==='checkbox')input.checked=value;else input.value=value??'';if(type==='number')input.step='any';input.oninput=()=>change(type==='checkbox'?input.checked:type==='number'?Number(input.value):input.value);return input;};
  const select=(label,value,options,change,parent=body)=>{const wrap=node('label',label,parent);wrap.className='state-field';const input=node('select',undefined,wrap);for(const [v,t]of options){const o=node('option',t,input);o.value=v;}input.value=value??'';input.onchange=()=>change(input.value);};
  async function request(path,method='GET',value){const r=await fetch('/api/role-state'+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});const v=await r.json();if(!r.ok)throw new Error(typeof v.detail==='string'?v.detail:JSON.stringify(v.detail));return v;}
  async function act(fn){if(processing||recording){status.textContent='请等待当前回复结束';return;}try{status.textContent='处理中…';await fn();status.textContent='已完成';}catch(e){status.textContent=e.message;}}
  async function refresh(){data=await request('/'+encodeURIComponent(cid));render();}
  async function save(){config=await request('/settings','PUT',config);await refresh();}
  function radar(parent){
    const wrap=node('div',undefined,parent);wrap.className='emotion-radar-wrap';const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 500 470');svg.setAttribute('role','img');svg.setAttribute('aria-label','十二情绪罗盘，四组各三项，强度0至100');wrap.append(svg);
    const point=(i,r)=>{const a=-Math.PI/2+(i+1)*Math.PI/6;return [250+Math.cos(a)*r,230+Math.sin(a)*r];};
    const add=(tag,attrs,text)=>{const e=document.createElementNS(svg.namespaceURI,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);};
    for(let g=0;g<4;g++){const points=[[250,230],...Array.from({length:4},(_,j)=>point(g*3+j-.5,150))];add('polygon',{points:points.map(p=>p.join(',')).join(' '),class:'radar-quadrant quadrant-'+g});}
    for(const value of [25,50,75,100])add('polygon',{points:data.labels.map((_,i)=>point(i,value*1.5).join(',')).join(' '),class:'radar-grid'});
    data.labels.forEach((name,i)=>{const p=point(i,150),t=point(i,183);add('line',{x1:250,y1:230,x2:p[0],y2:p[1],class:'radar-grid'});add('text',{x:t[0],y:t[1],'text-anchor':'middle'},name);add('text',{x:t[0],y:t[1]+16,'text-anchor':'middle',class:'radar-value'},Math.round(data.state.values[name]));});
    add('polygon',{points:data.labels.map((n,i)=>point(i,data.state.values[n]*1.5).join(',')).join(' '),class:'radar-emotion'});
    for(let g=0;g<4;g++)node('span',data.groups[g],wrap).className='quadrant-legend quadrant-'+g;
  }
  function render(){
    body.replaceChildren();dialog.querySelector('#roleStateTabs').replaceChildren();
    for(const [key,label]of [['general','常规'],['contact','主动联系'],['settings','设置'],['logs','日志']]){const b=button(label,async()=>{tab=key;await refresh();},dialog.querySelector('#roleStateTabs'));b.classList.toggle('selected',key===tab);}
    if(tab==='general'){
      manualDirty=false;
      const hero=node('section');hero.className='state-section';node('span',data.state.phase,hero).className='state-phase';node('p',`${currentCharacter()?.name||'角色'} · ${currentConversation()?.name||'会话'} · ${config.idle_minutes}分钟无新对话后进入冷却`,hero);
      const assessButton=button('一键评估当前情绪',async()=>{
        if(assessmentBusy)return;
        assessmentBusy=true;assessButton.disabled=true;
        const target=cid;
        try{
          status.textContent='正在根据角色与当前对话评估全部情绪…';
          const result=await request('/'+encodeURIComponent(target)+'/assess','POST');
          if(result.status==='stale')throw new Error('评估期间聊天或手动数值发生变化，本次结果未覆盖；可重新评估');
          if(cid===target){await refresh();lastStateRefresh=0;void refreshCompanionState();}
        }finally{assessmentBusy=false;assessButton.disabled=false;}
      },hero);
      node('p','调用一次情绪管家所选模型，依据角色设定与最近对话重新填写全部11项情绪并直接应用，精力由时钟计算。不受转冷开关限制。',hero).className='hint';
      radar(hero);
      node('p','情绪是当下强度，不是关系攻略分。点击下面的数值可手动调整；精力由本地时钟计算。',hero).className='hint';
      const grid=node('div',undefined,hero);grid.className='state-value-grid';const draft={};
      data.labels.forEach(name=>{const input=field(name,Math.round(data.state.values[name]),v=>{draft[name]=v;manualDirty=true;},'number',grid);input.min=0;input.max=100;input.step=1;input.disabled=name==='精力';});
      button('保存手动调整',async()=>{const updates=Object.entries(draft).map(([emotion,value])=>({emotion,operation:'set',value}));if(!updates.length)return;await request('/'+cid,'PATCH',{updates});await refresh();},hero);
      const motives=node('section');motives.className='state-section';node('h3','动机参考（不决定心跳行动）',motives);for(const [name,value]of Object.entries(data.state.motives))node('p',`${name} ${value.toFixed(1)} / 100`,motives);
    }else if(tab==='contact'){
      const old=document.getElementById('heartbeatPanel');const contents=old.querySelector('.dialog-scroll');body.append(contents);contents.classList.add('state-contact-content');void loadHeartbeat().catch(e=>status.textContent=e.message);
    }else if(tab==='settings'){
      const section=(title)=>{const s=node('section');s.className='state-section';node('h3',title,s);return s;};
      let s=section('聊天与冷却');field('启用角色情绪',config.enabled,v=>config.enabled=v,'checkbox',s);field('无新对话转冷时间（分钟）',config.idle_minutes,v=>config.idle_minutes=v,'number',s);
      field('允许对话模型暂时沉默',config.allow_silence,v=>config.allow_silence=v,'checkbox',s);
      field('情绪理解提示词（Gemini版本可粘贴到这里）',config.chat_prompt,v=>config.chat_prompt=v,'textarea',s);
      s=section('情绪管家 · 每次转为冷却仅总结一次');field('启用转冷总结（会调用模型）',config.summary_enabled,v=>config.summary_enabled=v,'checkbox',s);
      select('使用的 LLM Profile',config.llm_profile_id,[['','跟随当前会话 LLM'],...profiles.filter(p=>(p.purpose||'chat')==='chat').map(p=>[p.id,p.name])],v=>config.llm_profile_id=v||null,s);
      button('去模型与语音管理 Profile',async()=>{dialog.close();renderAllProviderProfiles();document.getElementById('providerPanel').showModal();},s);
      field('总结读取最近消息条数',config.history_limit,v=>config.history_limit=v,'number',s);field('情绪状态总结提示词',config.summary_prompt,v=>config.summary_prompt=v,'textarea',s);
      field('一键评估提示词',config.assessment_prompt,v=>config.assessment_prompt=v,'textarea',s);
      node('p','聊天变化项没有1–2项限制，可以同时更新全部11项；一键评估全量填写目标强度，转冷总结仍只填方向与程度。固定协议由后端附加。',s).className='hint';
      s=section('时间演算与主动联系参数');
      select('主动联系 LLM Profile',config.contact_llm_profile_id,[['','跟随当前会话 LLM'],...profiles.filter(p=>(p.purpose||'chat')==='chat').map(p=>[p.id,p.name])],v=>config.contact_llm_profile_id=v||null,s);
      for(const [key,label]of [['state_hours','管家状态有效期（小时）'],['step_per_hour','每级状态变化 / 小时'],['recovery_per_hour','到期后恢复 / 小时'],['longing_per_hour','冷却思念增长 / 小时'],['contact_weight','思念联系权重'],['worry_weight','担忧关心权重'],['retreat_weight','生气与低落退缩权重'],['no_action_minutes','两次主动判断最小间隔（分钟）']])field(label,config[key],v=>config[key]=v,'number',s);
      node('p',`联系 = ${config.contact_weight}×思念 + 0.2×爱意 − ${config.retreat_weight}×(生气+低落)；关心 = ${config.worry_weight}×担忧 − 0.1×低落；修复 = 0.8×内疚 + 0.2×爱意 − 0.2×生气；分享 = 0.7×欣喜 + 0.3×期待 − 0.2×低落。各动机限制到0–100，仅供面板参考。心跳将情绪与聊天交给AI自主判断联系或沉默，不使用动机阈值。`,s).className='hint';
      node('p','聊天期间不做默认恢复。转冷后有效状态按方向×程度×每级速度推进；到期才恢复。思念在无有效状态时累积。配置是实验初值，可调整。',s).className='hint';button('保存角色状态设置',save);
    }else{
      node('h3','状态变化与管家任务');if(!data.logs.length)node('p','尚无情绪变化记录');for(const record of data.logs){const d=node('details');node('summary',`${new Date(record.at).toLocaleString()} · ${record.source} · ${record.status||'数值更新'}`,d);node('pre',JSON.stringify(record,null,2),d);}
      for(const job of data.summaries){const d=node('details');node('summary','冷却总结 · '+job.status,d);node('pre',JSON.stringify(JSON.parse(job.document),null,2),d);}
    }
  }
  // 主动联系原表单保留事件监听器，切页时移回原容器，避免删除后失去控制。
  const baseRender=render;render=function(){const contents=dialog.querySelector('.state-contact-content');if(contents){contents.classList.remove('state-contact-content');document.getElementById('heartbeatPanel').append(contents);}baseRender();};
  entry.onclick=()=>act(async()=>{cid=activeConversationId;if(!cid)throw new Error('请先选择会话');config=await request('/settings');settings.provider_profiles=await providerApi('/api/provider-profiles');profiles=settings.provider_profiles.llm_profiles;tab='general';await refresh();dialog.showModal();});
  dialog.querySelector('#closeRoleState').onclick=()=>dialog.close();
  setInterval(()=>{if(dialog.open&&tab==='general'&&cid===activeConversationId&&!manualDirty&&!assessmentBusy&&!document.activeElement?.matches('input,textarea,select'))void refresh().catch(e=>status.textContent=e.message);else if(dialog.open&&cid!==activeConversationId)dialog.close();},30000);
})();
