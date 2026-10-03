from fastapi import HTTPException
from app.providers.diagnostics import safe_provider_detail as _safe_provider_detail
from app.memory.vector_store import delete_vector_library, freeze_vector_memory, fetch_vector_models, get_embeddings, get_rerank_scores, import_vector_library, list_vector_chunks, preview_vector_import, public_vector_memory, save_vector_config, set_vector_library_enabled, vectorize_library
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/vector-memory")
async def get_vector_memory():
    return public_vector_memory()


@router.put("/api/vector-memory/config")
async def update_vector_memory_config(value: dict):
    try:
        return public_vector_memory(save_vector_config(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/vector-memory/test")
async def test_vector_memory_provider():
    state = freeze_vector_memory()
    try:
        vector = (await get_embeddings(["WRX 向量连接测试"], state.config))[0]
        return {"ok": True, "dimensions": len(vector)}
    except Exception as exc:
        return {"ok": False, "detail": _safe_provider_detail(exc, state.config.api_key)}


@router.post("/api/vector-memory/models")
async def vector_memory_models(value: dict):
    state = freeze_vector_memory()
    kind = str(value.get("kind") or "embedding")
    try:
        if kind == "rerank":
            models = await fetch_vector_models(state.config.rerank_url, state.config.rerank_key)
        else:
            models = await fetch_vector_models(state.config.api_url, state.config.api_key)
        return {"ok": True, "models": models}
    except Exception as exc:
        secret = state.config.rerank_key if kind == "rerank" else state.config.api_key
        return {"ok": False, "models": [], "detail": _safe_provider_detail(exc, secret)}


@router.post("/api/vector-memory/rerank/test")
async def test_vector_memory_rerank():
    state = freeze_vector_memory()
    try:
        scores = await get_rerank_scores("test", ["test"], state.config)
        return {"ok": True, "score": scores[0]}
    except Exception as exc:
        return {"ok": False, "detail": _safe_provider_detail(exc, state.config.rerank_key)}


@router.post("/api/vector-memory/import/preview")
async def preview_vector_memory_import(value: dict):
    try:
        return preview_vector_import(str(value.get("text") or ""), str(value.get("filename") or ""), str(value.get("separator") or "---"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/vector-memory/import")
async def commit_vector_memory_import(value: dict):
    try:
        state, library = import_vector_library(str(value.get("name") or ""), str(value.get("text") or ""), str(value.get("filename") or ""), str(value.get("separator") or "---"))
        return {"state": public_vector_memory(state), "library": {"id": library.id, "name": library.name, "source_format": library.source_format, "chunk_count": len(library.chunks)}}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/vector-memory/libraries/{library_id}/enabled")
async def toggle_vector_library(library_id: str, value: dict):
    try:
        return public_vector_memory(set_vector_library_enabled(library_id, bool(value.get("enabled"))))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/vector-memory/libraries/{library_id}/chunks")
async def get_vector_library_chunks(library_id: str, offset: int = 0, limit: int = 20, query: str = ""):
    try:
        return list_vector_chunks(library_id, offset, limit, query)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/vector-memory/libraries/{library_id}")
async def remove_vector_library(library_id: str):
    try:
        return public_vector_memory(delete_vector_library(library_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/vector-memory/libraries/{library_id}/vectorize")
async def run_vectorization(library_id: str):
    try:
        state, report = await vectorize_library(library_id)
        return {"state": public_vector_memory(state), "report": report}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        state = freeze_vector_memory()
        raise HTTPException(status_code=502, detail=_safe_provider_detail(exc, state.config.api_key)) from exc
