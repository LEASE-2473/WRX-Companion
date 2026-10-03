"""在独立副本迁移存储格式；不启动应用、不调用模型或设备。"""
import argparse
from contextlib import closing
import hashlib
import json
import re
from pathlib import Path
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.common.identity import new_id, valid_id
from app.common.time_format import normalize_times, utc_seconds
from app.chat.storage_format import compact, initialize_requests, sanitize_images, initialize_relationships
from app.chat import images
from app.chat.maintenance import clean_database

# 实体身份白名单；任务去重键、模型签名、供应商资源和整数主键不在此列。
ENTITIES = {'characters':'id','conversations':'id','messages':'id','requests':'id',
            'diaries':'memory_id','ai_notes':'memory_id','shared_records':'memory_id',
            'external_memory_chunks':'memory_id','event_tags':'tag_id',
            'system_memories':'id','activity_runs':'id','deleted_memories':'memory_id','images':'id'}
REFERENCES = {'id','character_id','conversation_id','parent_conversation_id','branch_message_id',
              'request_id','message_id','memory_id','source_id','diary_id','tag_id','event_tag_id','activity_id','origin_id'}
JSON_COLUMNS = {'document','result','execution','debug','heartbeat','extra_usage','execution_result','unresolved_hooks','sources'}
PROSE = {'content','name','title','history','impression','description','personality','background',
         'system_prompt','persona','relationship','speaking_style','raw','llm_raw','reply','normalized_reply'}


