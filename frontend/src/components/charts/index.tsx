"use client";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, ComposedChart, Line } from "recharts";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { HistoryPoint, PredictionPoint } from "@/types";

export function PriceChart({ data, height = 300 }: { data: HistoryPoint[]; height?: number }) {
  if (!data?.length) return <div className="h-48 flex items-center justify-center text-gray-600">No data</div>;
  const first = data[0]?.close ?? 0;
  const last = data[data.length - 1]?.close ?? 0;
  const isUp = last >= first;
  const color = isUp ? "#22c55e" : "#ef4444";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.15} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
        <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => { try { return new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" }); } catch { return ""; } }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => `$${v.toFixed(0)}`} domain={["auto", "auto"]} width={60} />
        <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => formatDate(String(v))} formatter={(v: number) => [formatCurrency(v), "Price"]} />
        <Area type="monotone" dataKey="close" stroke={color} strokeWidth={1.5} fill="url(#colorPrice)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function VolumeChart({ data, height = 120 }: { data: HistoryPoint[]; height?: number }) {
  if (!data?.length) return null;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 0, right: 5, left: 0, bottom: 0 }}>
        <XAxis dataKey="date" tick={false} />
        <YAxis tick={{ fill: "#64748b", fontSize: 9 }} tickFormatter={(v) => `${(v / 1e6).toFixed(0)}M`} width={45} />
        <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [`${(v / 1e6).toFixed(1)}M`, "Volume"]} />
        <Bar dataKey="volume" fill="#3b82f620" stroke="#3b82f640" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function PredictionChart({ predictions, currentPrice, height = 350 }: { predictions: PredictionPoint[]; currentPrice: number; height?: number }) {
  if (!predictions?.length) return <div className="h-48 flex items-center justify-center text-gray-600">No predictions</div>;
  const last = predictions[predictions.length - 1]?.price ?? currentPrice;
  const isUp = last >= currentPrice;
  const color = isUp ? "#22c55e" : "#ef4444";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={predictions} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="colorBand" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.08} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
        <XAxis dataKey="date" tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => { try { return new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" }); } catch { return ""; } }} interval="preserveStartEnd" />
        <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(v) => `$${v.toFixed(0)}`} domain={["auto", "auto"]} width={60} />
        <Tooltip contentStyle={{ background: "#12121a", border: "1px solid #1e1e2e", borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => formatDate(String(v))} />
        <Area type="monotone" dataKey="upper" stroke="none" fill="url(#colorBand)" />
        <Area type="monotone" dataKey="lower" stroke="none" fill="transparent" />
        <Line type="monotone" dataKey="upper" stroke={color} strokeWidth={1} strokeDasharray="4 4" dot={false} name="Upper" />
        <Line type="monotone" dataKey="lower" stroke={color} strokeWidth={1} strokeDasharray="4 4" dot={false} name="Lower" />
        <Line type="monotone" dataKey="price" stroke={color} strokeWidth={2} dot={false} name="Predicted" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
