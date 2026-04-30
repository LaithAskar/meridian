"use client";
import { cn } from "@/lib/utils";
import { type ReactNode } from "react";
import { motion } from "framer-motion";

// ── Card ───────────────────────────────────────────────────
export function Card({ children, className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("bg-card border border-border rounded-xl p-5", className)} {...props}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mb-4", className)}>{children}</div>;
}

export function CardTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn("text-sm font-medium text-gray-400 uppercase tracking-wider", className)}>{children}</h3>;
}

// ── Badge ──────────────────────────────────────────────────
const badgeVariants: Record<string, string> = {
  bullish: "bg-bullish/15 text-bullish border-bullish/30",
  bearish: "bg-bearish/15 text-bearish border-bearish/30",
  neutral: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  warning: "bg-warning/15 text-warning border-warning/30",
  accent: "bg-accent/15 text-accent border-accent/30",
  buy: "bg-bullish/15 text-bullish border-bullish/30",
  sell: "bg-bearish/15 text-bearish border-bearish/30",
  filled: "bg-bullish/15 text-bullish border-bullish/30",
  cancelled: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  pending: "bg-warning/15 text-warning border-warning/30",
  confirmed: "bg-accent/15 text-accent border-accent/30",
};

export function Badge({ children, variant = "neutral", className }: { children: ReactNode; variant?: string; className?: string }) {
  const v = badgeVariants[variant.toLowerCase()] ?? badgeVariants.neutral;
  return <span className={cn("inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-md border", v, className)}>{children}</span>;
}

// ── Skeleton ───────────────────────────────────────────────
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse bg-border-light rounded", className)} />;
}

// ── StatCard ───────────────────────────────────────────────
export function StatCard({ label, value, sub, variant = "default", icon }: { label: string; value: string; sub?: string; variant?: string; icon?: ReactNode }) {
  const textColor = variant === "bullish" ? "text-bullish" : variant === "bearish" ? "text-bearish" : variant === "warning" ? "text-warning" : "text-white";
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
        {icon && <span className="text-gray-500">{icon}</span>}
      </div>
      <div className={cn("text-xl font-semibold font-mono", textColor)}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </motion.div>
  );
}

// ── Gauge ──────────────────────────────────────────────────
export function Gauge({ value, max = 100, size = 80, label }: { value: number; max?: number; size?: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const r = (size - 8) / 2;
  const circumference = Math.PI * r;
  const offset = circumference - (pct / 100) * circumference;
  const color = pct >= 70 ? "var(--bullish)" : pct >= 40 ? "var(--warning)" : "var(--bearish)";
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size / 2 + 8} viewBox={`0 0 ${size} ${size / 2 + 8}`}>
        <path d={`M 4 ${size / 2 + 4} A ${r} ${r} 0 0 1 ${size - 4} ${size / 2 + 4}`} fill="none" stroke="#1e1e2e" strokeWidth="6" strokeLinecap="round" />
        <path d={`M 4 ${size / 2 + 4} A ${r} ${r} 0 0 1 ${size - 4} ${size / 2 + 4}`} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} className="transition-all duration-700" />
        <text x={size / 2} y={size / 2} textAnchor="middle" fill={color} fontSize="16" fontWeight="600" fontFamily="JetBrains Mono">{Math.round(pct)}</text>
      </svg>
      {label && <span className="text-xs text-gray-500">{label}</span>}
    </div>
  );
}
