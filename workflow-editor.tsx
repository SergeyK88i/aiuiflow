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

const API_BASE_URL = "http://localhost:8000"

const nodeTypes = [
  { type: "gigachat", label: "GigaChat AI", icon: MessageSquare, color: "bg-orange-500", canStart: true },
  { type: "webhook", label: "Webhook Trigger", icon: Webhook, color: "bg-green-500", canStart: true },
  { type: "timer", label: "Timer Trigger", icon: Timer, color: "bg-blue-500", canStart: true },
  { type: "email", label: "Send Email", icon: Mail, color: "bg-red-500", canStart: false },
  { type: "database", label: "Database Query", icon: Database, color: "bg-purple-500", canStart: false },
]
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
  const [connections, setConnections] = useState<Connection[]>([])
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [draggedNode, setDraggedNode] = useState<Node | null>(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const [connecting, setConnecting] = useState<string | null>(null)
  const [workflowName, setWorkflowName] = useState("GigaChat Workflow")
  const canvasRef = useRef<HTMLDivElement>(null)

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
          "MTZhNzNmMTktNjg3YS00NGRiLWE3NjItYjU3NjgzY2I0ZDlhOjZiZjlhMjBiLTQ0NDktNDZiYS1iMDJhLTdjNmI1ZTM3YzBkYQ==",
        systemMessage: "Ты полезный ассистент, который отвечает кратко и по делу.",
        userMessage: "Привет! Расскажи что-нибудь интересное о программировании.",
        clearHistory: false,
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
      const newConnection: Connection = {
        id: `conn-${Date.now()}`,
        source: connecting,
        target: targetNodeId,
      }
      setConnections((prev) => [...prev, newConnection])
    }
    setConnecting(null)
  }

  const getNodeTypeInfo = (type: string) => {
    return nodeTypes.find((nt) => nt.type === type) || nodeTypes[0]
  }

  const renderConnection = (connection: Connection) => {
    const sourceNode = nodes.find((n) => n.id === connection.source)
    const targetNode = nodes.find((n) => n.id === connection.target)

    if (!sourceNode || !targetNode) return null

    const startX = sourceNode.position.x + 150
    const startY = sourceNode.position.y + 40
    const endX = targetNode.position.x
    const endY = targetNode.position.y + 40

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
    return (
      <path
        key={connection.id}
        d={`M ${startX} ${startY} C ${midX} ${startY} ${midX} ${endY} ${endX} ${endY}`}
        stroke="#6366f1"
        strokeWidth="2"
        fill="none"
        markerEnd="url(#arrowhead)"
      />
    )
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
          connections: connections,
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
    if (apiStatus === "offline") {
      alert("API сервер недоступен. Запустите FastAPI сервер на порту 8000.")
      return
    }
    // Сначала сохраняем workflow
    await saveWorkflow();

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
          connections: connections,
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
        await saveWorkflow();
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

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Input
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
            className="text-lg font-semibold border-none shadow-none p-0 h-auto"
          />
          <Badge variant="secondary">{nodes.length} nodes</Badge>
          <Badge variant={apiStatus === "online" ? "default" : "destructive"}>
            API: {apiStatus === "checking" ? "..." : apiStatus}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={checkApiStatus}>
            <ExternalLink className="w-4 h-4 mr-2" />
            Check API
          </Button>
          <Button variant="outline" size="sm" onClick={saveWorkflow} disabled={nodes.length === 0 || apiStatus === "offline"}>
            <Save className="w-4 h-4 mr-2" />
            Save
          </Button>
          {isExecuting ? (
            <Button onClick={stopExecution} size="sm" variant="destructive">
              <Square className="w-4 h-4 mr-2" />
              Stop
            </Button>
          ) : (
            <Button
              onClick={() => executeWorkflow()}
              size="sm"
              disabled={nodes.length === 0 || apiStatus === "offline"}
            >
              <Play className="w-4 h-4 mr-2" />
              Execute
            </Button>
          )}
        </div>
      </div>

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

                  {selectedNode.type === "webhook" && (
                    <>
                      <div>
                        <Label htmlFor="url">Webhook URL</Label>
                        <Input
                          id="url"
                          placeholder="https://api.example.com/webhook"
                          value={selectedNode.data.config.url || ""}
                          onChange={(e) => updateNodeConfig("url", e.target.value)}
                        />
                      </div>
                      <div>
                        <Label htmlFor="method">Method</Label>
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
                            <SelectItem value="DELETE">DELETE</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label htmlFor="headers">Headers</Label>
                        <Textarea
                          id="headers"
                          placeholder="Content-Type: application/json"
                          value={selectedNode.data.config.headers || ""}
                          onChange={(e) => updateNodeConfig("headers", e.target.value)}
                        />
                      </div>
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
                </CardContent>
              </Card>
            </div>
          )}
        </div>

        {/* Canvas */}
        <div className="flex-1 relative overflow-hidden">
          <div
            ref={canvasRef}
            className="w-full h-full relative bg-gray-50"
            style={{
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
                        {nodeTypeInfo.canStart && (
                          <Button
                            variant="secondary"
                            size="sm"
                            className="h-6 text-xs"
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

    </div>
  )
}
