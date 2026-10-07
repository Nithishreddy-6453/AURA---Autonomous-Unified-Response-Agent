"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "../components/Header";
import { HumanApprovalPanel } from "../components/HumanApprovalPanel";
import { LiveActivityTimeline } from "../components/LiveActivityTimeline";
import { TaskDetailTabs } from "../components/TaskDetailTabs";
import { TaskHistory } from "../components/TaskHistory";
import { TaskInput } from "../components/TaskInput";
import { TaskStatusCard } from "../components/TaskStatusCard";
import {
  approveTask,
  checkHealth,
  createTask,
  getTask,
  getTaskEvents,
  listTasks,
  rejectTask,
} from "../lib/api";
import { TaskDetail, TaskEvent, TaskSummary } from "../types";

export default function ControlCenterPage() {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [isPolling, setIsPolling] = useState<boolean>(false);
  const [isProcessingApproval, setIsProcessingApproval] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Health check polling
  useEffect(() => {
    const testConnection = async () => {
      const ok = await checkHealth();
      setIsConnected(ok);
    };
    testConnection();
    const interval = setInterval(testConnection, 10000);
    return () => clearInterval(interval);
  }, []);

  // Fetch recent tasks from SQLite MemoryStore
  const refreshTasksList = useCallback(async () => {
    try {
      const list = await listTasks(20);
      setRecentTasks(list);
      setErrorMessage(null);
    } catch (err: any) {
      // Don't overwrite error if already set
    }
  }, []);

  useEffect(() => {
    refreshTasksList();
  }, [refreshTasksList]);

  // Load single task data & events
  const loadTaskData = useCallback(
    async (taskId: string) => {
      try {
        setIsPolling(true);
        const [taskDetail, taskEvents] = await Promise.all([
          getTask(taskId),
          getTaskEvents(taskId, 60),
        ]);
        setActiveTask(taskDetail);
        setEvents(taskEvents);
        setErrorMessage(null);
        return taskDetail;
      } catch (err: any) {
        setErrorMessage(err.message || "Failed to load task details");
        return null;
      } finally {
        setIsPolling(false);
      }
    },
    []
  );

  // Set up polling loop when activeTaskId changes
  useEffect(() => {
    if (!activeTaskId) return;

    loadTaskData(activeTaskId);

    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    const interval = setInterval(async () => {
      const detail = await loadTaskData(activeTaskId);
      if (detail) {
        refreshTasksList();
        // Stop high-frequency polling on terminal or waiting states
        if (
          detail.state === "COMPLETED" ||
          detail.state === "FAILED" ||
          detail.state === "WAITING_FOR_HUMAN" ||
          detail.state === "NEEDS_HUMAN"
        ) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
        }
      }
    }, 2000);

    pollIntervalRef.current = interval;

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [activeTaskId, loadTaskData, refreshTasksList]);

  // Handle task submission
  const handleRunTask = async (goal: string) => {
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const created = await createTask(goal);
      setActiveTaskId(created.task_id);
      await refreshTasksList();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to launch task");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle human approval
  const handleApprove = async (feedback?: string) => {
    if (!activeTaskId) return;
    setIsProcessingApproval(true);
    setErrorMessage(null);
    try {
      await approveTask(activeTaskId, feedback);
      // Resume polling
      await loadTaskData(activeTaskId);
      await refreshTasksList();

      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(async () => {
        const detail = await loadTaskData(activeTaskId);
        if (
          detail &&
          (detail.state === "COMPLETED" ||
            detail.state === "FAILED" ||
            detail.state === "WAITING_FOR_HUMAN" ||
            detail.state === "NEEDS_HUMAN")
        ) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
        }
      }, 2000);
    } catch (err: any) {
      setErrorMessage(err.message || "Approval failed");
    } finally {
      setIsProcessingApproval(false);
    }
  };

  // Handle human rejection
  const handleReject = async (reason?: string) => {
    if (!activeTaskId) return;
    setIsProcessingApproval(true);
    setErrorMessage(null);
    try {
      await rejectTask(activeTaskId, reason);
      await loadTaskData(activeTaskId);
      await refreshTasksList();
    } catch (err: any) {
      setErrorMessage(err.message || "Rejection failed");
    } finally {
      setIsProcessingApproval(false);
    }
  };

  const isWaitingForHuman =
    activeTask?.state === "WAITING_FOR_HUMAN" ||
    activeTask?.state === "NEEDS_HUMAN";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header isConnected={isConnected} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {errorMessage && (
          <div className="bg-rose-950/80 border border-rose-800 text-rose-200 text-xs px-4 py-3 rounded-md flex items-center justify-between">
            <span>{errorMessage}</span>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-400 hover:text-rose-100 font-mono text-sm ml-4 cursor-pointer"
            >
              ✕
            </button>
          </div>
        )}

        {/* Task Input Section */}
        <TaskInput
          onSubmit={handleRunTask}
          isLoading={isSubmitting}
          disabled={!isConnected}
        />

        {/* Human Approval Required Banner */}
        {isWaitingForHuman && activeTask && (
          <HumanApprovalPanel
            task={activeTask}
            onApprove={handleApprove}
            onReject={handleReject}
            isProcessing={isProcessingApproval}
          />
        )}

        {/* Operational Dashboard Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main 2-column pane */}
          <div className="lg:col-span-2 space-y-6">
            <TaskStatusCard task={activeTask} />
            <LiveActivityTimeline events={events} isLoading={isPolling} />
            {activeTask && <TaskDetailTabs task={activeTask} />}
          </div>

          {/* Right sidebar: Recent Tasks */}
          <div className="space-y-6">
            <TaskHistory
              tasks={recentTasks}
              activeTaskId={activeTaskId}
              onSelectTask={(id) => setActiveTaskId(id)}
              onRefresh={refreshTasksList}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
