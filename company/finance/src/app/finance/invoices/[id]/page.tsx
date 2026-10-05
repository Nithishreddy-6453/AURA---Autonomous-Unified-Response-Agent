"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import { Invoice, InvoiceStatus } from "@/types/invoice";
import FinanceNavbar from "@/components/FinanceNavbar";

export default function InvoiceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const unwrappedParams = use(params);
  const id = unwrappedParams.id;

  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchInvoice = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/finance/invoices/${encodeURIComponent(id)}`);
      const data = await res.json();
      if (res.ok && data.success) {
        setInvoice(data.data);
      } else {
        setError(data.error || `Invoice '${id}' could not be found.`);
      }
    } catch {
      setError("Failed to connect to Finance service.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInvoice();
  }, [id]);

  const handleStatusChange = async (newStatus: InvoiceStatus) => {
    setUpdating(true);
    setStatusMsg(null);
    try {
      const res = await fetch(`/api/finance/invoices/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setInvoice(data.data);
        setStatusMsg(`Status updated to ${newStatus}`);
      } else {
        setError(data.error || "Failed to update status.");
      }
    } catch {
      setError("Network error updating invoice.");
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <FinanceNavbar />

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/finance/invoices"
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            &larr; Back to all invoices
          </Link>
          <div className="text-xs font-mono text-slate-400">ID: {id}</div>
        </div>

        {error && (
          <div
            id="detail-error-alert"
            className="mb-6 p-4 bg-rose-50 border border-rose-300 text-rose-800 rounded-lg text-sm"
          >
            {error}
          </div>
        )}

        {statusMsg && (
          <div
            id="detail-status-alert"
            className="mb-6 p-4 bg-emerald-50 border border-emerald-300 text-emerald-800 rounded-lg text-sm"
          >
            {statusMsg}
          </div>
        )}

        {loading ? (
          <div className="bg-white p-12 text-center text-slate-400 rounded-xl border border-slate-200">
            Loading invoice details...
          </div>
        ) : !invoice ? (
          <div
            id="invoice-not-found"
            className="bg-white p-12 text-center text-slate-600 rounded-xl border border-slate-200"
          >
            <h2 className="text-lg font-bold text-slate-800">Invoice Not Found</h2>
            <p className="text-sm text-slate-500 mt-2">
              No invoice with ID <span className="font-mono">{id}</span> was found in the system.
            </p>
          </div>
        ) : (
          <div
            id="invoice-detail-card"
            className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden"
          >
            {/* Header Banner */}
            <div className="p-6 bg-slate-900 text-white flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div>
                <span className="text-xs uppercase tracking-wider text-slate-400 font-semibold">
                  Invoice
                </span>
                <h1 className="text-2xl font-mono font-bold" id="detail-invoice-id">
                  {invoice.invoice_id}
                </h1>
                <p className="text-sm text-slate-300 mt-0.5" id="detail-company">
                  {invoice.company}
                </p>
              </div>
              <div className="text-right">
                <span
                  id="detail-status-badge"
                  className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold ${
                    invoice.status === "PAID"
                      ? "bg-emerald-500 text-white"
                      : invoice.status === "PENDING"
                      ? "bg-amber-500 text-white"
                      : "bg-slate-700 text-slate-200"
                  }`}
                >
                  {invoice.status}
                </span>
                <p className="text-2xl font-bold font-mono text-white mt-2" id="detail-amount">
                  ${invoice.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </p>
                <span className="text-xs uppercase text-slate-400 font-mono">
                  {invoice.currency}
                </span>
              </div>
            </div>

            {/* Info Grid */}
            <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-6 border-b border-slate-100">
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Invoice Date
                </h3>
                <p className="text-base font-medium text-slate-800 mt-1" id="detail-invoice-date">
                  {invoice.invoice_date}
                </p>
              </div>

              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Payment Due Date
                </h3>
                <p className="text-base font-medium text-slate-800 mt-1" id="detail-due-date">
                  {invoice.due_date}
                </p>
              </div>

              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  System Created At
                </h3>
                <p className="text-xs text-slate-600 mt-1 font-mono" id="detail-created-at">
                  {invoice.created_at}
                </p>
              </div>

              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Last Updated At
                </h3>
                <p className="text-xs text-slate-600 mt-1 font-mono" id="detail-updated-at">
                  {invoice.updated_at}
                </p>
              </div>
            </div>

            {/* Action Bar */}
            <div className="p-6 bg-slate-50 flex flex-wrap items-center justify-between gap-4">
              <span className="text-xs text-slate-500 font-medium">Update Status:</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  id="mark-pending-button"
                  disabled={updating || invoice.status === "PENDING"}
                  onClick={() => handleStatusChange("PENDING")}
                  className="px-3 py-1.5 text-xs font-semibold rounded-md border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-40 transition"
                >
                  Set PENDING
                </button>
                <button
                  type="button"
                  id="mark-paid-button"
                  disabled={updating || invoice.status === "PAID"}
                  onClick={() => handleStatusChange("PAID")}
                  className="px-3 py-1.5 text-xs font-semibold rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-40 transition"
                >
                  Mark PAID
                </button>
                <button
                  type="button"
                  id="mark-cancelled-button"
                  disabled={updating || invoice.status === "CANCELLED"}
                  onClick={() => handleStatusChange("CANCELLED")}
                  className="px-3 py-1.5 text-xs font-semibold rounded-md border border-rose-300 text-rose-700 hover:bg-rose-50 disabled:opacity-40 transition"
                >
                  Cancel Invoice
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
