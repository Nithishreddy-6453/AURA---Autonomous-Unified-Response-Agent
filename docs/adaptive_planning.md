# AURA Adaptive Observation & Re-Planning (Phase 2)

## Overview

AURA operates on an **adaptive, observation-driven reasoning loop** rather than blindly executing fixed multi-step plans. The live environment (file system, browser DOM, HTTP endpoints) is the sole source of truth. Every action yields an observation, and every subsequent action is grounded in that observation.

---

## 1. Static Planning vs. Adaptive Planning

| Feature | Static Script Planning | AURA Adaptive Planning |
| :--- | :--- | :--- |
| **Execution Flow** | Planner produces Actions 1..N upfront; Runtime executes all without re-evaluating. | Planner determines an action $\to$ Runtime executes $\to$ Tool returns Observation $\to$ Planner re-evaluates $\to$ Next Action. |
| **Environmental Changes** | Fails or submits corrupt data if the environment diverges from initial assumptions. | Reacts to dynamic DOM changes, extracted file values, and asynchronous redirects. |
| **Error Handling** | Throws unhandled exceptions or halts completely. | Captures structured error observations, classifies failure types, and selects corrective recovery paths. |
| **Validation Handling** | Cannot recover if required fields or dynamic UI states appear unexpectedly. | Identifies missing fields from validation messages and adaptively fills them. |

---

## 2. Why Observations Influence the Next Action

Tools do not guess or rely on stale predictions. Grounding decisions in observations ensures:
1. **Dynamic Parameter Resolution**: File searches return actual filenames and timestamps on disk; reading tools return actual invoice IDs and totals. Subsequent form-fill actions use these exact observed values.
2. **Context-Aware DOM Interaction**: Browser reads capture the real state of interactive controls (e.g., whether a form submitted, redirected, or displayed a validation alert).
3. **Adaptive Correction**: When an observation indicates that a required field is missing, the planner transitions to an action that inputs the missing field rather than repeating the same failed click.

---

## 3. How Runtime Drives the Adaptive Loop

The [`AgentRuntime`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/agent/runtime.py) coordinates execution through a bounded state machine:

```text
               ┌────────────────────────────────────────────────────────┐
               │                                                        │
               ▼                                                        │
[PLAN] ──► [EXECUTE] ──► [OBSERVE] ──► [ADAPT] ─────────────────────────┘
                                          │
                                          ├─► (needs_human)  ──► [NEEDS_HUMAN]
                                          ├─► (is_complete)  ──► [VERIFY] ──► [COMPLETED]
                                          │                         │ (failed)
                                          │                         ▼
                                          │                     [RECOVERY] ──► (retry loop)
                                          └─► (exhausted)    ──► [FAILED]
```

### Lifecycle Progression:
1. **Initial Planning**: Validates feasibility and formulates the initial task goal and first action.
2. **Execution**: Dispatches the action through [`ToolRegistry`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/registry.py).
3. **Observation Recording**: Records structured [`Observation`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/models/observation.py) containing success status, result data, or errors.
4. **Adaptive Evaluation**: Invokes `Planner.decide_next_action(task, recent_actions, recent_observations, recovery_context)`.
5. **Bounded Context**: Supplies a bounded window of recent history (default 5 steps) and explicit recovery guidance to prevent prompt bloat.

---

## 4. How Recovery Interacts with Re-Planning

The recovery subsystem (`backend/recovery/`) classifies failures into structured categories:
- **`VALIDATION`**: e.g., missing required form fields $\to$ Policy: `CORRECT_DATA`. Passes recovery guidance to the planner so it can fill missing inputs and re-attempt submission.
- **`TRANSIENT`**: e.g., timeouts or network glitches $\to$ Policy: `RETRY`.
- **`NAVIGATION_STATE`**: e.g., selector not found due to page state $\to$ Policy: `RESET_AND_RETRY`.
- **`DUPLICATE` / `UNKNOWN`**: e.g., duplicate invoice ID or unexpected internal error $\to$ Policy: `ESCALATE` (halts task to prevent corruption).

---

## 5. Duplicate Action Protection & Step-Budget Limits

To prevent infinite loops or redundant tool calls:
1. **Duplicate Action Guard**: If the planner proposes the exact same tool and arguments that just failed, the runtime detects the duplicate. Repeating identical failed actions twice triggers automatic escalation.
2. **Step Budget Limit**: Every task has a configurable `max_dynamic_steps` (default 15). If the agent does not reach completion within the budget, execution halts immediately with `TaskStatus.FAILED` and a clear exhaustion error.

---

## 6. Why Independent Verification is Still Required

Logical completion proposed by the LLM (`"is_complete": true`) is a belief, not ground truth.
- The UI might report success while the database write silently dropped a field.
- A client-side form might transition without updating the underlying backend record.

Therefore, when the Planner declares completion:
1. Runtime enters `AgentState.VERIFYING`.
2. The independent verifier ([`FinanceInvoiceVerifier`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/verification/finance_verifier.py)) bypasses the browser UI and directly queries the backend REST API (`/api/finance/invoices/[id]`).
3. Field-by-field validation checks `company`, `invoice_date`, `due_date`, and `amount`.
4. Only upon independent confirmation does the task transition to `AgentState.COMPLETED`.
5. If verification detects a discrepancy, the failure feeds directly back into the adaptive loop with recovery context, allowing the agent to correct the persisted record.
