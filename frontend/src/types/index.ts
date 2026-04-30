export interface Quote {
  ticker: string;
  name: string;
  price: number;
  previousClose: number;
  change: number;
  changePercent: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  avgVolume: number;
  marketCap: number;
  pe: number;
  forwardPe: number;
  eps: number;
  beta: number;
  dividend: number;
  week52High: number;
  week52Low: number;
  sector: string;
  industry: string;
  exchange: string;
  currency: string;
}

export interface HistoryPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TechnicalAnalysis {
  score: number;
  breakdown: {
    movingAverages: { signal: string; count: number; total?: number };
    momentum: { signal: string; rsi?: number; macdHistogram?: number; value?: number };
    volatility: { atr?: number; adx?: number; bbWidth?: number };
    trend: { signal: string; strength?: number };
  };
  indicators: Record<string, number>;
}

export interface FundamentalBreakdownItem {
  score: number;
  maxScore?: number;
  factors: Array<{ name: string; value: string | number; assessment: string }>;
}

export interface FundamentalAnalysis {
  score: number;
  grade: string;
  breakdown: {
    valuation: FundamentalBreakdownItem;
    profitability: FundamentalBreakdownItem;
    growth: FundamentalBreakdownItem;
    health: FundamentalBreakdownItem;
  };
  keyStats: Record<string, number>;
}

export interface AnalysisResult {
  ticker: string;
  quote: Quote;
  fundamental: FundamentalAnalysis;
  technical: TechnicalAnalysis;
}

export interface NewsArticle {
  title: string;
  summary: string;
  source: string;
  date: string;
  url: string;
  sentiment: string;
  score: number;
  compound?: number;
}

export interface NewsSentiment {
  ticker: string;
  articles: NewsArticle[];
  aggregate: string;
  aggregateSentiment: { score: number; label: string };
  stats: { total: number; bullish: number; bearish: number; neutral: number; averageCompound: number };
}

export interface EarningsRecord {
  date: string;
  epsEstimate: number;
  epsActual: number;
  surprise: number;
}

export interface AnalystInfo {
  recommendation: string;
  targetMean: number;
  targetHigh: number;
  targetLow: number;
  numberOfAnalysts: number;
  currentPrice: number;
}

export interface PredictionPoint {
  date: string;
  price: number;
  upper: number;
  lower: number;
}

export interface ModelPrediction {
  price: number;
  weight: number;
  confidence: number;
  direction: string;
  changePercent: number;
  available?: boolean;
}

export interface PredictionResult {
  ticker: string;
  days: number;
  currentPrice: number;
  ensemble: {
    predictedPrice: number;
    changePercent: number;
    confidence: number;
    direction: string;
    modelsUsed: string[];
    modelAgreement: boolean;
  } | null;
  models: Record<string, ModelPrediction>;
  predictions: PredictionPoint[];
  featureImportance: Array<{ feature: string; importance: number }>;
  riskMetrics: { maxDrawdown: number; upside: number; downside: number };
  error?: string;
}

export interface PortfolioPosition {
  ticker: string;
  weight: number;
  allocation: number;
  shares: number;
  currentPrice: number;
  expectedReturn: number;
  volatility: number;
  kellyFraction: number;
}

export interface PortfolioResult {
  summary: {
    expectedReturn: number;
    volatility: number;
    sharpeRatio: number;
    investmentAmount: number;
    riskTolerance: string;
    numAssets: number;
  };
  positions: PortfolioPosition[];
  correlation: Record<string, Record<string, number>>;
  riskWarnings: Array<{ level: string; message: string }>;
  error?: string;
}

export interface TradingStatus {
  running: boolean;
  uptime: number;
  marketOpen: boolean;
  stats: {
    totalTrades: number;
    buys: number;
    sells: number;
    circuitBreaker: { tripped: boolean; reason: string; tradesToday: number; dailyPnl: number };
    pdtRemaining: number;
    paperMode: boolean;
    loggedIn: boolean;
  };
  recentTrades: TradeRecord[];
  trending: Array<{ ticker: string; mentions: number; velocity: number }>;
  adaptiveSentiment: Record<string, any>;
  adaptiveQuant: Record<string, any>;
  paperMode: boolean;
}

export interface TradeRecord {
  ticker: string;
  side: string;
  dollars: number;
  reason: string;
  timestamp: string;
  paper: boolean;
  status: string;
  order_id?: string;
  error?: string;
}

export interface RobinhoodAccount {
  equity: number;
  extendedHoursEquity: number;
  marketValue: number;
  buyingPower: number;
  cash: number;
  todayPnl: number;
  totalPnl: number;
  error?: string;
}

export interface RobinhoodPosition {
  ticker: string;
  quantity: number;
  averageCost: number;
  currentPrice: number;
  marketValue: number;
  costBasis: number;
  pnl: number;
  pnlPercent: number;
}

export interface RobinhoodOrder {
  id: string;
  side: string;
  ticker: string;
  quantity: number;
  price: number;
  state: string;
  type: string;
  createdAt: string;
}

export interface CryptoPrice {
  price: number;
  bid?: number;
  ask?: number;
  high?: number;
  low?: number;
  volume?: number;
  note?: string;
}

export interface CryptoStatus {
  running: boolean;
  trades: Array<{
    id: number;
    timestamp: string;
    symbol: string;
    side: string;
    dollars: number;
    price: number;
    score: number;
    regime: string;
    status: string;
    pnl: number;
  }>;
}

export interface SearchResult {
  ticker: string;
  name: string;
}
