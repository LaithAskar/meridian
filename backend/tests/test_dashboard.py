"""
Tests for backend.dashboard.

Routes are tested in isolation against a fresh FastAPI app so they don't
trigger the main app's lifespan (which logs into Robinhood).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.dashboard import STRATEGIES, get_strategy_payload, register_dashboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    register_dashboard(app)
    return app


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _get(app: FastAPI, path: str):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


# ---------------------------------------------------------------------------
# get_strategy_payload — direct calls (no HTTP)
# ---------------------------------------------------------------------------


class TestStrategyPayload:
    def test_quant_payload_has_metrics_and_curves(self):
        # quant has results; metrics.json + equity_curve.csv are committed.
        p = get_strategy_payload("quant")
        assert p["strategy"] == "quant"
        assert p["metrics"]["status"] == "ok"
        assert p["metrics"]["full_window"]["sharpe"] is not None
        assert len(p["equity"]) > 0
        assert {"ts", "equity"} <= set(p["equity"][0].keys())

    def test_vader_payload_has_metrics_and_curves(self):
        p = get_strategy_payload("vader")
        assert p["strategy"] == "vader"
        assert p["metrics"]["status"] == "ok"
        assert p["metrics"]["full_window"]["sharpe"] is not None

    def test_finbert_payload_degrades_gracefully(self):
        # FinBERT results not yet generated; payload must say so, not crash.
        p = get_strategy_payload("finbert")
        assert p["strategy"] == "finbert"
        # Either "ok" (if a run has landed) or "no_results" — both must not
        # crash the route and must keep the shape stable.
        assert p["metrics"]["status"] in ("ok", "no_results", "error")
        assert isinstance(p["equity"], list)
        assert isinstance(p["trades"], list)

    def test_unknown_strategy_raises_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            get_strategy_payload("bogus")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


class TestRoutes:
    def test_per_strategy_endpoint_returns_200_for_each(self):
        app = _make_app()
        for s in STRATEGIES:
            r = _run(_get(app, f"/api/strategies/{s}"))
            assert r.status_code == 200, f"{s}: {r.text}"
            j = r.json()
            assert j["strategy"] == s
            assert "metrics" in j

    def test_unknown_strategy_returns_404(self):
        app = _make_app()
        r = _run(_get(app, "/api/strategies/bogus"))
        assert r.status_code == 404

    def test_all_strategies_endpoint(self):
        app = _make_app()
        r = _run(_get(app, "/api/strategies"))
        assert r.status_code == 200
        payload = r.json()
        for s in STRATEGIES:
            assert s in payload

    def test_dashboard_html_route(self):
        app = _make_app()
        r = _run(_get(app, "/dashboard"))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        assert "<!doctype html>" in body.lower()
        assert "chart.js" in body.lower()
        for s in STRATEGIES:
            assert s in body  # strategy names appear in the JS code at minimum

    def test_paper_endpoint_returns_200_for_each_strategy(self):
        app = _make_app()
        for s in STRATEGIES:
            r = _run(_get(app, f"/api/paper/{s}"))
            assert r.status_code == 200, f"{s}: {r.text}"
            j = r.json()
            assert j["strategy"] == s
            assert j["mode"] == "paper"
            # No paper data has been generated yet — every strategy degrades
            # to no_results, but the schema must stay stable.
            assert j["metrics"]["status"] in ("ok", "no_results", "error")
            assert isinstance(j["equity"], list)
            assert isinstance(j["trades"], list)

    def test_paper_all_endpoint(self):
        app = _make_app()
        r = _run(_get(app, "/api/paper"))
        assert r.status_code == 200
        payload = r.json()
        for s in STRATEGIES:
            assert s in payload
            assert payload[s]["mode"] == "paper"

    def test_dashboard_html_contains_paper_section(self):
        app = _make_app()
        r = _run(_get(app, "/dashboard"))
        assert r.status_code == 200
        body = r.text
        assert "paper-grid" in body
        assert "paper trading" in body.lower()
