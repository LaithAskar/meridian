import type {
  Quote, HistoryPoint, AnalysisResult, NewsSentiment, EarningsRecord,
  AnalystInfo, PredictionResult, PortfolioResult, TradingStatus,
  RobinhoodAccount, RobinhoodPosition, RobinhoodOrder, CryptoPrice,
  CryptoStatus, SearchResult, TechnicalAnalysis, FundamentalAnalysis,
  ModelPrediction,
} from "@/types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJson<T>(url: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...opts?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

// ── Stock Data ─────────────────────────────────────────────
export async function searchTickers(q: string): Promise<SearchResult[]> {
  if (!q.trim()) return [];
  return fetchJson(`/api/search?q=${encodeURIComponent(q)}`);
}

export async function getQuote(ticker: string): Promise<Quote> {
  return fetchJson(`/api/quote/${ticker}`);
}

export async function getHistory(ticker: string, period = "1y"): Promise<HistoryPoint[]> {
  return fetchJson(`/api/history/${ticker}?period=${period}`);
}

export async function getAnalysis(ticker: string): Promise<AnalysisResult> {
  const raw: any = await fetchJson(`/api/analysis/${ticker}`);
  return {
    ticker: raw.ticker ?? ticker.toUpperCase(),
    quote: raw.quote ?? { ticker: ticker.toUpperCase(), name: ticker, price: 0 } as Quote,
    fundamental: normalizeFundamental(raw.fundamental),
    technical: normalizeTechnical(raw.technical),
  };
}

export async function getNews(ticker: string): Promise<NewsSentiment> {
  const raw: any = await fetchJson(`/api/news/${ticker}`);
  const articles = (raw.articles ?? []).map((a: any) => ({
    title: a.title ?? "",
    summary: a.summary ?? "",
    source: a.source ?? a.publisher ?? "",
    date: a.date ?? "",
    url: a.url ?? "",
    sentiment: a.sentiment ?? "Neutral",
    score: a.score ?? a.compound ?? 0,
  }));
  const agg = raw.aggregate ?? "Neutral";
  const aggSent = raw.aggregateSentiment ?? {
    score: raw.stats?.averageCompound ?? 0,
    label: agg === "Bullish" ? "positive" : agg === "Bearish" ? "negative" : "neutral",
  };
  return { ticker: raw.ticker ?? ticker, articles, aggregate: agg, aggregateSentiment: aggSent, stats: raw.stats ?? { total: 0, bullish: 0, bearish: 0, neutral: 0, averageCompound: 0 } };
}

export async function getEarnings(ticker: string): Promise<EarningsRecord[]> {
  return fetchJson(`/api/earnings/${ticker}`);
}

export async function getFinancials(ticker: string): Promise<any> {
  return fetchJson(`/api/financials/${ticker}`);
}

export async function getAnalysts(ticker: string): Promise<AnalystInfo> {
  return fetchJson(`/api/analysts/${ticker}`);
}

export async function getPrediction(ticker: string, days = 30): Promise<PredictionResult> {
  const raw: any = await fetchJson(`/api/predict/${ticker}?days=${days}`);
  const models: Record<string, ModelPrediction> = {};
  for (const name of ["prophet", "xgboost", "lstm"]) {
    const m = raw.models?.[name];
    if (m) {
      models[name] = {
        price: m.price ?? m.predictedPrice ?? 0,
        weight: m.weight ?? 0,
        confidence: m.confidence ?? 0,
        direction: m.direction ?? "unavailable",
        changePercent: m.changePercent ?? 0,
        available: m.available !== false,
      };
    } else {
      models[name] = { price: 0, weight: 0, confidence: 0, direction: "unavailable", changePercent: 0, available: false };
    }
  }
  return {
    ticker: raw.ticker ?? ticker,
    days: raw.days ?? days,
    currentPrice: raw.currentPrice ?? 0,
    ensemble: raw.ensemble ?? null,
    models,
    predictions: raw.predictions ?? [],
    featureImportance: raw.featureImportance ?? [],
    riskMetrics: raw.riskMetrics ?? { maxDrawdown: 0, upside: 0, downside: 0 },
    error: raw.error,
  };
}

export async function optimizePortfolio(tickers: string[], investmentAmount: number, riskTolerance: string): Promise<PortfolioResult> {
  const raw: any = await fetchJson("/api/portfolio", {
    method: "POST",
    body: JSON.stringify({ tickers, investment_amount: investmentAmount, risk_tolerance: riskTolerance }),
  });
  if (raw.error) return { summary: { expectedReturn: 0, volatility: 0, sharpeRatio: 0, investmentAmount, riskTolerance, numAssets: 0 }, positions: [], correlation: {}, riskWarnings: [], error: raw.error };
  return {
    summary: raw.summary ?? { expectedReturn: 0, volatility: 0, sharpeRatio: 0, investmentAmount, riskTolerance, numAssets: 0 },
    positions: raw.positions ?? raw.holdings ?? [],
    correlation: raw.correlation ?? {},
    riskWarnings: raw.riskWarnings ?? [],
  };
}

