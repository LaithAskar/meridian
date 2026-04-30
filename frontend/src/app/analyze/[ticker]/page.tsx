"use client";
import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, BarChart3, Newspaper, DollarSign } from "lucide-react";
import { useStore } from "@/lib/store";
import { getAnalysis, getHistory, getNews, getEarnings, getAnalysts } from "@/lib/api";
import { formatCurrency, formatPercent, formatNumber, formatDate, sentimentColor, cn } from "@/lib/utils";
import { Card, CardTitle, Badge, Gauge, StatCard, Skeleton } from "@/components/ui";
import { PriceChart, VolumeChart } from "@/components/charts";

export default function AnalyzePage() {
  const { ticker } = useParams<{ ticker: string }>();
  const { setCurrentTicker, addRecentSearch } = useStore();

  useEffect(() => {
    if (ticker) { setCurrentTicker(ticker); addRecentSearch(ticker); }
  }, [ticker, setCurrentTicker, addRecentSearch]);

  const { data: analysis, isLoading: loadingAnalysis } = useQuery({ queryKey: ["analysis", ticker], queryFn: () => getAnalysis(ticker), enabled: !!ticker });
  const { data: history, isLoading: loadingHistory } = useQuery({ queryKey: ["history", ticker], queryFn: () => getHistory(ticker), enabled: !!ticker });
  const { data: news } = useQuery({ queryKey: ["news", ticker], queryFn: () => getNews(ticker), enabled: !!ticker });
  const { data: earnings } = useQuery({ queryKey: ["earnings", ticker], queryFn: () => getEarnings(ticker), enabled: !!ticker });
  const { data: analysts } = useQuery({ queryKey: ["analysts", ticker], queryFn: () => getAnalysts(ticker), enabled: !!ticker });

  if (!ticker) return <div className="text-center text-gray-500 py-20">Select a ticker to analyze</div>;

  const q = analysis?.quote;
  const tech = analysis?.technical;
  const fund = analysis?.fundamental;
  const isUp = (q?.change ?? 0) >= 0;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background/80 -mx-4 sm:-mx-6 lg:-mx-8 px-4 sm:px-6 lg:px-8 py-4 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold font-mono">{ticker.toUpperCase()}</h1>
              <Badge variant={q?.sector === "Technology" ? "accent" : "neutral"}>{q?.sector ?? "—"}</Badge>
            </div>
            <p className="text-sm text-gray-500">{q?.name ?? ""} · {q?.exchange ?? ""}</p>
          </div>
          <div className="text-right">
            {loadingAnalysis ? <Skeleton className="h-8 w-32" /> : (
              <>
                <div className="text-2xl font-bold font-mono">{formatCurrency(q?.price)}</div>
                <div className={cn("text-sm font-mono", isUp ? "text-bullish" : "text-bearish")}>
                  {isUp ? "+" : ""}{formatCurrency(q?.change)} ({isUp ? "+" : ""}{formatPercent(q?.changePercent)})
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Market Cap" value={formatCurrency(q?.marketCap)} />
        <StatCard label="P/E Ratio" value={(q?.pe ?? 0).toFixed(1)} />
        <StatCard label="Volume" value={formatNumber(q?.volume)} sub={`Avg: ${formatNumber(q?.avgVolume)}`} />
        <StatCard label="52W Range" value={`${formatCurrency(q?.week52Low, 0)} - ${formatCurrency(q?.week52High, 0)}`} />
      </div>

      {/* Chart */}
      <Card>
        <CardTitle>Price History</CardTitle>
        {loadingHistory ? <Skeleton className="h-[300px]" /> : <PriceChart data={history ?? []} />}
        {history && <VolumeChart data={history} />}
      </Card>

      {/* Scores */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Technical Score</CardTitle>
          <div className="flex items-center gap-6 mt-3">
            <Gauge value={tech?.score ?? 50} label="Overall" />
            <div className="flex-1 space-y-2 text-sm">
              {tech?.breakdown && Object.entries(tech.breakdown).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-gray-400 capitalize">{key.replace(/([A-Z])/g, " $1")}</span>
                  <Badge variant={typeof val === "object" && val !== null && "signal" in val ? (val as any).signal === "buy" || (val as any).signal === "bullish" ? "bullish" : (val as any).signal === "sell" || (val as any).signal === "bearish" ? "bearish" : "neutral" : "neutral"}>
                    {typeof val === "object" && val !== null && "signal" in val ? (val as any).signal : "—"}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card>
          <CardTitle>Fundamental Score</CardTitle>
          <div className="flex items-center gap-6 mt-3">
            <Gauge value={fund?.score ?? 0} label={fund?.grade ?? "N/A"} />
            <div className="flex-1 space-y-2 text-sm">
              {fund?.breakdown && Object.entries(fund.breakdown).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-gray-400 capitalize">{key}</span>
                  <span className="font-mono text-xs">{typeof val === "object" && val !== null ? (val as any).score ?? 0 : 0}{typeof val === "object" && val !== null && (val as any).maxScore ? `/${(val as any).maxScore}` : ""}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Analysts */}
      {analysts && analysts.numberOfAnalysts > 0 && (
        <Card>
          <CardTitle>Analyst Consensus</CardTitle>
          <div className="mt-3 flex items-center gap-6">
            <Badge variant={analysts.recommendation?.includes("buy") ? "bullish" : analysts.recommendation?.includes("sell") ? "bearish" : "neutral"} className="text-sm px-3 py-1">
              {analysts.recommendation?.toUpperCase() ?? "N/A"}
            </Badge>
            <div className="text-sm space-y-1">
              <div className="text-gray-400">Target: <span className="text-white font-mono">{formatCurrency(analysts.targetMean)}</span> ({formatCurrency(analysts.targetLow)} - {formatCurrency(analysts.targetHigh)})</div>
              <div className="text-gray-500">{analysts.numberOfAnalysts} analysts</div>
            </div>
          </div>
        </Card>
      )}

      {/* News */}
      {news && news.articles.length > 0 && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <CardTitle><span className="flex items-center gap-2"><Newspaper size={14} /> News Sentiment</span></CardTitle>
            <Badge variant={news.aggregateSentiment?.label === "positive" ? "bullish" : news.aggregateSentiment?.label === "negative" ? "bearish" : "neutral"}>
              {news.aggregateSentiment?.label ?? "neutral"} ({(news.aggregateSentiment?.score ?? 0).toFixed(2)})
            </Badge>
          </div>
          <div className="space-y-2">
            {news.articles.slice(0, 8).map((a, i) => (
              <a key={i} href={a.url || "#"} target="_blank" rel="noopener noreferrer" className="flex items-start gap-3 p-2.5 rounded-lg hover:bg-white/5 transition-colors group">
                <Badge variant={a.sentiment === "Bullish" ? "bullish" : a.sentiment === "Bearish" ? "bearish" : "neutral"} className="mt-0.5 shrink-0">
                  {a.score > 0 ? "+" : ""}{(a.score ?? 0).toFixed(2)}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-300 group-hover:text-white transition-colors line-clamp-1">{a.title}</div>
                  <div className="text-xs text-gray-600 mt-0.5">{a.source} · {formatDate(a.date)}</div>
                </div>
              </a>
            ))}
          </div>
        </Card>
      )}

      {/* Earnings */}
      {earnings && earnings.length > 0 && (
        <Card>
          <CardTitle><span className="flex items-center gap-2"><DollarSign size={14} /> Earnings History</span></CardTitle>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 text-xs border-b border-border">
                <th className="pb-2 text-left font-medium">Date</th>
                <th className="pb-2 text-right font-medium">Estimate</th>
                <th className="pb-2 text-right font-medium">Actual</th>
                <th className="pb-2 text-right font-medium">Surprise</th>
              </tr></thead>
              <tbody>
                {earnings.slice(0, 12).map((e, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="py-2 text-gray-400">{formatDate(e.date)}</td>
                    <td className="py-2 text-right font-mono">{(e.epsEstimate ?? 0).toFixed(2)}</td>
                    <td className="py-2 text-right font-mono">{(e.epsActual ?? 0).toFixed(2)}</td>
                    <td className={cn("py-2 text-right font-mono", (e.surprise ?? 0) >= 0 ? "text-bullish" : "text-bearish")}>{(e.surprise ?? 0) > 0 ? "+" : ""}{(e.surprise ?? 0).toFixed(1)}%</td>
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
