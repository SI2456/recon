import { BUSINESS_USER, normalizeRole, type Role } from "../lib/roles";
import { useState, useRef, useEffect } from "react";
import { 
  Building2, ShieldAlert, Upload, FileText, CheckCircle2, AlertTriangle, 
  ArrowUpRight, ArrowDownRight, Send, User, Bot, Download, RefreshCw, 
  Check, CircleDot, Clock, ChevronRight, X, MessageSquare, Landmark, 
  HelpCircle, Settings, LogOut, Sun, Moon, Info, Calendar, Sparkles
} from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { apiRequest } from "../lib/api";

interface ClientDashboardProps {
  user: {
    name: string;
    email: string;
    role: Role;
    firmName?: string;
    caName?: string;
    caEmail?: string;
    gstin?: string;
    gstLegalName?: string;
    gstTradeName?: string;
    gstStatus?: string;
  };
  dark: boolean;
  setDark: (v: boolean) => void;
  onLogout: () => void;
}

export default function ClientDashboard({ user, dark, setDark, onLogout }: ClientDashboardProps) {
  const [activeTab, setActiveTab] = useState<"dashboard" | "upload" | "reconciliation" | "alerts" | "chat" | "settings">("dashboard");
  const [currentUser, setCurrentUser] = useState(user);
  const [caDirectory, setCaDirectory] = useState<any[]>([]);
  const [needsCaSelection, setNeedsCaSelection] = useState(false);
  const [clientId, setClientId] = useState<number | null>(null);
  const [gstDetails, setGstDetails] = useState<any | null>(null);
  const [gstVerifyValue, setGstVerifyValue] = useState(user.gstin || "");
  const [gstVerifying, setGstVerifying] = useState(false);
  const [captchaImage, setCaptchaImage] = useState("");
  const [captchaSession, setCaptchaSession] = useState("");
  const [captchaText, setCaptchaText] = useState("");
  const [captchaLoading, setCaptchaLoading] = useState(false);

  const [showCaChangeModal, setShowCaChangeModal] = useState(false);
  const [myCaRequests, setMyCaRequests] = useState<any[]>([]);
  const [selectedTargetCa, setSelectedTargetCa] = useState("");
  const [selectedBarCaId, setSelectedBarCaId] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [submittingReq, setSubmittingReq] = useState(false);

  const [loadError, setLoadError] = useState("");

  const fetchCaRequests = async () => {
    try {
      const res = await apiRequest<{ requests: any[] }>("/api/ca-change-requests", { auth: true });
      setMyCaRequests(res?.requests || []);
    } catch (err) {
      // An empty list and a failed request must not look the same.
      setMyCaRequests([]);
      setLoadError(`Could not load your change requests: ${err instanceof Error ? err.message : "request failed"}.`);
    }
  };

  useEffect(() => {
    fetchCaRequests();
  }, []);

  useEffect(() => {
    setCurrentUser(user);
    apiRequest<{ client: any }>("/api/clients/me", { auth: true })
      .then(res => {
        if (res?.client) {
          setClientId(res.client.id || null);
          setCurrentUser(prev => ({
            ...prev,
            name: res.client.name || prev.name,
            gstin: res.client.gstin || prev.gstin,
            gstLegalName: res.client.gstLegalName,
            gstTradeName: res.client.gstTradeName,
            gstStatus: res.client.gstStatus,
            caName: res.client.caName,
            caEmail: res.client.caEmail,
            firmName: res.client.firmName,
          }));
          setGstVerifyValue(res.client.gstin || "");
          if (res.client.gstLegalName || res.client.gstTradeName || res.client.gstStatus) {
            setGstDetails(res.client);
          }
        }
      })
      .catch(err => setLoadError(`Could not load your workspace: ${err instanceof Error ? err.message : "request failed"}.`));
    apiRequest<{ profile: any }>("/api/client/profile", { auth: true })
      .then(res => {
        setClientId(res.profile?.clientId || null);
        setNeedsCaSelection(Boolean(res.profile?.needsCaSelection));
        if (res.profile?.ca) {
          setCurrentUser(prev => ({
            ...prev,
            caName: res.profile.ca.name,
            caEmail: res.profile.ca.email,
            firmName: res.profile.ca.firmName,
          }));
        }
        if (res.profile?.client) {
          setGstVerifyValue(res.profile.client.gstin || "");
          if (res.profile.client.gstLegalName || res.profile.client.gstTradeName || res.profile.client.gstStatus) {
            setGstDetails(res.profile.client);
          }
        }
      })
      .catch(err => setLoadError(`Could not load your profile: ${err instanceof Error ? err.message : "request failed"}.`));
    apiRequest<{ cas: any[] }>("/api/ca/list", { auth: true })
      .then(res => setCaDirectory(res.cas || []))
      .catch(err => setLoadError(`Could not load the reviewer directory: ${err instanceof Error ? err.message : "request failed"}.`));
  }, [user.name, user.email]);
  
  const clientGSTIN = currentUser.gstin || "";
  const clientName = currentUser.name || "Client Workspace";
  const verifiedGstName = currentUser.gstLegalName || currentUser.gstTradeName || gstDetails?.gstLegalName || gstDetails?.gstTradeName || "";
  const managingCA = (currentUser as any).caName || (currentUser.firmName && currentUser.firmName !== "Not assigned" ? currentUser.firmName : "Not assigned");
  const firmName = (currentUser as any).firmName || ((currentUser as any).caEmail ? `Firm (${(currentUser as any).caEmail})` : "Not assigned");

  const [myInvoices, setMyInvoices] = useState<any[]>([]);
  const [myAlerts, setMyAlerts] = useState<any[]>([]);

  const fetchClientData = async () => {
    try {
      const invRes = await apiRequest<{ invoices: any[] }>("/api/invoices", { auth: true });
      if (invRes?.invoices) setMyInvoices(invRes.invoices);
      const upRes = await apiRequest<{ uploads: any[] }>("/api/ingestion/uploads", { auth: true });
      if (upRes?.uploads) {
        setUploads(upRes.uploads.map(u => ({
          name: u.fileName,
          size: `${u.fileType || "document"} · ${u.parsedRows ?? 0} rows`,
          date: u.createdAt ? new Date(u.createdAt).toLocaleDateString() : "",
          status: u.status,
        })));
      }
      const alertRes = await apiRequest<{ alerts: any[] }>("/api/fraud-alerts", { auth: true });
      if (alertRes?.alerts) setMyAlerts(alertRes.alerts);
      if (clientId) {
        const msgRes = await apiRequest<{ messages: any[] }>(`/api/messages?clientId=${clientId}`, { auth: true });
        if (msgRes?.messages) {
          setMessages(msgRes.messages.map(message => ({
            sender: normalizeRole(message.senderRole) === BUSINESS_USER ? "client" : "ca",
            text: message.text,
            time: message.createdAt ? new Date(message.createdAt).toLocaleString() : "",
          })));
        }
      }
    } catch (err) {
      setLoadError(`Could not load your data: ${err instanceof Error ? err.message : "request failed"}.`);
    }
  };

  useEffect(() => {
    fetchClientData();
  }, [clientId]);

  const clientHistoryData: any[] = [];

  // Upload Files state
  const [uploads, setUploads] = useState<any[]>([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [clientNotice, setClientNotice] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const gstInputRef = useRef<HTMLInputElement>(null);

  // Real-time green progress bar state for Client upload
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadProgressText, setUploadProgressText] = useState("");
  const [uploadingFileName, setUploadingFileName] = useState("");

  // Chat State
  const [messages, setMessages] = useState<any[]>([]);
  const [chatInput, setChatInput] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSendMessage = async () => {
    if (!chatInput.trim()) return;
    if (!clientId) {
      setClientNotice("Client profile is still loading. Please try again in a moment.");
      return;
    }
    const text = chatInput.trim();
    setMessages(prev => [...prev, { sender: "client", text, time: "Just now" }]);
    setChatInput("");
    try {
      await apiRequest("/api/messages", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ clientId, text }),
      });
      fetchClientData();
    } catch (err) {
      setClientNotice(err instanceof Error ? err.message : "Message could not be sent to CA.");
    }
  };

  const uploadDocument = async (file: File, source: string) => {
    if (needsCaSelection) {
      setUploadStatus("Please select your Chartered Accountant before uploading documents.");
      return;
    }
    setIsUploading(true);
    setUploadingFileName(file.name);
    setUploadProgress(5);
    setUploadProgressText(`Initializing upload for ${file.name}...`);
    setUploadStatus(`Uploading ${file.name}...`);

    const interval = setInterval(() => {
      setUploadProgress(prev => {
        if (prev < 30) {
          setUploadProgressText("Transferring document to secure Tax Officer workspace...");
          return prev + 15;
        } else if (prev < 60) {
          setUploadProgressText("Running extract.py invoice parser & HSN/SAC checks...");
          return prev + 10;
        } else if (prev < 85) {
          setUploadProgressText("Generating tax summary & saving records...");
          return prev + 5;
        } else if (prev < 95) {
          return prev + 1;
        }
        return prev;
      });
    }, 200);

    try {
      const formData = new FormData();
      formData.append("source", source);
      formData.append("file", file);

      await apiRequest<{ upload: { fileName: string; status: string } }>("/api/ingestion/upload", {
        method: "POST",
        auth: true,
        body: formData,
      });

      clearInterval(interval);
      setUploadProgress(100);
      setUploadProgressText(`100% Complete! ${file.name} sent to your Tax Officer.`);
      setUploadStatus(`${file.name} sent to your Tax Officer for processing. It will appear here once your Tax Officer shares it.`);
      fetchClientData();

      setTimeout(() => {
        setIsUploading(false);
        setUploadProgress(0);
      }, 4000);
    } catch (err) {
      clearInterval(interval);
      setIsUploading(false);
      setUploadProgress(0);
      setUploadStatus(err instanceof Error ? err.message : "Upload failed. Please try again.");
    }
  };

  const selectCa = async (caId: string | number) => {
    try {
      const res = await apiRequest<{ profile: any }>("/api/client/select-ca", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ caId }),
      });
      setNeedsCaSelection(false);
      if (res.profile?.ca) {
        setCurrentUser(prev => ({
          ...prev,
          caName: res.profile.ca.name,
          caEmail: res.profile.ca.email,
          firmName: res.profile.ca.firmName,
        }));
      }
      setClientNotice("Your Tax Officer has been selected.");
      fetchClientData();
    } catch (err) {
      setClientNotice(err instanceof Error ? err.message : "Could not select Tax Officer.");
    }
  };
  const loadCaptcha = async () => {
    setCaptchaLoading(true);
    setCaptchaText("");
    try {
      const cap: any = await apiRequest("/api/client/gstin-captcha", { auth: true });
      setCaptchaImage(cap.image || "");
      setCaptchaSession(cap.sessionId || "");
    } catch (err) {
      setClientNotice(err instanceof Error ? err.message : "Could not load captcha.");
    } finally {
      setCaptchaLoading(false);
    }
  };

  const cancelGstinVerify = () => {
    setCaptchaImage("");
    setCaptchaSession("");
    setCaptchaText("");
  };

  const submitGstinCaptcha = async () => {
    if (!captchaText.trim()) {
      setClientNotice("Enter the captcha text.");
      return;
    }
    setGstVerifying(true);
    setClientNotice("");
    try {
      const res: any = await apiRequest("/api/client/verify-gstin", {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          gstin: gstVerifyValue,
          sessionId: captchaSession,
          captcha: captchaText,
        }),
      });

      if (res?.client) {
        setGstDetails(res.client);
        setGstVerifyValue(res.client.gstin || gstVerifyValue);
        setCurrentUser(prev => ({
          ...prev,
          gstin: res.client.gstin || prev.gstin,
          gstLegalName: res.client.gstLegalName,
          gstTradeName: res.client.gstTradeName,
          gstStatus: res.client.gstStatus,
        }));
        setClientNotice(`GSTIN verified: ${res.client.gstLegalName || res.client.gstin} (${res.client.gstStatus || "Active"})`);
      } else {
        setClientNotice("GSTIN verified successfully.");
      }
      cancelGstinVerify();
      fetchClientData();
    } catch (err) {
      setClientNotice(err instanceof Error ? err.message : "GSTIN verification failed.");
      await loadCaptcha();
    } finally {
      setGstVerifying(false);
    }
  };
  
  const EmptyState = ({ message }: { message: string }) => (
    <div className="px-4 py-8 text-center text-xs text-muted-foreground">{message}</div>
  );

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col" style={{ fontFamily: "'Inter', sans-serif" }}>
      <header className="h-14 border-b border-border bg-card flex items-center justify-between px-6 sticky top-0 z-40">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-amber-500 flex items-center justify-center shadow-md shadow-amber-500/10">
            <Building2 size={16} className="text-slate-950 font-bold" />
          </div>
          <div>
            <span className="font-bold text-sm text-foreground tracking-tight">{clientName}</span>
            <span className="text-[10px] font-mono text-muted-foreground ml-2">GSTIN: {clientGSTIN || "not verified"}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setDark(!dark)} className="p-2 rounded hover:bg-muted text-muted-foreground transition-colors">{dark ? <Sun size={15} /> : <Moon size={15} />}</button>
          <div className="h-6 w-px bg-border mx-2" />
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-amber-500/20 text-amber-700 dark:text-amber-400 flex items-center justify-center text-xs font-semibold">{clientName[0]}</div>
            <div className="hidden sm:block text-left">
              <div className="text-xs font-medium text-foreground">Client Workspace</div>
              <div className="text-[9px] text-muted-foreground font-mono">Assigned to: {firmName}</div>
            </div>
          </div>
        </div>
      </header>

      {loadError && (
        <div className="mx-6 mt-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-md px-3 py-2 flex items-center justify-between gap-3">
          <span>{loadError}</span>
          <button type="button" onClick={() => setLoadError("")} className="text-destructive/70 hover:text-destructive shrink-0">
            <X size={13} />
          </button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-56 bg-card border-r border-border flex flex-col shrink-0">
          <nav className="flex-1 py-4 px-2.5 space-y-0.5">
            {[
              { id: "dashboard", label: "Business Dashboard", icon: Building2 },
              { id: "upload", label: "Upload Documents", icon: Upload },
              { id: "reconciliation", label: "Reconciliation Status", icon: FileText },
              { id: "alerts", label: "Fraud & Alerts", icon: ShieldAlert },
              { id: "chat", label: "Message my Tax Officer", icon: MessageSquare },
              { id: "settings", label: "Client Settings", icon: Settings },
            ].map(tab => {
              const active = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button key={tab.id} onClick={() => setActiveTab(tab.id as any)} className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-colors ${active ? "bg-amber-500/10 text-amber-700 dark:text-amber-400" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
                  <Icon size={14} className={active ? "text-amber-500" : ""} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>
          
          <div className="p-3 border-t border-border bg-muted/20 text-left space-y-1.5">
            <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide">Your Tax Officer</div>
            <div className="text-xs font-semibold text-foreground">{managingCA}</div>
            <div className="text-[10px] text-muted-foreground font-mono">{firmName}</div>
            <button type="button" onClick={() => setShowCaChangeModal(true)} className="text-[10px] font-semibold text-amber-700 dark:text-amber-400 bg-amber-500/15 border border-amber-500/30 px-2 py-1 rounded hover:bg-amber-500/25 w-full text-center transition-colors block mt-1">
              Request Tax Officer Change
            </button>
            {myCaRequests.length > 0 && (
              <div className="text-[10px] text-muted-foreground pt-0.5">Request: <span className="font-semibold text-primary">{myCaRequests[0].status}</span></div>
            )}
          </div>

          <div className="p-2 border-t border-border">
            <button 
              onClick={onLogout}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 transition-colors"
            >
              <LogOut size={14} />
              <span>Log out</span>
            </button>
          </div>
        </aside>

        {/* Content Pane */}
        <main className="flex-1 overflow-y-auto bg-background/50 p-6 text-left">
          {clientNotice && (
            <div className="mb-4 text-xs text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
              {clientNotice}
            </div>
          )}

          {needsCaSelection && (
            <div className="mb-5 bg-card border border-amber-500/40 rounded-xl p-3.5 flex flex-wrap items-center justify-between gap-3 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-amber-500/15 text-amber-600 flex items-center justify-center shrink-0">
                  <Building2 size={16} />
                </div>
                <div>
                  <div className="text-xs font-semibold">Select Your Tax Officer</div>
                  <div className="text-[11px] text-muted-foreground">Choose a tax officer to connect GST data & manage compliance</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={selectedBarCaId}
                  onChange={e => setSelectedBarCaId(e.target.value)}
                  className="bg-muted border border-border rounded-md px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-amber-500"
                >
                  <option value="">Select Tax Officer Division...</option>
                  {caDirectory.map(ca => (
                    <option key={ca.id} value={ca.id}>
                      {ca.name} {ca.firmName ? `(${ca.firmName})` : ""}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => {
                    if (selectedBarCaId) selectCa(selectedBarCaId);
                  }}
                  disabled={!selectedBarCaId}
                  className="bg-amber-500 text-slate-950 text-xs font-semibold px-3.5 py-1.5 rounded-md hover:bg-amber-400 disabled:opacity-50 transition-colors shadow-sm"
                >
                  Confirm Selection
                </button>
              </div>
            </div>
          )}
          
          {/* Dashboard Tab */}
          {activeTab === "dashboard" && (
            <div className="space-y-6">
              {/* Welcome bar */}
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-lg font-bold">Welcome back, {clientName}</h1>
                  <p className="text-xs text-muted-foreground">
                    {verifiedGstName ? `Verified GST business: ${verifiedGstName}. ` : ""}
                    Compliance cycle will appear after your Tax Officer connects GST data. Associated Tax Officer: {firmName}
                  </p>
                </div>
                <div className="flex items-center gap-1.5 text-xs bg-card border border-border px-3 py-1.5 rounded-lg shadow-sm">
                  <Calendar size={13} className="text-muted-foreground" />
                  <span>GST FY not loaded</span>
                </div>
              </div>

              {/* Stats Widgets */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-card border border-border rounded-xl p-4 flex flex-col justify-between h-32">
                  <div className="flex justify-between items-start">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Compliance Rating</span>
                    <span className="p-1.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400"><CheckCircle2 size={14} /></span>
                  </div>
                  <div className="mt-2">
                    <div className="text-2xl font-bold font-mono">N/A</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">No compliance history loaded</div>
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-4 flex flex-col justify-between h-32">
                  <div className="flex justify-between items-start">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Total Invoices Uploaded</span>
                    <span className="p-1.5 rounded bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400"><FileText size={14} /></span>
                  </div>
                  <div className="mt-2">
                    <div className="text-2xl font-bold font-mono">{myInvoices.length}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">No invoices uploaded yet</div>
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-4 flex flex-col justify-between h-32">
                  <div className="flex justify-between items-start">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Reconciliation Matches</span>
                    <span className="p-1.5 rounded bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400"><RefreshCw size={14} /></span>
                  </div>
                  <div className="mt-2">
                    <div className="text-2xl font-bold font-mono">N/A</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">Awaiting reconciliation</div>
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-4 flex flex-col justify-between h-32 border-amber-500/30 bg-amber-500/[0.01]">
                  <div className="flex justify-between items-start">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400">Tax Anomalies Flagged</span>
                    <span className="p-1.5 rounded bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400"><ShieldAlert size={14} /></span>
                  </div>
                  <div className="mt-2">
                    <div className="text-2xl font-bold font-mono text-red-500">{myAlerts.length}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">No active warnings loaded</div>
                  </div>
                </div>
              </div>

              {/* Chart & alerts summary */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                
                {/* Score Chart */}
                <div className="lg:col-span-8 bg-card border border-border rounded-xl p-4 space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold">Compliance Rating Progression</h3>
                    <p className="text-xs text-muted-foreground">No compliance history loaded</p>
                  </div>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={clientHistoryData}>
                        <defs>
                          <linearGradient id="clientGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="rgb(245, 158, 11)" stopOpacity={0.2} />
                            <stop offset="95%" stopColor="rgb(245, 158, 11)" stopOpacity={0.01} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                        <YAxis domain={[80, 100]} tick={{ fontSize: 10 }} />
                        <Tooltip formatter={(v) => [`${v}% Compliance`, ""]} />
                        <Area type="monotone" dataKey="score" stroke="rgb(245, 158, 11)" fill="url(#clientGrad)" strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Warnings summary */}
                <div className="lg:col-span-4 bg-card border border-border rounded-xl p-4 space-y-3">
                  <div>
                    <h3 className="text-sm font-semibold">Flagged Business Anomalies</h3>
                    <p className="text-xs text-muted-foreground">No active warnings loaded</p>
                  </div>
                  <div className="space-y-3 pt-2">
                    {myAlerts.map(a => (
                      <div key={a.id} className="p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/40 rounded-lg space-y-1">
                        <div className="flex justify-between items-center text-[10px]">
                          <span className="font-mono text-muted-foreground">{a.id}</span>
                          <span className="font-bold text-red-800 dark:text-red-400 bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 rounded">{a.type}</span>
                        </div>
                        <div className="text-xs font-semibold">{a.details}</div>
                        <div className="text-[10px] text-muted-foreground">{a.desc}</div>
                        <div className="text-[10px] font-medium pt-1 text-slate-500 font-mono">CA Status: {a.status}</div>
                      </div>
                    ))}
                    {myAlerts.length === 0 && <EmptyState message="No flagged business anomalies loaded." />}
                  </div>
                </div>

              </div>
            </div>
          )}

          {/* Upload Tab */}
          {activeTab === "upload" && (
            <div className="space-y-6">
              <div>
                <h1 className="text-lg font-bold">Document Upload Center</h1>
                <p className="text-xs text-muted-foreground">Ingest sales books (Excel/CSV), GSTR portal logs (JSON), or supplier bills (PDF)</p>
              </div>

              <div className="border-2 border-dashed border-border hover:border-amber-500/50 bg-card rounded-xl p-8 text-center transition-colors">
                <div className="flex flex-col items-center gap-3">
                  <div className="w-10 h-10 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-full flex items-center justify-center">
                    <Upload size={18} />
                  </div>
                  <div>
                    <div className="text-sm font-semibold">Select files to upload</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">Supports CSV, XLS, XLSX, JSON or PDF files up to 50MB</div>
                  </div>
                  <div className="flex gap-2 pt-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="hidden"
                      accept=".csv,.json,.pdf,.xls,.xlsx,.png,.jpg,.jpeg,.webp"
                      onChange={e => {
                        const file = e.target.files?.[0];
                        if (file) uploadDocument(file, "books");
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
                        if (file) uploadDocument(file, "gstr");
                        e.currentTarget.value = "";
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="text-xs font-semibold px-4 py-2 bg-amber-500 text-slate-950 rounded hover:bg-amber-400 transition-colors"
                    >
                      Browse files
                    </button>
                    <button
                      type="button"
                      onClick={() => gstInputRef.current?.click()}
                      className="text-xs font-semibold px-4 py-2 border border-border bg-card rounded hover:bg-muted transition-colors"
                    >
                      Select GSTIN Log
                    </button>
                  </div>
                  {uploadStatus && !isUploading && <div className="text-xs text-amber-600 dark:text-amber-400 pt-1">{uploadStatus}</div>}
                </div>
              </div>

              {/* Real-time Green Progress Bar */}
              {isUploading && (
                <div className="bg-card border border-emerald-500/40 rounded-xl p-4 space-y-2.5 animate-in fade-in duration-200 shadow-md">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 font-medium">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping shrink-0" />
                      <span className="text-foreground font-semibold">{uploadProgressText}</span>
                    </div>
                    <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400 text-sm">{uploadProgress}%</span>
                  </div>
                  <div className="w-full h-3 bg-muted rounded-full overflow-hidden p-0.5 border border-emerald-500/30">
                    <div
                      className="h-full bg-emerald-500 rounded-full transition-all duration-300 ease-out shadow-[0_0_12px_rgba(16,185,129,0.6)]"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <div className="flex justify-between items-center text-[10px] text-muted-foreground font-mono">
                    <span>File: {uploadingFileName}</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                      {uploadProgress === 100 ? "✓ 100% Upload Completed" : "Uploading in Real-Time..."}
                    </span>
                  </div>
                </div>
              )}

              {/* Uploads history */}
              <div className="bg-card border border-border rounded-xl">
                <div className="px-4 py-3 border-b border-border">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Ingested Document Log</h3>
                </div>
                <div className="divide-y divide-border">
                  {uploads.map((u, i) => (
                    <div key={i} className="px-4 py-3.5 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-muted rounded flex items-center justify-center text-amber-500">
                          <FileText size={16} />
                        </div>
                        <div>
                          <div className="text-xs font-semibold font-mono">{u.name}</div>
                          <div className="text-[10px] text-muted-foreground">{u.size} · Uploaded {u.date}</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded font-medium">
                          <Check size={11} /> Ready
                        </div>
                      </div>
                    </div>
                  ))}
                  {uploads.length === 0 && <EmptyState message="No documents uploaded yet." />}
                </div>
              </div>
            </div>
          )}

          {/* Reconciliation Status Tab */}
          {activeTab === "reconciliation" && (
            <div className="space-y-4">
              <div className="flex justify-between items-end">
                <div>
                  <h1 className="text-lg font-bold">Invoice Reconciliation Status</h1>
                  <p className="text-xs text-muted-foreground">Self-monitoring mismatch details generated by CA's audit model.</p>
                </div>
                <button type="button" onClick={() => setClientNotice("Client reconciliation export will be available after CA publishes a report.")} className="flex items-center gap-1 text-xs border border-border bg-card hover:bg-muted px-3 py-1.5 rounded-lg shadow-sm transition-colors">
                  <Download size={13} className="text-muted-foreground" /> Export Reports
                </button>
              </div>

              {/* Table */}
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border bg-muted/40 font-medium text-muted-foreground">
                        <th className="px-4 py-3 text-left">Invoice No.</th>
                        <th className="px-4 py-3 text-left">Supplier</th>
                        <th className="px-4 py-3 text-left">Date</th>
                        <th className="px-4 py-3 text-left">Total Value</th>
                        <th className="px-4 py-3 text-left">Status</th>
                        <th className="px-4 py-3 text-left">Risk Flag</th>
                        <th className="px-4 py-3 text-left"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {myInvoices.map((inv) => {
                        const isExpanded = expandedInvoice === inv.id;
                        return (
                          <>
                            <tr 
                              key={inv.id} 
                              onClick={() => setExpandedInvoice(isExpanded ? null : inv.id)}
                              className={`hover:bg-muted/30 cursor-pointer ${isExpanded ? "bg-muted/20" : ""}`}
                            >
                              <td className="px-4 py-3 font-mono text-primary">{inv.id}</td>
                              <td className="px-4 py-3 font-semibold">{inv.supplier}</td>
                              <td className="px-4 py-3 text-muted-foreground">{inv.date}</td>
                              <td className="px-4 py-3 font-mono font-medium">{inv.total}</td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium font-mono ${
                                  inv.status === "Matched" 
                                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400" 
                                    : "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400"
                                }`}>
                                  {inv.status}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium font-mono ${
                                  inv.risk === "Low" 
                                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400" 
                                    : inv.risk === "Medium"
                                    ? "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400"
                                    : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
                                }`}>
                                  {inv.risk}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-right">
                                <ChevronRight size={13} className={`text-muted-foreground transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr key={`${inv.id}-detail`} className="bg-muted/10">
                                <td colSpan={7} className="px-6 py-4 border-t border-b border-border">
                                  <div className="grid grid-cols-2 gap-8">
                                    <div>
                                      <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide mb-2">My In-House Books Data</div>
                                      <div className="space-y-1 text-xs">
                                        <div className="flex justify-between"><span className="text-muted-foreground">GSTIN</span><span className="font-mono">{clientGSTIN}</span></div>
                                        <div className="flex justify-between"><span className="text-muted-foreground">Invoice No.</span><span className="font-mono">{inv.id}</span></div>
                                        <div className="flex justify-between"><span className="text-muted-foreground">Supplier Code</span><span className="font-mono">{inv.gstin}</span></div>
                                        <div className="flex justify-between"><span className="text-muted-foreground">Total In Books</span><span className="font-mono font-semibold">{inv.total}</span></div>
                                      </div>
                                    </div>
                                    <div>
                                      <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide mb-2">GST Portal GSTR-2B Registry</div>
                                      <div className="space-y-1 text-xs">
                                        <div className="flex justify-between"><span className="text-muted-foreground">Reported GSTIN</span><span className="font-mono">{clientGSTIN}</span></div>
                                        <div className="flex justify-between"><span className="text-muted-foreground">Invoice No.</span><span className="font-mono">{inv.id}</span></div>
                                        <div className="flex justify-between"><span className="text-muted-foreground">Supplier Code</span><span className="font-mono">{inv.gstin}</span></div>
                                        <div className="flex justify-between">
                                          <span className="text-muted-foreground">Total In GSTR-2B</span>
                                          <span className={`font-mono font-semibold ${inv.status === "Mismatched" ? "text-red-500 font-bold" : ""}`}>
                                            {inv.status === "Mismatched" ? "NOT FOUND / MISSING" : inv.total}
                                          </span>
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                  <div className="mt-4 pt-3 border-t border-border flex justify-end gap-2">
                                    <button 
                                      onClick={() => {
                                        setActiveTab("chat");
                                        setChatInput(`Regarding invoice ${inv.id} matching issue: `);
                                      }}
                                      className="text-[11px] font-semibold bg-amber-500 text-slate-950 px-3 py-1.5 rounded hover:bg-amber-400 transition-colors"
                                    >
                                      Ask CA for resolution
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </>
                        );
                      })}
                      {myInvoices.length === 0 && (
                        <tr>
                          <td colSpan={7}>
                            <EmptyState message="No invoices loaded." />
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Alerts Tab */}
          {activeTab === "alerts" && (
            <div className="space-y-6">
              <div>
                <h1 className="text-lg font-bold">Fraud & Risk Alerts</h1>
                <p className="text-xs text-muted-foreground">Suspicious matches flagged by ReconAI's graph neural networks and SHAP classifiers.</p>
              </div>

              <div className="space-y-4">
                {myAlerts.map(alert => (
                  <div key={alert.id} className="bg-card border border-border rounded-xl p-5 space-y-4">
                    <div className="flex items-start justify-between">
                      <div className="flex gap-3">
                        <div className="p-2 bg-red-50 dark:bg-red-950/20 text-red-600 rounded-lg">
                          <ShieldAlert size={18} />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono text-muted-foreground">{alert.id}</span>
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400 font-mono">
                              {alert.type}
                            </span>
                            <span className="text-xs font-semibold text-muted-foreground font-mono">Amt: {alert.amount}</span>
                          </div>
                          <h3 className="text-sm font-bold mt-1 text-foreground">{alert.details}</h3>
                          <p className="text-xs text-muted-foreground mt-1">{alert.desc}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">AI Anomaly Risk</div>
                        <div className="text-xl font-bold font-mono text-red-500">{alert.risk}/100</div>
                      </div>
                    </div>

                    <div className="border-t border-border pt-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                      <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                        <Clock size={12} />
                        <span>Audit Status: <strong>{alert.status}</strong></span>
                      </div>
                      <div className="flex gap-2">
                        <button 
                          onClick={() => {
                            setActiveTab("chat");
                            setChatInput(`I see fraud alert ${alert.id} (${alert.type}) flagged for ${alert.details}. What supporting docs are needed?`);
                          }}
                          className="text-xs font-semibold bg-amber-500 text-slate-950 px-3.5 py-1.5 rounded hover:bg-amber-400 transition-colors"
                        >
                          Clarify with CA
                        </button>
                        <button type="button" onClick={() => fileInputRef.current?.click()} className="text-xs font-semibold border border-border bg-card hover:bg-muted px-3.5 py-1.5 rounded transition-colors">
                          Upload Clarification Receipt
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
                {myAlerts.length === 0 && (
                  <div className="bg-card border border-border rounded-xl">
                    <EmptyState message="No fraud or risk alerts loaded." />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Chat with CA Tab */}
          {activeTab === "chat" && (
            <div className="flex flex-col h-[calc(100vh-8rem)] bg-card border border-border rounded-xl overflow-hidden text-left">
              {/* Chat Header */}
              <div className="px-5 py-3 border-b border-border flex items-center justify-between bg-muted/20">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-500/10 text-amber-600 flex items-center justify-center">
                    <User size={15} />
                  </div>
                  <div>
                    <h3 className="text-xs font-bold text-foreground">{managingCA}</h3>
                    <div className="text-[10px] text-emerald-600 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 bg-muted-foreground rounded-full" /> Advisor not connected
                    </div>
                  </div>
                </div>
                <div className="text-xs text-muted-foreground font-mono bg-card px-2.5 py-0.5 rounded border border-border">
                  Firm ID: Not configured
                </div>
              </div>

              {/* Chat Messages */}
              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {messages.map((m, i) => (
                  <div key={i} className={`flex gap-3 max-w-[80%] ${m.sender === "client" ? "ml-auto flex-row-reverse" : "mr-auto"}`}>
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${m.sender === "client" ? "bg-amber-500 text-slate-950" : "bg-muted"}`}>
                      <User size={12} />
                    </div>
                    <div>
                      <div className={`p-3 rounded-lg text-xs leading-relaxed ${
                        m.sender === "client" 
                          ? "bg-amber-500 text-slate-950 font-medium" 
                          : "bg-muted text-foreground border border-border"
                      }`}>
                        {m.text}
                      </div>
                      <div className="text-[9px] text-muted-foreground mt-0.5 font-mono px-1">
                        {m.time}
                      </div>
                    </div>
                  </div>
                ))}
                {messages.length === 0 && <EmptyState message="No messages yet." />}
                <div ref={chatEndRef} />
              </div>

              {/* Input section */}
              <div className="p-3 border-t border-border bg-muted/10 flex gap-2">
                <input 
                  type="text" 
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") handleSendMessage(); }}
                  placeholder="Ask your accountant about matching reports, active anomalies, or compliance thresholds..."
                  className="flex-1 text-xs px-3.5 py-2.5 bg-background border border-border rounded-lg focus:outline-none focus:border-amber-500"
                />
                <button 
                  onClick={handleSendMessage}
                  className="p-2.5 bg-amber-500 text-slate-950 rounded-lg hover:bg-amber-400 transition-colors shadow-sm"
                >
                  <Send size={14} />
                </button>
              </div>
            </div>
          )}

          {/* Settings Tab */}
          {activeTab === "settings" && (
            <div className="max-w-lg bg-card border border-border rounded-xl p-6 space-y-6">
              <div>
                <h1 className="text-base font-bold">Client Settings</h1>
                <p className="text-xs text-muted-foreground">Manage business details and security integrations</p>
              </div>

              <div className="space-y-4">
                {[
                  ["Authorized Person Name", clientName],
                  ["Registered Email Address", user.email],
                  ["GSTIN Number", clientGSTIN],
                  ["GST Legal Name", verifiedGstName || "Not verified"],
                  ["GST Status", currentUser.gstStatus || gstDetails?.gstStatus || "Not verified"],
                  ["Selected Chartered Accountant", managingCA]
                ].map(([label, val]) => (
                  <div key={label}>
                    <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1">{label}</label>
                    <input 
                      type="text" 
                      defaultValue={val} 
                      disabled
                      className="w-full text-xs px-3 py-2 bg-muted/65 border border-border rounded text-muted-foreground font-mono"
                    />
                  </div>
                ))}

                <div className="border-t border-border pt-4 space-y-3">
                  <div>
                    <div className="text-xs font-semibold">GSTIN Verification</div>
                    <div className="text-[10px] text-muted-foreground">Validate GSTIN using GSTVerify and save official GST details for you and your CA.</div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1">GSTIN</label>
                      <input
                        type="text"
                        value={gstVerifyValue}
                        onChange={e => setGstVerifyValue(e.target.value.toUpperCase())}
                        className="w-full text-xs px-3 py-2 bg-background border border-border rounded font-mono"
                        placeholder="27AAPFU0939F1ZV"
                      />
                    </div>
                  </div>
                  {!captchaImage ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={startGstinVerify}
                        disabled={captchaLoading}
                        className="text-xs font-semibold bg-amber-500 text-slate-950 px-3 py-2 rounded hover:bg-amber-400 transition-colors disabled:opacity-50"
                      >
                        {captchaLoading ? "Loading captcha..." : "Verify GSTIN"}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2 bg-muted/40 border border-border rounded-lg p-3">
                      <div className="text-[10px] text-muted-foreground">Enter the characters shown to fetch official GST details from the portal.</div>
                      <div className="flex items-center gap-3">
                        <img src={captchaImage} alt="GST portal captcha" className="h-12 rounded border border-border bg-white" />
                        <button type="button" onClick={loadCaptcha} disabled={captchaLoading} className="text-[11px] underline text-muted-foreground hover:text-foreground disabled:opacity-50">
                          {captchaLoading ? "Refreshing..." : "Refresh"}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={captchaText}
                        onChange={e => setCaptchaText(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") submitGstinCaptcha(); }}
                        className="w-full text-xs px-3 py-2 bg-background border border-border rounded font-mono"
                        placeholder="Captcha text"
                        autoFocus
                      />
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={submitGstinCaptcha}
                          disabled={gstVerifying}
                          className="text-xs font-semibold bg-amber-500 text-slate-950 px-3 py-2 rounded hover:bg-amber-400 transition-colors disabled:opacity-50"
                        >
                          {gstVerifying ? "Verifying..." : "Submit & Verify"}
                        </button>
                        <button type="button" onClick={cancelGstinVerify} className="text-xs border border-border px-3 py-2 rounded hover:bg-muted transition-colors">
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                  {gstDetails && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] bg-muted/40 border border-border rounded-lg p-3">
                      <div><span className="text-muted-foreground">Legal Name:</span> <span className="font-semibold">{gstDetails.gstLegalName || "N/A"}</span></div>
                      <div><span className="text-muted-foreground">Trade Name:</span> <span className="font-semibold">{gstDetails.gstTradeName || "N/A"}</span></div>
                      <div><span className="text-muted-foreground">Status:</span> <span className="font-semibold">{gstDetails.gstStatus || "N/A"}</span></div>
                      <div><span className="text-muted-foreground">GSTIN:</span> <span className="font-mono">{gstDetails.gstin || clientGSTIN}</span></div>
                    </div>
                  )}
                </div>

                <div className="border-t border-border pt-4">
                  <div className="text-xs font-semibold mb-2">Display Theme</div>
                  <div className="flex gap-2">
                    {[
                      { label: "Light", val: false, icon: Sun },
                      { label: "Dark", val: true, icon: Moon }
                    ].map(themeOpt => {
                      const active = dark === themeOpt.val;
                      const Icon = themeOpt.icon;
                      return (
                        <button
                          key={themeOpt.label}
                          onClick={() => setDark(themeOpt.val)}
                          className={`flex items-center gap-2 px-4 py-2 border rounded-md text-xs font-semibold transition-colors ${
                            active ? "border-amber-500 bg-amber-500/10 text-amber-700 dark:text-amber-400" : "border-border hover:bg-muted"
                          }`}
                        >
                          <Icon size={13} />
                          <span>{themeOpt.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="border-t border-border pt-4">
                  <button type="button" onClick={() => setClientNotice("Client preferences saved locally.")} className="text-xs font-semibold bg-amber-500 text-slate-950 px-4 py-2 rounded hover:bg-amber-400 transition-colors shadow-sm">
                    Save preferences
                  </button>
                </div>
              </div>
            </div>
          )}

        </main>
      </div>

      {/* Tax Officer Change Request Modal */}
      {showCaChangeModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border text-card-foreground rounded-xl p-6 w-full max-w-md space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Building2 size={18} className="text-amber-500" /> Request Tax Officer Change
              </h3>
              <button onClick={() => setShowCaChangeModal(false)} className="p-1 hover:bg-muted rounded"><X size={15} /></button>
            </div>

            <p className="text-xs text-muted-foreground">
              Select a new Tax Officer. System Admin will review and allow the transfer of your client records.
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium block mb-1">Target Tax Officer</label>
                <select
                  value={selectedTargetCa}
                  onChange={e => setSelectedTargetCa(e.target.value)}
                  className="w-full text-xs px-3 py-2 bg-muted border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-amber-500"
                >
                  <option value="">Select a Tax Officer...</option>
                  {caDirectory.map(ca => (
                    <option key={ca.id} value={ca.id}>
                      {ca.name} {ca.firmName ? `(${ca.firmName})` : ""} — {ca.email}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Reason for Transfer (Optional)</label>
                <textarea
                  value={changeReason}
                  onChange={e => setChangeReason(e.target.value)}
                  placeholder="State reason for changing Tax Officer..."
                  rows={3}
                  className="w-full text-xs px-3 py-2 bg-muted border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowCaChangeModal(false)} className="text-xs border border-border px-3 py-1.5 rounded hover:bg-muted">Cancel</button>
              <button
                onClick={async () => {
                  if (!selectedTargetCa) {
                    setClientNotice("Please select a target Tax Officer.");
                    return;
                  }
                  setSubmittingReq(true);
                  try {
                    await apiRequest("/api/ca-change-requests", {
                      method: "POST",
                      auth: true,
                      body: JSON.stringify({ requestedCaId: selectedTargetCa, reason: changeReason })
                    });
                    setClientNotice("Tax Officer Change Request submitted to System Admin for approval.");
                    setShowCaChangeModal(false);
                    fetchCaRequests();
                  } catch (err) {
                    setClientNotice(err instanceof Error ? err.message : "Request failed.");
                  } finally {
                    setSubmittingReq(false);
                  }
                }}
                disabled={submittingReq}
                className="text-xs bg-amber-500 text-slate-950 font-semibold px-4 py-1.5 rounded hover:bg-amber-400 disabled:opacity-50"
              >
                {submittingReq ? "Submitting..." : "Submit Request to Admin"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
