"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import FinanceNavbar from "@/components/FinanceNavbar";

export default function NewInvoicePage() {
  const router = useRouter();

  const [form, setForm] = useState({
    invoice_id: "",
    company: "",
    invoice_date: "",
    amount: "",
    currency: "USD",
    due_date: "",
    status: "PENDING",
  });

  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    // Clear specific field error upon editing
    if (fieldErrors[name]) {
      setFieldErrors((prev) => {
        const copy = { ...prev };
        delete copy[name];
        return copy;
      });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);
    setFieldErrors({});
    setSuccessMessage(null);

    try {
      const res = await fetch("/api/finance/invoices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        setSuccessMessage(`Invoice ${data.data.invoice_id} successfully recorded!`);
        setTimeout(() => {
          router.push(`/finance/invoices/${data.data.invoice_id}`);
        }, 800);
      } else {
        setErrorMessage(data.error || "Failed to create invoice.");
        if (data.fieldErrors) {
          setFieldErrors(data.fieldErrors);
        }
      }
    } catch {
      setErrorMessage("Network error connecting to Finance service.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <FinanceNavbar />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">Enter New Invoice</h1>
            <p className="text-sm text-slate-500 mt-1">
              Record incoming vendor invoice details for accounts payable.
            </p>
          </div>
          <Link
            href="/finance/invoices"
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            &larr; Back to Invoices
          </Link>
        </div>

        {errorMessage && (
          <div
            id="form-error-alert"
            className="mb-6 p-4 bg-rose-50 border border-rose-300 text-rose-800 rounded-lg text-sm font-medium flex flex-col gap-1"
          >
            <div className="flex items-center gap-2">
              <span className="font-bold text-rose-700">Error:</span>
              <span>{errorMessage}</span>
            </div>
            {Object.keys(fieldErrors).length > 0 && (
              <ul className="list-disc list-inside mt-2 text-rose-700 text-xs space-y-1">
                {Object.entries(fieldErrors).map(([f, err]) => (
                  <li key={f}>
                    <span className="font-semibold uppercase">{f}</span>: {err}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {successMessage && (
          <div
            id="form-success-alert"
            className="mb-6 p-4 bg-emerald-50 border border-emerald-300 text-emerald-800 rounded-lg text-sm font-medium"
          >
            {successMessage}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          id="new-invoice-form"
          className="bg-white p-8 rounded-xl border border-slate-200 shadow-xs space-y-6"
        >
          {/* Invoice ID */}
          <div>
            <label
              htmlFor="invoice_id"
              className="block text-sm font-semibold text-slate-700 mb-1"
            >
              Invoice ID / Reference Number *
            </label>
            <input
              type="text"
              name="invoice_id"
              id="invoice_id"
              placeholder="e.g. INV-2026-0089"
              value={form.invoice_id}
              onChange={handleChange}
              className={`w-full px-4 py-2 border rounded-lg text-sm font-mono focus:outline-hidden focus:ring-2 ${
                fieldErrors.invoice_id
                  ? "border-rose-400 focus:ring-rose-400 bg-rose-50/30"
                  : "border-slate-300 focus:ring-indigo-500 bg-white"
              }`}
            />
            {fieldErrors.invoice_id && (
              <p className="mt-1 text-xs text-rose-600" id="error-invoice_id">
                {fieldErrors.invoice_id}
              </p>
            )}
          </div>

          {/* Company / Vendor */}
          <div>
            <label htmlFor="company" className="block text-sm font-semibold text-slate-700 mb-1">
              Company / Vendor Name *
            </label>
            <input
              type="text"
              name="company"
              id="company"
              placeholder="e.g. Acme Corp"
              value={form.company}
              onChange={handleChange}
              className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-hidden focus:ring-2 ${
                fieldErrors.company
                  ? "border-rose-400 focus:ring-rose-400 bg-rose-50/30"
                  : "border-slate-300 focus:ring-indigo-500 bg-white"
              }`}
            />
            {fieldErrors.company && (
              <p className="mt-1 text-xs text-rose-600" id="error-company">
                {fieldErrors.company}
              </p>
            )}
          </div>

          {/* Amount & Currency */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label htmlFor="amount" className="block text-sm font-semibold text-slate-700 mb-1">
                Total Amount *
              </label>
              <div className="relative rounded-md shadow-2xs">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500 text-sm">
                  $
                </span>
                <input
                  type="text"
                  name="amount"
                  id="amount"
                  placeholder="0.00"
                  value={form.amount}
                  onChange={handleChange}
                  className={`w-full pl-8 pr-4 py-2 border rounded-lg text-sm font-mono focus:outline-hidden focus:ring-2 ${
                    fieldErrors.amount
                      ? "border-rose-400 focus:ring-rose-400 bg-rose-50/30"
                      : "border-slate-300 focus:ring-indigo-500 bg-white"
                  }`}
                />
              </div>
              {fieldErrors.amount && (
                <p className="mt-1 text-xs text-rose-600" id="error-amount">
                  {fieldErrors.amount}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="currency"
                className="block text-sm font-semibold text-slate-700 mb-1"
              >
                Currency
              </label>
              <select
                name="currency"
                id="currency"
                value={form.currency}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
              >
                <option value="USD">USD ($)</option>
                <option value="EUR">EUR (€)</option>
                <option value="GBP">GBP (£)</option>
              </select>
            </div>
          </div>

          {/* Invoice Date & Due Date */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="invoice_date"
                className="block text-sm font-semibold text-slate-700 mb-1"
              >
                Invoice Date *
              </label>
              <input
                type="date"
                name="invoice_date"
                id="invoice_date"
                value={form.invoice_date}
                onChange={handleChange}
                className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-hidden focus:ring-2 ${
                  fieldErrors.invoice_date
                    ? "border-rose-400 focus:ring-rose-400 bg-rose-50/30"
                    : "border-slate-300 focus:ring-indigo-500 bg-white"
                }`}
              />
              {fieldErrors.invoice_date && (
                <p className="mt-1 text-xs text-rose-600" id="error-invoice_date">
                  {fieldErrors.invoice_date}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="due_date"
                className="block text-sm font-semibold text-slate-700 mb-1"
              >
                Due Date *
              </label>
              <input
                type="date"
                name="due_date"
                id="due_date"
                value={form.due_date}
                onChange={handleChange}
                className={`w-full px-4 py-2 border rounded-lg text-sm focus:outline-hidden focus:ring-2 ${
                  fieldErrors.due_date
                    ? "border-rose-400 focus:ring-rose-400 bg-rose-50/30"
                    : "border-slate-300 focus:ring-indigo-500 bg-white"
                }`}
              />
              {fieldErrors.due_date && (
                <p className="mt-1 text-xs text-rose-600" id="error-due_date">
                  {fieldErrors.due_date}
                </p>
              )}
            </div>
          </div>

          {/* Status */}
          <div>
            <label htmlFor="status" className="block text-sm font-semibold text-slate-700 mb-1">
              Initial Status
            </label>
            <select
              name="status"
              id="status"
              value={form.status}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
            >
              <option value="PENDING">PENDING (Awaiting Approval)</option>
              <option value="PAID">PAID (Settled)</option>
              <option value="OVERDUE">OVERDUE</option>
            </select>
          </div>

          {/* Submit Buttons */}
          <div className="pt-4 border-t border-slate-100 flex items-center justify-end gap-3">
            <Link
              href="/finance/invoices"
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800"
            >
              Cancel
            </Link>
            <button
              type="submit"
              id="submit-invoice-button"
              disabled={submitting}
              className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-semibold rounded-lg shadow-xs transition"
            >
              {submitting ? "Saving..." : "Save Invoice"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
