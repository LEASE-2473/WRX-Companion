"""离线迁移部署副本；源目录只读，不启动服务或调用模型。"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chat.maintenance import clean_database
from app.memory.schema import initialize as initialize_role
from app.memory.system import initialize as initialize_system


def digest_rows(db, table):
    columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[1] != 'scope']
    if not columns:
        return None
    digest = hashlib.sha256()
    count = 0
    order = ','.join('"' + col + '"' for col in columns)
    selection = " WHERE record_type != 'agreement'" if table == 'shared_records' else ''
    for row in db.execute(f'SELECT {order} FROM "{table}"{selection} ORDER BY {order}'):
        digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode())
        count += 1
    return {'rows': count, 'sha256': digest.hexdigest()}


def prepare(source_dir, output_dir, now=None):
    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    source = source_dir / 'companion.sqlite3'
    if not source.is_file():
        raise ValueError('源目录缺少 companion.sqlite3')
    if output_dir == source_dir or source_dir in output_dir.parents or output_dir in source_dir.parents:
        raise ValueError('输出目录必须与源目录独立')
    if output_dir.exists():
        raise ValueError('输出目录已存在，请选择新目录，避免覆盖数据')
    now = now or datetime.now(timezone.utc)
    protected = ('characters', 'conversations', 'messages', 'conversation_branches',
                 'regenerations', 'resends', 'companion_states', 'role_emotions',
                 'emotion_summaries', 'memory_jobs', 'deleted_memories',
                 'diaries', 'ai_notes', 'shared_records', 'external_memory_chunks',
                 'diary_hooks', 'event_tags', 'diary_event_tags')
    with source.open('rb') as stream:
        original_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    output_dir.mkdir(parents=True)
    target = output_dir / 'companion.sqlite3'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        src.row_factory = sqlite3.Row
        before = {table: digest_rows(src, table) for table in protected}
        with closing(sqlite3.connect(target)) as db:
            src.backup(db)
            db.execute('PRAGMA journal_mode=DELETE')
    copied = {}
    for entry in source_dir.iterdir():
        if entry.is_file() and entry.name not in ('companion.sqlite3', 'companion.sqlite3-wal', 'companion.sqlite3-shm'):
            if entry.suffix == '.json':
                json.loads(entry.read_text(encoding='utf-8-sig'))
            shutil.copy2(entry, output_dir / entry.name)
            with entry.open('rb') as stream:
                copied[entry.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    with closing(sqlite3.connect(target)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        agreements = db.execute("SELECT count(*) FROM shared_records WHERE record_type='agreement'").fetchone()[0]
        initialize_role(db)
        initialize_system(db)
        counts = clean_database(db, now)
        db.commit()
        db.execute('VACUUM')
        check = db.execute('PRAGMA integrity_check').fetchall()
        if [row[0] for row in check] != ['ok'] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('迁移副本完整性检查失败，不能部署')
        after = {table: digest_rows(db, table) for table in protected}
        if before != after:
            raise RuntimeError('受保护的数据发生变化，不能部署')
        for table in ('diaries', 'shared_records', 'external_memory_chunks'):
            counts[table] = db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != original_hash:
            raise RuntimeError('源数据库发生变化，请在服务器停服后重新备份')
    for filename, digest in copied.items():
        with (output_dir / filename).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise RuntimeError('配置复制校验失败')
    report = {'prepared_at': now.isoformat(), 'source_bytes': source.stat().st_size,
              'output_bytes': target.stat().st_size, 'original_sha256': original_hash,
              'debug_retention_count': 20, 'deleted_legacy_agreements': agreements,
              'cleanup': counts, 'preserved_tables': before, 'copied_files_sha256': copied,
              'integrity_check': 'ok', 'foreign_key_check': 'ok'}
    (output_dir.parent / (output_dir.name + '-report.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_dir, args.output_dir), ensure_ascii=False, indent=2))
