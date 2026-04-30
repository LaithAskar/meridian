"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Landmark, Play, Square, Wifi, WifiOff, Bot, ShieldAlert, TrendingUp, TrendingDown } from "lucide-react";
import { getRhStatus, rhLogin, getRhAccount, getRhPositions, getRhHistory, getTradingStatus, startTrading, stopTrading, placeRhOrder } from "@/lib/api";
import { formatCurrency, formatPercent, formatDate, formatTime, formatDuration, cn } from "@/lib/utils";
import { Card, CardTitle, Badge, StatCard, Skeleton } from "@/components/ui";

export default function RobinhoodPage() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tradeForm, setTradeForm] = useState<{ ticker: string; side: string; dollars: number } | null>(null);

  const { data: status } = useQuery({ queryKey: ["rh-status"], queryFn: getRhStatus, refetchInterval: 15000 });
  const { data: account } = useQuery({ queryKey: ["rh-account"], queryFn: getRhAccount, enabled: status?.connected, refetchInterval: 30000 });
  const { data: positions } = useQuery({ queryKey: ["rh-positions"], queryFn: getRhPositions, enabled: status?.connected, refetchInterval: 30000 });
  const { data: orders } = useQuery({ queryKey: ["rh-history"], queryFn: getRhHistory, enabled: status?.connected });
  const { data: botStatus } = useQuery({ queryKey: ["trading-status"], queryFn: getTradingStatus, refetchInterval: 10000 });

  const loginMut = useMutation({ mutationFn: () => rhLogin(username, password), onSuccess: () => qc.invalidateQueries({ queryKey: ["rh-status"] }) });
  const startMut = useMutation({ mutationFn: startTrading, onSuccess: () => qc.invalidateQueries({ queryKey: ["trading-status"] }) });
  const stopMut = useMutation({ mutationFn: stopTrading, onSuccess: () => qc.invalidateQueries({ queryKey: ["trading-status"] }) });
  const orderMut = useMutation({ mutationFn: (f: { ticker: string; side: string; dollars: number }) => placeRhOrder(f.ticker, f.side, f.dollars), onSuccess: () => { qc.invalidateQueries({ queryKey: ["rh-positions"] }); setTradeForm(null); } });

  const connected = status?.connected ?? false;
  const botRunning = botStatus?.running ?? false;
  const stats = botStatus?.stats;
  const todayPnl = account?.todayPnl ?? 0;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center gap-2">
        <Landmark size={20} className="text-accent" />
        <h1 className="text-xl font-bold">Robinhood Dashboard</h1>
      </div>

      {/* Connection Banner */}
      <div className={cn("flex items-center justify-between p-4 rounded-xl border", connected ? "bg-bullish/5 border-bullish/20" : "bg-card border-border")}>
        <div className="flex items-center gap-3">
          {connected ? <Wifi size={18} className="text-bullish" /> : <WifiOff size={18} className="text-gray-500" />}
          <div>
            <span className={cn("text-sm font-medium", connected ? "text-bullish" : "text-gray-400")}>{connected ? "Connected to Robinhood" : "Not Connected"}</span>
            {connected && <span className="text-xs text-gray-500 ml-2">Push MFA active</span>}
          </div>
        </div>
        {!connected && (
          <div className="flex items-center gap-2">
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username" className="bg-background border border-border rounded-lg px-3 py-1.5 text-xs w-32 focus:outline-none focus:border-accent/50" />
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder="Password" className="bg-background border border-border rounded-lg px-3 py-1.5 text-xs w-32 focus:outline-none focus:border-accent/50" />
            <button onClick={() => loginMut.mutate()} disabled={loginMut.isPending} className="px-4 py-1.5 bg-accent text-white text-xs rounded-lg font-medium hover:bg-accent/90 disabled:opacity-50">
              {loginMut.isPending ? "..." : "Connect"}
            </button>
          </div>
        )}
      </div>

      {/* Account Summary */}
      {connected && account && !account.error && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Total Equity" value={formatCurrency(account.equity)} icon={<Landmark size={14} />} />
          <StatCard label="Buying Power" value={formatCurrency(account.buyingPower)} />
          <StatCard label="Today's P&L" value={`${todayPnl >= 0 ? "+" : ""}${formatCurrency(todayPnl)}`} variant={todayPnl >= 0 ? "bullish" : "bearish"} />
          <StatCard label="Cash" value={formatCurrency(account.cash)} />
        </div>
      )}

      {/* Trading Bot Panel */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle><span className="flex items-center gap-2"><Bot size={14} /> Sentiment Auto-Trader</span></CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={botRunning ? "bullish" : "neutral"}>{botRunning ? "Active" : "Inactive"}</Badge>
            {botRunning ? (
              <button onClick={() => stopMut.mutate()} className="px-3 py-1.5 bg-bearish/10 text-bearish border border-bearish/30 rounded-lg text-xs hover:bg-bearish/20 flex items-center gap-1.5">
                <Square size={12} /> Stop
              </button>
            ) : (
              <button onClick={() => startMut.mutate()} className="px-3 py-1.5 bg-bullish/10 text-bullish border border-bullish/30 rounded-lg text-xs hover:bg-bullish/20 flex items-center gap-1.5">
                <Play size={12} /> Start
              </button>
            )}
          </div>
        </div>

        {botStatus && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
            <div className="text-center p-2 bg-background/50 rounded-lg">
              <div className="text-xs text-gray-500">Trades</div>
              <div className="font-mono text-sm">{stats?.totalTrades ?? 0}</div>
            </div>
            <div className="text-center p-2 bg-background/50 rounded-lg">
              <div className="text-xs text-gray-500">Buys / Sells</div>
              <div className="font-mono text-sm">{stats?.buys ?? 0} / {stats?.sells ?? 0}</div>
            </div>
            <div className="text-center p-2 bg-background/50 rounded-lg">
              <div className="text-xs text-gray-500">PDT Left</div>
              <div className="font-mono text-sm">{stats?.pdtRemaining ?? 3}</div>
            </div>
            <div className="text-center p-2 bg-background/50 rounded-lg">
              <div className="text-xs text-gray-500">Uptime</div>
              <div className="font-mono text-sm">{formatDuration(botStatus.uptime)}</div>
            </div>
            <div className="text-center p-2 bg-background/50 rounded-lg">
              <div className="text-xs text-gray-500">Mode</div>
              <div className="font-mono text-sm">{botStatus.paperMode ? "Paper" : "Live"}</div>
            </div>
          </div>
        )}

        {stats?.circuitBreaker?.tripped && (
          <div className="flex items-center gap-2 p-3 bg-bearish/10 border border-bearish/30 rounded-lg mb-4">
            <ShieldAlert size={16} className="text-bearish" />
            <span className="text-sm text-bearish">Circuit breaker tripped: {stats.circuitBreaker.reason}</span>
          </div>
        )}

        {/* Recent Bot Trades */}
        {botStatus?.recentTrades && botStatus.recentTrades.length > 0 && (
          <div>
            <h4 className="text-xs text-gray-500 uppercase tracking-wider mb-2">Recent Bot Trades</h4>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {botStatus.recentTrades.slice(0, 10).map((t, i) => (
                <div key={i} className="flex items-center justify-between p-2 bg-background/50 rounded-lg text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant={t.side}>{t.side}</Badge>
                    <span className="font-mono font-medium">{t.ticker}</span>
                  </div>
                  <div className="flex items-center gap-3 text-gray-400">
                    <span className="font-mono">{formatCurrency(t.dollars)}</span>
                    <Badge variant={t.status?.includes("fill") ? "filled" : t.status === "submitted" ? "pending" : "neutral"}>{t.status}</Badge>
                    <span>{formatTime(t.timestamp)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* Positions */}
      {connected && positions && Array.isArray(positions) && positions.length > 0 && (
        <Card>
          <CardTitle>Open Positions</CardTitle>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 text-xs border-b border-border">
                <th className="pb-2 text-left font-medium">Ticker</th>
                <th className="pb-2 text-right font-medium">Qty</th>
                <th className="pb-2 text-right font-medium">Avg Cost</th>
                <th className="pb-2 text-right font-medium">Current</th>
                <th className="pb-2 text-right font-medium">Value</th>
                <th className="pb-2 text-right font-medium">P&L</th>
                <th className="pb-2 text-right font-medium">Actions</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.ticker} className="border-b border-border/50">
                    <td className="py-2.5 font-mono font-medium">{p.ticker}</td>
                    <td className="py-2.5 text-right font-mono">{p.quantity.toFixed(4)}</td>
                    <td className="py-2.5 text-right font-mono">{formatCurrency(p.averageCost)}</td>
                    <td className="py-2.5 text-right font-mono">{formatCurrency(p.currentPrice)}</td>
                    <td className="py-2.5 text-right font-mono">{formatCurrency(p.marketValue)}</td>
                    <td className={cn("py-2.5 text-right font-mono", p.pnl >= 0 ? "text-bullish" : "text-bearish")}>
                      {p.pnl >= 0 ? "+" : ""}{formatCurrency(p.pnl)} ({p.pnl >= 0 ? "+" : ""}{formatPercent(p.pnlPercent)})
                    </td>
                    <td className="py-2.5 text-right">
                      <div className="flex items-center gap-1 justify-end">
                        <button onClick={() => setTradeForm({ ticker: p.ticker, side: "buy", dollars: 25 })} className="px-2 py-1 text-xs bg-bullish/10 text-bullish border border-bullish/30 rounded hover:bg-bullish/20">Buy</button>
                        <button onClick={() => setTradeForm({ ticker: p.ticker, side: "sell", dollars: p.marketValue })} className="px-2 py-1 text-xs bg-bearish/10 text-bearish border border-bearish/30 rounded hover:bg-bearish/20">Sell</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Quick Trade Modal */}
      {tradeForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setTradeForm(null)}>
          <div className="bg-card border border-border rounded-xl p-6 w-80 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-medium mb-4">
              <Badge variant={tradeForm.side}>{tradeForm.side}</Badge> <span className="font-mono ml-2">{tradeForm.ticker}</span>
            </h3>
            <label className="text-xs text-gray-500 block mb-1">Amount ($)</label>
            <input type="number" value={tradeForm.dollars} onChange={(e) => setTradeForm({ ...tradeForm, dollars: Number(e.target.value) })} className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm font-mono mb-4 focus:outline-none focus:border-accent/50" />
            <div className="flex gap-2">
              <button onClick={() => setTradeForm(null)} className="flex-1 py-2 border border-border rounded-lg text-sm text-gray-400 hover:bg-white/5">Cancel</button>
              <button onClick={() => orderMut.mutate(tradeForm)} disabled={orderMut.isPending} className={cn("flex-1 py-2 rounded-lg text-sm font-medium text-white", tradeForm.side === "buy" ? "bg-bullish hover:bg-bullish/90" : "bg-bearish hover:bg-bearish/90")}>
                {orderMut.isPending ? "..." : `${tradeForm.side === "buy" ? "Buy" : "Sell"} ${formatCurrency(tradeForm.dollars)}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Order History */}
      {connected && orders && Array.isArray(orders) && orders.length > 0 && (
        <Card>
          <CardTitle>Recent Orders</CardTitle>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 text-xs border-b border-border">
                <th className="pb-2 text-left font-medium">Time</th>
                <th className="pb-2 text-left font-medium">Side</th>
                <th className="pb-2 text-left font-medium">Ticker</th>
                <th className="pb-2 text-right font-medium">Qty</th>
                <th className="pb-2 text-right font-medium">Price</th>
                <th className="pb-2 text-right font-medium">Status</th>
              </tr></thead>
              <tbody>
                {orders.slice(0, 20).map((o) => (
                  <tr key={o.id} className="border-b border-border/50">
                    <td className="py-2 text-gray-400 text-xs">{formatDate(o.createdAt)}</td>
                    <td className="py-2"><Badge variant={o.side}>{o.side}</Badge></td>
                    <td className="py-2 font-mono">{o.ticker}</td>
                    <td className="py-2 text-right font-mono">{(o.quantity ?? 0).toFixed(4)}</td>
                    <td className="py-2 text-right font-mono">{formatCurrency(o.price)}</td>
                    <td className="py-2 text-right"><Badge variant={o.state === "filled" ? "filled" : o.state === "cancelled" ? "cancelled" : "pending"}>{o.state}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </motion.div>
  );
}
