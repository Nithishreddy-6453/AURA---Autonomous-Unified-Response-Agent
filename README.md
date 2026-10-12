# AURA — Autonomous Unified Response Agent

**An autonomous AI agent that plans, executes, adapts, recovers, and verifies multi-step workflows across company documents and web applications.**

**Repository:** [AURA — Autonomous Unified Response Agent](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent)

AURA is a task-execution prototype built to demonstrate how an AI agent can take a natural-language goal, select appropriate tools, interact with local business applications, handle errors, request human approval for sensitive actions, and verify whether the intended outcome was actually achieved.

Rather than relying solely on an LLM's final response, AURA combines adaptive planning, browser automation, policy enforcement, persistent task memory, error recovery, and independent verification.

The project uses local Finance and HR sandbox applications with synthetic development data.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture](#architecture)
- [Core Subsystems](#core-subsystems)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Running AURA](#running-aura)
- [Example Workflows](#example-workflows)
- [Safety and Human Approval](#safety-and-human-approval)
- [Testing](#testing)
- [Important Design Decisions](#important-design-decisions)
- [Assumptions](#assumptions)
- [Known Limitations](#known-limitations)
- [Future Improvements](#future-improvements)
- [Documentation](#documentation)
- [Project Status](#project-status)

---

## Key Features

- **Goal-driven autonomy:** Accepts natural-language goals and uses an LLM planner to select tools and subsequent actions.
- **Adaptive execution:** Uses observations from previous actions to decide what to do next.
- **Browser automation:** Uses Playwright to interact with web applications, navigate pages, fill forms, click controls, and inspect visible content.
- **Centralized safety policies:** Evaluates actions before execution, blocks prohibited operations, and requires human approval for sensitive actions.
- **Error recovery:** Classifies failures and applies suitable recovery strategies, including correcting invalid data, retrying, resetting browser state, or escalating.
- **Persistent task memory:** Stores task state, actions, observations, recovery events, and policy decisions in SQLite.
- **Independent verification:** Checks actual application state instead of assuming that a successful browser action proves that the requested outcome occurred.
- **Operations console:** Provides task submission, execution timelines, task history, status visibility, and a human-approval interface.
- **Multiple task domains:** Demonstrates workflows across Finance and HR sandbox applications.

---

## Architecture

### Architectural Flow

```text
                   User Goal
                       |
                       v
                 Task Creation
                   (UUID)
                       |
                       v
              Adaptive LLM Planner
                       |
                       v
                Proposed Action
                       |
                       v
              Action Policy Engine
                       |
          +------------+------------+
          |            |            |
          v            v            v
       ALLOWED     REQUIRES      BLOCKED
                    HUMAN
          |            |            |
          |            v            v
          |       Await Approval   Prevent
          |            |          Execution
          |            v            |
          |       Resume Task       v
          |            |         Observation
          +------------+------------+
                       |
                       v
                  Tool Execution
                       |
                       v
                   Observation
                       |
                       v
                Adaptive Recovery
                       |
                       v
              Independent Verification
                       |
             +---------+---------+
             |                   |
             v                   v
       Verified Success     Failure / Escalation
             |                   |
             +---------+---------+
                       |
                       v
             Persist Final Task State
```

### System Components

```text
AURA
|
|-- frontend/
|   `-- Control Center
|
|-- backend/
|   |-- api/             FastAPI gateway
|   |-- agent/           Planner, runtime, and task orchestration
|   |-- policy/          Action authorization and safety enforcement
|   |-- memory/          Task persistence and memory interfaces
|   |-- tools/           Document and browser tools
|   |-- recovery/        Failure classification and recovery
|   `-- verification/    Independent outcome verification
|
|-- company/
|   |-- finance/         Finance sandbox application
|   `-- hr/              HR sandbox application
|
|-- data/
|   |-- company/         Synthetic company documents and fixtures
|   `--                 Local development data
|
|-- tests/               Automated tests and regression coverage
|
`-- docs/                Architecture and implementation documentation
```

---

## Core Subsystems

### 1. Agent Core and Runtime

**Location:** `backend/agent/`

The agent runtime orchestrates the task lifecycle, invokes the planner, dispatches approved actions, records observations, and continues execution until the task reaches a terminal state.

Key responsibilities include:

- Creating and tracking tasks with unique identifiers.
- Executing an adaptive observation-grounded loop.
- Enforcing execution budgets and duplicate-action safeguards.
- Managing task states, including execution, verification, approval, and failure.
- Resuming tasks after human approval.
- Producing completion summaries consistent with the verification outcome.

Pydantic models provide structured representations for tasks, actions, plans, and observations.

### 2. Safety, Permissions, and Policy Enforcement

**Location:** `backend/policy/`

The centralized policy engine evaluates proposed actions independently of the LLM planner.

Depending on the action and applicable rules, an operation may be allowed, require human approval, or be blocked.

The policy system distinguishes risk levels such as:

- `READ`
- `WRITE`
- `SENSITIVE`
- `DESTRUCTIVE`

The exact decision depends on the registered tool, action arguments, domain rules, and task context.

This separation is important because the LLM proposes actions, while the policy engine determines whether those actions may execute.

### 3. Task Memory and Persistence

**Location:** `backend/memory/`

AURA uses a `MemoryStore` interface with a durable local SQLite implementation.

The memory layer records task lifecycles, action results, observations, state transitions, recovery events, and policy audit information.

Persisted state supports task-history inspection and recovery of non-terminal tasks. Terminal task states are preserved rather than blindly replaying completed actions.

### 4. Company Document Tools

**Location:** `backend/tools/`

AURA provides tools for working with synthetic company data:

- `search_company_files`
- `read_company_file`
- `document_extract`

These tools allow the planner to find relevant source documents, read their contents, and extract structured information.

Static company documents and live application state are treated as distinct sources of information. When a goal requests current portal status, the agent should inspect the live application rather than relying solely on a potentially outdated document.

### 5. Browser Automation

**Location:** `backend/tools/browser/`

AURA uses Playwright to control a browser and interact with permitted local web applications.

The browser tool layer includes:

- `browser_navigate`
- `browser_click`
- `browser_type`
- `browser_read`
- `browser_screenshot`

Navigation observations include page information intended to help the planner evaluate the destination and its visible content.

Browser actions can fail because of validation errors, missing elements, incorrect selectors, navigation problems, or unexpected page states. Such failures should be handled through the recovery system rather than treated as successful outcomes.

The local development configuration supports visible browser execution. On Windows, run the backend in an interactive terminal when you want to observe the Playwright-controlled browser window.

Browser access is restricted by the project's URL and sandbox security rules.

### 6. Adaptive Re-planning and Recovery

**Location:** `backend/recovery/`

When a tool fails, AURA observes the failure, classifies it, and determines an appropriate response.

Failure categories include:

- `VALIDATION`
- `TRANSIENT`
- `NAVIGATION_STATE`
- `DUPLICATE`
- `UNKNOWN`

Recovery strategies include:

- `CORRECT_DATA`
- `RETRY`
- `RESET_AND_RETRY`
- `ESCALATE`

For example, when Finance rejects an invoice submission because a required date is missing, AURA can observe the validation error, correct the missing field, and retry the submission.

Recovery is bounded by the runtime's execution safeguards. If a safe recovery is not available, the agent should fail or request intervention instead of repeatedly performing the same unsuccessful action.

### 7. Independent Verification

**Location:** `backend/verification/`

AURA has independent verification components for the sandbox workflows.

For Finance, `FinanceInvoiceVerifier` queries the Finance API and compares the persisted invoice record with its source data.

For HR, `HROnboardingVerifier` distinguishes between read-only inspection and tasks that actually request onboarding completion.

The objective is to verify the requested outcome using application state rather than relying solely on a browser action's success response or an LLM-generated completion summary.

A task should report success only when its applicable verification requirements pass.

### 8. AURA Control Center

**Location:** `frontend/`

The Control Center is a Next.js, TypeScript, and Tailwind CSS operations interface.

It provides:

- Natural-language task submission.
- Finance and HR domain selection.
- Active task status and execution timeline.
- Action and observation inspection.
- Recent task history.
- Human approval and rejection controls.
- Visibility into task completion and failure.

The Control Center communicates with the FastAPI backend, which orchestrates background task execution.

---

## Technology Stack

| Area | Technology |
|---|---|
| Agent runtime | Python |
| Backend API | FastAPI |
| Data validation | Pydantic |
| Task persistence | SQLite |
| Browser automation | Playwright |
| Local language model runtime | Ollama |
| Development model | `qwen2.5-coder:7b` |
| Control Center | Next.js |
| Frontend language | TypeScript |
| Frontend styling | Tailwind CSS |
| Sandbox applications | Next.js and Node.js |
| Automated testing | Python `unittest`, Playwright frontend tests |
| Version control | Git and GitHub |

The configured model is used through the local Ollama runtime. The setup described below reflects the local development environment; alternative model providers would require the corresponding implementation and configuration.

---

## Prerequisites

Install the following before running the complete prototype:

- Windows and PowerShell for the documented commands.
- Python installed and available from the terminal.
- Node.js and npm.
- Git.
- Ollama with the configured development model available.
- The project’s Python and Node.js dependencies.

The standard local development ports are:

| Service | Address |
|---|---|
| Finance Portal | http://localhost:3000/finance |
| AURA Control Center | http://localhost:3001 |
| HR Portal | http://localhost:3002/hr |
| FastAPI backend | http://127.0.0.1:8000 |
| Ollama API | http://127.0.0.1:11434 |

Ensure these ports are available before starting the services.

---

## Installation and Setup

### 1. Clone the repository

```powershell
git clone https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent.git

cd AURA---Autonomous-Unified-Response-Agent
```

### 2. Set up the Python environment

Create the virtual environment if it does not already exist:

```powershell
py -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install backend dependencies using the dependency manifest included with the repository. If the repository root contains `requirements.txt`, run:

```powershell
python -m pip install -r requirements.txt
```

If PowerShell does not allow virtual-environment activation, invoke Python directly using:

```powershell
.\.venv\Scripts\python.exe
```

### 3. Set up Ollama

Install Ollama and ensure the configured model is available locally:

```powershell
ollama pull qwen2.5-coder:7b
```

Check the installed model:

```powershell
ollama list
```

Ensure the Ollama service is running before submitting autonomous tasks.

### 4. Set up the Finance Portal

Open a separate PowerShell terminal:

```powershell
cd company/finance

npm install
```

Build the application:

```powershell
npm run build
```

### 5. Set up the Control Center

Open another terminal from the repository root:

```powershell
cd frontend

npm install
npm run build
```

Keep each application in its own terminal so that service logs and errors can be inspected separately.

---

## Running AURA

Start the services in separate PowerShell terminals and leave each running while using AURA.

### Terminal 1 — Finance Portal

```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent\company\finance

npm run start
```

Open http://localhost:3000/finance

### Terminal 2 — HR Sandbox

From the repository root:

```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent

node company/hr/standalone_server.mjs
```

Open http://localhost:3002/hr

### Terminal 3 — Ollama

Ensure the Ollama service is running and the configured model is available. If Ollama is already running as a background service, do not start a duplicate instance.

The default local API endpoint is:

```text
http://127.0.0.1:11434
```

### Terminal 4 — AURA Backend

From the repository root:

```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent

.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Check the health endpoint:

http://127.0.0.1:8000/health

Keep the terminal open while executing tasks. On Windows, running the backend from an interactive terminal allows headed Playwright browser windows to appear visibly during browser automation.

Do not start another backend process on port `8000` while one is already running. If the port is occupied, inspect the existing process before attempting a restart.

### Terminal 5 — AURA Control Center

```powershell
cd C:\SAMPLEWEBSITE\centrai\aura-agent\frontend

npm run start
```

Open http://localhost:3001

Once all services are running, select a domain, submit a natural-language goal, and observe the task timeline.

---

## Example Workflows

### Example 1: Finance Invoice Entry

**Goal:**

> Find the latest Acme invoice and enter its amount into the Finance Portal.

Expected execution sequence:

1. Search the company invoice documents.
2. Read the relevant source invoice.
3. Extract the required invoice fields.
4. Navigate to the Finance Portal.
5. Populate the invoice form.
6. Submit the form.
7. Observe and recover from validation errors, if necessary.
8. Verify the saved record using the Finance API and independent verifier.
9. Report success only after verification passes.

During development, AURA was tested with the synthetic invoice `INV-2026-0095`, for Acme Corp, with an amount of USD 19,116.00. The reported live test successfully saved and independently verified the record.

### Example 2: Read-only HR Inspection

**Goal:**

> Inspect the current live HR Portal and report the details of employee HR-TEST-1001.

Expected execution sequence:

1. Navigate to the HR Portal dashboard.
2. Locate the employee row.
3. Read the actual displayed employee information.
4. Report the name, department, start date, overall status, and visible checklist information.
5. Avoid all record modifications.

A successful manual test inspected the live employee row for HR-TEST-1001, Alex Morgan, in Engineering, with a start date of April 1, 2026. The overall status displayed by the portal was `COMPLETED`.

The dashboard showed the checklist item names but did not expose each item's individual completion status in that table. AURA should report that limitation rather than assume the individual items are complete.

### Example 3: Human Approval and Safe Resumption

When an action is classified as sensitive, AURA can pause execution and request human approval.

After approval, the pending action is resumed and execution continues under the same policy controls.

Rejecting an action should stop that operation rather than bypassing the policy system.

---

## Safety and Human Approval

Safety enforcement is an essential part of AURA's architecture.

The system is designed to:

- Evaluate proposed actions before executing tools.
- Block prohibited or unregistered actions.
- Require human approval for applicable sensitive operations.
- Persist approval information and pending actions.
- Resume approved actions through the runtime.
- Prevent explicit read-only HR tasks from invoking onboarding finalization or other prohibited modifications.
- Preserve failure and verification results in the task state.

The Finance and HR applications are local sandbox environments with synthetic data. This project is not intended to authorize unrestricted actions on real company systems.

Human approval should be treated as an authorization boundary, not as a substitute for independent verification.

---

## Testing

### Run the complete Python test suite

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

### Run Finance persistence regression tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_finance_persistence_regression
```

These tests cover invoice validation failures, missing-record verification, and successful invoice persistence.

### Run browser-navigation regression tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_browser_navigation_validation
```

### Run HR workflow regression tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_hr_workflow_regression
```

### Run the existing HR pilot tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_hr_domain_pilot
```

### Run frontend tests

```powershell
cd frontend

npm test
```

The latest reported full Python test run during development completed with **195 tests passing and zero failures or errors**. The reported run included the Finance persistence, browser-navigation, and HR workflow regression coverage.

Test results can change after further modifications. Rerun the relevant commands against the exact version being evaluated.

---

## Important Design Decisions

### 1. Separate Planning from Policy Enforcement

The LLM determines which action appears useful for achieving a goal. The centralized policy engine independently evaluates whether that action can be executed.

This avoids making the planner the sole authority over permissions and safety.

### 2. Use Observations to Drive Re-planning

Each tool execution generates an observation. The planner can use the observation to select the next action or adapt to unexpected conditions.

This makes error handling part of the task execution loop rather than simply returning a failure message.

### 3. Verify Persisted State Independently

A browser click returning success does not necessarily mean that a business operation succeeded.

AURA's Finance verifier queries the persisted invoice through the application API and compares it against the source document. This reduces dependence on UI feedback and LLM-generated claims.

### 4. Preserve Task State and Approval History

SQLite persistence records the task lifecycle, observations, actions, and policy decisions.

This supports debugging, task-history inspection, and controlled resumption without blindly replaying every earlier action.

### 5. Distinguish Read-only Inspection from Mutation

An inspection task and an onboarding-completion task have different intended outcomes.

The verifier and policy rules should reflect that difference: a read-only HR task can succeed while an employee remains `PENDING`, whereas a task explicitly requesting onboarding completion must verify the required final state.

---

## Assumptions

AURA is developed under the following assumptions:

1. Finance and HR are local sandbox applications intended for testing and demonstrations.
2. Company documents and employee records use synthetic development data.
3. The configured local LLM is available through Ollama.
4. The LLM planner may make incorrect decisions or propose invalid selectors, so tool results, policy enforcement, recovery, and verification remain necessary.
5. The live application's state is authoritative when a task requests the current portal status.
6. Sensitive business actions require the appropriate policy decision and human approval.
7. The current implementation is a prototype and is not a substitute for production-grade enterprise identity management, permission administration, monitoring, or operational safeguards.

---

## Known Limitations

- **Model-dependent planning:** Tool selection and action arguments can vary with model output and the observations provided to the planner.
- **Browser locator fragility:** Changes in page structure, accessible names, selectors, or navigation behavior can cause tool failures.
- **Local application assumptions:** Several workflows depend on the URLs and structures of the local Finance and HR sandbox applications.
- **HR checklist visibility:** The dashboard displays checklist item names, but individual completion states are not displayed in the employee table.
- **Static document freshness:** Source documents may become stale relative to live application state. Live inspection is required when the user asks for current status.
- **Human approval overhead:** Sensitive operations can pause until a person approves or rejects the pending action.
- **Local service requirements:** The backend, sandbox applications, and configured model must be available for complete end-to-end workflows.
- **Production readiness:** The current project has been validated in a controlled local development environment. Broader integration testing, security review, observability, concurrency testing, and failure testing would be necessary before production use.

---

## Future Improvements

If more development time were available, the next priorities would be:

1. Improve robust page understanding and selector discovery so that minor UI changes do not unnecessarily interrupt execution.
2. Represent checklist items as structured data with independent completion states in the HR sandbox.
3. Expand isolated end-to-end tests for Finance and HR, including negative cases and recovery after partial failure.
4. Improve task-state synchronization and frontend refresh behavior.
5. Add structured telemetry and clearer diagnostics for planner decisions, policy outcomes, verification failures, and retries.
6. Improve configuration management and environment validation.
7. Explore additional sandbox domains while retaining the same runtime, policy engine, memory, and verification architecture.

---

## Documentation

Detailed implementation documentation is available in the repository:

- [Browser Automation Architecture — Phase 1](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent/blob/main/docs/browser_automation.md)
- [Adaptive Observation and Re-planning — Phase 2](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent/blob/main/docs/adaptive_planning.md)
- [Task State Persistence and Short-term Memory — Phase 3](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent/blob/main/docs/memory.md)
- [Safety, Permissions, and Policy Enforcement — Phase 4](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent/blob/main/docs/security_and_permissions.md)
- [AURA Control Center — Phase 5](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent/blob/main/docs/control_center.md)

---

## Project Status

AURA is an actively developed autonomous task-execution prototype.

The implementation demonstrates goal-driven planning, document and browser tools, centralized policy enforcement, human approval, adaptive recovery, persistent task state, and independent verification across local Finance and HR applications.

The reported development test suite has passed, and manual testing has demonstrated Finance invoice persistence and read-only HR dashboard inspection.

The project remains a prototype with the limitations described above. Its purpose is to demonstrate the engineering principles of an agent that does actual work, responds to failures, respects authorization boundaries, and verifies results before reporting success.

**Repository:** [Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent](https://github.com/Nithishreddy-6453/AURA---Autonomous-Unified-Response-Agent)
