import http from "node:http";
import { readDb, updateDb, publicUser, createId } from "./store.js";

const PORT = Number(process.env.PORT || 4000);
const CLIENT_ORIGIN = process.env.CLIENT_ORIGIN || "http://localhost:5173";

function send(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": CLIENT_ORIGIN,
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  });
  res.end(JSON.stringify(payload));
}

async function parseBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    const error = new Error("Invalid JSON request body.");
    error.status = 400;
    throw error;
  }
}

function requireAuth(req, db) {
  const token = req.headers.authorization?.replace(/^Bearer\s+/i, "");
  if (!token) return null;
  return db.users.find((user) => user.id === token) || null;
}

function scopeClientIds(user, db) {
  if (user.role === "admin") return db.clients.map((client) => client.id);
  if (user.role === "ca") return db.clients.filter((client) => client.caId === user.id).map((client) => client.id);
  return db.clients.filter((client) => client.email === user.email || client.gstin === user.gstin).map((client) => client.id);
}

function summarizeDashboard(user, db) {
  const clientIds = scopeClientIds(user, db);
  const clients = db.clients.filter((client) => clientIds.includes(client.id));
  const invoices = db.invoices.filter((invoice) => clientIds.includes(invoice.clientId));
  const fraudAlerts = db.fraudAlerts.filter((alert) => clientIds.includes(alert.clientId));

  return {
    kpis: {
      totalClients: clients.length,
      uploadedInvoices: invoices.length,
      matchedInvoices: invoices.filter((invoice) => invoice.status === "Matched").length,
      mismatchedInvoices: invoices.filter((invoice) => invoice.status === "Mismatched").length,
      duplicateInvoices: invoices.filter((invoice) => invoice.status === "Duplicate").length,
      highRiskTransactions: fraudAlerts.filter((alert) => alert.risk >= 70).length,
      complianceScore: clients.length ? Math.round(clients.reduce((sum, client) => sum + client.compliance, 0) / clients.length) : null,
    },
    monthlyData: [],
    supplierRisk: fraudAlerts.map((alert) => ({
      supplier: alert.entity,
      risk: alert.risk,
      amount: alert.amount,
      reason: alert.reason,
    })),
  };
}

