"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function NewOnboardingPage() {
  const router = useRouter();
  const [employeeId, setEmployeeId] = useState("");
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [startDate, setStartDate] = useState("2026-04-01");
  const [role, setRole] = useState("");
  const [checklist, setChecklist] = useState<string[]>([
    "Security Background Check",
    "Laptop Provisioning",
    "System Access",
  ]);
  const [statusVal, setStatusVal] = useState("COMPLETED");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const toggleChecklistItem = (item: string) => {
    setChecklist((prev) =>
      prev.includes(item) ? prev.filter((i) => i !== item) : [...prev, item]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const payload = {
        employee_id: employeeId.trim(),
        name: name.trim(),
        department: department.trim(),
        start_date: startDate.trim(),
        role: role.trim() || undefined,
        checklist,
        status: statusVal,
      };

      const res = await fetch("/api/hr/onboarding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || `Failed to create onboarding record (${res.status})`);
      }

      setSuccessMessage(`Onboarding for ${employeeId} finalized and saved successfully.`);
      setTimeout(() => {
        router.push("/hr");
      }, 1500);
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-10">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Process Onboarding Request</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Complete employee details and checklist in HR Portal sandbox
          </p>
        </div>
        <Link
          href="/hr"
          className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
        >
          ← Back to Dashboard
        </Link>
      </div>

      {error && (
        <div
          id="error-banner"
          className="bg-rose-950/60 border border-rose-800 text-rose-300 text-sm rounded-md p-3 mb-6"
        >
          {error}
        </div>
      )}

      {successMessage && (
        <div
          id="success-banner"
          className="bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-sm rounded-md p-3 mb-6"
        >
          {successMessage}
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-5">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Employee ID *
          </label>
          <input
            type="text"
            name="employee_id"
            id="employee_id"
            required
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            placeholder="e.g. HR-TEST-1001 or EMP-091"
            className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Full Name *
          </label>
          <input
            type="text"
            name="name"
            id="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Alex Morgan"
            className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
              Department *
            </label>
            <input
              type="text"
              name="department"
              id="department"
              required
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="e.g. Engineering"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
              Start Date *
            </label>
            <input
              type="text"
              name="start_date"
              id="start_date"
              required
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              placeholder="YYYY-MM-DD"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Role / Position
          </label>
          <input
            type="text"
            name="role"
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder="e.g. Platform Engineer"
            className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
            Required Onboarding Checklist Items
          </label>
          <div className="space-y-2 bg-slate-950/60 p-3 rounded border border-slate-800">
            {["Security Background Check", "Laptop Provisioning", "System Access", "Benefits Enrolled"].map((item) => (
              <label key={item} className="flex items-center space-x-2 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  name={item.toLowerCase().replace(/\s+/g, "_")}
                  checked={checklist.includes(item)}
                  onChange={() => toggleChecklistItem(item)}
                  className="rounded border-slate-700 text-indigo-600 focus:ring-indigo-500"
                />
                <span>{item}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Onboarding Status
          </label>
          <select
            name="status"
            id="status"
            value={statusVal}
            onChange={(e) => setStatusVal(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="COMPLETED">COMPLETED</option>
            <option value="IN_PROGRESS">IN_PROGRESS</option>
            <option value="PENDING">PENDING</option>
          </select>
        </div>

        <div className="pt-2 flex items-center justify-between">
          <Link
            href="/hr"
            className="text-xs text-slate-500 hover:text-slate-400 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            id="finalize-onboarding-btn"
            disabled={submitting}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-sm font-medium rounded-md shadow-sm transition-colors cursor-pointer"
          >
            {submitting ? "Finalizing..." : "Finalize Onboarding"}
          </button>
        </div>
      </form>
    </div>
  );
}
