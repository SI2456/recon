import { useState } from "react";
import type { ReactNode } from "react";
import { ArrowLeft, Award, Building, FileText, KeyRound, Landmark, Loader2, Lock, Mail, Phone, RotateCcw, Shield, User } from "lucide-react";
import { apiRequest, type AuthResponse } from "../lib/api";
import { ADMIN, BUSINESS_USER, TAX_REVIEWER, ROLE_SHORT_LABELS, normalizeRole, roleLabel, type Role } from "../lib/roles";

import logoImg from "../../../darkThemeLogo.png";

interface AuthPagesProps {
  initialRole: Role;
  initialMode: "signin" | "signup";
  onBackToLanding: () => void;
  onLogin: (user: {
    name: string;
    email: string;
    role: Role;
    firmName?: string;
    gstin?: string;
    icaiNumber?: string;
  }) => void;
}

type AuthMode = "signin" | "signup" | "verify" | "forgot" | "reset";

export default function AuthPages({ initialRole, initialMode, onBackToLanding, onLogin }: AuthPagesProps) {
  const [role, setRole] = useState<Role>(normalizeRole(initialRole) || TAX_REVIEWER);
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [phone, setPhone] = useState("");
  const [icaiNumber, setIcaiNumber] = useState("");
  const [firmName, setFirmName] = useState("");
  const [clientBusinessName, setClientBusinessName] = useState("");
  const [gstin, setGstin] = useState("");
  const [city, setCity] = useState("");
  const [specialization, setSpecialization] = useState("GST");
  const [experience, setExperience] = useState("0 Years");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const finishLogin = (result: AuthResponse) => {
    localStorage.setItem("reconai_token", result.token);
    localStorage.setItem("reconai_user", JSON.stringify(result.user));
    onLogin(result.user);
  };

  const handleSignIn = async () => {
    const result = await apiRequest<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
      auth: false,
    });
    if (normalizeRole(result.user.role) !== role) throw new Error(`This account is registered as ${roleLabel(result.user.role)}. Select that role to continue.`);
    finishLogin(result);
  };

  const handleRegister = async () => {
    if (!name.trim()) throw new Error("Please provide your full name.");
    if (role === TAX_REVIEWER && (!icaiNumber.trim() || !firmName.trim())) throw new Error("Tax & Compliance Reviewers must provide a membership/registration ID and firm name.");
    if (role === BUSINESS_USER && !clientBusinessName.trim()) throw new Error("Business users must provide a business name.");

    const result = await apiRequest<{ message: string; email: string; devOtp?: string }>("/api/auth/register", {
      method: "POST",
      auth: false,
      body: JSON.stringify({
        name: name.trim(),
        email,
        password,
        role,
        phone,
        firmName: role === TAX_REVIEWER ? firmName.trim() : "",
        gstin: role === BUSINESS_USER ? "" : gstin.trim().toUpperCase(),
        icaiNumber: role === TAX_REVIEWER ? icaiNumber.trim().toUpperCase() : "",
        businessName: role === BUSINESS_USER ? clientBusinessName.trim() : "",
        city,
        specialization,
        experience,
      }),
    });
    setNotice(result.devOtp ? `${result.message} Real-Time OTP: ${result.devOtp}` : result.message);
    if (result.devOtp) setOtp(result.devOtp);
    setMode("verify");
  };

  const handleVerifyOtp = async () => {
    const result = await apiRequest<AuthResponse>("/api/auth/verify-otp", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email, otp }),
    });
    finishLogin(result);
  };

  const handleForgotPassword = async () => {
    const result = await apiRequest<{ message: string; devOtp?: string }>("/api/auth/forgot-password", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email }),
    });
    setNotice(result.devOtp ? `${result.message} Real-Time OTP: ${result.devOtp}` : result.message);
    if (result.devOtp) setOtp(result.devOtp);
    setMode("reset");
  };

  const handleResetPassword = async () => {
    // The server enforces 8; checking the same number here avoids a round trip
    // that would only come back as a 400.
    if (!newPassword || newPassword.length < 8) {
      throw new Error("Password must be at least 8 characters.");
    }
    // The success notice is only shown after the server confirms the change —
    // previously this reported success without ever calling the API, so the
    // password silently stayed as it was.
    await apiRequest("/api/auth/reset-password", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email, otp: otp.trim(), password: newPassword }),
    });
    setNotice("Password reset successfully. You can now sign in with your new password.");
    setPassword("");
    setNewPassword("");
    setOtp("");
    setMode("signin");
  };

  // OTPs are scoped to a purpose, so resending from the reset screen has to ask
  // for a password_reset code — a registration code would never verify. The
  // caller may name the purpose; otherwise it is derived from the screen.
  const handleResendOtp = async (purpose?: "registration" | "password_reset") => {
    const result = await apiRequest<{ message: string; devOtp?: string }>("/api/auth/resend-otp", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email, purpose: purpose ?? (mode === "reset" ? "password_reset" : "registration") }),
    });
    setNotice(result.devOtp ? `${result.message} Real-Time OTP: ${result.devOtp}` : result.message);
    if (result.devOtp) setOtp(result.devOtp);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");
    if (!email.trim()) {
      setError("Please enter your email.");
      return;
    }
    if ((mode === "signin" || mode === "signup") && !password) {
      setError("Please enter your password.");
      return;
    }
    if ((mode === "verify" || mode === "reset") && otp.trim().length !== 6) {
      setError("Please enter the 6-digit OTP.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") await handleSignIn();
      if (mode === "signup") await handleRegister();
      if (mode === "verify") await handleVerifyOtp();
      if (mode === "forgot") await handleForgotPassword();
      if (mode === "reset") await handleResetPassword();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const resetDemoAccount = () => {
    // Keyed by canonical role; the seeded demo addresses keep their original
    // local parts so existing accounts still sign in.
    const demoEmailByRole: Record<Role, string> = {
      admin: "admin.demo@reconai.local",
      tax_reviewer: "ca.demo@reconai.local",
      business_user: "client.demo@reconai.local",
    };
    setMode("signin");
    setEmail(demoEmailByRole[role]);
    setPassword("Demo@123");
    setError("");
    setNotice("");
  };

  const title = mode === "signin" ? "Sign In to ReconAI" : mode === "signup" ? "Register Account" : mode === "verify" ? "Verify Email OTP" : mode === "forgot" ? "Forgot Password" : "Reset Password";

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-4 relative overflow-hidden" style={{ fontFamily: "'Inter', sans-serif" }}>
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-indigo-500/10 rounded-full blur-[120px]" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-amber-500/5 rounded-full blur-[120px]" />

      <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-12 bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl relative z-10">
        <div className="md:col-span-5 bg-gradient-to-b from-slate-900 to-slate-950 p-8 flex flex-col justify-between border-r border-slate-800 text-left">
          <div className="space-y-6">
            <button onClick={onBackToLanding} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">
              <ArrowLeft size={13} /> Back to main
            </button>
            <img src={logoImg} alt="ReconAI Logo" className="h-10 object-contain" />
            <div className="space-y-4">
              <h2 className="text-xl font-semibold tracking-tight text-amber-400">Secure Compliance Login</h2>
              <p className="text-xs text-slate-400 leading-relaxed">
                Email OTP protects account registration and password reset. Clients choose a verified Tax Officer from the directory after login.
              </p>
            </div>
          </div>
          <div className="space-y-4 pt-8 md:pt-0">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded bg-slate-800/60 text-amber-500"><Shield size={16} /></div>
              <div className="text-left">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-300">OTP Verification</div>
                <div className="text-[10px] text-slate-400">SMTP email OTP with 10-minute expiry</div>
              </div>
            </div>
            <div className="border-t border-slate-800 pt-4 text-[10px] text-slate-500 font-mono">ReconAI Auth Gateway</div>
          </div>
        </div>

        <div className="md:col-span-7 p-8 md:p-12 flex flex-col justify-center text-left">
          <div className="space-y-6">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-100">{title}</h1>
              <p className="text-xs text-slate-400 mt-1">Use your verified email credentials to continue.</p>
            </div>

            {(mode === "signin" || mode === "signup") && (
              <div className="flex bg-slate-900 p-1 rounded-lg border border-slate-800">
                {/* Admin accounts are provisioned, not self-registered, so the
                    role is offered for sign-in only. */}
                {(mode === "signup" ? [TAX_REVIEWER, BUSINESS_USER] : [TAX_REVIEWER, BUSINESS_USER, ADMIN]).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => { setRole(r); setError(""); }}
                    className={`flex-1 text-center py-2 text-xs rounded-md font-semibold transition-all ${role === r ? "bg-amber-500 text-slate-950 shadow-md shadow-amber-500/10" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}
                  >
                    {ROLE_SHORT_LABELS[r]}
                  </button>
                ))}
              </div>
            )}

            {error && <div className="text-xs bg-red-950/40 border border-red-900/60 text-red-400 p-3 rounded-lg">{error}</div>}
            {notice && <div className="text-xs bg-emerald-950/40 border border-emerald-900/60 text-emerald-300 p-3 rounded-lg">{notice}</div>}

            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === "signup" && (
                <Field icon={<User size={14} />} label="Full Name" value={name} onChange={setName} placeholder="Full legal name" />
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field icon={<Mail size={14} />} label="Email Address" value={email} onChange={setEmail} placeholder="name@company.com" type="email" />
                {(mode === "signin" || mode === "signup") && <Field icon={<Lock size={14} />} label="Password" value={password} onChange={setPassword} placeholder="Minimum 8 characters" type="password" />}
                {mode === "reset" && <Field icon={<Lock size={14} />} label="New Password" value={newPassword} onChange={setNewPassword} placeholder="Minimum 8 characters" type="password" />}
                {(mode === "verify" || mode === "reset") && <Field icon={<KeyRound size={14} />} label="6-Digit OTP" value={otp} onChange={setOtp} placeholder="123456" />}
              </div>

              {mode === "signup" && <Field icon={<Phone size={14} />} label="Phone Number" value={phone} onChange={setPhone} placeholder="Phone number" />}

              {mode === "signup" && role === TAX_REVIEWER && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 bg-indigo-950/20 border border-indigo-900/30 rounded-lg">
                  <Field icon={<Award size={14} />} label="Tax Officer ID" value={icaiNumber} onChange={setIcaiNumber} placeholder="e.g. TO123456" compact />
                  <Field icon={<Landmark size={14} />} label="Office / Division Name" value={firmName} onChange={setFirmName} placeholder="Division name" compact />
                  <Field icon={<FileText size={14} />} label="Specialization" value={specialization} onChange={setSpecialization} placeholder="GST" compact />
                  <Field icon={<Building size={14} />} label="Experience" value={experience} onChange={setExperience} placeholder="8 Years" compact />
                  <Field icon={<Building size={14} />} label="City" value={city} onChange={setCity} placeholder="Ahmedabad" compact />
                </div>
              )}

              {mode === "signup" && role === BUSINESS_USER && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3 bg-amber-950/10 border border-amber-900/30 rounded-lg">
                  <Field icon={<Building size={14} />} label="Business Name" value={clientBusinessName} onChange={setClientBusinessName} placeholder="Registered business name" compact />
                  <Field icon={<Building size={14} />} label="City" value={city} onChange={setCity} placeholder="Mumbai" compact />
                  <div className="sm:col-span-2 text-[10px] text-slate-500">
                    GSTIN verification happens after login from Client Settings.
                  </div>
                </div>
              )}

              {mode === "signin" && (
                <div className="flex items-center justify-between text-xs pt-1">
                  <button type="button" onClick={resetDemoAccount} className="inline-flex items-center gap-1 text-amber-500 hover:underline">
                    <RotateCcw size={11} /> Reset demo account
                  </button>
                  <button type="button" onClick={() => { setMode("forgot"); setError(""); setNotice(""); }} className="text-amber-500 hover:underline">Forgot password?</button>
                </div>
              )}

              {(mode === "verify" || mode === "reset") && (
                <button
                  type="button"
                  // Outside the form's submit handler, so a failure here has to
                  // be caught and shown or the click looks like it did nothing.
                  onClick={() => {
                    setError("");
                    handleResendOtp(mode === "verify" ? "registration" : "password_reset").catch(err =>
                      setError(err instanceof Error ? err.message : "Could not resend the OTP."),
                    );
                  }}
                  className="text-xs text-amber-500 hover:underline"
                >
                  Resend OTP
                </button>
              )}

              <button disabled={loading} className="w-full py-3 mt-4 rounded-lg bg-amber-500 text-slate-950 font-bold hover:bg-amber-400 transition-colors flex items-center justify-center gap-2 text-xs disabled:opacity-50">
                {loading ? <><Loader2 size={14} className="animate-spin" /> Processing...</> : <span>{mode === "signin" ? `Sign In as ${ROLE_SHORT_LABELS[role]}` : mode === "signup" ? "Register and Send OTP" : mode === "verify" ? "Verify OTP" : mode === "forgot" ? "Send Reset OTP" : "Reset Password"}</span>}
              </button>
            </form>

            <div className="text-center pt-2 text-xs text-slate-400">
              {mode !== "signin" && <button type="button" onClick={() => { setMode("signin"); setError(""); setNotice(""); }} className="text-amber-500 font-semibold hover:underline">Back to Sign In</button>}
              {mode === "signin" && <>Don't have an account? <button type="button" onClick={() => { setMode("signup"); if (role === ADMIN) setRole(TAX_REVIEWER); setError(""); setNotice(""); }} className="text-amber-500 font-semibold hover:underline">Register Now</button></>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ icon, label, value, onChange, placeholder, type = "text", compact = false }: {
  icon: ReactNode;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
  compact?: boolean;
}) {
  return (
    <div>
      <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-1">{label}</label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">{icon}</span>
        <input
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`w-full text-xs pl-9 pr-3 ${compact ? "py-2" : "py-2.5"} bg-slate-900 border border-slate-800 rounded-lg text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/25`}
        />
      </div>
    </div>
  );
}
