# AURA — Autonomous Unified Response Agent

AURA is an enterprise-grade autonomous response agent designed to observe, plan, execute, adapt, recover, and independently verify multi-step workflows across company documents and web applications.

## Architectural Flow

```
User Goal
  │
  ▼
Task (UUID)
  │
  ▼
Planner (Adaptive Reasoner)
  │
  ▼
Requested Action
  │
  ▼
Policy Enforcement (ActionPolicy Engine) ─────► MemoryStore (Policy Audit Record)
  │
  ├──► ALLOWED ───────────────► Tool Execution ──► Observation ──► Adapt / Verify
  │
  ├──► REQUIRES_HUMAN ────────► WAITING_FOR_HUMAN (Pending Action Persisted)
  │                                   │
  │                             [Human Approval]
  │                                   │
  │                                   ▼
  │                             Resume ──► Execute Pending Action ──► Loop Continues
  │
  └──► BLOCKED ───────────────► Execution Prevented
                                      │
                                      ▼
                                Blocked Observation ──► Planner Adapts to Safe Path
```

## Core Subsystems

1. **Agent Core & Runtime** ([`backend/agent/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/agent/)):
   - Adaptive observation-grounded loop with step budget protection and duplicate action guards.
   - Strongly-typed Pydantic schemas for tasks, actions, plans, and observations.
2. **Safety, Permissions & Policy Enforcement** ([`backend/policy/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/policy/)):
   - Centralized pre-execution policy engine evaluating action risk (`READ`, `WRITE`, `SENSITIVE`, `DESTRUCTIVE`).
   - Independent from LLM; enforces permissions, blocks destructive/unregistered tools, and pauses for human approval.
3. **Task Memory & State Persistence** ([`backend/memory/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/memory/)):
   - Pluggable `MemoryStore` interface and durable local `SQLiteMemoryStore`.
   - Records complete task lifecycles, state transitions, actions, observations, recovery events, and policy audits.
   - Supports non-terminal task resumption without replaying actions blindly; preserves terminal states.
4. **Company Document Tools** ([`backend/tools/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/)):
   - `search_company_files`, `read_company_file`, `document_extract`.
5. **Browser Automation Layer** ([`backend/tools/browser/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/)):
   - Playwright-backed controlled browser tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_read`, `browser_screenshot`.
   - Sandbox security restrictions (local origins and workspace test fixtures only).
6. **Adaptive Re-Planning & Recovery** ([`backend/recovery/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/recovery/)):
   - Dynamic replanning based on bounded recent observations.
   - Failure classification (`VALIDATION`, `TRANSIENT`, `NAVIGATION_STATE`, `DUPLICATE`, `UNKNOWN`) and recovery policies (`CORRECT_DATA`, `RETRY`, `RESET_AND_RETRY`, `ESCALATE`).
7. **Independent Verification** ([`backend/verification/`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/verification/)):
   - Verifies persisted application state independently via backend API, bypassing browser UI assumptions.

## Documentation

- [Browser Automation Architecture (Phase 1)](docs/browser_automation.md)
- [Adaptive Observation & Re-Planning (Phase 2)](docs/adaptive_planning.md)
- [Task State Persistence & Short-Term Memory (Phase 3)](docs/memory.md)
- [Safety, Permissions & Policy Enforcement (Phase 4)](docs/security_and_permissions.md)

## Running Tests

Ensure local Finance Portal is running:
```bash
cd company/finance
npm run start
```

Run test suite:
```bash
.venv\Scripts\python.exe -m unittest discover -s tests
```