async function route(req, res) {
  if (req.method === "OPTIONS") return send(res, 204, {});

  const url = new URL(req.url, `http://${req.headers.host}`);
  const { pathname } = url;

  if (req.method === "GET" && pathname === "/api/health") {
    return send(res, 200, { ok: true, service: "ReconAI API", timestamp: new Date().toISOString() });
  }

  if (req.method === "POST" && pathname === "/api/auth/login") {
    const body = await parseBody(req);
    const db = await readDb();
    const user = db.users.find((candidate) => candidate.email.toLowerCase() === String(body.email || "").toLowerCase() && candidate.password === body.password);
    if (!user) return send(res, 401, { error: "Invalid email or password." });
    return send(res, 200, { token: user.id, user: publicUser(user) });
  }

  if (req.method === "POST" && pathname === "/api/auth/register") {
    const body = await parseBody(req);
    const created = await updateDb((db) => {
      if (db.users.some((user) => user.email.toLowerCase() === String(body.email || "").toLowerCase())) {
        const error = new Error("Email is already registered.");
        error.status = 409;
        throw error;
      }
      const user = {
        id: createId("usr"),
        name: body.name,
        email: body.email,
        password: body.password,
        role: body.role,
        phone: body.phone || "",
        firmName: body.firmName || "",
        gstin: body.gstin || "",
        icaiNumber: body.icaiNumber || "",
        status: "active",
        createdAt: new Date().toISOString(),
      };
      db.users.push(user);
      if (user.role === "client") {
        db.clients.push({
          id: createId("cl"),
          name: body.businessName || user.name,
          gstin: user.gstin,
          email: user.email,
          caId: body.caId || "usr_ca_demo",
          city: body.city || "",
          status: "Active",
          risk: "Low",
          compliance: 0,
          createdAt: user.createdAt,
        });
      }
      return user;
    });
    return send(res, 201, { token: created.id, user: publicUser(created) });
  }

  const db = await readDb();
  const user = requireAuth(req, db);
  if (!user) return send(res, 401, { error: "Authentication required." });

  if (req.method === "GET" && pathname === "/api/me") return send(res, 200, { user: publicUser(user) });
  if (req.method === "GET" && pathname === "/api/dashboard") return send(res, 200, summarizeDashboard(user, db));

  const clientIds = scopeClientIds(user, db);

  if (req.method === "GET" && pathname === "/api/clients") {
    return send(res, 200, { clients: db.clients.filter((client) => clientIds.includes(client.id)) });
  }

  if (req.method === "POST" && pathname === "/api/clients") {
    if (!["admin", "ca"].includes(user.role)) return send(res, 403, { error: "Only admin or CA users can create clients." });
    const body = await parseBody(req);
    const client = await updateDb((nextDb) => {
      const created = {
        id: createId("cl"),
        name: body.name,
        gstin: body.gstin,
        email: body.email,
        caId: user.role === "ca" ? user.id : body.caId,
        city: body.city || "",
        status: "Active",
        risk: "Low",
        compliance: 0,
        createdAt: new Date().toISOString(),
      };
      nextDb.clients.push(created);
      return created;
    });
    return send(res, 201, { client });
  }

  if (req.method === "GET" && pathname === "/api/invoices") {
    return send(res, 200, { invoices: db.invoices.filter((invoice) => clientIds.includes(invoice.clientId)) });
  }

  if (req.method === "POST" && pathname === "/api/uploads") {
    const body = await parseBody(req);
    const upload = await updateDb((nextDb) => {
      const created = {
        id: createId("upl"),
        clientId: body.clientId || clientIds[0],
        name: body.name,
        type: body.type || "document",
        size: body.size || 0,
        status: "Ready",
        uploadedBy: user.id,
        createdAt: new Date().toISOString(),
      };
      nextDb.uploads.push(created);
      return created;
    });
    return send(res, 201, { upload });
  }

  if (req.method === "POST" && pathname === "/api/reconciliation/run") {
    const body = await parseBody(req);
    const selectedClientId = body.clientId || clientIds[0];
    if (!clientIds.includes(selectedClientId)) return send(res, 403, { error: "Client is outside your workspace." });
    const invoices = db.invoices.filter((invoice) => invoice.clientId === selectedClientId);
    return send(res, 200, {
      jobId: createId("rec"),
      status: "completed",
      summary: {
        total: invoices.length,
        matched: invoices.filter((invoice) => invoice.status === "Matched").length,
        mismatched: invoices.filter((invoice) => invoice.status === "Mismatched").length,
        duplicates: invoices.filter((invoice) => invoice.status === "Duplicate").length,
      },
    });
  }

  if (req.method === "GET" && pathname === "/api/fraud-alerts") {
    return send(res, 200, { alerts: db.fraudAlerts.filter((alert) => clientIds.includes(alert.clientId)) });
  }

  if (req.method === "POST" && pathname === "/api/messages") {
    const body = await parseBody(req);
    const message = await updateDb((nextDb) => {
      const created = {
        id: createId("msg"),
        clientId: body.clientId || clientIds[0],
        senderId: user.id,
        text: body.text,
        createdAt: new Date().toISOString(),
      };
      nextDb.messages.push(created);
      return created;
    });
    return send(res, 201, { message });
  }

  if (req.method === "GET" && pathname === "/api/reports") {
    return send(res, 200, { reports: db.reports.filter((report) => clientIds.includes(report.clientId)) });
  }

  return send(res, 404, { error: "Route not found." });
}

const server = http.createServer((req, res) => {
  route(req, res).catch((error) => {
    send(res, error.status || 500, { error: error.message || "Internal server error." });
  });
});

server.listen(PORT, () => {
  console.log(`ReconAI API listening on http://localhost:${PORT}`);
});
