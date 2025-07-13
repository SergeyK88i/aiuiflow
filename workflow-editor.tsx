"use client"

import type React from "react"
import { useState, useRef, useCallback, useEffect } from "react"
import {
  Plus,
  Play,
  Save,
  Trash2,
  Database,
  Mail,
  Webhook,
  Timer,
  MessageSquare,
  Square,
  ExternalLink,
  Pause,
  Clock,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  ListChecks,
  Info,
  GitBranch,
  Box,
  FolderOpen,
  Copy // иконка для открытия
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { GitMerge } from "lucide-react" // Добавьте к существующим импортам
// НОВОЕ: Импортируем наши API функции и типы
import * as api from './api';
import { WorkflowManagerModal } from "@/WorkflowManagerModal"
import { ScrollArea } from "@/components/ui/scroll-area";
import { Checkbox } from "./components/ui/checkbox"

/**
 * Проверяет, является ли potentialAncestorId предком для nodeId в графе.
 * Это используется для обнаружения создания циклов.
 * @param potentialAncestorId - ID узла, к которому мы пытаемся подключиться.
 * @param nodeId - ID узла, от которого идет соединение.
 * @param connections - Массив всех существующих соединений.
 * @returns true, если создается цикл.
 */
const isCreatingCycle = (targetId: string, sourceId: string, connections: Connection[]): boolean => {
  // Мы ищем путь от targetId к sourceId. Если он существует,
  // то добавление соединения от sourceId к targetId создаст цикл.
  const queue: string[] = [targetId];
  const visited = new Set<string>([targetId]);

  while (queue.length > 0) {
    const currentId = queue.shift()!;
    
    if (currentId === sourceId) {
      // Мы нашли путь от цели к источнику, значит, это создаст цикл.
      return true;
    }

    // Находим все узлы, в которые можно попасть из текущего узла
    const outgoingConnections = connections.filter(c => c.source === currentId);
    for (const conn of outgoingConnections) {
      if (!visited.has(conn.target)) {
        visited.add(conn.target);
        queue.push(conn.target);
      }
    }
  }

  // Путь не найден, цикл не создается.
  return false;
};

interface Node {
  id: string
  type: string
  position: { x: number; y: number }
  data: {
    label: string
    config: Record<string, any>
  }
}

interface Connection {
  id: string
  source: string
  target: string
}

interface TimerData {
  id: string
  node_id: string
  interval: number
  next_execution: string
  status: "active" | "paused" | "error"
}
interface ConnectionWithLabel extends Connection {
  data?: {
    label?: string;
  };
}

const API_BASE_URL = "http://localhost:8000"

const nodeTypes = [
  { type: "gigachat", label: "GigaChat AI", icon: MessageSquare, color: "bg-orange-500", canStart: true },
  { type: "webhook_trigger", label: "Webhook Trigger", icon: Webhook, color: "bg-green-500", canStart: true },
  { type: "webhook", label: "Send Webhook", icon: ExternalLink, color: "bg-blue-600", canStart: false },
  { type: "timer", label: "Timer Trigger", icon: Timer, color: "bg-blue-500", canStart: true },
  { type: "email", label: "Send Email", icon: Mail, color: "bg-red-500", canStart: false },
  { type: "database", label: "Database Query", icon: Database, color: "bg-purple-500", canStart: false },
  { type: "join", label: "Join/Merge", icon: GitMerge, color: "bg-yellow-500", canStart: false },
  { type: "request_iterator", label: "Request Iterator", icon: ListChecks, color: "bg-teal-500", canStart: false },
  {type: "if_else",label: "If/Else",icon: GitBranch, color: "bg-purple-500",description: "Условное ветвление с поддержкой циклов"},
  // НОВОЕ: Добавляем ноду Диспетчер
  { 
    type: "dispatcher", 
    label: "Dispatcher", 
    icon: GitBranch, // Или Box
    color: "bg-indigo-500", 
    canStart: false 
  },
  ];
  
  
// Добавьте после импортов (примерно строка 30)
const gigaChatRoles = [
  {
    id: "assistant",
    name: "Полезный ассистент",
    systemMessage: "Ты полезный ассистент, который отвечает кратко и по делу.",
    userMessage: "Привет! Расскажи что-нибудь интересное о программировании."
  },
  {
    id: "translator",
    name: "Переводчик",
    systemMessage: "Ты профессиональный переводчик. Переводи тексты точно, сохраняя смысл и стиль оригинала.",
    userMessage: "Переведи на английский: Искусственный интеллект меняет мир."
  },
  {
    id: "coder",
    name: "Программист",
    systemMessage: "Ты опытный программист. Пиши чистый, эффективный код с комментариями. Объясняй решения.",
    userMessage: "Напиши функцию на Python для сортировки списка."
  },
  {
    id: "analyst",
    name: "Аналитик данных",
    systemMessage: "Ты аналитик данных. Анализируй информацию, находи закономерности, делай выводы на основе фактов.",
    userMessage: "Проанализируй тренды в области ИИ за последний год."
  },
  {
    id: "creative",
    name: "Креативный писатель",
    systemMessage: "Ты креативный писатель. Создавай интересные истории, используй яркие образы и метафоры.",
    userMessage: "Придумай короткую историю про робота, который мечтает стать поваром."
  },
  {
    id: "teacher",
    name: "Учитель",
    systemMessage: "Ты терпеливый учитель. Объясняй сложные концепции простым языком, используй примеры и аналогии.",
    userMessage: "Объясни, как работает нейронная сеть, простыми словами."
  },
  {
    id: "custom",
    name: "Своя роль",
    systemMessage: "",
    userMessage: ""
  }
];

export default function WorkflowEditor() {
  const [nodes, setNodes] = useState<Node[]>([])
  const [connections, setConnections] = useState<ConnectionWithLabel[]>([])
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [draggedNode, setDraggedNode] = useState<Node | null>(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const [connecting, setConnecting] = useState<string | null>(null)
  const [workflowName, setWorkflowName] = useState("GigaChat Workflow")
  const canvasRef = useRef<HTMLDivElement>(null)
  // Добавьте в компонент состояние для вебхуков
  const [webhooks, setWebhooks] = useState<Array<{
    webhook_id: string;
    workflow_id: string;
    name: string;
    url: string;
    created_at: string;
  }>>([]);
  // НОВОЕ: Состояния для управления workflows
  const [workflows, setWorkflows] = useState<api.WorkflowListItem[]>([]);
  const [currentWorkflowId, setCurrentWorkflowId] = useState<string | null>(null);
  const [currentWorkflowName, setCurrentWorkflowName] = useState<string>("Новый Workflow");
  const [isWorkflowModalOpen, setWorkflowModalOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  // const WorkflowEditor = () => {
  //   const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  //   const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  // НОВОЕ: Загружаем список workflows при запуске
  useEffect(() => {
    const fetchWorkflows = async () => {
      try {
        const workflowList = await api.listWorkflows();
        setWorkflows(workflowList);
      } catch (error) {
        console.error("Failed to load workflows list:", error);
        // Здесь можно показать уведомление об ошибке
      }
    };
    fetchWorkflows();
  }, []);

  // НОВОЕ: Функции для работы с workflows
const loadWorkflowsList = async () => {
  try {
      const workflowList = await api.listWorkflows();
      setWorkflows(workflowList);
  } catch (error) {
      console.error("Failed to reload workflows list:", error);
  }
};

const handleLoadWorkflow = async (id: string) => {
  try {
      const workflowData = await api.getWorkflow(id);
      setNodes(workflowData.nodes || []);
      setConnections(workflowData.connections || []);
      setCurrentWorkflowId(id);
      setCurrentWorkflowName(workflowData.name);
      setWorkflowModalOpen(false); // Закрываем модалку после загрузки
      console.log(`Workflow "${workflowData.name}" loaded.`);
  } catch (error) {
      console.error(`Failed to load workflow ${id}:`, error);
      // Тут можно показать уведомление об ошибке
  }
};

const handleCreateWorkflow = async (name: string) => {
  try {
      // Создаем пустой workflow
      const newWorkflowData = { nodes: [], connections: [] };
      const result = await api.createWorkflow(name, newWorkflowData);
      
      // Обновляем список и загружаем новый пустой workflow на холст
      await loadWorkflowsList();
      setNodes([]);
      setConnections([]);
      setCurrentWorkflowId(result.workflow_id);
      setCurrentWorkflowName(name);
      setWorkflowModalOpen(false);
      console.log(`Workflow "${name}" created with id ${result.workflow_id}.`);
  } catch (error) {
      console.error("Failed to create workflow:", error);
  }
};

const handleDeleteWorkflow = async (id: string) => {
  try {
      await api.deleteWorkflow(id);
      await loadWorkflowsList();
      // Если удалили текущий открытый workflow, очищаем холст
      if (currentWorkflowId === id) {
          setNodes([]);
          setConnections([]);
          setCurrentWorkflowId(null);
          setCurrentWorkflowName("Новый Workflow");
      }
      console.log(`Workflow ${id} deleted.`);
  } catch (error) {
      console.error(`Failed to delete workflow ${id}:`, error);
  }
};

// НОВАЯ ФУНКЦИЯ ДЛЯ КЛОНИРОВАНИЯ
const handleCloneWorkflow = async (sourceId: string, sourceName: string) => {
  const newName = prompt(`Введите имя для копии workflow:`, `${sourceName} (копия)`);
  if (!newName || !newName.trim()) {
    console.log("Клонирование отменено.");
    return;
  }

  try {
    console.log(`Клонирование workflow "${sourceName}" (ID: ${sourceId})...`);
    
    // 1. Получаем данные исходного workflow
    const workflowToClone = await api.getWorkflow(sourceId);
    
    // 2. Создаем новый workflow с этими данными и новым именем
    await api.createWorkflow(newName, {
      nodes: workflowToClone.nodes,
      connections: workflowToClone.connections,
    });

    console.log(`Workflow успешно склонирован как "${newName}"`);
    
    // 3. Обновляем список, чтобы увидеть клон
    await loadWorkflowsList();
    
    alert(`Workflow "${sourceName}" успешно склонирован как "${newName}"!`);

  } catch (error) {
    console.error(`Ошибка при клонировании workflow ${sourceId}:`, error);
    alert("Не удалось склонировать workflow. Подробности в консоли.");
  }
};

// НОВОЕ: Универсальная функция сохранения
// НОВОЕ: Универсальная функция сохранения с настройкой таймера
const handleSave = async () => {
  setIsSaving(true);
  let savedWorkflowId: string | null = currentWorkflowId;
  let savedWorkflowName: string = currentWorkflowName;

  try {
      const workflowData = { nodes, connections };

      if (currentWorkflowId) {
          // --- ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕГО WORKFLOW ---
          await api.updateWorkflow(currentWorkflowId, workflowData);
          console.log(`✅ Workflow "${currentWorkflowName}" updated.`);
      } else {
          // --- СОЗДАНИЕ НОВОГО WORKFLOW ---
          const name = prompt("Введите имя для нового workflow:", "Мой новый workflow");
          if (name) {
              const result = await api.createWorkflow(name, workflowData);
              // Сохраняем ID и имя нового workflow для последующих шагов
              savedWorkflowId = result.workflow_id;
              savedWorkflowName = name;
              
              setCurrentWorkflowId(result.workflow_id);
              setCurrentWorkflowName(name);
              await loadWorkflowsList(); // Обновляем список, чтобы он появился в модалке
              console.log(`✅ Workflow "${name}" created with id ${result.workflow_id}.`);
          } else {
              // Пользователь отменил ввод имени
              setIsSaving(false);
              return;
          }
      }

      // --- НОВЫЙ БЛОК: НАСТРОЙКА ТАЙМЕРА ПОСЛЕ СОХРАНЕНИЯ ---
      // Проверяем, есть ли в workflow нода таймера
      const timerNode = nodes.find(n => n.type === 'timer');

      // Если есть нода таймера и у нас есть ID workflow...
      if (timerNode && savedWorkflowId) {
          console.log(`🕒 Found timer node (${timerNode.id}). Setting up schedule for workflow ${savedWorkflowId}...`);
          try {
              // ...вызываем новый эндпоинт для настройки расписания
              const timerResult = await api.setupTimer(timerNode, savedWorkflowId);
              console.log(`✅ Timer setup successful:`, timerResult.message);
              // Опционально: можно показать уведомление об успехе
              // alert("Расписание для workflow успешно настроено!");
              
              // Обновляем список активных таймеров в UI
              await loadTimers();

          } catch (error) {
              console.error("❌ Failed to set up timer:", error);
              alert(`Ошибка настройки расписания: ${error.message}`);
          }
      }
      // --- КОНЕЦ НОВОГО БЛОКА ---

  } catch (error) {
      console.error("❌ Failed to save workflow:", error);
      alert(`Ошибка сохранения workflow: ${error.message}`);
  } finally {
      setIsSaving(false);
  }
};

// Функция для создания нового "безымянного" workflow на холсте
const handleNewWorkflow = () => {
  setNodes([]);
  setConnections([]);
  setCurrentWorkflowId(null);
  setCurrentWorkflowName("Новый Workflow");
  console.log("Cleared canvas for a new workflow.");
};

  // 1. Замени текущую функцию handleConnect на эту:
  const handleConnect = (targetId: string) => {
    if (!connecting) return;
  
    // --- Шаг 1: Определяем ключевые переменные ---
    const isIfElseNode = connecting.includes(':');
    const sourceId = isIfElseNode ? connecting.split(':')[0] : connecting;
    const sourceNode = nodes.find(n => n.id === sourceId);
  
    if (!sourceNode) {
      setConnecting(null);
      return;
    }
  
    // --- Шаг 2: Главная проверка на создание цикла ---
    // Эта проверка выполняется для ЛЮБОЙ попытки соединения.
    if (isCreatingCycle(targetId, sourceId, connections)) {
      
      // --- Шаг 2.1: Если цикл исходит от If/Else, предлагаем GOTO ---
      if (isIfElseNode) {
        const confirmGoto = confirm(
          "⚠️ Обнаружен циклический переход!\n\n" +
          "Вы пытаетесь соединить узел с одним из его предшественников. Чтобы избежать бесконечных циклов, это соединение должно быть GOTO-переходом.\n\n" +
          "Нажмите 'ОК', чтобы автоматически преобразовать это соединение в безопасный GOTO-переход."
        );
  
        if (confirmGoto) {
          const portType = connecting.split(':')[1];
          const newConnection: ConnectionWithLabel = {
            id: `${sourceId}-${targetId}-${Date.now()}`,
            source: sourceId,
            target: targetId,
            data: { label: `${portType}:goto` }
          };
          setConnections(prev => [...prev, newConnection]);
        }
        // Если пользователь нажал "Отмена", ничего не делаем.
      } 
      // --- Шаг 2.2: Если цикл исходит от любой другой ноды, ЗАПРЕЩАЕМ ---
      else {
        alert(
          "❌ Действие отменено.\n\n" +
          "Создание циклического соединения запрещено для этого типа узлов. Циклы (GOTO-переходы) разрешены только для узлов 'If/Else'."
        );
        // Никакое соединение не создается.
      }
  
      // В любом случае, после обработки цикла, завершаем операцию.
      setConnecting(null);
      return;
    }
  
    // --- Шаг 3: Обработка НЕ-циклических соединений ---
    
    // Проверяем, не включен ли GOTO вручную для If/Else (для особых случаев)
    if (isIfElseNode && sourceNode.data.config.enableGoto) {
      const confirmManualGoto = confirm(
        `Создать принудительный GOTO переход?\n\n` +
        `Опция GOTO для этой ноды включена. Нажмите 'ОК', чтобы создать GOTO-переход, или 'Отмена' для создания обычного соединения.`
      );
      if (confirmManualGoto) {
          const portType = connecting.split(':')[1];
          const newConnection: ConnectionWithLabel = {
            id: `${sourceId}-${targetId}-${Date.now()}`,
            source: sourceId,
            target: targetId,
            data: { label: `${portType}:goto` }
          };
          setConnections(prev => [...prev, newConnection]);
          setConnecting(null);
          return;
      }
    }
  
    // Если это не цикл и не ручной GOTO, создаем обычное соединение.
    const label = isIfElseNode ? connecting.split(':')[1] : undefined;
    const newConnection: ConnectionWithLabel = {
      id: `${sourceId}-${targetId}-${Date.now()}`,
      source: sourceId,
      target: targetId,
      data: label ? { label } : undefined
    };
    setConnections(prev => [...prev, newConnection]);
  
    setConnecting(null);
  };
  
  
  
const getSanitizedConnections = () => {
  return connections.map(conn => {
    const sourceNode = nodes.find(n => n.id === conn.source);
    if (sourceNode?.type === 'if_else' && !conn.data?.label) {
      console.warn(`⚠️ Соединение от If/Else ноды ${conn.source} не имеет метки. Добавляем метку 'true' по умолчанию.`);
      return {
        ...conn,
        data: { label: 'true' }
      };
    }
    return conn;
  });
};

  
  
  const renderConnection = (connection: ConnectionWithLabel) => {
    const sourceNode = nodes.find((n) => n.id === connection.source)
    const targetNode = nodes.find((n) => n.id === connection.target)
  
    if (!sourceNode || !targetNode) return null
  
    // Определяем начальные и конечные координаты
    let startX = sourceNode.position.x + 200
    let startY = sourceNode.position.y + 40
    let endX = targetNode.position.x
    let endY = targetNode.position.y + 40
  
    // Для If/Else ноды используем разные порты
    if (sourceNode.type === 'if_else') {
      const connectionLabel = connection.data?.label || '';
      if (connectionLabel.startsWith('true')) {
        // Зеленый порт (верхний)
        startY = sourceNode.position.y + 30;
      } else if (connectionLabel.startsWith('false')) {
        // Красный порт (нижний)
        startY = sourceNode.position.y + 70;
      }
    }
  
    const midX = (startX + endX) / 2
    
    // Определяем статус соединения
    const sourceExecuted = !!executionResults[connection.source]
    const targetExecuted = !!executionResults[connection.target]
    const sourceHasError = executionLogs.some(log => log.nodeId === connection.source && log.status === "error")
    const targetIsActive = activeNode === connection.target
    
    // Определяем стиль соединения
    let strokeColor = "#6366f1" // Стандартный цвет
    let strokeWidth = "2"
    let dashArray = ""
    
    // Для goto соединений используем пунктирную линию
    const isGoto = connection.data?.label?.includes('goto');
    if (isGoto) {
      dashArray = "5,5"
    }
    
    if (sourceExecuted && !sourceHasError) {
      if (targetIsActive) {
        // Активное соединение (данные передаются)
        strokeColor = "#16a34a" // Зеленый
        strokeWidth = "3"
      } else if (targetExecuted) {
        // Успешно выполненное соединение
        strokeColor = "#16a34a" // Зеленый
      }
    } else if (sourceHasError) {
      // Ошибка в исходной ноде
      strokeColor = "#dc2626" // Красный
    }
  
    // Для If/Else соединений добавляем метку
    const connectionLabel = connection.data?.label;
    const showLabel = connectionLabel && sourceNode.type === 'if_else';
    
    return (
      <g key={connection.id} style={{ pointerEvents: 'auto' }}>
        <path
          d={`M ${startX} ${startY} C ${midX} ${startY} ${midX} ${endY} ${endX} ${endY}`}
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={dashArray}
          fill="none"
          markerEnd="url(#arrowhead)"
        />
        
        {/* Метка соединения */}
        {showLabel && (
          <text
            x={midX}
            y={(startY + endY) / 2 - 10}
            textAnchor="middle"
            fill={connectionLabel?.startsWith('true') ? "#16a34a" : "#dc2626"}
            fontSize="12"
            fontWeight="bold"
          >
            {connectionLabel}
          </text>
        )}
        
        {/* Кнопка удаления соединения */}
        <circle
          cx={midX}
          cy={(startY + endY) / 2}
          r="8"
          fill="white"
          stroke="#6366f1"
          strokeWidth="1"
          style={{ cursor: 'pointer' }}
          onClick={() => handleDeleteConnection(connection.id)}
        />
        <text
          x={midX}
          y={(startY + endY) / 2 + 4}
          textAnchor="middle"
          fill="#6366f1"
          fontSize="12"
          fontWeight="bold"
          style={{ cursor: 'pointer', pointerEvents: 'none' }}
        >
          ×
        </text>
      </g>
    )
  }
  
  const handleDeleteConnection = (connectionId: string) => {
    setConnections(prev => prev.filter(c => c.id !== connectionId));
  };
  
  

  // НОВАЯ ВЕРСИЯ
  const createWebhook = async () => {
    // Сначала сохраняем workflow, используя новую универсальную функцию
    await handleSave();

    // Проверяем, что после сохранения у нас есть ID (особенно важно для новых workflow)
    if (!currentWorkflowId) {
      alert("Не удалось сохранить workflow. Пожалуйста, попробуйте еще раз.");
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/webhooks/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          // Используем правильный ID из состояния
          workflow_id: currentWorkflowId,
          name: `${currentWorkflowName} Webhook`,
          description: `Webhook для запуска workflow: ${currentWorkflowName}`,
          auth_required: false,
          allowed_ips: []
        }),
      });

      if (response.ok) {
        const webhook = await response.json();
        
        // Обновляем ноду webhook с полученным URL
        const webhookNode = nodes.find(n => n.type === "webhook_trigger");
        if (webhookNode) {
          // Здесь нужно обновить состояние ноды. Предполагается, что у вас есть функция для этого.
          // Если updateNodeConfig обновляет только selectedNode, нужно обновить глобальное состояние.
          const newNodes = nodes.map(n => {
            if (n.type === "webhook_trigger") {
              return {
                ...n,
                data: {
                  ...n.data,
                  config: {
                    ...n.data.config,
                    webhookId: webhook.webhook_id,
                    webhookUrl: webhook.url,
                  }
                }
              };
            }
            return n;
          });
          setNodes(newNodes);
        }

        setExecutionLogs((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            nodeId: "system",
            status: "success",
            message: `Webhook создан: ${webhook.url}`,
            timestamp: new Date(),
          },
        ]);

        // Копируем URL в буфер обмена
        navigator.clipboard.writeText(webhook.url);
        alert(`Webhook создан!\n\nURL: ${webhook.url}\n\n(Скопирован в буфер обмена)`);
      } else {
          const error = await response.json();
          throw new Error(error.detail || "Failed to create webhook");
      }
    } catch (error) {
      console.error("Error creating webhook:", error);
      alert(`Ошибка создания webhook: ${error.message}`);
    }
  };


  const [isExecuting, setIsExecuting] = useState(false)
  const [executionLogs, setExecutionLogs] = useState<
    Array<{
      id: string
      nodeId: string
      status: "running" | "success" | "error"
      message: string
      timestamp: Date
      data?: any
    }>
  >([])
  const [activeNode, setActiveNode] = useState<string | null>(null)
  const [executionResults, setExecutionResults] = useState<Record<string, any>>({})
  const [abortController, setAbortController] = useState<AbortController | null>(null)
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking")
  const [debugInfo, setDebugInfo] = useState<string>("")
  const [selectedResult, setSelectedResult] = useState<{nodeId: string, data: any} | null>(null);
  const [isWorkflowResultModalOpen, setWorkflowResultModalOpen] = useState(false);

  // Состояние для таймеров
  const [timers, setTimers] = useState<TimerData[]>([])
  const [timerRefreshInterval, setTimerRefreshInterval] = useState<NodeJS.Timeout | null>(null)

  // Проверка статуса API при загрузке
  useEffect(() => {
    console.log("🚀 Компонент загружен, проверяем API...")
    checkApiStatus()
  }, [])

  // Загрузка и обновление таймеров
  useEffect(() => {
    // Загружаем таймеры при монтировании компонента
    loadTimers()

    // Устанавливаем интервал для обновления таймеров
    const interval = setInterval(loadTimers, 10000) // Обновляем каждые 10 секунд
    setTimerRefreshInterval(interval)

    return () => {
      // Очищаем интервал при размонтировании компонента
      if (timerRefreshInterval) {
        clearInterval(timerRefreshInterval)
      }
      if (interval) {
        clearInterval(interval)
      }
    }
  }, [apiStatus])

    // Добавьте новый useEffect для опроса статусов нод
