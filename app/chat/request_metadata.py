"""请求仅保留执行判定与实体关联，不保存回复或整轮结果快照。"""
def execution_metadata(value):
    value=value or {}
    metadata={}
    if isinstance(value.get('action'),str): metadata['action']=value['action']
    if isinstance(value.get('latency_seconds'),(int,float)): metadata['latency_seconds']=value['latency_seconds']
    message=value.get('assistant_message')
    if isinstance(message,dict) and message.get('id'): metadata['reply_message_id']=message['id']
    change=value.get('emotion_change')
    if isinstance(change,dict):
        metadata['emotion_change']={'status':change.get('status','unknown'),
            'changes':[{k:item[k] for k in ('emotion','before','after') if k in item} for item in change.get('changes',[]) if isinstance(item,dict)]}
    autonomy=value.get('autonomy')
    if isinstance(autonomy,dict): metadata['autonomy']={k:v for k,v in autonomy.items() if k in ('status','run_id','error')}
    calls=((value.get('debug') or {}).get('prompt_trace') or {}).get('role_tools',{}).get('calls',[])
    for call in calls:
        if call.get('name')!='toy_get_state' and call.get('status')=='accepted':
            metadata['device_effect']={'status':'accepted','name':call.get('name')}
            break
    return metadata
