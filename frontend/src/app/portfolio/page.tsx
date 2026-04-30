"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { PieChart, AlertTriangle, Plus, X } from "lucide-react";
import { optimizePortfolio } from "@/lib/api";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Card, CardTitle, Badge, StatCard, Skeleton } from "@/components/ui";
import type { PortfolioResult } from "@/types";

export default function PortfolioPage() {
  const [tickers, setTickers] = useState<string[]>(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]);
  const [input, setInput] = useState("");
  const [amount, setAmount] = useState(10000);
  const [risk, setRisk] = useState("moderate");

  const mutation = useMutation({
    mutationFn: () => optimizePortfolio(tickers, amount, risk),
  });

  const addTicker = () => {
    const t = input.trim().toUpperCase();
    if (t && !tickers.includes(t)) { setTickers([...tickers, t]); setInput(""); }
  };

  const removeTicker = (t: string) => setTickers(tickers.filter((x) => x !== t));
  const result = mutation.data;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center gap-2 mb-2">
        <PieChart size={20} className="text-accent" />
        <h1 className="text-xl font-bold">Portfolio Optimizer</h1>
      </div>

      {/* Form */}
      <Card>
        <div className="space-y-4">
          <div>
            <label className="text-xs text-gray-500 uppercase tracking-wider block mb-2">Tickers</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {tickers.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 px-2.5 py-1 bg-background border border-border rounded-lg text-xs font-mono">
                  {t} <button onClick={() => removeTicker(t)} className="text-gray-600 hover:text-bearish"><X size={12} /></button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addTicker()} placeholder="Add ticker..." className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent/50" />
              <button onClick={addTicker} className="px-3 py-2 bg-accent/10 text-accent border border-accent/30 rounded-lg text-sm hover:bg-accent/20"><Plus size={14} /></button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-500 uppercase tracking-wider block mb-2">Investment ($)</label>
              <input type="number" value={amount} onChange={(e) => setAmount(Number(e.target.value))} className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-accent/50" />
            </div>
            <div>
              <label className="text-xs text-gray-500 uppercase tracking-wider block mb-2">Risk Tolerance</label>
              <div className="flex gap-2">
                {["conservative", "moderate", "aggressive"].map((r) => (
                  <button key={r} onClick={() => setRisk(r)} className={cn("flex-1 py-2 text-xs rounded-lg border transition-colors capitalize", r === risk ? "border-accent bg-accent/10 text-accent" : "border-border text-gray-500 hover:border-gray-600")}>
                    {r}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button onClick={() => mutation.mutate()} disabled={tickers.length < 2 || mutation.isPending} className="w-full py-2.5 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent/90 disabled:opacity-50 transition-colors">
            {mutation.isPending ? "Optimizing..." : "Optimize Portfolio"}
          </button>
        </div>
      </Card>

      {/* Results */}
      {result?.error && (
        <Card className="border-bearish/30"><p className="text-bearish text-sm">{result.error}</p></Card>
      )}

      {result && !result.error && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Expected Return" value={`${formatPercent(result.summary?.expectedReturn)}`} variant="bullish" />
            <StatCard label="Volatility" value={formatPercent(result.summary?.volatility)} variant="warning" />
            <StatCard label="Sharpe Ratio" value={(result.summary?.sharpeRatio ?? 0).toFixed(3)} />
            <StatCard label="Assets" value={String(result.summary?.numAssets ?? 0)} />
          </div>

          <Card>
            <CardTitle>Optimal Allocation</CardTitle>
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-sm">
                <thead><tr className="text-gray-500 text-xs border-b border-border">
                  <th className="pb-2 text-left font-medium">Ticker</th>
                  <th className="pb-2 text-right font-medium">Weight</th>
                  <th className="pb-2 text-right font-medium">Allocation</th>
                  <th className="pb-2 text-right font-medium">Shares</th>
                  <th className="pb-2 text-right font-medium">Exp. Return</th>
                  <th className="pb-2 text-right font-medium">Volatility</th>
                  <th className="pb-2 text-right font-medium">Kelly</th>
                </tr></thead>
                <tbody>
                  {(result.positions ?? []).map((p) => (
                    <tr key={p.ticker} className="border-b border-border/50">
                      <td className="py-2.5 font-mono font-medium">{p.ticker}</td>
                      <td className="py-2.5 text-right font-mono">{formatPercent(p.weight)}</td>
                      <td className="py-2.5 text-right font-mono">{formatCurrency(p.allocation)}</td>
                      <td className="py-2.5 text-right font-mono">{p.shares}</td>
                      <td className={cn("py-2.5 text-right font-mono", p.expectedReturn >= 0 ? "text-bullish" : "text-bearish")}>{formatPercent(p.expectedReturn)}</td>
                      <td className="py-2.5 text-right font-mono text-warning">{formatPercent(p.volatility)}</td>
                      <td className="py-2.5 text-right font-mono text-gray-400">{formatPercent(p.kellyFraction)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {result.riskWarnings && result.riskWarnings.length > 0 && (
            <Card className="border-warning/30">
              <CardTitle><span className="flex items-center gap-2"><AlertTriangle size={14} className="text-warning" /> Risk Warnings</span></CardTitle>
              <div className="space-y-2 mt-2">
                {result.riskWarnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <Badge variant={w.level}>{w.level}</Badge>
                    <span className="text-gray-400">{w.message}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </motion.div>
  );
}
