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
  }
  
  export interface WorkflowListItem {
    id: string;
    name: string;
  }

export interface TimerData {
    id: string;
    node_id: string;
    interval: number;
    next_execution: string;
    status: "active" | "paused" | "error";
}
