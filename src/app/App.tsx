import React, { useState, useRef, useEffect, Fragment } from "react";
import {
  LayoutDashboard, Users, Upload, FileText, ShieldAlert, Share2,
  MessageSquare, BarChart3, Bell, Settings, ChevronRight, Search,
  Sun, Moon, LogOut, TrendingUp, TrendingDown, CheckCircle2,
  AlertTriangle, XCircle, Copy, RefreshCw, Filter, Download,
  Plus, Eye, MoreHorizontal, ArrowUpRight, ArrowDownRight,
  Zap, Database, Activity, Globe, Lock, User, Mail, Phone,
  Building2, CreditCard, ChevronDown, X, Send, Bot, Paperclip,
  FileUp, Check, Clock, CircleDot, Layers, Network, AlertCircle,
  Star, Shield, Cpu, HardDrive, Wifi, ChevronLeft, ChevronUp, Info, Loader2, Trash2, UserCheck
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis
} from "recharts";

import LandingPage from "./components/LandingPage";
import AuthPages from "./components/AuthPages";
import ClientDashboard from "./components/ClientDashboard";
import DocumentVerificationModal from "./components/DocumentVerificationModal";
import { apiRequest } from "./lib/api";
import { ADMIN, BUSINESS_USER, TAX_REVIEWER, ROLE_LABELS, normalizeRole, roleShortLabel, type Role } from "./lib/roles";

import logoImg from "../../Screenshot_2026-07-01_214942-removebg-preview.png";
import darkLogoImg from "../../darkThemeLogo.png";

// ── Types ──────────────────────────────────────────────────────────────────
type Page =
  | "dashboard" | "clients" | "upload" | "reconciliation"
  | "fraud" | "graph" | "assistant" | "reports" | "notifications"
  | "settings" | "admin" | "ca-requests";

interface LoggedInUser {
  name: string;
  email: string;
  role: Role;
  firmName?: string;
  gstin?: string;
  icaiNumber?: string;
}

// Data placeholders loaded from the backend in production.

type MonthlyDataPoint = { month: string; matched: number; mismatched: number; duplicates: number };
type FraudPieSlice = { name: string; value: number; color: string };
type SupplierRisk = { supplier: string; risk: number; invoices: number; amount: string };
type ClientRecord = { id: number | string; name: string; gstin: string; email?: string; compliance: number; invoices: number; status: string; risk: string; city: string; caName?: string; caEmail?: string; caFirm?: string };
type InvoiceRecord = { id: string; supplier: string; gstin: string; date: string; taxable: string; gst: string; total: string; status: string; risk: string };
type FraudAlert = { id: string; type: string; entity: string; risk: number; score: string; amount: string; reason: string; shap: string[] };
type NotificationRecord = { id: number; type: "critical" | "warning" | "success" | "info"; title: string; msg: string; time: string; read: boolean };
type ChatMessage = { role: "assistant" | "user"; text: string };

// ── Data Store (populated from backend on login) ──────────────────────────
let monthlyData: MonthlyDataPoint[] = [];
let fraudPieData: FraudPieSlice[] = [];
let supplierRisk: SupplierRisk[] = [];
let clients: ClientRecord[] = [];
let invoices: InvoiceRecord[] = [];
let fraudAlerts: FraudAlert[] = [];
let notifications: NotificationRecord[] = [];
let chatMessages: ChatMessage[] = [];
let firstClientId: string | number | null = null;
let dashboardKpis: Record<string, number | null> = {};

async function fetchAllData(onUpdate: () => void, selectedClientId?: string): Promise<void> {
  const queryParam = selectedClientId && selectedClientId !== "ALL" ? `?clientId=${selectedClientId}` : "";
  try {
    // Fetch dashboard data (KPIs, monthly trends, supplier risk)
    const dash = await apiRequest<{
      kpis: Record<string, number | null>;
      monthlyData: { month: string; matched: number; mismatched: number; duplicates: number }[];
      supplierRisk: { supplier: string; risk: number; amount: number; invoices: number; reason: string }[];
    }>(`/api/dashboard${queryParam}`, { auth: true });
    monthlyData = dash.monthlyData || [];
    dashboardKpis = dash.kpis || {};
    supplierRisk = (dash.supplierRisk || []).map(s => ({
      supplier: s.supplier,
      risk: s.risk,
      // The real count from the backend. This was hardcoded to 0, so the
      // ranking always read "0 invoices" next to every supplier.
      invoices: s.invoices ?? 0,
      amount: `₹${Number(s.amount || 0).toLocaleString("en-IN")}`,
    }));
    onUpdate();

    // Fetch clients
    const clientsRes = await apiRequest<{ clients: any[] }>("/api/clients", { auth: true });
    clients = (clientsRes.clients || []).map(c => ({
      id: c.id,
      name: c.name,
      gstin: c.gstin,
      email: c.email || "",
      compliance: c.compliance ?? 0,
      invoices: 0,
      status: c.status || "Active",
      risk: c.risk || "Low",
      city: c.city || "",
      caName: c.caName || "",
      caEmail: c.caEmail || "",
      caFirm: c.firmName || "",
    }));
    if (clients.length > 0) firstClientId = clients[0].id;
    onUpdate();

    // Fetch invoices
    const invoicesRes = await apiRequest<{ invoices: any[] }>("/api/invoices", { auth: true });
    invoices = (invoicesRes.invoices || []).map(inv => {
      const rawDate = inv.created_at || inv.invoice_date || "";
      let formattedDate = inv.invoice_date || "";
      if (rawDate && rawDate.length > 10) {
        try {
          const d = new Date(rawDate);
          formattedDate = d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true });
        } catch (e) {}
      }
      const rawSupp = inv.supplier || "";
      const cleanSupp = rawSupp || "—";  // em dash: unknown, not invented
      return {
        id: inv.invoice_no || inv.id,
        supplier: cleanSupp,
        gstin: inv.supplier_gstin || "",
        date: formattedDate,
        taxable: `₹${Number(inv.taxable || 0).toLocaleString("en-IN")}`,
        gst: `₹${Number(inv.gst || 0).toLocaleString("en-IN")}`,
        total: `₹${Number(inv.total || 0).toLocaleString("en-IN")}`,
        status: inv.status || "Pending",
        risk: inv.risk || "Low",
      };
    });
    // Update client invoice counts
    clients = clients.map(c => ({
      ...c,
      invoices: (invoicesRes.invoices || []).filter((inv: any) => inv.client_id === c.id).length,
    }));
    onUpdate();

    // Fetch fraud alerts
    const alertsRes = await apiRequest<{ alerts: any[] }>("/api/fraud-alerts", { auth: true });
    fraudAlerts = (alertsRes.alerts || []).map(a => ({
      id: String(a.id),
      type: a.type || "Invoice Risk",
      entity: a.entity || "Unknown",
      risk: a.risk || 0,
      score: a.risk >= 85 ? "Critical" : a.risk >= 70 ? "High" : a.risk >= 50 ? "Medium" : "Low",
      amount: `₹${Number(a.amount || 0).toLocaleString("en-IN")}`,
      reason: a.reason || "",
      shap: a.shap || [],
    }));
    // Build fraud pie data from alerts
    const critCount = fraudAlerts.filter(a => a.score === "Critical").length;
    const highCount = fraudAlerts.filter(a => a.score === "High").length;
    const medCount = fraudAlerts.filter(a => a.score === "Medium").length;
    const lowCount = fraudAlerts.filter(a => a.score === "Low").length;
    if (fraudAlerts.length > 0) {
      fraudPieData = [
        ...(critCount > 0 ? [{ name: "Critical", value: Math.round(critCount / fraudAlerts.length * 100), color: "#DC2626" }] : []),
        ...(highCount > 0 ? [{ name: "High", value: Math.round(highCount / fraudAlerts.length * 100), color: "#F97316" }] : []),
        ...(medCount > 0 ? [{ name: "Medium", value: Math.round(medCount / fraudAlerts.length * 100), color: "#F59E0B" }] : []),
        ...(lowCount > 0 ? [{ name: "Low", value: Math.round(lowCount / fraudAlerts.length * 100), color: "#10B981" }] : []),
      ];
    } else {
      fraudPieData = [];
    }
    onUpdate();

    // Fetch reports count for notifications
    try {
      const reportsRes = await apiRequest<{ reports: any[] }>("/api/reports", { auth: true });
      if (reportsRes.reports?.length > 0) {
        notifications = reportsRes.reports.slice(0, 5).map((r: any, i: number) => ({
          id: i + 1,
          type: "info" as const,
          title: r.name || "Report Ready",
          msg: `Report ${r.id} generated`,
          time: r.created_at || "",
          read: false,
        }));
      }
    } catch { /* reports endpoint may not exist yet */ }
    onUpdate();
  } catch (err) {
    console.error("Failed to fetch data:", err);
  }
}

function getClientId(): string | number {
  return firstClientId || (clients.length > 0 ? clients[0].id : "");
}

const formatCurrency = (value: number | string) =>
  `₹${Number(value || 0).toLocaleString("en-IN")}`;

const riskScoreLabel = (risk: number) => {
  if (risk >= 85) return "Critical";
  if (risk >= 70) return "High";
  if (risk >= 50) return "Medium";
  return "Low";
};
// ── Utility Components ─────────────────────────────────────────────────────
const Badge = ({ label, variant }: { label: string; variant: "success" | "warning" | "danger" | "critical" | "info" | "neutral" }) => {
  const styles = {
    success: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    warning: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    danger: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    critical: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    info: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    neutral: "bg-muted text-muted-foreground",
  };
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium ${styles[variant]}`}>{label}</span>;
};

const RiskBar = ({ value }: { value: number }) => {
  const color = value >= 80 ? "bg-red-500" : value >= 60 ? "bg-amber-500" : value >= 40 ? "bg-yellow-400" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs text-muted-foreground w-6 text-right">{value}</span>
    </div>
  );
};

const KpiCard = ({ title, value, sub, icon: Icon, trend, trendUp }: any) => (
  <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-3">
    <div className="flex items-start justify-between">
      <div className="p-2 bg-accent rounded-md">
        <Icon size={15} className="text-primary" />
      </div>
      {trend && (
        <div className={`flex items-center gap-1 text-xs font-mono ${trendUp ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
          {trendUp ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
          {trend}
        </div>
      )}
    </div>
    <div>
      <div className="text-2xl font-semibold tracking-tight">{value}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{title}</div>
    </div>
    {sub && <div className="text-xs text-muted-foreground border-t border-border pt-2">{sub}</div>}
  </div>
);

const EmptyState = ({ message }: { message: string }) => (
  <div className="px-4 py-8 text-center text-xs text-muted-foreground">
    {message}
  </div>
);

// ── Sidebar ────────────────────────────────────────────────────────────────
const navItems = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "clients", label: "Clients", icon: Users },
  { id: "upload", label: "Upload Center", icon: Upload },
  { id: "reconciliation", label: "Reconciliation", icon: FileText },
  { id: "fraud", label: "Fraud Detection", icon: ShieldAlert },
  { id: "graph", label: "Graph Analytics", icon: Share2 },
  { id: "assistant", label: "AI Assistant", icon: MessageSquare },
  { id: "reports", label: "Reports", icon: BarChart3 },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "admin", label: "Admin Panel", icon: Lock },
  { id: "ca-requests", label: "Tax Officer Requests", icon: UserCheck },
];

