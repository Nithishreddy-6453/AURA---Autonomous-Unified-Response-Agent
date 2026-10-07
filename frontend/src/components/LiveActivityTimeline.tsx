import React from "react";
import { TaskEvent } from "../types";

interface LiveActivityTimelineProps {
  events: TaskEvent[];
  isLoading: boolean;
}

export const LiveActivityTimeline: React.FC<LiveActivityTimelineProps> = ({ events, isLoading }) => {
  const getBadgeStyle = (eventType: string) => {
    switch (eventType) {
      case "STATE_CHANGE":
      case "STATE_CURRENT":
        return "bg-blue-950/70 text-blue-300 border-blue-800";
      case "ACTION_STARTED":
      case "ACTION":
        return "bg-sky-950/70 text-sky-300 border-sky-800";
      case "ACTION_SUCCESS":
      case "OBSERVATION":
        return "bg-emerald-950/70 text-emerald-300 border-emerald-800";
      case "ACTION_FAILURE":
        return "bg-rose-950/70 text-rose-300 border-rose-800";
      case "POLICY":
        return "bg-indigo-950/70 text-indigo-300 border-indigo-800";
      case "RECOVERY":
        return "bg-cyan-950/70 text-cyan-300 border-cyan-800";
      case "APPROVAL_GRANTED":
      case "APPROVAL_REJECTED":
        return "bg-amber-950/70 text-amber-300 border-amber-800";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2">
          <h3 className="text-sm font-semibold text-slate-200">Live Activity Timeline</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            {events.length} events
          </span>
        </div>
        {isLoading && (
          <span className="text-xs font-mono text-slate-400 flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />
            <span>Polling...</span>
          </span>
        )}
      </div>

      {events.length === 0 ? (
        <div className="py-8 text-center text-slate-500 text-xs">
          No operational events recorded yet.
        </div>
      ) : (
        <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
          {events.map((evt, idx) => {
            const timeStr = evt.timestamp
              ? new Date(evt.timestamp).toLocaleTimeString()
              : "";
            return (
              <div
                key={`${evt.timestamp}-${idx}`}
                className="flex items-start space-x-3 text-xs bg-slate-950/40 p-2.5 rounded border border-slate-800/60"
              >
                <span className="text-slate-500 font-mono shrink-0 pt-0.5 w-16">{timeStr}</span>
                <span
                  className={`px-2 py-0.5 rounded text-[11px] font-mono border uppercase shrink-0 ${getBadgeStyle(
                    evt.event_type
                  )}`}
                >
                  {evt.event_type}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-slate-200 font-medium break-words">{evt.message}</p>
                  {evt.details && Object.keys(evt.details).length > 0 && (
                    <details className="mt-1">
                      <summary className="text-[11px] text-slate-500 hover:text-slate-400 cursor-pointer select-none">
                        View details
                      </summary>
                      <pre className="mt-1 p-2 rounded bg-slate-950 text-[11px] text-slate-400 font-mono overflow-x-auto border border-slate-800">
                        {JSON.stringify(evt.details, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
