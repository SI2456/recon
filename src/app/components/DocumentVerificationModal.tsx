import React, { useState, useEffect } from "react";
import {
  X, ZoomIn, ZoomOut, RotateCcw, Save, Download,
  FileText, Building2, UserCheck, Package, Receipt, LandPlot,
  ChevronLeft, ChevronRight, Loader2, Sparkles, ExternalLink, AlertTriangle,
  ShieldAlert, Bell, CheckCircle2, Database, Activity, MapPin, CreditCard, Monitor, Cpu
} from "lucide-react";
import { API_BASE_URL, apiRequest } from "../lib/api";

interface VerificationDetails {
  id: string;
  uploadId: string;
  fileName: string;
  invoiceInfo: {
    invoiceNumber: string;
    invoiceDate: string;
    invoiceType: string;
    documentTitle: string;
    poNumber: string;
    dueDate: string;
    currency: string;
  };
  supplierInfo: {
    supplierName: string;
    supplierGstin: string;
    supplierAddress: string;
    supplierState: string;
    supplierCity: string;
    supplierPin: string;
    supplierPhone: string;
    supplierEmail: string;
  };
  buyerInfo: {
    buyerName: string;
    buyerGstin: string;
    buyerState: string;
    billingAddress: string;
    shippingAddress: string;
    placeOfSupply: string;
  };
  productInfo: {
    lineItems: any[];
    tableHeaders: string[];
    hsnSac: string;
    subtotal: string;
    taxableAmount: string;
    grandTotal: string;
    totalInWords: string;
  };
  taxInfo: {
    cgstRate: string;
    sgstRate: string;
    cgstAmount: string;
    sgstAmount: string;
    totalTaxAmount: string;
  };
  paymentInfo: {
    balanceDue: string;
    bankName: string;
    accountNumber: string;
    ifscCode: string;
    accountHolder: string;
    branch: string;
  };
}

interface FraudFinding {
  code: string;
  check: string;
  link: number;
  weight: number;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
}

interface FraudAssessment {
  score: number;
  riskLabel?: string;
  findings: FraudFinding[];
  checks: { key: string; label: string; passed: boolean }[];
  invoiceKnown: boolean;
  invoiceStatus?: string;
  message?: string;
  alert: { id: number; type: string; risk: number; reason: string; shap: string[]; status: string } | null;
}

interface DocumentVerificationModalProps {
  documentId: string;
  onClose: () => void;
  onRefresh?: () => void;
}

