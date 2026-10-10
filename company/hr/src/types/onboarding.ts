export interface OnboardingRecord {
  employee_id: string;
  name: string;
  department: string;
  start_date: string;
  role?: string;
  checklist: string[];
  status: "PENDING" | "IN_PROGRESS" | "COMPLETED";
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface CreateOnboardingInput {
  employee_id: string;
  name: string;
  department: string;
  start_date: string;
  role?: string;
  checklist?: string[];
  status?: "PENDING" | "IN_PROGRESS" | "COMPLETED";
  notes?: string;
}

export interface UpdateOnboardingInput {
  name?: string;
  department?: string;
  start_date?: string;
  role?: string;
  checklist?: string[];
  status?: "PENDING" | "IN_PROGRESS" | "COMPLETED";
  notes?: string;
}
