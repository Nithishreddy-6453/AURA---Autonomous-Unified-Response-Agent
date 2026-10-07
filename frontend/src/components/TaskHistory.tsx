import React from "react";
import { TaskSummary } from "../types";

interface TaskHistoryProps {
  tasks: TaskSummary[];
  activeTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  onRefresh: () => void;
}

export const TaskHistory: React.FC<TaskHistoryProps> = ({
  tasks,
  activeTaskId,
  onSelectTask,
  onRefresh,
}) => {
  const getBadgeStyle = (state: string) => {
    switch (state) {
      case "COMPLETED":
        return "bg-emerald-950/60 text-emerald-400 border-emerald-800";
      case "FAILED":
        return "bg-rose-950/60 text-rose-400 border-rose-800";
      case "WAITING_FOR_HUMAN":
      case "NEEDS_HUMAN":
        return "bg-amber-950/60 text-amber-400 border-amber-800";
      case "EXECUTING":
        return "bg-sky-950/60 text-sky-400 border-sky-800";
      default:
        return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2">
          <h3 className="text-sm font-semibold text-slate-200">Recent Tasks</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            SQLite Store
          </span>
        </div>
        <button
          onClick={onRefresh}
          className="text-xs text-slate-400 hover:text-slate-200 transition-colors font-mono cursor-pointer"
        >
          Refresh
        </button>
      </div>

      {tasks.length === 0 ? (
        <div className="py-8 text-center text-slate-500 text-xs">
          No previous tasks found in MemoryStore.
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
          {tasks.map((task) => {
            const isActive = task.task_id === activeTaskId;
            return (
              <button
                key={task.task_id}
                onClick={() => onSelectTask(task.task_id)}
                className={`w-full text-left p-3 rounded border transition-colors cursor-pointer block ${
                  isActive
                    ? "bg-slate-800/90 border-blue-600 shadow-sm"
                    : "bg-slate-950/60 border-slate-800/80 hover:bg-slate-800/50"
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="font-mono text-xs text-slate-400 truncate max-w-[160px]">
                    {task.task_id}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono border ${getBadgeStyle(
                      task.state
                    )}`}
                  >
                    {task.state}
                  </span>
                </div>
                <p className="text-xs text-slate-200 line-clamp-2 mb-2 font-medium">
                  {task.user_goal}
                </p>
                <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                  <span>{new Date(task.created_at).toLocaleTimeString()}</span>
                  <span>{task.status}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
