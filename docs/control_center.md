# AURA Control Center Architecture & Operational Guide

## 1. Overview & Conceptual Architecture

The **AURA Control Center** is the unified user-facing operations console for interacting with the AURA autonomous agent. It allows operators to submit complex business goals, monitor live operational execution, inspect detailed short-term memory traces, and review/grant permissions at human approval gates.

```
       User Operator
             │
             ▼
    AURA Control Center (Next.js / TypeScript / Tailwind CSS)
             │  (HTTP / JSON Polling: GET/POST /api/tasks)
             ▼
        FastAPI Gateway (backend/api/main.py)
             │
             ▼
        AgentRuntime (Sole Orchestration Authority)
             │
    ┌────────┴───────────────────────────┬──────────────────────┐
    ▼                                    ▼                      ▼
 Planner (LLM)                  Action Policy Engine      MemoryStore (SQLite)
    │                                    │                      │
    ▼                                    ▼                      │
 Tool Registry                   WAITING_FOR_HUMAN              │
 (Document / Browser Tools)       (Human Approval)              │
    │                                    │                      │
    └────────────────┬───────────────────┘                      │
                     ▼                                          ▼
            Observation Layer ───────────────────────► Short-Term History
                     │
                     ▼
          Verification Subsystem
```

### Critical Architectural Boundaries
* **Frontend Authority**: The Control Center is strictly a visual user interface. It contains **no** Planner logic, **no** LLM prompts, and **never** executes tools directly.
* **Backend Runtime Authority**: `AgentRuntime` remains the sole orchestration and lifecycle authority.
* **Privacy & Reasoning Isolation**: Internal chain-of-thought and hidden prompt mechanics are never exposed to the client; only bounded operational lifecycle events (actions, observations, policy gates, verifications) are surfaced.

---

## 2. API Architecture & Data Contracts

The FastAPI backend provides structured, strongly-typed endpoints defined in `backend/api/models.py`.

### Endpoints
* `GET /health`: Health check endpoint (`{"status": "ok", "service": "aura-agent-api"}`).
* `POST /api/tasks`: Creates a task record in `MemoryStore` as `AgentState.RECEIVED`, returns `TaskSummary` with HTTP 201, and schedules background execution via `asyncio.create_task`.
* `GET /api/tasks`: Lists recent tasks from `SQLiteMemoryStore` (`limit` parameter up to 100).
* `GET /api/tasks/{task_id}`: Retrieves full `TaskDetail` including actions, observations, recovery events, policy decisions, and plan.
* `GET /api/tasks/{task_id}/events`: Retrieves chronological operational events (`TaskEvent[]`) for the live activity timeline.
* `POST /api/tasks/{task_id}/approve`: Approves a pending action in `WAITING_FOR_HUMAN`, logs approval to `MemoryStore`, and resumes execution in the background.
* `POST /api/tasks/{task_id}/reject`: Rejects a pending action, records rejection reason, and transitions task to `FAILED`.
* `POST /api/tasks/{task_id}/resume`: Resumes a non-terminal interrupted task.

### Background Execution
Background task dispatch avoids HTTP request timeouts:
1. `POST /api/tasks` writes the task immediately to `data/aura_memory.db` to prevent query race conditions.
2. An asynchronous background worker executes `runtime.execute_task(task)`.
3. The frontend receives the `task_id` in milliseconds and begins interval polling.

---

## 3. Task Lifecycle & Polling Strategy

Tasks transition through standardized `AgentState` values:
```
RECEIVED ──► UNDERSTANDING ──► PLANNING ──► EXECUTING ──► OBSERVING ──► ADAPTING ──► VERIFYING ──► COMPLETED
                                                │                                       │
                                                ▼                                       ▼
                                       WAITING_FOR_HUMAN                              FAILED
```

### Client Polling Policy
* **Active Tasks**: While a task is active (`RECEIVED`, `UNDERSTANDING`, `PLANNING`, `EXECUTING`, `OBSERVING`, `ADAPTING`, `VERIFYING`), the frontend polls `GET /api/tasks/{task_id}` and `GET /api/tasks/{task_id}/events` every 2000ms.
* **Terminal or Gated States**: When a task reaches `COMPLETED`, `FAILED`, or `WAITING_FOR_HUMAN`, continuous polling stops automatically to preserve system resources.
* **Post-Approval Resume**: Submitting an approval or rejection resumes polling until the subsequent terminal state is reached.

---

## 4. Human Approval Flow

When the `ActionPolicy` engine identifies a `SENSITIVE` action (e.g., invoice payments or financial adjustments):
1. The backend sets `state = WAITING_FOR_HUMAN` and `status = WAITING_FOR_HUMAN`.
2. The action arguments and policy reason are saved in `task.metadata["pending_action"]`.
3. The Control Center renders the **HUMAN APPROVAL REQUIRED** banner, detailing the target tool, risk classification (`SENSITIVE`), reason, and arguments.
4. The operator can:
   * **Approve & Continue**: Sends `POST /api/tasks/{task_id}/approve` with optional operator notes. The runtime marks `approval_status = APPROVED`, resumes execution, and runs the authorized tool.
   * **Reject**: Sends `POST /api/tasks/{task_id}/reject` with rejection feedback. The task transitions safely to `FAILED`.

---

## 5. Running the Complete System

### Step 1: Start Finance Portal (Port 3000)
```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent\company\finance
npm run start
```
Verifies at `http://localhost:3000/finance/invoices`.

### Step 2: Start FastAPI Backend (Port 8000)
```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent
.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```
Verifies at `http://127.0.0.1:8000/health`.

### Step 3: Start AURA Control Center (Port 3001)
```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent\frontend
npm run start
```
Access the Operations Console at `http://localhost:3001`.

---

## 6. End-to-End Invoice Demonstration Walkthrough

1. Open `http://localhost:3001` in your browser.
2. Confirm the header shows **API Connected** (green indicator).
3. Click **Insert Acme Invoice Example** or type:
   `Find the latest Acme invoice and enter its amount into the Finance Portal.`
4. Click **Run Task**.
5. Observe:
   * Instant assignment of task ID and `RECEIVED` status.
   * `Live Activity Timeline` populates with operational milestones: document extraction, file search, browser navigation to `http://localhost:3000`.
   * Playwright interacts with the Finance Portal to enter invoice fields with ISO date protection.
   * Verification subsystem confirms persisted records in the database.
   * The status badge shifts to `COMPLETED`.
