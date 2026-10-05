import asyncio
from contextlib import asynccontextmanager
from app.chat.core import core
from app.chat import store as companion_store
from app.chat.heartbeat import run_scheduler

@asynccontextmanager
async def lifespan(app):
    companion_store.recover_interrupted()
    from app.memory.role import initialize as initialize_memory
    with companion_store.database() as db:
        initialize_memory(db)
    from app.memory.system import recover as recover_system_memory
    recover_system_memory()
    from app.autonomy.service import archive_settings
    archive_settings()
    from app.chat.maintenance import maintenance_once, run_scheduler as run_cleanup_scheduler
    await asyncio.to_thread(maintenance_once)
    cleanup_scheduler = asyncio.create_task(run_cleanup_scheduler())
    scheduler = asyncio.create_task(run_scheduler())
    from app.memory.role import scheduler as run_memory_scheduler
    memory_scheduler = asyncio.create_task(run_memory_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        memory_scheduler.cancel()
        cleanup_scheduler.cancel()
        from app.memory.system import shutdown as shutdown_system_memory
        await shutdown_system_memory()
        from app.autonomy.service import shutdown as shutdown_activities
        await shutdown_activities()
        from app.character.state import shutdown as shutdown_emotions
        await shutdown_emotions()
        await asyncio.gather(memory_scheduler, return_exceptions=True)
        await asyncio.gather(scheduler, return_exceptions=True)
        await asyncio.gather(cleanup_scheduler, return_exceptions=True)
        await core.shutdown()
        from app.extensions.manager import shutdown as shutdown_tools
        await asyncio.to_thread(shutdown_tools)
