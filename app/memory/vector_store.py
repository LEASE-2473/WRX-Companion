"""本地向量知识库：预切片导入、OpenAI-compatible Embedding 与余弦召回。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from app.common.identity import new_id
from pathlib import Path
from typing import Any

import httpx

from app.config import VECTOR_MEMORY_FILE
from app.models import VectorChunk, VectorLibrary, VectorMemoryConfig, VectorMemoryState

_HTTP_CLIENT: httpx.AsyncClient | None = None
_MARKDOWN_CHUNK_HEADING = re.compile(r"^###\s+\[([^\]]+)](?:\s+(.*))?$", re.MULTILINE)


def _path(path: Path | None = None) -> Path:
    return path or VECTOR_MEMORY_FILE


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_vector_memory(path: Path | None = None) -> VectorMemoryState:
    target = _path(path)
    if not target.exists():
        return VectorMemoryState()
    try:
        return VectorMemoryState.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return VectorMemoryState()


def save_vector_memory(state: VectorMemoryState, path: Path | None = None) -> VectorMemoryState:
    _atomic_write(_path(path), state.model_dump())
    return state


def freeze_vector_memory(path: Path | None = None) -> VectorMemoryState:
    return copy.deepcopy(load_vector_memory(path))


def public_vector_memory(state: VectorMemoryState | None = None) -> dict[str, Any]:
    state = state or load_vector_memory()
    config = state.config.model_dump(exclude={"api_key", "rerank_key"})
    config["api_key_set"] = bool(state.config.api_key)
    config["rerank_key_set"] = bool(state.config.rerank_key)
    return {
        "schema_version": state.schema_version,
        "config": config,
        "libraries": [
            {
                "id": library.id,
                "name": library.name,
                "enabled": library.enabled,
                "source_format": library.source_format,
                "chunk_count": len(library.chunks),
                "vectorized_count": sum(chunk.vector is not None for chunk in library.chunks),
            }
            for library in state.libraries
        ],
    }


def save_vector_config(value: dict[str, Any], path: Path | None = None) -> VectorMemoryState:
    state = load_vector_memory(path)
    incoming = dict(value)
    if not str(incoming.get("api_key", "")).strip():
        incoming["api_key"] = state.config.api_key
    if not str(incoming.get("rerank_key", "")).strip():
        incoming["rerank_key"] = state.config.rerank_key
    state.config = VectorMemoryConfig.model_validate(incoming)
    return save_vector_memory(state, path)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunk(chunk_id: str, content: str, metadata: dict[str, Any] | None = None) -> VectorChunk:
    cleaned = content.strip()
    return VectorChunk(id=new_id(), content=cleaned, metadata=dict(metadata or {}, **({'source_id': chunk_id.strip()} if chunk_id.strip() else {})), content_sha256=_content_hash(cleaned))


def _split_plain_text(text: str, separator: str) -> list[VectorChunk]:
    marker = separator or "---"
    if marker in {"\\n", "\n"}:
        pieces = text.splitlines()
    else:
        # 分隔符必须独占一行，避免误切正文里的连字符或 Markdown 表格。
        pieces = re.split(rf"(?m)^\s*{re.escape(marker)}\s*$", text)
    return [_chunk(f"chunk-{index}", piece) for index, piece in enumerate(pieces, 1) if piece.strip()]


def _parse_jsonl(text: str) -> list[VectorChunk]:
    chunks: list[VectorChunk] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行不是合法 JSON：{exc.msg}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"JSONL 第 {line_number} 行必须是对象")
        content = str(item.get("content") or item.get("text") or "").strip()
        if not content:
            raise ValueError(f"JSONL 第 {line_number} 行缺少 content/text")
        chunk_id = str(item.get("chunk_id") or item.get("id") or f"chunk-{line_number}")
        metadata = {key: value for key, value in item.items() if key not in {"content", "text", "vector"}}
        chunks.append(_chunk(chunk_id, content, metadata))
    return chunks


def _parse_markdown_chunks(text: str, separator: str) -> list[VectorChunk]:
    matches = list(_MARKDOWN_CHUNK_HEADING.finditer(text))
    if not matches:
        return _split_plain_text(text, separator)
    chunks: list[VectorChunk] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        body = re.sub(r"(?m)^\s*---\s*$", "", body).strip()
        fenced = re.fullmatch(r"```(?:text)?\s*\n?(.*?)\n?```", body, re.DOTALL | re.IGNORECASE)
        if fenced:
            body = fenced.group(1).strip()
        metadata: dict[str, Any] = {}
        if match.group(2):
            metadata["heading"] = match.group(2).strip()
        if body:
            chunks.append(_chunk(match.group(1), body, metadata))
    return chunks


def parse_vector_source(text: str, filename: str = "", separator: str = "---") -> tuple[str, list[VectorChunk]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".jsonl":
        return "jsonl", _parse_jsonl(text)
    if suffix in {".md", ".markdown"}:
        return "markdown", _parse_markdown_chunks(text, separator)
    return "text", _split_plain_text(text, separator)


def preview_vector_import(text: str, filename: str = "", separator: str = "---") -> dict[str, Any]:
    source_format, chunks = parse_vector_source(text, filename, separator)
    if not chunks:
        raise ValueError("没有解析到可导入的切片")
    duplicate_ids = sorted({chunk.metadata['source_id'] for chunk in chunks if sum(item.metadata.get('source_id') == chunk.metadata.get('source_id') for item in chunks) > 1})
    return {
        "source_format": source_format,
        "chunk_count": len(chunks),
        "duplicate_ids": duplicate_ids,
        "total_characters": sum(len(chunk.content) for chunk in chunks),
        "samples": [{"id": chunk.id, "characters": len(chunk.content), "preview": chunk.content[:160], "metadata": chunk.metadata} for chunk in chunks[:3]],
    }


def import_vector_library(name: str, text: str, filename: str = "", separator: str = "---", path: Path | None = None) -> tuple[VectorMemoryState, VectorLibrary]:
    source_format, chunks = parse_vector_source(text, filename, separator)
    if not chunks:
        raise ValueError("没有解析到可导入的切片")
    seen: set[str] = set()
    for chunk in chunks:
        source_id = chunk.metadata.get('source_id',chunk.id)
        if source_id in seen:
            raise ValueError(f"切片来源 ID 重复：{source_id}")
        seen.add(source_id)
    library = VectorLibrary(id=new_id(lambda value: any(item.id == value for item in load_vector_memory(path).libraries)), name=name.strip() or Path(filename).stem or "向量知识库", source_format=source_format, chunks=chunks)
    state = load_vector_memory(path)
    state.libraries.append(library)
    return save_vector_memory(state, path), library


def delete_vector_library(library_id: str, path: Path | None = None) -> VectorMemoryState:
    state = load_vector_memory(path)
    before = len(state.libraries)
    state.libraries = [library for library in state.libraries if library.id != library_id]
    if len(state.libraries) == before:
        raise KeyError("Vector library not found")
    return save_vector_memory(state, path)


def set_vector_library_enabled(library_id: str, enabled: bool, path: Path | None = None) -> VectorMemoryState:
    state = load_vector_memory(path)
    library = next((item for item in state.libraries if item.id == library_id), None)
    if library is None:
        raise KeyError("Vector library not found")
    library.enabled = enabled
    return save_vector_memory(state, path)


def list_vector_chunks(library_id: str, offset: int = 0, limit: int = 20, query: str = "", path: Path | None = None) -> dict[str, Any]:
    state = load_vector_memory(path)
    library = next((item for item in state.libraries if item.id == library_id), None)
    if library is None:
        raise KeyError("Vector library not found")
    normalized_query = query.strip().casefold()
    indexed_chunks = list(enumerate(library.chunks))
    if normalized_query:
        indexed_chunks = [
            (index, chunk) for index, chunk in indexed_chunks
            if normalized_query in chunk.id.casefold()
            or normalized_query in chunk.content.casefold()
            or normalized_query in json.dumps(chunk.metadata, ensure_ascii=False).casefold()
        ]
    safe_offset = max(0, offset)
    safe_limit = min(100, max(1, limit))
    page = indexed_chunks[safe_offset:safe_offset + safe_limit]
    return {
        "library": {"id": library.id, "name": library.name, "source_format": library.source_format},
        "total": len(indexed_chunks),
        "unfiltered_total": len(library.chunks),
        "offset": safe_offset,
        "limit": safe_limit,
        "chunks": [
            {
                "index": index + 1,
                "id": chunk.id,
                "content": chunk.content,
                "metadata": chunk.metadata,
                "characters": len(chunk.content),
                "content_sha256": chunk.content_sha256,
                "vectorized": chunk.vector is not None,
                "vector_dimensions": len(chunk.vector) if chunk.vector is not None else 0,
            }
            for index, chunk in page
        ],
    }


def _embedding_url(api_url: str) -> str:
    cleaned = api_url.rstrip("/")
    if cleaned.endswith("/embeddings"):
        return cleaned
    if "googleapis.com" in cleaned and "openai" in cleaned:
        return f"{cleaned}/embeddings"
    if not cleaned.endswith("/v1"):
        cleaned = f"{cleaned}/v1"
    return f"{cleaned}/embeddings"


def _rerank_url(api_url: str) -> str:
    cleaned = api_url.rstrip('/')
    if cleaned.endswith('/rerank'):
        return cleaned
    if not cleaned.endswith('/v1'):
        cleaned += '/v1'
    return cleaned + '/rerank'


def _models_url(api_url: str) -> str:
    cleaned = api_url.rstrip('/')
    for suffix in ('/embeddings', '/rerank', '/chat/completions', '/models'):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
            break
    if not cleaned.endswith('/v1') and not ('googleapis.com' in cleaned and '/openai' in cleaned):
        cleaned += '/v1'
    return cleaned + '/models'


async def _client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(timeout=90, limits=httpx.Limits(max_keepalive_connections=4, max_connections=8, keepalive_expiry=60))
    return _HTTP_CLIENT


async def get_embeddings(texts: list[str], config: VectorMemoryConfig) -> list[list[float]]:
    if not config.api_url.strip() or not config.model.strip():
        raise ValueError("向量 API URL 和 Embedding Model 均不能为空")
    headers = {"Content-Type": "application/json"}
    if config.api_key.strip():
        headers["Authorization"] = f"Bearer {config.api_key}"
    response = await (await _client()).post(
        _embedding_url(config.api_url),
        headers=headers,
        json={"model": config.model, "input": texts},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Embedding API 返回的向量数量与输入不一致")
    ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
    vectors = [item.get("embedding") for item in ordered]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise ValueError("Embedding API 未返回有效向量")
    return [[float(value) for value in vector] for vector in vectors]


async def fetch_vector_models(api_url: str, api_key: str = "", models_url: str = "") -> list[str]:
    if not api_url.strip():
        raise ValueError("请先填写 API URL")
    headers: dict[str, str] = {}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key}"
    response = await (await _client()).get(models_url.strip() or _models_url(api_url), headers=headers)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("模型接口未返回 data 数组")
    return sorted({str(item.get("id") or "").strip() for item in data if isinstance(item, dict) and str(item.get("id") or "").strip()})


async def get_rerank_scores(query: str, documents: list[str], config: VectorMemoryConfig) -> list[float]:
    if not config.rerank_url.strip() or not config.rerank_model.strip():
        raise ValueError("Rerank API URL 和 Model 均不能为空")
    headers = {"Content-Type": "application/json"}
    if config.rerank_key.strip():
        headers["Authorization"] = f"Bearer {config.rerank_key}"
    response = await (await _client()).post(
        config.rerank_url,
        headers=headers,
        json={"model": config.rerank_model, "query": query, "documents": documents, "top_n": len(documents), "return_documents": False},
        timeout=3,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Rerank API 未返回 results 数组")
    scores: list[float | None] = [None] * len(documents)
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, int) and 0 <= index < len(scores) and isinstance(score, (int, float)):
            scores[index] = float(score)
    if any(score is None for score in scores):
        raise ValueError("Rerank API 返回结果数量或索引不完整")
    return [float(score) for score in scores]


async def vectorize_library(library_id: str, path: Path | None = None, batch_size: int = 32) -> tuple[VectorMemoryState, dict[str, int]]:
    state = load_vector_memory(path)
    library = next((item for item in state.libraries if item.id == library_id), None)
    if library is None:
        raise KeyError("Vector library not found")
    pending = [chunk for chunk in library.chunks if chunk.vector is None]
    completed = 0
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        vectors = await get_embeddings([chunk.content for chunk in batch], state.config)
        for chunk, vector in zip(batch, vectors):
            chunk.vector = vector
            completed += 1
        save_vector_memory(state, path)
    return state, {"completed": completed, "total": len(library.chunks), "already_vectorized": len(library.chunks) - len(pending)}


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else -1.0


async def retrieve_vector_memories(query: str, state: VectorMemoryState | None = None) -> list[dict[str, Any]]:
    state = state or freeze_vector_memory()
    if not state.config.enabled or not query.strip():
        return []
    candidates = [(library, chunk) for library in state.libraries if library.enabled for chunk in library.chunks if chunk.vector is not None]
    if not candidates:
        return []
    query_vector = (await get_embeddings([query], state.config))[0]
    ranked = sorted(
        ({"library_id": library.id, "library_name": library.name, "chunk_id": chunk.id, "content": chunk.content, "metadata": chunk.metadata, "score": _cosine(query_vector, chunk.vector or [])} for library, chunk in candidates),
        key=lambda item: item["score"],
        reverse=True,
    )
    target_count = state.config.max_results
    initial_threshold = 0.1 if state.config.rerank_enabled else state.config.threshold
    recall_count = target_count * 2 if state.config.rerank_enabled else target_count
    selected = [item for item in ranked if item["score"] >= initial_threshold][:recall_count]
    if state.config.rerank_enabled and selected:
        try:
            scores = await get_rerank_scores(query, [item["content"] for item in selected], state.config)
            for item, rerank_score in zip(selected, scores):
                item["vector_score"] = item["score"]
                item["rerank_score"] = rerank_score
                item["score"] = rerank_score
                item["rerank_status"] = "applied"
            selected.sort(key=lambda item: item["score"], reverse=True)
        except Exception as exc:
            for item in selected:
                item["rerank_status"] = "fallback"
                item["rerank_error"] = str(exc)
    final_threshold = 0.001 if state.config.rerank_enabled else state.config.threshold
    return [item for item in selected if item["score"] >= final_threshold][:target_count]
