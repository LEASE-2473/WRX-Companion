from fastapi import HTTPException
from app.chat import store

def api_error(exc):
    return HTTPException(status_code=409 if isinstance(exc, store.Conflict) else 404 if isinstance(exc, KeyError) else 422,
                         detail=str(exc).strip("'"))
