import logging
import json
from typing import Dict, Any

from scripts.models.schemas import Node, WorkflowExecuteRequest
from scripts.services.giga_chat import GigaChatAPI
from scripts.utils.template_engine import replace_templates
from scripts.services.storage import get_workflow_by_id

logger = logging.getLogger(__name__)

async def execute_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, sessions: Dict, all_results: Dict[str, Any]) -> Dict[str, Any]:
    """Выполняет диспетчер в режиме router или orchestrator"""
    config = node.data.get('config', {})
    dispatcher_type = config.get('dispatcher_type') or config.get('dispatcherType', 'router')

    logger.info(f"🎯 Executing dispatcher {node.id} in {dispatcher_type} mode")
    
    if dispatcher_type == 'router':
        return await execute_router_dispatcher(node, label_to_id_map, input_data, gigachat_api)
    
    elif dispatcher_type == 'orchestrator':
        return await execute_orchestrator_dispatcher(node, label_to_id_map, input_data, gigachat_api, sessions)
    
    else:
        raise Exception(f"Неизвестный тип диспетчера: {dispatcher_type}")

async def execute_router_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI) -> Dict[str, Any]:
    """Агент-диспетчер, который анализирует запрос и выбирает нужный workflow (старая логика)"""
    logger.info(f"DEBUG: input_data for dispatcher: {json.dumps(input_data, ensure_ascii=False, indent=2)}")

    logger.info(f"🔀 Executing Router Dispatcher node: {node.id}")
    config = node.data.get('config', {})
    
    query_template = config.get('userQueryTemplate') or '{{ input.output.text }}'

    if not label_to_id_map:
        label_to_id_map = {}
        for k, v in all_results.items():
            if isinstance(v, dict) and 'label' in v:
                label_to_id_map[v['label']] = k

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

        dispatcher_prompt = config.get('dispatcherPrompt')
        DEFAULT_PROMPT = (
            "Определи категорию запроса пользователя и выбери подходящий обработчик.\n"
            "Доступные категории: {категории}\n"
            "Запрос пользователя: {запрос пользователя}\n"
            "Ответь ТОЛЬКО одним словом - названием категории."
        )
        categories_desc = []
        for name, info in workflow_routes.items():
            desc = info.get("description", "")
            keywords = ", ".join(info.get("keywords", []))
            part = f"{name}"
            if desc:
                part += f" — {desc}"
            if keywords:
                part += f" (ключевые слова: {keywords})"
            categories_desc.append(part)

        categories_str = "; ".join(categories_desc)
        prompt_template = dispatcher_prompt or DEFAULT_PROMPT
        classification_prompt = prompt_template.replace("{категории}", categories_str).replace("{запрос пользователя}", user_query)
        logger.info(f"AI classification prompt:\n{classification_prompt}")

        if await gigachat_api.get_token(auth_token):
            gigachat_result = await gigachat_api.get_chat_completion(
                "Ты - классификатор запросов. Отвечай только одним словом - названием категории.",
                classification_prompt
            )
            response_text = gigachat_result.get('response', 'default').strip().lower()
            if response_text in workflow_routes:
                category = response_text
            else:
                logger.warning(f"GigaChat returned an unknown category '{response_text}', using default.")
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
        raise Exception(f"Dispatcher: No route found for category '{category}' and no default route is set.")

    workflow_id = selected_route['workflow_id']
    logger.info(f"🎯 Диспетчер выбрал категорию: {category} -> Запуск workflow: {workflow_id}")

    workflow_data = get_workflow_by_id(workflow_id)
    if not workflow_data:
        raise Exception(f"Dispatcher: Target workflow '{workflow_id}' not found.")

    from scripts.core.workflow_engine import execute_workflow_internal
    workflow_request = WorkflowExecuteRequest(
        nodes=workflow_data["nodes"],
        connections=workflow_data["connections"]
    )
    
    sub_workflow_result = await execute_workflow_internal(
        workflow_request, 
        initial_input_data={
            **input_data,
            "dispatcher_info": {
                "category": category,
                "original_query": user_query,
                "selected_workflow": workflow_id
            }
        }
    )

    return {
        **sub_workflow_result.result,
        "success": sub_workflow_result.success,
        "dispatcher_category": category,
        "executed_workflow_id": workflow_id,
        "output": {
            "text": f"Результат от workflow '{workflow_id}': {sub_workflow_result.result}",
            "json": sub_workflow_result.result
        }
    }

