# Safety, Permissions, and Action Policy Enforcement

Phase 4 introduces a centralized, deterministic safety and permissions policy layer to AURA.

---

## 1. Why Policy Enforcement Exists

In autonomous agent systems, language models generate proposed tool calls based on prompt context and goal instructions. However:
1. **The LLM is NOT the Authority**: Models may hallucinate dangerous parameters, select inappropriate tools, or fall victim to prompt injections that attempt unauthorized operations.
2. **Deterministic Security Boundaries**: Enterprise software cannot rely on prompt guidelines or probabilistic LLM alignment to prevent destructive operations.
3. **Defense-in-Depth**: An independent policy layer must intercept and evaluate every action **before** tool execution, ensuring only permitted actions reach execution substrates.

---

## 2. Architectural Flow

```
User Goal
  │
  ▼
Planner (Adaptive Reasoner)
  │
  ▼
Requested Action
  │
  ▼
Policy Check (ActionPolicy) ────────────────► MemoryStore (Audit Event)
  │
  ├──► ALLOWED ───────────────► Tool Execution ──► Observation ──► Loop continues
  │
  ├──► REQUIRES_HUMAN ────────► WAITING_FOR_HUMAN (Pending Action Stored)
  │                                   │
  │                             [Human Approval via approve_task]
  │                                   │
  │                                   ▼
  │                             Resume ──► Execute Pending Action ──► Loop continues
  │
  └──► BLOCKED ───────────────► Execution Prevented
                                      │
                                      ▼
                                Failure Observation ──► Planner Adapts to Safe Alternative
```

---

## 3. Planner vs. Policy Responsibilities

| Subsystem | Role | Authority |
| :--- | :--- | :--- |
| **Planner** | Strategic reasoning & action generation | Proposes candidate actions to achieve the user's goal based on recent observations. Has **no authority** to permit execution. |
| **ActionPolicy** | Safety & permission evaluation | Evaluates proposed actions against declared rules, tool capabilities, arguments, and environment constraints. **Sole authority** to allow, require approval, or block. |
| **Runtime** | Execution controller | Coordinates lifecycle transitions. Strictly validates policy before invoking `Tool.execute()`. |
| **MemoryStore** | Audit & state persistence | Records every policy evaluation, risk classification, approval, and rejection. |

---

## 4. Action Risk Classifications

Actions are classified into typed risk categories:

- **`READ`**: Read-only operations that inspect state without modifying the environment.
  - Examples: `browser_read`, `browser_navigate`, `browser_screenshot`, `search_company_files`, `read_company_file`, `document_extract`.
  - **Policy**: `ALLOWED` automatically in all environments.
- **`WRITE`**: Standard state modifications or data-entry operations.
  - Examples: `browser_type`, `browser_click` (normal interactive elements).
  - **Policy**: `ALLOWED` within configured sandboxes (e.g. local Finance Portal).
- **`SENSITIVE`**: High-impact or financial operations that require explicit human verification.
  - Examples: `submit_payment`, `wire_funds`, payment authorization clicks, or actions flagged with sensitive metadata.
  - **Policy**: `REQUIRES_HUMAN`. Execution halts; task transitions to `WAITING_FOR_HUMAN`.
- **`DESTRUCTIVE`**: Irreversible state destruction, data removal, or unpermitted tools.
  - Examples: `delete_record`, `drop_table`, `truncate`, `destroy`, or unknown tool names.
  - **Policy**: `BLOCKED`. Execution is strictly prevented; tool is never invoked.

---

## 5. Human Approval Flow & Resumption

When an action is evaluated as `REQUIRES_HUMAN`:
1. **Execution Halts**: The tool's `execute()` method is **never** called.
2. **Task State Updated**: The pending action is serialized into `task.metadata["pending_action"]`, along with the human intervention reason.
3. **State Transition**: The task transitions to `AgentState.WAITING_FOR_HUMAN` and `TaskStatus.WAITING_FOR_HUMAN`, persisted immediately to SQLite.
4. **Approval API**: An operator reviews the pending action and calls:
   ```python
   runtime.approve_task(task_id, feedback="Approved by Finance Manager")
   ```
5. **Durable Approval**: Memory records a `HUMAN_APPROVAL` audit event and marks `approval_status = "APPROVED"`.
6. **Task Resumption**: Calling `runtime.resume_task(task_id)` detects the approved pending action, executes it, records the observation, and continues the adaptive planning loop until business verification and completion.
7. **Survives Process Restarts**: Because pending actions and approval states are persisted in SQLite, tasks can be approved and resumed even after a complete process crash or server reboot.

---

## 6. Blocked Actions & Adaptive Planning

When an action is evaluated as `BLOCKED`:
1. **Execution Blocked**: The tool is never executed.
2. **Observation Feedback**: A structured failure observation is generated:
   `"Action blocked by policy: Destructive action 'delete_record' is blocked by safety policy."`
3. **Planner Adaptation**: The observation is fed into the planner's bounded history. The agent can reason about the policy restriction and choose a permitted alternative (e.g. read-only lookup).
4. **Loop Protection**: If an agent repeatedly requests the same blocked action, AURA's duplicate action loop detector catches the repeat attempts, prevents infinite cycles, and safely escalates to `TaskStatus.FAILED`.

---

## 7. Operational Audit Logging

Every evaluation produces a structured log entry without exposing hidden internal deliberation:
```
[POLICY] browser_read → READ → ALLOWED
[POLICY] browser_type → WRITE → ALLOWED
[POLICY] submit_payment → SENSITIVE → REQUIRES_HUMAN
[POLICY] delete_record → DESTRUCTIVE → BLOCKED
[APPROVAL] Task <id> approved by human operator.
```
