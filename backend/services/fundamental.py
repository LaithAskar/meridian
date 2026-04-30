from __future__ import annotations

import logging
from typing import Any

from backend.utils.helpers import TTLCache, safe_float, safe_div
from backend.services.data_service import get_info

logger = logging.getLogger(__name__)


def grade_metric(value: float, thresholds: list[tuple[float, str]], higher_is_better: bool = True) -> str:
    if value == 0:
        return "N/A"
    for threshold, grade in thresholds:
        if higher_is_better and value >= threshold:
            return grade
        if not higher_is_better and value <= threshold:
            return grade
    return thresholds[-1][1] if thresholds else "C"


@TTLCache(ttl=300, maxsize=100)
def get_fundamental_analysis(ticker: str) -> dict[str, Any]:
    try:
        info = get_info(ticker)
        if not info:
            return {"score": 0, "breakdown": {}, "keyStats": {}}

        pe = safe_float(info.get("trailingPE"))
        fwd_pe = safe_float(info.get("forwardPE"))
        pb = safe_float(info.get("priceToBook"))
        ps = safe_float(info.get("priceToSalesTrailing12Months"))
        peg = safe_float(info.get("pegRatio"))
        de = safe_float(info.get("debtToEquity"))
        roe = safe_float(info.get("returnOnEquity", 0)) * 100
        roa = safe_float(info.get("returnOnAssets", 0)) * 100
        margin = safe_float(info.get("profitMargins", 0)) * 100
        gross_margin = safe_float(info.get("grossMargins", 0)) * 100
        rev_growth = safe_float(info.get("revenueGrowth", 0)) * 100
        earn_growth = safe_float(info.get("earningsGrowth", 0)) * 100
        current_ratio = safe_float(info.get("currentRatio"))
        quick_ratio = safe_float(info.get("quickRatio"))
        div_yield = safe_float(info.get("dividendYield", 0)) * 100
        payout = safe_float(info.get("payoutRatio", 0)) * 100
        beta = safe_float(info.get("beta"))
        market_cap = safe_float(info.get("marketCap"))

        # Valuation Score (0-35)
        val_score = 0
        val_factors = []
        if pe > 0:
            if pe < 15:
                val_score += 10
                val_factors.append({"name": "P/E Ratio", "value": round(pe, 1), "assessment": "Undervalued"})
            elif pe < 25:
                val_score += 6
                val_factors.append({"name": "P/E Ratio", "value": round(pe, 1), "assessment": "Fair"})
            else:
                val_score += 2
                val_factors.append({"name": "P/E Ratio", "value": round(pe, 1), "assessment": "Expensive"})
        if peg > 0:
            if peg < 1:
                val_score += 8
            elif peg < 2:
                val_score += 4
        if pb > 0:
            if pb < 3:
                val_score += 6
            elif pb < 5:
                val_score += 3
        if fwd_pe > 0 and pe > 0 and fwd_pe < pe:
            val_score += 5
            val_factors.append({"name": "Forward P/E", "value": round(fwd_pe, 1), "assessment": "Improving"})
        if ps > 0 and ps < 5:
            val_score += 3
        val_score = min(35, val_score)

        # Profitability Score (0-25)
        prof_score = 0
        prof_factors = []
        if roe > 15:
            prof_score += 8
            prof_factors.append({"name": "ROE", "value": f"{roe:.1f}%", "assessment": "Strong"})
        elif roe > 8:
            prof_score += 4
        if margin > 15:
            prof_score += 7
            prof_factors.append({"name": "Profit Margin", "value": f"{margin:.1f}%", "assessment": "Healthy"})
        elif margin > 5:
            prof_score += 3
        if gross_margin > 50:
            prof_score += 5
        elif gross_margin > 30:
            prof_score += 2
        if roa > 10:
            prof_score += 5
        elif roa > 5:
            prof_score += 2
        prof_score = min(25, prof_score)

        # Growth Score (0-20)
        growth_score = 0
        growth_factors = []
        if rev_growth > 20:
            growth_score += 10
            growth_factors.append({"name": "Revenue Growth", "value": f"{rev_growth:.1f}%", "assessment": "High"})
        elif rev_growth > 5:
            growth_score += 5
        if earn_growth > 20:
            growth_score += 10
        elif earn_growth > 5:
            growth_score += 5
        growth_score = min(20, growth_score)

        # Financial Health Score (0-20)
        health_score = 0
        health_factors = []
        if current_ratio > 1.5:
            health_score += 5
        elif current_ratio > 1:
            health_score += 3
        if de > 0 and de < 50:
            health_score += 5
            health_factors.append({"name": "Debt/Equity", "value": round(de, 1), "assessment": "Low"})
        elif de > 0 and de < 100:
            health_score += 3
        if quick_ratio > 1:
            health_score += 5
        if beta > 0 and beta < 1.5:
            health_score += 5
        health_score = min(20, health_score)

        total_score = val_score + prof_score + growth_score + health_score

        # Letter grade
        if total_score >= 80:
            grade = "A+"
        elif total_score >= 70:
            grade = "A"
        elif total_score >= 60:
            grade = "B+"
        elif total_score >= 50:
            grade = "B"
        elif total_score >= 40:
            grade = "C+"
        elif total_score >= 30:
            grade = "C"
        elif total_score >= 20:
            grade = "D"
        else:
            grade = "F"

        return {
            "score": total_score,
            "grade": grade,
            "breakdown": {
                "valuation": {"score": round(val_score, 1), "maxScore": 35, "factors": val_factors},
                "profitability": {"score": round(prof_score, 1), "maxScore": 25, "factors": prof_factors},
                "growth": {"score": round(growth_score, 1), "maxScore": 20, "factors": growth_factors},
                "health": {"score": round(health_score, 1), "maxScore": 20, "factors": health_factors},
            },
            "keyStats": {
                "pe": round(pe, 2),
                "forwardPe": round(fwd_pe, 2),
                "priceToBook": round(pb, 2),
                "priceToSales": round(ps, 2),
                "pegRatio": round(peg, 2),
                "debtToEquity": round(de, 2),
                "roe": round(roe, 2),
                "roa": round(roa, 2),
                "profitMargin": round(margin, 2),
                "grossMargin": round(gross_margin, 2),
                "revenueGrowth": round(rev_growth, 2),
                "earningsGrowth": round(earn_growth, 2),
                "currentRatio": round(current_ratio, 2),
                "quickRatio": round(quick_ratio, 2),
                "dividendYield": round(div_yield, 2),
                "payoutRatio": round(payout, 2),
                "beta": round(beta, 2),
                "marketCap": market_cap,
            },
        }
    except Exception as e:
        logger.error(f"Fundamental analysis error for {ticker}: {e}")
        return {"score": 0, "grade": "N/A", "breakdown": {}, "keyStats": {}}
