export type AgentState =
  | "RECEIVED"
  | "UNDERSTANDING"
  | "PLANNING"
  | "EXECUTING"
  | "OBSERVING"
  | "ADAPTING"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED"
  | "WAITING_FOR_HUMAN"
  | "NEEDS_HUMAN";

export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "WAITING_FOR_HUMAN"
  | "NEEDS_HUMAN";

export interface TaskSummary {
  task_id: string;
  user_goal: string;
  status: TaskStatus;
  state: AgentState;
  created_at: string;
  updated_at: string;
}

export interface TaskEvent {
  task_id: string;
  event_type: string;
  message: string;
  timestamp: string;
  details: Record<string, any>;
}

export interface ActionRecord {
  action_id: string;
  tool_name: string;
  arguments: Record<string, any>;
  status: string;
  retry_count: number;
}

export interface ObservationRecord {
  action_id: string;
  success: boolean;
  result?: any;
  error?: string | null;
  metadata?: Record<string, any>;
}

export interface TaskDetail {
  task_id: string;
  user_goal: string;
  status: TaskStatus;
  state: AgentState;
  created_at: string;
  updated_at: string;
  metadata: Record<string, any>;
  actions: ActionRecord[];
  observations: ObservationRecord[];
  recovery_events: Record<string, any>[];
  policy_events: Record<string, any>[];
  plan?: Record<string, any> | null;
}
