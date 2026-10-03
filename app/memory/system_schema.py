"""系统四表显式列；序号为唯一持久身份，向量采用Float64 BLOB。"""
import json
import math
import struct

TABLES={'summary':'system_summary','person':'system_people','item':'system_items','agreement':'system_agreements'}
FIELDS={'summary':('content','tag'),'person':('name','relationship','history','impression'),'item':('name','description','location'),'agreement':('content',)}

def pack(vector):
    if not isinstance(vector,(list,tuple)) or not vector or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector) or not any(x != 0 for x in vector):
        raise ValueError('向量必须是非空有限数值数组')
    return struct.pack('<'+'d'*len(vector),*vector)

def unpack(blob):
    if not blob or len(blob)%8: raise ValueError('无效系统记忆向量')
    result=list(struct.unpack('<'+'d'*(len(blob)//8),blob))
    if not all(math.isfinite(x) for x in result):raise ValueError('无效系统记忆向量')
    return result

def locate(ref):
    try:
        kind,number=ref.split(':')
        sequence=int(number)
        if kind not in TABLES or sequence<1 or str(sequence)!=number:raise ValueError()
        return TABLES[kind],sequence
    except (ValueError,AttributeError):raise ValueError('无效系统记忆表／序号')

def decode(kind,row):
    data=dict(row)
    data.update(kind=kind,id=f"{kind}:{data['sequence']}",scope='character')
    data['vector']=unpack(data['vector']) if data['vector'] else None
    data['vectorized']=bool(data['vectorized'])
    return data

def rows(db,character_id):
    result=[]
    for kind,table in TABLES.items():
        result.extend(decode(kind,r) for r in db.execute(f'SELECT * FROM {table} WHERE character_id=?',(character_id,)))
    return sorted(result,key=lambda r:(r['range_start'],r['kind'],r['sequence']))

def initialize(db):
    db.execute('SAVEPOINT system_four_tables')
    try:
        for old,new in (('_system_items','system_items'),('_system_agreements','system_agreements')):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(old,)).fetchone():
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(new,)).fetchone():
                    raise ValueError('新旧系统表同时存在，请先检查数据，避免序号冲突')
                db.execute(f'ALTER TABLE {old} RENAME TO {new}')
                db.execute(f'DROP INDEX IF EXISTS {old}_character')
        for kind,table in TABLES.items():
            fields=','.join(f"{name} TEXT NOT NULL DEFAULT ''" for name in FIELDS[kind])
            db.execute(f"CREATE TABLE IF NOT EXISTS {table}(sequence INTEGER PRIMARY KEY AUTOINCREMENT,character_id TEXT NOT NULL,conversation_id TEXT NOT NULL,range_start TEXT NOT NULL,range_end TEXT NOT NULL,{fields},mode TEXT NOT NULL DEFAULT 'hot' CHECK(mode IN ('hot','cold')),vector BLOB CHECK(vector IS NULL OR (typeof(vector)='blob' AND length(vector)>0 AND length(vector)%8=0)),vector_signature TEXT NOT NULL DEFAULT '',vectorized INTEGER GENERATED ALWAYS AS (vector IS NOT NULL) VIRTUAL)")
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_character ON {table}(character_id,range_start)')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_memories'").fetchone():
            old=db.execute('SELECT * FROM system_memories ORDER BY range_start,id').fetchall()
            for row in old:
                r=dict(row);kind=r['kind'];table=TABLES[kind]
                vector=None
                if r['vector']:
                    try:vector=pack(json.loads(r['vector']))
                    except (ValueError,TypeError):pass
                # 来源会话保留，绑定统一为角色；坏向量转热，避免迁移后失忆。
                values={key:r[key] for key in ('character_id','conversation_id','range_start','range_end',*FIELDS[kind])}
                values.update(mode=r['mode'] if vector or r['mode']=='hot' else 'hot',vector=vector,vector_signature=r['vector_signature'] if vector else '')
                cols=list(values)
                db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",list(values.values()))
            if sum(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES.values())<len(old):raise ValueError('系统记忆迁移数量异常')
            db.execute('DROP TABLE system_memories')
        db.execute('RELEASE system_four_tables')
    except BaseException:
        db.execute('ROLLBACK TO system_four_tables');db.execute('RELEASE system_four_tables');raise
