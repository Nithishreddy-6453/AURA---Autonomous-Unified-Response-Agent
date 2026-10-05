import React from "react";
import Link from "next/link";

export default function FinanceNavbar() {
  return (
    <header className="border-b border-slate-200 bg-white shadow-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link href="/finance" className="flex items-center gap-2 text-indigo-600 font-bold text-xl tracking-tight">
            <span className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center text-sm font-black shadow-sm">
              FP
            </span>
            Finance Portal
          </Link>
          <nav className="flex items-center gap-4 text-sm font-medium">
            <Link
              href="/finance"
              className="text-slate-600 hover:text-indigo-600 transition-colors py-1 px-2 rounded-md hover:bg-slate-50"
            >
              Dashboard
            </Link>
            <Link
              href="/finance/invoices"
              className="text-slate-600 hover:text-indigo-600 transition-colors py-1 px-2 rounded-md hover:bg-slate-50"
            >
              Invoices
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/finance/invoices/new"
            id="nav-new-invoice-btn"
            className="inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-xs text-white bg-indigo-600 hover:bg-indigo-700 transition"
          >
            + New Invoice
          </Link>
        </div>
      </div>
    </header>
  );
}
