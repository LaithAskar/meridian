from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SourceConfig:
    enabled: bool = True
    subreddits: list[str] = field(default_factory=lambda: ["wallstreetbets", "stocks"])
    min_score: int = 3
    trending_only: bool = False


@dataclass
class SentimentConfig:
    vader_threshold: float = 0.35
    finbert_threshold: float = 0.6
    finbert_device: str = "cpu"


@dataclass
class TradingConfig:
    paper_mode: bool = False
    max_position_pct: float = 0.08
    max_daily_trades: int = 50
    max_daily_loss_pct: float = 0.03
    order_type: str = "market"
    cooldown_seconds: int = 60
    default_trade_dollars: float = 25.0
    liquidity_reserve_pct: float = 0.20
    min_trade_dollars: float = 5.0
    max_trade_dollars: float = 200.0


@dataclass
class TrendingConfig:
    window_seconds: int = 300
    min_mentions: int = 8
    auto_trade_trending: bool = True


@dataclass
class QuantConfig:
    enabled: bool = True
    cycle_minutes: int = 5
    universe_size: int = 30
    min_consensus: float = 0.55
    momentum_weight: float = 0.35
    reversion_weight: float = 0.30
    factor_weight: float = 0.35


@dataclass
class BotConfig:
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    trending: TrendingConfig = field(default_factory=TrendingConfig)
    quant: QuantConfig = field(default_factory=QuantConfig)

    @classmethod
    def from_yaml(cls, path: str) -> BotConfig:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {}
        except Exception as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            data = {}

        sources = {}
        for name, src_data in data.get("sources", {}).items():
            if isinstance(src_data, dict):
                sources[name] = SourceConfig(**{k: v for k, v in src_data.items() if k in SourceConfig.__dataclass_fields__})
            else:
                sources[name] = SourceConfig(enabled=bool(src_data))

        sentiment = SentimentConfig(**{k: v for k, v in data.get("sentiment", {}).items() if k in SentimentConfig.__dataclass_fields__})
        trading_data = data.get("trading", {})
        trading = TradingConfig(**{k: v for k, v in trading_data.items() if k in TradingConfig.__dataclass_fields__})
        trending = TrendingConfig(**{k: v for k, v in data.get("trending", {}).items() if k in TrendingConfig.__dataclass_fields__})
        quant = QuantConfig(**{k: v for k, v in data.get("quant", {}).items() if k in QuantConfig.__dataclass_fields__})

        paper = os.getenv("TRADING_PAPER_MODE", "").lower()
        if paper in ("true", "1", "yes"):
            trading.paper_mode = True

        return cls(sources=sources, sentiment=sentiment, trading=trading, trending=trending, quant=quant)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)
