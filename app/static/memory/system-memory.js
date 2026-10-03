/* 系统表格与后台追溯；用户内容只通过textContent/value显示。 */
(() => {
  const dialog=document.createElement('dialog'); dialog.className='manager-dialog'; dialog.id='systemMemoryPanel';
  dialog.innerHTML='<div class="dialog-header"><h2>系统记忆</h2><button type="button">关闭</button></div><div class="dialog-scroll"><p role="status"></p><div class="system-memory-body"></div></div>';
  document.body.append(dialog); dialog.querySelector('button').onclick=()=>dialog.close();
  const entry=document.createElement('button'); entry.textContent='系统记忆';
  document.querySelector('[data-open-panel="promptPanel"]').parentElement.append(entry);
  let character,cid,config,data,profiles=[],busy=false,tableKind='summary';
  const body=dialog.querySelector('.system-memory-body'),status=dialog.querySelector('[role="status"]');
  const tables={summary:['聊天总结',{content:'概述',tag:'标签'}],person:['人物记忆',{name:'姓名',relationship:'关系',history:'历史事件',impression:'用户印象'}],item:['物品',{name:'名称',description:'描述',location:'位置'}],agreement:['约定',{content:'概述'}]};
  const node=(tag,text,parent=body)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n;};
  async function api(path,method='GET',value){const r=await fetch('/api/system-memory'+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;}
  async function bookApi(path,method='GET',value){const r=await fetch('/api/role-memory'+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;}
  async function act(fn){if(busy)return;busy=true;status.textContent='处理中…';try{await fn();status.textContent='完成';}catch(e){status.textContent=e.message;}finally{busy=false;}}
  const button=(label,fn,parent=body)=>{const n=node('button',label,parent);n.type='button';n.onclick=()=>act(fn);return n;};
  function field(label,value,type,parent,change){const l=node('label',label,parent),n=node(type==='textarea'?'textarea':'input',undefined,l);if(type!=='textarea')n.type=type;if(type==='checkbox')n.checked=value;else n.value=value??'';n.oninput=()=>change(type==='checkbox'?n.checked:type==='number'?Number(n.value):n.value);return n;}
  function select(label,value,options,parent,change){const l=node('label',label,parent),s=node('select',undefined,l);for(const [v,t]of options){const o=node('option',t,s);o.value=v;}s.value=value;s.onchange=()=>change(s.value);}
  async function refresh(render=true){const wasRunning=data?.progress?.status==='running',books=data?.books||[];data=await api('/'+encodeURIComponent(character)+'?conversation_id='+encodeURIComponent(cid));data.books=books;if(render||(wasRunning&&data.progress?.status!=='running')){const records=await bookApi('/'+encodeURIComponent(character)+'?conversation_id='+encodeURIComponent(cid));data.books=records.records.filter(r=>r.kind==='book');draw();}else updateProgress();}
  function updateProgress(){const p=data.progress;const el=body.querySelector('.system-progress');if(el)el.textContent=p?`${p.status} · ${p.completed}/${p.total} · ${p.range||''}${p.error?' · '+p.error:''}`:'暂无追溯任务';}
  function draw(){body.replaceChildren();dialog.querySelector('h2').textContent='系统记忆 · '+(currentCharacter()?.name||character);
    if(tableKind!=='book'){
    const settings=node('details');node('summary','自动填表与提示词',settings);const grid=node('div',undefined,settings);grid.className='system-grid';
    field('启用自动填表',config.enabled,'checkbox',grid,v=>config.enabled=v);
    field('总结间隔（分钟）',config.interval_minutes,'number',grid,v=>config.interval_minutes=v);
    field('批次请求间隔（秒）',config.delay_seconds,'number',grid,v=>config.delay_seconds=v);
    node('p','系统记忆按角色共享，会话仅保留来源。',grid);
    select('填表模型',config.llm_profile_id||'',[['','沿用日记任务模型'],...profiles.map(p=>[p.id,p.name])],grid,v=>config.llm_profile_id=v||null);
    field('第三人称填表提示词',config.prompt,'textarea',settings,v=>config.prompt=v);
    button('保存设置',async()=>{config=await api('/settings','PUT',config);},settings);
    const scan=node('section');node('h3','按显示时间追溯',scan);node('p','直接读取原始聊天，含开始、不含结束，不受聊天上下文过滤影响。默认角色范围涵盖该角色所有会话；每批提交成功后再处理下一批。',scan);
    let start='',end='';const range=node('div',undefined,scan);range.className='system-grid';
    field('开始（当前会话时区）',start,'datetime-local',range,v=>start=v);field('结束（当前会话时区）',end,'datetime-local',range,v=>end=v);
    button('开始分批追溯',async()=>{if(!start||!end)throw Error('请选择开始和结束时间');config=await api('/settings','PUT',config);await api('/'+character+'/scan','POST',{conversation_id:cid,start,end});await refresh(false);},scan);
    button('停止追溯',async()=>{await api('/'+character+'/cancel','POST');await refresh(false);},scan);
    button('刷新表格',()=>refresh(),scan);node('p','',scan).className='system-progress';updateProgress();
    }
    const tabs=node('nav');tabs.className='system-tabs';tabs.setAttribute('aria-label','系统记忆表');for(const [kind,[label]]of Object.entries({...tables,book:['外部世界书']})){const count=kind==='book'?data.books.length:data.rows.filter(r=>r.kind===kind).length;const b=button(label+' '+count,async()=>{tableKind=kind;draw();},tabs);b.setAttribute('aria-pressed',String(tableKind===kind));}
    if(tableKind==='book'){drawBooks();return;}
    for(const [kind,[label,columns]]of Object.entries(tables)){if(kind!==tableKind)continue;const section=node('section');node('h3',label,section);const wrap=node('div',undefined,section);wrap.className='system-table-wrap';const table=node('table',undefined,wrap),head=node('tr',undefined,node('thead',undefined,table));node('th','序号',head);node('th',kind==='agreement'?'约定来源时间段':'来源时间段',head);Object.values(columns).forEach(x=>node('th',x,head));node('th','状态／操作',head);const tbody=node('tbody',undefined,table);
      const rows=data.rows.filter(r=>r.kind===kind);if(!rows.length)node('p','暂无记录',section);
      for(const row of rows){const tr=node('tr',undefined,tbody);node('td',row.sequence,tr);node('td',row.range_start+' → '+row.range_end,tr);Object.keys(columns).forEach(k=>node('td',row[k],tr));const ops=node('td',undefined,tr);node('span',(row.mode==='hot'?'热':'冷')+' · '+(row.vectorized?'向量就绪':'向量未就绪'),ops);
        button(row.mode==='hot'?'转冷':'转热',async()=>{await api(`/${character}/${row.id}/mode`,'POST',{conversation_id:cid,mode:row.mode==='hot'?'cold':'hot'});await refresh();},ops);
        button('编辑',async()=>{const edit=node('tr',undefined,tbody),cell=node('td',undefined,edit);cell.colSpan=Object.keys(columns).length+3;const draft={};for(const [k,title]of Object.entries(columns)){draft[k]=row[k];field(title,row[k],'textarea',cell,v=>draft[k]=v);}button('保存',async()=>{await api(`/${character}/${row.id}?conversation_id=${encodeURIComponent(cid)}`,'PUT',draft);await refresh();},cell);button('收起',async()=>edit.remove(),cell);},ops);
        button('删除',async()=>{if(!confirm('永久删除这条系统记忆？'))return;await api(`/${character}/${row.id}?conversation_id=${encodeURIComponent(cid)}`,'DELETE');await refresh();},ops);
      }
    }
    const jobs=node('details');node('summary','最近批次与失败原因',jobs);for(const job of data.batches)node('p',`${job.range_start} → ${job.range_end} · ${job.status}${job.error?' · '+job.error:''}`,jobs);
  }
  function drawBooks(){
    const section=node('section');node('h3','外部世界书',section);
    node('p','导入资料后按切片向量召回。已有资料继续使用原数据；外部世界书不参与自动填表。',section);
    let name='',text='',separator='---',scope='character';
    const grid=node('div',undefined,section);grid.className='system-grid';
    const nameInput=field('知识书名称',name,'text',grid,v=>name=v);
    field('切片分隔符（独占一行）',separator,'text',grid,v=>separator=v);
    select('绑定范围',scope,[['character','角色共享'],['conversation','当前会话']],grid,v=>scope=v);
    const file=field('导入 TXT／Markdown','','file',grid,()=>{});file.accept='.txt,.md';
    const textInput=field('或粘贴内容',text,'textarea',section,v=>text=v);
    file.onchange=()=>act(async()=>{const selected=file.files?.[0];if(!selected)return;text=await selected.text();textInput.value=text;if(!name){name=selected.name;nameInput.value=name;}});
    button('导入（暂不调用 API）',async()=>{await bookApi(`/${character}/import/book`,'POST',{conversation_id:cid,name,text,separator,scope});await refresh();},section);
    button('向量化所有待处理切片',async()=>{for(const row of data.books.filter(r=>!r.vectorized))await bookApi(`/${character}/records/${row.id}/mode`,'POST',{mode:'cold'});await refresh();},section);
    button('刷新资料',()=>refresh(),section);
    node('p','Embedding／Rerank与日记及系统表共用向量配置，可在角色记忆的设置页调整。',section);
    if(!data.books.length)node('p','暂无外部世界书，导入文件或粘贴资料后显示切片。');
    for(const record of data.books){
      const card=node('details');node('summary',(record.tags.join(' / ')||'未命名知识书')+' · '+(record.vectorized?'已向量化':'待向量化'),card);
      node('p',`绑定：${record.scope==='character'?'角色共享':'会话私有'}${record.conversation_id===cid?'':' · 来自其他会话'}`,card);
      const draft={...record};
      field('正文',draft.content,'textarea',card,v=>draft.content=v);
      field('资料标签（逗号分隔）',draft.tags.join(','),'text',card,v=>draft.tags=v.split(',').map(s=>s.trim()).filter(Boolean));
      field('检索关键词（逗号分隔）',(draft.keywords||[]).join(','),'text',card,v=>draft.keywords=v.split(',').map(s=>s.trim()).filter(Boolean));
      select('绑定范围',draft.scope,[['character','角色共享'],['conversation','来源会话']],card,v=>draft.scope=v);
      button('保存编辑',async()=>{await bookApi(`/${character}/book/${record.id}`,'PUT',draft);await refresh();},card);
      button('生成／更新向量',async()=>{await bookApi(`/${character}/records/${record.id}/mode`,'POST',{mode:'cold'});await refresh();},card);
    }
  }
  entry.onclick=()=>act(async()=>{character=currentCharacter()?.id;cid=currentConversation()?.id;if(!character||!cid)throw Error('请先选择角色和会话');config=await api('/settings');const p=await(await fetch('/api/provider-profiles')).json();profiles=p.llm_profiles||[];await refresh();dialog.showModal();});
  setInterval(async()=>{if(dialog.open&&!busy){try{await refresh(false);}catch(e){status.textContent=e.message;}}},3000);
})();
