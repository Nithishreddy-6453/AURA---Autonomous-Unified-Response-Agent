"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { OnboardingRecord } from "@/types/onboarding";

export default function HRDashboardPage() {
  const [records, setRecords] = useState<OnboardingRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const fetchRecords = async () => {
    try {
      setLoading(true);
      const url = search ? `/api/hr/onboarding?q=${encodeURIComponent(search)}` : "/api/hr/onboarding";
      const res = await fetch(url);
      const json = await res.json();
      if (json.success) {
        setRecords(json.data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRecords();
  }, [search]);

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between border-b border-slate-800 pb-5 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">HR Onboarding Portal</h1>
          <p className="text-sm text-slate-400 mt-1">
            AURA Autonomous Task Execution — Second Domain Pilot Sandbox (Port 3002)
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <Link
            href="/hr/onboarding/new"
            id="new-onboarding-link"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-md text-sm font-medium transition-colors cursor-pointer"
          >
            + New Onboarding Request
          </Link>
        </div>
      </div>

      <div className="mb-6 flex items-center justify-between">
        <input
          type="text"
          placeholder="Search by ID, candidate name, or department..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-slate-900 border border-slate-800 rounded-md px-4 py-2 text-sm text-slate-200 placeholder-slate-500 w-96 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <span className="text-xs text-slate-500">
          Showing {records.length} records
        </span>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-sm">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950/80 text-xs text-slate-400 uppercase tracking-wider border-b border-slate-800">
            <tr>
              <th className="px-6 py-3 font-semibold">Employee ID</th>
              <th className="px-6 py-3 font-semibold">Name</th>
              <th className="px-6 py-3 font-semibold">Department</th>
              <th className="px-6 py-3 font-semibold">Start Date</th>
              <th className="px-6 py-3 font-semibold">Checklist</th>
              <th className="px-6 py-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-500">
                  Loading onboarding records...
                </td>
              </tr>
            ) : records.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-500">
                  No onboarding records found.
                </td>
              </tr>
            ) : (
              records.map((r) => (
                <tr key={r.employee_id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-6 py-4 font-mono font-medium text-indigo-400">
                    {r.employee_id}
                  </td>
                  <td className="px-6 py-4 text-white font-medium">{r.name}</td>
                  <td className="px-6 py-4 text-slate-300">{r.department}</td>
                  <td className="px-6 py-4 text-slate-400 font-mono">{r.start_date}</td>
                  <td className="px-6 py-4 text-xs text-slate-400">
                    {r.checklist && r.checklist.length > 0 ? (
                      <span>{r.checklist.length} items ({r.checklist.join(", ")})</span>
                    ) : (
                      <span className="text-slate-600">None</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        r.status === "COMPLETED"
                          ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                          : r.status === "IN_PROGRESS"
                          ? "bg-amber-950 text-amber-400 border border-amber-800"
                          : "bg-slate-800 text-slate-400 border border-slate-700"
                      }`}
                    >
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
