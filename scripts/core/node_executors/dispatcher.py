import logging
import json
from typing import Dict, Any
import uuid
from datetime import datetime

from scripts.models.schemas import Node, WorkflowExecuteRequest, DispatcherCallbackRequest
from scripts.services.giga_chat import GigaChatAPI
from scripts.utils.template_engine import replace_templates
from scripts.services.storage import get_workflow_by_id

logger = logging.getLogger(__name__)

# Хранилище сессий теперь принадлежит этому модулю
dispatcher_sessions: Dict[str, Dict[str, Any]] = {}

# --- Вспомогательные функции --- 

async def launch_workflow_by_id(workflow_id: str, input_data: Dict[str, Any]):
    """Запускает workflow по ID"""
    from scripts.core.workflow_engine import execute_workflow_internal
    workflow_data = get_workflow_by_id(workflow_id)
    if not workflow_data:
        raise Exception(f"Workflow {workflow_id} не найден в сохраненных workflow")
    
    logger.info(f"🚀 Запуск workflow {workflow_id}")
    
    workflow_request = WorkflowExecuteRequest(
        nodes=workflow_data["nodes"],
        connections=workflow_data["connections"]
    )
    
    # В асинхронном мире мы не можем просто ждать. 
    # Правильная реализация будет запускать это как фоновую задачу.
    # Но для сохранения логики пока оставим await.
    result = await execute_workflow_internal(workflow_request, initial_input_data=input_data)
    
    # В реальной системе этот результат должен был бы отправиться 
    # на эндпоинт /dispatcher/callback, а не просто вернуться.
    return result

