import React, { useState } from "react";

interface TaskInputProps {
  onSubmit: (goal: string, domain?: string) => Promise<void>;
  isLoading: boolean;
  disabled: boolean;
}

export const TaskInput: React.FC<TaskInputProps> = ({ onSubmit, isLoading, disabled }) => {
  const [goal, setGoal] = useState("");
  const [domain, setDomain] = useState<string>("finance");

  const financeExample = "Find the latest Acme invoice and enter its amount into the Finance Portal.";
  const hrExample = "Complete the onboarding checklist for synthetic employee HR-TEST-1001 using the approved mock onboarding request. Add all required checklist items, and verify the saved onboarding state.";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim() || isLoading || disabled) return;
    await onSubmit(goal.trim(), domain);
    setGoal("");
  };

  const handleUseExample = () => {
    if (domain === "hr") {
      setGoal(hrExample);
    } else {
      setGoal(financeExample);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-sm">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Domain Selection */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Domain:</span>
            <div className="inline-flex rounded-md shadow-xs bg-slate-950 p-0.5 border border-slate-800" role="group">
              <button
                type="button"
                id="domain-select-finance"
                onClick={() => setDomain("finance")}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer ${
                  domain === "finance"
                    ? "bg-blue-600 text-white shadow-xs"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Finance
              </button>
              <button
                type="button"
                id="domain-select-hr"
                onClick={() => setDomain("hr")}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors cursor-pointer ${
                  domain === "hr"
                    ? "bg-indigo-600 text-white shadow-xs"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                HR Onboarding
              </button>
            </div>
          </div>

          <button
            type="button"
            id="insert-example-btn"
            onClick={handleUseExample}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors underline cursor-pointer"
          >
            {domain === "hr" ? "Insert HR Onboarding Example" : "Insert Acme Invoice Example"}
          </button>
        </div>

        <div>
          <label htmlFor="user-goal" className="block text-sm font-semibold text-slate-200 mb-1">
            What should I do?
          </label>
          <textarea
            id="user-goal"
            rows={3}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={
              domain === "hr"
                ? "e.g. Complete the onboarding checklist for synthetic employee HR-TEST-1001..."
                : "e.g. Find the latest Acme invoice and enter its amount into the Finance Portal."
            }
            disabled={disabled || isLoading}
            className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 font-sans resize-none"
          />
        </div>

        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-slate-400">
            AURA evaluates domain safety policies before executing tools.
          </p>
          <button
            type="submit"
            id="run-task-btn"
            disabled={!goal.trim() || isLoading || disabled}
            className="px-5 py-2 rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-sm font-medium transition-colors cursor-pointer disabled:cursor-not-allowed flex items-center space-x-2"
          >
            {isLoading ? (
              <>
                <span className="inline-block w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                <span>Starting Task...</span>
              </>
            ) : (
              <span>Run Task</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
};
