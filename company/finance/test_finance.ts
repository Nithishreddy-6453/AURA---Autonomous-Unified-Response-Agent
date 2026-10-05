import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import {
  listInvoices,
  getInvoice,
  createInvoice,
  updateInvoice,
  resetStore,
  ValidationError,
  DuplicateError,
} from "./src/lib/invoiceStore";

beforeEach(() => {
  resetStore();
});

test("Finance Portal Data Layer: List seeded invoices", () => {
  const invoices = listInvoices();
  assert.equal(invoices.length, 3);
  const ids = invoices.map((i) => i.invoice_id);
  assert.ok(ids.includes("INV-2026-0012")); // Acme seeded
  assert.ok(ids.includes("INV-GLX-4011")); // Globex seeded
  assert.ok(ids.includes("INV-NOV-9902")); // Nova seeded
});

test("Finance Portal Data Layer: Search invoices by query", () => {
  const acmeMatches = listInvoices("Acme");
  assert.equal(acmeMatches.length, 1);
  assert.equal(acmeMatches[0].company, "Acme Corp");

  const idMatches = listInvoices("4011");
  assert.equal(idMatches.length, 1);
  assert.equal(idMatches[0].invoice_id, "INV-GLX-4011");
});

test("Finance Portal Data Layer: Get invoice by ID", () => {
  const inv = getInvoice("INV-2026-0012");
  assert.ok(inv !== null);
  assert.equal(inv?.company, "Acme Corp");
  assert.equal(inv?.amount, 15120.0);

  const missing = getInvoice("INV-DOES-NOT-EXIST");
  assert.equal(missing, null);
});

test("Finance Portal Data Layer: Create invoice successfully", () => {
  const newInv = createInvoice({
    invoice_id: "INV-2026-0089",
    company: "Acme Corp",
    invoice_date: "2026-03-20",
    due_date: "2026-04-20",
    amount: "18036.00",
    currency: "USD",
    status: "PENDING",
  });

  assert.equal(newInv.invoice_id, "INV-2026-0089");
  assert.equal(newInv.amount, 18036.0);
  assert.equal(newInv.status, "PENDING");

  const fetched = getInvoice("INV-2026-0089");
  assert.ok(fetched !== null);
  assert.equal(fetched?.amount, 18036.0);

  const all = listInvoices();
  assert.equal(all.length, 4);
});

test("Finance Portal Data Layer: Duplicate invoice rejection", () => {
  assert.throws(
    () => {
      createInvoice({
        invoice_id: "INV-2026-0012", // Already seeded
        company: "Acme Corp",
        invoice_date: "2026-01-15",
        due_date: "2026-02-15",
        amount: 1000,
      });
    },
    (err: unknown) => {
      assert.ok(err instanceof DuplicateError);
      assert.equal(err.code, "DUPLICATE_INVOICE");
      return true;
    }
  );
});

test("Finance Portal Data Layer: Validation errors for missing required fields", () => {
  assert.throws(
    () => {
      createInvoice({
        invoice_id: "",
        company: "",
        invoice_date: "",
        due_date: "",
        amount: "",
      });
    },
    (err: unknown) => {
      assert.ok(err instanceof ValidationError);
      assert.ok(err.fieldErrors.invoice_id);
      assert.ok(err.fieldErrors.company);
      assert.ok(err.fieldErrors.amount);
      return true;
    }
  );
});

test("Finance Portal Data Layer: Validation error for invalid non-positive amount", () => {
  assert.throws(
    () => {
      createInvoice({
        invoice_id: "INV-BAD-AMT",
        company: "Acme Corp",
        invoice_date: "2026-03-20",
        due_date: "2026-04-20",
        amount: "-50.00",
      });
    },
    (err: unknown) => {
      assert.ok(err instanceof ValidationError);
      assert.ok(err.fieldErrors.amount.includes("greater than 0"));
      return true;
    }
  );
});

test("Finance Portal Data Layer: Update invoice", () => {
  const updated = updateInvoice("INV-2026-0012", {
    status: "CANCELLED",
    amount: 15500,
  });

  assert.equal(updated.status, "CANCELLED");
  assert.equal(updated.amount, 15500);

  const fetched = getInvoice("INV-2026-0012");
  assert.equal(fetched?.status, "CANCELLED");
});
