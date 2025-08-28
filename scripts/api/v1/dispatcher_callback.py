from fastapi import APIRouter, status
from scripts.models.schemas import DispatcherCallbackRequest
from scripts.core.node_executors.dispatcher import process_orchestrator_callback

router = APIRouter()

@router.post("/dispatcher/callback", status_code=status.HTTP_202_ACCEPTED)
async def dispatcher_callback(request: DispatcherCallbackRequest):
    """
    Принимает "ответ" от выполненного суб-воркфлоу и передает его в ядро диспетчера.
    """
    return await process_orchestrator_callback(request)
