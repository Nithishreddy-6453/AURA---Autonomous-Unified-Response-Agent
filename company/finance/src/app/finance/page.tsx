import React from "react";
import Link from "next/link";
import { listInvoices } from "@/lib/invoiceStore";
import FinanceNavbar from "@/components/FinanceNavbar";

export default function FinanceDashboardPage() {
  const invoices = listInvoices();

  const totalAmount = invoices.reduce((acc, inv) => acc + inv.amount, 0);
  const paidCount = invoices.filter((i) => i.status === "PAID").length;
  const pendingCount = invoices.filter((i) => i.status === "PENDING").length;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <FinanceNavbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-200">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
              Finance Overview
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Accounts Payable & Invoice Entry Workspace
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/finance/invoices/new"
              id="dashboard-create-invoice-link"
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg shadow-xs transition"
            >
              Enter Invoice
            </Link>
            <Link
              href="/finance/invoices"
              id="dashboard-view-all-invoices-link"
              className="px-4 py-2 bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 text-sm font-semibold rounded-lg shadow-xs transition"
            >
              View Invoices
            </Link>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-8">
          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-xs">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Total Invoiced
            </p>
            <p className="text-3xl font-bold text-slate-900 mt-2" id="metric-total-invoiced">
              ${totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
            <p className="text-xs text-slate-400 mt-1">{invoices.length} invoices recorded</p>
          </div>

          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-xs">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Pending / Due
            </p>
            <p className="text-3xl font-bold text-amber-600 mt-2" id="metric-pending-count">
              {pendingCount}
            </p>
            <p className="text-xs text-slate-400 mt-1">Awaiting verification or payment</p>
          </div>

          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-xs">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Paid Invoices
            </p>
            <p className="text-3xl font-bold text-emerald-600 mt-2" id="metric-paid-count">
              {paidCount}
            </p>
            <p className="text-xs text-slate-400 mt-1">Settled invoices</p>
          </div>
        </div>

        {/* Recent Invoices Table */}
        <div className="mt-10 bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Recent Invoices</h2>
            <Link
              href="/finance/invoices"
              className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
            >
              See all &rarr;
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" id="dashboard-recent-invoices-table">
              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200 text-xs uppercase font-medium">
                <tr>
                  <th className="px-6 py-3">Invoice ID</th>
                  <th className="px-6 py-3">Company</th>
                  <th className="px-6 py-3">Date</th>
                  <th className="px-6 py-3">Due Date</th>
                  <th className="px-6 py-3 text-right">Amount</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {invoices.slice(0, 5).map((inv) => (
                  <tr key={inv.invoice_id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-6 py-4 font-mono font-medium text-indigo-600">
                      <Link href={`/finance/invoices/${inv.invoice_id}`}>
                        {inv.invoice_id}
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-slate-800 font-medium">{inv.company}</td>
                    <td className="px-6 py-4 text-slate-600">{inv.invoice_date}</td>
                    <td className="px-6 py-4 text-slate-600">{inv.due_date}</td>
                    <td className="px-6 py-4 font-mono font-medium text-right text-slate-900">
                      ${inv.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
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
                        className="text-xs font-medium text-slate-600 hover:text-indigo-600 border border-slate-200 px-2.5 py-1 rounded-md"
                      >
                        Details
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
