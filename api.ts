// Определим типы для наших данных, чтобы TypeScript нам помогал
export interface NodeData {
    id: string;
    type: string;
    position: { x: number; y: number };
    data: {
      label?: string;
      config?: any;
    };
    width?: number | null;
    height?: number | null;
  }
  
  export interface ConnectionData {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
    data?: { label?: string };
  }
  
  export interface Workflow {
    name: string;
    nodes: NodeData[];
    connections: ConnectionData[];
    status?: 'draft' | 'published';
  }
  
  export interface WorkflowListItem {
    id: string;
    name: string;
  }
  // Определим тип для данных, которые мы отправляем
  interface WorkflowExecutePayload {
    nodes: NodeData[]; // Замените any на более конкретный тип Node, если он у вас есть
    connections: ConnectionData[]; // Замените any на тип Connection
    startNodeId?: string;
  }
  const API_BASE_URL = "http://localhost:8000/api/v1"; // Убедитесь, что порт верный
  
  // Получить список всех workflows
  export const listWorkflows = async (): Promise<WorkflowListItem[]> => {
    const response = await fetch(`${API_BASE_URL}/workflows`);
    if (!response.ok) {
      throw new Error("Failed to fetch workflows");
    }
    const data = await response.json();
    return data.workflows;
  };
  
  // Загрузить конкретный workflow
  export const getWorkflow = async (id: string): Promise<Workflow> => {
    const response = await fetch(`${API_BASE_URL}/workflows/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch workflow ${id}`);
    }
    return response.json();
  };
  
  // Создать новый workflow
  export const createWorkflow = async (name: string, data: Omit<Workflow, 'name'>): Promise<{ workflow_id: string }> => {
    const response = await fetch(`${API_BASE_URL}/workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, name }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Failed to create workflow");
    }
    return response.json();
  };
  
  // Обновить существующий workflow
  export const updateWorkflow = async (id: string, data: Omit<Workflow, 'name'>): Promise<void> => {
      const response = await fetch(`${API_BASE_URL}/workflows/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
      });
      if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'Failed to update workflow');
      }
  };
  
  // Выполнить workflow
  export const executeWorkflow = async (payload: WorkflowExecutePayload) => {
    console.log("[API] Вызов executeWorkflow с данными:", payload);
    try {
      const response = await fetch(`${API_BASE_URL}/execute-workflow`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        // Если сервер вернул ошибку, пытаемся прочитать ее текст
        const errorText = await response.text();
        console.error(`[API] Ошибка выполнения workflow. Статус: ${response.status}. Ответ: ${errorText}`);
        throw new Error(`Ошибка сервера: ${errorText || response.statusText}`);
      }

      console.log("[API] executeWorkflow выполнен успешно.");
      return await response.json();
    } catch (error) {
      console.error("[API] Критическая ошибка в executeWorkflow:", error);
      // Перебрасываем ошибку дальше, чтобы ее поймал вызывающий код
      throw error;
    }
  };
  // Удалить workflow
  export const deleteWorkflow = async (id: string): Promise<void> => {
    const response = await fetch(`${API_BASE_URL}/workflows/${id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(`Failed to delete workflow ${id}`);
    }
  };

  // ... (другие ваши импорты и функции)

// НОВОЕ: Тип для данных ноды, если он еще не определен глобально
// interface Node {
//   id: string;
//   type: string;
//   position: { x: number; y: number };
//   data: {
//     label: string;
//     config: Record<string, any>;
//   };
// }

// НОВОЕ: Функция для вызова эндпоинта настройки таймера
export const setupTimer = async (node: NodeData, workflow_id: string): Promise<any> => {
  const response = await fetch(`${API_BASE_URL}/setup-timer`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ node, workflow_id }),
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || 'Failed to set up timer');
  }

  return response.json();
};
// --- НОВЫЕ ФУНКЦИИ ДЛЯ ПУБЛИКАЦИИ ---
 
 // Опубликовать воркфлоу
 export const publishWorkflow = async (id: string) => {
     const response = await fetch(`${API_BASE_URL}/workflows/${id}/publish`, {
         method: 'POST',
     });
     if (!response.ok) {
         const error = await response.json();
         throw new Error(error.detail || "Failed to publish workflow");
     }
     return response.json();
 };
 
 // Снять воркфлоу с публикации
 export const unpublishWorkflow = async (id: string) => {
     const response = await fetch(`${API_BASE_URL}/workflows/${id}/unpublish`, {
         method: 'POST',
     });
     if (!response.ok) {
         const error = await response.json();
         throw new Error(error.detail || "Failed to unpublish workflow");
     }
     return response.json();
 };
  