def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare(source_dir, output_dir, now=None):
    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output_dir.exists() or source_dir == output_dir or source_dir in output_dir.parents or output_dir in source_dir.parents:
        raise ValueError('输出目录必须独立且不存在')
    source = source_dir/'companion.sqlite3'
    original = sha(source)
    now = now or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True)
    target = output_dir/'companion.sqlite3'
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(target)) as db:
        src.backup(db)
    configs = {}
    source_hashes = {}
    for path in source_dir.iterdir():
        if path.is_file() and path.name not in ('companion.sqlite3','companion.sqlite3-wal','companion.sqlite3-shm'):
            source_hashes[path.name] = sha(path)
            if path.suffix == '.json': configs[path.name] = json.loads(path.read_text(encoding='utf-8-sig'))
            else: shutil.copy2(path,output_dir/path.name)
    mapping = {}
    used = set()
    def register(old):
        if not isinstance(old,str) or not old or old == 'default': return
        if old not in mapping:
            fresh = old if valid_id(old) else new_id(lambda value: value in used)
            mapping[old] = fresh; used.add(fresh)
    def collect(value, parent=''):
        if isinstance(value,dict):
            # 配置集合中的id为实体身份；prompt identifier为协议槽位，独立分类。
            if 'id' in value and parent not in ('raw_fields',): register(value['id'])
            for key,item in value.items():
                if key != 'raw_fields': collect(item,key)
        elif isinstance(value,list):
            for item in value: collect(item,parent)
    def rewrite(value,key=''):
        if isinstance(value,dict): return {mapping.get(k,k):rewrite(v,k) for k,v in value.items()}
        if isinstance(value,list): return [rewrite(v,key) for v in value]
        if isinstance(value,str):
            if value in mapping and key not in PROSE: return mapping[value]
            if key in ('epoch','id','memory_job_id') or key.endswith('_key'):
                for old,fresh in sorted(mapping.items(),key=lambda item:-len(item[0])):
                    value=value.replace(old,fresh)
                if key=='epoch' and ':' in value:
                    head,tail=value.split(':',1)
                    value=head+':'+normalize_times(tail)
            return normalize_times(value) if key not in PROSE else value
        return value
    with closing(sqlite3.connect(target)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=DELETE')
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
        before={t:db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        sequence_before=[tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence')]
        branch_before=[tuple(r) for r in db.execute('SELECT conversation_id,parent_conversation_id,branch_message_id FROM conversation_branches ORDER BY rowid')] if 'conversation_branches' in tables else [tuple(r) for r in db.execute('SELECT id,parent_conversation_id,branch_message_id FROM conversations WHERE parent_conversation_id IS NOT NULL ORDER BY rowid')] if 'parent_conversation_id' in {r[1] for r in db.execute('PRAGMA table_info(conversations)')} else []
        content_before={t:[tuple(r) for r in db.execute(f'SELECT content FROM "{t}" ORDER BY rowid')] for t in ('diaries','ai_notes','shared_records','external_memory_chunks','system_memories') if t in tables}
        message_before={r['id']:(r['role'],json.loads(r['document']).get('content',''),json.loads(r['document']).get('source','web'),normalize_times(json.loads(r['document']).get('timestamp',''))) for r in db.execute('SELECT id,role,document FROM messages')}
        vectors_before=[tuple(r) for r in db.execute('SELECT vector,model_signature,index_state FROM memory_vectors ORDER BY rowid')]
        verified_legacy_actions=[]
        old_request_columns={r[1] for r in db.execute('PRAGMA table_info(requests)')}
        for request in db.execute('SELECT * FROM requests').fetchall():
            if 'fingerprint_version' in old_request_columns and request['fingerprint_version']>=2: continue
            resend=db.execute('SELECT message_id,content FROM resends WHERE request_id=?',(request['id'],)).fetchone()
            regen=db.execute('SELECT message_id FROM regenerations WHERE request_id=?',(request['id'],)).fetchone()
            if not resend and not regen: continue
            if resend: user=db.execute('SELECT id,document FROM messages WHERE id=?',(resend['message_id'],)).fetchone()
            else: user=db.execute("SELECT id,document FROM messages WHERE conversation_id=? AND role='user' AND sequence<(SELECT sequence FROM messages WHERE id=?) ORDER BY sequence DESC LIMIT 1",(request['conversation_id'],regen['message_id'])).fetchone()
            if not user: continue
            doc=json.loads(user['document']);text=resend['content'] if resend else doc.get('content','')
            tz=db.execute('SELECT timezone FROM conversations WHERE id=?',(request['conversation_id'],)).fetchone()[0]
            original_fingerprint=request['fingerprint'].hex() if isinstance(request['fingerprint'],bytes) else request['fingerprint']
            matched_mode=None
            for mode in ('AUTO','ON','OFF'):
                for attachments in (doc.get('images',[]),[]):
                    payload=[request['conversation_id'],text,tz,request['source'],mode]+([regen['message_id']] if regen and not resend else [])+([attachments] if attachments else [])+(['resend',resend['message_id']] if resend else [])
                    if hashlib.sha256(encode(payload).encode()).hexdigest()==original_fingerprint: matched_mode=mode
            if matched_mode:
                verified_legacy_actions.append(dict(request_id=request['id'],conversation_id=request['conversation_id'],text=text,tz=tz,source=request['source'],mode=matched_mode,user_id=user['id'],regen=regen['message_id'] if regen and not resend else None,resend=resend['message_id'] if resend else None,original=original_fingerprint))
        orphan_sources_before={r[0] for r in db.execute('SELECT DISTINCT source_id FROM memory_sources WHERE source_id NOT IN (SELECT id FROM messages) AND source_id NOT IN (SELECT memory_id FROM diaries) AND source_id NOT IN (SELECT memory_id FROM ai_notes) AND source_id NOT IN (SELECT memory_id FROM shared_records)')}
        for table,column in ENTITIES.items():
            if table in tables:
                for row in db.execute(f'SELECT "{column}" FROM "{table}"'): register(row[0])
        # 应用层来源可能指向用户早先删除的消息；仍转换身份，保留其既有缺失状态。
        for table in tables:
            columns={r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            for column in columns & (REFERENCES-{'id'}):
                for row in db.execute(f'SELECT "{column}" FROM "{table}"'):
                    if row[0] and row[0]!='default': register(row[0])
        for value in configs.values(): collect(value)
        for value in configs.values():
            def collect_prompt_ids(node):
                if isinstance(node,dict):
                    identifier=node.get('identifier')
                    if isinstance(identifier,str) and (re.fullmatch(r'[0-9a-fA-F-]{36}',identifier) or identifier.startswith('prompt-')): register(identifier)
                    for k,v in node.items():
                        if k!='raw_fields': collect_prompt_ids(v)
                elif isinstance(node,list):
                    for v in node: collect_prompt_ids(v)
            collect_prompt_ids(value)
        # 删除恢复快照中已不存在的身份也必须迁移。
        if 'deleted_memories' in tables:
            for row in db.execute('SELECT document FROM deleted_memories'): collect(json.loads(row[0]))
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        if 'origin_id' not in {r[1] for r in db.execute('PRAGMA table_info(messages)')}:
            db.execute('ALTER TABLE messages ADD COLUMN origin_id TEXT')
            db.execute('UPDATE messages SET origin_id=id')
            # 分支按父会话前缀对应，保留原始身份，避免秒级相同文本被误去重。
            branch_rows=db.execute('SELECT conversation_id,parent_conversation_id FROM conversation_branches ORDER BY rowid').fetchall() if 'conversation_branches' in tables else db.execute('SELECT id,parent_conversation_id FROM conversations WHERE parent_conversation_id IS NOT NULL ORDER BY rowid').fetchall() if 'parent_conversation_id' in {r[1] for r in db.execute('PRAGMA table_info(conversations)')} else []
            for branch in branch_rows:
                parent=db.execute('SELECT id,origin_id,role,document FROM messages WHERE conversation_id=? ORDER BY sequence',(branch[1],)).fetchall()
                children=db.execute('SELECT id,role,document FROM messages WHERE conversation_id=? ORDER BY sequence',(branch[0],)).fetchall()
                for old,child in zip(parent,children):
                    a,b=json.loads(old['document']),json.loads(child['document'])
                    if old['role']!=child['role'] or a.get('content')!=b.get('content') or a.get('timestamp')!=b.get('timestamp'): break
                    db.execute('UPDATE messages SET origin_id=? WHERE id=?',(old['origin_id'] or old['id'],child['id']))
        for table in tables:
            columns=[r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            for row in db.execute(f'SELECT rowid AS _rowid,* FROM "{table}"').fetchall():
                changes={}
                for column in columns:
                    value=row[column]; updated=value
                    if isinstance(value,str):
                        if column in JSON_COLUMNS:
                            try: updated=encode(rewrite(json.loads(value)))
                            except json.JSONDecodeError: pass
                        elif column in REFERENCES:
                            updated=mapping.get(value,value)
                        elif table=='memory_jobs' and column=='id' or column=='epoch':
                            updated=rewrite(value,'id' if column=='id' else column)
                        elif column not in PROSE:
                            updated=normalize_times(value)
                    if updated!=value: changes[column]=updated
                if changes:
                    setters=','.join(f'"{c}"=?' for c in changes)
                    db.execute(f'UPDATE "{table}" SET {setters} WHERE rowid=?',(*changes.values(),row['_rowid']))
        db.commit()
        initialize_requests(db)
        db.commit()
        # 改变列声明为BLOB，同时保持原有行顺序与约束；外键目标仍为requests。
        schema=db.execute("SELECT sql FROM sqlite_master WHERE name='requests'").fetchone()[0]
        if 'fingerprint TEXT' in schema:
            indexes=[r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='requests' AND sql IS NOT NULL")]
            db.execute(re.sub(r'CREATE TABLE\s+["`\[]?requests["`\]]?', 'CREATE TABLE requests_compact', schema, count=1, flags=re.I).replace('fingerprint TEXT','fingerprint BLOB'))
            db.execute('INSERT INTO requests_compact SELECT * FROM requests ORDER BY rowid')
            db.execute('DROP TABLE requests')
            db.execute('ALTER TABLE requests_compact RENAME TO requests')
            for sql in indexes: db.execute(sql)
        # 旧指纹包含旧实体身份：通过完整逆映射保持旧请求的SHA256比较语义。
        fingerprint_entities={r[0] for r in db.execute('SELECT id FROM conversations')}
        fingerprint_entities.update(r[0] for r in db.execute('SELECT message_id FROM regenerations'))
        fingerprint_entities.update(r[0] for r in db.execute('SELECT message_id FROM resends'))
        db.execute("INSERT OR REPLACE INTO settings VALUES ('storage_identity_aliases',?)",(encode({fresh:old for old,fresh in mapping.items() if fresh!=old and fresh in fingerprint_entities}),))
        db.execute("INSERT OR REPLACE INTO settings VALUES ('storage_legacy_requests',?)",(encode([r[0] for r in db.execute('SELECT id FROM requests')]),))
        images.initialize(db)
        migrated_images=0
        for row in db.execute('SELECT id,conversation_id,document FROM messages').fetchall():
            value=json.loads(row['document'])
            urls=value.pop('images',[])
            if urls and not db.execute('SELECT 1 FROM images WHERE message_id=?',(row['id'],)).fetchone():
                images.save(db,row['conversation_id'],row['id'],urls,value.get('timestamp') or utc_seconds(now))
                migrated_images+=len(urls)
            for key in ('id','role','request_id','timezone','local_datetime','usage'): value.pop(key,None)
            db.execute('UPDATE messages SET document=? WHERE id=?',(encode(compact(normalize_times(value))),row['id']))
        # 实录与结果／删除快照不能藏有图片字节副本。
        for table in tables:
            columns={r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            for column in columns & JSON_COLUMNS:
                for row in db.execute(f'SELECT rowid,"{column}" FROM "{table}" WHERE "{column}" LIKE \'%data:image/%\'').fetchall():
                    value=sanitize_images(json.loads(row[1]))
                    db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',(encode(value),row[0]))
        fingerprint_proofs=[]
        for item in verified_legacy_actions:
            rid=mapping.get(item['request_id'],item['request_id']);mid=mapping.get(item['user_id'],item['user_id'])
            refs=[{'image_ref':r[0]} for r in db.execute('SELECT origin_id FROM images WHERE message_id=? ORDER BY rowid',(mid,))]
            regen=mapping.get(item['regen'],item['regen']);resend=mapping.get(item['resend'],item['resend'])
            payload=[mapping.get(item['conversation_id'],item['conversation_id']),item['text'],item['tz'],item['source'],item['mode']]+([regen] if regen else [])+([refs] if refs else [])+(['resend',resend] if resend else [])
            digest=hashlib.sha256(encode(payload).encode()).digest()
            db.execute('UPDATE requests SET fingerprint=?,fingerprint_version=2 WHERE id=?',(digest,rid))
            fingerprint_proofs.append(dict(request_id=rid,original_sha256=item['original'],migrated_sha256=digest.hex()))
        db.execute("UPDATE settings SET document=? WHERE key='storage_legacy_requests'",(encode([r[0] for r in db.execute('SELECT id FROM requests') if r[0] not in {p['request_id'] for p in fingerprint_proofs}]),))
        db.execute('CREATE TABLE IF NOT EXISTS memory_action_keys(request_id TEXT NOT NULL,action_index INTEGER NOT NULL,memory_id TEXT NOT NULL,PRIMARY KEY(request_id,action_index))')
        # 手动任务的材料摘要包含消息身份；身份变更后重算原完整语义的派生键。
        rekeyed_jobs=0
        from app.memory.role import plain_dialogue
        for row in db.execute('SELECT id,document FROM memory_jobs').fetchall():
            pieces=row['id'].split(':');doc=json.loads(row['document'])
            if len(pieces)==5 and doc.get('start') and doc.get('end') and doc.get('source_ids'):
                material=[]
                for mid in doc['source_ids']:
                    message=db.execute('SELECT document FROM messages WHERE id=?',(mid,)).fetchone()
                    if message: material.append((mid,plain_dialogue(json.loads(message[0]).get('content',''))))
                if len(material)==len(doc['source_ids']):
                    selection=hashlib.sha256(encode([doc['start'],doc['end'],material]).encode()).hexdigest()[:20]
                    fresh=':'.join(pieces[:4]+[selection])
                    if fresh!=row['id']:
                        db.execute('UPDATE memory_jobs SET id=? WHERE id=?',(fresh,row['id']));rekeyed_jobs+=1
        db.execute("UPDATE resends SET content='' WHERE request_id IN (SELECT id FROM requests WHERE status='complete')")
        initialize_relationships(db)
        retired={t:before[t] for t in ('conversation_branches','deleted_memories','companion_states') if t in before}
        tables=[t for t in tables if t not in retired]
        cleanup=clean_database(db,now)
        db.commit()
        db.execute('PRAGMA foreign_keys=ON')
        check=[r[0] for r in db.execute('PRAGMA integrity_check')]
        foreign=[tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
        if check!=['ok'] or foreign: raise RuntimeError('迁移完整性／外键验证失败')
        after={r[0]:db.execute(f'SELECT count(*) FROM "{r[0]}"').fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()}
        branches_after={tuple(r) for r in db.execute('SELECT id,parent_conversation_id,branch_message_id FROM conversations WHERE parent_conversation_id IS NOT NULL')}
        if branches_after!={tuple(mapping.get(v,v) for v in row) for row in branch_before}: raise RuntimeError('分支来源迁移不一致')
        if any(before[t]!=after[t] for t in tables if t not in ('emotion_logs','settings','images')): raise RuntimeError('实体数量变化')
        if db.execute('SELECT count(*) FROM images').fetchone()[0]!=before.get('images',0)+migrated_images: raise RuntimeError('附件数量变化')
        if sequence_before != [tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence')]: raise RuntimeError('自增序号变化')
        for table,content in content_before.items():
            if content != [tuple(r) for r in db.execute(f'SELECT content FROM "{table}" ORDER BY rowid')]: raise RuntimeError('记忆正文变化')
        for row in db.execute('SELECT id,role,document FROM messages'):
            doc=json.loads(row['document'])
            old=next((old for old,fresh in mapping.items() if fresh==row['id']),row['id'])
            actual=(row['role'],doc.get('content',''),doc.get('source','web'),doc.get('timestamp',''))
            if actual!=message_before[old]: raise RuntimeError('消息正文／来源／秒级UTC时间校验失败')
            if set(doc)&{'id','request_id','role','usage','timezone','local_datetime','images'}: raise RuntimeError('正文仍有存储元数据副本')
        if vectors_before != [tuple(r) for r in db.execute('SELECT vector,model_signature,index_state FROM memory_vectors ORDER BY rowid')]: raise RuntimeError('向量或模型签名变化')
        orphan_sources_after={r[0] for r in db.execute('SELECT DISTINCT source_id FROM memory_sources WHERE source_id NOT IN (SELECT id FROM messages) AND source_id NOT IN (SELECT memory_id FROM diaries) AND source_id NOT IN (SELECT memory_id FROM ai_notes) AND source_id NOT IN (SELECT memory_id FROM shared_records)')}
        if orphan_sources_after!={mapping.get(v,v) for v in orphan_sources_before}: raise RuntimeError('新增了来源断链')
        for table,column in ENTITIES.items():
            if table in tables and any(r[0]!='default' and not valid_id(r[0]) for r in db.execute(f'SELECT "{column}" FROM "{table}"')): raise RuntimeError('身份格式验证失败')
        if db.execute("SELECT count(*) FROM requests WHERE typeof(fingerprint)!='blob' OR length(fingerprint)!=32").fetchone()[0]: raise RuntimeError('指纹不是完整32字节')
        # 四类系统记忆最终拆表；不影响此前身份／正文／向量保留核验。
        from app.memory import system_schema
        system_schema.initialize(db)
        if 'system_memories' in before:retired['system_memories']=before['system_memories']
        db.commit()
        if [r[0] for r in db.execute('PRAGMA integrity_check')]!=['ok'] or db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('系统记忆拆表完整性失败')
        after={r[0]:db.execute(f'SELECT count(*) FROM "{r[0]}"').fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()}
        db.execute('VACUUM')
    for name,value in configs.items():
        (output_dir/name).write_text(json.dumps(rewrite(value),ensure_ascii=False,indent=2),encoding='utf-8')
    if sha(source)!=original or any(sha(source_dir/name)!=digest for name,digest in source_hashes.items()): raise RuntimeError('源文件发生变化')
    report={'prepared_at':utc_seconds(now),'source_bytes':source.stat().st_size,'output_bytes':target.stat().st_size,
            'source_sha256':original,'output_sha256':sha(target),'identity_mapping_count':len(mapping),
            'rows_before':before,'rows_after':after,'cleanup':cleanup,'migrated_images':migrated_images,
            'integrity_check':'ok','foreign_key_check':'ok','sqlite_sequence_preserved':True,
            'debug_retention_count':20,'fingerprint_bytes':32,'source_unchanged':True,'retired_tables':retired}
    report.update(message_semantics_preserved=True,vectors_preserved=True,
                  inherited_missing_source_identities=len(orphan_sources_before),rekeyed_material_jobs=rekeyed_jobs,
                  verified_rekeyed_action_fingerprints=len(fingerprint_proofs))
    (output_dir.parent/(output_dir.name+'-fingerprint-proofs.json')).write_text(json.dumps(fingerprint_proofs,ensure_ascii=False,indent=2),encoding='utf-8')
    (output_dir.parent/(output_dir.name+'-identity-map.json')).write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    (output_dir.parent/(output_dir.name+'-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.source_dir,args.output_dir),ensure_ascii=False,indent=2))
