import { OnboardingRecord, CreateOnboardingInput, UpdateOnboardingInput } from "../types/onboarding";
import { SEED_ONBOARDINGS } from "./seed";

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
    this.code = "DUPLICATE_ONBOARDING";
  }
}

const globalForHR = globalThis as unknown as {
  hrOnboardingStore: Map<string, OnboardingRecord> | undefined;
};

function getStore(): Map<string, OnboardingRecord> {
  if (!globalForHR.hrOnboardingStore) {
    const store = new Map<string, OnboardingRecord>();
    for (const item of SEED_ONBOARDINGS) {
      store.set(item.employee_id.toUpperCase(), { ...item });
    }
    globalForHR.hrOnboardingStore = store;
  }
  return globalForHR.hrOnboardingStore;
}

export function listOnboardings(query?: string): OnboardingRecord[] {
  const store = getStore();
  const all = Array.from(store.values());

  all.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  if (!query) {
    return all;
  }

  const q = query.trim().toLowerCase();
  return all.filter(
    (item) =>
      item.employee_id.toLowerCase().includes(q) ||
      item.name.toLowerCase().includes(q) ||
      item.department.toLowerCase().includes(q) ||
      item.status.toLowerCase().includes(q)
  );
}

export function getOnboarding(id: string): OnboardingRecord | null {
  const store = getStore();
  return store.get(id.trim().toUpperCase()) || null;
}

export function createOnboarding(input: CreateOnboardingInput): OnboardingRecord {
  const store = getStore();
  const fieldErrors: Record<string, string> = {};

  const employee_id = input.employee_id?.trim();
  const name = input.name?.trim();
  const department = input.department?.trim();
  const start_date = input.start_date?.trim();
  const role = input.role?.trim() || "Employee";
  const status = input.status || "PENDING";
  const checklist = Array.isArray(input.checklist) ? input.checklist : [];
  const notes = input.notes?.trim() || "";

  if (!employee_id) fieldErrors.employee_id = "Employee ID is required.";
  if (!name) fieldErrors.name = "Employee name is required.";
  if (!department) fieldErrors.department = "Department is required.";
  if (!start_date) fieldErrors.start_date = "Start date is required.";

  if (Object.keys(fieldErrors).length > 0) {
    throw new ValidationError("Onboarding validation failed. Please check required fields.", fieldErrors);
  }

  const normalizedId = employee_id.toUpperCase();
  if (store.has(normalizedId)) {
    throw new DuplicateError(`Onboarding record with Employee ID '${employee_id}' already exists.`);
  }

  const now = new Date().toISOString();
  const newRecord: OnboardingRecord = {
    employee_id,
    name,
    department,
    start_date,
    role,
    checklist,
    status,
    notes,
    created_at: now,
    updated_at: now,
  };

  store.set(normalizedId, newRecord);
  return newRecord;
}

export function updateOnboarding(id: string, input: UpdateOnboardingInput): OnboardingRecord {
  const store = getStore();
  const normalizedId = id.trim().toUpperCase();
  const existing = store.get(normalizedId);

  if (!existing) {
    throw new Error(`Onboarding record '${id}' not found.`);
  }

  const updated: OnboardingRecord = {
    ...existing,
    name: input.name !== undefined ? input.name.trim() : existing.name,
    department: input.department !== undefined ? input.department.trim() : existing.department,
    start_date: input.start_date !== undefined ? input.start_date.trim() : existing.start_date,
    role: input.role !== undefined ? input.role.trim() : existing.role,
    checklist: Array.isArray(input.checklist) ? input.checklist : existing.checklist,
    status: input.status !== undefined ? input.status : existing.status,
    notes: input.notes !== undefined ? input.notes.trim() : existing.notes,
    updated_at: new Date().toISOString(),
  };

  store.set(normalizedId, updated);
  return updated;
}

export function resetStore(): void {
  const store = new Map<string, OnboardingRecord>();
  for (const item of SEED_ONBOARDINGS) {
    store.set(item.employee_id.toUpperCase(), { ...item });
  }
  globalForHR.hrOnboardingStore = store;
}
