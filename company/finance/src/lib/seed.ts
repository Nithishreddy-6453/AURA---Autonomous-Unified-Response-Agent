import { Invoice } from "../types/invoice";

// Seeded sample invoices for Acme, Globex, and Nova
// Notice: Acme Jan 2026 invoice (INV-2026-0012) is already in the portal,
// while the latest Acme Mar 2026 invoice (INV-2026-0089) is ready to be entered by AURA!
export const SEED_INVOICES: Invoice[] = [
  {
    invoice_id: "INV-2026-0012",
    company: "Acme Corp",
    invoice_date: "2026-01-15",
    amount: 15120.0,
    currency: "USD",
    due_date: "2026-02-15",
    status: "PAID",
    created_at: "2026-01-16T09:00:00.000Z",
    updated_at: "2026-01-16T09:00:00.000Z",
  },
  {
    invoice_id: "INV-GLX-4011",
    company: "Globex Logistics",
    invoice_date: "2026-02-10",
    amount: 5886.0,
    currency: "USD",
    due_date: "2026-03-10",
    status: "PAID",
    created_at: "2026-02-11T10:15:00.000Z",
    updated_at: "2026-02-11T10:15:00.000Z",
  },
  {
    invoice_id: "INV-NOV-9902",
    company: "Nova Systems",
    invoice_date: "2026-03-01",
    amount: 8640.0,
    currency: "USD",
    due_date: "2026-03-31",
    status: "PAID",
    created_at: "2026-03-02T14:30:00.000Z",
    updated_at: "2026-03-02T14:30:00.000Z",
  },
];
