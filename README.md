# Meridian — Quantitative Trading Platform

AI-powered stock & crypto analysis with institutional-grade quant engine, sentiment-driven trading, and autonomous crypto bot.

## Architecture

```
Frontend (Next.js :3000)  →  Backend (FastAPI :8000)  →  Robinhood (robin_stocks)
                                    ↓
                          ┌─────────┴─────────┐
                    Sentiment Bot          Quant Engine
                    (Finviz + YF)       (Momentum/Reversion/Factor)
                          ↓                    ↓
                       Trade Executor (PDT-safe, dynamic sizing)
                                    ↓
                             Crypto Bot (24/7)
```

## Quick Start

### 1. Backend

```bash
cd meridian
pip install -r requirements.txt

# Set environment variables
cp .env .env.local  # Edit with your Robinhood credentials

# Run backend
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev    # Development at localhost:3000
# OR
npm run build && npm start  # Production
```

### 3. Crypto Bot (Optional - separate process)

```bash
cd crypto_bot
python main.py
```

## API Endpoints (40+)

### Stock Data
| Endpoint | Description |
|----------|-------------|
| `GET /api/quote/{ticker}` | Real-time quote |
| `GET /api/history/{ticker}?period=1y` | OHLCV data |
| `GET /api/analysis/{ticker}` | Full analysis |
| `GET /api/news/{ticker}` | News + VADER sentiment |
| `GET /api/earnings/{ticker}` | Earnings history |
| `GET /api/predict/{ticker}?days=30` | ML ensemble prediction |
| `POST /api/portfolio` | Markowitz optimization |
| `GET /api/trending` | Trending stocks |

### Trading Bot
| Endpoint | Description |
|----------|-------------|
| `POST /api/trading/start` | Start bot |
| `POST /api/trading/stop` | Stop bot |
| `GET /api/trading/status` | Status + stats |
| `GET /api/trading/signals` | Recent signals |

### Robinhood Account
| Endpoint | Description |
|----------|-------------|
| `POST /api/robinhood/login` | Login (push MFA) |
| `GET /api/robinhood/account` | Equity, buying power |
| `GET /api/robinhood/positions` | Open positions |
| `POST /api/robinhood/order` | Place trade |

### Crypto Bot
| Endpoint | Description |
|----------|-------------|
| `POST /api/crypto/start` | Start crypto bot |
| `POST /api/crypto/stop` | Stop crypto bot |
| `GET /api/crypto/status` | Status + trade log |
| `GET /api/crypto/prices` | Live prices (8 coins) |

## Trading Bot Features

### Dual Engine Architecture
- **Sentiment Engine**: Finviz + Yahoo Finance → VADER → Momentum consensus → Trade
- **Quant Engine**: Momentum + Mean Reversion + Factor Model → Regime-adjusted → Ensemble voting

### Safety Systems
- **PDT Rule**: Never sells same-day purchases. Max 3 day trades / 5 business days. Auto-lifts at $25K.
- **Circuit Breaker**: Max 50 trades/day, 3% daily loss limit
- **Liquidity Reserve**: 20% of equity always kept liquid
- **Adaptive Learning**: 3 independent engines that self-tune and revert on poor performance

### Crypto Bot
- 8 coins: BTC, ETH, SOL, LINK, AVAX, DOGE, SHIB, XLM
- 2-minute cycles, 24/7 (no market hours restriction)
- 3-of-5 indicator confirmation required
- Regime-adjusted weights (trending/mean-reverting/choppy)
- Max $40/trade, 3% daily loss halt, 10% drawdown halt

## ML Prediction Models
- **Prophet**: Facebook's time-series forecasting
- **XGBoost**: Gradient boosting with 20+ engineered features
- **LSTM**: Deep learning (optional, requires TensorFlow)
- **Ensemble**: Weighted combination with confidence scoring

## Zero API Keys Required
Works out of the box with yfinance + Finviz (free, no API key needed).
Reddit/StockTwits may 403 from cloud IPs — the bot gracefully degrades.

## Deployment (Linux/systemd)

```bash
# Backend service
sudo systemctl enable meridian-backend
sudo systemctl start meridian-backend

# Frontend service
sudo systemctl enable meridian-frontend
sudo systemctl start meridian-frontend

# Crypto bot service
sudo systemctl enable meridian-crypto
sudo systemctl start meridian-crypto
```

## Disclaimer
Meridian is for educational purposes only. Not financial advice. Trading involves significant risk of loss. Past performance does not guarantee future results. Use at your own risk.
