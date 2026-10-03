"""图片只存一次；模型有效期与实际删除期独立。"""
import base64
from datetime import datetime, timedelta
from app.common.identity import new_id


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS images(
        id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        conversation_id TEXT NOT NULL REFERENCES conversations(id),
        uploaded_at TEXT NOT NULL,mime_type TEXT NOT NULL,content BLOB,
        origin_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS images_message ON images(message_id);
        CREATE INDEX IF NOT EXISTS images_cleanup ON images(uploaded_at);''')


def save(db, cid, mid, urls, uploaded_at):
    for url in urls:
        header, encoded = url.split(',', 1)
        iid = new_id(lambda value: db.execute('SELECT 1 FROM images WHERE id=?', (value,)).fetchone())
        db.execute('INSERT INTO images VALUES (?,?,?,?,?,?,?)',
                   (iid, mid, cid, uploaded_at, header[5:-7], base64.b64decode(encoded), iid))


def urls(db, mid, model=False, now=None):
    from app.chat import store
    now = now or store.utcnow()
    out = []
    for row in db.execute('SELECT * FROM images WHERE message_id=? ORDER BY rowid', (mid,)):
        if row['content'] is None or now - datetime.fromisoformat(row['uploaded_at']) >= timedelta(hours=3):
            continue
        if model:
            count = db.execute('''SELECT count(*) FROM messages WHERE conversation_id=? AND role='user'
                AND sequence>(SELECT sequence FROM messages WHERE id=?)''', (row['conversation_id'], mid)).fetchone()[0]
            if now - datetime.fromisoformat(row['uploaded_at']) > timedelta(minutes=5) or count >= 5:
                continue
        out.append('data:' + row['mime_type'] + ';base64,' + base64.b64encode(row['content']).decode())
    return out


def cleanup(db, now):
    # 会话有生成任务时暂缓删除；已编译请求的图片也不会被后台破坏。
    return db.execute('''UPDATE images SET content=NULL WHERE content IS NOT NULL
        AND julianday(uploaded_at)<=julianday(?) AND NOT EXISTS (
            SELECT 1 FROM requests WHERE conversation_id=images.conversation_id AND status='running')''',
        ((now-timedelta(hours=3)).isoformat(),)).rowcount


def copy(db, old_mid, new_mid, cid):
    for row in db.execute('SELECT * FROM images WHERE message_id=?', (old_mid,)).fetchall():
        iid = new_id(lambda value: db.execute('SELECT 1 FROM images WHERE id=?', (value,)).fetchone())
        db.execute('INSERT INTO images VALUES (?,?,?,?,?,?,?)',
                   (iid,new_mid,cid,row['uploaded_at'],row['mime_type'],row['content'],row['origin_id']))
