from __future__ import annotations

import logging
from typing import Any

from backend.models.prophet_model import predict_prophet
from backend.models.xgboost_model import predict_xgboost
from backend.models.lstm_model import predict_lstm
from backend.utils.helpers import TTLCache, safe_float

logger = logging.getLogger(__name__)


@TTLCache(ttl=600, maxsize=50)
def predict_ensemble(ticker: str, days: int = 30) -> dict[str, Any]:
    models = {}
    weights = {}

    # Run each model
    prophet_result = predict_prophet(ticker, days)
    if prophet_result:
        models["prophet"] = prophet_result
        weights["prophet"] = 0.4

    xgb_result = predict_xgboost(ticker, days)
    if xgb_result:
        models["xgboost"] = xgb_result
        weights["xgboost"] = 0.4

    lstm_result = predict_lstm(ticker, days)
    if lstm_result:
        models["lstm"] = lstm_result
        weights["lstm"] = 0.2

    if not models:
        return {
            "ticker": ticker.upper(),
            "days": days,
            "error": "No prediction models available",
            "models": {},
            "ensemble": None,
        }

    # Normalize weights
    total_weight = sum(weights.values())
    for k in weights:
        weights[k] /= total_weight

    # Weighted ensemble
    ensemble_price = 0
    ensemble_change = 0
    ensemble_confidence = 0

    for name, result in models.items():
        w = weights[name]
        ensemble_price += w * safe_float(result.get("predictedPrice"))
        ensemble_change += w * safe_float(result.get("changePercent"))
        ensemble_confidence += w * safe_float(result.get("confidence"))

    current_price = safe_float(next(iter(models.values())).get("currentPrice"))

    # Merge daily predictions
    all_dates = set()
    for m in models.values():
        for p in m.get("predictions", []):
            all_dates.add(p["date"])

    merged_predictions = []
    for date in sorted(all_dates):
        day_price = 0
        day_upper = 0
        day_lower = 0
        day_count = 0
        for name, result in models.items():
            w = weights[name]
            for p in result.get("predictions", []):
                if p["date"] == date:
                    day_price += w * safe_float(p["price"])
                    day_upper += w * safe_float(p["upper"])
                    day_lower += w * safe_float(p["lower"])
                    day_count += 1
                    break
        if day_count > 0:
            merged_predictions.append({
                "date": date,
                "price": round(day_price, 2),
                "upper": round(day_upper, 2),
                "lower": round(day_lower, 2),
            })

    # Model agreement
    directions = [m.get("direction", "sideways") for m in models.values()]
    agreement = len(set(directions)) == 1

    # Build model summary for frontend
    model_details = {}
    for name, result in models.items():
        model_details[name] = {
            "price": safe_float(result.get("predictedPrice")),
            "weight": round(weights[name] * 100, 1),
            "confidence": safe_float(result.get("confidence")),
            "direction": result.get("direction", "sideways"),
            "changePercent": safe_float(result.get("changePercent")),
        }

    # Provide defaults for missing models
    for model_name in ["prophet", "xgboost", "lstm"]:
        if model_name not in model_details:
            model_details[model_name] = {
                "price": 0,
                "weight": 0,
                "confidence": 0,
                "direction": "unavailable",
                "changePercent": 0,
                "available": False,
            }

    return {
        "ticker": ticker.upper(),
        "days": days,
        "currentPrice": round(current_price, 2),
        "ensemble": {
            "predictedPrice": round(ensemble_price, 2),
            "changePercent": round(ensemble_change, 2),
            "confidence": round(ensemble_confidence, 1),
            "direction": "up" if ensemble_change > 1 else "down" if ensemble_change < -1 else "sideways",
            "modelsUsed": list(models.keys()),
            "modelAgreement": agreement,
        },
        "models": model_details,
        "predictions": merged_predictions,
        "featureImportance": xgb_result.get("featureImportance", []) if xgb_result else [],
        "riskMetrics": {
            "maxDrawdown": round(abs(min(p["lower"] for p in merged_predictions) - current_price) / current_price * 100, 2) if merged_predictions else 0,
            "upside": round(max(p["upper"] for p in merged_predictions) / current_price * 100 - 100, 2) if merged_predictions else 0,
            "downside": round(min(p["lower"] for p in merged_predictions) / current_price * 100 - 100, 2) if merged_predictions else 0,
        },
    }
