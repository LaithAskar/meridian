"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Search, TrendingUp, Clock, Zap } from "lucide-react";
import { useStore } from "@/lib/store";
import { searchTickers, getTrending } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";

export default function HomePage() {
  const router = useRouter();
  const { recentSearches, setCurrentTicker, addRecentSearch } = useStore();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ ticker: string; name: string }>>([]);

  const { data: trending } = useQuery({ queryKey: ["trending"], queryFn: getTrending, refetchInterval: 60000 });

  const handleSearch = useCallback(async (q: string) => {
    setQuery(q);
    if (q.length >= 1) {
      const r = await searchTickers(q);
      setResults(r);
    } else {
      setResults([]);
    }
  }, []);

  const goToTicker = (ticker: string) => {
    setCurrentTicker(ticker);
    addRecentSearch(ticker);
    router.push(`/analyze/${ticker.toUpperCase()}`);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) goToTicker(query.trim().toUpperCase());
  };

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center -mt-8">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-2xl text-center">
        {/* Hero */}
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent/10 text-accent text-xs font-medium mb-4">
            <Zap size={12} /> AI-Powered Quantitative Trading
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight mb-3">
            Meri<span className="text-accent">dian</span>
          </h1>
          <p className="text-gray-500 text-sm">Stock analysis, ML predictions, and autonomous trading</p>
        </div>

        {/* Search */}
        <form onSubmit={handleSubmit} className="relative mb-8">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="Search ticker or company..."
            className="w-full bg-card border border-border rounded-xl pl-11 pr-4 py-3.5 text-sm focus:outline-none focus:border-accent/50 transition-colors placeholder:text-gray-600"
            autoFocus
          />
          {results.length > 0 && (
            <div className="absolute top-full mt-1 w-full bg-card border border-border rounded-xl overflow-hidden shadow-2xl z-50">
              {results.map((r) => (
                <button key={r.ticker} onClick={() => goToTicker(r.ticker)} className="w-full text-left px-4 py-2.5 hover:bg-white/5 flex items-center justify-between text-sm transition-colors">
                  <span className="font-mono font-medium text-white">{r.ticker}</span>
                  <span className="text-gray-500 text-xs truncate ml-3">{r.name}</span>
                </button>
              ))}
            </div>
          )}
        </form>

        {/* Recent Searches */}
        {recentSearches.length > 0 && (
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-3 justify-center">
              <Clock size={13} className="text-gray-600" />
              <span className="text-xs text-gray-600 uppercase tracking-wider">Recent</span>
            </div>
            <div className="flex flex-wrap gap-2 justify-center">
              {recentSearches.map((t) => (
                <button key={t} onClick={() => goToTicker(t)} className="px-3 py-1.5 bg-card border border-border rounded-lg text-xs font-mono font-medium hover:border-accent/30 transition-colors">
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Trending */}
        {(trending?.trending?.length ?? 0) > 0 && (
          <Card className="text-left">
            <CardTitle>
              <span className="flex items-center gap-2"><TrendingUp size={14} /> Trending Stocks</span>
            </CardTitle>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
              {trending!.trending.slice(0, 8).map((t) => (
                <button key={t.ticker} onClick={() => goToTicker(t.ticker)} className="px-3 py-2 bg-background/50 border border-border rounded-lg text-left hover:border-accent/30 transition-colors">
                  <div className="font-mono text-sm font-medium">{t.ticker}</div>
                  <div className="text-[10px] text-gray-600">{t.mentions} mentions</div>
                </button>
              ))}
            </div>
          </Card>
        )}
      </motion.div>
    </div>
  );
}
