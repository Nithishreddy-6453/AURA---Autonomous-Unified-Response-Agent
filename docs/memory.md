# AURA Task State Persistence & Short-Term Agent Memory

Phase 3 introduces durable task state persistence and bounded short-term memory to the AURA architecture.

---

## 1. Why AURA Needs Memory

In enterprise workflows, agents perform multi-step operations that interact with physical documents, file systems, remote APIs, and interactive browser applications. Without memory:
1. **No Resiliency Against Crashes/Interruptions**: If a process crashes, disconnects, or hits a timeout mid-task, all progress and discovered facts are lost, requiring restarting from scratch.
2. **Loss of Operational Context**: Without tracking what actions already occurred, agents cannot distinguish whether an input field is empty because it was never filled or because a submission cleared it.
3. **Auditability & Traceability**: Enterprise compliance requires recording what tool actions were taken, what observations were returned, what failures were detected, and which recovery policies were executed.

Memory decouples the agent's life cycle from ephemeral in-memory variables and provides durable persistence across restarts.

---

## 2. Architectural Flow with Memory

```
User Goal
  │
  ▼
Task (UUID) ──────────────────────────► MemoryStore (SQLite)
  │                                           ▲
  ▼                                           │
Agent Runtime (Lifecycle Controller)          │ [records task, state, actions,
  │                                           │  observations, recovery events]
  ├──► Action (Executed via Tool) ────────────┤
  │                                           │
  ├──► Observation (Structured Result) ───────┤
  │                                           │
  └──► Bounded Short-Term Memory ─────────────┘
         │ (recent N steps)
         ▼
       Planner (Next Action / Completion Decision)
         │
         ▼
       Next Action / Verifier / Terminal State
```

---

## 3. Task State vs. Planner Context

A critical architectural distinction is preserved in Phase 3:

| Concept | Scope | Responsibility |
| :--- | :--- | :--- |
| **Task State / Memory** | Global, Durable | Complete history of the task stored in SQLite: all actions, observations, timestamps, state transitions, and recovery events. Never pruned. |
| **Planner Context** | Local, Bounded | Bounded short-term window (default `limit=5`) passed to the LLM step reasoner. Only contains recent actions, recent observations, recovery guidance, and the active goal. |

**Why Bounded Context Still Matters**:
- LLMs suffer from performance degradation, latency spikes, and hallucination ("lost in the middle") when fed unbounded historical logs.
- Memory persistence and LLM prompt context are fundamentally separate concerns: the database remembers everything; the planner reasons over the bounded recent horizon.

---

## 4. What Gets Persisted vs. What Does NOT

### What Gets Persisted:
- **Task Identifiers & Metadata**: UUID task ID, user goal, creation/update timestamps (ISO 8601 UTC), metadata dictionary.
- **State & Status**: `AgentState` transitions (`RECEIVED`, `UNDERSTANDING`, `PLANNING`, `EXECUTING`, `OBSERVING`, `ADAPTING`, `VERIFYING`, `COMPLETED`, `FAILED`, `NEEDS_HUMAN`) and `TaskStatus`.
- **Action Records**: Tool name, structured arguments (JSON), status (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`), retry count, timestamp.
- **Observation Records**: Structured return value (JSON), success boolean, error message, structured metadata.
- **Recovery Events**: Failure classification, recovery policy (`RETRY`, `CORRECT_DATA`, `ESCALATE`), source tool name.
- **Plans**: High-level decomposed action sequences and plan IDs.

### What Does NOT Get Persisted (Memory Safety):
- **Raw Browser Session Handles**: Playwright browser instances, browser contexts, page handles, and event listeners.
- **Massive Raw HTML Dumps**: Only structured extracted text or targeted DOM summaries.
- **Authentication Secrets & Passwords**: Credentials and secrets are never committed to task memory logs.
- **Chain-of-Thought / Internal Prompt Scaffolding**: Raw LLM internal deliberation is not saved in persistent records.

---

## 5. Memory Interface (`MemoryStore`)

The persistence layer is isolated behind a clean abstract interface, decoupling `AgentRuntime` from database engines:

```python
class MemoryStore(ABC):
    @abstractmethod
    def create_task(self, task: Task, initial_state: AgentState) -> None: ...
    @abstractmethod
    def get_task(self, task_id: str) -> Optional[TaskRecord]: ...
    @abstractmethod
    def update_task_state(self, task_id: str, state: AgentState, status: Optional[TaskStatus] = None, metadata: Optional[Dict[str, Any]] = None) -> None: ...
    @abstractmethod
    def append_action(self, task_id: str, action: Action) -> None: ...
    @abstractmethod
    def append_observation(self, task_id: str, observation: Observation) -> None: ...
    @abstractmethod
    def append_recovery_event(self, task_id: str, event: Dict[str, Any]) -> None: ...
    @abstractmethod
    def save_plan(self, task_id: str, plan: Plan) -> None: ...
    @abstractmethod
    def get_recent_history(self, task_id: str, limit: int = 5) -> Tuple[List[Action], List[Observation]]: ...
    @abstractmethod
    def list_tasks(self, limit: int = 20) -> List[TaskRecord]: ...
```

---

## 6. Storage Implementation: SQLite

The initial implementation uses Python's standard `sqlite3` without external infrastructure (no Postgres, Redis, or vector DBs):

### Database Schema:
```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    user_goal TEXT NOT NULL,
    status TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT,
    plan_json TEXT
);

CREATE TABLE actions (
    action_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    success INTEGER NOT NULL,
    result_json TEXT,
    error TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE TABLE recovery_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX idx_actions_task ON actions(task_id);
CREATE INDEX idx_obs_task ON observations(task_id);
CREATE INDEX idx_recovery_task ON recovery_events(task_id);
```

- Tables and indexes are created automatically on initialization if they do not exist.
- Supports file-backed persistence (`data/aura_memory.db`) or transient in-memory instances (`:memory:`) for test isolation.

---

## 7. Task Resume Semantics

### Non-Terminal Task Resume:
When `runtime.resume_task(task_id)` is called:
1. `MemoryStore` loads the task record, existing actions, and observations.
2. The runtime restores `current_task`, `executed_actions`, and `observations`.
3. If the previous observation ended in an error, `recovery_context` is restored with guidance.
4. The runtime enters `AgentState.ADAPTING` and continues the adaptive execution loop starting at `steps_taken = len(record.actions)`.
5. **No Blind Replay**: The agent does NOT re-execute already completed actions; the Planner uses recent memory to decide the *next* logical step.

### Terminal Tasks:
- `COMPLETED`: Remains completed. Does not restart automatically.
- `FAILED`: Preserves failure error message and metadata.
- `WAITING_FOR_HUMAN` / `NEEDS_HUMAN`: Preserves human intervention reason for operator review.

---

## 8. Concise Lifecycle Logging

Runtime logs standardized memory events:
- `[TASK] created <id>`
- `[MEMORY] action persisted`
- `[MEMORY] observation persisted`
- `[MEMORY] state -> <STATE>`
- `[MEMORY] recovery event persisted`
- `[RESUME] loading task <id>`
