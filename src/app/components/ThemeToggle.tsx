import { Sun, Moon } from "lucide-react";

interface ThemeToggleProps {
  dark: boolean;
  setDark: (v: boolean) => void;
  className?: string;
}

export default function ThemeToggle({ dark, setDark, className = "" }: ThemeToggleProps) {
  return (
    <button
      onClick={() => setDark(!dark)}
      className={`relative inline-flex h-8 w-16 shrink-0 cursor-pointer rounded-full border border-border p-1 transition-colors duration-500 ease-in-out focus:outline-none focus:ring-1 focus:ring-primary/40 select-none ${
        dark 
          ? "bg-slate-950 shadow-[inset_0_2px_4px_rgba(0,0,0,0.6)]" 
          : "bg-gradient-to-r from-sky-100 to-amber-100 shadow-[inset_0_2px_4px_rgba(0,0,0,0.05)]"
      } ${className}`}
      aria-label="Toggle Theme"
    >
      {/* Background static icons to give context under the slider */}
      <div className="absolute inset-0 flex justify-between items-center px-2 pointer-events-none select-none">
        <Sun size={12} className={`text-amber-500/50 stroke-[2.5] transition-opacity duration-300 ${dark ? 'opacity-100' : 'opacity-0'}`} />
        <Moon size={12} className={`text-indigo-400/50 stroke-[2.5] transition-opacity duration-300 ${dark ? 'opacity-0' : 'opacity-100'}`} />
      </div>

      {/* Sliding background indicator / thumb */}
      <span
        style={{ transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)" }}
        className={`pointer-events-none flex h-6 w-6 items-center justify-center rounded-full shadow-md transform transition-all duration-500 ${
          dark 
            ? "translate-x-8 bg-slate-900 border border-slate-700 text-yellow-200" 
            : "translate-x-0 bg-white text-amber-500"
        }`}
      >
        <span className="relative h-4 w-4 flex items-center justify-center">
          <Sun
            size={14}
            className={`absolute h-4 w-4 stroke-[2.5] transition-all duration-500 ease-out transform ${
              dark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100"
            }`}
          />
          <Moon
            size={14}
            className={`absolute h-4 w-4 stroke-[2.5] transition-all duration-500 ease-out transform ${
              dark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0"
            }`}
          />
        </span>
      </span>
    </button>
  );
}