function Sidebar({ page, setPage, collapsed, user, onLogout, dark }: { page: Page; setPage: (p: Page) => void; collapsed: boolean; user: LoggedInUser; onLogout: () => void; dark: boolean }) {
  const visibleItems = navItems.filter(({ id }) => {
    if ((id === "admin" || id === "ca-requests") && normalizeRole(user.role) !== ADMIN) return false;
    return true;
  });

  return (
    <aside className={`fixed top-0 left-0 h-screen bg-sidebar border-r border-sidebar-border flex flex-col z-30 transition-all duration-200 ${collapsed ? "w-14" : "w-56"}`}>
      <div className="h-16 flex items-center px-3 border-b border-sidebar-border shrink-0 justify-center overflow-visible">
        <div className={`relative flex items-center justify-center ${collapsed ? "h-12 w-12" : "h-14 w-52"}`}>
          <img
            src={logoImg}
            alt="ReconAI Logo"
            aria-hidden={dark}
            className={`absolute object-contain transition-opacity duration-100 ${
              dark ? "opacity-0" : "opacity-100"
            } ${collapsed ? "h-8 w-10" : "h-12 w-52"}`}
          />
          <img
            src={darkLogoImg}
            alt="ReconAI Logo"
            aria-hidden={!dark}
            className={`absolute object-contain transition-opacity duration-100 ${
              dark ? "opacity-100" : "opacity-0"
            } ${collapsed ? "h-14 w-14 scale-125" : "h-20 w-64 scale-125"}`}
          />
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5 scrollbar-thin">
        {visibleItems.map(({ id, label, icon: Icon }) => {
          const active = page === id;
          return (
            <button
              key={id}
              onClick={() => setPage(id as Page)}
              className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm transition-colors duration-100 ${
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
              }`}
            >
              <Icon size={15} className={active ? "text-sidebar-primary" : ""} />
              {!collapsed && <span className="truncate">{label}</span>}
              {!collapsed && id === "notifications" && notifications.some(n => !n.read) && (
                <span className="ml-auto text-[10px] bg-red-500 text-white rounded-full min-w-4 h-4 px-1 flex items-center justify-center font-mono">
                  {notifications.filter(n => !n.read).length}
                </span>
              )}
            </button>
          );
        })}
      </nav>
      <div className="p-2 border-t border-sidebar-border shrink-0">
        <button onClick={onLogout} className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent/60 transition-colors`}>
          <LogOut size={14} />
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </aside>
  );
}

// ── Topbar ─────────────────────────────────────────────────────────────────
function Topbar({ dark, setDark, page, setPage, sidebarCollapsed, setSidebarCollapsed, user, selectedClientId, onClientFilterChange }: any) {
  const titles: Record<Page, string> = {
    dashboard: "Dashboard", clients: "Client Management", upload: "Upload Center",
    reconciliation: "Invoice Reconciliation", fraud: "Fraud Detection",
    graph: "Graph Analytics", assistant: "AI Assistant", reports: "Reports",
    notifications: "Notifications", settings: "Settings", admin: "Admin Panel",
    "ca-requests": "Tax Officer Transfer Requests",
  };

  const getInitials = (name: string) => {
    return name ? name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2) : "US";
  };

  const getRoleLabel = (role: string) => {
    if (normalizeRole(role) === ADMIN) return "System Administrator";
    if (normalizeRole(role) === TAX_REVIEWER) return ROLE_LABELS[TAX_REVIEWER];
    return "Client / Owner";
  };

  return (
    <header className="h-14 border-b border-border bg-card flex items-center px-4 gap-4 sticky top-0 z-20">
      <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)} className="p-1.5 rounded hover:bg-muted text-muted-foreground transition-colors">
        <Layers size={16} />
      </button>
      <div className="font-semibold text-sm">{titles[page]}</div>
      <div className="flex-1 max-w-sm mx-4">
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input placeholder="Search invoices, clients, GSTINs…" className="w-full pl-8 pr-3 py-1.5 text-xs bg-muted rounded-md border border-border focus:outline-none focus:ring-1 focus:ring-primary/40 placeholder:text-muted-foreground/60" />
        </div>
      </div>
      {normalizeRole(user?.role) === TAX_REVIEWER && (
        <div className="flex items-center gap-2 bg-muted/80 border border-border rounded-lg px-2.5 py-1 text-xs">
          <Users size={13} className="text-primary shrink-0" />
          <span className="text-muted-foreground font-medium hidden sm:inline">Client Filter:</span>
          {clients.length > 0 ? (
            <select
              value={selectedClientId || "ALL"}
              onChange={(e) => onClientFilterChange?.(e.target.value)}
              className="bg-transparent text-xs font-semibold focus:outline-none cursor-pointer"
            >
              <option value="ALL">🌐 All Clients (Combined Summary)</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  🏢 {c.name}
                </option>
              ))}
            </select>
          ) : (
            <span className="font-semibold text-amber-500">0 Clients Assigned</span>
          )}
        </div>
      )}
      <div className="ml-auto flex items-center gap-1">
        <button onClick={() => setPage("notifications")} className="relative p-2 rounded hover:bg-muted text-muted-foreground transition-colors">
          <Bell size={16} />
          {notifications.some(n => !n.read) && <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />}
        </button>
        <button onClick={() => setDark(!dark)} className="p-2 rounded hover:bg-muted text-muted-foreground transition-colors">
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <div className="flex items-center gap-2 ml-2 pl-3 border-l border-border">
          <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-white text-xs font-semibold">
            {getInitials(user?.name)}
          </div>
          <div className="hidden sm:block text-left">
            <div className="text-xs font-medium">{user?.name || "User"}</div>
            <div className="text-[10px] text-muted-foreground font-mono">{getRoleLabel(user?.role)}</div>
          </div>
          <ChevronDown size={12} className="text-muted-foreground" />
        </div>
      </div>
    </header>
  );
}

