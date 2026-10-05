import { Invoice, CreateInvoiceInput, UpdateInvoiceInput } from "../types/invoice";
import { SEED_INVOICES } from "./seed";

export class ValidationError extends Error {
  public fieldErrors: Record<string, string>;
  public code: string;

  constructor(message: string, fieldErrors: Record<string, string> = {}, code = "VALIDATION_ERROR") {
    super(message);
    this.name = "ValidationError";
    this.fieldErrors = fieldErrors;
    this.code = code;
  }
}

export class DuplicateError extends Error {
  public code: string;

  constructor(message: string) {
    super(message);
    this.name = "DuplicateError";
    this.code = "DUPLICATE_INVOICE";
  }
}

// In-memory data store using globalThis so state persists across API route calls in dev mode
const globalForInvoices = globalThis as unknown as {
  financeInvoicesStore: Map<string, Invoice> | undefined;
};

function getStore(): Map<string, Invoice> {
  if (!globalForInvoices.financeInvoicesStore) {
    const store = new Map<string, Invoice>();
    for (const inv of SEED_INVOICES) {
      store.set(inv.invoice_id.toUpperCase(), { ...inv });
    }
    globalForInvoices.financeInvoicesStore = store;
  }
  return globalForInvoices.financeInvoicesStore;
}

export function listInvoices(query?: string): Invoice[] {
  const store = getStore();
  const all = Array.from(store.values());

  // Sort descending by invoice_date
  all.sort((a, b) => new Date(b.invoice_date).getTime() - new Date(a.invoice_date).getTime());

  if (!query) {
    return all;
  }

  const q = query.trim().toLowerCase();
  return all.filter(
    (inv) =>
      inv.invoice_id.toLowerCase().includes(q) ||
      inv.company.toLowerCase().includes(q) ||
      inv.status.toLowerCase().includes(q) ||
      inv.amount.toString().includes(q)
  );
}

export function getInvoice(id: string): Invoice | null {
  const store = getStore();
  return store.get(id.trim().toUpperCase()) || null;
}

export function createInvoice(input: CreateInvoiceInput): Invoice {
  const store = getStore();
  const fieldErrors: Record<string, string> = {};

  const invoice_id = input.invoice_id?.trim();
  const company = input.company?.trim();
  const invoice_date = input.invoice_date?.trim();
  const due_date = input.due_date?.trim();
  const currency = (input.currency?.trim() || "USD").toUpperCase();
  const status = input.status || "PENDING";

  // 1. Missing required field checks
  if (!invoice_id) {
    fieldErrors.invoice_id = "Invoice ID is required.";
  }
  if (!company) {
    fieldErrors.company = "Company name is required.";
  }
  if (!invoice_date) {
    fieldErrors.invoice_date = "Invoice date is required.";
  }
  if (!due_date) {
    fieldErrors.due_date = "Due date is required.";
  }

  // 2. Amount validation
  if (input.amount === undefined || input.amount === null || input.amount === "") {
    fieldErrors.amount = "Invoice amount is required.";
  }

  const parsedAmount = typeof input.amount === "string" ? parseFloat(input.amount) : input.amount;
  if (isNaN(parsedAmount) || parsedAmount <= 0) {
    fieldErrors.amount = "Amount must be a valid positive number greater than 0.";
  }

  if (Object.keys(fieldErrors).length > 0) {
    throw new ValidationError("Invoice validation failed. Please check the fields.", fieldErrors);
  }

  // 3. Duplicate detection
  const normalizedId = invoice_id.toUpperCase();
  if (store.has(normalizedId)) {
    throw new DuplicateError(`Invoice with ID '${invoice_id}' already exists.`);
  }

  const now = new Date().toISOString();
  const newInvoice: Invoice = {
    invoice_id,
    company,
    invoice_date,
    amount: Math.round(parsedAmount * 100) / 100,
    currency,
    due_date,
    status,
    created_at: now,
    updated_at: now,
  };

  store.set(normalizedId, newInvoice);
  return newInvoice;
}

export function updateInvoice(id: string, input: UpdateInvoiceInput): Invoice {
  const store = getStore();
  const normalizedId = id.trim().toUpperCase();
  const existing = store.get(normalizedId);

  if (!existing) {
    throw new Error(`Invoice '${id}' not found.`);
  }

  const fieldErrors: Record<string, string> = {};

  if (input.amount !== undefined) {
    const parsed = typeof input.amount === "string" ? parseFloat(input.amount) : input.amount;
    if (isNaN(parsed) || parsed <= 0) {
      fieldErrors.amount = "Amount must be a valid positive number greater than 0.";
    }
  }

  if (Object.keys(fieldErrors).length > 0) {
    throw new ValidationError("Failed to update invoice.", fieldErrors);
  }

  const updated: Invoice = {
    ...existing,
    company: input.company !== undefined ? input.company.trim() : existing.company,
    invoice_date: input.invoice_date !== undefined ? input.invoice_date.trim() : existing.invoice_date,
    amount:
      input.amount !== undefined
        ? Math.round(
            (typeof input.amount === "string" ? parseFloat(input.amount) : input.amount) * 100
          ) / 100
        : existing.amount,
    currency: input.currency !== undefined ? input.currency.trim().toUpperCase() : existing.currency,
    due_date: input.due_date !== undefined ? input.due_date.trim() : existing.due_date,
    status: input.status !== undefined ? input.status : existing.status,
    updated_at: new Date().toISOString(),
  };

  store.set(normalizedId, updated);
  return updated;
}

export function resetStore(): void {
  const store = new Map<string, Invoice>();
  for (const inv of SEED_INVOICES) {
    store.set(inv.invoice_id.toUpperCase(), { ...inv });
  }
  globalForInvoices.financeInvoicesStore = store;
}
