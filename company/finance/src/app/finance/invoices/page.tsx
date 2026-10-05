"use client";

import React, { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { Invoice } from "@/types/invoice";
import FinanceNavbar from "@/components/FinanceNavbar";

export default function InvoicesListPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const fetchInvoices = async (q?: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = q ? `/api/finance/invoices?q=${encodeURIComponent(q)}` : "/api/finance/invoices";
      const res = await fetch(url);
      const data = await res.json();
      if (data.success) {
        setInvoices(data.data);
      } else {
        setError(data.error || "Failed to load invoices.");
      }
    } catch {
      setError("Network error fetching invoices.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInvoices();
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startTransition(() => {
      fetchInvoices(searchQuery);
    });
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <FinanceNavbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-200">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Invoices</h1>
            <p className="mt-1 text-sm text-slate-500">
              Manage accounts payable and recorded vendor billing.
            </p>
          </div>
          <Link
            href="/finance/invoices/new"
            id="create-invoice-button"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg shadow-xs transition"
          >
            + New Invoice
          </Link>
        </div>

        {/* Search Bar */}
        <div className="mt-6 flex items-center justify-between gap-4">
          <form onSubmit={handleSearchSubmit} className="flex-1 max-w-lg flex items-center gap-2">
            <input
              type="text"
              id="invoice-search-input"
              placeholder="Search by Invoice ID, vendor, or amount..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-4 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 shadow-2xs"
            />
            <button
              type="submit"
              id="invoice-search-button"
              className="px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white text-sm font-medium rounded-lg transition"
            >
              Search
            </button>
            {searchQuery && (
              <button
                type="button"
                id="invoice-search-clear-button"
                onClick={() => {
                  setSearchQuery("");
                  fetchInvoices("");
                }}
                className="px-3 py-2 text-slate-500 hover:text-slate-700 text-sm font-medium"
              >
                Clear
              </button>
            )}
          </form>
          <div className="text-sm text-slate-500 font-medium">
            Total records: <span id="invoices-count">{invoices.length}</span>
          </div>
        </div>

        {error && (
          <div
            id="invoices-error-banner"
            className="mt-4 p-4 bg-rose-50 border border-rose-200 text-rose-700 rounded-lg text-sm"
          >
            {error}
          </div>
        )}

        {/* Table of Invoices */}
        <div className="mt-6 bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-slate-400 text-sm" id="invoices-loading">
              Loading invoices...
            </div>
          ) : invoices.length === 0 ? (
            <div className="p-12 text-center text-slate-500 text-sm" id="invoices-empty">
              No invoices found matching your criteria.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" id="invoices-table">
                <thead className="bg-slate-50 text-slate-600 border-b border-slate-200 text-xs uppercase font-medium">
                  <tr>
                    <th className="px-6 py-3">Invoice ID</th>
                    <th className="px-6 py-3">Company / Vendor</th>
                    <th className="px-6 py-3">Date</th>
                    <th className="px-6 py-3">Due Date</th>
                    <th className="px-6 py-3 text-right">Amount</th>
                    <th className="px-6 py-3">Currency</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invoices.map((inv) => (
                    <tr
                      key={inv.invoice_id}
                      className="hover:bg-slate-50/80 transition-colors"
                      data-invoice-id={inv.invoice_id}
                    >
                      <td className="px-6 py-4 font-mono font-medium text-indigo-600">
                        <Link
                          href={`/finance/invoices/${inv.invoice_id}`}
                          id={`invoice-link-${inv.invoice_id}`}
                        >
                          {inv.invoice_id}
                        </Link>
                      </td>
                      <td className="px-6 py-4 text-slate-800 font-medium">{inv.company}</td>
                      <td className="px-6 py-4 text-slate-600">{inv.invoice_date}</td>
                      <td className="px-6 py-4 text-slate-600">{inv.due_date}</td>
                      <td className="px-6 py-4 font-mono font-medium text-right text-slate-900">
                        ${inv.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-6 py-4 text-slate-500 uppercase">{inv.currency}</td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                            inv.status === "PAID"
                              ? "bg-emerald-100 text-emerald-800"
                              : inv.status === "PENDING"
                              ? "bg-amber-100 text-amber-800"
                              : "bg-slate-100 text-slate-800"
                          }`}
                        >
                          {inv.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <Link
                          href={`/finance/invoices/${inv.invoice_id}`}
                          className="text-xs font-medium text-indigo-600 hover:text-indigo-900 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-md transition"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
