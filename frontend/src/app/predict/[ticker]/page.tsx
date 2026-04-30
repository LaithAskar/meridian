"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Brain, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import { useStore } from "@/lib/store";
import { getPrediction } from "@/lib/api";
import { formatCurrency, formatPercent, cn } from "@/lib/utils";
import { Card, CardTitle, Badge, Gauge, StatCard, Skeleton } from "@/components/ui";
import { PredictionChart } from "@/components/charts";

export default function PredictPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const { setCurrentTicker, addRecentSearch } = useStore();
  const [days, setDays] = useState(30);

  useEffect(() => {
    if (ticker) { setCurrentTicker(ticker); addRecentSearch(ticker); }
  }, [ticker, setCurrentTicker, addRecentSearch]);

  const { data, isLoading } = useQuery({ queryKey: ["predict", ticker, days], queryFn: () => getPrediction(ticker, days), enabled: !!ticker });

  if (!ticker) return <div className="text-center text-gray-500 py-20">Select a ticker first</div>;

  const ens = data?.ensemble;
  const isUp = (ens?.changePercent ?? 0) > 0;
  const dirColor = isUp ? "text-bullish" : "text-bearish";

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Brain size={20} className="text-accent" />
            <h1 className="text-xl font-bold">ML Predictions — <span className="font-mono">{ticker.toUpperCase()}</span></h1>
          </div>
          <p className="text-sm text-gray-500">Ensemble model: Prophet + XGBoost + LSTM</p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 14, 30, 60, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} className={cn("px-3 py-1.5 text-xs rounded-lg border transition-colors", d === days ? "border-accent bg-accent/10 text-accent" : "border-border text-gray-500 hover:border-gray-600")}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      {isLoading ? <Skeleton className="h-96" /> : data?.error ? (
        <Card><p className="text-gray-500">{data.error}</p></Card>
      ) : (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Current Price" value={formatCurrency(data?.currentPrice)} />
            <StatCard label="Predicted Price" value={formatCurrency(ens?.predictedPrice)} variant={isUp ? "bullish" : "bearish"} />
            <StatCard label="Change" value={`${isUp ? "+" : ""}${formatPercent(ens?.changePercent)}`} variant={isUp ? "bullish" : "bearish"} />
            <StatCard label="Confidence" value={formatPercent(ens?.confidence)} variant={(ens?.confidence ?? 0) > 60 ? "bullish" : "warning"} />
          </div>

          {/* Chart */}
          <Card>
            <CardTitle>Price Forecast ({days} days)</CardTitle>
            <PredictionChart predictions={data?.predictions ?? []} currentPrice={data?.currentPrice ?? 0} />
          </Card>

          {/* Models */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.entries(data?.models ?? {}).map(([name, model]) => (
              <Card key={name} className={cn(model.available === false && "opacity-50")}>
                <CardTitle>{name.charAt(0).toUpperCase() + name.slice(1)}</CardTitle>
                <div className="mt-3 space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Predicted</span>
                    <span className="font-mono">{model.price > 0 ? formatCurrency(model.price) : "N/A"}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Change</span>
                    <span className={cn("font-mono", model.changePercent > 0 ? "text-bullish" : model.changePercent < 0 ? "text-bearish" : "text-gray-400")}>
                      {model.changePercent > 0 ? "+" : ""}{formatPercent(model.changePercent)}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Weight</span>
                    <span className="font-mono">{model.weight}%</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Direction</span>
                    <Badge variant={model.direction === "up" ? "bullish" : model.direction === "down" ? "bearish" : "neutral"}>
                      {model.direction}
                    </Badge>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Risk Metrics */}
          {data?.riskMetrics && (
            <Card>
              <CardTitle><span className="flex items-center gap-2"><AlertTriangle size={14} /> Risk Metrics</span></CardTitle>
              <div className="grid grid-cols-3 gap-4 mt-3 text-sm">
                <div><span className="text-gray-500 block text-xs mb-1">Max Drawdown</span><span className="font-mono text-bearish">{formatPercent(data.riskMetrics.maxDrawdown)}</span></div>
                <div><span className="text-gray-500 block text-xs mb-1">Upside</span><span className="font-mono text-bullish">+{formatPercent(data.riskMetrics.upside)}</span></div>
                <div><span className="text-gray-500 block text-xs mb-1">Downside</span><span className="font-mono text-bearish">{formatPercent(data.riskMetrics.downside)}</span></div>
              </div>
            </Card>
          )}

          {/* Feature Importance */}
          {data?.featureImportance && data.featureImportance.length > 0 && (
            <Card>
              <CardTitle>Feature Importance (XGBoost)</CardTitle>
              <div className="space-y-2 mt-3">
                {data.featureImportance.slice(0, 8).map((f, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 w-28 truncate">{f.feature}</span>
                    <div className="flex-1 bg-border rounded-full h-2">
                      <div className="bg-accent h-2 rounded-full transition-all" style={{ width: `${Math.min(100, f.importance * 500)}%` }} />
                    </div>
                    <span className="text-xs font-mono text-gray-500 w-12 text-right">{(f.importance * 100).toFixed(1)}%</span>
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
