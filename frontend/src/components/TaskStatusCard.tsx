import React, { useMemo } from "react";
import { AgentState, TaskDetail, TaskSummary } from "../types";

interface TaskStatusCardProps {
  task: TaskDetail | TaskSummary | null;
}

export const TaskStatusCard: React.FC<TaskStatusCardProps> = ({ task }) => {
  if (!task) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 text-center text-slate-500">
        <p className="text-sm">No task currently selected. Run a new task or pick one from history.</p>
      </div>
    );
  }

  const stateColor = useMemo(() => {
    switch (task.state) {
      case "COMPLETED":
        return "bg-emerald-950/60 text-emerald-400 border-emerald-800";
      case "FAILED":
        return "bg-rose-950/60 text-rose-400 border-rose-800";
      case "WAITING_FOR_HUMAN":
      case "NEEDS_HUMAN":
        return "bg-amber-950/60 text-amber-400 border-amber-800 animate-pulse";
      case "EXECUTING":
        return "bg-sky-950/60 text-sky-400 border-sky-800";
      case "PLANNING":
        return "bg-indigo-950/60 text-indigo-400 border-indigo-800";
      case "VERIFYING":
        return "bg-purple-950/60 text-purple-400 border-purple-800";
      case "OBSERVING":
      case "ADAPTING":
        return "bg-cyan-950/60 text-cyan-400 border-cyan-800";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  }, [task.state]);

  const elapsedTime = useMemo(() => {
    try {
      const created = new Date(task.created_at).getTime();
      const updated = new Date(task.updated_at).getTime();
      const diffSec = Math.max(0, Math.floor((updated - created) / 1000));
      if (diffSec < 60) return `${diffSec}s`;
      const mins = Math.floor(diffSec / 60);
      const secs = diffSec % 60;
      return `${mins}m ${secs}s`;
    } catch {
      return "—";
    }
  }, [task.created_at, task.updated_at]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
        <div>
          <span className="text-xs font-mono text-slate-500 uppercase tracking-wider">Active Task</span>
          <p className="font-mono text-sm text-slate-200 select-all">{task.task_id}</p>
        </div>
        <div className="flex items-center space-x-2">
          <span
            className={`px-3 py-1 text-xs font-mono font-semibold rounded-md border ${stateColor}`}
          >
            {task.state}
          </span>
          <span className="px-2 py-0.5 text-xs font-mono rounded bg-slate-800 text-slate-400 border border-slate-700">
            {task.status}
          </span>
        </div>
      </div>

      <div>
        <span className="text-xs font-mono text-slate-500 uppercase tracking-wider">Goal</span>
        <p className="text-sm font-medium text-slate-100 mt-0.5">{task.user_goal}</p>
      </div>

      <div className="grid grid-cols-3 gap-3 pt-1 text-xs font-mono text-slate-400 border-t border-slate-800/80">
        <div>
          <span className="text-slate-500 block">Created</span>
          <span>{new Date(task.created_at).toLocaleTimeString()}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Updated</span>
          <span>{new Date(task.updated_at).toLocaleTimeString()}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Elapsed</span>
          <span>{elapsedTime}</span>
        </div>
      </div>
    </div>
  );
};
