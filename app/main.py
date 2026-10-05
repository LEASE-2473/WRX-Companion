"""Application assembly; run with uvicorn app.main:app."""
import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.config import APP_VERSION, STATIC_DIR
from app.lifecycle import lifespan
from app.chat.routes import router as chat_router
from app.extensions.routes import router as extensions_router
from app.tools.routes import router as tools_router
from app.memory.role_routes import router as role_memory_router
from app.memory.system_routes import router as system_memory_router
from app.memory.vector_routes import router as vector_memory_router
from app.skills.routes import router as skills_router
from app.character.routes import router as character_router
from app.autonomy.routes import router as autonomy_router
from app.prompting.routes import router as prompting_router
from app.providers.routes import router as providers_router
from app.settings.routes import router as settings_router
from app.voice.routes import router as voice_router

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="WRX Companion", version=APP_VERSION, lifespan=lifespan)
for router in (
    chat_router, extensions_router, tools_router, role_memory_router, system_memory_router,
    vector_memory_router, skills_router, character_router, autonomy_router,
    prompting_router, providers_router, settings_router, voice_router,
):
    app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