async def execute_orchestrator_dispatcher(node: Node, label_to_id_map: Dict[str, str], input_data: Dict[str, Any], gigachat_api: GigaChatAPI, sessions: Dict):
    """Планирующий диспетчер - создает план и координирует выполнение"""
    config = node.data.get('config', {})
    session_id = input_data.get('session_id')
    dispatcher_id = node.id
    
    logger.info(f"🎼 Orchestrator dispatcher {dispatcher_id} processing request")
    
    if dispatcher_id not in sessions:
        sessions[dispatcher_id] = {}
    
    dispatcher_sessions = sessions[dispatcher_id]
    
    if input_data.get('return_to_dispatcher'):
        logger.info(f"📥 Handling workflow return for session {session_id}")
        return await handle_workflow_return(dispatcher_id, dispatcher_sessions, input_data)
    
    elif session_id and session_id in dispatcher_sessions:
        logger.info(f"🔄 Continuing session {session_id}")
        return await handle_session_continuation(dispatcher_id, dispatcher_sessions, input_data)
    
    else:
        logger.info(f"🆕 Creating new session for new request")
        return await create_new_orchestrator_session(dispatcher_id, dispatcher_sessions, config, input_data, gigachat_api, label_to_id_map)

async def create_new_orchestrator_session(dispatcher_id: str, sessions: Dict, config: Dict, input_data: Dict[str, Any], gigachat_api: GigaChatAPI, label_to_id_map=None):
    """Создает новую сессию и план выполнения"""
    import uuid
    from datetime import datetime
    
    session_id = str(uuid.uuid4())
    
    query_template = config.get('userQueryTemplate') or '{{ input.query }}'

    if not label_to_id_map:
        label_to_id_map = {}
        for k, v in all_results.items():
            if isinstance(v, dict) and 'label' in v:
                label_to_id_map[v['label']] = k

    user_query = replace_templates(query_template, input_data, label_to_id_map, all_results).strip()

    if not user_query:
        user_query = (
            input_data.get('user_query')
            or input_data.get('message')
            or input_data.get('query')
            or input_data.get('text', '')
        )

    logger.info(f"📋 Creating execution plan for: {user_query}")

    plan = await create_execution_plan(config, user_query, gigachat_api)

    sessions[session_id] = {
        "plan": plan,
        "current_step": 0,
        "user_query": user_query,
        "accumulated_data": {},
        "created_at": datetime.now(),
        "dispatcher_id": dispatcher_id
    }
    
    logger.info(f"💾 Session {session_id} created with {len(plan)} steps")
    
    if plan:
        first_step = plan[0]
        workflow_id = first_step.get('workflow_id')
        
        if workflow_id:
            workflow_input = {
                **input_data,
                "session_id": session_id,
                "dispatcher_context": {
                    "plan": plan,
                    "step": 0,
                    "dispatcher_id": dispatcher_id
                }
            }
            
            logger.info(f"🚀 Launching first workflow: {workflow_id}")
            return await launch_workflow_by_id(workflow_id, workflow_input)
        else:
            raise Exception("Первый шаг плана не содержит workflow_id")
    else:
        raise Exception("Не удалось создать план выполнения")

async def create_execution_plan(config: Dict, user_query: str, gigachat_api: GigaChatAPI):
    """Создает план выполнения через GigaChat"""
    import json
    
    available_workflows = (
        config.get('available_workflows')
        or config.get('availableWorkflows', {})
    )
    auth_token = config.get('dispatcherAuthToken', '')
    
    if not auth_token:
        raise Exception("Токен авторизации для планирующего диспетчера не указан")
    
    if not available_workflows:
        raise Exception("Доступные workflow для планирования не указаны")
    
    workflows_description = "\n".join([
        f"- {wf_id}: {wf_config.get('description', 'Описание отсутствует')}"
        + (f" (ключевые слова: {', '.join(wf_config.get('keywords', []))})" if wf_config.get('keywords') else "")
        for wf_id, wf_config in available_workflows.items()
    ])

    
    planning_prompt = f"""
    Пользователь просит: "{user_query}"    
    Доступные workflow для выполнения:
    {workflows_description}
    
    Создай пошаговый план выполнения в формате JSON массива:
    [
        {{"workflow_id": "workflow1", "description": "что делает этот шаг"}},
        {{"workflow_id": "workflow2", "description": "что делает этот шаг"}}
    ]
    
    Правила:
    1. Используй только workflow_id из списка выше
    2. Создавай логичную последовательность шагов
    3. Отвечай ТОЛЬКО JSON массивом, без дополнительного текста
    4. Если задача простая, можно использовать один workflow
    """
    logger.info(f"Orchestrator planning prompt:\n{planning_prompt}")

    if await gigachat_api.get_token(auth_token):
        result = await gigachat_api.get_chat_completion(
            "Ты планировщик задач. Анализируй запрос пользователя и создавай оптимальный план выполнения из доступных workflow.",
            planning_prompt
        )
        
        try:
            plan = json.loads(result['response'])
            
            if not isinstance(plan, list):
                raise ValueError("План должен быть массивом")
            
            for step in plan:
                if not isinstance(step, dict) or 'workflow_id' not in step:
                    raise ValueError("Каждый шаг должен содержать workflow_id")
                
                if step['workflow_id'] not in available_workflows:
                    raise ValueError(f"Workflow {step['workflow_id']} не найден в доступных")
            
            logger.info(f"📋 Создан план из {len(plan)} шагов: {[s['workflow_id'] for s in plan]}")
            return plan
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"❌ Ошибка парсинга плана: {result['response']}")
            logger.error(f"❌ Детали ошибки: {str(e)}")
            
            fallback_workflows = list(available_workflows.keys())
            if fallback_workflows:
                fallback_plan = [{"workflow_id": fallback_workflows[0], "description": "Fallback workflow"}]
                logger.info(f"🔄 Используем fallback план: {fallback_plan}")
                return fallback_plan
            else:
                raise Exception("Не удалось создать план и нет доступных workflow для fallback")
    
    else:
        raise Exception("Не удалось авторизоваться в GigaChat API для создания плана")

