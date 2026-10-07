import React, { useState } from "react";
import { TaskDetail } from "../types";

interface HumanApprovalPanelProps {
  task: TaskDetail;
  onApprove: (feedback?: string) => Promise<void>;
  onReject: (reason?: string) => Promise<void>;
  isProcessing: boolean;
}

export const HumanApprovalPanel: React.FC<HumanApprovalPanelProps> = ({
  task,
  onApprove,
  onReject,
  isProcessing,
}) => {
  const [feedback, setFeedback] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectInput, setShowRejectInput] = useState(false);

  const pendingAction = task.metadata?.pending_action || {};
  const toolName = pendingAction.tool_name || task.metadata?.pending_tool_name || "sensitive_operation";
  const reason =
    task.metadata?.human_intervention_reason ||
    "This operation requires human authorization before execution.";
  const risk = "SENSITIVE";

  const handleApprove = async () => {
    await onApprove(feedback || undefined);
  };

  const handleReject = async () => {
    await onReject(rejectReason || undefined);
  };

  return (
    <div className="bg-amber-950/40 border-2 border-amber-500/80 rounded-lg p-5 shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="w-3 h-3 rounded-full bg-amber-500 animate-ping inline-block" />
          <h3 className="text-base font-bold text-amber-300 tracking-wider font-mono uppercase">
            Human Approval Required
          </h3>
        </div>
        <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
          POLICY GATE
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-slate-950/60 rounded-md p-3 border border-amber-900/50 text-xs font-mono">
        <div>
          <span className="text-slate-400 block mb-1">Action</span>
          <span className="text-amber-200 font-semibold">{toolName}</span>
        </div>
        <div>
          <span className="text-slate-400 block mb-1">Risk</span>
          <span className="text-rose-300 font-semibold">{risk}</span>
        </div>
        <div>
          <span className="text-slate-400 block mb-1">Reason</span>
          <span className="text-slate-200">{reason}</span>
        </div>
      </div>

      {pendingAction.arguments && (
        <div className="bg-slate-950/80 rounded p-3 border border-slate-800 text-xs font-mono overflow-x-auto">
          <span className="text-slate-400 block mb-1">Proposed Arguments:</span>
          <pre className="text-slate-300">
            {JSON.stringify(pendingAction.arguments, null, 2)}
          </pre>
        </div>
      )}

      {showRejectInput ? (
        <div className="space-y-2">
          <input
            type="text"
            placeholder="Reason for rejection (optional)..."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            disabled={isProcessing}
            className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-rose-500 font-mono"
          />
          <div className="flex justify-end space-x-2">
            <button
              type="button"
              onClick={() => setShowRejectInput(false)}
              disabled={isProcessing}
              className="px-3 py-1.5 rounded text-xs text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleReject}
              disabled={isProcessing}
              className="px-4 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium cursor-pointer"
            >
              Confirm Rejection
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-2">
          <input
            type="text"
            placeholder="Operator approval notes (optional)..."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={isProcessing}
            className="flex-1 bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 font-mono"
          />
          <div className="flex items-center space-x-3">
            <button
              type="button"
              onClick={() => setShowRejectInput(true)}
              disabled={isProcessing}
              className="px-4 py-2 rounded-md bg-rose-950/80 hover:bg-rose-900 text-rose-300 border border-rose-800 text-xs font-medium transition-colors cursor-pointer"
            >
              Reject
            </button>
            <button
              type="button"
              onClick={handleApprove}
              disabled={isProcessing}
              className="px-5 py-2 rounded-md bg-amber-600 hover:bg-amber-500 text-slate-950 text-xs font-bold transition-colors cursor-pointer shadow-md flex items-center space-x-1"
            >
              {isProcessing ? (
                <span>Resuming Task...</span>
              ) : (
                <span>Approve &amp; Continue</span>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
