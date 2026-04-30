"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Bitcoin, Play, Square, Activity } from "lucide-react";
import { getCryptoStatus, startCrypto, stopCrypto, getCryptoPrices } from "@/lib/api";
import { formatCurrency, formatPercent, formatDate, formatTime, cn } from "@/lib/utils";
import { Card, CardTitle, Badge, StatCard } from "@/components/ui";

export default function CryptoPage() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ["crypto-status"], queryFn: getCryptoStatus, refetchInterval: 15000 });
  const { data: prices } = useQuery({ queryKey: ["crypto-prices"], queryFn: getCryptoPrices, refetchInterval: 30000 });

  const startMut = useMutation({ mutationFn: startCrypto, onSuccess: () => qc.invalidateQueries({ queryKey: ["crypto-status"] }) });
  const stopMut = useMutation({ mutationFn: stopCrypto, onSuccess: () => qc.invalidateQueries({ queryKey: ["crypto-status"] }) });

  const botRunning = status?.running ?? false;
  const trades = status?.trades ?? [];
  const todayTrades = trades.filter((t) => { try { return t.timestamp?.startsWith(new Date().toISOString().slice(0, 10)); } catch { return false; } });
  const todayPnl = todayTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  const wins = todayTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const losses = todayTrades.filter((t) => (t.pnl ?? 0) < 0).length;
  const winRate = todayTrades.length > 0 ? (wins / todayTrades.length * 100) : 0;
  const openPositions = trades.filter((t) => t.side === "buy").length - trades.filter((t) => t.side === "sell").length;

  const coinIcons: Record<string, string> = { BTC: "₿", ETH: "Ξ", SOL: "◎", LINK: "⬡", AVAX: "△", DOGE: "Ð", SHIB: "⟁", XLM: "✦" };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center gap-2">
        <Bitcoin size={20} className="text-accent" />
        <h1 className="text-xl font-bold">Crypto Trading Bot</h1>
      </div>

      {/* Bot Control */}
      <div className={cn("flex items-center justify-between p-4 rounded-xl border", botRunning ? "bg-bullish/5 border-bullish/20" : "bg-card border-border")}>
        <div className="flex items-center gap-3">
          <Activity size={18} className={botRunning ? "text-bullish animate-pulse" : "text-gray-500"} />
          <div>
            <span className={cn("text-sm font-medium", botRunning ? "text-bullish" : "text-gray-400")}>
              {botRunning ? "Bot Active — Scanning 8 coins every 2 min" : "Bot Inactive"}
            </span>
            <span className="text-xs text-gray-600 block">24/7 autonomous trading • No PDT restrictions</span>
          </div>
        </div>
        {botRunning ? (
          <button onClick={() => stopMut.mutate()} className="px-4 py-2 bg-bearish/10 text-bearish border border-bearish/30 rounded-lg text-xs font-medium hover:bg-bearish/20 flex items-center gap-1.5">
            <Square size={12} /> Stop Bot
          </button>
        ) : (
          <button onClick={() => startMut.mutate()} className="px-4 py-2 bg-bullish/10 text-bullish border border-bullish/30 rounded-lg text-xs font-medium hover:bg-bullish/20 flex items-center gap-1.5">
            <Play size={12} /> Start Bot
          </button>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Today's P&L" value={`${todayPnl >= 0 ? "+" : ""}${formatCurrency(todayPnl)}`} variant={todayPnl >= 0 ? "bullish" : "bearish"} />
        <StatCard label="Trades Today" value={String(todayTrades.length)} />
        <StatCard label="Win Rate" value={formatPercent(winRate)} variant={winRate >= 50 ? "bullish" : "warning"} />
        <StatCard label="Open Positions" value={String(Math.max(0, openPositions))} />
      </div>

      {/* Live Prices Grid */}
      {prices && (
        <Card>
          <CardTitle>Live Crypto Prices</CardTitle>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
            {Object.entries(prices).map(([coin, data]) => (
              <div key={coin} className="p-3 bg-background/50 border border-border rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{coinIcons[coin] ?? "●"}</span>
                    <span className="font-mono font-medium text-sm">{coin}</span>
                  </div>
                </div>
                <div className="font-mono text-lg font-semibold">
                  {data.price > 0 ? formatCurrency(data.price, data.price > 100 ? 2 : 4) : "—"}
                </div>
                {data.bid != null && data.ask != null && data.bid > 0 && (
                  <div className="text-[10px] text-gray-600 mt-1 font-mono">
                    Spread: {((data.ask! - data.bid!) / ((data.ask! + data.bid!) / 2) * 100).toFixed(3)}%
                  </div>
                )}
                {data.high != null && data.high > 0 && (
                  <div className="text-[10px] text-gray-600 font-mono">
                    H: {formatCurrency(data.high, 2)} L: {formatCurrency(data.low, 2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recent Trades */}
      {trades.length > 0 && (
        <Card>
          <CardTitle>Trade History</CardTitle>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 text-xs border-b border-border">
                <th className="pb-2 text-left font-medium">Time</th>
                <th className="pb-2 text-left font-medium">Side</th>
                <th className="pb-2 text-left font-medium">Coin</th>
                <th className="pb-2 text-right font-medium">Amount</th>
                <th className="pb-2 text-right font-medium">Price</th>
                <th className="pb-2 text-right font-medium">Score</th>
                <th className="pb-2 text-right font-medium">Regime</th>
                <th className="pb-2 text-right font-medium">P&L</th>
                <th className="pb-2 text-right font-medium">Status</th>
              </tr></thead>
              <tbody>
                {trades.slice(0, 30).map((t) => (
                  <tr key={t.id} className="border-b border-border/50">
                    <td className="py-2 text-gray-400 text-xs">{formatDate(t.timestamp)} {formatTime(t.timestamp)}</td>
                    <td className="py-2"><Badge variant={t.side}>{t.side}</Badge></td>
                    <td className="py-2 font-mono font-medium">{t.symbol}</td>
                    <td className="py-2 text-right font-mono">{formatCurrency(t.dollars)}</td>
                    <td className="py-2 text-right font-mono">{formatCurrency(t.price, t.price > 100 ? 2 : 4)}</td>
                    <td className="py-2 text-right font-mono text-gray-400">{(t.score ?? 0).toFixed(3)}</td>
                    <td className="py-2 text-right"><Badge variant="neutral">{t.regime || "—"}</Badge></td>
                    <td className={cn("py-2 text-right font-mono", (t.pnl ?? 0) >= 0 ? "text-bullish" : "text-bearish")}>
                      {t.pnl != null && t.pnl !== 0 ? `${t.pnl >= 0 ? "+" : ""}${formatCurrency(t.pnl)}` : "—"}
                    </td>
                    <td className="py-2 text-right"><Badge variant={t.status?.includes("fill") || t.status?.includes("dry") ? "filled" : "pending"}>{t.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Disclaimer */}
      <div className="text-center text-[10px] text-gray-700 py-4">
        Meridian Crypto Bot — Cryptocurrency trading involves significant risk. Not financial advice. Past performance does not guarantee future results.
      </div>
    </motion.div>
  );
}