export default function DocumentVerificationModal({
  documentId,
  onClose,
  onRefresh,
}: DocumentVerificationModalProps) {
  const [editMode, setEditMode] = useState(false);
  const [showFraudModal, setShowFraudModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages] = useState(1);

  const [data, setData] = useState<VerificationDetails | null>(null);
  const [fraud, setFraud] = useState<FraudAssessment | null>(null);
  const [fraudLoading, setFraudLoading] = useState(false);
  const [fraudError, setFraudError] = useState("");

  // The assessment is fetched when the panel is opened, and re-fetched after a
  // save so corrections are reflected immediately.
  const loadFraud = async () => {
    setFraudLoading(true);
    setFraudError("");
    try {
      const res = await apiRequest<{ assessment: FraudAssessment }>(
        `/api/extract/fraud/${documentId}`,
        { auth: true }
      );
      setFraud(res.assessment);
    } catch (err) {
      setFraudError(err instanceof Error ? err.message : "Could not run fraud checks.");
    } finally {
      setFraudLoading(false);
    }
  };

  const openFraud = () => {
    setShowFraudModal(true);
    loadFraud();
  };

  useEffect(() => {
    async function loadDetails() {
      setLoading(true);
      try {
        const res = await apiRequest<{ details: VerificationDetails }>(`/api/extract/details/${documentId}`, { auth: true });
        setData(res.details);
      } catch (err) {
        setStatusMsg(err instanceof Error ? err.message : "Failed to load document extraction details.");
      } finally {
        setLoading(false);
      }
    }
    loadDetails();
  }, [documentId]);

  const handleInputChange = (section: keyof VerificationDetails, field: string, value: string) => {
    if (!data) return;
    setData({
      ...data,
      [section]: {
        ...(data[section] as object),
        [field]: value,
      },
    });
  };

  const handleSave = async () => {
    if (!data) return;
    setSaving(true);
    setStatusMsg("");
    try {
      await apiRequest(`/api/extract/details/${documentId}`, {
        method: "PATCH",
        auth: true,
        body: JSON.stringify(data),
      });
      setStatusMsg("✓ Extraction details saved to the database.");
      onRefresh?.();
      // Corrections change what the checks see — re-run them.
      if (showFraudModal || fraud) loadFraud();
      setTimeout(() => setStatusMsg(""), 3500);
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : "Could not save extraction changes.");
    } finally {
      setSaving(false);
    }
  };

  const handleDownload = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.fileName || "extracted_invoice"}_verified.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center">
        <div className="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl p-8 flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-amber-500" />
          <div className="text-sm font-medium">Running extract.py & Parsing JSON Outputs...</div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  // The iframe and the "Open PDF" link are plain browser GETs and cannot set an
  // Authorization header, so the token travels as a query parameter instead.
  const fileUrl =
    `${API_BASE_URL}/api/uploads/file/${data.uploadId || documentId}` +
    `?token=${encodeURIComponent(localStorage.getItem("reconai_token") || "")}`;

  // Helper for rendering form fields with RED missing warnings when empty
  const renderField = (
    label: string,
    value: string,
    section: keyof VerificationDetails,
    field: string,
    mono: boolean = false,
    colSpan: boolean = false
  ) => {
    const isMissing = !value || value.trim() === "" || value === "0.00" || value === "0.0";
    return (
      <div className={colSpan ? "col-span-2" : ""}>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-slate-400 font-medium">{label}</label>
          {isMissing && (
            <span className="text-[10px] font-bold text-rose-400 bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/30 flex items-center gap-1">
              <AlertTriangle size={10} /> Missing
            </span>
          )}
        </div>
        <input
          type="text"
          disabled={!editMode}
          value={value || ""}
          placeholder={isMissing ? "? Missing (Click Edit Mode to enter)" : ""}
          onChange={e => handleInputChange(section, field, e.target.value)}
          className={`w-full rounded-lg px-3 py-2 text-xs transition-colors focus:outline-none ${
            mono ? "font-mono" : ""
          } ${
            isMissing
              ? "bg-rose-950/20 border border-rose-500/60 text-rose-300 placeholder:text-rose-400/50 focus:border-rose-400"
              : "bg-slate-900 border border-slate-700/80 text-slate-100 disabled:opacity-75 disabled:bg-slate-950 focus:border-amber-500"
          }`}
        />
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/95 backdrop-blur-md flex flex-col overflow-hidden text-slate-100 font-sans">
      {/* Top Header Bar */}
      <header className="h-16 px-6 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
            <FileText className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <div className="text-base font-bold text-slate-100 flex items-center gap-2">
              <span>{data.fileName}</span>
              {editMode && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 font-mono">
                  Edit Mode Active
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Page & Zoom Controls */}
        <div className="flex items-center gap-4 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="p-1 hover:bg-slate-800 rounded disabled:opacity-30"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="font-mono text-slate-300">Page {currentPage} / {totalPages}</span>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
              className="p-1 hover:bg-slate-800 rounded disabled:opacity-30"
            >
              <ChevronRight size={14} />
            </button>
          </div>

          <div className="h-4 w-px bg-slate-800" />

          <div className="flex items-center gap-1.5">
            <button onClick={() => setZoom(z => Math.max(50, z - 15))} className="p-1 hover:bg-slate-800 rounded">
              <ZoomOut size={14} />
            </button>
            <span className="font-mono w-12 text-center text-slate-300">{zoom}%</span>
            <button onClick={() => setZoom(z => Math.min(200, z + 15))} className="p-1 hover:bg-slate-800 rounded">
              <ZoomIn size={14} />
            </button>
            <button onClick={() => setZoom(100)} className="p-1 hover:bg-slate-800 rounded text-slate-400">
              <RotateCcw size={12} />
            </button>
          </div>
        </div>

        {/* Edit Mode Switch & Save Actions */}
        <div className="flex items-center gap-3">
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs text-amber-400 hover:underline bg-slate-800/80 px-2.5 py-1.5 rounded-lg border border-slate-700"
          >
            <ExternalLink size={12} />
            <span>Open PDF</span>
          </a>

          <div className="flex items-center gap-2 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
            <span className="text-slate-400 font-medium">Edit Mode</span>
            <button
              type="button"
              onClick={() => setEditMode(!editMode)}
              className={`w-10 h-5 rounded-full transition-colors relative flex items-center p-0.5 ${editMode ? "bg-amber-500" : "bg-slate-800"}`}
            >
              <div className={`w-4 h-4 rounded-full bg-white shadow-md transition-transform ${editMode ? "translate-x-5" : "translate-x-0"}`} />
            </button>
          </div>

          <button
            type="button"
            onClick={openFraud}
            className="flex items-center gap-1.5 text-xs font-bold bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white px-3.5 py-2 rounded-lg transition-all shadow-md shadow-red-950/40"
          >
            <ShieldAlert size={14} />
            <span>Fraud Detection</span>
          </button>

          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-2 rounded-lg transition-colors shadow-lg shadow-emerald-900/30 disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            <span>Save Changes</span>
          </button>

          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 text-xs border border-slate-800 bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded-lg transition-colors"
          >
            <Download size={14} />
            <span>Download Data</span>
          </button>

          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {/* Status Banner */}
      {statusMsg && (
        <div className="bg-emerald-950/80 border-b border-emerald-800/50 text-emerald-300 text-xs px-6 py-2 flex items-center justify-between">
          <span>{statusMsg}</span>
          <button onClick={() => setStatusMsg("")}><X size={12} /></button>
        </div>
      )}

      {/* Dual-Panel Main Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel: Actual PDF Viewer */}
        <div className="w-1/2 bg-slate-950 border-r border-slate-800 flex flex-col relative overflow-hidden">
          <div className="px-4 py-2 bg-slate-900/60 border-b border-slate-800/80 text-xs text-slate-400 flex items-center justify-between">
            <span className="font-mono font-medium">{data.fileName}</span>
            <span className="text-[10px] text-emerald-400">Actual Uploaded Document Binary</span>
          </div>

          <div className="flex-1 overflow-auto p-4 flex justify-center items-start bg-slate-950">
            <div
              style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
              className="transition-transform duration-150 shadow-2xl rounded-lg border border-slate-800 bg-slate-900 w-full h-full min-h-[750px] overflow-hidden"
            >
              <iframe
                src={`${fileUrl}#toolbar=0&navpanes=0`}
                className="w-full h-full min-h-[750px] border-0"
                title="Actual PDF Document"
              />
            </div>
          </div>
        </div>

        {/* Right Panel: All 6 Groups Stacked in One Single Scrollable View */}
        <div className="w-1/2 bg-slate-900 flex flex-col overflow-y-auto p-6 space-y-8">
          
          {/* SECTION 1: Invoice Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2 border-b border-slate-800/80 pb-2.5">
              <FileText size={15} /> 1. Invoice Information
            </div>
            <div className="grid grid-cols-2 gap-4">
              {renderField("Invoice Number", data.invoiceInfo.invoiceNumber, "invoiceInfo", "invoiceNumber", true)}
              {renderField("Invoice Date", data.invoiceInfo.invoiceDate, "invoiceInfo", "invoiceDate", true)}
              {renderField("Invoice Type", data.invoiceInfo.invoiceType, "invoiceInfo", "invoiceType")}
              {renderField("Document Title", data.invoiceInfo.documentTitle, "invoiceInfo", "documentTitle")}
              {renderField("PO Number", data.invoiceInfo.poNumber, "invoiceInfo", "poNumber")}
              {renderField("Due Date", data.invoiceInfo.dueDate, "invoiceInfo", "dueDate")}
              {renderField("Currency", data.invoiceInfo.currency, "invoiceInfo", "currency", false, true)}
            </div>
          </section>

          {/* SECTION 2: Supplier Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2 border-b border-slate-800/80 pb-2.5">
              <Building2 size={15} /> 2. Supplier Information
            </div>
            <div className="grid grid-cols-2 gap-4">
              {renderField("Supplier Name", data.supplierInfo.supplierName, "supplierInfo", "supplierName")}
              {renderField("Supplier GSTIN", data.supplierInfo.supplierGstin, "supplierInfo", "supplierGstin", true)}
              {renderField("Supplier Address", data.supplierInfo.supplierAddress, "supplierInfo", "supplierAddress", false, true)}
              {renderField("Supplier State", data.supplierInfo.supplierState, "supplierInfo", "supplierState")}
              {renderField("Supplier City", data.supplierInfo.supplierCity, "supplierInfo", "supplierCity")}
              {renderField("Supplier PIN Code", data.supplierInfo.supplierPin, "supplierInfo", "supplierPin", true)}
              {renderField("Supplier Phone", data.supplierInfo.supplierPhone, "supplierInfo", "supplierPhone")}
              {renderField("Supplier Email", data.supplierInfo.supplierEmail, "supplierInfo", "supplierEmail", false, true)}
            </div>
          </section>

          {/* SECTION 3: Buyer Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2 border-b border-slate-800/80 pb-2.5">
              <UserCheck size={15} /> 3. Buyer Information
            </div>
            <div className="grid grid-cols-2 gap-4">
              {renderField("Buyer Name", data.buyerInfo.buyerName, "buyerInfo", "buyerName")}
              {renderField("Buyer GSTIN", data.buyerInfo.buyerGstin, "buyerInfo", "buyerGstin", true)}
              {renderField("Buyer State", data.buyerInfo.buyerState, "buyerInfo", "buyerState")}
              {renderField("Place of Supply", data.buyerInfo.placeOfSupply, "buyerInfo", "placeOfSupply")}
              {renderField("Billing Address", data.buyerInfo.billingAddress, "buyerInfo", "billingAddress", false, true)}
              {renderField("Shipping Address", data.buyerInfo.shippingAddress, "buyerInfo", "shippingAddress", false, true)}
            </div>
          </section>

          {/* SECTION 4: Product / Item Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center justify-between border-b border-slate-800/80 pb-2.5">
              <span className="flex items-center gap-2"><Package size={15} /> 4. Product / Item Information</span>
              <span className="text-[11px] text-slate-400 font-mono">{(data.productInfo.lineItems || []).length} Item(s)</span>
            </div>

            {/* Line Items Table */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 bg-slate-950 text-slate-400 font-medium">
                      {(data.productInfo.tableHeaders || ["#", "Item Description", "HSN/SAC", "Qty", "Rate", "Taxable", "GST", "Total"]).map((h, i) => (
                        <th key={i} className="text-left px-3 py-2 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800 font-mono text-[11px]">
                    {(data.productInfo.lineItems || []).map((row: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-800/40">
                        {Array.isArray(row) ? (
                          row.map((cell: any, cidx: number) => (
                            <td key={cidx} className="px-3 py-2">
                              {editMode ? (
                                <input
                                  type="text"
                                  value={String(cell || "")}
                                  onChange={e => {
                                    const newItems = [...data.productInfo.lineItems];
                                    newItems[idx][cidx] = e.target.value;
                                    handleInputChange("productInfo", "lineItems", newItems as any);
                                  }}
                                  className="bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] w-full text-slate-100 focus:outline-none focus:border-amber-500"
                                />
                              ) : (
                                String(cell || "—")
                              )}
                            </td>
                          ))
                        ) : (
                          <td colSpan={8} className="px-3 py-2 text-slate-400">{JSON.stringify(row)}</td>
                        )}
                      </tr>
                    ))}
                    {(data.productInfo.lineItems || []).length === 0 && (
                      <tr>
                        <td colSpan={8} className="px-4 py-4 text-center text-rose-400 bg-rose-950/20 font-sans">
                          ⚠️ No line item rows extracted. Enable Edit Mode to add manual items.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
              {renderField("HSN / SAC Code", data.productInfo.hsnSac, "productInfo", "hsnSac", true)}
              {renderField("Subtotal", data.productInfo.subtotal, "productInfo", "subtotal", true)}
              {renderField("Taxable Amount", data.productInfo.taxableAmount, "productInfo", "taxableAmount", true)}
              {renderField("Grand Total", data.productInfo.grandTotal, "productInfo", "grandTotal", true)}
              {renderField("Total In Words", data.productInfo.totalInWords, "productInfo", "totalInWords")}
            </div>
          </section>

          {/* SECTION 5: Tax Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2 border-b border-slate-800/80 pb-2.5">
              <Receipt size={15} /> 5. Tax Information
            </div>
            <div className="grid grid-cols-2 gap-4">
              {renderField("CGST Rate", data.taxInfo.cgstRate, "taxInfo", "cgstRate", true)}
              {renderField("SGST Rate", data.taxInfo.sgstRate, "taxInfo", "sgstRate", true)}
              {renderField("CGST Amount", data.taxInfo.cgstAmount, "taxInfo", "cgstAmount", true)}
              {renderField("SGST Amount", data.taxInfo.sgstAmount, "taxInfo", "sgstAmount", true)}
              {renderField("Total Tax Amount", data.taxInfo.totalTaxAmount, "taxInfo", "totalTaxAmount", true, true)}
            </div>
          </section>

          {/* SECTION 6: Payment / Bank Information */}
          <section className="bg-slate-950/80 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2 border-b border-slate-800/80 pb-2.5">
              <LandPlot size={15} /> 6. Payment / Bank Information
            </div>
            <div className="grid grid-cols-2 gap-4">
              {renderField("Balance Due", data.paymentInfo.balanceDue, "paymentInfo", "balanceDue", true)}
              {renderField("Bank Name", data.paymentInfo.bankName, "paymentInfo", "bankName")}
              {renderField("Account Number", data.paymentInfo.accountNumber, "paymentInfo", "accountNumber", true)}
              {renderField("IFSC Code", data.paymentInfo.ifscCode, "paymentInfo", "ifscCode", true)}
              {renderField("Account Holder", data.paymentInfo.accountHolder, "paymentInfo", "accountHolder")}
              {renderField("Branch", data.paymentInfo.branch, "paymentInfo", "branch")}
            </div>
          </section>

        </div>
      </div>

      {/* FRAUD DETECTION SYSTEM MODAL (FULL SCREEN matching user's screenshot layout & color format) */}
      {showFraudModal && (
        <div className="fixed inset-0 z-[100] w-screen h-screen bg-[#070A13] flex flex-col overflow-hidden font-sans text-slate-100">
          <div className="w-full h-full flex flex-col bg-[#0B0F19] text-slate-100 overflow-y-auto">
            
            {/* Top Blue Header Bar with ALERT badge */}
            <div className="bg-gradient-to-r from-sky-600 via-blue-600 to-indigo-700 px-8 py-4 flex items-center justify-between shadow-lg shrink-0">
              <div className="flex items-center gap-3">
                <ShieldAlert className="w-7 h-7 text-white animate-pulse" />
                <h2 className="text-2xl font-black tracking-wider text-white uppercase font-sans">
                  FRAUD DETECTION SYSTEM
                </h2>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 bg-amber-400 text-slate-950 font-black px-4 py-1.5 rounded-full text-xs shadow-md border border-amber-300">
                  <span className="tracking-wide">ALERT</span>
                  <Bell size={15} className="animate-bounce text-slate-950" />
                </div>
                <button
                  type="button"
                  onClick={() => setShowFraudModal(false)}
                  className="p-2 rounded-xl bg-black/20 hover:bg-black/40 text-white transition-colors border border-white/20"
                >
                  <X size={20} />
                </button>
              </div>
            </div>

            <div className="p-8 space-y-8 bg-[#0B0F19] flex-1">
              
              {/* 8-Step Pipeline Visual Flow */}
              <div className="bg-[#0D1424] border border-[#1E293B] rounded-2xl p-5 shadow-xl">
                <div className="grid grid-cols-4 md:grid-cols-8 gap-4 min-w-[760px] text-center">
                  {[
                    { step: 1, title: "DATA COLLECTION", desc: "Data & form collections", icon: Database, color: "text-sky-400 border-sky-500/50 bg-sky-500/15" },
                    { step: 2, title: "IDENTITY VERIFICATION", desc: "Fingerprint, ID, GSTIN", icon: UserCheck, color: "text-indigo-400 border-indigo-500/50 bg-indigo-500/15" },
                    { step: 3, title: "LOCATION ANALYSIS", desc: "Geolocation, state maps", icon: MapPin, color: "text-amber-400 border-amber-500/50 bg-amber-500/15" },
                    { step: 4, title: "BEHAVIORAL PROFILING", desc: "Activity logs, patterns", icon: Activity, color: "text-emerald-400 border-emerald-500/50 bg-emerald-500/15" },
                    { step: 5, title: "TRANSACTION MONITORING", desc: "Payment card, tax checks", icon: CreditCard, color: "text-blue-400 border-blue-500/50 bg-blue-500/15" },
                    { step: 6, title: "DEVICE FINGERPRINTING", desc: "IP, phone, tablet, comp", icon: Monitor, color: "text-purple-400 border-purple-500/50 bg-purple-500/15" },
                    { step: 7, title: "MACHINE LEARNING SCORING", desc: "Neural net, graphs, SHAP", icon: Cpu, color: "text-rose-400 border-rose-500/50 bg-rose-500/15" },
                    { step: 8, title: "FINAL ALERT & DECISION", desc: "Report, flag decision", icon: ShieldAlert, color: "text-red-400 border-red-500/50 bg-red-500/15" },
                  ].map((s) => {
                    const Icon = s.icon;
                    return (
                      <div key={s.step} className="flex flex-col items-center gap-2.5 p-3 rounded-xl bg-[#090D18] border border-[#1E293B] hover:border-sky-500/60 transition-all shadow-sm">
                        <div className={`w-9 h-9 rounded-full flex items-center justify-center font-extrabold text-sm border ${s.color}`}>
                          {s.step}
                        </div>
                        <Icon size={18} className="text-slate-300" />
                        <div className="text-[11px] font-extrabold text-slate-200 uppercase tracking-tight leading-tight">
                          {s.title}
                        </div>
                        <div className="text-[10px] text-slate-400 leading-tight">
                          {s.desc}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* PARTICULAR PAGE REPORT Panel */}
              <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
                
                {/* Left Panel: Table List & Checklist Status */}
                <div className="md:col-span-7 bg-[#0D1424] border border-[#1E293B] rounded-2xl p-6 space-y-5 shadow-xl">
                  <div className="flex items-center justify-between border-b border-[#1E293B] pb-4">
                    <h3 className="text-sm font-black uppercase tracking-wider text-sky-400 font-sans flex items-center gap-2">
                      PARTICULAR PAGE REPORT — {data.fileName}
                    </h3>
                    <span className="text-xs bg-[#1E293B] text-slate-300 px-3 py-1 rounded-md font-mono border border-slate-700">
                      Document ID: {String(documentId).slice(0, 12)}
                    </span>
                  </div>

                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#1E293B] text-slate-400 text-[11px] font-black uppercase tracking-wider">
                        <th className="text-left py-3">TABLE LIST</th>
                        <th className="text-right py-3">STATUS</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#1E293B]">
                      {(fraud?.checks || []).map(check => {
                        const hits = (fraud?.findings || []).filter(f => f.check === check.key);
                        return {
                          label: check.label,
                          value: hits.length
                            ? hits.map(f => f.title).join(" • ")
                            : "No issue detected",
                          status: check.passed ? "PASS" : "FAIL",
                        };
                      }).map((item, idx) => (
                        <tr key={idx} className="hover:bg-[#090D18] transition-colors">
                          <td className="py-3">
                            <div className="flex items-center gap-2.5">
                              <div className={`w-5 h-5 rounded flex items-center justify-center font-bold text-xs shrink-0 ${
                                item.status === "PASS" ? "bg-sky-500/20 text-sky-400" : "bg-red-500/20 text-red-400"
                              }`}>
                                {item.status === "PASS" ? "✓" : "!"}
                              </div>
                              <div className="font-bold text-slate-100 text-xs">{item.label}</div>
                            </div>
                            <div className="text-[11px] text-slate-400 font-mono pl-7 mt-0.5">{item.value}</div>
                          </td>
                          <td className="py-3 text-right">
                            <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-md text-xs font-black font-mono shadow-sm ${
                              item.status === "PASS"
                                ? "bg-emerald-600 text-white border border-emerald-400/30"
                                : "bg-red-600 text-white border border-red-400/30"
                            }`}>
                              {item.status === "PASS" ? "✓ PASS" : "✕ FAIL"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Right Panel: Detailed Document Fraud Inspection Summary */}
                <div className="md:col-span-5 bg-[#0D1424] border border-[#1E293B] rounded-2xl p-6 space-y-6 flex flex-col justify-between shadow-xl">
                  <div className="space-y-5">
                    <div className="flex items-center justify-between border-b border-[#1E293B] pb-4">
                      <div className="text-xs font-black uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-2">
                        <Activity size={16} /> Document Inspection Risk Score
                      </div>
                      <span className={`text-xs font-mono font-black px-3 py-1 rounded-md border ${
                        !fraud || fraud.score < 25
                          ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                          : fraud.score < 50
                          ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                          : fraud.score < 70
                          ? "bg-orange-500/20 text-orange-300 border-orange-500/40"
                          : "bg-red-500/20 text-red-300 border-red-500/40"
                      }`}>
                        {fraudLoading
                          ? "Running checks…"
                          : fraud
                          ? `${fraud.score}% ${fraud.riskLabel || ""} Risk`
                          : "—"}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3.5 text-xs">
                      <div className="bg-[#090D18] border border-[#1E293B] rounded-xl p-3.5">
                        <div className="text-[10px] text-slate-400 uppercase font-medium">Invoice Number</div>
                        <div className="font-mono font-bold text-slate-100 mt-1">{data.invoiceInfo.invoiceNumber || "N/A"}</div>
                      </div>
                      <div className="bg-[#090D18] border border-[#1E293B] rounded-xl p-3.5">
                        <div className="text-[10px] text-slate-400 uppercase font-medium">Supplier Legal Name</div>
                        <div className="font-bold text-slate-100 mt-1 truncate">{data.supplierInfo.supplierName || "N/A"}</div>
                      </div>
                      <div className="bg-[#090D18] border border-[#1E293B] rounded-xl p-3.5">
                        <div className="text-[10px] text-slate-400 uppercase font-medium">Taxable Amount</div>
                        <div className="font-mono font-bold text-amber-400 mt-1 text-sm">₹{data.productInfo.taxableAmount || "0.00"}</div>
                      </div>
                      <div className="bg-[#090D18] border border-[#1E293B] rounded-xl p-3.5">
                        <div className="text-[10px] text-slate-400 uppercase font-medium">Total Tax (CGST+SGST)</div>
                        <div className="font-mono font-bold text-emerald-400 mt-1 text-sm">₹{data.taxInfo.totalTaxAmount || "0.00"}</div>
                      </div>
                    </div>

                    <div className="space-y-2.5 pt-2">
                      <div className="text-xs font-black uppercase tracking-wider text-slate-300">
                        {fraud && fraud.findings.length > 0 ? "Findings" : "Risk Factors"}
                      </div>

                      {fraudError && (
                        <div className="text-xs bg-red-950/40 border border-red-900/60 text-red-300 p-3 rounded-lg">{fraudError}</div>
                      )}

                      {!fraudError && fraudLoading && (
                        <div className="flex items-center gap-2 text-xs text-slate-400 py-3">
                          <Loader2 size={14} className="animate-spin" /> Running integrity checks…
                        </div>
                      )}

                      {!fraudLoading && fraud && !fraud.invoiceKnown && (
                        <div className="text-xs bg-amber-950/30 border border-amber-900/50 text-amber-300 p-3 rounded-lg">
                          {fraud.message || "This document has not been processed yet."}
                        </div>
                      )}

                      {!fraudLoading && fraud && fraud.invoiceKnown && fraud.findings.length === 0 && (
                        <div className="flex items-center gap-2 text-xs bg-emerald-950/30 border border-emerald-900/50 text-emerald-300 p-3 rounded-lg">
                          <CheckCircle2 size={14} /> All integrity checks passed — no defect found in this document.
                        </div>
                      )}

                      <div className="space-y-1.5 text-xs">
                        {(fraud?.findings || []).map(f => (
                          <div key={f.code} className="bg-[#090D18] px-3.5 py-2.5 rounded-lg border border-[#1E293B]">
                            <div className="flex items-start justify-between gap-3">
                              <span className="text-slate-200 font-bold">{f.title}</span>
                              <span className={`font-mono font-bold shrink-0 px-1.5 py-0.5 rounded text-[10px] uppercase border ${
                                f.severity === "critical" ? "text-red-300 border-red-500/40 bg-red-500/10"
                                : f.severity === "high" ? "text-orange-300 border-orange-500/40 bg-orange-500/10"
                                : f.severity === "medium" ? "text-amber-300 border-amber-500/40 bg-amber-500/10"
                                : "text-slate-300 border-slate-600/40 bg-slate-500/10"
                              }`}>
                                {f.severity} · +{f.weight}
                              </span>
                            </div>
                            <div className="text-[11px] text-slate-400 mt-1 leading-snug">{f.detail}</div>
                            <div className="text-[10px] text-slate-500 mt-1 font-mono">
                              {f.code} · breaks LINK {f.link}
                            </div>
                          </div>
                        ))}

                        {/* The model's own explanation, when a fraud alert exists. */}
                        {fraud?.alert && (
                          <div className="bg-[#090D18] px-3.5 py-2.5 rounded-lg border border-[#1E293B] mt-2">
                            <div className="flex items-center justify-between">
                              <span className="text-slate-200 font-bold">{fraud.alert.type}</span>
                              <span className="font-mono text-rose-400 font-bold">risk {fraud.alert.risk}</span>
                            </div>
                            <div className="text-[11px] text-slate-400 mt-1">{fraud.alert.reason}</div>
                            {fraud.alert.shap.length > 0 && (
                              <div className="text-[10px] text-slate-500 mt-1 font-mono">
                                SHAP: {fraud.alert.shap.join(" · ")}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="pt-5 border-t border-[#1E293B] flex items-center justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => setShowFraudModal(false)}
                      className="px-5 py-2.5 text-xs font-bold bg-[#1E293B] hover:bg-slate-700 text-slate-200 rounded-xl transition-colors"
                    >
                      Close Fraud Report
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const count = fraud?.findings.length ?? 0;
                        setStatusMsg(
                          count === 0
                            ? `✓ Inspection completed for ${data.fileName}: no anomalies flagged.`
                            : `⚠ Inspection completed for ${data.fileName}: ${count} finding${count === 1 ? "" : "s"} — risk ${fraud?.score ?? 0}%.`
                        );
                        setShowFraudModal(false);
                      }}
                      className="px-5 py-2.5 text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl transition-colors shadow-lg shadow-emerald-950/40"
                    >
                      Approve & Clear Risk
                    </button>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>
      )}
    </div>
  );
}
