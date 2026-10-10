// Standalone zero-dependency Node HTTP server for HR Onboarding Sandbox (Port 3002)
import http from "node:http";
import { URL } from "node:url";

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 3002;

const SEED_ONBOARDINGS = [
  {
    employee_id: "HR-TEST-1001",
    name: "Alex Morgan",
    department: "Engineering",
    start_date: "2026-04-01",
    role: "Platform Engineer",
    checklist: ["Security Background Check", "Laptop Provisioning", "System Access"],
    status: "PENDING",
    notes: "Awaiting hardware provisioning and system setup.",
    created_at: "2026-03-25T08:00:00Z",
    updated_at: "2026-03-25T08:00:00Z",
  },
  {
    employee_id: "EMP-091",
    name: "Alex Chen",
    department: "Core Engineering",
    start_date: "2026-04-01",
    role: "Senior Software Engineer",
    checklist: ["Security Background Check", "Laptop Provisioning", "GitHub & Cloud Access"],
    status: "PENDING",
    notes: "Candidate starting April 2026.",
    created_at: "2026-03-20T10:00:00Z",
    updated_at: "2026-03-20T10:00:00Z",
  },
  {
    employee_id: "HR-TEST-1002",
    name: "Jordan Lee",
    department: "Product",
    start_date: "2026-04-10",
    role: "Product Manager",
    checklist: ["Security Background Check", "Welcome Session Scheduled"],
    status: "PENDING",
    notes: "Direct report to VP Product.",
    created_at: "2026-03-22T09:30:00Z",
    updated_at: "2026-03-22T09:30:00Z",
  },
  {
    employee_id: "HR-TEST-1003",
    name: "Taylor Swift",
    department: "Design",
    start_date: "2026-03-15",
    role: "Lead UI Designer",
    checklist: ["Security Background Check", "Figma Licenses", "Laptop Provisioning", "Benefits Enrolled"],
    status: "COMPLETED",
    notes: "All onboarding steps completed successfully.",
    created_at: "2026-03-10T11:00:00Z",
    updated_at: "2026-03-15T16:00:00Z",
  },
];

let store = new Map();
function resetStore() {
  store.clear();
  for (const item of SEED_ONBOARDINGS) {
    store.set(item.employee_id.toUpperCase(), { ...item });
  }
}
resetStore();