useEffect(() => {
  // Проверяем, есть ли активные таймеры и онлайн ли API
  if (apiStatus !== "online" || timers.length === 0 || isExecuting) {
    return;
  }
  
  console.log("🔄 Запуск опроса статусов нод (активные таймеры:", timers.length, ")");
  
  // Функция для получения статусов нод
  const fetchNodeStatus = async () => {
    try {
      // Получаем ID всех нод в workflow
      const nodeIds = nodes.map(node => node.id);
      
      if (nodeIds.length === 0) return;
      
      const response = await fetch(`${API_BASE_URL}/node-status`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(nodeIds),
      });
      
      if (!response.ok) return;
      
      const data = await response.json();
      const results = data.results || {};
      
      // Проверяем, есть ли новые результаты
      const nodeIdsWithResults = Object.keys(results);
      if (nodeIdsWithResults.length === 0) return;
      
      console.log("📊 Получены статусы нод:", results);
      
      // Обновляем результаты выполнения
      setExecutionResults(prev => ({
        ...prev,
        ...Object.fromEntries(
          Object.entries(results).map(([nodeId, data]) => [nodeId, data.result])
        )
      }));
      
      // Последовательно подсвечиваем ноды
      nodeIdsWithResults.forEach((nodeId, index) => {
        setTimeout(() => {
          setActiveNode(nodeId);
          
          // Добавляем запись в логи
          const nodeInfo = nodes.find(n => n.id === nodeId);
          setExecutionLogs(prev => [
            ...prev,
            {
              id: `${Date.now()}-${nodeId}`,
              nodeId: nodeId,
              status: "success",
              message: `${nodeInfo?.data.label || 'Node'} executed by timer`,
              timestamp: new Date(),
              data: results[nodeId].result,
            }
          ]);
          
          // Снимаем подсветку через 1 секунду
          setTimeout(() => setActiveNode(null), 1000);
        }, index * 1500); // Задержка между подсветкой нод
      });
    } catch (error) {
      console.error("❌ Ошибка при получении статусов нод:", error);
    }
  };
  
  // Запускаем опрос каждые 3 секунды
  const intervalId = setInterval(fetchNodeStatus, 3000);
  
  // Очищаем интервал при размонтировании
  return () => {
    console.log("🛑 Остановка опроса статусов нод");
    clearInterval(intervalId);
  };
}, [apiStatus, timers.length, nodes, isExecuting]);

  const loadTimers = async () => {
    if (apiStatus === "offline") return

    try {
      const response = await fetch(`${API_BASE_URL}/timers`)
      if (response.ok) {
        const data = await response.json()
        setTimers(data.timers || [])
      }
    } catch (error) {
      console.error("Error loading timers:", error)
    }
  }

  const pauseTimer = async (timerId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/timers/${timerId}/pause`, {
        method: "POST",
      })
      if (response.ok) {
        loadTimers() // Обновляем список таймеров
      }
    } catch (error) {
      console.error(`Error pausing timer ${timerId}:`, error)
    }
  }

  const resumeTimer = async (timerId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/timers/${timerId}/resume`, {
        method: "POST",
      })
      if (response.ok) {
        loadTimers() // Обновляем список таймеров
      }
    } catch (error) {
      console.error(`Error resuming timer ${timerId}:`, error)
    }
  }

  const deleteTimer = async (timerId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/timers/${timerId}`, {
        method: "DELETE",
      })
      if (response.ok) {
        loadTimers() // Обновляем список таймеров
      }
    } catch (error) {
      console.error(`Error deleting timer ${timerId}:`, error)
    }
  }

  const executeTimerNow = async (timerId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/timers/${timerId}/execute-now`, {
        method: "POST",
      })
      if (response.ok) {
        // Обрабатываем результат выполнения
        const result = await response.json()

        // Обновляем логи и результаты
        if (result.logs) {
          result.logs.forEach((log: any, index: number) => {
            setTimeout(() => {
              setExecutionLogs((prev) => [
                ...prev,
                {
                  id: `${Date.now()}-${index}`,
                  nodeId: log.nodeId || "system",
                  status: log.level === "error" ? "error" : log.level === "success" ? "success" : "running",
                  message: log.message,
                  timestamp: new Date(log.timestamp),
                  data: log.data,
                },
              ])
            }, index * 500)
          })
        }

        if (result.result) {
          setExecutionResults(result.result)
        }
      }
    } catch (error) {
      console.error(`Error executing timer ${timerId}:`, error)
    }
  }

  const checkApiStatus = async () => {
    setApiStatus("checking")
    setDebugInfo("Проверка подключения к API...")

    try {
      console.log("🔍 Проверяем API на:", API_BASE_URL)
      console.log("🌐 Полный URL:", `${API_BASE_URL}/health`)

      const controller = new AbortController()
      const timeoutId = setTimeout(() => {
        controller.abort()
        setDebugInfo("Таймаут подключения к API (5 сек)")
        console.log("⏰ Таймаут подключения к API")
      }, 5000)

      const response = await fetch(`${API_BASE_URL}/health`, {
        method: "GET",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
        },
      })

      clearTimeout(timeoutId)

      console.log("📡 Ответ от API:", response.status, response.statusText)

      if (response.ok) {
        const data = await response.json()
        console.log("✅ API сервер доступен:", data)
        setApiStatus("online")
        setDebugInfo(`API онлайн: ${data.status}`)
      } else {
        console.error("❌ API сервер вернул ошибку:", response.status, response.statusText)
        setApiStatus("offline")
        setDebugInfo(`API ошибка: ${response.status} ${response.statusText}`)
      }
    } catch (error) {
      console.error("❌ Ошибка подключения к API:", error)
      console.error("🔍 Тип ошибки:", error.name)
      console.error("📝 Сообщение:", error.message)

      setApiStatus("offline")
      if (error.name === "AbortError") {
        setDebugInfo("Таймаут подключения к API")
      } else if (error.name === "TypeError" && error.message.includes("fetch")) {
        setDebugInfo("Сервер недоступен - проверьте запуск FastAPI")
      } else {
        setDebugInfo(`Ошибка: ${error.message}`)
      }
    }
  }
 

  const addNode = (type: string) => {
    const nodeType = nodeTypes.find((nt) => nt.type === type)
    if (!nodeType) return

    const defaultConfigs = {
      gigachat: {
        role: "assistant", // Добавляем роль по умолчанию
        authToken:
          "MTZhNzNmMTktNjg3YS00NGRiLWE3NjItYjU3NjgzY2I0ZDlhOjNmN2FjY2VjLWUxZmEtNDEwMS05MmEyLTg1NGUwMTdlYTc0Mg==",
        systemMessage: "Ты полезный ассистент, который отвечает кратко и по делу.",
        userMessage: "Привет! Расскажи что-нибудь интересное о программировании.",
        clearHistory: false,
      },
      webhook_trigger: {
        url: "https://api.example.com/webhook",
        method: "POST",
        headers: "Content-Type: application/json",
      },
      webhook: {
        url: "https://api.example.com/webhook",
        method: "POST",
        headers: "Content-Type: application/json",
      },
      email: {
        to: "user@example.com",
        subject: "",
        body: "",
      },
      database: {
        query: "",
        connection: "postgres",
      },
      timer: {
        interval: 5,
        timezone: "UTC",
      },
      join: {
        waitForAll: true,
        mergeStrategy: "combine_text",
        separator: "\n\n---\n\n",
      },
      request_iterator: {
        baseUrl: "http://localhost:8080/api", // Пример, измени на свой
        executionMode: "sequential", // 'sequential' or 'parallel'
        commonHeaders: JSON.stringify({}, null, 2), // Example common
      },
      if_else: {
        conditionType: "equals",
        fieldPath: "output.text",
        compareValue: "",
        caseSensitive: false,
        enableGoto: false,
        maxGotoIterations: 10
      },
      dispatcher: {
        useAI: false,
        dispatcherAuthToken: '',
        routes: {}
      }
    }

    const newNode: Node = {
      id: `node-${Date.now()}`,
      type,
      position: { x: 300, y: 200 },
      data: {
        label: nodeType.label,
        config: defaultConfigs[type] || {},
      },
    }
    setNodes((prev) => [...prev, newNode])
  }

  const deleteNode = (nodeId: string) => {
    setNodes((prev) => prev.filter((node) => node.id !== nodeId))
    setConnections((prev) => prev.filter((conn) => conn.source !== nodeId && conn.target !== nodeId))
    if (selectedNode?.id === nodeId) {
      setSelectedNode(null)
    }
  }

  const handleMouseDown = (e: React.MouseEvent, node: Node) => {
    e.preventDefault()
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return

    setDraggedNode(node)
    setDragOffset({
      x: e.clientX - rect.left - node.position.x,
      y: e.clientY - rect.top - node.position.y,
    })
  }

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!draggedNode || !canvasRef.current) return

      const rect = canvasRef.current.getBoundingClientRect()
      const newPosition = {
        x: e.clientX - rect.left - dragOffset.x,
        y: e.clientY - rect.top - dragOffset.y,
      }

      setNodes((prev) => prev.map((node) => (node.id === draggedNode.id ? { ...node, position: newPosition } : node)))
    },
    [draggedNode, dragOffset],
  )

  const handleMouseUp = useCallback(() => {
    setDraggedNode(null)
  }, [])

  useEffect(() => {
    if (draggedNode) {
      document.addEventListener("mousemove", handleMouseMove)
      document.addEventListener("mouseup", handleMouseUp)
      return () => {
        document.removeEventListener("mousemove", handleMouseMove)
        document.removeEventListener("mouseup", handleMouseUp)
      }
    }
  }, [draggedNode, handleMouseMove, handleMouseUp])
  // Добавьте это состояние в начало компонента
  const [showExecutionSummary, setShowExecutionSummary] = useState(true);

  // Добавьте этот useEffect для автоматического показа сводки при появлении новых логов
  useEffect(() => {
    if (executionLogs.length > 0) {
      setShowExecutionSummary(true);
    }
  }, [executionLogs.length]);


  const startConnection = (nodeId: string) => {
    setConnecting(nodeId)
  }

  const completeConnection = (targetNodeId: string) => {
    if (connecting && connecting !== targetNodeId) {
      // Используем handleConnect для создания соединения
      handleConnect(targetNodeId);
    }
  };
  
  

  const getNodeTypeInfo = (type: string) => {
    return nodeTypes.find((nt) => nt.type === type) || nodeTypes[0]
  }

  

  const stopExecution = () => {
    if (abortController) {
      abortController.abort()
      setAbortController(null)
    }
    setIsExecuting(false)
    setActiveNode(null)
    setExecutionLogs((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        nodeId: "system",
        status: "error",
        message: "Execution stopped by user",
        timestamp: new Date(),
      },
    ])
  }
  const saveWorkflow = async () => {
    if (apiStatus === "offline" || nodes.length === 0) return;
      // Убедись, что все соединения имеют правильные метки для If/Else
    const connectionsWithLabels = getSanitizedConnections(); // <-- Используем хелпер
    

  
    try {
      setExecutionLogs((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          nodeId: "system",
          status: "running",
          message: "Saving workflow...",
          timestamp: new Date(),
        },
      ]);
  
      const response = await fetch(`${API_BASE_URL}/save-workflow`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: workflowName,
          nodes: nodes,
          connections: connectionsWithLabels,
        }),
      });
  
      const result = await response.json();
      if (result.success) {
        console.log("✅ Workflow saved successfully");
        setExecutionLogs((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            nodeId: "system",
            status: "success",
            message: "Workflow saved successfully",
            timestamp: new Date(),
          },
        ]);
      } else {
        console.error("❌ Failed to save workflow:", result.error);
        setExecutionLogs((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            nodeId: "system",
            status: "error",
            message: `Failed to save workflow: ${result.error}`,
            timestamp: new Date(),
          },
        ]);
      }
    } catch (error) {
      console.error("❌ Error saving workflow:", error);
      setExecutionLogs((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          nodeId: "system",
          status: "error",
          message: `Error saving workflow: ${error.message}`,
          timestamp: new Date(),
        },
      ]);
    }
  };
  
  const executeWorkflow = async (startNodeId?: string) => {
    if (nodes.length === 0) return
    // Убедись, что все соединения имеют правильные метки для If/Else
    const connectionsWithLabels = getSanitizedConnections(); // <-- Используем хелпер
    
    if (apiStatus === "offline") {
      alert("API сервер недоступен. Запустите FastAPI сервер на порту 8000.")
      return
    }
    // Сначала сохраняем workflow
    await handleSave();

    const controller = new AbortController()
    setAbortController(controller)
    setIsExecuting(true)
    setExecutionLogs([])
    setExecutionResults({})

    try {
      console.log("🚀 Executing workflow with nodes:", nodes)
      console.log("🔗 Connections:", connections)

      const response = await fetch(`${API_BASE_URL}/execute-workflow`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          nodes: nodes,
          connections: connectionsWithLabels,
          startNodeId: startNodeId,
        }),
        signal: controller.signal,
      })

      const result = await response.json()
      console.log("📊 Workflow execution result:", result)

      if (result.success) {
        // Обновляем результаты
        setExecutionResults(result.result || {})

        // Выводим результаты в консоль для отладки
        console.log("🔍 Detailed execution results:", result.result)
        const gigachatNodes = nodes.filter(node => node.type === 'gigachat')
        gigachatNodes.forEach(node => {
          if (result.result && result.result[node.id]) {
            console.log(`🤖 GigaChat node ${node.id} response:`, result.result[node.id])
            if (result.result[node.id].response) {
              console.log(`📝 GigaChat response text:`, result.result[node.id].response)
            }
            if (result.result[node.id].output && result.result[node.id].output.text) {
              console.log(`📄 GigaChat output text:`, result.result[node.id].output.text)
            }
          }
        })

        // Обновляем логи
        const logs = result.logs || []
        logs.forEach((log: any, index: number) => {
          setTimeout(() => {
            setExecutionLogs((prev) => [
              ...prev,
              {
                id: `${Date.now()}-${index}`,
                nodeId: log.nodeId || "system",
                status: log.level === "error" ? "error" : log.level === "success" ? "success" : "running",
                message: log.message,
                timestamp: new Date(log.timestamp),
                data: log.data,
              },
            ])

            // Подсвечиваем активную ноду
            if (log.nodeId && log.level !== "error") {
              setActiveNode(log.nodeId)
              setTimeout(() => setActiveNode(null), 1000)
            }
          }, index * 500) // Задержка для анимации
        })

        // Проверяем, есть ли ноды Timer в workflow
        const hasTimerNodes = nodes.some((node) => node.type === "timer")
        if (hasTimerNodes) {
          // Обновляем список таймеров
          loadTimers()
        }
      } else {
        setExecutionLogs([
          {
            id: Date.now().toString(),
            nodeId: "system",
            status: "error",
            message: result.error || "Unknown error",
            timestamp: new Date(),
          },
        ])
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        setExecutionLogs([
          {
            id: Date.now().toString(),
            nodeId: "system",
            status: "error",
            message: `Network error: ${error.message}`,
            timestamp: new Date(),
          },
        ])
      }
    } finally {
      setIsExecuting(false)
      setActiveNode(null)
      setAbortController(null)
    }
  }

  const executeNode = async (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId)
    if (!node || apiStatus === "offline") return

    setIsExecuting(true)
    setActiveNode(nodeId)

    try {
       // Если это нода таймера, сначала сохраняем workflow
      if (node.type === "timer") {
        await handleSave();
      }
      const response = await fetch(`${API_BASE_URL}/execute-node?node_type=${node.type}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          node_data: {
            id: node.id,
            type: node.type,
            position: node.position,
            data: {
              config: node.data.config,
              label: node.data.label,
            },
          },
          input_data: null,
        }),
      })

      const result = await response.json()

      if (result.success) {
        setExecutionResults((prev) => ({ ...prev, [nodeId]: result.result }))
        setExecutionLogs((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            nodeId,
            status: "success",
            message: `${node.data.label} executed successfully`,
            timestamp: new Date(),
            data: result.result,
          },
        ])

        // Если это нода Timer, обновляем список таймеров
        if (node.type === "timer") {
          loadTimers()
        }
      } else {
        setExecutionLogs((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            nodeId,
            status: "error",
            message: result.error || "Unknown error",
            timestamp: new Date(),
          },
        ])
      }
    } catch (error) {
      setExecutionLogs((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          nodeId,
          status: "error",
          message: `Network error: ${error.message}`,
          timestamp: new Date(),
        },
      ])
    } finally {
      setIsExecuting(false)
      setActiveNode(null)
    }
  }

  const updateNodeConfig = (field: string, value: any) => {
    if (!selectedNode) return

    setNodes((prev) =>
      prev.map((node) =>
        node.id === selectedNode.id
          ? {
              ...node,
              data: { ...node.data, config: { ...node.data.config, [field]: value } },
            }
          : node,
      ),
    )
    setSelectedNode((prev) =>
      prev
        ? {
            ...prev,
            data: { ...prev.data, config: { ...prev.data.config, [field]: value } },
          }
        : null,
    )
  }
  // НОВАЯ ФУНКЦИЯ
  const updateNodeData = (field: 'label', value: string) => {
    if (!selectedNode) return;

    const trimmedValue = value.trim();

    // Проверка на уникальность лейбла (только если это не текущая нода)
    if (field === 'label') {
      if (!trimmedValue) {
        alert("Имя ноды (label) не может быть пустым.");
        // "Отряхиваем" состояние, чтобы UI вернул старое значение
        setNodes(prev => [...prev]);
        return;
      }
      const isDuplicate = nodes.some(n => n.id !== selectedNode.id && n.data.label === trimmedValue);
      if (isDuplicate) {
        alert(`Имя ноды "${trimmedValue}" уже используется. Имена должны быть уникальными.`);
        setNodes(prev => [...prev]);
        return;
      }
    }

    // Обновляем состояние нод и выбранной ноды
    const newNodes = nodes.map(node =>
      node.id === selectedNode.id
        ? { ...node, data: { ...node.data, [field]: trimmedValue } }
        : node
    );
    setNodes(newNodes);

    setSelectedNode(prev =>
      prev
        ? { ...prev, data: { ...prev.data, [field]: trimmedValue } }
        : null
    );
  };

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* НОВОЕ: Добавляем компонент модального окна */}
      <WorkflowManagerModal
        isOpen={isWorkflowModalOpen}
        onClose={() => setWorkflowModalOpen(false)}
        workflows={workflows}
        onLoad={handleLoadWorkflow}
        onCreate={handleCreateWorkflow}
        onDelete={handleDeleteWorkflow}
        onClone={handleCloneWorkflow}
      />
      {/* Header */}
      <header className="p-2 border-b flex items-center justify-between bg-card shrink-0">
  <div className="flex items-center gap-4">
    <Button variant="outline" onClick={() => setWorkflowModalOpen(true)} size="sm">
      <FolderOpen className="h-4 w-4 mr-2" />
      <span>{currentWorkflowName}</span>
    </Button>
    <Button variant="ghost" size="sm" onClick={handleNewWorkflow}>
      Создать новый
    </Button>
    <Badge variant="secondary">{nodes.length} nodes</Badge>
    <Badge variant={apiStatus === "online" ? "default" : "destructive"}>
       API: {apiStatus}
    </Badge>
  </div>

  <div className="flex items-center gap-2">
    <Button variant="outline" size="sm" onClick={checkApiStatus}>
      <ExternalLink className="h-4 w-4 mr-2" />
      Check API
    </Button>

    <Button 
      variant="outline" 
      size="sm" 
      onClick={createWebhook}
      disabled={nodes.length === 0 || !nodes.some(n => n.type === "webhook_trigger") || apiStatus === "offline"}
    >
      <Webhook className="w-4 h-4 mr-2" />
        Create Webhook
    </Button>

    <Button onClick={handleSave} disabled={nodes.length === 0 || apiStatus === "offline"} size="sm">
      <Save className="h-4 w-4 mr-2" />
      {isSaving ? "Сохранение..." : (currentWorkflowId ? "Сохранить" : "Сохранить как...")}
    </Button>
    {isExecuting ? (
      <Button onClick={stopExecution} variant="destructive" size="sm">
        <Square className="h-4 w-4 mr-2" />
          Stop
      </Button>
      ) : (
      <Button onClick={() =>executeWorkflow()} disabled={nodes.length === 0 || apiStatus === "offline"} size="sm">
        <Play className="h-4 w-4 mr-2" />
          Выполнить
      </Button>
    )}
  </div>
</header>

      {/* API Status Alert */}
      {apiStatus === "offline" && (
        <Alert className="mx-4 mt-2">
          <AlertDescription>
            ⚠️ API сервер недоступен. {debugInfo}
            <br />
            Запустите FastAPI сервер: <code>python scripts/fastapi_server.py</code>
            <br />
            Или проверьте:{" "}
            <a href="http://localhost:8000/health" target="_blank" className="text-blue-600 underline" rel="noreferrer">
              http
            </a>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-1">
        {/* Sidebar */}
        <div className="w-80 bg-white border-r p-4 overflow-y-auto">
          <h3 className="font-semibold mb-4">Nodes</h3>
          <div className="space-y-2">
            {nodeTypes.map((nodeType) => (
              <Button
                key={nodeType.type}
                variant="outline"
                className="w-full justify-start"
                onClick={() => addNode(nodeType.type)}
              >
                <nodeType.icon className="w-4 h-4 mr-2" />
                {nodeType.label}
                {nodeType.canStart && (
                  <Badge variant="secondary" className="ml-auto text-xs">
                    Start
                  </Badge>
                )}
              </Button>
            ))}
          </div>

          {selectedNode && (
            <div className="mt-8">
              <h3 className="font-semibold mb-4">Node Settings</h3>
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm flex items-center justify-between">
                    {selectedNode.data.label}
                    {getNodeTypeInfo(selectedNode.type).canStart && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => executeNode(selectedNode.id)}
                        disabled={isExecuting || apiStatus === "offline"}
                      >
                        <Play className="w-3 h-3 mr-1" />
                        Test
                      </Button>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-2 border-b pb-4">
                      <Label htmlFor="nodeLabel" className="font-semibold">
                        Имя ноды (Label)
                      </Label>
                      <div className="relative flex items-center">
                        <Input
                          id="nodeLabel"
                          value={selectedNode.data.label || ''}
                          onChange={(e) => {
                            // Временно обновляем UI для отзывчивости
                            const newLabel = e.target.value;
                            setSelectedNode(prev => prev ? { ...prev, data: { ...prev.data, label: newLabel } } : null);
                          }}
                          onBlur={(e) => {
                            // Финальное обновление с валидацией при потере фокуса
                            updateNodeData('label', e.target.value);
                          }}
                          placeholder="Например: Получить данные клиента"
                          className="pr-10" // Место для кнопки
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          className="absolute right-1 top-1/2 -translate-y-1/2 h-8 w-8 text-gray-500 hover:text-gray-800"
                          title="Скопировать переменную шаблона"
                          onClick={() => {
                            if (!selectedNode.data.label) {
                              alert("Сначала введите имя ноды.");
                              return;
                            }
                            const template = `{{${selectedNode.data.label}}}`;
                            navigator.clipboard.writeText(template);
                            alert(`Шаблон "${template}" скопирован в буфер обмена!`);
                          }}
                        >
                          <Copy className="h-4 w-4" />
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Уникальное имя для ссылки в шаблонах. Например:{" "}
                        <code className="bg-muted px-1 py-0.5 rounded">
                          {"{{Имя ноды.output.text}}"}
                        </code>
                      </p>
                    </div>

                  {selectedNode.type === "gigachat" && (
                    <>
                      <div>
                        <Label htmlFor="role">Роль AI</Label>
                        <Select
                          value={selectedNode.data.config.role || "assistant"}
                          onValueChange={(value) => {
                            const role = gigaChatRoles.find(r => r.id === value);
                            if (role && value !== "custom") {
                              // Обновляем все поля сразу
                              setNodes((prev) =>
                                prev.map((node) =>
                                  node.id === selectedNode.id
                                    ? {
                                        ...node,
                                        data: {
                                          ...node.data,
                                          config: {
                                            ...node.data.config,
                                            role: value,
                                            systemMessage: role.systemMessage,
                                            userMessage: role.userMessage
                                          }
                                        }
                                      }
                                    : node
                                )
                              );
                              setSelectedNode((prev) =>
                                prev
                                  ? {
                                      ...prev,
                                      data: {
                                        ...prev.data,
                                        config: {
                                          ...prev.data.config,
                                          role: value,
                                          systemMessage: role.systemMessage,
                                          userMessage: role.userMessage
                                        }
                                      }
                                    }
                                  : null
                              );
                            } else {
                              updateNodeConfig("role", value);
                            }
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Выберите роль" />
                          </SelectTrigger>
                          <SelectContent>
                            {gigaChatRoles.map((role) => (
                              <SelectItem key={role.id} value={role.id}>
                                {role.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-gray-500 mt-1">
                          Выберите готовую роль или создайте свою
                        </p>
                      </div>
                      
                      <div>
                        <Label htmlFor="authToken">Auth Token</Label>
                        <Input
                          id="authToken"
                          type="password"
                          placeholder="Введите токен авторизации"
                          value={selectedNode.data.config.authToken || ""}
                          onChange={(e) => updateNodeConfig("authToken", e.target.value)}
                        />
                        <p className="text-xs text-gray-500 mt-1">Base64 токен для доступа к GigaChat API</p>
                      </div>
                      
                      <div>
                        <Label htmlFor="systemMessage">System Message</Label>
                        <Textarea
                          id="systemMessage"
                          placeholder="Ты полезный ассистент..."
                          value={selectedNode.data.config.systemMessage || ""}
                          onChange={(e) => updateNodeConfig("systemMessage", e.target.value)}
                          rows={3}
                          disabled={selectedNode.data.config.role && selectedNode.data.config.role !== "custom"}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          {selectedNode.data.config.role && selectedNode.data.config.role !== "custom" 
                            ? "Автоматически заполнено для выбранной роли" 
                            : "Системное сообщение для настройки поведения AI"}
                        </p>
                      </div>
                      
                      <div>
                        <Label htmlFor="userMessage">User Message</Label>
                        <Textarea
                          id="userMessage"
                          placeholder="Введите ваш вопрос..."
                          value={selectedNode.data.config.userMessage || ""}
                          onChange={(e) => updateNodeConfig("userMessage", e.target.value)}
                          rows={3}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          {selectedNode.data.config.role && selectedNode.data.config.role !== "custom" 
                            ? "Можете изменить пример сообщения" 
                            : "Сообщение пользователя для отправки в GigaChat"}
                        </p>
                      </div>
                      
                      <div className="flex items-center space-x-2">
                        <Switch
                          id="clearHistory"
                          checked={selectedNode.data.config.clearHistory || false}
                          onCheckedChange={(checked) => updateNodeConfig("clearHistory", checked)}
                        />
                        <Label htmlFor="clearHistory">Clear History</Label>
                      </div>
                      <p className="text-xs text-gray-500">Очистить историю диалога перед отправкой запроса</p>
                    </>
                  )}
                  {selectedNode.type === "webhook_trigger" && (
                    <>
                      <div>
                        <Label>Webhook Status</Label>
                        {selectedNode.data.config.webhookUrl ? (
                          <div className="space-y-2">
                            <div className="p-3 bg-green-50 rounded-md">
                              <p className="text-sm font-medium text-green-800">✅ Webhook активен</p>
                              <p className="text-xs text-green-600 mt-1 break-all">
                                {selectedNode.data.config.webhookUrl}
                              </p>
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              className="w-full"
                              onClick={() => {
                                navigator.clipboard.writeText(selectedNode.data.config.webhookUrl);
                                alert("URL скопирован в буфер обмена");
                              }}
                            >
                              <ExternalLink className="w-3 h-3 mr-2" />
                              Копировать URL
                            </Button>
                          </div>
                        ) : (
                          <div className="p-3 bg-gray-50 rounded-md">
                            <p className="text-sm text-gray-600">
                              Webhook не создан. Нажмите "Create Webhook" в верхней панели.
                            </p>
                          </div>
                        )}
                      </div>

                      <div className="flex items-center space-x-2">
                        <Switch
                          id="authRequired"
                          checked={selectedNode.data.config.authRequired || false}
                          onCheckedChange={(checked) => updateNodeConfig("authRequired", checked)}
                        />
                        <Label htmlFor="authRequired">Требовать авторизацию</Label>
                      </div>

                      <div>
                        <Label htmlFor="allowedIps">Разрешенные IP адреса</Label>
                        <Textarea
                          id="allowedIps"
                          placeholder="192.168.1.1&#10;10.0.0.1"
                          value={selectedNode.data.config.allowedIps || ""}
                          onChange={(e) => updateNodeConfig("allowedIps", e.target.value)}
                          rows={3}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Оставьте пустым для доступа с любых IP. Каждый IP с новой строки.
                        </p>
                      </div>
                    </>
                  )}
                  {selectedNode.type === "webhook" && (
                    <>
                      <div>
                        <Label htmlFor="url">Target URL</Label>
                        <Input
                          id="url"
                          placeholder="https://api.example.com/items/{{node-1.json.itemId}}"
                          value={selectedNode.data.config.url || ""}
                          onChange={(e) => updateNodeConfig("url", e.target.value)}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          URL для отправки запроса. Поддерживает шаблоны: {"{{node-id.json.field}}"}
                        </p>
                      </div>

                      <div>
                        <Label htmlFor="method">HTTP Method</Label>
                        <Select
                          value={selectedNode.data.config.method || "POST"}
                          onValueChange={(value) => updateNodeConfig("method", value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="POST" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="GET">GET</SelectItem>
                            <SelectItem value="POST">POST</SelectItem>
                            <SelectItem value="PUT">PUT</SelectItem>
                            <SelectItem value="PATCH">PATCH</SelectItem>
                            <SelectItem value="DELETE">DELETE</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <div>
                        <Label htmlFor="headers">Headers</Label>
                        <Textarea
                          id="headers"
                          placeholder="Content-Type: application/json&#10;Authorization: Bearer {{node-auth.json.token}}"
                          value={selectedNode.data.config.headers || "Content-Type: application/json"}
                          onChange={(e) => updateNodeConfig("headers", e.target.value)}
                          rows={3}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Заголовки запроса (каждый с новой строки). Поддерживает шаблоны.
                        </p>
                      </div>
                      
                      {/* Ваш новый, абсолютно правильный блок */}
                      <div className="mt-2">
                        <Label htmlFor="bodyTemplate">Request Body (JSON с шаблонами)</Label>
                        <Textarea
                          id="bodyTemplate"
                          placeholder={`{
  "name": "Новый клиент",
  "source_id": "{{node-1.json.id}}",
  "comment": "{{node-2.text}}"
}`}
                          value={selectedNode.data.config.bodyTemplate || ""}
                          onChange={(e) => updateNodeConfig("bodyTemplate", e.target.value)}
                          rows={5}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Тело запроса для методов POST/PUT/PATCH. Используйте шаблоны для динамических данных.
                        </p>
                      </div>

                      <Alert className="mt-4">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription className="text-xs">
                          Эта нода отправляет HTTP запрос на указанный URL с данными, сформированными из шаблона тела запроса.
                        </AlertDescription>
                      </Alert>
                    </>
                  )}

                  {selectedNode.type === "email" && (
                    <>
                      <div>
                        <Label htmlFor="to">To</Label>
                        <Input
                          id="to"
                          placeholder="recipient@example.com"
                          value={selectedNode.data.config.to || ""}
                          onChange={(e) => updateNodeConfig("to", e.target.value)}
                        />
                      </div>
                      <div>
                        <Label htmlFor="subject">Subject</Label>
                        <Input
                          id="subject"
                          placeholder="Оставьте пустым для автозаполнения"
                          value={selectedNode.data.config.subject || ""}
                          onChange={(e) => updateNodeConfig("subject", e.target.value)}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Если пусто, будет использован результат предыдущей ноды
                        </p>
                      </div>
                      <div>
                        <Label htmlFor="body">Body</Label>
                        <Textarea
                          id="body"
                          placeholder="Оставьте пустым для автозаполнения"
                          value={selectedNode.data.config.body || ""}
                          onChange={(e) => updateNodeConfig("body", e.target.value)}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Если пусто, будет использован результат предыдущей ноды
                        </p>
                      </div>
                    </>
                  )}
                  {selectedNode.type === "database" && (
                    <>
                      <div>
                        <Label htmlFor="query">SQL Query</Label>
                        <Textarea
                          id="query"
                          placeholder="Оставьте пустым для автозаполнения"
                          value={selectedNode.data.config.query || ""}
                          onChange={(e) => updateNodeConfig("query", e.target.value)}
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Если пусто, будет создан INSERT с данными предыдущей ноды
                        </p>
                      </div>
                      <div>
                        <Label htmlFor="connection">Connection</Label>
                        <Select
                          value={selectedNode.data.config.connection || "postgres"}
                          onValueChange={(value) => updateNodeConfig("connection", value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select database" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="postgres">PostgreSQL</SelectItem>
                            <SelectItem value="mysql">MySQL</SelectItem>
                            <SelectItem value="sqlite">SQLite</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                  {selectedNode.type === "timer" && (
                    <>
                      <div>
                        <Label htmlFor="interval">Interval (minutes)</Label>
                        <Input
                          id="interval"
                          type="number"
                          placeholder="5"
                          value={selectedNode.data.config.interval || ""}
                          onChange={(e) => updateNodeConfig("interval", e.target.value)}
                        />
                      </div>
                      <div>
                        <Label htmlFor="timezone">Timezone</Label>
                        <Select
                          value={selectedNode.data.config.timezone || "UTC"}
                          onValueChange={(value) => updateNodeConfig("timezone", value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="UTC" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="UTC">UTC</SelectItem>
                            <SelectItem value="Europe/Moscow">Europe/Moscow</SelectItem>
                            <SelectItem value="America/New_York">America/New_York</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      {/* Информация о статусе таймера */}
                      {timers.some((timer) => timer.node_id === selectedNode.id) && (
                        <div className="mt-4 p-3 bg-gray-50 rounded-md">
                          <h4 className="text-sm font-medium mb-2">Timer Status</h4>
                          {timers
                            .filter((timer) => timer.node_id === selectedNode.id)
                            .map((timer) => (
                              <div key={timer.id} className="space-y-2">
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-medium">Status:</span>
                                  {timer.status === "active" && (
                                    <Badge variant="outline" className="text-xs bg-green-50">
                                      <CheckCircle className="w-3 h-3 mr-1 text-green-500" />
                                      Active
                                    </Badge>
                                  )}
                                  {timer.status === "paused" && (
                                    <Badge variant="outline" className="text-xs bg-yellow-50">
                                      <Pause className="w-3 h-3 mr-1 text-yellow-500" />
                                      Paused
                                    </Badge>
                                  )}
                                  {timer.status === "error" && (
                                    <Badge variant="outline" className="text-xs bg-red-50">
                                      <AlertCircle className="w-3 h-3 mr-1 text-red-500" />
                                      Error
                                    </Badge>
                                  )}
                                </div>
                                <div className="flex items-center justify-between">
                                  <span className="text-xs font-medium">Next run:</span>
                                  <span className="text-xs">{new Date(timer.next_execution).toLocaleString()}</span>
                                </div>
                                <div className="flex items-center justify-between mt-2">
                                  {timer.status === "active" ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 text-xs"
                                      onClick={() => pauseTimer(timer.id)}
                                    >
                                      <Pause className="w-3 h-3 mr-1" />
                                      Pause Timer
                                    </Button>
                                  ) : (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 text-xs"
                                      onClick={() => resumeTimer(timer.id)}
                                    >
                                      <Play className="w-3 h-3 mr-1" />
                                      Resume Timer
                                    </Button>
                                  )}
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 text-xs"
                                    onClick={() => executeTimerNow(timer.id)}
                                  >
                                    <RefreshCw className="w-3 h-3 mr-1" />
                                    Run Now
                                  </Button>
                                </div>
                              </div>
                            ))}
                        </div>
                      )}
                    </>
                  )}
                  {selectedNode.type === "join" && (
                    <>
                      <div className="flex items-center space-x-2">
                        <Switch
                          id="waitForAll"
                          checked={selectedNode.data.config.waitForAll ?? true}
                          onCheckedChange={(checked) => updateNodeConfig("waitForAll", checked)}
                        />
                        <Label htmlFor="waitForAll">Wait for all inputs</Label>
                      </div>
                      <p className="text-xs text-gray-500">Ждать данные от всех входящих соединений</p>
                      
                      <div>
                        <Label htmlFor="mergeStrategy">Merge Strategy</Label>
                        <Select
                          value={selectedNode.data.config.mergeStrategy || "combine_text"}
                          onValueChange={(value) => updateNodeConfig("mergeStrategy", value)}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Select strategy" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="combine_text">Combine Text (объединить тексты)</SelectItem>
                            <SelectItem value="merge_json">Merge JSON (объединить в JSON)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {selectedNode.data.config.mergeStrategy === "combine_text" && (
                        <div>
                          <Label htmlFor="separator">Text Separator</Label>
                          <Input
                            id="separator"
                            placeholder="\n\n---\n\n"
                            value={selectedNode.data.config.separator || ""}
                            onChange={(e) => updateNodeConfig("separator", e.target.value)}
                          />
                          <p className="text-xs text-gray-500 mt-1">
                            Разделитель между текстами (используйте \n для новой строки)
                          </p>
                        </div>
                      )}
                    </>
                  )}
                  {selectedNode.type === "request_iterator" && (
  <>
    {/* Informational Alert - Принцип работы */}
    <Alert>
      <AlertCircle className="h-4 w-4" />
      <AlertDescription className="text-xs">
        <p className="font-medium mb-1">Принцип работы ноды:</p>
        Эта нода ожидает на вход JSON-массив с описанием HTTP-запросов, выполняет их и возвращает массив с результатами.
      </AlertDescription>
    </Alert>

    {/* НОВОЕ ПОЛЕ: JSON Input */}
    <div className="mt-4">
      <Label htmlFor="jsonInput">JSON Input (с поддержкой шаблонов)</Label>
      <Textarea
        id="jsonInput"
        placeholder="{{ node-123.text }}"
        value={selectedNode.data.config.jsonInput || ""}
        onChange={(e) => updateNodeConfig("jsonInput", e.target.value)}
        rows={3}
      />
      <p className="text-xs text-gray-500 mt-1">
        Укажите, откуда брать JSON-массив для запросов.
        <br />
        Пример: <strong>{"{{ node-1751277373449.text }}"}</strong>
      </p>
    </div>

    {/* Base URL */}
    <div className="mt-4">
      <Label htmlFor="baseUrl">Base URL (API)</Label>
      <Input
        id="baseUrl"
        placeholder="http://api-host:port/api"
        value={selectedNode.data.config.baseUrl || ""}
        onChange={(e) => updateNodeConfig("baseUrl", e.target.value)}
      />
      <p className="text-xs text-gray-500 mt-1">
        Базовый URL. Эндпоинты из JSON будут добавлены к нему.
      </p>
    </div>

    {/* Execution Mode */}
    <div className="mt-4">
      <Label htmlFor="executionMode">Режим выполнения</Label>
      <Select
        value={selectedNode.data.config.executionMode || "sequential"}
        onValueChange={(value) => updateNodeConfig("executionMode", value)}
      >
        <SelectTrigger id="executionMode">
          <SelectValue placeholder="Выберите режим" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="sequential">Последовательно</SelectItem>
          <SelectItem value="parallel">Параллельно</SelectItem>
        </SelectContent>
      </Select>
    </div>

    {/* Common Headers */}
    <div className="mt-4">
      <Label htmlFor="commonHeaders">Общие заголовки (JSON)</Label>
      <Textarea
        id="commonHeaders"
        placeholder={JSON.stringify({"Authorization": "Bearer YOUR_TOKEN"}, null, 2)}
        value={selectedNode.data.config.commonHeaders || JSON.stringify({}, null, 2)}
        onChange={(e) => updateNodeConfig("commonHeaders", e.target.value)}
        rows={3}
      />
      <p className="text-xs text-gray-500 mt-1">
        JSON-объект с заголовками для всех запросов.
      </p>
    </div>

    {/* Пример входного JSON для справки */}
    <Alert className="mt-6">
      <Info className="h-4 w-4" />
      <AlertDescription className="text-xs">
        <p className="mt-2 font-medium">Пример входного JSON:</p>
        <pre className="mt-1 p-2 bg-gray-100 rounded text-[11px] leading-tight overflow-x-auto">
          {`[
  {
    "endpoint": "/resource/1",
    "method": "GET"
  },
  {
    "endpoint": "/resource",
    "method": "POST",
    "body": {"key": "value"}
  }
]`}
        </pre>
      </AlertDescription>
    </Alert>
  </>
)}

                  {selectedNode.type === "if_else" && (
                                      <>
                                        <div className="space-y-4">
                                          <div>
                                            <Label htmlFor="conditionType">Тип условия</Label>
                                            <Select
                                              value={selectedNode.data.config.conditionType || "equals"}
                                              onValueChange={(value) => updateNodeConfig("conditionType", value)}
                                            >
                                              <SelectTrigger id="conditionType">
                                                <SelectValue />
                                              </SelectTrigger>
                                              <SelectContent>
                                                <SelectItem value="equals">Равно (=)</SelectItem>
                                                <SelectItem value="not_equals">Не равно (≠)</SelectItem>
                                                <SelectItem value="contains">Содержит текст</SelectItem>
                                                <SelectItem value="not_contains">Не содержит текст</SelectItem>
                                                <SelectItem value="greater">{`Больше (>)`}</SelectItem>
                                                <SelectItem value="less">{`Меньше (<)`}</SelectItem>
                                                <SelectItem value="regex">Регулярное выражение</SelectItem>
                                                <SelectItem value="exists">Поле существует</SelectItem>
                                                <SelectItem value="is_empty">Поле пустое</SelectItem>
                                                <SelectItem value="is_not_empty">Поле не пустое</SelectItem>
                                              </SelectContent>
                                            </Select>
                                          </div>

                                          <div>
                                            <Label htmlFor="fieldPath">Путь к полю для проверки</Label>
                                            <Input
                                              id="fieldPath"
                                              placeholder="output.text"
                                              value={selectedNode.data.config.fieldPath || "output.text"}
                                              onChange={(e) => updateNodeConfig("fieldPath", e.target.value)}
                                            />
                                            <p className="text-xs text-gray-500 mt-1">
                                              Путь к данным из предыдущей ноды. Примеры:
                                              <br />• output.text - текст ответа
                                              <br />• output.status - статус код
                                              <br />• output.json.items[0].id - вложенные данные
                                            </p>
                                          </div>

                                          <div>
                                            <Label htmlFor="compareValue">Значение для сравнения</Label>
                                            <Input
                                              id="compareValue"
                                              placeholder="Введите значение"
                                              value={selectedNode.data.config.compareValue || ""}
                                              onChange={(e) => updateNodeConfig("compareValue", e.target.value)}
                                            />
                                            <p className="text-xs text-gray-500 mt-1">
                                              Оставьте пустым для условий "exists", "is_empty", "is_not_empty"
                                            </p>
                                          </div>

                                          <div className="flex items-center space-x-2">
                                            <Switch
                                              id="caseSensitive"
                                              checked={selectedNode.data.config.caseSensitive || false}
                                              onCheckedChange={(checked) => updateNodeConfig("caseSensitive", checked)}
                                            />
                                            <Label htmlFor="caseSensitive">Учитывать регистр букв</Label>
                                          </div>

                                          <div>
                                            <Label htmlFor="maxGotoIterations">Максимум goto переходов (защита от циклов)</Label>
                                            <Input
                                              id="maxGotoIterations"
                                              type="number"
                                              min="1"
                                              max="100"
                                              value={selectedNode.data.config.maxGotoIterations || 10}
                                              onChange={(e) => updateNodeConfig("maxGotoIterations", parseInt(e.target.value))}
                                            />
                                            <p className="text-xs text-gray-500 mt-1">
                                              Если используете goto для циклов, это предотвратит бесконечные циклы
                                            </p>
                                          </div>

                                          {/* Информация о соединениях */}
                                          {/* <div className="border-t pt-4">
                                            <h4 className="font-medium mb-2">Как использовать:</h4>
                                            <div className="text-sm text-gray-600 space-y-1">
                                              <p>1. Потяните от <span className="text-green-600 font-bold">зеленого порта (T)</span> для TRUE ветки</p>
                                              <p>2. Потяните от <span className="text-red-600 font-bold">красного порта (F)</span> для FALSE ветки</p>
                                              <p>3. При создании соединения выберите:</p>
                                              <ul className="ml-4 list-disc">
                                                <li><strong>Обычный переход</strong> - для линейного выполнения</li>
                                                <li><strong>GOTO переход</strong> - для создания циклов</li>
                                              </ul>
                                            </div>
                                          </div> */}
                                          

                                          <div className="flex items-center space-x-2">
                    <Switch
                      id="enableGoto"
                      checked={selectedNode.data.config.enableGoto || false}
                      onCheckedChange={(checked) => updateNodeConfig("enableGoto", checked)}
                    />
                    <Label htmlFor="enableGoto">Включить GOTO режим (для циклов)</Label>
                  </div>
                  <p className="text-xs text-gray-500">
                    Позволяет создавать циклические переходы обратно к предыдущим нодам
                  </p>

                                          {/* Текущие соединения */}
                                          <div className="border-t pt-4">
                                            <h4 className="font-medium mb-2">Текущие соединения:</h4>
                                            <div className="text-sm space-y-1">
                                              {connections
                                                .filter(c => c.source === selectedNode.id)
                                                .map(conn => {
                                                  const targetNode = nodes.find(n => n.id === conn.target);
                                                  const label = conn.data?.label || 'обычное';
                                                  const color = label.startsWith('true') ? 'text-green-600' : 'text-red-600';
                                                  const isGoto = label.includes('goto');
                                                  
                                                  return (
                                                    <div key={conn.id} className="flex items-center gap-2">
                                                      <span className={`${color} font-medium`}>
                                                        {label}
                                                      </span>
                                                      <span>→</span>
                                                      <span className="font-medium">
                                                        {targetNode?.data.label || targetNode?.type || conn.target}
                                                      </span>
                                                      {isGoto && <span className="text-purple-600 text-xs">(GOTO)</span>}
                                                    </div>
                                                  );
                                                })}
                                              {connections.filter(c => c.source === selectedNode.id).length === 0 && (
                                                <p className="text-gray-500">Нет соединений</p>
                                              )}
                                            </div>
                                          </div>
                                        </div>
                                      </>
                  )}
                  {/********************************************/}
                  {/*     НАЧАЛО БЛОКА ДЛЯ НОДЫ "ДИСПЕТЧЕР"     */}
                  {/********************************************/}
                  {selectedNode.type === "dispatcher" && (() => {
  // Получаем маршруты из конфига
  const routes = selectedNode.data.config?.routes || {};
  const routeEntries = Object.entries(routes);

  // Типы диспетчера
  const dispatcherTypes = [
    { value: "router", label: "Маршрутизатор" },
    { value: "orchestrator", label: "Оркестратор" },
  ];

  // Функции для работы с маршрутами
  const handleRouteConfigChange = (category, field, value) => {
    const newRoutes = { ...routes };
    if (!newRoutes[category]) newRoutes[category] = {};
    newRoutes[category][field] = value;
    updateNodeConfig('routes', newRoutes);
  };

  const handleCategoryChange = (oldCategory, newCategory) => {
    if (oldCategory === newCategory || !newCategory.trim() || routes[newCategory]) return;
    const newRoutes = { ...routes };
    newRoutes[newCategory] = newRoutes[oldCategory];
    delete newRoutes[oldCategory];
    updateNodeConfig('routes', newRoutes);
  };

  const handleAddRoute = () => {
    const newCategory = `Новый маршрут ${Object.keys(routes).length + 1}`;
    const newRoutes = { ...routes, [newCategory]: { workflow_id: '', keywords: [] } };
    updateNodeConfig('routes', newRoutes);
  };

  const handleDeleteRoute = (category) => {
    const newRoutes = { ...routes };
    delete newRoutes[category];
    updateNodeConfig('routes', newRoutes);
  };

  // Проверяем режим
  const isOrchestrator = selectedNode.data.config.dispatcherType === "orchestrator";

  return (
    <div className="p-4 space-y-4">
      <h3 className="text-lg font-semibold">Настройки Диспетчера</h3>

      {/* Выбор типа диспетчера */}
      <div>
        <Label htmlFor="dispatcherType">Тип диспетчера</Label>
        <Select
          value={selectedNode.data.config.dispatcherType || "router"}
          onValueChange={(value) => updateNodeConfig("dispatcherType", value)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Выберите тип" />
          </SelectTrigger>
          <SelectContent>
            {dispatcherTypes.map((type) => (
              <SelectItem key={type.value} value={type.value}>
                {type.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
  <Label htmlFor="userQueryTemplate" className="mb-1 block">
    Шаблон для поиска пользовательского запроса
  </Label>
  <Input
    id="userQueryTemplate"
    placeholder="Например: {{ Webhook Trigger.output.text }}"
    value={selectedNode.data.config.userQueryTemplate || ''}
    onChange={e => updateNodeConfig('userQueryTemplate', e.target.value)}
    className="mb-2"
  />
  <div className="text-xs text-muted-foreground">
    Используйте <code>{'{{ label_ноды.output.text }}'}</code> или <code>{'{{ node-id.output.text }}'}</code>
  </div>
</div>


      {/* Настройки для router */}
      {!isOrchestrator && (
        <>
          <div className="flex items-center space-x-2">
            <Switch
              id="use-ai-switch"
              checked={selectedNode.data.config?.useAI || false}
              onCheckedChange={(checked) => updateNodeConfig('useAI', checked)}
            />
            <Label htmlFor="use-ai-switch">Использовать AI для маршрутизации</Label>
          </div>
          {selectedNode.data.config?.useAI && (
            <div>
              <Label>Токен GigaChat для диспетчера</Label>
              <Input
                type="password"
                placeholder="Введите токен..."
                value={selectedNode.data.config?.dispatcherAuthToken || ''}
                onChange={(e) => updateNodeConfig('dispatcherAuthToken', e.target.value)}
              />
              <div className="mt-4">
              <Label htmlFor="dispatcherPrompt">Промпт для AI маршрутизации</Label>
              <Textarea
                id="dispatcherPrompt"
                placeholder="Определи категорию запроса пользователя и выбери подходящий обработчик..."
                value={selectedNode.data.config?.dispatcherPrompt || ''}
                onChange={e => updateNodeConfig('dispatcherPrompt', e.target.value)}
                rows={5}
                className="mt-1"
              />
              <div className="text-xs text-muted-foreground mt-1">
                Здесь вы можете задать собственную инструкцию для GigaChat.<br />
                Используйте <code>{'{категории}'}</code> и <code>{'{запрос пользователя}'}</code> для подстановки.
              </div>
            </div>
            </div>
          )}
          <h4 className="text-md font-semibold border-t pt-4">Маршруты</h4>
          <ScrollArea className="h-[350px] w-full">
            <div className="space-y-3 pr-4">
              {routeEntries.map(([category, config]) => (
                <div key={category} className="p-3 border rounded-lg bg-card">
                  <div className="flex justify-between items-center mb-3">
                    <Input
                      defaultValue={category}
                      className="font-semibold text-md h-8 border-0 shadow-none focus-visible:ring-1"
                      onBlur={(e) => handleCategoryChange(category, e.target.value)}
                    />
                    <Button variant="ghost" size="icon" onClick={() => handleDeleteRoute(category)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <Label>Вызываемый Workflow</Label>
                      <Select
                        value={config.workflow_id || ''}
                        onValueChange={(value) => handleRouteConfigChange(category, 'workflow_id', value)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Выберите workflow..." />
                        </SelectTrigger>
                        <SelectContent>
                          {workflows.map(wf => (
                            <SelectItem key={wf.id} value={wf.id}>
                              {wf.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {!selectedNode.data.config?.useAI && (
                      <div>
                        <Label>Ключевые слова (через запятую)</Label>
                        <Input
                          placeholder="заказ, статус, купить..."
                          value={(config.keywords || []).join(', ')}
                          onChange={(e) =>
                            handleRouteConfigChange(category, 'keywords', e.target.value.split(',').map(k => k.trim()))
                          }
                        />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
          <Button onClick={handleAddRoute} className="mt-2 w-full">
            Добавить маршрут
          </Button>
        </>
      )}

      {/* Настройки для orchestrator */}
      {isOrchestrator && (
  <div>
    <Label htmlFor="availableWorkflows" className="mb-2 block text-base font-medium">
      Доступные Workflow для Оркестратора
    </Label>
    <div className="flex flex-col gap-2">
      {workflows.map((wf) => (
        <label
          key={wf.id}
          htmlFor={`workflow-${wf.id}`}
          className="flex items-center gap-2 p-2 rounded hover:bg-muted transition"
        >
          <Checkbox
            id={`workflow-${wf.id}`}
            checked={
              !!(
                selectedNode.data.config.availableWorkflows &&
                selectedNode.data.config.availableWorkflows[wf.id] !== undefined
              )
            }
            onCheckedChange={(checked) => {
              const newAvailableWorkflows = { ...selectedNode.data.config.availableWorkflows };
              if (checked) {
                newAvailableWorkflows[wf.id] = { description: wf.name };
              } else {
                delete newAvailableWorkflows[wf.id];
              }
              updateNodeConfig("availableWorkflows", newAvailableWorkflows);
            }}
          />
          <span className="text-base">{wf.name}</span>
        </label>
      ))}
    </div>
  </div>
)}

    </div>
  );
})()}

                  {/********************************************/}
                  {/*      КОНЕЦ БЛОКА ДЛЯ НОДЫ "ДИСПЕТЧЕР"      */}
                  {/********************************************/}

                                 
                </CardContent>
              </Card>
            </div>
          )}
        </div>

        {/* Canvas */}
        <div className="flex-1 relative overflow-auto">
          <div
            ref={canvasRef}
            className="w-full h-full relative bg-gray-50"
            style={{
              width: "3000px",  // Фиксированная ширина холста
              height: "2000px", // Фиксированная высота холста
              backgroundImage: "radial-gradient(circle, #e5e7eb 1px, transparent 1px)",
              backgroundSize: "20px 20px",
            }}
          >
            {/* SVG for connections */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              <defs>
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#6366f1" />
                </marker>
              </defs>
              {connections.map(renderConnection)}
            </svg>

            {/* Nodes */}
            {nodes.map((node) => {
              const nodeTypeInfo = getNodeTypeInfo(node.type)
              const IconComponent = nodeTypeInfo.icon

              return (
                <div
                  key={node.id}
                  // Обновите класс для нод
                  className={`absolute cursor-move select-none 
                    ${selectedNode?.id === node.id ? "ring-2 ring-blue-500" : ""} 
                    ${activeNode === node.id ? "ring-2 ring-green-500 animate-pulse" : ""} 
                    ${executionResults[node.id] ? 
                      executionLogs.some(log => log.nodeId === node.id && log.status === "error") ? 
                        "ring-2 ring-red-500" : 
                        "ring-2 ring-green-500" : 
                      ""}`}

                  style={{
                    left: node.position.x,
                    top: node.position.y,
                    transform: draggedNode?.id === node.id ? "scale(1.05)" : "scale(1)",
                    transition: draggedNode?.id === node.id ? "none" : "transform 0.1s",
                  }}
                  onMouseDown={(e) => handleMouseDown(e, node)}
                  onClick={(e) => {
                    setSelectedNode(node);
                    // Если есть результаты выполнения и был сделан двойной клик, показываем результаты
                    if (executionResults[node.id] && e.detail === 2) {
                      setSelectedResult({
                        nodeId: node.id,
                        data: executionResults[node.id]
                      });
                    }
                  }}
                  >
                  <Card className="w-48 shadow-lg hover:shadow-xl transition-shadow">
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div
                            className={`w-8 h-8 rounded-full ${nodeTypeInfo.color} flex items-center justify-center`}
                          >
                            <IconComponent className="w-4 h-4 text-white" />
                          </div>
                          <CardTitle className="text-sm">{node.data.label}</CardTitle>
                          {executionResults[node.id] && (
                            <div className="ml-auto">
                              {executionLogs.some(log => log.nodeId === node.id && log.status === "error") ? (
                                <AlertCircle className="w-4 h-4 text-red-500" />
                              ) : (
                                <CheckCircle className="w-4 h-4 text-green-500" />
                              )}
                            </div>
                          )}
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteNode(node.id)
                          }}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
  <div className="flex justify-between items-center">
    {node.type === 'if_else' ? (
      // Специальные кнопки для If/Else
      <>
        {connecting && connecting.startsWith(node.id) ? (
          // Если уже нажали Connect на этой ноде - показываем Cancel
          <Button
            variant="outline"
            size="sm"
            className="h-6 text-xs w-full"
            onClick={(e) => {
              e.stopPropagation()
              setConnecting(null)
            }}
          >
            Cancel
          </Button>
        ) : connecting && !connecting.startsWith(node.id) ? (
          // Если нажали Connect на другой ноде - показываем Target
          <Button
            variant="default"
            size="sm"
            className="h-6 text-xs w-full"
            onClick={(e) => {
              e.stopPropagation()
              completeConnection(node.id)
            }}
          >
            Target
          </Button>
        ) : (
          // Исходное состояние - две кнопки Connect
          <div className="flex gap-1 w-full">
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs flex-1 text-green-600 hover:bg-green-50"
              onClick={(e) => {
                e.stopPropagation()
                setConnecting(`${node.id}:true`)
              }}
            >
              True
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs flex-1 text-red-600 hover:bg-red-50"
              onClick={(e) => {
                e.stopPropagation()
                setConnecting(`${node.id}:false`)
              }}
            >
              False
            </Button>
          </div>
        )}
      </>
    ) : (
      // Обычные кнопки для остальных нод
      <>
        <Button
          variant="outline"
          size="sm"
          className="h-6 text-xs"
          onClick={(e) => {
            e.stopPropagation()
            startConnection(node.id)
          }}
        >
          Connect
        </Button>
        {connecting && connecting !== node.id && (
          <Button
            variant="default"
            size="sm"
            className="h-6 text-xs"
            onClick={(e) => {
              e.stopPropagation()
              completeConnection(node.id)
            }}
          >
            Target
          </Button>
        )}
      </>
    )}
    
    {/* Кнопка Play для нод, которые могут стартовать */}
    {nodeTypeInfo.canStart && (
      <Button
        variant="secondary"
        size="sm"
        className="h-6 text-xs ml-2"
        onClick={(e) => {
          e.stopPropagation()
          executeNode(node.id)
        }}
        disabled={isExecuting || apiStatus === "offline"}
      >
        <Play className="w-3 h-3" />
      </Button>
    )}
  </div>
  
  {/* Блок с результатами остается без изменений */}
  {executionResults[node.id] && (
    <div className="mt-2 flex justify-end">
      <Button
        variant="ghost"
        size="sm"
        className="h-6 text-xs"
        onClick={(e) => {
          e.stopPropagation();
          setSelectedResult({
            nodeId: node.id,
            data: executionResults[node.id]
          });
        }}
        title="Просмотр результатов"
      >
        <ExternalLink className="w-3 h-3 mr-1" />
        Результаты
      </Button>
    </div>
  )}
</CardContent>

                  </Card>
                </div>
              )
            })}

            {/* Empty state */}
            {nodes.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 bg-gray-200 rounded-full flex items-center justify-center">
                    <Plus className="w-8 h-8 text-gray-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-gray-600 mb-2">Start building your workflow</h3>
                  <p className="text-gray-500 mb-4">Add nodes from the sidebar to create your automation</p>
                  <Button onClick={() => addNode("gigachat")}>
                    <Plus className="w-4 h-4 mr-2" />
                    Add GigaChat Node
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* Execution Logs Panel */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-4">
        {/* Active Timers Panel */}
        {timers.length > 0 && (
          <div className="w-70 ml-auto bg-white border rounded-lg shadow-lg overflow-hidden">
            <div className="bg-gray-50 px-4 py-2 border-b flex items-center justify-between">
              <h3 className="font-semibold text-sm flex items-center">
                <Clock className="w-4 h-4 mr-2" />
                Active Timers
              </h3>
              <Button variant="ghost" size="sm" onClick={loadTimers} className="h-6 w-6 p-0">
                <RefreshCw className="w-3 h-3" />
              </Button>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {timers.map((timer) => {
                const timerNode = nodes.find((n) => n.id === timer.node_id)
                const nextExecution = new Date(timer.next_execution)

                return (
                  <div key={timer.id} className="p-3 border-b last:border-b-0">
                    <div className="flex items-center justify-between mb-1">
                      <div className="font-medium text-sm">
                        {timerNode?.data.label || `Timer ${timer.id.split("_")[1]}`}
                      </div>
                      <div className="flex items-center gap-1">
                        {timer.status === "active" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0"
                            onClick={() => pauseTimer(timer.id)}
                            title="Pause timer"
                          >
                            <Pause className="w-3 h-3" />
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0"
                            onClick={() => resumeTimer(timer.id)}
                            title="Resume timer"
                          >
                            <Play className="w-3 h-3" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          onClick={() => executeTimerNow(timer.id)}
                          title="Execute now"
                        >
                          <RefreshCw className="w-3 h-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0 text-red-500"
                          onClick={() => deleteTimer(timer.id)}
                          title="Delete timer"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </div>
                    <div className="text-xs text-gray-500 flex items-center gap-2">
                      <span>Every {timer.interval} minutes</span>
                      {timer.status === "active" && (
                        <Badge variant="outline" className="text-xs">
                          <CheckCircle className="w-3 h-3 mr-1 text-green-500" />
                          Active
                        </Badge>
                      )}
                      {timer.status === "paused" && (
                        <Badge variant="outline" className="text-xs">
                          <Pause className="w-3 h-3 mr-1 text-yellow-500" />
                          Paused
                        </Badge>
                      )}
                      {timer.status === "error" && (
                        <Badge variant="outline" className="text-xs">
                          <AlertCircle className="w-3 h-3 mr-1 text-red-500" />
                          Error
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs mt-1">Next run: {nextExecution.toLocaleString()}</div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Execution Logs */}
        {executionLogs.length > 0 && (
          <div className="w-96 max-h-64 bg-white border rounded-lg shadow-lg overflow-hidden">
            <div className="bg-gray-50 px-4 py-2 border-b flex items-center justify-between">
              <h3 className="font-semibold text-sm">Execution Logs</h3>
              <Button variant="ghost" size="sm" onClick={() => setExecutionLogs([])} className="h-6 w-6 p-0">
                ×
              </Button>
            </div>
            <div className="max-h-48 overflow-y-auto p-2 space-y-1">
              {executionLogs.map((log) => (
                <div
                  key={log.id}
                  className={`text-xs p-2 rounded flex items-center gap-2 ${
                    log.status === "running"
                      ? "bg-blue-50 text-blue-700"
                      : log.status === "success"
                        ? "bg-green-50 text-green-700"
                        : "bg-red-50 text-red-700"
                  }`}
                >
                  <div
                    className={`w-2 h-2 rounded-full ${
                      log.status === "running"
                        ? "bg-blue-500 animate-pulse"
                        : log.status === "success"
                          ? "bg-green-500"
                          : "bg-red-500"
                    }`}
                  />
                  <span className="flex-1">{log.message}</span>
                  <span className="text-gray-500">{log.timestamp.toLocaleTimeString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      
      
      {/* Execution Summary Panel */}
      {executionLogs.length > 0 && !isExecuting && showExecutionSummary &&(
        <div className="w-70 ml-auto max-h-64 bg-white border rounded-lg shadow-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b flex items-center justify-between">
            <h3 className="font-semibold text-sm">Сводка выполнения</h3>
          <Button variant="ghost" size="sm" onClick={() => setShowExecutionSummary(false)} className="h-6 w-6 p-0">
          ×
          </Button>
          </div>
          <div className="p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm">Всего нод:</span>
              <Badge>{nodes.length}</Badge>
            </div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm">Выполнено:</span>
              <Badge variant="outline" className="bg-green-50 text-green-700">
                {Object.keys(executionResults).length}
              </Badge>
            </div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm">Ошибки:</span>
              <Badge variant="outline" className="bg-red-50 text-red-700">
                {executionLogs.filter(log => log.status === "error" && log.nodeId !== "system").length}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Время выполнения:</span>
              <span className="text-xs">
                {executionLogs.length > 0 ? 
                  (() => {
                    const timestamps = executionLogs.map(log => log.timestamp.getTime());
                    if (timestamps.length < 2) return "N/A";
                    const start = Math.min(...timestamps);
                    const end = Math.max(...timestamps);
                    return `${((end - start) / 1000).toFixed(1)} сек`;
                  })() : "N/A"
                }
              </span>
            </div>
            <div className="flex items-center justify-between">

              <Button 
                className="w-full mt-3"
                variant="outline"
                onClick={() => setWorkflowResultModalOpen(true)}
              >
                {/* <GitBranch className="w-4 h-4 mr-2" /> */}
                Посмотреть полные результаты
              </Button>
            </div>
          </div>
        </div>
      )} 
      </div>
      {/* Results Modal */}
      {selectedResult && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-3/4 max-w-3xl max-h-[80vh] overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
              <h3 className="font-semibold">
                Результаты выполнения: {nodes.find(n => n.id === selectedResult.nodeId)?.data.label}
              </h3>
              <Button variant="ghost" size="sm" onClick={() => setSelectedResult(null)}>×</Button>
            </div>
            <div className="p-4 overflow-y-auto max-h-[calc(80vh-60px)]">
              {selectedResult.data.output?.text ? (
                <div className="mb-4">
                  <h4 className="font-medium mb-2">Текстовый результат:</h4>
                  <div className="bg-gray-50 p-3 rounded border whitespace-pre-wrap">
                    {selectedResult.data.output.text}
                  </div>
                </div>
              ) : null}
              
              <h4 className="font-medium mb-2">Полные данные:</h4>
              <pre className="bg-gray-50 p-3 rounded border overflow-x-auto text-xs">
                {JSON.stringify(selectedResult.data, null, 2)}
              </pre>
            </div>
          </div>
        </div>

      )}
      {isWorkflowResultModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-3/4 max-w-4xl max-h-[80vh] flex flex-col">
            <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between shrink-0">
              <h3 className="font-semibold">
                Полные результаты выполнения Workflow
              </h3>
              <Button variant="ghost" size="sm" onClick={() => setWorkflowResultModalOpen(false)}>×</Button>
            </div>
            <div className="p-4 overflow-y-auto">
              <p className="text-sm text-gray-600 mb-2">
                Это полный объект с результатами всех выполненных нод. Его можно использовать для составления шаблонов в следующих нодах.
              </p>
              <pre className="bg-gray-50 p-3 rounded border overflow-x-auto text-xs">
                {JSON.stringify(executionResults, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
