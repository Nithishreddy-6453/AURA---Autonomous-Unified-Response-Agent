import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.agent.state import AgentState
from backend.memory.base import MemoryStore, TaskRecord
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.plan import Plan
from backend.models.task import Task, TaskStatus


class SQLiteMemoryStore(MemoryStore):
    """SQLite-backed implementation of AURA Task State Persistence and Short-Term Memory."""

    def __init__(self, db_path: Union[str, Path] = "data/aura_memory.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None

        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            # Maintain persistent connection for in-memory DB instances
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes tables and indexes if they do not exist."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON;")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        user_goal TEXT NOT NULL,
                        status TEXT NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata_json TEXT,
                        plan_json TEXT
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS actions (
                        action_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        arguments_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS observations (
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
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS recovery_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS policy_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                    );
                """)

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_task ON actions(task_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_obs_task ON observations(task_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_recovery_task ON recovery_events(task_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_policy_task ON policy_events(task_id);")

                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def create_task(self, task: Task, initial_state: AgentState = AgentState.RECEIVED) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO tasks (task_id, user_goal, status, state, created_at, updated_at, metadata_json, plan_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        user_goal=excluded.user_goal,
                        status=excluded.status,
                        state=excluded.state,
                        updated_at=excluded.updated_at,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        task.task_id,
                        task.user_goal,
                        task.status.value,
                        initial_state.value,
                        task.created_at.isoformat(),
                        now_iso,
                        json.dumps(task.metadata),
                        None,
                    ),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
                task_row = cursor.fetchone()
                if not task_row:
                    return None

                task = Task(
                    task_id=task_row["task_id"],
                    user_goal=task_row["user_goal"],
                    status=TaskStatus(task_row["status"]),
                    created_at=datetime.fromisoformat(task_row["created_at"]),
                    updated_at=datetime.fromisoformat(task_row["updated_at"]),
                    metadata=json.loads(task_row["metadata_json"] or "{}"),
                )

                state = AgentState(task_row["state"])

                plan = None
                if task_row["plan_json"]:
                    plan_data = json.loads(task_row["plan_json"])
                    plan = Plan.model_validate(plan_data)

                # Fetch actions
                cursor.execute(
                    "SELECT * FROM actions WHERE task_id = ? ORDER BY rowid ASC",
                    (task_id,),
                )
                action_rows = cursor.fetchall()
                actions = [
                    Action(
                        action_id=r["action_id"],
                        tool_name=r["tool_name"],
                        arguments=json.loads(r["arguments_json"] or "{}"),
                        status=ActionStatus(r["status"]),
                        retry_count=r["retry_count"],
                    )
                    for r in action_rows
                ]

                # Fetch observations
                cursor.execute(
                    "SELECT * FROM observations WHERE task_id = ? ORDER BY id ASC",
                    (task_id,),
                )
                obs_rows = cursor.fetchall()
                observations = [
                    Observation(
                        action_id=r["action_id"],
                        success=bool(r["success"]),
                        result=json.loads(r["result_json"]) if r["result_json"] else None,
                        error=r["error"],
                        metadata=json.loads(r["metadata_json"] or "{}"),
                    )
                    for r in obs_rows
                ]

                # Fetch recovery events
                cursor.execute(
                    "SELECT * FROM recovery_events WHERE task_id = ? ORDER BY id ASC",
                    (task_id,),
                )
                rec_rows = cursor.fetchall()
                recovery_events = [json.loads(r["event_json"]) for r in rec_rows]

                # Fetch policy events
                cursor.execute(
                    "SELECT * FROM policy_events WHERE task_id = ? ORDER BY id ASC",
                    (task_id,),
                )
                pol_rows = cursor.fetchall()
                policy_events = [json.loads(r["event_json"]) for r in pol_rows]

                return TaskRecord(
                    task=task,
                    state=state,
                    actions=actions,
                    observations=observations,
                    recovery_events=recovery_events,
                    policy_events=policy_events,
                    plan=plan,
                )
            finally:
                if self._mem_conn is None:
                    conn.close()

    def update_task_state(
        self,
        task_id: str,
        state: AgentState,
        status: Optional[TaskStatus] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                if status is not None and metadata is not None:
                    cursor.execute(
                        """
                        UPDATE tasks
                        SET state = ?, status = ?, metadata_json = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (state.value, status.value, json.dumps(metadata), now_iso, task_id),
                    )
                elif status is not None:
                    cursor.execute(
                        """
                        UPDATE tasks
                        SET state = ?, status = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (state.value, status.value, now_iso, task_id),
                    )
                elif metadata is not None:
                    cursor.execute(
                        """
                        UPDATE tasks
                        SET state = ?, metadata_json = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (state.value, json.dumps(metadata), now_iso, task_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE tasks
                        SET state = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (state.value, now_iso, task_id),
                    )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def append_action(self, task_id: str, action: Action) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO actions (action_id, task_id, tool_name, arguments_json, status, retry_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(action_id) DO UPDATE SET
                        status = excluded.status,
                        retry_count = excluded.retry_count,
                        arguments_json = excluded.arguments_json
                    """,
                    (
                        action.action_id,
                        task_id,
                        action.tool_name,
                        json.dumps(action.arguments),
                        action.status.value,
                        action.retry_count,
                        now_iso,
                    ),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def append_observation(self, task_id: str, observation: Observation) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                result_json = json.dumps(observation.result) if observation.result is not None else None
                meta_json = json.dumps(observation.metadata) if observation.metadata else None
                cursor.execute(
                    """
                    INSERT INTO observations (task_id, action_id, success, result_json, error, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        observation.action_id,
                        1 if observation.success else 0,
                        result_json,
                        observation.error,
                        meta_json,
                        now_iso,
                    ),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def append_recovery_event(self, task_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO recovery_events (task_id, event_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (task_id, json.dumps(event), now_iso),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def append_policy_event(self, task_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO policy_events (task_id, event_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (task_id, json.dumps(event), now_iso),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def save_plan(self, task_id: str, plan: Plan) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    UPDATE tasks
                    SET plan_json = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (plan.model_dump_json(), now_iso, task_id),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def get_recent_history(
        self, task_id: str, limit: int = 5
    ) -> Tuple[List[Action], List[Observation]]:
        record = self.get_task(task_id)
        if not record:
            return ([], [])
        recent_actions = record.actions[-limit:] if record.actions else []
        recent_observations = record.observations[-limit:] if record.observations else []
        return (recent_actions, recent_observations)

    def list_tasks(self, limit: int = 20) -> List[TaskRecord]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT task_id FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
                )
                rows = cursor.fetchall()
            finally:
                if self._mem_conn is None:
                    conn.close()

        records = []
        for r in rows:
            rec = self.get_task(r["task_id"])
            if rec:
                records.append(rec)
        return records

    def close(self) -> None:
        with self._lock:
            if self._mem_conn:
                self._mem_conn.close()
                self._mem_conn = None
