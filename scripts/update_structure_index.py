"""从实际文件和人工用途表生成目录说明；--check只读检查是否需要更新。"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'docs/PROJECT_STRUCTURE.md'
PURPOSES = ROOT / 'docs/reference/FILE_PURPOSES.json'
SKIP = {'__pycache__', '.pytest_cache'}


def files(directory):
    return sorted(p for p in (ROOT / directory).rglob('*')
                  if p.is_file() and not set(p.relative_to(ROOT).parts) & SKIP
                  and p.suffix != '.pyc')


def render():
    purposes = json.loads(PURPOSES.read_text(encoding='utf-8'))
    app_files = files('app')
    actual = {p.relative_to(ROOT).as_posix() for p in app_files}
    registered = {p for p in purposes if p.startswith('app/')}
    if actual != registered:
        raise ValueError(f'运行文件用途表需要更新：未登记={sorted(actual-registered)}，已移走={sorted(registered-actual)}')
    for name in purposes:
        if not (ROOT / name).is_file():
            raise ValueError(f'用途表指向不存在的文件：{name}')
    out = ['# 当前项目目录与逐文件用途', '',
           '更新：2026-10-04。此索引以实际文件生成；历史迁移说明在docs/archive。', '',
           '编辑用途表`docs/reference/FILE_PURPOSES.json`后运行`python scripts/update_structure_index.py`。',
           '`python scripts/check_structure.py`检查运行文件登记、索引同步及现行文档链接。', '',
           '## 根目录', '', '| 位置 | 用途 |', '|---|---|',
           '| app/ | 正式程序及全部必需静态资源、技能和任务提示词 |',
           '| data/ | 私人SQLite、JSON配置、设备记录与本机备份；不公开上传 |',
           '| docs/ | 当前说明、操作指南、未来规划、历史归档 |',
           '| experiments/emotion-lab/ | 独立离线实验，不参与正式聊天 |',
           '| tests/ | 按业务区域分组的离线Python和Node回归 |',
           '| scripts/ | 结构检查、目录索引生成、离线数据迁移 |',
           '| Toy connection/ | 本地设备研究程序、采集与解包资料；正式应用不依赖；说明已归docs/archive/research/toy |',
           '| remote service backup/ | 原服务器私人备份，保留原位置 |',
           '| remote service prepared/ | 迁移源、中间副本与指定成品；详见operations/DEPLOYMENT_SNAPSHOTS |',
           '| .venv/、.pytest_cache/、__pycache__/、.git/ | 环境、生成缓存和既有版本管理元数据，不是业务模块 |', '']

    def table(paths, description):
        out.extend(['| 文件 | 用途 |', '|---|---|'])
        for p in paths:
            name = p.relative_to(ROOT).as_posix()
            out.append(f'| [{name}](../{name}) | {description(p, name).replace(chr(10), " ").replace("|", "／")} |')
        out.append('')

    out.extend(['## 根目录文件', ''])
    root_files = sorted(p for p in ROOT.iterdir() if p.is_file())
    table(root_files, lambda p,n: purposes.get(n, '根目录辅助文件；修改前核对内容'))
    out.extend(['## app：按功能区域的全部运行文件', '',
                '入口为app.main:app；不再依赖根prompts目录。__init__.py用于Python包标记，不能按空文件判定为历史残留。', ''])
    for group in sorted({p.relative_to(ROOT / 'app').parts[0] if len(p.relative_to(ROOT / 'app').parts)>1 else '(入口与公共模型)' for p in app_files}):
        out.extend([f'### {group}', ''])
        selected = [p for p in app_files if (p.relative_to(ROOT / 'app').parts[0] if len(p.relative_to(ROOT / 'app').parts)>1 else '(入口与公共模型)') == group]
        table(selected, lambda p,n: purposes[n])

    out.extend(['## docs：现行说明', '',
                'archive保存原文历史，可能含旧路径，详见[归档索引](archive/README.md)。planning仅表示未来／封存方向。', ''])
    current_docs = [p for p in files('docs') if 'archive' not in p.relative_to(ROOT/'docs').parts]
    def doc_description(p, name):
        if name in purposes: return purposes[name]
        if p.suffix == '.md':
            title = re.search(r'^#+\s+(.+)$', p.read_text(encoding='utf-8-sig'), re.M)
            return title.group(1) if title else '现行模块说明'
        return '说明配图／参考资源'
    table(current_docs, doc_description)
    out.extend(['## tests：实际测试文件', '', '默认仅收集tests，不运行研究目录设备脚本。', ''])
    table(files('tests'), lambda p,n: purposes.get(n, '测试包标记' if p.name=='__init__.py' else
          ('前端离线回归' if p.suffix=='.cjs' else 'HTTP路由契约基线' if p.suffix=='.json' else '离线回归：'+p.stem.removeprefix('test_'))))
    out.extend(['## scripts：维护入口', ''])
    table(files('scripts'), lambda p,n: purposes[n])
    out.extend(['## experiments：实验文件', ''])
    table(files('experiments'), lambda p,n: purposes[n])
    out.extend(['## 常见修改在哪里', '',
                '| 目标 | 修改入口与关联 |', '|---|---|',
                '| 修改系统总结提示词 | app/memory/prompts/system.md；解析规则在memory/system与system_schema |',
                '| 修改独立日记风格 | memory/prompts/diary或diary_instant；合并用diary_merge |',
                '| 修改AI聊天自主日记 | skills/definitions/diary-write；写入由skills/runtime处理 |',
                '| 修改聊天显示或消息操作 | static/chat/chat-ui；会话API在chat/routes与store |',
                '| 修改模型／语音配置 | providers与static/settings/app；录音播放在static/voice |',
                '| 修改冷热记忆／召回 | memory/role、system、vector_store；同步模型签名和失配回退 |',
                '| 修改情绪／主动联系 | character/state、chat/heartbeat及chat/core；跨模块同步 |',
                '| 修改设备能力 | tools/toy；技能、协议、执行和退出清理要一起核对 |',
                '| 查数据库或部署版本 | docs/reference/DATABASE_FIELDS及docs/operations |',
                '| 查旧讨论、研究或升级过程 | docs/archive；当前状态仍以PROJECT_CONTEXT和源码为准 |', '',
                '跨模块修改清单见[MAINTENANCE](MAINTENANCE.md)。新增／移动文件时更新用途表、索引、引用和相关测试；不要再通过同名全局函数覆盖旧实现。', ''])
    return '\n'.join(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = render()
    if args.check:
        if not INDEX.exists() or INDEX.read_text(encoding='utf-8') != content:
            raise SystemExit('目录索引过期，请运行scripts/update_structure_index.py')
        print('目录索引与文件用途登记一致')
    else:
        INDEX.write_text(content, encoding='utf-8')
        print('已更新docs/PROJECT_STRUCTURE.md')
