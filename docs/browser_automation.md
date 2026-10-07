# AURA Browser Automation Layer (Phase 1)

## Overview

The browser automation layer provides AURA with controlled, sandboxed web interaction capabilities using Playwright. It bridges natural-language goals reasoned by the LLM with real DOM actions on web applications (such as the internal Finance Portal), returning structured observations back to the agent loop.

---

## Architectural Principles

AURA strictly separates cognitive reasoning from execution mechanics:

| Component | Role | Responsibility |
| :--- | :--- | :--- |
| **LLM** | Reasoning | Interprets user goals, synthesizes state, and formulates plans. |
| **Planner** | Decision Engine | Validates available tools, formulates action parameters, and plans transitions. |
| **Tool** | Controlled Capability | Abstract, validated interface registered in `ToolRegistry`. No direct LLM calls inside tools. |
| **Playwright** | Execution Mechanism | Interacts with the real headless browser/DOM. Kept strictly behind tool abstractions. |
| **Observation** | Grounded Evidence | Structured evidence returned to runtime/planner detailing outcome, DOM state, or errors. |
| **Recovery** | Failure Handler | Classifies tool and verification failures (transient, validation, not found) to choose recovery policies. |
| **Verifier** | Independent Confirm | Bypasses UI to inspect API/database state, confirming genuine business outcomes. |

Playwright is **never** the agent itself; it is purely an execution substrate executing single, bounded tool instructions.

---

## Why Playwright Exists in AURA

Modern enterprise workflows (e.g., invoice processing, CRM updates, compliance approvals) interact with web applications. Playwright provides:
1. **Deterministic DOM automation**: Reliable waiting, event dispatching, and form manipulation.
2. **Robust headless execution**: Runs in local and CI environments without overhead.
3. **Session persistence**: Reuses a single browser session across multi-step agent tasks.
4. **Sandboxed control**: Keeps browser automation bounded within whitelisted hosts (`localhost:3000`) and local test fixtures, prohibiting arbitrary code execution.

---

## Browser Session Management (`BrowserSession`)

Located in [`backend/tools/browser/browser_session.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_session.py):
- Manages Chromium lifecycle via Playwright.
- Reuses the same `BrowserContext` and `Page` across all actions in a task to maintain form state and cookies.
- Configurable headless mode via `BROWSER_HEADLESS` or constructor.
- Provides explicit lifecycle controls (`get_page()`, `close()`) and async context manager (`async with BrowserSession() as session:`).

---

## Registered Browser Tools

Each tool inherits from the base [`Tool`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/base.py) class and returns a structured [`Observation`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/models/observation.py).

### 1. `browser_navigate`
- **Location**: [`backend/tools/browser/browser_navigate.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_navigate.py)
- **Schema**: `{"url": string}` (Required)
- **Functionality**: Validates URL against security whitelist (`localhost:3000`, local test files). Navigates until DOM is loaded and returns status code, title, and current URL.

### 2. `browser_click`
- **Location**: [`backend/tools/browser/browser_click.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_click.py)
- **Schema**: Supports `selector` (CSS), `text` (visible label), `role` (accessible role), and `target`.
- **Functionality**: Locates element, waits for visibility, clicks, and returns updated URL and title. Never silently swallows failures.

### 3. `browser_type`
- **Location**: [`backend/tools/browser/browser_type.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_type.py)
- **Schema**: `{"text": string}` (Required), `{"selector": string}` or `{"target": string}`
- **Functionality**: Fills text into target inputs. Safely formats HTML5 date inputs (`input[type="date"]`) and dispatches synthetic change/input events for modern React/Next.js controlled components. Prohibits arbitrary JavaScript execution.

### 4. `browser_read`
- **Location**: [`backend/tools/browser/browser_read.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_read.py)
- **Schema**: `{"selector": string}` (Optional), `{"max_elements": integer}` (Optional)
- **Functionality**: Returns bounded, structured page information: current URL, page title, visible text summary (<2000 chars), and interactive controls. If a `selector` is provided, reads bounded inner text from that container. Never dumps unlimited raw HTML.

### 5. `browser_screenshot`
- **Location**: [`backend/tools/browser/browser_screenshot.py`](file:///c:/SAMPLEWEBSITE/centrai/aura-agent/backend/tools/browser/browser_screenshot.py)
- **Schema**: `{"name": string}` (Optional)
- **Functionality**: Captures visual proof-of-work saved under `artifacts/` for auditability and verification.

---

## Tool Registration & Dynamic Flow

```
Agent Task Received
        │
        ▼
ToolRegistry (`backend/tools/registry.py`)
  ├── search_company_files
  ├── read_company_file
  ├── document_extract
  ├── browser_navigate
  ├── browser_read
  ├── browser_click
  └── browser_type
        │
        ▼ (get_tool_specs())
Planner / LLM Context (Receives schemas dynamically)
        │
        ▼ (Action Decision)
AgentRuntime (`backend/agent/runtime.py`)
        │
        ▼
Browser Tool (`execute(**action.arguments)`)
        │
        ▼
Playwright Chromium Page
        │
        ▼
Observation (`backend/models/observation.py`)
  ├── success: true/false
  ├── result: {...}
  └── error: string | null
        │
        ▼
Agent Observation Memory -> Informs Next Planner Step
```

The Planner never hard-codes tool definitions; it receives tool specifications purely through `ToolRegistry.get_tool_specs()`.

---

## Error Handling & Security

- **Sandboxed Navigation**: Reject all external domains (`google.com`, `malicious.com`) and unauthorized ports.
- **No Arbitrary Execution**: No arbitrary JavaScript evaluation, no arbitrary shell execution, no arbitrary filesystem access.
- **Graceful Error Observations**: Timeouts, missing selectors, or invalid navigation destinations produce `Observation(success=False, error=...)` without crashing the agent process.