function renderDashboardHtml(records) {
  const rows = records.map(r => `
    <tr style="border-bottom: 1px solid #1e293b;">
      <td style="padding: 12px 16px; font-family: monospace; color: #818cf8;">${r.employee_id}</td>
      <td style="padding: 12px 16px; font-weight: bold; color: #fff;">${r.name}</td>
      <td style="padding: 12px 16px; color: #cbd5e1;">${r.department}</td>
      <td style="padding: 12px 16px; font-family: monospace; color: #94a3b8;">${r.start_date}</td>
      <td style="padding: 12px 16px; font-size: 12px; color: #94a3b8;">${(r.checklist || []).join(", ")}</td>
      <td style="padding: 12px 16px;">
        <span style="padding: 4px 8px; border-radius: 9999px; font-size: 11px; font-weight: bold; background: ${r.status === 'COMPLETED' ? '#064e3b; color: #34d399' : '#1e293b; color: #94a3b8'};">
          ${r.status}
        </span>
      </td>
    </tr>
  `).join("");

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>HR Onboarding Portal</title>
  <style>
    body { background: #020617; color: #f8fafc; font-family: system-ui, sans-serif; margin: 0; padding: 40px; }
    .container { max-width: 1000px; margin: 0 auto; }
    .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 20px; margin-bottom: 30px; }
    .btn { background: #4f46e5; color: #fff; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: 500; }
    table { width: 100%; border-collapse: collapse; background: #0f172a; border-radius: 8px; overflow: hidden; border: 1px solid #1e293b; }
    th { text-align: left; padding: 14px 16px; background: #020617; color: #94a3b8; font-size: 12px; text-transform: uppercase; border-bottom: 1px solid #1e293b; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 style="margin: 0; font-size: 24px;">HR Onboarding Portal</h1>
        <p style="margin: 6px 0 0 0; color: #94a3b8; font-size: 13px;">AURA Pilot Sandbox (Port 3002)</p>
      </div>
      <a href="/hr/onboarding/new" id="new-onboarding-link" class="btn">+ New Onboarding Request</a>
    </div>
    <table>
      <thead>
        <tr>
          <th>Employee ID</th>
          <th>Name</th>
          <th>Department</th>
          <th>Start Date</th>
          <th>Checklist</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  </div>
</body>
</html>`;
}

function renderFormHtml() {
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Process Onboarding - HR Portal</title>
  <style>
    body { background: #020617; color: #f8fafc; font-family: system-ui, sans-serif; margin: 0; padding: 40px; }
    .container { max-width: 600px; margin: 0 auto; }
    .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px; }
    .card { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 24px; }
    label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; color: #94a3b8; margin-bottom: 6px; }
    input[type="text"], select { width: 100%; box-sizing: border-box; background: #020617; border: 1px solid #334155; border-radius: 6px; padding: 10px 12px; color: #fff; font-size: 14px; margin-bottom: 16px; }
    .btn { background: #4f46e5; color: #fff; padding: 12px 20px; border-radius: 6px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; width: 100%; }
    .banner { padding: 12px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; display: none; }
    .success { background: #064e3b; border: 1px solid #059669; color: #6ee7b7; }
    .error { background: #881337; border: 1px solid #e11d48; color: #fda4af; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 style="margin: 0; font-size: 20px;">Process Onboarding Request</h1>
        <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 12px;">Fill in candidate details and checklist</p>
      </div>
      <a href="/hr" style="color: #818cf8; text-decoration: none; font-size: 13px;">← Back</a>
    </div>

    <div id="success-banner" class="banner success"></div>
    <div id="error-banner" class="banner error"></div>

    <form id="onboarding-form" class="card">
      <label for="employee_id">Employee ID *</label>
      <input type="text" id="employee_id" name="employee_id" required placeholder="e.g. HR-TEST-1001" />

      <label for="name">Full Name *</label>
      <input type="text" id="name" name="name" required placeholder="e.g. Alex Morgan" />

      <label for="department">Department *</label>
      <input type="text" id="department" name="department" required placeholder="e.g. Engineering" />

      <label for="start_date">Start Date *</label>
      <input type="text" id="start_date" name="start_date" required value="2026-04-01" />

      <label for="status">Onboarding Status</label>
      <select id="status" name="status">
        <option value="COMPLETED">COMPLETED</option>
        <option value="IN_PROGRESS">IN_PROGRESS</option>
        <option value="PENDING">PENDING</option>
      </select>

      <button type="submit" id="finalize-onboarding-btn" class="btn">Finalize Onboarding</button>
    </form>
  </div>

  <script>
    document.getElementById('onboarding-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const employee_id = document.getElementById('employee_id').value.trim();
      const name = document.getElementById('name').value.trim();
      const department = document.getElementById('department').value.trim();
      const start_date = document.getElementById('start_date').value.trim();
      const status = document.getElementById('status').value;

      try {
        const res = await fetch('/api/hr/onboarding', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            employee_id,
            name,
            department,
            start_date,
            status,
            checklist: ["Security Background Check", "Laptop Provisioning", "System Access"]
          })
        });
        const json = await res.json();
        if (json.success) {
          const s = document.getElementById('success-banner');
          s.innerText = 'Onboarding for ' + employee_id + ' finalized and saved successfully.';
          s.style.display = 'block';
          document.getElementById('error-banner').style.display = 'none';
        } else {
          throw new Error(json.error || 'Failed');
        }
      } catch (err) {
        const eb = document.getElementById('error-banner');
        eb.innerText = err.message;
        eb.style.display = 'block';
        document.getElementById('success-banner').style.display = 'none';
      }
    });
  </script>
</body>
</html>`;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;


  // CORS headers
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  // HTML pages
  if (req.method === "GET" && (pathname === "/" || pathname === "/hr")) {
    const list = Array.from(store.values());
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(renderDashboardHtml(list));
    return;
  }

  if (req.method === "GET" && pathname === "/hr/onboarding/new") {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(renderFormHtml());
    return;
  }

  // API endpoints
  if (pathname === "/api/hr/onboarding" && req.method === "GET") {
    const q = url.searchParams.get("q")?.toLowerCase();
    let list = Array.from(store.values());
    if (q) {
      list = list.filter(i =>
        i.employee_id.toLowerCase().includes(q) ||
        i.name.toLowerCase().includes(q) ||
        i.department.toLowerCase().includes(q)
      );
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: true, count: list.length, data: list }));
    return;
  }

  if (pathname === "/api/hr/reset" && req.method === "POST") {
    resetStore();
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: true, message: "Store reset" }));
    return;
  }

  if (pathname.startsWith("/api/hr/onboarding/") && req.method === "GET") {
    const id = pathname.replace("/api/hr/onboarding/", "").trim().toUpperCase();
    const item = store.get(id);
    if (!item) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ success: false, error: `Record '${id}' not found` }));
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ success: true, data: item }));
    return;
  }

  if (pathname === "/api/hr/onboarding" && req.method === "POST") {
    let body = "";
    req.on("data", chunk => body += chunk);
    req.on("end", () => {
      try {
        const data = JSON.parse(body);
        const empId = data.employee_id?.trim();
        if (!empId || !data.name || !data.department || !data.start_date) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: false, error: "Missing required fields" }));
          return;
        }
        const normId = empId.toUpperCase();
        if (store.has(normId)) {
          const existing = store.get(normId);
          const updated = {
            ...existing,
            name: data.name ? data.name.trim() : existing.name,
            department: data.department ? data.department.trim() : existing.department,
            start_date: data.start_date ? data.start_date.trim() : existing.start_date,
            role: data.role ? data.role.trim() : existing.role,
            checklist: data.checklist || existing.checklist,
            status: data.status || existing.status,
            notes: data.notes !== undefined ? data.notes : existing.notes,
            updated_at: new Date().toISOString()
          };
          store.set(normId, updated);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: true, data: updated }));
          return;
        }
        const record = {
          employee_id: empId,
          name: data.name.trim(),
          department: data.department.trim(),
          start_date: data.start_date.trim(),
          role: data.role || "Employee",
          checklist: data.checklist || [],
          status: data.status || "PENDING",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        };
        store.set(normId, record);
        res.writeHead(201, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: true, data: record }));
      } catch (e) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: false, error: e.message }));
      }
    });
    return;
  }

  if (pathname.startsWith("/api/hr/onboarding/") && req.method === "PATCH") {
    const id = pathname.replace("/api/hr/onboarding/", "").trim().toUpperCase();
    const existing = store.get(id);
    if (!existing) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ success: false, error: `Record '${id}' not found` }));
      return;
    }
    let body = "";
    req.on("data", chunk => body += chunk);
    req.on("end", () => {
      try {
        const data = JSON.parse(body);
        const updated = {
          ...existing,
          ...data,
          updated_at: new Date().toISOString()
        };
        store.set(id, updated);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: true, data: updated }));
      } catch (e) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: false, error: e.message }));
      }
    });
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[HR Sandbox] Listening on http://127.0.0.1:${PORT}`);
});