async def handle_workflow_return(dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
    """Обрабатывает возврат от workflow"""
    session_id = input_data.get('session_id')
    if not session_id or session_id not in sessions:
        raise Exception(f"Сессия {session_id} не найдена в диспетчере {dispatcher_id}")
    
    session = sessions[session_id]
    session['accumulated_data'][f"step_{session['current_step']}_result"] = input_data.get('workflow_result', {})
    session['current_step'] += 1
    
    if session['current_step'] < len(session['plan']):
        next_step = session['plan'][session['current_step']]
        next_workflow_id = next_step.get('workflow_id')
        logger.info(f"➡️ Переход к шагу {session['current_step']}: {next_workflow_id}")
        
        # Get the result of the step that just finished
        last_step_index = session['current_step'] - 1
        last_step_result = session['accumulated_data'].get(f"step_{last_step_index}_result", {})

        workflow_input = {
            "user_query": session['user_query'],
            "previous_results": session['accumulated_data'],
            "last_step_result": last_step_result, # NEW
            "dispatcher_context": {
                "session_id": session_id,
                "plan": session['plan'],
                "step": session['current_step'],
                "dispatcher_id": dispatcher_id
            }
        }
        return await launch_workflow_by_id(next_workflow_id, workflow_input)
    else:
        logger.info(f"✅ План для сессии {session_id} выполнен полностью")
        final_result = {
            "success": True,
            "message": "План выполнен успешно",
            "results": session['accumulated_data']
        }
        del sessions[session_id]
        return final_result

async def create_execution_plan(config: Dict, user_query: str, gigachat_api: GigaChatAPI):
    """Создает план выполнения через GigaChat"""
    available_workflows = config.get('availableWorkflows', {})
    auth_token = config.get('dispatcherAuthToken', '')
    
    if not auth_token:
        raise Exception("Токен авторизации для планирующего диспетчера не указан")
    if not available_workflows:
        raise Exception("Доступные workflow для планирования не указаны")
    
    workflows_description = "\n".join([
        f"- {wf_id}: {wf_config.get('description', 'Описание отсутствует')}"
        for wf_id, wf_config in available_workflows.items()
    ])

    planning_prompt = f"""
    Пользователь просит: "{user_query}"
    Доступные workflow для выполнения:
    {workflows_description}
    Создай пошаговый план выполнения в формате JSON массива вида [{{"workflow_id": "id", "description": "desc"}}].
    Поле 'description' должно быть на русском языке и кратко объяснять, почему ты выбрал этот шаг.
    Отвечай ТОЛЬКО JSON массивом, без дополнительного текста.
    """
    
    logger.info(f"Планирующий промпт для GigaChat:\n{planning_prompt}")
    if await gigachat_api.get_token(auth_token):
        result = await gigachat_api.get_chat_completion(
            "Ты планировщик задач. Создавай план из доступных workflow.",
            planning_prompt
        )
        try:
            plan = json.loads(result['response'])
            if not isinstance(plan, list):
                raise ValueError("План должен быть массивом")
            for step in plan:
                if 'workflow_id' not in step:
                    raise ValueError("Каждый шаг должен содержать workflow_id")
            return plan
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Ошибка парсинга плана: {result['response']}. Ошибка: {e}")
            raise Exception("Не удалось создать корректный план выполнения.")
    else:
        raise Exception("Не удалось авторизоваться в GigaChat API для создания плана")

async def create_new_orchestrator_session(dispatcher_id: str, sessions: Dict, config: Dict, input_data: Dict[str, Any], gigachat_api: GigaChatAPI, label_to_id_map, all_results):
    """Создает новую сессию и план выполнения"""
    session_id = str(uuid.uuid4())
    query_template = config.get('userQueryTemplate') or '{{ input.query }}'
    user_query = replace_templates(query_template, input_data, label_to_id_map, all_results).strip()

    if not user_query:
        raise Exception("Orchestrator: User query not found in input data.")

    plan = await create_execution_plan(config, user_query, gigachat_api)

    sessions[session_id] = {
        "plan": plan,
        "current_step": 0,
        "user_query": user_query,
        "accumulated_data": {},
        "created_at": datetime.now(),
        "dispatcher_id": dispatcher_id
    }
    
    if plan:
        first_step = plan[0]
        workflow_id = first_step.get('workflow_id')
        if workflow_id:
            workflow_input = {
                **input_data,
                "dispatcher_context": {
                    "session_id": session_id,
                    "plan": plan,
                    "step": 0,
                    "dispatcher_id": dispatcher_id
                }
            }
            return await launch_workflow_by_id(workflow_id, workflow_input)
    raise Exception("Не удалось создать или запустить план выполнения")

async def execute_router_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Агент-диспетчер, который анализирует запрос и выбирает нужный workflow."""
    from scripts.core.workflow_engine import execute_workflow_internal
    config = node.data.get('config', {})
    query_template = config.get('userQueryTemplate') or '{{ input.output.text }}'
    user_query = replace_templates(query_template, input_data, label_to_id_map, all_results).strip()

    if not user_query:
        raise Exception("Dispatcher: User query not found in input data.")

    workflow_routes = config.get('routes', {})
    if not workflow_routes:
        raise Exception("Dispatcher: Routes are not configured.")

    category = 'default'
    if config.get('useAI', True):
        auth_token = config.get('dispatcherAuthToken')
        if not auth_token:
            raise Exception("Dispatcher: GigaChat auth token is required for AI mode.")

        dispatcher_prompt = config.get('dispatcherPrompt') or "Определи категорию запроса: {категории}. Запрос: {запрос пользователя}. Ответь одним словом."
        categories_str = ", ".join(workflow_routes.keys())
        classification_prompt = dispatcher_prompt.replace("{категории}", categories_str).replace("{запрос пользователя}", user_query)
        logger.info(f"AI classification prompt:\n{classification_prompt}")
        
        if await gigachat_api.get_token(auth_token):
            gigachat_result = await gigachat_api.get_chat_completion("Ты - классификатор запросов.", classification_prompt)
            
            # NEW: Проверяем, что вызов API был успешным
            if gigachat_result and gigachat_result.get('success'):
                response_text = gigachat_result.get('response', 'default').strip().lower()
                if response_text in workflow_routes:
                    category = response_text
            else:
                # NEW: Если API вернул ошибку, логируем ее и используем 'default'
                logger.error(f"GigaChat API call failed: {gigachat_result.get('error')}. Falling back to 'default' category.")
                # category уже 'default', так что дополнительных действий не нужно
        else:
             logger.error("Dispatcher: Failed to get GigaChat token.")
    else:
        query_lower = user_query.lower()
        for cat_name, cat_info in workflow_routes.items():
            if cat_name != 'default' and 'keywords' in cat_info:
                if any(keyword.lower() in query_lower for keyword in cat_info['keywords']):
                    category = cat_name
                    break

    selected_route = workflow_routes.get(category, workflow_routes.get('default'))
    if not selected_route:
        raise Exception(f"Dispatcher: No route found for category '{category}'.")

    workflow_id = selected_route['workflow_id']
    workflow_data = get_workflow_by_id(workflow_id)
    if not workflow_data:
        raise Exception(f"Dispatcher: Target workflow '{workflow_id}' not found.")

    workflow_request = WorkflowExecuteRequest(nodes=workflow_data["nodes"], connections=workflow_data["connections"])
    
    sub_workflow_result = await execute_workflow_internal(workflow_request, initial_input_data={**input_data, "dispatcher_info": {"category": category}})
    
    # Возвращаем полный результат, а не только .result
    return sub_workflow_result.dict()

async def execute_orchestrator_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, all_results: Dict[str, Any]):
    """Планирующий диспетчер - создает план и координирует выполнение"""
    dispatcher_id = node.id
    if dispatcher_id not in dispatcher_sessions:
        dispatcher_sessions[dispatcher_id] = {}
    
    current_dispatcher_sessions = dispatcher_sessions[dispatcher_id]
    
    if input_data.get('return_to_dispatcher'):
        return await handle_workflow_return(dispatcher_id, current_dispatcher_sessions, input_data)
    else:
        return await create_new_orchestrator_session(dispatcher_id, current_dispatcher_sessions, node.data.get('config', {}), input_data, gigachat_api, label_to_id_map, all_results)

# --- Основная функция-исполнитель, вызываемая движком --- 

async def execute_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполняет диспетчер в режиме router или orchestrator"""
    config = node.data.get('config', {})
    dispatcher_type = config.get('dispatcher_type') or config.get('dispatcherType', 'router')

    logger.info(f"🎯 Executing dispatcher {node.id} in {dispatcher_type} mode")
    
    if dispatcher_type == 'router':
        return await execute_router_dispatcher(node, label_to_id_map, input_data, gigachat_api, all_results)
    elif dispatcher_type == 'orchestrator':
        return await execute_orchestrator_dispatcher(node, label_to_id_map, input_data, gigachat_api, all_results)
    else:
        raise Exception(f"Неизвестный тип диспетчера: {dispatcher_type}")

# --- Точка входа для API --- 

async def process_orchestrator_callback(callback_data: DispatcherCallbackRequest):
    """
    Точка входа для обработки коллбэков от суб-воркфлоу.
    """
    session_id = callback_data.session_id
    step_result = callback_data.step_result

    logger.info(f"🧠 Dispatcher received callback for session {session_id}")

    found_session_info = None
    for disp_id, sessions in dispatcher_sessions.items():
        if session_id in sessions:
            found_session_info = (disp_id, sessions)
            break
    
    if not found_session_info:
        raise Exception(f"Session {session_id} not found in any dispatcher sessions.")

    dispatcher_id, sessions_container = found_session_info

    callback_input_data = {
        "session_id": session_id,
        "return_to_dispatcher": True,
        "workflow_result": step_result
    }

    return await handle_workflow_return(dispatcher_id, sessions_container, callback_input_data)
