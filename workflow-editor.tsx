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

const API_BASE_URL = "http://localhost:8000"

const nodeTypes = [
  { type: "gigachat", label: "GigaChat AI", icon: MessageSquare, color: "bg-orange-500", canStart: true },
  { type: "webhook", label: "Webhook Trigger", icon: Webhook, color: "bg-green-500", canStart: true },
  { type: "timer", label: "Timer Trigger", icon: Timer, color: "bg-blue-500", canStart: true },
  { type: "email", label: "Send Email", icon: Mail, color: "bg-red-500", canStart: false },
  { type: "database", label: "Database Query", icon: Database, color: "bg-purple-500", canStart: false },
]

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

  // Проверка статуса API при загрузке
  useEffect(() => {
    console.log("🚀 Компонент загружен, проверяем API...")
    checkApiStatus()
  }, [])

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
        authToken:
          "MmMzZDA5OGMtODIyNS00MGJlLWJhOGItMzRhOTgyY2M0YjBhOjk3NGQ0ZTA3LWQ3MDUtNDhhNC1iYjFlLTQ0N2Y2ZmJkMWM4Mg==",
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

  const executeWorkflow = async (startNodeId?: string) => {
    if (nodes.length === 0) return
    if (apiStatus === "offline") {
      alert("API сервер недоступен. Запустите FastAPI сервер на порту 8000.")
      return
    }

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
            }
          },
          input_data: null
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
          {/*apiStatus === "offline" && (
            <Button variant="outline" size="sm" onClick={() => setApiStatus("online")} className="text-orange-600">
              Force Online
            </Button>
          )*/}
          <Button variant="outline" size="sm">
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
              http://localhost:8000/health
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
                        />
                        <p className="text-xs text-gray-500 mt-1">Системное сообщение для настройки поведения AI</p>
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
                        <p className="text-xs text-gray-500 mt-1">Сообщение пользователя для отправки в GigaChat</p>
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
                  className={`absolute cursor-move select-none ${selectedNode?.id === node.id ? "ring-2 ring-blue-500" : ""} ${activeNode === node.id ? "ring-2 ring-green-500 animate-pulse" : ""} ${executionResults[node.id] ? "ring-1 ring-green-300" : ""}`}
                  style={{
                    left: node.position.x,
                    top: node.position.y,
                    transform: draggedNode?.id === node.id ? "scale(1.05)" : "scale(1)",
                    transition: draggedNode?.id === node.id ? "none" : "transform 0.1s",
                  }}
                  onMouseDown={(e) => handleMouseDown(e, node)}
                  onClick={() => setSelectedNode(node)}
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
      {executionLogs.length > 0 && (
        <div className="absolute bottom-4 right-4 w-96 max-h-64 bg-white border rounded-lg shadow-lg overflow-hidden">
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
    </div>
  )
}