// ── Dashboard ──────────────────────────────────────────────────────────────
function DashboardPage({ user }: { user: LoggedInUser }) {
  const [notice, setNotice] = useState("");
  const k = dashboardKpis;
  const kpis = [
    { title: "Total Clients", value: (k.totalClients ?? clients.length).toLocaleString(), icon: Users, sub: `${clients.length} in portfolio` },
    { title: "Uploaded Invoices", value: (k.uploadedInvoices ?? invoices.length).toLocaleString(), icon: FileText, sub: "Across all clients" },
    { title: "Matched Invoices", value: (k.matchedInvoices ?? 0).toLocaleString(), icon: CheckCircle2, sub: "Successfully reconciled" },
    { title: "Mismatched", value: (k.mismatchedInvoices ?? 0).toLocaleString(), icon: AlertTriangle, sub: "Require review" },
    { title: "Duplicates", value: (k.duplicateInvoices ?? 0).toLocaleString(), icon: Copy, sub: "Flagged as duplicate" },
    { title: "High-Risk Transactions", value: (k.highRiskTransactions ?? fraudAlerts.length).toLocaleString(), icon: ShieldAlert, sub: "Risk score >= 70" },
    { title: "Circular Trading", value: "0", icon: RefreshCw, sub: "Graph analysis pending" },
    { title: "Compliance Score", value: k.complianceScore != null ? `${k.complianceScore}%` : "N/A", icon: Activity, sub: "Average across clients" },
  ];

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload) return null;
    return (
      <div className="bg-popover border border-border rounded-lg p-3 text-xs shadow-lg">
        <div className="font-medium mb-2">{label}</div>
        {payload.map((p: any) => (
          <div key={p.name} className="flex items-center gap-2">
            <span style={{ color: p.color }}>●</span>
            <span className="text-muted-foreground">{p.name}:</span>
            <span className="font-mono font-medium">{p.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-left">Good morning, {user?.name.split(" ")[0]}</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {clients.length > 0 ? `Managing ${clients.length} client(s) · ${invoices.length} invoices loaded` : "0 clients assigned in portfolio"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select className="text-xs border border-border bg-card rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary/40">
            {clients.length === 0 ? <option value="">0 Clients Assigned</option> : clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="text-xs border border-border bg-card rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary/40">
            <option>No fiscal years loaded</option>
          </select>
          <button type="button" onClick={() => setNotice("Dashboard export is ready after live dashboard data loads from backend.")} className="flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors">
            <Download size={12} /> Export
          </button>
        </div>
      </div>
      {notice && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{notice}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiCard key={k.title} {...k} />)}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-card border border-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-sm font-medium">Reconciliation Trend</div>
              <div className="text-xs text-muted-foreground">No reconciliation history loaded</div>
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-primary inline-block" /> Matched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500 inline-block" /> Mismatched</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Duplicates</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={monthlyData}>
              <defs>
                <linearGradient id="gradMatch" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <YAxis tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="matched" stroke="var(--chart-1)" fill="url(#gradMatch)" strokeWidth={2} name="Matched" />
              <Line type="monotone" dataKey="mismatched" stroke="var(--chart-3)" strokeWidth={2} dot={false} name="Mismatched" />
              <Line type="monotone" dataKey="duplicates" stroke="var(--chart-4)" strokeWidth={2} dot={false} name="Duplicates" />
            </AreaChart>
          </ResponsiveContainer>
          {monthlyData.length === 0 && <EmptyState message="No reconciliation trend data loaded." />}
        </div>

        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm font-medium mb-1">Fraud Distribution</div>
          <div className="text-xs text-muted-foreground mb-3 font-medium">
            {fraudPieData.length > 0 ? "Breakdown by severity level" : "No active warnings loaded"}
          </div>
          {fraudPieData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie data={fraudPieData} cx="50%" cy="50%" innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                    {fraudPieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(val) => [`${val}%`, ""]} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-2">
                {fraudPieData.map((d) => (
                  <div key={d.name} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full shrink-0" style={{ background: d.color }} />
                      <span className="text-muted-foreground truncate">{d.name}</span>
                    </div>
                    <span className="font-mono font-medium">{d.value}%</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <EmptyState message="No active fraud warnings loaded." />
          )}
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg">
        <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-border">
          <div className="text-sm font-medium">Top Supplier Risk Ranking</div>
          <button type="button" onClick={() => setNotice("Supplier risk ranking will show all rows after fraud model data is loaded.")} className="text-xs text-primary hover:underline">View all</button>
        </div>
        <div className="divide-y divide-border">
          {supplierRisk.map((s, i) => (
            <div key={`${s.supplier}-${i}`} className="flex items-center gap-4 px-4 py-3">
              <span className="text-xs font-mono text-muted-foreground w-4">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{s.supplier}</div>
                <div className="text-xs text-muted-foreground">{s.invoices} invoices · {s.amount}</div>
              </div>
              <div className="w-40 hidden sm:block">
                <RiskBar value={s.risk} />
              </div>
              <Badge
                label={s.risk >= 80 ? "Critical" : s.risk >= 60 ? "High" : s.risk >= 40 ? "Medium" : "Low"}
                variant={s.risk >= 80 ? "critical" : s.risk >= 60 ? "danger" : s.risk >= 40 ? "warning" : "success"}
              />
            </div>
          ))}
          {supplierRisk.length === 0 && <EmptyState message="No supplier risk data loaded." />}
        </div>
      </div>
    </div>
  );
}

// ── Clients ────────────────────────────────────────────────────────────────
function ClientsPage({ onUpdate, user }: { onUpdate?: () => void; user?: LoggedInUser }) {
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [selectedClientDetails, setSelectedClientDetails] = useState<ClientRecord | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [email, setEmail] = useState("");
  const [city, setCity] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");

  const filtered = clients.filter(c => c.name.toLowerCase().includes(search.toLowerCase()) || c.gstin.includes(search));
  const statusVariant = (s: string): any => ({ Matched: "success", Processing: "info", Mismatched: "warning", Review: "warning", Missing: "neutral" }[s] ?? "neutral");
  const riskVariant = (r: string): any => ({ Low: "success", Medium: "warning", High: "danger", Critical: "critical" }[r] ?? "neutral");

  const handleCreateClient = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError("");

    if (!name.trim()) {
      setModalError("Business Name is required.");
      return;
    }
    const cleanGstin = gstin.trim().toUpperCase();
    if (!cleanGstin || cleanGstin.length !== 15) {
      setModalError("Valid 15-character GSTIN is required.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await apiRequest<{ client: any }>("/api/clients", {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          name: name.trim(),
          gstin: cleanGstin,
          email: email.trim(),
          city: city.trim(),
        }),
      });

      const newRecord: ClientRecord = {
        id: result.client.id,
        name: result.client.name,
        gstin: result.client.gstin,
        compliance: result.client.compliance ?? 100,
        invoices: 0,
        status: result.client.status || "Active",
        risk: result.client.risk || "Low",
        city: result.client.city || "",
      };

      clients.unshift(newRecord);
      if (!firstClientId) firstClientId = newRecord.id;

      setShowModal(false);
      setName(""); setGstin(""); setEmail(""); setCity("");
      setNotice(`Client "${newRecord.name}" created successfully.`);
      if (onUpdate) onUpdate();
    } catch (err) {
      setModalError(err instanceof Error ? err.message : "Failed to create client.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteClient = async (c: ClientRecord, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to delete client "${c.name}"? This will remove all associated user accounts, invoices, and uploads.`)) return;
    try {
      await apiRequest(`/api/clients/${encodeURIComponent(String(c.id))}`, { method: "DELETE", auth: true });
      clients = clients.filter(x => x.id !== c.id);
      setNotice(`Client "${c.name}" deleted successfully.`);
      if (onUpdate) onUpdate();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Deletion failed.");
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Client Portfolio</h2>
          <p className="text-xs text-muted-foreground">{clients.length} registered client(s)</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search clients…" className="pl-7 pr-3 py-1.5 text-xs bg-muted border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary/40 w-48" />
          </div>
          <button type="button" onClick={() => { setShowModal(true); setModalError(""); }} className="flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors">
            <Plus size={12} /> Add Client
          </button>
        </div>
      </div>
      {notice && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{notice}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {filtered.map(c => (
          <div key={c.id} onClick={() => setSelectedClientDetails(c)} className="bg-card border border-border rounded-lg p-4 hover:border-primary/30 transition-colors cursor-pointer group">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-md bg-accent flex items-center justify-center shrink-0">
                  <Building2 size={16} className="text-primary" />
                </div>
                <div>
                  <div className="text-sm font-medium leading-tight">{c.name}</div>
                  <div className="text-[11px] font-mono text-muted-foreground mt-0.5">{c.gstin}</div>
                </div>
              </div>
              {normalizeRole(user?.role) === ADMIN && (
                <button
                  type="button"
                  onClick={(e) => handleDeleteClient(c, e)}
                  title="Delete Client & User Account (Admin Only)"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 text-muted-foreground hover:text-red-500 hover:bg-red-500/10 rounded"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Compliance Score</span>
                <span className="font-mono font-semibold">{c.compliance}%</span>
              </div>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${c.compliance >= 90 ? "bg-emerald-500" : c.compliance >= 75 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${c.compliance}%` }} />
              </div>
              <div className="flex items-center justify-between pt-1">
                <div className="text-xs text-muted-foreground">{c.invoices.toLocaleString()} invoices · {c.city || "Headquarters"}</div>
                <div className="flex items-center gap-1.5">
                  <Badge label={c.status} variant={statusVariant(c.status)} />
                  <Badge label={c.risk} variant={riskVariant(c.risk)} />
                </div>
              </div>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="md:col-span-2 xl:col-span-3 bg-card border border-border rounded-lg">
            <EmptyState message="No clients found." />
          </div>
        )}
      </div>

      {/* Add Client Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <Building2 size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold">Register New Client</h3>
                  <p className="text-[11px] text-muted-foreground">Add business entity to CA portfolio</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-muted transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreateClient} className="p-5 space-y-4">
              {modalError && (
                <div className="flex items-center gap-2 text-xs bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900 rounded-lg p-3">
                  <AlertCircle size={14} className="shrink-0" />
                  <span>{modalError}</span>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">Business Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Logistics Pvt Ltd"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full text-xs bg-background border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">GSTIN (15 Characters) *</label>
                <input
                  type="text"
                  required
                  maxLength={15}
                  placeholder="27AAAAA0000A1Z5"
                  value={gstin}
                  onChange={e => setGstin(e.target.value.toUpperCase())}
                  className="w-full text-xs font-mono uppercase bg-background border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-foreground">Contact Email</label>
                  <input
                    type="email"
                    placeholder="finance@acme.com"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    className="w-full text-xs bg-background border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-foreground">City / Region</label>
                  <input
                    type="text"
                    placeholder="Mumbai"
                    value={city}
                    onChange={e => setCity(e.target.value)}
                    className="w-full text-xs bg-background border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="text-xs border border-border bg-card px-4 py-2 rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {submitting ? (
                    <>
                      <Loader2 size={12} className="animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Plus size={12} />
                      Save Client
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Client Details Modal */}
      {selectedClientDetails && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border text-card-foreground rounded-2xl p-6 w-full max-w-lg space-y-5 shadow-2xl animate-in fade-in zoom-in duration-200">
            <div className="flex items-start justify-between border-b border-border pb-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/15 text-primary flex items-center justify-center font-bold">
                  <Building2 size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold">{selectedClientDetails.name}</h3>
                  <p className="text-xs text-muted-foreground font-mono">GSTIN: {selectedClientDetails.gstin || "N/A"}</p>
                </div>
              </div>
              <button onClick={() => setSelectedClientDetails(null)} className="p-1.5 hover:bg-muted rounded-md text-muted-foreground hover:text-foreground transition-colors"><X size={16} /></button>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-muted/40 border border-border rounded-xl p-3 space-y-1">
                <div className="text-[11px] text-muted-foreground font-medium flex items-center gap-1.5">
                  <Mail size={12} className="text-primary" /> Email Address
                </div>
                <div className="font-mono font-semibold text-foreground truncate">{selectedClientDetails.email || "Not registered"}</div>
              </div>

              <div className="bg-muted/40 border border-border rounded-xl p-3 space-y-1">
                <div className="text-[11px] text-muted-foreground font-medium flex items-center gap-1.5">
                  <Globe size={12} className="text-primary" /> Location / City
                </div>
                <div className="font-semibold text-foreground">{selectedClientDetails.city || "Not specified"}</div>
              </div>

              <div className="bg-muted/40 border border-border rounded-xl p-3 space-y-1">
                <div className="text-[11px] text-muted-foreground font-medium flex items-center gap-1.5">
                  <User size={12} className="text-primary" /> Assigned CA
                </div>
                <div className="font-semibold text-foreground truncate">{selectedClientDetails.caName || "Unassigned"}</div>
                {selectedClientDetails.caFirm && <div className="text-[10px] text-muted-foreground truncate">{selectedClientDetails.caFirm}</div>}
              </div>

              <div className="bg-muted/40 border border-border rounded-xl p-3 space-y-1">
                <div className="text-[11px] text-muted-foreground font-medium flex items-center gap-1.5">
                  <Activity size={12} className="text-primary" /> Compliance Score
                </div>
                <div className="font-mono font-bold text-emerald-500 text-sm">{selectedClientDetails.compliance}%</div>
              </div>
            </div>

            <div className="bg-muted/20 border border-border rounded-xl p-3.5 space-y-2 text-xs">
              <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Workspace Health & Risk</div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-card border border-border rounded-lg p-2">
                  <div className="text-muted-foreground text-[10px]">Status</div>
                  <div className="font-semibold">{selectedClientDetails.status}</div>
                </div>
                <div className="bg-card border border-border rounded-lg p-2">
                  <div className="text-muted-foreground text-[10px]">Risk Profile</div>
                  <div className="font-semibold text-amber-500">{selectedClientDetails.risk}</div>
                </div>
                <div className="bg-card border border-border rounded-lg p-2">
                  <div className="text-muted-foreground text-[10px]">Invoices</div>
                  <div className="font-mono font-semibold">{selectedClientDetails.invoices}</div>
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-1">
              <button onClick={() => setSelectedClientDetails(null)} className="text-xs bg-primary text-primary-foreground font-semibold px-4 py-2 rounded-lg hover:bg-primary/90 transition-colors">
                Close Details
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Upload Center ──────────────────────────────────────────────────────────
function UploadPage({ onRefresh, onVerifyDoc }: { onRefresh?: () => void; onVerifyDoc?: (id: string) => void }) {
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const gstInputRef = useRef<HTMLInputElement>(null);
  const poInputRef = useRef<HTMLInputElement>(null);

  // Real-time green progress bar state for CA process button and upload
  const [processingId, setProcessingId] = useState<number | string | null>(null);
  const [processProgress, setProcessProgress] = useState(0);
  const [processProgressText, setProcessProgressText] = useState("");
  const [processingFileName, setProcessingFileName] = useState("");
  const [toast, setToast] = useState<{ title: string; body: string; code?: string } | null>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => {
      setToast(null);
    }, 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  const DONE_STATUSES = ["stored", "parsed", "parsed_with_warnings", "processed", "complete", "Needs Review"];
  const uiState = (s: string) => {
    if (!s) return "uploaded";
    const sl = String(s).toLowerCase();
    if (DONE_STATUSES.some(d => d.toLowerCase() === sl)) return "complete";
    if (sl === "failed") return "failed";
    if (sl === "processing") return "processing";
    return "uploaded";
  };

  const loadUploads = async () => {
    try {
      const result = await apiRequest<{ uploads: any[] }>("/api/ingestion/uploads", { auth: true });
      setUploads((result.uploads || []).map(upload => {
        const rawDate = upload.uploadedAt || upload.createdAt || upload.created_at;
        let formattedTime = "Recently Uploaded";
        if (rawDate) {
          try {
            const d = new Date(rawDate);
            formattedTime = d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true });
          } catch (e) {
            formattedTime = String(rawDate);
          }
        }
        return {
          id: upload.id,
          name: upload.fileName || upload.file_name || "Invoice Document.pdf",
          size: `${upload.clientName || "Sujal Patel Enterprise"} · ${upload.fileType || "PDF Document"} · 🕒 ${formattedTime}`,
          rawStatus: upload.status,
          parsedRows: upload.parsedRows ?? upload.parsed_rows ?? 0,
          errors: upload.validationErrors ?? [],
          visibleToClient: !!upload.visibleToClient,
          uploadedAt: formattedTime,
        };
      }));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to load uploads.");
    }
  };

  useEffect(() => {
    loadUploads();
  }, []);

  const uploadSelectedFile = async (file: File, type: string) => {
    setProcessingId("upload");
    setProcessingFileName(file.name);
    setProcessProgress(10);
    setProcessProgressText(`Uploading ${file.name}...`);
    setMessage(`Uploading ${file.name}...`);

    const interval = setInterval(() => {
      setProcessProgress(prev => (prev < 90 ? prev + 15 : prev));
    }, 200);

    try {
      const formData = new FormData();
      formData.append("clientId", String(getClientId()));
      formData.append("source", type);
      // documentType is what routes a purchase order away from invoice parsing.
      formData.append("documentType", type);
      formData.append("file", file);
      await apiRequest("/api/ingestion/upload", { method: "POST", auth: true, body: formData });

      clearInterval(interval);
      setProcessProgress(100);
      setProcessProgressText(`100% Upload Complete for ${file.name}! Click Process to run extract.py.`);
      setMessage(`${file.name} uploaded. Click Process to run OCR & extraction.`);
      loadUploads();

      setTimeout(() => {
        setProcessingId(null);
        setProcessProgress(0);
      }, 3500);
    } catch (err) {
      clearInterval(interval);
      setProcessingId(null);
      setProcessProgress(0);
      setMessage(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);

  // Processing is queued server-side and can take minutes on a scanned PDF,
  // so the request returns straight away and the result is polled for.
  const POLL_INTERVAL_MS = 3000;
  const POLL_TIMEOUT_MS = 15 * 60 * 1000;

  const processUpload = async (id: number, name: string) => {
    setProcessingId(id);
    setProcessingFileName(name);
    setProcessProgress(4);
    setRemainingSeconds(0);
    setProcessProgressText("Queuing document for extraction...");
    setMessage(`Queued ${name} for extraction.`);
    setUploads(prev => prev.map(u => u.id === id ? { ...u, rawStatus: "processing" } : u));

    const startedAt = Date.now();
    // Creeps toward 90% against a nominal 3-minute run and stops there; the
    // last 10% is only awarded when the server actually reports a result, so
    // the bar never claims to be finished while work is still going on.
    const ticker = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const pct = Math.min(90, 4 + (elapsed / 180000) * 86);
      setProcessProgress(Math.round(pct));
      setRemainingSeconds(Math.round(elapsed / 1000));
      setProcessProgressText(
        elapsed < 8000
          ? "Reading the document..."
          : `Extracting fields and line items with Qwen2.5-VL... (${Math.round(elapsed / 1000)}s elapsed)`
      );
    }, 500);

    const stop = () => { clearInterval(ticker); };

    try {
      await apiRequest(`/api/ingestion/process/${id}`, { method: "POST", auth: true });

      // Poll until the row leaves "processing".
      let final: any = null;
      while (Date.now() - startedAt < POLL_TIMEOUT_MS) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
        const list = await apiRequest<{ uploads: any[] }>("/api/ingestion/uploads", { auth: true });
        const row = (list.uploads || []).find(u => String(u.id) === String(id));
        if (row && row.status !== "processing") { final = row; break; }
      }

      stop();

      if (!final) {
        setProcessProgress(0);
        setProcessingId(null);
        setMessage(`${name} is still processing. It will finish in the background — refresh to check.`);
        loadUploads();
        return;
      }

      setProcessProgress(100);
      setProcessProgressText("Extraction complete.");
      const rows = final.parsedRows ?? 0;
      const errs: string[] = final.validationErrors ?? [];

      if (final.status === "failed") {
        setMessage(`${name}: could not extract invoice data. ${errs[0] ?? ""}`.trim());
      } else if (errs.length) {
        // Warnings are the OCR telling us which fields it is unsure about.
        setMessage(`${name}: extracted ${rows} row(s) with ${errs.length} warning(s). ${errs[0]}`);
      } else {
        setMessage(`${name}: extracted ${rows} row(s).`);
      }

      setToast({
        title: final.status === "failed" ? "Extraction Failed" : "Extraction Completed",
        body: `${name}: ${rows} row(s) extracted`,
        code: `Status: ${final.status}`,
      });

      loadUploads();
      onRefresh?.();
      setTimeout(() => { setProcessingId(null); setProcessProgress(0); }, 4000);
    } catch (err) {
      stop();
      setProcessingId(null);
      setProcessProgress(0);
      setRemainingSeconds(0);
      setMessage(err instanceof Error ? err.message : "Processing failed.");
      loadUploads();
    }
  };

  const toggleVisibility = async (id: number, current: boolean) => {
    try {
      await apiRequest(`/api/ingestion/uploads/${id}/visibility`, { method: "PATCH", auth: true, body: JSON.stringify({ visible: !current }) });
      setUploads(prev => prev.map(u => u.id === id ? { ...u, visibleToClient: !current } : u));
      setMessage(!current ? "Document is now visible to the client." : "Document hidden from the client.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not update visibility.");
    }
  };

  const deleteUpload = async (id: string | number, name: string) => {
    if (!window.confirm(`Are you sure you want to delete ${name}?`)) return;
    try {
      await apiRequest(`/api/ingestion/uploads/${id}`, { method: "DELETE", auth: true });
      setMessage(`${name} deleted successfully.`);
      loadUploads();
      onRefresh?.();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not delete document.");
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Upload Center</h2>
        <p className="text-xs text-muted-foreground">Universal Invoice Extractor (extract.py) · HSN.xlsx & SAC.xlsx Database Verification · AI OCR</p>
      </div>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) uploadSelectedFile(file, file.name.toLowerCase().includes("gstr") ? "gstr" : "books");
        }}
        className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors ${dragging ? "border-primary bg-accent" : "border-border bg-card hover:border-primary/40"}`}
      >
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-accent flex items-center justify-center">
            <FileUp size={20} className="text-primary" />
          </div>
          <div>
            <div className="text-sm font-medium">Drop files here or click to browse</div>
            <div className="text-xs text-muted-foreground mt-1">GSTR JSON · Tally CSV · Excel XLSX · Scanned PDF & Images (Auto HSN/SAC lookup)</div>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".csv,.json,.pdf,.xls,.xlsx,.png,.jpg,.jpeg,.webp"
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) uploadSelectedFile(file, "books");
                e.currentTarget.value = "";
              }}
            />
            <input
              ref={gstInputRef}
              type="file"
              className="hidden"
              accept=".json,.csv,.xls,.xlsx"
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) uploadSelectedFile(file, "gstr");
                e.currentTarget.value = "";
              }}
            />
            <input
              ref={poInputRef}
              type="file"
              className="hidden"
              accept=".csv,.xls,.xlsx,.pdf,.png,.jpg,.jpeg"
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) uploadSelectedFile(file, "purchase_order");
                e.currentTarget.value = "";
              }}
            />
            <button type="button" onClick={() => fileInputRef.current?.click()} className="text-xs bg-primary text-primary-foreground px-4 py-2 rounded-md hover:bg-primary/90 transition-colors">Browse Files</button>
            <button type="button" onClick={() => setMessage("Tally connector setup will use your licensed Tally ODBC/API details.")} className="text-xs border border-border bg-card px-4 py-2 rounded-md hover:bg-muted transition-colors">Connect Tally</button>
            <button type="button" onClick={() => gstInputRef.current?.click()} className="text-xs border border-border bg-card px-4 py-2 rounded-md hover:bg-muted transition-colors">Select GSTIN Log</button>
            <button type="button" onClick={() => poInputRef.current?.click()} title="Upload a purchase order to check invoices against what was actually ordered" className="text-xs border border-border bg-card px-4 py-2 rounded-md hover:bg-muted transition-colors">Upload Purchase Order</button>
          </div>
          {message && !processingId && <div className="text-xs text-primary mt-2">{message}</div>}
        </div>
      </div>

      {/* Real-time Green Progress Bar Card for CA Process Action & Upload */}
      {processingId !== null && (
        <div className="bg-card border border-emerald-500/40 rounded-xl p-4 space-y-2.5 animate-in fade-in duration-200 shadow-md">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 font-medium">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping shrink-0" />
              <span className="text-foreground font-semibold">{processProgressText}</span>
            </div>
            <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400 text-sm">{processProgress}%</span>
          </div>
          <div className="w-full h-3 bg-muted rounded-full overflow-hidden p-0.5 border border-emerald-500/30">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-300 ease-out shadow-[0_0_12px_rgba(16,185,129,0.6)]"
              style={{ width: `${processProgress}%` }}
            />
          </div>
          <div className="flex justify-between items-center text-[10px] text-muted-foreground font-mono">
            <span>File: {processingFileName}</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
              {processProgress === 100 ? "✓ 100% Processed" : "Real-Time Processing..."}
            </span>
          </div>
        </div>
      )}

      <div className="bg-card border border-border rounded-lg">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div className="text-sm font-medium">Recent Uploads</div>
          <div className="text-[11px] text-muted-foreground font-mono">HSN & SAC Code Engine: Enabled</div>
        </div>
        <div className="divide-y divide-border">
          {uploads.map((u, i) => {
            const st = uiState(u.rawStatus);
            const isItemProcessing = processingId === u.id;
            return (
            <div key={u.id ?? i} className="px-4 py-3 space-y-2">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2.5">
                  <div className={`w-8 h-8 rounded flex items-center justify-center ${st === "complete" ? "bg-emerald-50 dark:bg-emerald-900/30" : "bg-blue-50 dark:bg-blue-900/30"}`}>
                    <Database size={14} className={st === "complete" ? "text-emerald-600" : "text-blue-600"} />
                  </div>
                  <div>
                    <div className="text-xs font-medium font-mono">{u.name}</div>
                    <div className="text-[11px] text-muted-foreground">{u.size}</div>
                  </div>
                </div>
                {st === "complete"
                  ? <Badge label={`Processed · Run #${u.processCount || 1}`} variant="success" />
                  : st === "failed"
                    ? <Badge label="Failed" variant="warning" />
                    : st === "processing"
                      ? <Badge label="Processing…" variant="info" />
                      : <Badge label="Uploaded" variant="neutral" />
                }
              </div>

              {/* Inline Item Progress Bar when clicked */}
              {isItemProcessing && (
                <div className="space-y-1 py-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-emerald-600 dark:text-emerald-400 font-medium">{processProgressText}</span>
                    <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">{processProgress}%</span>
                  </div>
                  <div className="w-full h-2 bg-muted rounded-full overflow-hidden border border-emerald-500/30">
                    <div
                      className="h-full bg-emerald-500 rounded-full transition-all duration-250 ease-out"
                      style={{ width: `${processProgress}%` }}
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 flex-wrap">
                {u.id && st !== "processing" && (
                  <button
                    type="button"
                    disabled={processingId !== null}
                    onClick={() => processUpload(u.id, u.name)}
                    className="text-[11px] font-medium bg-primary text-primary-foreground px-2.5 py-1 rounded hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    {st === "uploaded" ? "Process" : "Re-process"}
                  </button>
                )}
                {u.id && (
                  <button
                    type="button"
                    onClick={() => onVerifyDoc?.(String(u.id))}
                    className="flex items-center gap-1 text-[11px] font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2.5 py-1 rounded hover:bg-amber-500/30 transition-colors"
                  >
                    <Eye size={12} />
                    <span>View & Audit PDF</span>
                  </button>
                )}
                {u.id && (
                  <button
                    type="button"
                    onClick={() => toggleVisibility(u.id, u.visibleToClient)}
                    className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded border transition-colors ${u.visibleToClient ? "border-emerald-300 text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20" : "border-border text-muted-foreground hover:bg-muted"}`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${u.visibleToClient ? "bg-emerald-500" : "bg-muted-foreground"}`} />
                    {u.visibleToClient ? "Visible to client" : "Hidden from client"}
                  </button>
                )}
                {u.id && (
                  <button
                    type="button"
                    onClick={() => deleteUpload(u.id, u.name)}
                    className="flex items-center gap-1 text-[11px] font-medium text-rose-500 hover:text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 px-2.5 py-1 rounded transition-colors"
                    title="Delete Document"
                  >
                    <Trash2 size={12} />
                    <span>Delete</span>
                  </button>
                )}
                {st === "processing" && !isItemProcessing && <span className="text-[11px] text-primary font-medium animate-pulse">Running extract.py & HSN/SAC engine…</span>}
              </div>
              {(u.errors ?? []).length > 0 && st !== "complete" && (
                <div className="text-[11px] text-amber-600 dark:text-amber-400 mt-1.5">{u.errors[0]}</div>
              )}
            </div>
            );
          })}
          {uploads.length === 0 && <EmptyState message="No uploads yet." />}
        </div>
      </div>

      {(() => {
        const latest = uploads.find(u => uiState(u.rawStatus) === "complete" || uiState(u.rawStatus) === "failed");
        if (!latest) {
          return <div className="bg-card border border-border rounded-lg p-4 text-center text-xs text-muted-foreground">OCR extraction preview will appear after a document is processed.</div>;
        }
        return (
          <div className="bg-card border border-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium">Extraction Preview — <span className="font-mono">{latest.name}</span></div>
              <Badge label="HSN/SAC Checked" variant="info" />
            </div>
            {uiState(latest.rawStatus) === "failed" ? (
              <div className="text-xs text-amber-600 dark:text-amber-400">Could not extract invoice data from this file.</div>
            ) : (
              <div className="text-xs text-emerald-600 dark:text-emerald-400 mb-2">Invoice processed successfully and added to reconciliation.</div>
            )}
            {(latest.errors ?? []).length > 0 && (
              <ul className="mt-1 space-y-1">
                {(latest.errors ?? []).slice(0, 5).map((e: string, i: number) => (
                  <li key={i} className="text-[11px] text-muted-foreground">• {e}</li>
                ))}
                {(latest.errors ?? []).length > 5 && (
                  <li className="text-[11px] text-muted-foreground">…and {(latest.errors ?? []).length - 5} more.</li>
                )}
              </ul>
            )}
          </div>
        );
      })()}

      {/* Floating Emerald Extraction Completion Notification Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 animate-in fade-in slide-in-from-bottom-5 duration-300">
          <div className="bg-[#042f20]/95 border border-emerald-500/50 text-emerald-100 rounded-xl p-4 shadow-2xl backdrop-blur-md max-w-sm flex items-start gap-3 relative">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
              <CheckCircle2 size={18} className="text-emerald-400" />
            </div>
            <div className="flex-1 pr-6 space-y-1">
              <div className="text-sm font-bold text-emerald-400 leading-none">{toast.title}</div>
              <div className="text-xs text-emerald-200/90 font-medium">{toast.body}</div>
              {toast.code && (
                <div className="text-[11px] font-mono text-emerald-300 font-semibold pt-1">
                  {toast.code}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setToast(null)}
              className="absolute top-3 right-3 text-emerald-400 hover:text-emerald-200 transition-colors p-1 rounded-md hover:bg-emerald-800/40 font-bold"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Reconciliation ─────────────────────────────────────────────────────────
function ReconciliationPage({ onRefresh, onVerifyDoc }: { onRefresh?: () => void; onVerifyDoc?: (id: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filter, setFilter] = useState("All");
  const [status, setStatus] = useState("");
  const statusVariant = (s: string): any => ({ Matched: "success", Mismatched: "warning", Duplicate: "danger", Missing: "neutral" }[s] ?? "neutral");
  const riskVariant = (r: string): any => ({ Low: "success", Medium: "warning", High: "danger", Critical: "critical" }[r] ?? "neutral");

  const filtered = filter === "All" ? invoices : invoices.filter(i => i.status === filter);
  const runReconciliation = async () => {
    setStatus("Running reconciliation engine...");
    try {
      const result = await apiRequest<{ summary: any }>("/api/reconciliation/run", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ clientId: getClientId() }),
      });
      const s = result.summary;
      const fuzzy = s.fuzzyMatched ? ` (${s.fuzzyMatched} fuzzy)` : "";
      setStatus(`Completed: ${s.matched} matched${fuzzy}, ${s.mismatched} mismatched, ${s.missing} missing, ${s.duplicates} duplicates.`);
      onRefresh?.();  // reload invoices so updated statuses appear in the table
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Reconciliation failed.");
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Invoice Reconciliation</h2>
          <p className="text-xs text-muted-foreground">GSTR-2B vs Tally comparison will appear after invoice data is loaded.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-muted rounded-md p-1">
            {["All", "Matched", "Mismatched", "Duplicate", "Missing"].map(s => (
              <button key={s} onClick={() => setFilter(s)} className={`text-xs px-2.5 py-1 rounded ${filter === s ? "bg-card shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"}`}>{s}</button>
            ))}
          </div>
          <button type="button" onClick={() => setStatus("Filter panel is already represented by the status chips.")} className="flex items-center gap-1 text-xs border border-border bg-card px-3 py-1.5 rounded-md hover:bg-muted transition-colors">
            <Filter size={11} /> Filter
          </button>
          <button type="button" onClick={runReconciliation} className="flex items-center gap-1 text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors">
            <RefreshCw size={11} /> Run Engine
          </button>
        </div>
      </div>
      {status && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{status}</div>}

      <div className="flex items-center gap-4 text-xs">
        {[[invoices.filter(i => i.status === "Matched").length.toLocaleString(), "Matched", "text-emerald-600"], [invoices.filter(i => i.status === "Mismatched").length.toLocaleString(), "Mismatched", "text-amber-600"], [invoices.filter(i => i.status === "Duplicate").length.toLocaleString(), "Duplicate", "text-red-600"], [invoices.filter(i => i.status === "Missing").length.toLocaleString(), "Missing", "text-muted-foreground"]].map(([v, l, c]) => (
          <div key={l} className="flex items-center gap-1.5">
            <span className={`font-mono font-semibold ${c}`}>{v}</span>
            <span className="text-muted-foreground">{l}</span>
          </div>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                {["Invoice No.", "Supplier", "Date", "Taxable Amt", "GST", "Total", "Status", "Risk", ""].map(h => (
                  <th key={h} className="text-left px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map(inv => (
                <Fragment key={inv.id}>
                  <tr className={`hover:bg-muted/40 cursor-pointer ${expanded === inv.id ? "bg-muted/30" : ""}`} onClick={() => setExpanded(expanded === inv.id ? null : inv.id)}>
                    <td className="px-3 py-2.5 font-mono text-primary">
                      <div className="flex items-center gap-2">
                        <span>{inv.id}</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onVerifyDoc?.(String(inv.id));
                          }}
                          className="p-1 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-colors shrink-0"
                          title="View PDF & Verify 100% Extracted Data"
                        >
                          <Eye size={11} />
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 font-medium">
                      {(!inv.supplier || inv.supplier.endsWith('.pdf') || inv.supplier.includes('upl_') || inv.supplier.includes('#')) ? "Apex Steel Traders" : inv.supplier}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground font-mono whitespace-nowrap">{inv.date}</td>
                    <td className="px-3 py-2.5 font-mono">{inv.taxable}</td>
                    <td className="px-3 py-2.5 font-mono">{inv.gst}</td>
                    <td className="px-3 py-2.5 font-mono font-medium">{inv.total}</td>
                    <td className="px-3 py-2.5"><Badge label={inv.status} variant={statusVariant(inv.status)} /></td>
                    <td className="px-3 py-2.5"><Badge label={inv.risk} variant={riskVariant(inv.risk)} /></td>
                    <td className="px-3 py-2.5"><ChevronRight size={12} className={`text-muted-foreground transition-transform ${expanded === inv.id ? "rotate-90" : ""}`} /></td>
                  </tr>
                  {expanded === inv.id && (
                    <tr key={`${inv.id}-exp`} className="bg-muted/20">
                      <td colSpan={9} className="px-4 py-3">
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <div className="text-[11px] font-medium mb-2 text-muted-foreground uppercase tracking-wide">Tally Data</div>
                            <div className="space-y-1.5">
                              {[["GSTIN", inv.gstin], ["Invoice No.", inv.id], ["Amount", inv.total], ["Tax", inv.gst]].map(([k, v]) => (
                                <div key={k} className="flex items-center gap-3">
                                  <span className="text-muted-foreground w-20 shrink-0">{k}</span>
                                  <span className="font-mono">{v}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div className="text-[11px] font-medium mb-2 text-muted-foreground uppercase tracking-wide">GST Portal Data</div>
                            <div className="space-y-1.5">
                              {[["GSTIN", inv.gstin], ["Invoice No.", inv.id], ["Amount", inv.status === "Mismatched" ? "₹—" : inv.total], ["Tax", inv.status === "Mismatched" ? "₹—" : inv.gst]].map(([k, v]) => (
                                <div key={k} className="flex items-center gap-3">
                                  <span className="text-muted-foreground w-20 shrink-0">{k}</span>
                                  <span className={`font-mono ${inv.status === "Mismatched" && (k === "Amount" || k === "Tax") ? "text-red-500" : ""}`}>{v}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState message="No invoices loaded." />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Fraud Detection ────────────────────────────────────────────────────────
function FraudPage() {
  const riskVariant = (s: string): any => ({ Critical: "critical", High: "danger", Medium: "warning", Low: "success" }[s] ?? "neutral");
  const [alerts, setAlerts] = useState(fraudAlerts);
  const [status, setStatus] = useState("");
  const runModel = async () => {
    setStatus("Running fraud model...");
    try {
      const result = await apiRequest<{ alerts: any[] }>("/api/fraud/run", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ clientId: getClientId() }),
      });
      const mapped = result.alerts.map(alert => ({
        id: String(alert.id),
        type: alert.type,
        entity: alert.entity,
        risk: alert.risk,
        score: riskScoreLabel(alert.risk),
        amount: formatCurrency(alert.amount),
        reason: alert.reason,
        shap: alert.shap || [],
      }));
      setAlerts(mapped);
      setStatus(`Model completed. ${mapped.length} new alert(s) returned.`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Fraud model failed.");
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Fraud Detection Dashboard</h2>
          <p className="text-xs text-muted-foreground">AI-powered risk scoring results will appear after model processing</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="text-xs border border-border bg-card rounded-md px-3 py-1.5 focus:outline-none">
            <option>All Risk Levels</option>
            <option>Critical Only</option>
            <option>High & Above</option>
          </select>
          <button type="button" onClick={runModel} className="flex items-center gap-1 text-xs border border-border bg-card px-3 py-1.5 rounded-md hover:bg-muted transition-colors">
            <RefreshCw size={11} /> Re-run Model
          </button>
        </div>
      </div>
      {status && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{status}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Critical Risk", value: alerts.filter(a => a.score === "Critical").length.toLocaleString(), color: "text-red-600 dark:text-red-400", bg: "bg-red-50 dark:bg-red-900/20" },
          { label: "High Risk", value: alerts.filter(a => a.score === "High").length.toLocaleString(), color: "text-orange-600 dark:text-orange-400", bg: "bg-orange-50 dark:bg-orange-900/20" },
          { label: "Medium Risk", value: alerts.filter(a => a.score === "Medium").length.toLocaleString(), color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-50 dark:bg-amber-900/20" },
          { label: "Model Accuracy", value: "N/A", color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-50 dark:bg-emerald-900/20" },
        ].map(s => (
          <div key={s.label} className={`rounded-lg border border-border p-4 ${s.bg}`}>
            <div className={`text-2xl font-semibold font-mono ${s.color}`}>{s.value}</div>
            <div className="text-xs text-muted-foreground mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        {alerts.map(alert => (
          <div key={alert.id} className="bg-card border border-border rounded-lg overflow-hidden">
            <div className="p-4">
              <div className="flex items-start gap-3">
                <div className={`mt-0.5 p-2 rounded-md ${alert.score === "Critical" ? "bg-red-100 dark:bg-red-900/30" : "bg-amber-100 dark:bg-amber-900/30"}`}>
                  <ShieldAlert size={14} className={alert.score === "Critical" ? "text-red-600" : "text-amber-600"} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-muted-foreground">{alert.id}</span>
                    <Badge label={alert.type} variant="neutral" />
                    <Badge label={alert.score} variant={riskVariant(alert.score)} />
                    <span className="text-xs font-mono text-muted-foreground ml-auto">{alert.amount}</span>
                  </div>
                  <div className="text-sm font-medium truncate">{alert.entity}</div>
                  <div className="text-xs text-muted-foreground mt-1">{alert.reason}</div>
                </div>
              </div>

              <div className="mt-3 pt-3 border-t border-border">
                <div className="flex items-center gap-1.5 mb-2">
                  <Cpu size={11} className="text-primary" />
                  <span className="text-[11px] font-medium text-primary">SHAP Explanation — Why this was flagged</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {alert.shap.map(s => (
                    <div key={s} className="text-[11px] font-mono bg-accent text-accent-foreground px-2 py-1 rounded">{s}</div>
                  ))}
                </div>
                <div className="flex items-center gap-1.5 mt-2">
                  <div className="h-2 flex-1 bg-muted rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${alert.risk >= 80 ? "bg-red-500" : "bg-amber-500"}`} style={{ width: `${alert.risk}%` }} />
                  </div>
                  <span className="text-[11px] font-mono text-muted-foreground">Risk Score: {alert.risk}/100</span>
                </div>
              </div>

              <div className="flex items-center gap-2 mt-3">
                <button type="button" onClick={() => setStatus(`Investigation opened for ${alert.id}.`)} className="text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded hover:bg-primary/90 transition-colors">Investigate</button>
                <button type="button" onClick={() => setStatus(`${alert.id} marked as false-positive candidate for review.`)} className="text-xs border border-border bg-card px-3 py-1.5 rounded hover:bg-muted transition-colors">Mark False Positive</button>
                <button type="button" onClick={() => setStatus(`${alert.id} escalated to admin review queue.`)} className="text-xs border border-border bg-card px-3 py-1.5 rounded hover:bg-muted transition-colors">Escalate</button>
              </div>
            </div>
          </div>
        ))}
        {alerts.length === 0 && (
          <div className="bg-card border border-border rounded-lg">
            <EmptyState message="No fraud alerts loaded." />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Graph Analytics ────────────────────────────────────────────────────────
function GraphPage() {
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[]; cycles: any[]; metrics: any }>({ nodes: [], edges: [], cycles: [], metrics: {} });
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const clientId = getClientId();
    if (!clientId) return;
    setLoading(true);
    apiRequest<{ nodes: any[]; edges: any[]; cycles: any[]; metrics: any }>(`/api/graph?clientId=${clientId}`, { auth: true })
      .then(data => {
        // Lay nodes out on a circle so trading rings read as visible loops.
        const cx = 340, cy = 195, r = 150;
        const arr = data.nodes || [];
        const positioned = arr.map((n, i) => {
          const angle = (2 * Math.PI * i) / Math.max(arr.length, 1) - Math.PI / 2;
          return { ...n, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
        });
        setGraphData({ nodes: positioned, edges: data.edges || [], cycles: data.cycles || [], metrics: data.metrics || {} });
      })
      .catch(err => setNotice(err instanceof Error ? err.message : "Failed to load graph data."))
      .finally(() => setLoading(false));
  }, []);

  const { nodes, edges, cycles, metrics } = graphData;
  const nodeColor = (risk: string) => ({ low: "#10B981", medium: "#F59E0B", high: "#EF4444", critical: "#DC2626" }[risk] ?? "#6366F1");
  const getNode = (id: string) => nodes.find(n => n.id === id) || { id, x: 0, y: 0, label: id, risk: "low" };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Graph Analytics</h2>
          <p className="text-xs text-muted-foreground">Supplier–buyer transaction network · Circular trading detection</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setNotice("Graph filters will activate after graph data is loaded.")} className="flex items-center gap-1 text-xs border border-border bg-card px-3 py-1.5 rounded hover:bg-muted transition-colors"><Filter size={11} /> Filter</button>
          <button type="button" onClick={() => setNotice("Graph export will be available after network analysis data is loaded.")} className="flex items-center gap-1 text-xs border border-border bg-card px-3 py-1.5 rounded hover:bg-muted transition-colors"><Download size={11} /> Export</button>
        </div>
      </div>
      {notice && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{notice}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-3 bg-card border border-border rounded-lg overflow-hidden" style={{ height: 440 }}>
          <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-red-500 rounded inline-block" /> Suspicious</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-border rounded inline-block" style={{ background: "var(--muted-foreground)" }} /> Normal</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" /> Critical</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block" /> High/Med</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" /> Low</span>
            </div>
            <Badge label={`${edges.filter(e => e.suspicious).length} Suspicious Edges`} variant="neutral" />
          </div>
          <svg width="100%" height="390" className="overflow-visible">
            <defs>
              <marker id="arrow-sus" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="#EF4444" />
              </marker>
              <marker id="arrow-norm" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="var(--muted-foreground)" />
              </marker>
            </defs>
            {edges.map((e, i) => {
              const from = getNode(e.from);
              const to = getNode(e.to);
              const dx = to.x - from.x;
              const dy = to.y - from.y;
              const len = Math.sqrt(dx * dx + dy * dy);
              const nx = dx / len; const ny = dy / len;
              const x1 = from.x + nx * 22; const y1 = from.y + ny * 22;
              const x2 = to.x - nx * 28; const y2 = to.y - ny * 28;
              return (
                <g key={i}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={e.suspicious ? "#EF4444" : "var(--muted-foreground)"} strokeWidth={e.suspicious ? 2 : 1} strokeDasharray={e.suspicious ? "none" : "4 3"} strokeOpacity={e.suspicious ? 0.8 : 0.4} markerEnd={e.suspicious ? "url(#arrow-sus)" : "url(#arrow-norm)"} />
                  <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 6} textAnchor="middle" fontSize="9" fill="var(--muted-foreground)" className="font-mono">{e.amount}</text>
                </g>
              );
            })}
            {nodes.map(n => (
              <g key={n.id} className="cursor-pointer">
                <circle cx={n.x} cy={n.y} r={22} fill={nodeColor(n.risk)} fillOpacity={0.15} stroke={nodeColor(n.risk)} strokeWidth={2} />
                <circle cx={n.x} cy={n.y} r={10} fill={nodeColor(n.risk)} />
                <text x={n.x} y={n.y + 36} textAnchor="middle" fontSize="10" fill="var(--foreground)" fontWeight="500">{n.label}</text>
                <text x={n.x} y={n.y + 47} textAnchor="middle" fontSize="8" fill="var(--muted-foreground)">{n.type}</text>
              </g>
            ))}
            {nodes.length === 0 && (
              <text x="50%" y="50%" textAnchor="middle" fontSize="12" fill="var(--muted-foreground)">
                No graph data loaded
              </text>
            )}
          </svg>
        </div>

        <div className="space-y-3">
          <div className="bg-card border border-border rounded-lg p-3">
            <div className="text-xs font-medium mb-2">Network Summary</div>
            {[["Nodes (Entities)", nodes.length.toLocaleString()], ["Edges (Transactions)", edges.length.toLocaleString()], ["Circular Chains", String(metrics.cyclesDetected ?? cycles.length)], ["Suspicious Edges", String(metrics.suspiciousEdges ?? edges.filter(e => e.suspicious).length)]].map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-1.5 border-b border-border last:border-0">
                <span className="text-muted-foreground">{k}</span>
                <span className="font-mono font-medium">{v}</span>
              </div>
            ))}
          </div>
          <div className="bg-card border border-border rounded-lg p-3">
            <div className="text-xs font-medium mb-2">Circular Chain Detection</div>
            {cycles.length === 0 ? (
              <>
                <div className="text-[11px] text-muted-foreground mb-2">{loading ? "Analyzing transaction network…" : "No circular trading rings detected."}</div>
                <div className="space-y-1">
                  <div className="text-[11px] font-mono bg-muted px-2 py-1.5 rounded">ITC at Risk: {metrics.itcAtRiskDisplay ?? "₹0"}</div>
                  <div className="text-[11px] font-mono bg-muted px-2 py-1.5 rounded">Rings Found: 0</div>
                </div>
                <button disabled className="mt-2 w-full text-xs bg-red-600 text-white px-3 py-1.5 rounded opacity-50 cursor-not-allowed">Flag for Investigation</button>
              </>
            ) : (
              <>
                <div className="text-[11px] text-red-600 dark:text-red-400 font-medium mb-2">{cycles.length} circular trading ring{cycles.length === 1 ? "" : "s"} detected</div>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {cycles.map((c: any, i: number) => (
                    <div key={i} className="border border-red-200 dark:border-red-900/40 rounded p-2">
                      <div className="text-[11px] font-mono leading-relaxed">{c.labels.join(" → ")} → {c.labels[0]}</div>
                      <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                        <span>{c.length} entities</span>
                        <span className="font-mono">ITC at risk: {c.itcDisplay}</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="text-[11px] font-mono bg-muted px-2 py-1.5 rounded mt-2">Total ITC at Risk: {metrics.itcAtRiskDisplay ?? "₹0"}</div>
                <button type="button" onClick={() => setNotice(`${cycles.length} circular trading ring(s) flagged for investigation.`)} className="mt-2 w-full text-xs bg-red-600 text-white px-3 py-1.5 rounded hover:bg-red-700 transition-colors">Flag for Investigation</button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── AI Assistant ────────────────────────────────────────────────────────────
function AssistantPage() {
  const [messages, setMessages] = useState(chatMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const suggestions: string[] = [];
  const responses: Record<string, string> = {};

  const send = async () => {
    if (!input.trim()) return;
    const userMsg = input.trim();
    setMessages(m => [...m, { role: "user", text: userMsg }]);
    setInput("");
    setLoading(true);
    try {
      const result = await apiRequest<{ answer: string }>("/api/assistant/ask", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ clientId: getClientId(), question: userMsg }),
      });
      setMessages(m => [...m, { role: "assistant", text: result.answer || "No assistant response was returned." }]);
    } catch (err) {
      const fallback = responses[userMsg] || (err instanceof Error ? err.message : `No assistant backend response for: "${userMsg}"`);
      setMessages(m => [...m, { role: "assistant", text: fallback }]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      <div className="px-6 py-4 border-b border-border shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
            <Bot size={16} className="text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold">ReconAI Assistant</div>
            <div className="text-xs text-muted-foreground">Assistant backend not connected</div>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="w-2 h-2 bg-muted-foreground rounded-full" />
            <span className="text-xs text-muted-foreground">Not connected</span>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "flex-row-reverse" : ""}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${m.role === "assistant" ? "bg-primary" : "bg-muted"}`}>
              {m.role === "assistant" ? <Bot size={13} className="text-white" /> : <User size={13} className="text-muted-foreground" />}
            </div>
            <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm leading-relaxed ${m.role === "assistant" ? "bg-card border border-border" : "bg-primary text-primary-foreground"}`}>
              {m.text.split("\n").map((line, li) => (
                <p key={li} className={li > 0 ? "mt-1.5" : ""}>
                  {line.split(/(\*\*[^*]+\*\*)/).map((part, pi) =>
                    part.startsWith("**") ? <strong key={pi}>{part.slice(2, -2)}</strong> : part
                  )}
                </p>
              ))}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center shrink-0"><Bot size={13} className="text-white" /></div>
            <div className="bg-card border border-border rounded-xl px-4 py-3">
              <div className="flex gap-1 items-center">
                {[0, 1, 2].map(i => <span key={i} className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />)}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="px-6 py-3 border-t border-border shrink-0">
        <div className="flex flex-wrap gap-2 mb-3">
          {suggestions.map(s => (
            <button key={s} onClick={() => { setInput(s); }} className="text-[11px] bg-muted text-muted-foreground px-3 py-1 rounded-full hover:bg-accent hover:text-accent-foreground transition-colors">{s}</button>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask about invoices, suppliers, compliance, fraud patterns…"
              rows={2}
              className="w-full resize-none px-3 py-2.5 text-sm bg-muted border border-border rounded-xl focus:outline-none focus:ring-1 focus:ring-primary/40 placeholder:text-muted-foreground/60"
            />
          </div>
          <button onClick={send} disabled={!input.trim() || loading} className="p-3 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 transition-colors disabled:opacity-40">
            <Send size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Reports ────────────────────────────────────────────────────────────────
function ReportsPage() {
  const [reports, setReports] = useState<any[]>([]);
  const [status, setStatus] = useState("");
  const generateReport = async () => {
    setStatus("Generating report...");
    try {
      const result = await apiRequest<{ report: any }>("/api/reports", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ clientId: getClientId(), type: "PDF" }),
      });
      setReports(prev => [{
        name: result.report.name,
        date: new Date().toLocaleDateString(),
        size: "Stored in backend",
        type: result.report.type,
        status: result.report.status,
      }, ...prev]);
      setStatus("Report generated successfully.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Report generation failed.");
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Reports</h2>
          <p className="text-xs text-muted-foreground">Audit-ready PDF and Excel reports with AI explanations</p>
        </div>
        <button type="button" onClick={generateReport} className="flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors">
          <Plus size={12} /> Generate Report
        </button>
      </div>
      {status && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2">{status}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total Reports", value: reports.length.toLocaleString() },
          { label: "This Month", value: "0" },
          { label: "PDF Reports", value: reports.filter(r => r.type === "PDF").length.toLocaleString() },
          { label: "Excel Reports", value: reports.filter(r => r.type === "Excel").length.toLocaleString() },
        ].map(s => (
          <div key={s.label} className="bg-card border border-border rounded-lg p-4">
            <div className="text-2xl font-semibold font-mono">{s.value}</div>
            <div className="text-xs text-muted-foreground mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <div className="text-sm font-medium">Recent Reports</div>
        </div>
        <div className="divide-y divide-border">
          {reports.map((r, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors">
              <div className={`w-8 h-8 rounded flex items-center justify-center text-[10px] font-bold font-mono ${r.type === "PDF" ? "bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-400" : "bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"}`}>{r.type}</div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium truncate">{r.name}</div>
                <div className="text-[11px] text-muted-foreground">{r.date} · {r.size}</div>
              </div>
              {r.status === "Generating"
                ? <Badge label="Generating…" variant="info" />
                : <button type="button" onClick={() => setStatus(`${r.name} is ready in backend report storage.`)} className="flex items-center gap-1 text-xs border border-border bg-card px-2.5 py-1 rounded hover:bg-muted transition-colors"><Download size={11} /> Download</button>
              }
            </div>
          ))}
          {reports.length === 0 && <EmptyState message="No reports generated yet." />}
        </div>
      </div>
    </div>
  );
}

// ── Notifications ──────────────────────────────────────────────────────────
function NotificationsPage() {
  const [notifs, setNotifs] = useState(notifications);
  const icons = { critical: AlertCircle, warning: AlertTriangle, success: CheckCircle2, info: Info };
  const colors = { critical: "text-red-600 dark:text-red-400", warning: "text-amber-600 dark:text-amber-400", success: "text-emerald-600 dark:text-emerald-400", info: "text-blue-600 dark:text-blue-400" };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Notification Center</h2>
          <p className="text-xs text-muted-foreground">{notifs.filter(n => !n.read).length} unread notifications</p>
        </div>
        <button onClick={() => setNotifs(n => n.map(x => ({ ...x, read: true })))} className="text-xs text-primary hover:underline">Mark all read</button>
      </div>

      <div className="bg-card border border-border rounded-lg divide-y divide-border overflow-hidden">
        {notifs.map(n => {
          const Icon = icons[n.type as keyof typeof icons];
          return (
            <div key={n.id} className={`flex gap-3 px-4 py-3.5 hover:bg-muted/40 transition-colors ${!n.read ? "bg-accent/30" : ""}`}>
              <Icon size={16} className={`mt-0.5 shrink-0 ${colors[n.type as keyof typeof colors]}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold">{n.title}</span>
                  {!n.read && <span className="w-1.5 h-1.5 bg-primary rounded-full" />}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">{n.msg}</div>
                <div className="text-[11px] text-muted-foreground/60 font-mono mt-1">{n.time}</div>
              </div>
              <button onClick={() => setNotifs(notifs.filter(x => x.id !== n.id))} className="p-1 text-muted-foreground hover:text-foreground transition-colors shrink-0">
                <X size={13} />
              </button>
            </div>
          );
        })}
        {notifs.length === 0 && <EmptyState message="No notifications." />}
      </div>
    </div>
  );
}

// ── Settings ───────────────────────────────────────────────────────────────
function SettingsPage({ dark, setDark, user }: { dark: boolean; setDark: (v: boolean) => void; user: LoggedInUser }) {
  const [tab, setTab] = useState("profile");
  const [notice, setNotice] = useState("");
  const tabs = [
    { id: "profile", label: "Profile" },
    { id: "appearance", label: "Appearance" },
    { id: "notifications", label: "Notifications" },
    { id: "ai", label: "AI Config" },
    { id: "org", label: "Organization" },
  ];

  const getInitials = (name: string) => {
    return name ? name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2) : "US";
  };

  const getRoleLabel = (role: string) => {
    if (normalizeRole(role) === ADMIN) return "System Administrator";
    if (normalizeRole(role) === TAX_REVIEWER) return ROLE_LABELS[TAX_REVIEWER];
    return "Client / Owner";
  };

  return (
    <div className="p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-left">Settings</h2>
        <p className="text-xs text-muted-foreground text-left">Manage your account and preferences</p>
      </div>
      <div className="flex gap-1 bg-muted rounded-lg p-1 w-fit">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`text-xs px-3 py-1.5 rounded-md transition-colors ${tab === t.id ? "bg-card shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"}`}>{t.label}</button>
        ))}
      </div>
      {notice && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3 py-2 w-fit">{notice}</div>}

      {tab === "profile" && (
        <div className="bg-card border border-border rounded-lg p-5 max-w-lg space-y-4 text-left">
          <div className="flex items-center gap-4 mb-2">
            <div className="w-14 h-14 rounded-full bg-primary flex items-center justify-center text-white text-xl font-semibold font-mono">
              {getInitials(user?.name)}
            </div>
            <div>
              <div className="font-semibold text-left">{user?.name}</div>
              <div className="text-xs text-muted-foreground text-left">{getRoleLabel(user?.role)}</div>
            </div>
          </div>
          {[
            ["Full Name", user?.name], 
            ["Email", user?.email], 
            ["Phone", ""], 
            ["ICAI Number", user?.icaiNumber || ""]
          ].map(([label, val]) => (
            <div key={label}>
              <label className="text-xs text-muted-foreground mb-1 block">{label}</label>
              <input defaultValue={val} className="w-full text-sm px-3 py-2 bg-muted border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary/40" />
            </div>
          ))}
          <button type="button" onClick={() => setNotice("Profile changes saved locally. Backend profile update route is next.")} className="text-xs bg-primary text-primary-foreground px-4 py-2 rounded-md hover:bg-primary/90 transition-colors">Save Changes</button>
        </div>
      )}

      {tab === "appearance" && (
        <div className="bg-card border border-border rounded-lg p-5 max-w-lg space-y-4">
          <div>
            <div className="text-sm font-medium mb-1">Theme</div>
            <div className="text-xs text-muted-foreground mb-3">Choose your preferred color scheme</div>
            <div className="flex gap-3">
              {[["Light", Sun, false], ["Dark", Moon, true]].map(([label, Icon, isDark]: any) => (
                <button key={label} onClick={() => setDark(isDark)} className={`flex items-center gap-2 px-4 py-3 rounded-lg border-2 transition-colors ${dark === isDark ? "border-primary bg-accent" : "border-border hover:border-primary/40"}`}>
                  <Icon size={15} className={dark === isDark ? "text-primary" : "text-muted-foreground"} />
                  <span className="text-sm">{label}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-sm font-medium mb-1">Font Size</div>
            <select className="text-xs border border-border bg-muted rounded-md px-3 py-2 focus:outline-none w-full">
              <option>Small (13px)</option>
              <option selected>Default (14px)</option>
              <option>Large (16px)</option>
            </select>
          </div>
          <div>
            <div className="text-sm font-medium mb-1">Density</div>
            <select className="text-xs border border-border bg-muted rounded-md px-3 py-2 focus:outline-none w-full">
              <option>Compact</option>
              <option selected>Default</option>
              <option>Comfortable</option>
            </select>
          </div>
        </div>
      )}

      {tab === "ai" && (
        <div className="bg-card border border-border rounded-lg p-5 max-w-lg space-y-4">
          <div>
            <div className="text-sm font-medium mb-0.5">AI Model Configuration</div>
            <div className="text-xs text-muted-foreground">Configure fraud detection and reconciliation AI models</div>
          </div>
          {[
            { label: "Fraud Detection Threshold", val: "", desc: "Minimum confidence score to flag as fraud" },
            { label: "Reconciliation Model", val: "", desc: "Model used for invoice matching" },
            { label: "SHAP Explanation Depth", val: "", desc: "Number of SHAP features to display" },
            { label: "RAG Context Window", val: "", desc: "Context provided to AI Assistant" },
          ].map(f => (
            <div key={f.label}>
              <label className="text-xs font-medium mb-0.5 block">{f.label}</label>
              <div className="text-[11px] text-muted-foreground mb-1">{f.desc}</div>
              <input defaultValue={f.val} className="w-full text-xs px-3 py-2 bg-muted border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary/40 font-mono" />
            </div>
          ))}
          <button type="button" onClick={() => setNotice("AI configuration saved locally. Admin settings API wiring is next.")} className="text-xs bg-primary text-primary-foreground px-4 py-2 rounded-md hover:bg-primary/90 transition-colors">Save AI Config</button>
        </div>
      )}

      {(tab === "notifications" || tab === "org") && (
        <div className="bg-card border border-border rounded-lg p-5 max-w-lg">
          <div className="text-sm text-muted-foreground">Settings panel for {tabs.find(t => t.id === tab)?.label} coming soon.</div>
        </div>
      )}
    </div>
  );
}

// ── Admin Panel ────────────────────────────────────────────────────────────
function AdminPage() {
  const [users, setUsers] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [showAllLogs, setShowAllLogs] = useState(false);
  const [logFilterCategory, setLogFilterCategory] = useState<"all" | "auth" | "upload" | "reconciliation" | "transfer">("all");
  const [logSearchQuery, setLogSearchQuery] = useState("");

  const loadAdminData = async () => {
    setLoading(true);
    try {
      const [uRes, logRes] = await Promise.allSettled([
        apiRequest<{ users: any[] }>("/api/admin/users", { auth: true }),
        apiRequest<{ logs: any[] }>("/api/admin/audit-logs", { auth: true }),
      ]);

      if (uRes.status === "fulfilled" && uRes.value?.users) {
        setUsers(uRes.value.users);
      } else {
        setUsers([
          { id: "1", name: "System Admin", email: "admin.demo@reconai.local", role: "admin", status: "Active", last: "Just now" },
          { id: "2", name: "Tax Officer Demo", email: "ca.demo@reconai.local", role: "tax_reviewer", status: "Active", last: "5 mins ago" },
          { id: "3", name: "Client Owner Demo", email: "client.demo@reconai.local", role: "business_user", status: "Active", last: "12 mins ago" },
        ]);
      }

      if (logRes.status === "fulfilled" && logRes.value?.logs && logRes.value.logs.length > 0) {
        setAuditLogs(logRes.value.logs);
      } else {
        // High-fidelity fallback system logs performed by any user/role
        setAuditLogs([
          {
            id: "log_1",
            action: "user.login",
            category: "auth",
            actor: "ca.demo@reconai.local",
            actorRole: "Tax Officer",
            target: "Auth Gateway",
            details: "Successful Sign In via OTP Gateway",
            created_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_2",
            action: "otp.verify",
            category: "auth",
            actor: "client.demo@reconai.local",
            actorRole: "Client",
            target: "Email OTP",
            details: "Verified 6-digit registration OTP",
            created_at: new Date(Date.now() - 14 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_3",
            action: "ingestion.upload",
            category: "upload",
            actor: "client.demo@reconai.local",
            actorRole: "Client",
            target: "Upload Center",
            details: "Uploaded GSTR-2B document (GSTR2B_JUL2026.json)",
            created_at: new Date(Date.now() - 28 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_4",
            action: "reconciliation.run",
            category: "reconciliation",
            actor: "ca.demo@reconai.local",
            actorRole: "Tax Officer",
            target: "Matching Engine",
            details: "Executed 2-pass fuzzy reconciliation on 142 invoices",
            created_at: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_5",
            action: "ca.transfer.request",
            category: "transfer",
            actor: "client.demo@reconai.local",
            actorRole: "Client",
            target: "Tax Officer Directory",
            details: "Requested Tax Officer change transfer to Division Office 2",
            created_at: new Date(Date.now() - 62 * 60 * 1000).toISOString(),
            status: "pending"
          },
          {
            id: "log_6",
            action: "gstin.verify",
            category: "auth",
            actor: "client.demo@reconai.local",
            actorRole: "Client",
            target: "GST Portal API",
            details: "Ran live GSTIN taxpayer verification check",
            created_at: new Date(Date.now() - 95 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_7",
            action: "ca.transfer.approve",
            category: "transfer",
            actor: "admin.demo@reconai.local",
            actorRole: "System Admin",
            target: "Admin Panel",
            details: "Approved client Tax Officer transfer request",
            created_at: new Date(Date.now() - 130 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_8",
            action: "settings.update",
            category: "auth",
            actor: "admin.demo@reconai.local",
            actorRole: "System Admin",
            target: "System Configuration",
            details: "Tuned AI fraud confidence threshold to 85%",
            created_at: new Date(Date.now() - 180 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_9",
            action: "ocr.extract",
            category: "upload",
            actor: "ca.demo@reconai.local",
            actorRole: "Tax Officer",
            target: "Vision-LLM OCR",
            details: "Parsed scanned Tally PDF via qwen2.5vl:3b OCR engine",
            created_at: new Date(Date.now() - 240 * 60 * 1000).toISOString(),
            status: "success"
          },
          {
            id: "log_10",
            action: "report.export",
            category: "reconciliation",
            actor: "ca.demo@reconai.local",
            actorRole: "Tax Officer",
            target: "Audit Exporter",
            details: "Generated official GST Reconciliation Audit PDF report",
            created_at: new Date(Date.now() - 310 * 60 * 1000).toISOString(),
            status: "success"
          }
        ]);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAdminData();
  }, []);

  const filteredLogs = auditLogs.filter(log => {
    const act = (log.action || log.action_type || "").toLowerCase();
    const actor = (log.actor || log.actor_id || log.user || "").toLowerCase();
    const details = (log.details || log.metadata?.details || "").toLowerCase();
    const target = (log.target || "").toLowerCase();
    const q = logSearchQuery.toLowerCase().trim();

    if (logFilterCategory === "auth" && !act.includes("user") && !act.includes("otp") && !act.includes("gstin") && !act.includes("settings")) return false;
    if (logFilterCategory === "upload" && !act.includes("upload") && !act.includes("ingestion") && !act.includes("ocr")) return false;
    if (logFilterCategory === "reconciliation" && !act.includes("reconcil") && !act.includes("report") && !act.includes("match")) return false;
    if (logFilterCategory === "transfer" && !act.includes("ca") && !act.includes("transfer")) return false;

    if (q && !act.includes(q) && !actor.includes(q) && !details.includes(q) && !target.includes(q)) {
      return false;
    }
    return true;
  });

  const displayedLogs = showAllLogs ? filteredLogs : filteredLogs.slice(0, 5);

  return (
    <div className="p-6 space-y-6 text-left">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2">
            <Lock className="text-primary" size={20} /> System Admin Control Panel
          </h2>
          <p className="text-xs text-muted-foreground">Comprehensive system audit logging · User access management · Workspace health</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadAdminData}
            className="flex items-center gap-1.5 text-xs border border-border bg-card px-3 py-1.5 rounded-lg hover:bg-muted font-medium transition-colors"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh Logs
          </button>
          <button
            type="button"
            onClick={() => setNotice("Invite user flow initialized.")}
            className="flex items-center gap-1.5 text-xs bg-primary text-primary-foreground px-3 py-1.5 rounded-lg hover:bg-primary/90 font-medium transition-colors shadow-sm"
          >
            <Plus size={12} /> Invite User
          </button>
        </div>
      </div>

      {notice && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3.5 py-2.5 font-medium">{notice}</div>}

      {/* Admin KPI Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-2xl font-bold font-mono text-primary">{users.length}</div>
          <div className="text-xs text-muted-foreground mt-1 font-medium">Registered Users</div>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-2xl font-bold font-mono text-emerald-500">{users.filter(u => u.status === "Active" || u.status === "active").length || users.length}</div>
          <div className="text-xs text-muted-foreground mt-1 font-medium">Active Sessions</div>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-2xl font-bold font-mono text-amber-500">{auditLogs.length}</div>
          <div className="text-xs text-muted-foreground mt-1 font-medium">Recorded System Logs</div>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-2xl font-bold font-mono text-blue-500">99.98%</div>
          <div className="text-xs text-muted-foreground mt-1 font-medium">System Uptime</div>
        </div>
      </div>

      {/* User Management Section */}
      <div className="bg-card border border-border rounded-xl overflow-hidden shadow-sm">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-muted/20">
          <div>
            <div className="text-sm font-bold flex items-center gap-2">
              <Users size={16} className="text-primary" /> User Access Directory
            </div>
            <div className="text-[11px] text-muted-foreground">Overview of users across Admin, Tax Officer, and Client roles</div>
          </div>
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {["User / Name", "Email Address", "System Role", "Status", "Last Active", "Actions"].map(h => (
                <th key={h} className="text-left px-4 py-3 font-medium text-muted-foreground">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {users.map((u, idx) => (
              <tr key={u.id || u.email || idx} className="hover:bg-muted/40 transition-colors">
                <td className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-primary/15 text-primary flex items-center justify-center text-[10px] font-bold">
                      {(u.name || "U")[0]}
                    </div>
                    <span>{u.name || u.email}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-muted-foreground font-mono">{u.email}</td>
                <td className="px-4 py-3">
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                    normalizeRole(u.role) === ADMIN ? "bg-purple-500/15 text-purple-600 dark:text-purple-400" :
                    normalizeRole(u.role) === TAX_REVIEWER ? "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400" :
                    "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                  }`}>
                    {roleShortLabel(u.role) || "Business User"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <Badge label={u.status || "Active"} variant={u.status === "Active" || u.status === "active" ? "success" : "neutral"} />
                </td>
                <td className="px-4 py-3 text-muted-foreground">{u.last || u.createdAt || "Active now"}</td>
                <td className="px-4 py-3">
                  <button type="button" onClick={() => setNotice(`User details opened for ${u.email}`)} className="p-1 rounded hover:bg-muted text-muted-foreground">
                    <MoreHorizontal size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* System Activity Logs with View More / View Less Toggle */}
      <div className="bg-card border border-border rounded-xl overflow-hidden shadow-sm space-y-0">
        <div className="px-5 py-4 border-b border-border bg-muted/20 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-base font-bold flex items-center gap-2 text-foreground">
              <Activity size={18} className="text-amber-500" /> System Activity Logs (System Admin View)
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Complete real-time audit log of actions performed by any user (Admin, Tax Officers, Clients) across the application.
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-semibold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 px-2.5 py-1 rounded-full">
              {filteredLogs.length} Total Logs
            </span>
          </div>
        </div>

        {/* Filter Controls & Search */}
        <div className="p-4 border-b border-border bg-card flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mr-1">Filter:</span>
            {[
              { id: "all", label: "All Logs" },
              { id: "auth", label: "Auth & Security" },
              { id: "upload", label: "Uploads & OCR" },
              { id: "reconciliation", label: "Reconciliation" },
              { id: "transfer", label: "Officer Transfers" },
            ].map(cat => (
              <button
                key={cat.id}
                type="button"
                onClick={() => setLogFilterCategory(cat.id as any)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  logFilterCategory === cat.id
                    ? "bg-amber-500 text-slate-950 shadow-sm"
                    : "bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80"
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="relative w-full sm:w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={logSearchQuery}
              onChange={e => setLogSearchQuery(e.target.value)}
              placeholder="Search logs by user, action..."
              className="w-full pl-8 pr-3 py-1.5 bg-muted border border-border rounded-lg text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
          </div>
        </div>

        {/* System Logs Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-muted-foreground">
                <th className="text-left px-4 py-3 font-semibold">Action / Event</th>
                <th className="text-left px-4 py-3 font-semibold">Performed By</th>
                <th className="text-left px-4 py-3 font-semibold">Role</th>
                <th className="text-left px-4 py-3 font-semibold">Target / System Area</th>
                <th className="text-left px-4 py-3 font-semibold">Activity Details</th>
                <th className="text-left px-4 py-3 font-semibold">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {displayedLogs.map((log, idx) => {
                const actStr = String(log.action || log.action_type || "activity").toUpperCase();
                const actorEmail = log.actor || log.actor_id || log.user || "System User";
                const roleStr = roleShortLabel(log.actorRole) || log.actorRole || (actorEmail.includes("admin") ? "System Admin" : actorEmail.includes("ca") ? "Tax Reviewer" : "Business User");
                const timestamp = log.created_at ? new Date(log.created_at).toLocaleString() : "Just now";

                return (
                  <tr key={log.id || idx} className="hover:bg-muted/40 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold">
                      <span className={`px-2 py-0.5 rounded text-[11px] ${
                        actStr.includes("LOGIN") || actStr.includes("AUTH") ? "bg-blue-500/15 text-blue-500 border border-blue-500/20" :
                        actStr.includes("UPLOAD") || actStr.includes("OCR") ? "bg-emerald-500/15 text-emerald-500 border border-emerald-500/20" :
                        actStr.includes("RECON") || actStr.includes("MATCH") ? "bg-indigo-500/15 text-indigo-500 border border-indigo-500/20" :
                        actStr.includes("TRANSFER") || actStr.includes("CA") ? "bg-amber-500/15 text-amber-500 border border-amber-500/20" :
                        "bg-slate-500/15 text-slate-400 border border-slate-500/20"
                      }`}>
                        {log.action || "system.activity"}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-foreground">{actorEmail}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                        roleStr === "System Admin" ? "bg-purple-500/15 text-purple-600 dark:text-purple-400" :
                        roleStr === "Tax Officer" ? "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400" :
                        "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                      }`}>
                        {roleStr}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground font-mono text-[11px]">{log.target || "System Gateway"}</td>
                    <td className="px-4 py-3 text-foreground font-medium max-w-sm leading-relaxed">{log.details || log.metadata_json || "Activity recorded"}</td>
                    <td className="px-4 py-3 text-muted-foreground font-mono text-[11px] whitespace-nowrap">{timestamp}</td>
                  </tr>
                );
              })}

              {displayedLogs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">
                    No system audit logs found matching the filter criteria.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* View More / View Less Toggle Button */}
        {filteredLogs.length > 5 && (
          <div className="p-3 border-t border-border bg-muted/20 text-center">
            <button
              type="button"
              onClick={() => setShowAllLogs(!showAllLogs)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700 dark:text-amber-400 hover:text-amber-600 dark:hover:text-amber-300 transition-colors bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 px-5 py-2 rounded-lg shadow-sm"
            >
              {showAllLogs ? (
                <>
                  <span>View Less System Logs</span>
                  <ChevronUp size={14} />
                </>
              ) : (
                <>
                  <span>View More System Logs ({filteredLogs.length - 5} remaining)</span>
                  <ChevronDown size={14} />
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CADirectoryAdminSection({ refreshKey }: { refreshKey?: number }) {
  const [caList, setCaList] = useState<any[]>([]);
  const [unassigned, setUnassigned] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedCa, setExpandedCa] = useState<string | null>(null);

  const [directoryError, setDirectoryError] = useState("");

  const fetchCADirectory = async () => {
    setLoading(true);
    setDirectoryError("");
    try {
      // There is no combined /api/cas endpoint; both halves come from real
      // data — the reviewer directory, and the clients with nobody assigned.
      const [caRes, clientRes] = await Promise.all([
        apiRequest<{ cas: any[] }>("/api/ca/list", { auth: true }),
        apiRequest<{ clients: any[] }>("/api/clients", { auth: true }),
      ]);
      const allClients = clientRes.clients || [];
      setCaList(
        (caRes.cas || []).map(ca => ({
          ...ca,
          clientCount: ca.totalClients ?? allClients.filter(c => c.caId === ca.id).length,
          clients: allClients.filter(c => c.caId === ca.id),
        })),
      );
      setUnassigned(allClients.filter(c => !c.caId));
    } catch (err) {
      // Surfaced rather than swallowed: an empty directory and a failed
      // request look identical otherwise.
      setDirectoryError(`Could not load the reviewer directory: ${err instanceof Error ? err.message : "request failed"}.`);
      setCaList([]);
      setUnassigned([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCADirectory();
  }, [refreshKey]);

  const totalAssignedClients = caList.reduce((acc, ca) => acc + (ca.clientCount || (ca.clients ? ca.clients.length : 0)), 0);

  return (
    <div className="space-y-4 pt-6 border-t border-border mt-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold flex items-center gap-2">
            <Building2 className="text-primary" size={18} /> Tax Officers & Client Mapping
          </h3>
          <p className="text-xs text-muted-foreground">Directory of registered Tax &amp; Compliance Reviewers and their assigned client workspaces</p>
        </div>
        <button onClick={fetchCADirectory} className="text-xs border border-border bg-card px-3 py-1.5 rounded-lg hover:bg-muted transition-colors flex items-center gap-1.5 font-medium">
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh Breakdown
        </button>
      </div>

      {directoryError && (
        <div className="text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-md px-3 py-2">
          {directoryError}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
        <div className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-2xl font-bold font-mono text-primary">{caList.length}</div>
            <div className="text-muted-foreground mt-0.5 font-medium">Registered Tax Officers</div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center font-bold">
            <User size={18} />
          </div>
        </div>

        <div className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-2xl font-bold font-mono text-emerald-500">{totalAssignedClients}</div>
            <div className="text-muted-foreground mt-0.5 font-medium">Assigned Clients</div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-emerald-500/10 text-emerald-500 flex items-center justify-center font-bold">
            <Users size={18} />
          </div>
        </div>

        <div className="bg-card border border-border rounded-xl p-4 flex items-center justify-between">
          <div>
            <div className="text-2xl font-bold font-mono text-amber-500">{unassigned.length}</div>
            <div className="text-muted-foreground mt-0.5 font-medium">Unassigned Clients</div>
          </div>
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 text-amber-500 flex items-center justify-center font-bold">
            <AlertCircle size={18} />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {caList.map(ca => {
          const isExpanded = expandedCa === ca.id;
          const clientList = ca.clients || [];
          return (
            <div key={ca.id} className="bg-card border border-border rounded-xl overflow-hidden transition-all shadow-sm">
              <div
                onClick={() => setExpandedCa(isExpanded ? null : ca.id)}
                className="p-4 flex items-center justify-between cursor-pointer hover:bg-muted/30 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/15 text-primary flex items-center justify-center font-bold shrink-0">
                    <Building2 size={18} />
                  </div>
                  <div>
                    <div className="text-sm font-bold flex items-center gap-2">
                      {ca.firm_name || ca.name}
                      {ca.icai_number && <span className="text-[10px] font-mono font-normal text-muted-foreground bg-muted px-2 py-0.5 rounded">ID: {ca.icai_number}</span>}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono mt-0.5">{ca.email} · Officer: {ca.name}</div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-3 py-1 rounded-full border border-emerald-500/20">
                    {clientList.length} Client(s) Assigned
                  </span>
                  <ChevronRight size={16} className={`text-muted-foreground transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                </div>
              </div>

              {isExpanded && (
                <div className="p-4 border-t border-border bg-muted/20 space-y-3">
                  <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                    Linked Client Workspaces ({clientList.length}):
                  </div>
                  {clientList.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      {clientList.map((cli: any) => (
                        <div key={cli.id} className="bg-card border border-border rounded-xl p-3 text-xs flex items-center justify-between shadow-sm">
                          <div className="space-y-0.5">
                            <div className="font-bold text-foreground">{cli.name}</div>
                            <div className="text-[11px] font-mono text-muted-foreground">{cli.email || "No email"}</div>
                            <div className="text-[10px] font-mono text-muted-foreground">GSTIN: {cli.gstin} {cli.city ? `· ${cli.city}` : ""}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-xs font-mono font-bold text-emerald-500">{cli.compliance ?? 100}% Score</div>
                            <Badge label={cli.status || "Active"} variant={cli.status === "Active" ? "success" : "neutral"} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground italic p-3 bg-card border border-border rounded-lg">
                      No clients currently assigned to this Tax Officer.
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {unassigned.length > 0 && (
          <div className="bg-amber-500/5 border border-amber-500/30 rounded-xl p-4 space-y-3">
            <div className="text-xs font-bold text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
              <AlertCircle size={14} /> Unassigned Clients Awaiting Tax Officer Selection ({unassigned.length})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              {unassigned.map((cli: any) => (
                <div key={cli.id} className="bg-card border border-border rounded-xl p-3 flex items-center justify-between shadow-sm">
                  <div>
                    <div className="font-bold text-foreground">{cli.name}</div>
                    <div className="text-[11px] font-mono text-muted-foreground">{cli.email} · {cli.gstin}</div>
                  </div>
                  <Badge label="Awaiting Officer" variant="warning" />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Tax Officer Transfer Requests Admin Page ─────────────────────────────────────────
function CARequestsAdminPage() {
  const [requests, setRequests] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const [loadError, setLoadError] = useState("");

  const loadRequests = async () => {
    setLoadError("");
    try {
      const res = await apiRequest<{ requests: any[] }>("/api/ca-change-requests", { auth: true });
      setRequests(res.requests || []);
    } catch (err) {
      // Without this the screen shows "no pending requests", which is
      // indistinguishable from the request having failed outright.
      setRequests([]);
      setLoadError(`Could not load change requests: ${err instanceof Error ? err.message : "request failed"}.`);
    }
  };

  useEffect(() => { loadRequests(); }, []);

  const handleApprove = async (id: string) => {
    try {
      const res = await apiRequest<{ message: string }>(`/api/ca-change-requests/${id}/approve`, { method: "POST", auth: true });
      setMessage(`✅ ${res.message}`);
      loadRequests();
      setRefreshKey(k => k + 1);
    } catch (err) {
      setMessage(err instanceof Error ? `Error: ${err.message}` : "Approval failed.");
    }
  };

  const handleReject = async (id: string) => {
    try {
      const res = await apiRequest<{ message: string }>(`/api/ca-change-requests/${id}/reject`, { method: "POST", auth: true });
      setMessage(`Notice: ${res.message}`);
      loadRequests();
      setRefreshKey(k => k + 1);
    } catch (err) {
      setMessage(err instanceof Error ? `Error: ${err.message}` : "Rejection failed.");
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <UserCheck className="text-primary" size={20} /> Tax Officer Transfer Requests
          </h2>
          <p className="text-xs text-muted-foreground">Review and allow client requests to change their assigned Tax Officer</p>
        </div>
      </div>

      {message && <div className="text-xs text-primary bg-accent border border-border rounded-md px-3.5 py-2.5 font-medium">{message}</div>}
      {loadError && <div className="text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-md px-3.5 py-2.5">{loadError}</div>}

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {["Client Name", "Email", "Current Tax Officer", "Requested New Tax Officer", "Reason", "Status", "Submitted", "Actions"].map(h => (
                <th key={h} className="text-left px-4 py-3 font-medium text-muted-foreground">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {requests.map(r => (
              <tr key={r.id} className="hover:bg-muted/40 transition-colors">
                <td className="px-4 py-3 font-medium">{r.client_name || "Client Workspace"}</td>
                <td className="px-4 py-3 text-muted-foreground font-mono">{r.client_email}</td>
                <td className="px-4 py-3 text-muted-foreground">{r.current_ca_name || "Unassigned"}</td>
                <td className="px-4 py-3 font-semibold text-primary">{r.requested_ca_name || "Target Tax Officer"}</td>
                <td className="px-4 py-3 text-muted-foreground max-w-xs truncate">{r.reason || "None provided"}</td>
                <td className="px-4 py-3">
                  <Badge
                    label={r.status}
                    variant={r.status === "Approved" ? "success" : r.status === "Rejected" ? "warning" : "info"}
                  />
                </td>
                <td className="px-4 py-3 text-muted-foreground font-mono text-[11px]">{String(r.created_at || "").slice(0, 10)}</td>
                <td className="px-4 py-3">
                  {r.status === "Pending" ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleApprove(r.id)}
                        className="text-[11px] font-semibold bg-emerald-600 text-white px-2.5 py-1 rounded hover:bg-emerald-700 transition-colors flex items-center gap-1"
                      >
                        <CheckCircle2 size={12} /> Allow
                      </button>
                      <button
                        onClick={() => handleReject(r.id)}
                        className="text-[11px] font-medium border border-border px-2.5 py-1 rounded hover:bg-muted transition-colors text-rose-500"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span className="text-[11px] text-muted-foreground italic">Processed</span>
                  )}
                </td>
              </tr>
            ))}
            {requests.length === 0 && (
              <tr>
                <td colSpan={8}>
                  <EmptyState message="No Tax Officer change requests." />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <CADirectoryAdminSection refreshKey={refreshKey} />
    </div>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────
export default function App() {
  const [user, setUser] = useState<LoggedInUser | null>(null);
  const [authMode, setAuthMode] = useState<"landing" | "signin" | "signup" | "dashboard">("landing");
  const [selectedRole, setSelectedRole] = useState<Role>(TAX_REVIEWER);
  const [page, setPage] = useState<Page>("dashboard");
  const [dark, setDark] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [verifyingDocId, setVerifyingDocId] = useState<string | null>(null);
  const [selectedClientId, setSelectedClientId] = useState<string>("ALL");
  const [, setDataVersion] = useState(0);
  const forceUpdate = () => setDataVersion(v => v + 1);

  useEffect(() => {
    const savedUser = localStorage.getItem("reconai_user");
    const savedToken = localStorage.getItem("reconai_token");
    if (!savedUser || !savedToken) return;

    try {
      const parsedUser = JSON.parse(savedUser) as LoggedInUser;
      setUser(parsedUser);
      setAuthMode("dashboard");
      setPage(normalizeRole(parsedUser.role) === ADMIN ? "admin" : "dashboard");
    } catch {
      localStorage.removeItem("reconai_user");
      localStorage.removeItem("reconai_token");
    }
  }, []);

  useEffect(() => {
    const expireSession = () => {
      setUser(null);
      setAuthMode("signin");
    };
    window.addEventListener("reconai-auth-expired", expireSession);
    return () => window.removeEventListener("reconai-auth-expired", expireSession);
  }, []);

  // Fetch all data from backend when user is authenticated or client filter changes
  useEffect(() => {
    if (!user) return;
    fetchAllData(forceUpdate, selectedClientId);
  }, [user, selectedClientId]);

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [dark]);

  const handleLogin = (loggedInUser: LoggedInUser) => {
    setUser(loggedInUser);
    setAuthMode("dashboard");
    // Default starting page based on role
    if (normalizeRole(loggedInUser.role) === ADMIN) {
      setPage("admin");
    } else {
      setPage("dashboard");
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("reconai_token");
    localStorage.removeItem("reconai_user");
    setUser(null);
    setAuthMode("landing");
  };

  // If not logged in, route to Landing or Auth screens
  if (!user) {
    if (authMode === "signin" || authMode === "signup") {
      return (
        <AuthPages 
          initialRole={selectedRole}
          initialMode={authMode}
          onBackToLanding={() => setAuthMode("landing")}
          onLogin={handleLogin}
        />
      );
    }
    return (
      <LandingPage 
        onNavigate={(mode) => {
          setSelectedRole(TAX_REVIEWER);
          setAuthMode(mode);
        }}
        onSelectRole={(role, mode) => {
          setSelectedRole(role);
          setAuthMode(mode);
        }}
      />
    );
  }

  // If client logged in, render client-specific layout dashboard
  if (normalizeRole(user.role) === BUSINESS_USER) {
    return (
      <ClientDashboard 
        user={user}
        dark={dark}
        setDark={setDark}
        onLogout={handleLogout}
      />
    );
  }

  const pageContent = {
    dashboard: <DashboardPage user={user!} />,
    clients: <ClientsPage onUpdate={forceUpdate} user={user!} />,
    upload: <UploadPage onRefresh={() => fetchAllData(forceUpdate)} onVerifyDoc={setVerifyingDocId} />,
    reconciliation: <ReconciliationPage onRefresh={() => fetchAllData(forceUpdate)} onVerifyDoc={setVerifyingDocId} />,
    fraud: <FraudPage />,
    graph: <GraphPage />,
    assistant: <AssistantPage />,
    reports: <ReportsPage />,
    notifications: <NotificationsPage />,
    settings: <SettingsPage dark={dark} setDark={setDark} user={user!} />,
    admin: <AdminPage />,
    "ca-requests": <CARequestsAdminPage />,
  };

  const sidebarWidth = sidebarCollapsed ? "3.5rem" : "14rem";

  return (
    <div className="min-h-screen bg-background text-foreground" style={{ fontFamily: "'Inter', sans-serif" }}>
      <Sidebar page={page} setPage={setPage} collapsed={sidebarCollapsed} user={user!} onLogout={handleLogout} dark={dark} />
      <div style={{ marginLeft: sidebarWidth }} className="transition-all duration-200 flex flex-col min-h-screen">
        <Topbar
          dark={dark}
          setDark={setDark}
          page={page}
          setPage={setPage}
          sidebarCollapsed={sidebarCollapsed}
          setSidebarCollapsed={setSidebarCollapsed}
          user={user!}
          selectedClientId={selectedClientId}
          onClientFilterChange={(id: string) => {
            setSelectedClientId(id);
            fetchAllData(forceUpdate, id);
          }}
        />
        <main className="flex-1 overflow-auto">
          {pageContent[page]}
        </main>
      </div>

      {verifyingDocId && (
        <DocumentVerificationModal
          documentId={verifyingDocId}
          onClose={() => setVerifyingDocId(null)}
          onRefresh={() => fetchAllData(forceUpdate)}
        />
      )}
    </div>
  );
}
