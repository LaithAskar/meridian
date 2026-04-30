import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value?: number | null, decimals = 2): string {
  try {
    if (value == null || isNaN(value)) return "$0.00";
    const v = Number(value);
    if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(decimals)}T`;
    if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(decimals)}B`;
    if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(decimals)}M`;
    return `$${v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
  } catch { return "$0.00"; }
}

export function formatPercent(value?: number | null, decimals = 2): string {
  try {
    if (value == null || isNaN(value)) return "0.00%";
    return `${Number(value).toFixed(decimals)}%`;
  } catch { return "0.00%"; }
}

export function formatNumber(value?: number | null, decimals = 2): string {
  try {
    if (value == null || isNaN(value)) return "0";
    const v = Number(value);
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toLocaleString("en-US", { maximumFractionDigits: decimals });
  } catch { return "0"; }
}

export function formatDate(dateStr?: string | null): string {
  try {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch { return "—"; }
}

export function formatTime(dateStr?: string | null): string {
  try {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

export function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function scoreColor(score: number): string {
  if (score >= 70) return "text-bullish";
  if (score >= 40) return "text-warning";
  return "text-bearish";
}

export function sentimentColor(label?: string): string {
  if (!label) return "text-gray-400";
  const l = label.toLowerCase();
  if (l === "bullish" || l === "positive" || l === "buy") return "text-bullish";
  if (l === "bearish" || l === "negative" || l === "sell") return "text-bearish";
  return "text-gray-400";
}