async def handle_workflow_return(dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
    """Обрабатывает возврат от workflow"""
    session_id = input_data.get('session_id')
    
    if not session_id or session_id not in sessions:
        raise Exception(f"Сессия {session_id} не найдена в диспетчере {dispatcher_id}")
    
    session = sessions[session_id]
    
    workflow_result = input_data.get('workflow_result', {})
    completed_workflow = input_data.get('completed_workflow', 'unknown')
    
    logger.info(f"📥 Workflow {completed_workflow} завершен для сессии {session_id}")
    
    session['accumulated_data'][f"step_{session['current_step']}_result"] = workflow_result
    session['accumulated_data'][f"step_{session['current_step']}_workflow"] = completed_workflow
    
    session['current_step'] += 1
    
    if session['current_step'] < len(session['plan']):
        next_step = session['plan'][session['current_step']]
        next_workflow_id = next_step.get('workflow_id')
        
        logger.info(f"➡️ Переход к шагу {session['current_step']}: {next_workflow_id}")
        
        workflow_input = {
            "session_id": session_id,
            "user_query": session['user_query'],
            "previous_results": session['accumulated_data'],
            "dispatcher_context": {
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
            "session_id": session_id,
            "completed_steps": len(session['plan']),
            "results": session['accumulated_data'],
            "session_completed": True,
            "output": {
                "text": f"Выполнен план из {len(session['plan'])} шагов",
                "json": session['accumulated_data']
            }
        }
        
        del sessions[session_id]
        logger.info(f"🗑️ Сессия {session_id} удалена")
        
        return final_result

async def handle_session_continuation(dispatcher_id: str, sessions: Dict, input_data: Dict[str, Any]):
    """Обрабатывает продолжение существующей сессии (новый запрос пользователя)"""
    session_id = input_data.get('session_id')
    session = sessions[session_id]
    
    user_query = input_data.get('user_query', input_data.get('message', ''))
    
    logger.info(f"🔄 Продолжение сессии {session_id}: {user_query}")
    
    if 'additional_requests' not in session:
        session['additional_requests'] = []
    
    session['additional_requests'].append({
        "query": user_query,
        "timestamp": datetime.now().isoformat()
    })
    
    current_step = session['current_step']
    total_steps = len(session['plan'])
    
    return {
        "success": True,
        "message": f"Запрос добавлен к существующей сессии. Выполняется шаг {current_step + 1} из {total_steps}",
        "session_id": session_id,
        "current_step": current_step,
        "total_steps": total_steps,
        "additional_request_added": True,
        "output": {
            "text": f"Ваш запрос принят. Сейчас выполняется шаг {current_step + 1} из {total_steps}",
            "json": {
                "session_status": "active",
                "progress": f"{current_step}/{total_steps}"
            }
        }
    }

async def launch_workflow_by_id(workflow_id: str, input_data: Dict[str, Any]):
    """Запускает workflow по ID"""
    workflow_data = get_workflow_by_id(workflow_id)
    if not workflow_data:
        raise Exception(f"Workflow {workflow_id} не найден в сохраненных workflow")
    
    logger.info(f"🚀 Запуск workflow {workflow_id}")
    
    from scripts.core.workflow_engine import execute_workflow_internal
    workflow_request = WorkflowExecuteRequest(
        nodes=workflow_data["nodes"],
        connections=workflow_data["connections"]
    )
    
    result = await execute_workflow_internal(workflow_request, initial_input_data=input_data)
    
    return {
        "success": result.success,
        "workflow_id": workflow_id,
        "result": result.result,
        "error": result.error,
        "logs": result.logs,
        "output": {
            "text": f"Workflow {workflow_id} {'выполнен успешно' if result.success else 'завершился с ошибкой'}",
            "json": result.result
        }
    }
