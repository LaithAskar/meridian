from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from backend.utils.helpers import safe_float

logger = logging.getLogger(__name__)

LSTM_AVAILABLE = False
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM as LSTMLayer, Dense, Dropout
    from sklearn.preprocessing import MinMaxScaler
    LSTM_AVAILABLE = True
except ImportError:
    logger.info("TensorFlow not available, LSTM predictions disabled")


def predict_lstm(ticker: str, days: int = 30) -> Optional[dict[str, Any]]:
    if not LSTM_AVAILABLE:
        return None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        df = t.history(period="2y", interval="1d")
        if df is None or df.empty or len(df) < 100:
            return None

        close = df["Close"].values.reshape(-1, 1)
        scaler = MinMaxScaler()
        scaled = scaler.fit_transform(close)

        seq_len = 60
        X, y = [], []
        for i in range(seq_len, len(scaled)):
            X.append(scaled[i-seq_len:i, 0])
            y.append(scaled[i, 0])
        X, y = np.array(X), np.array(y)
        X = X.reshape(X.shape[0], X.shape[1], 1)

        split = int(len(X) * 0.8)
        X_train, y_train = X[:split], y[:split]

        model = Sequential([
            LSTMLayer(50, return_sequences=True, input_shape=(seq_len, 1)),
            Dropout(0.2),
            LSTMLayer(50, return_sequences=False),
            Dropout(0.2),
            Dense(25),
            Dense(1),
        ])
        model.compile(optimizer="adam", loss="mse")
        model.fit(X_train, y_train, epochs=10, batch_size=32, verbose=0)

        last_seq = scaled[-seq_len:].reshape(1, seq_len, 1)
        predictions = []
        current = last_seq.copy()

        for _ in range(days):
            pred = model.predict(current, verbose=0)
            predictions.append(pred[0, 0])
            new_seq = np.append(current[0, 1:, 0], pred[0, 0]).reshape(1, seq_len, 1)
            current = new_seq

        pred_prices_raw = scaler.inverse_transform(np.array(predictions).reshape(-1, 1)).flatten()
        current_price = safe_float(close[-1, 0])

        pred_prices = []
        for i, price in enumerate(pred_prices_raw):
            date = pd.Timestamp.now() + pd.Timedelta(days=i+1)
            pred_prices.append({
                "date": str(date.date()),
                "price": round(float(price), 2),
                "upper": round(float(price * 1.08), 2),
                "lower": round(float(price * 0.92), 2),
            })

        final = float(pred_prices_raw[-1])
        change_pct = ((final - current_price) / current_price * 100) if current_price > 0 else 0

        return {
            "model": "lstm",
            "currentPrice": round(current_price, 2),
            "predictedPrice": round(final, 2),
            "changePercent": round(change_pct, 2),
            "confidence": 45.0,
            "predictions": pred_prices,
            "direction": "up" if change_pct > 1 else "down" if change_pct < -1 else "sideways",
        }
    except Exception as e:
        logger.error(f"LSTM prediction error for {ticker}: {e}")
        return None