export async function getTrending(): Promise<{ trending: Array<{ ticker: string; mentions: number }> }> {
  return fetchJson("/api/trending");
}

// ── Trading Bot ────────────────────────────────────────────
export async function startTrading(): Promise<any> { return fetchJson("/api/trading/start", { method: "POST" }); }
export async function stopTrading(): Promise<any> { return fetchJson("/api/trading/stop", { method: "POST" }); }
export async function getTradingStatus(): Promise<TradingStatus> {
  const raw: any = await fetchJson("/api/trading/status");
  return { running: raw.running ?? false, uptime: raw.uptime ?? 0, marketOpen: raw.marketOpen ?? false, stats: raw.stats ?? { totalTrades: 0, buys: 0, sells: 0, circuitBreaker: { tripped: false, reason: "", tradesToday: 0, dailyPnl: 0 }, pdtRemaining: 3, paperMode: true, loggedIn: false }, recentTrades: raw.recentTrades ?? [], trending: raw.trending ?? [], adaptiveSentiment: raw.adaptiveSentiment ?? {}, adaptiveQuant: raw.adaptiveQuant ?? {}, paperMode: raw.paperMode ?? true };
}
export async function getTradingSignals(): Promise<any> { return fetchJson("/api/trading/signals"); }

// ── Robinhood ──────────────────────────────────────────────
export async function getRhStatus(): Promise<{ connected: boolean }> { return fetchJson("/api/robinhood/status"); }
export async function rhLogin(username: string, password: string): Promise<any> { return fetchJson("/api/robinhood/login", { method: "POST", body: JSON.stringify({ username, password }) }); }
export async function getRhAccount(): Promise<RobinhoodAccount> { return fetchJson("/api/robinhood/account"); }
export async function getRhPositions(): Promise<RobinhoodPosition[]> { const r = await fetchJson<any>("/api/robinhood/positions"); return Array.isArray(r) ? r : []; }
export async function getRhHistory(): Promise<RobinhoodOrder[]> { const r = await fetchJson<any>("/api/robinhood/history"); return Array.isArray(r) ? r : []; }
export async function placeRhOrder(ticker: string, side: string, dollars: number): Promise<any> { return fetchJson("/api/robinhood/order", { method: "POST", body: JSON.stringify({ ticker, side, dollars }) }); }

// ── Crypto ─────────────────────────────────────────────────
export async function getCryptoStatus(): Promise<CryptoStatus> { const r: any = await fetchJson("/api/crypto/status"); return { running: r.running ?? false, trades: r.trades ?? [] }; }
export async function startCrypto(): Promise<any> { return fetchJson("/api/crypto/start", { method: "POST" }); }
export async function stopCrypto(): Promise<any> { return fetchJson("/api/crypto/stop", { method: "POST" }); }
export async function getCryptoPrices(): Promise<Record<string, CryptoPrice>> { return fetchJson("/api/crypto/prices"); }

// ── Normalization helpers ──────────────────────────────────
function normalizeTechnical(raw: any): TechnicalAnalysis {
  if (!raw) return { score: 50, breakdown: { movingAverages: { signal: "neutral", count: 0 }, momentum: { signal: "neutral" }, volatility: {}, trend: { signal: "neutral" } }, indicators: {} };
  const score = raw.score != null ? ((raw.score + 100) / 2) : 50;
  return {
    score: Math.round(Math.max(0, Math.min(100, score))),
    breakdown: raw.breakdown ?? { movingAverages: { signal: "neutral", count: 0 }, momentum: { signal: "neutral" }, volatility: {}, trend: { signal: "neutral" } },
    indicators: raw.indicators ?? {},
  };
}

function normalizeFundamental(raw: any): FundamentalAnalysis {
  if (!raw) return { score: 0, grade: "N/A", breakdown: { valuation: { score: 0, factors: [] }, profitability: { score: 0, factors: [] }, growth: { score: 0, factors: [] }, health: { score: 0, factors: [] } }, keyStats: {} };
  const bd = raw.breakdown ?? {};
  const normalizeSection = (section: any) => {
    if (!section) return { score: 0, factors: [] };
    if (typeof section === "number") return { score: section, factors: [] };
    return { score: section.score ?? 0, maxScore: section.maxScore, factors: section.factors ?? [] };
  };
  return {
    score: raw.score ?? 0,
    grade: raw.grade ?? "N/A",
    breakdown: {
      valuation: normalizeSection(bd.valuation),
      profitability: normalizeSection(bd.profitability),
      growth: normalizeSection(bd.growth),
      health: normalizeSection(bd.financialHealth ?? bd.health),
    },
    keyStats: raw.keyStats ?? {},
  };
}
