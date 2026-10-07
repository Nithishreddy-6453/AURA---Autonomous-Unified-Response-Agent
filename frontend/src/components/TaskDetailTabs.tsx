import React, { useState } from "react";
import { TaskDetail } from "../types";

interface TaskDetailTabsProps {
  task: TaskDetail;
}

export const TaskDetailTabs: React.FC<TaskDetailTabsProps> = ({ task }) => {
  const [activeTab, setActiveTab] = useState<
    "actions" | "observations" | "policy" | "recovery" | "metadata"
  >("actions");

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center space-x-1 border-b border-slate-800 pb-2 overflow-x-auto">
        <button
          onClick={() => setActiveTab("actions")}
          className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
            activeTab === "actions"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Actions ({task.actions.length})
        </button>
        <button
          onClick={() => setActiveTab("observations")}
          className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
            activeTab === "observations"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Observations ({task.observations.length})
        </button>
        <button
          onClick={() => setActiveTab("policy")}
          className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
            activeTab === "policy"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Policy Events ({task.policy_events.length})
        </button>
        <button
          onClick={() => setActiveTab("recovery")}
          className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
            activeTab === "recovery"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Recovery Events ({task.recovery_events.length})
        </button>
        <button
          onClick={() => setActiveTab("metadata")}
          className={`px-3 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
            activeTab === "metadata"
              ? "bg-blue-600 text-white"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          Verification / Context
        </button>
      </div>

      <div className="min-h-48 max-h-80 overflow-y-auto pr-1">
        {activeTab === "actions" && (
          <div className="space-y-2">
            {task.actions.length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">No actions executed yet.</p>
            ) : (
              task.actions.map((act, idx) => (
                <div
                  key={`${act.action_id}-${idx}`}
                  className="p-3 bg-slate-950/60 rounded border border-slate-800 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-semibold text-sky-300">{act.tool_name}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                      {act.status}
                    </span>
                  </div>
                  {act.arguments && Object.keys(act.arguments).length > 0 && (
                    <details className="mt-1">
                      <summary className="text-[11px] text-slate-400 cursor-pointer">Arguments</summary>
                      <pre className="mt-1 p-2 rounded bg-slate-950 text-[11px] text-slate-300 font-mono overflow-x-auto border border-slate-800">
                        {JSON.stringify(act.arguments, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "observations" && (
          <div className="space-y-2">
            {task.observations.length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">No observations recorded yet.</p>
            ) : (
              task.observations.map((obs, idx) => (
                <div
                  key={`${obs.action_id}-${idx}`}
                  className="p-3 bg-slate-950/60 rounded border border-slate-800 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-slate-400">Action: {obs.action_id}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono border ${
                        obs.success
                          ? "bg-emerald-950/80 text-emerald-300 border-emerald-800"
                          : "bg-rose-950/80 text-rose-300 border-rose-800"
                      }`}
                    >
                      {obs.success ? "SUCCESS" : "FAILURE"}
                    </span>
                  </div>
                  {obs.error && <p className="text-rose-400 text-xs mt-1">{obs.error}</p>}
                  {obs.result && (
                    <details className="mt-1">
                      <summary className="text-[11px] text-slate-400 cursor-pointer">Result data</summary>
                      <pre className="mt-1 p-2 rounded bg-slate-950 text-[11px] text-slate-300 font-mono overflow-x-auto border border-slate-800">
                        {JSON.stringify(obs.result, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "policy" && (
          <div className="space-y-2">
            {task.policy_events.length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">No policy events recorded.</p>
            ) : (
              task.policy_events.map((pol, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-slate-950/60 rounded border border-slate-800 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-indigo-300 font-medium">
                      {pol.type || "POLICY_DECISION"}
                    </span>
                    {pol.risk_level && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                        {pol.risk_level}
                      </span>
                    )}
                  </div>
                  {pol.reason && <p className="text-slate-300 text-xs">{pol.reason}</p>}
                  <details className="mt-1">
                    <summary className="text-[11px] text-slate-400 cursor-pointer">Event JSON</summary>
                    <pre className="mt-1 p-2 rounded bg-slate-950 text-[11px] text-slate-400 font-mono overflow-x-auto border border-slate-800">
                      {JSON.stringify(pol, null, 2)}
                    </pre>
                  </details>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "recovery" && (
          <div className="space-y-2">
            {task.recovery_events.length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">No recovery events recorded.</p>
            ) : (
              task.recovery_events.map((rec, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-slate-950/60 rounded border border-slate-800 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-cyan-300 font-medium">
                      Policy: {rec.policy || "UNKNOWN"}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">{rec.source}</span>
                  </div>
                  {rec.details && <p className="text-slate-300 text-xs">{rec.details}</p>}
                  {rec.error && <p className="text-rose-400 text-xs">{rec.error}</p>}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "metadata" && (
          <div className="space-y-3 text-xs">
            {task.metadata.human_intervention_reason && (
              <div className="p-3 bg-amber-950/30 border border-amber-800/60 rounded">
                <span className="text-amber-300 font-mono block font-semibold mb-1">
                  Human Intervention Context
                </span>
                <p className="text-slate-200">{task.metadata.human_intervention_reason}</p>
              </div>
            )}
            {task.metadata.approval_status && (
              <div className="p-3 bg-slate-950 border border-slate-800 rounded">
                <span className="text-slate-400 font-mono block font-semibold mb-1">
                  Approval Status
                </span>
                <p className="text-slate-200 font-mono">
                  {task.metadata.approval_status}
                  {task.metadata.approval_feedback && ` — ${task.metadata.approval_feedback}`}
                </p>
              </div>
            )}
            {task.metadata.completion_summary && (
              <div className="p-3 bg-emerald-950/30 border border-emerald-800/60 rounded">
                <span className="text-emerald-300 font-mono block font-semibold mb-1">
                  Completion Summary
                </span>
                <p className="text-slate-200">{task.metadata.completion_summary}</p>
              </div>
            )}
            <details className="mt-2">
              <summary className="text-[11px] text-slate-400 cursor-pointer">
                Full Task Metadata JSON
              </summary>
              <pre className="mt-1 p-2 rounded bg-slate-950 text-[11px] text-slate-400 font-mono overflow-x-auto border border-slate-800">
                {JSON.stringify(task.metadata, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
};
