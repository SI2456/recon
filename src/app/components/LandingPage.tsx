import { ADMIN, BUSINESS_USER, TAX_REVIEWER, type Role } from "../lib/roles";
import { useState, useRef, useEffect } from "react";
import { 
  Zap, ShieldAlert, Users, FileText, CheckCircle2, BarChart3, 
  ArrowRight, Lock, Building2, Sparkles, Activity, Shield, Cpu, HelpCircle 
} from "lucide-react";

import promoVideo1 from "../../../ReconAI_video_script_202607012130.mp4";
import promoVideo2 from "../../../ReconAI_video_GST_reconciliation…_202607012157.mp4";
import logoImg from "../../../Screenshot_2026-07-01_214942-removebg-preview.png";
import darkLogoImg from "../../../darkThemeLogo.png";

interface LandingPageProps {
  onNavigate: (mode: "signin" | "signup") => void;
  onSelectRole: (role: Role, mode: "signin" | "signup") => void;
}

export default function LandingPage({ onNavigate, onSelectRole }: LandingPageProps) {
  const playlist = [promoVideo1, promoVideo2];
  const videoTitles = [
    "ReconAI Product Overview",
    "AI GST Reconciliation Demo"
  ];
  
  const [videoIndex, setVideoIndex] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.load();
      videoRef.current.play().catch(err => console.log("Video playback error:", err));
    }
  }, [videoIndex]);

  const handleVideoEnded = () => {
    setVideoIndex((prev) => (prev + 1) % playlist.length);
  };
  const features = [
    {
      icon: Cpu,
      title: "AI-Powered Matching Engine",
      desc: "Instantly reconcile GSTR-2A/2B against books of accounts using intelligent fuzzy matching and deep pattern analysis.",
      color: "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400"
    },
    {
      icon: ShieldAlert,
      title: "Fraud Anomaly Detection",
      desc: "Identify duplicate invoices, suspended supplier GSTINs, and suspicious input tax credit (ITC) claims with visual SHAP explanations.",
      color: "bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400"
    },
    {
      icon: Activity,
      title: "Circular Trading Network Visualizer",
      desc: "Map supplier-buyer transactions as graph networks. Detect suspect loops and round-tripping schemes automatically.",
      color: "bg-purple-50 text-purple-600 dark:bg-purple-950/40 dark:text-purple-400"
    },
    {
      icon: FileText,
      title: "Intelligent OCR Parsing",
      desc: "Upload Tally CSVs, PDFs, or scanned images. Our OCR engine automatically extracts invoice numbers, amounts, dates, and GSTINs.",
      color: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400"
    },
    {
      icon: BarChart3,
      title: "Audit-Ready Exporter",
      desc: "Generate professional compliance audit logs, reconciliation summaries, and detailed Excel/PDF reports with one click.",
      color: "bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400"
    },
    {
      icon: Sparkles,
      title: "RAG AI Assistant",
      desc: "Query your compliance database in plain English. Get answers on client portfolios, tax flags, or compliance history instantly.",
      color: "bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-400"
    }
  ];

  const roles = [
    {
      id: ADMIN,
      icon: Lock,
      title: "Administrator (Admin)",
      tagline: "System Control & Health Monitoring",
      desc: "Oversees the entire enterprise. Has full visibility across all Tax Officer divisions, manages RBAC permissions, configures system AI models, monitors backup health, and inspects secure audit logs.",
      responsibilities: [
        "Manage Tax Officer offices and enterprise accounts",
        "Configure RBAC roles and permissions",
        "Monitor system status and server uptime",
        "Tune AI confidence thresholds and RAG settings",
        "Manage data backups and storage optimization",
        "Inspect global system logs and audit records"
      ],
      color: "border-slate-200 dark:border-slate-800 hover:border-slate-400 dark:hover:border-slate-700 bg-card",
      iconColor: "text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-900/60"
    },
    {
      id: TAX_REVIEWER,
      icon: Users,
      title: "Tax Officer",
      tagline: "Primary Workspace & Client Manager",
      desc: "The primary user of ReconAI. Manages multiple corporate clients, handles document ingestion, triggers reconciliation matches, runs fraud checks, analyzes graph structures, and runs compliance reviews.",
      responsibilities: [
        "Manage client portfolio dashboard",
        "Upload GSTR documents, CSVs, and PDFs",
        "Perform intelligent GST reconciliation",
        "Investigate fraud alerts and invoice mismatches",
        "Analyze circular trading networks and cycles",
        "Export audit reports and communicate with clients"
      ],
      color: "border-primary/20 dark:border-primary/10 hover:border-primary/50 dark:hover:border-primary/40 bg-indigo-50/20 dark:bg-indigo-950/10",
      iconColor: "text-primary bg-indigo-100 dark:bg-indigo-900/40"
    },
    {
      id: BUSINESS_USER,
      icon: Building2,
      title: "Client / Business Owner",
      tagline: "Self-Service Portal & Transparency",
      desc: "Assigned individual portal. Can upload GST portal receipts, monitor reconciliation status, view relevant fraud warnings, track current compliance score, download client reports, and chat directly with their Tax Officer.",
      responsibilities: [
        "Upload own GST-related invoices & books",
        "Track compliance history & risk scores",
        "View fraud warnings affecting their business",
        "Download tax audit spreadsheets & reports",
        "Submit documents requested by the Tax Officer",
        "Chat with their dedicated Tax Officer"
      ],
      color: "border-amber-200 dark:border-amber-900/40 hover:border-amber-400 dark:hover:border-amber-800 bg-amber-50/10 dark:bg-amber-950/5",
      iconColor: "text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40"
    }
  ];

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans">
      <div className="fixed bottom-4 right-4 z-[100] flex gap-2 rounded-lg border border-border bg-card p-2 shadow-xl md:hidden">
        <button
          type="button"
          onClick={() => onNavigate("signin")}
          className="text-xs font-semibold px-4 py-2 rounded-md bg-primary text-primary-foreground"
        >
          Sign In
        </button>
        <button
          type="button"
          onClick={() => onNavigate("signup")}
          className="text-xs font-semibold px-4 py-2 rounded-md border border-border bg-card"
        >
          Register
        </button>
      </div>

      {/* Navigation Header */}
      <header className="h-16 border-b border-border bg-card/85 backdrop-blur-md sticky top-0 z-50 flex items-center justify-between px-6 md:px-12">
        <div className="flex items-center">
          <img src={logoImg} alt="ReconAI Logo" className="dark:hidden h-10 object-contain" />
          <img src={darkLogoImg} alt="ReconAI Logo" className="hidden dark:block h-10 object-contain" />
        </div>
        <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-muted-foreground">
          <a href="#about" className="hover:text-foreground transition-colors">Why ReconAI?</a>
          <a href="#features" className="hover:text-foreground transition-colors">Features</a>
          <a href="#roles" className="hover:text-foreground transition-colors">Roles</a>
        </nav>
        <div className="flex items-center gap-3">
          <button 
            type="button"
            onClick={() => onNavigate("signin")} 
            className="text-xs font-semibold px-4 py-2 rounded-md hover:bg-muted transition-colors border border-border text-foreground bg-card"
          >
            Sign In
          </button>
          <button 
            type="button"
            onClick={() => onNavigate("signup")} 
            className="text-xs font-semibold px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/95 transition-all shadow-sm shadow-primary/10"
          >
            Register
          </button>
        </div>
      </header>

      {/* Hero Section */}
      <section id="about" className="relative py-20 px-6 md:px-12 max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 items-center overflow-hidden">
        <div className="lg:col-span-6 flex flex-col gap-6 text-left relative z-10">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 text-xs font-medium w-fit">
            <Sparkles size={12} /> Compliance Simplified
          </div>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
            AI-Powered GST <br />
            <span className="bg-gradient-to-r from-primary to-violet-600 bg-clip-text text-transparent">Reconciliation</span> & Anomaly Guard
          </h1>
          <p className="text-muted-foreground text-sm md:text-base max-w-xl leading-relaxed">
            GST compliance in India can involve massive transactional audits. Tax Officers face significant overhead with manual books vs. GSTR matching, and fraud risk like fake invoices or circular trading loops.
          </p>
          <p className="text-muted-foreground text-sm md:text-base max-w-xl leading-relaxed">
            <strong>ReconAI</strong> was built to automate the reconciliation process with fuzzy matching, SHAP explainable fraud engines, and circular trading network analyzers.
          </p>
          <div className="flex flex-wrap items-center gap-4 mt-2">
            <button 
              type="button"
              onClick={() => onSelectRole(TAX_REVIEWER, "signup")} 
              className="group flex items-center gap-2 text-xs font-semibold bg-primary text-primary-foreground px-5 py-3 rounded-lg hover:bg-primary/90 transition-all shadow-md shadow-primary/20"
            >
              Get Started as Tax Officer <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </button>
            <button 
              type="button"
              onClick={() => onSelectRole(BUSINESS_USER, "signin")} 
              className="text-xs font-semibold border border-border bg-card hover:bg-muted px-5 py-3 rounded-lg transition-colors"
            >
              Access Client Portal
            </button>
          </div>
          
          <div className="grid grid-cols-3 gap-6 pt-6 border-t border-border mt-4">
            <div>
              <div className="text-2xl font-bold font-mono">N/A</div>
              <div className="text-[11px] text-muted-foreground">Matching benchmark</div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono">N/A</div>
              <div className="text-[11px] text-muted-foreground">Accuracy after training</div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono">N/A</div>
              <div className="text-[11px] text-muted-foreground">Tax flags handled</div>
            </div>
          </div>
        </div>

        {/* Hero Visual Mockup - Integrated Sequential Video Playlist */}
        <div className="lg:col-span-6 relative flex justify-center w-full">
          <div className="absolute -top-12 -left-12 w-64 h-64 bg-primary/10 rounded-full blur-3xl -z-10" />
          <div className="absolute -bottom-12 -right-12 w-64 h-64 bg-violet-500/10 rounded-full blur-3xl -z-10" />
          
          {/* Simulated Browser Frame with Video Playlist */}
          <div className="w-full max-w-2xl rounded-xl border border-border bg-card shadow-2xl overflow-hidden flex flex-col hover:border-primary/45 transition-colors duration-300">
            <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-muted/30 shrink-0 select-none">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
              </div>
              <div className="text-[10px] font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded">
                {videoTitles[videoIndex]} (Video {videoIndex + 1}/{playlist.length})
              </div>
            </div>
            
            <div className="relative aspect-video bg-slate-950 flex items-center justify-center overflow-hidden">
              <video 
                ref={videoRef}
                src={playlist[videoIndex]}
                autoPlay 
                muted 
                playsInline
                onEnded={handleVideoEnded}
                className="w-full h-full object-cover"
              />
              {/* Playlist Indicators Overlay */}
              <div className="absolute bottom-3 left-4 flex gap-1.5 z-10 bg-black/40 px-2 py-1 rounded-full backdrop-blur-sm">
                {playlist.map((_, i) => (
                  <button 
                    type="button"
                    key={i} 
                    onClick={() => setVideoIndex(i)}
                    className={`w-2 h-2 rounded-full transition-all ${videoIndex === i ? "bg-amber-500 w-4" : "bg-white/40 hover:bg-white/80"}`}
                    title={`Play ${videoTitles[i]}`}
                  />
                ))}
              </div>
              {/* Overlay shadow mask */}
              <div className="absolute inset-0 bg-gradient-to-t from-slate-950/20 via-transparent to-transparent pointer-events-none" />
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-24 bg-card/50 border-t border-b border-border">
        <div className="max-w-7xl mx-auto px-6 md:px-12 text-center space-y-12">
          <div className="max-w-2xl mx-auto space-y-4">
            <h2 className="text-3xl font-bold tracking-tight">Full-Suite AI Audit Platform</h2>
            <p className="text-muted-foreground text-sm">
              ReconAI includes specialized algorithmic solvers to reduce tax liability exposure and automate reconciliation overhead.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((f, i) => (
              <div key={i} className="p-6 rounded-xl border border-border bg-card flex flex-col items-start text-left gap-4 hover:shadow-lg transition-all group">
                <div className={`p-2.5 rounded-lg ${f.color}`}>
                  <f.icon size={16} />
                </div>
                <h3 className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">{f.title}</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Roles & Responsibilities Section */}
      <section id="roles" className="py-24 px-6 md:px-12 max-w-7xl mx-auto space-y-12">
        <div className="text-center max-w-2xl mx-auto space-y-4">
          <h2 className="text-3xl font-bold tracking-tight">Multi-User Role Engine</h2>
          <p className="text-muted-foreground text-sm">
            ReconAI features strict Role-Based Access Control (RBAC) separating administrative tasks, accountant work, and client portals.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {roles.map((r) => (
            <div 
              key={r.id} 
              className={`p-6 rounded-xl border flex flex-col justify-between gap-6 transition-all duration-200 ${r.color}`}
            >
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className={`p-2.5 rounded-lg ${r.iconColor}`}>
                    <r.icon size={16} />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-foreground">{r.title}</h3>
                    <div className="text-[10px] text-muted-foreground font-medium">{r.tagline}</div>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{r.desc}</p>
                <div className="border-t border-border pt-4 space-y-2">
                  <div className="text-[10px] font-bold text-foreground uppercase tracking-wider">Responsibilities:</div>
                  <ul className="space-y-1.5">
                    {r.responsibilities.map((resp, ri) => (
                      <li key={ri} className="flex items-start gap-2 text-xs text-muted-foreground leading-snug">
                        <CheckCircle2 size={12} className="text-emerald-500 mt-0.5 shrink-0" />
                        <span>{resp}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <button 
                type="button"
                onClick={() => onSelectRole(r.id, "signin")}
                className="w-full py-2.5 rounded-lg border border-border bg-card text-xs font-semibold hover:bg-muted hover:border-foreground/20 transition-all flex items-center justify-center gap-1.5"
              >
                Access as {r.id.toUpperCase()} <ArrowRight size={12} />
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Trust & FAQ Footer */}
      <footer className="mt-auto bg-card border-t border-border py-12 px-6 md:px-12">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center">
            <img src={logoImg} alt="ReconAI Logo" className="dark:hidden h-8 object-contain" />
            <img src={darkLogoImg} alt="ReconAI Logo" className="hidden dark:block h-8 object-contain" />
          </div>
          <div className="flex items-center gap-6 text-xs text-muted-foreground font-mono">
            <span>Security controls configurable</span>
            <span>·</span>
            <span>GST data integration ready</span>
          </div>
          <div className="text-xs text-muted-foreground font-mono">
            &copy; 2026 ReconAI Inc. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}
