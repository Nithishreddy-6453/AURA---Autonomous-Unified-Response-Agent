import { TaskDetail, TaskEvent, TaskSummary } from "../types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function createTask(user_goal: string, domain?: string): Promise<TaskSummary> {
  const res = await fetch(`${API_BASE}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_goal, domain: domain || "finance" }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to create task (${res.status})`);
  }
  return res.json();
}


export async function listTasks(limit = 20): Promise<TaskSummary[]> {
  const res = await fetch(`${API_BASE}/api/tasks?limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch tasks (${res.status})`);
  }
  return res.json();
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch task ${taskId} (${res.status})`);
  }
  return res.json();
}

export async function getTaskEvents(taskId: string, limit = 50): Promise<TaskEvent[]> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/events?limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch events for task ${taskId} (${res.status})`);
  }
  return res.json();
}

export async function approveTask(taskId: string, feedback?: string): Promise<TaskSummary> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to approve task (${res.status})`);
  }
  return res.json();
}

export async function rejectTask(taskId: string, reason?: string): Promise<TaskSummary> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to reject task (${res.status})`);
  }
  return res.json();
}

export async function resumeTask(taskId: string): Promise<TaskSummary> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/resume`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to resume task (${res.status})`);
  }
  return res.json();
}
