import logging
import json
from typing import Dict, Any
import uuid
from datetime import datetime
import re

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
    workflow_data_raw = await get_workflow_by_id(workflow_id)
    if not workflow_data_raw:
        raise Exception(f"Workflow {workflow_id} не найден в сохраненных workflow")
    
    logger.info(f"🚀 Запуск workflow {workflow_id}")
    
    workflow_data = dict(workflow_data_raw)
    nodes = json.loads(workflow_data.get('nodes', '[]'))
    connections = json.loads(workflow_data.get('connections', '[]'))

    workflow_request = WorkflowExecuteRequest(
        nodes=nodes,
        connections=connections
    )
    
    # В асинхронном мире мы не можем просто ждать. 
    # Правильная реализация будет запускать это как фоновую задачу.
    # Но для сохранения логики пока оставим await.
    result = await execute_workflow_internal(workflow_request, initial_input_data=input_data)
    
    # В реальной системе этот результат должен был бы отправиться 
    # на эндпоинт /dispatcher/callback, а не просто вернуться.
    return result

async def re_plan_in_memory(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes the current state of a session and creates a new plan.
    This is the 'brain' of the agent mode.
    """
    logger.info(f"🧠 Agent is re-planning for session {session.get('dispatcher_id')}")
    
    config = session.get("dispatcher_config", {})
    initial_query = session.get("initial_query", "")
    history = session.get("execution_history", [])

    # 1. Instantiate a GigaChat API client
    gigachat_api = GigaChatAPI()
    auth_token = config.get('dispatcherAuthToken', '')
    if not auth_token:
        raise Exception("Auth token for dispatcher not found in session config.")

    # 2. Format the history for the prompt
    history_str = ""
    for i, record in enumerate(history):
        step_info = record.get("step_info", {})
        result = record.get("result", {})
        history_str += f"Шаг {i+1}: Я выполнил воркфлоу `{step_info.get('workflow_id')}` с описанием `{step_info.get('description')}`.\n"
        history_str += f"Результат: {json.dumps(result, ensure_ascii=False, indent=2)}\n\n"

    # 3. Get available workflows from the stored config
    available_workflows = config.get('availableWorkflows', {})
    if not available_workflows:
         # If there are no tools, we can't make a new plan.
        logger.warning("No available workflows found in dispatcher config for re-planning. Aborting.")
        session['plan'] = []
        return session

    workflows_description = "\n".join([
        f"- {wf_id}: {wf_config.get('description', 'Описание отсутствует')}"
        for wf_id, wf_config in available_workflows.items()
    ])

    # 4. Build the re-planning prompt
    re_planning_prompt = f"""
===Изиагада задача ===
{initial_query}

===Что уже сделано (История выполнения) ===
{history_str if history_str else "Еще ничего не сделано."} 

===Доступные инструменты (воркфлоу) для следущего шага ===
{workflows_description}

===Новая инструкция ===
Основываясь на изизагадада задачу и истории выполненных шагов, реши, какой должен быть следующий шаг.
Создай ОБНОВЛЕННЫЙ И ПОЛНЫЙ план оставшихся действий в формате JSON массива вида [{{"workflow_id": "id", "description": "desc"}}].
- Если задача уже решена, верни пустой массив [].
- Если следующий шаг очевиден, верни план из одного этого шага.
- Если задача сложная, разбей ее на несколько шагов.
- Используй только инструменты из списка доступных.
Отвечай ТОЛЬКО JSON массивом, без дополнительного текста.
"""
    logger.info(f"🤖 Re-planning prompt for GigaChat:\n{re_planning_prompt}")

    # 5. Call GigaChat to get the new plan
    if await gigachat_api.get_token(auth_token):
        result = await gigachat_api.get_chat_completion(
            "You are an advanced AI agent that analyzes completed work and plans the next steps.",
            re_planning_prompt
        )
        try:
            # Clean up potential markdown code blocks
            raw_response_text = result.get('response', '[]')
            match = re.search(r'```(json)?\s*([\s\S]*?)\s*```', raw_response_text)
            if match:
                cleaned_response_text = match.group(2)
            else:
                cleaned_response_text = raw_response_text

            new_plan = json.loads(cleaned_response_text)
            if not isinstance(new_plan, list):
                raise ValueError("New plan must be a list.")
            
            logger.info(f"✅ Agent received a new plan with {len(new_plan)} steps.")
            session['plan'] = new_plan
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error parsing new plan from LLM: {result.get('response')}. Error: {e}")
            # On failure, abort by returning an empty plan.
            session['plan'] = []
    else:
        raise Exception("Failed to get GigaChat token for re-planning.")

    return session


async def handle_workflow_return(dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
    """Обрабатывает возврат от workflow"""
    session_id = input_data.get('session_id')
    if not session_id or session_id not in sessions:
        raise Exception(f"Сессия {session_id} не найдена в диспетчере {dispatcher_id}")
    
    session = sessions[session_id]
    
    # Save result of the completed step to the history
    if session['current_step'] < len(session['plan']):
        completed_step_info = session['plan'][session['current_step']]
        step_result = input_data.get('workflow_result', {})
        session['execution_history'].append({
            "step_info": completed_step_info,
            "result": step_result,
            "timestamp": datetime.now().isoformat()
        })

    # Check for agent mode and re-plan if enabled
    if session.get('is_agent_mode', False):
        logger.info(f"Agent mode enabled for session {session_id}. Re-planning...")
        session = await re_plan_in_memory(session)
        # After re-planning, we start from the beginning of the new plan
        session['current_step'] = 0
    else:
        # In simple orchestrator mode, just move to the next step
        session['current_step'] += 1
    
    # Check if the plan is complete
    if session['current_step'] >= len(session['plan']):
        logger.info(f"✅ План для сессии {session_id} выполнен полностью")
        final_result = {
            "success": True,
            "message": "План выполнен успешно",
            "results": session['execution_history'] # Return the full history
        }
        del sessions[session_id]
        return final_result

    # Launch the next step
    next_step = session['plan'][session['current_step']]
    next_workflow_id = next_step.get('workflow_id')
    logger.info(f"➡️ Переход к шагу {session['current_step']}: {next_workflow_id}")
    
    last_step_result = session['execution_history'][-1]['result'] if session['execution_history'] else {}

    workflow_input = {
        "initial_query": session.get('initial_query', ''),
        "execution_history": session['execution_history'],
        "last_step_result": last_step_result,
        "dispatcher_context": {
            "session_id": session_id,
            "plan": session['plan'],
            "step": session['current_step'],
            "dispatcher_id": dispatcher_id
        }
    }
    return await launch_workflow_by_id(next_workflow_id, workflow_input)

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
        "initial_query": user_query,
        "execution_history": [],
        "is_agent_mode": config.get('is_agent_mode', False),
        "dispatcher_config": config, # Store node config for re-planning
        "accumulated_data": {}, # Maintained for compatibility, may be deprecated
        "created_at": datetime.now(),
        "dispatcher_id": dispatcher_id
    }
    
    if plan:
        first_step = plan[0]
        workflow_id = first_step.get('workflow_id')
        if workflow_id:
            # Create the standardized input context for the first step
            workflow_input = {
                "initial_query": user_query,
                "last_step_result": {},  # Exists, but is empty
                "execution_history": [],   # Exists, but is empty
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
    workflow_data_raw = await get_workflow_by_id(workflow_id)
    if not workflow_data_raw:
        raise Exception(f"Dispatcher: Target workflow '{workflow_id}' not found.")

    workflow_data = dict(workflow_data_raw)
    nodes = json.loads(workflow_data.get('nodes', '[]'))
    connections = json.loads(workflow_data.get('connections', '[]'))

    workflow_request = WorkflowExecuteRequest(nodes=nodes, connections=connections)
    
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
