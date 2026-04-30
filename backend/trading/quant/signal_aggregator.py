from __future__ import annotations

import logging
from typing import Any
from collections import defaultdict

logger = logging.getLogger(__name__)


def aggregate_signals(
    momentum_signals: list[dict],
    reversion_signals: list[dict],
    factor_signals: list[dict],
    strategy_weights: dict[str, float],
    min_consensus: float = 0.55,
) -> list[dict[str, Any]]:
    ticker_scores: dict[str, dict] = defaultdict(lambda: {"scores": [], "strategies": [], "total_weight": 0})

    weight_map = {
        "momentum": strategy_weights.get("momentum", 0.35),
        "mean_reversion": strategy_weights.get("mean_reversion", 0.30),
        "factor_model": strategy_weights.get("factor", 0.35),
    }

    for signal_list in [momentum_signals, reversion_signals, factor_signals]:
        for sig in signal_list:
            ticker = sig["ticker"]
            strategy = sig["strategy"]
            w = weight_map.get(strategy, 0.33)
            weighted_score = sig["score"] * w
            ticker_scores[ticker]["scores"].append(weighted_score)
            ticker_scores[ticker]["strategies"].append({
                "name": strategy,
                "score": sig["score"],
                "weight": w,
                "direction": sig["direction"],
                "metrics": sig.get("metrics", {}),
            })
            ticker_scores[ticker]["total_weight"] += w

    aggregated = []
    for ticker, data in ticker_scores.items():
        total_w = data["total_weight"]
        if total_w == 0:
            continue
        ensemble_score = sum(data["scores"]) / total_w
        buy_votes = sum(1 for s in data["strategies"] if s["direction"] == "buy")
        sell_votes = sum(1 for s in data["strategies"] if s["direction"] == "sell")
        total_votes = len(data["strategies"])
        if total_votes == 0:
            continue

        buy_pct = buy_votes / total_votes
        sell_pct = sell_votes / total_votes
        consensus = max(buy_pct, sell_pct)

        if consensus >= min_consensus:
            direction = "buy" if buy_pct > sell_pct else "sell"
            aggregated.append({
                "ticker": ticker,
                "direction": direction,
                "ensembleScore": round(ensemble_score, 4),
                "consensus": round(consensus, 3),
                "strategies": data["strategies"],
                "buyVotes": buy_votes,
                "sellVotes": sell_votes,
                "source": "quant_engine",
            })

    aggregated.sort(key=lambda x: abs(x["ensembleScore"]), reverse=True)
    return aggregated
