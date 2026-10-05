"""Check local imports and deployed resource paths without starting services."""
import ast
import json
import re
import runpy
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]


def audit():
    errors = []
    sources = list((ROOT / 'app').rglob('*.py')) + list((ROOT / 'tests').rglob('*.py'))
    sources += list((ROOT / 'scripts').glob('*.py'))
    imports = 0
    for path in sources:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(('app.', 'tests.')):
                imports += 1
                target = ROOT.joinpath(*node.module.split('.'))
                if not target.with_suffix('.py').exists() and not (target / '__init__.py').exists():
                    errors.append(f'{path.relative_to(ROOT)}:{node.lineno}: missing {node.module}')
    html = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
    resources = re.findall(r'(?:src|href)=["\'](/static/[^"\']+)', html)
    for url in resources:
        target = ROOT / 'app' / urlsplit(url).path.lstrip('/')
        if not target.is_file():
            errors.append(f'index.html: missing {url}')
    for path in (ROOT / 'app/static').rglob('*.css'):
        for url in re.findall(r'url\(\s*["\']?([^\)"\']+)', path.read_text(encoding='utf-8')):
            if url.startswith(('data:', 'http:', 'https:', '#')):
                continue
            target = ROOT / 'app' / url.lstrip('/') if url.startswith('/') else path.parent / urlsplit(url).path
            if not target.is_file():
                errors.append(f'{path.relative_to(ROOT)}: missing {url}')
    index_module = runpy.run_path(str(ROOT / 'scripts/update_structure_index.py'))
    try:
        expected_index = index_module['render']()
        if (ROOT / 'docs/PROJECT_STRUCTURE.md').read_text(encoding='utf-8') != expected_index:
            errors.append('docs/PROJECT_STRUCTURE.md: 索引过期，运行scripts/update_structure_index.py')
    except ValueError as exc:
        errors.append(str(exc))
    documents = list(ROOT.glob('*.md')) + list((ROOT / 'docs').rglob('*.md'))
    links = 0
    for path in documents:
        if 'archive' in path.relative_to(ROOT).parts and path != ROOT / 'docs/archive/README.md':
            continue  # 历史原文的旧路径只作为当时证据，不改写。
        content = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8-sig'), flags=re.S)
        for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', content):
            url = match.group(1).strip('<>')
            if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', url) or url.startswith('#'):
                continue
            target = unquote(urlsplit(url).path)
            if not target:
                continue
            links += 1
            if not (path.parent / target).exists():
                errors.append(f'{path.relative_to(ROOT)}: 文档链接不存在 {target}')
    return {'python_sources': len(sources), 'local_imports': imports,
            'html_resources': len(resources), 'document_links': links, 'errors': errors}


if __name__ == '__main__':
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(bool(result['errors']))
