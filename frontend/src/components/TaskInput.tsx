import React, { useState } from "react";

interface TaskInputProps {
  onSubmit: (goal: string) => Promise<void>;
  isLoading: boolean;
  disabled: boolean;
}

export const TaskInput: React.FC<TaskInputProps> = ({ onSubmit, isLoading, disabled }) => {
  const [goal, setGoal] = useState("");
  const exampleGoal = "Find the latest Acme invoice and enter its amount into the Finance Portal.";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim() || isLoading || disabled) return;
    await onSubmit(goal.trim());
    setGoal("");
  };

  const handleUseExample = () => {
    setGoal(exampleGoal);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 shadow-sm">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex items-center justify-between">
          <label htmlFor="user-goal" className="block text-sm font-semibold text-slate-200">
            What should I do?
          </label>
          <button
            type="button"
            onClick={handleUseExample}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors underline cursor-pointer"
          >
            Insert Acme Invoice Example
          </button>
        </div>

        <textarea
          id="user-goal"
          rows={3}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Find the latest Acme invoice and enter its amount into the Finance Portal."
          disabled={disabled || isLoading}
          className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 font-sans resize-none"
        />

        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-slate-400">
            AURA evaluates safety policies before executing tools.
          </p>
          <button
            type="submit"
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
