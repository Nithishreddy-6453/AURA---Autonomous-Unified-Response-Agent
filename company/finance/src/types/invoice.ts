export type InvoiceStatus = "PENDING" | "PAID" | "OVERDUE" | "CANCELLED";

export interface Invoice {
  invoice_id: string;
  company: string;
  invoice_date: string;
  amount: number;
  currency: string;
  due_date: string;
  status: InvoiceStatus;
  created_at: string;
  updated_at: string;
}

export interface CreateInvoiceInput {
  invoice_id: string;
  company: string;
  invoice_date: string;
  amount: number | string;
  currency?: string;
  due_date: string;
  status?: InvoiceStatus;
}

export interface UpdateInvoiceInput {
  company?: string;
  invoice_date?: string;
  amount?: number | string;
  currency?: string;
  due_date?: string;
  status?: InvoiceStatus;
}
