# Lightweight MLP for 10s Price Prediction (Binance Data)

Goal:  
Predict the **price change 10 seconds into the future** using a lightweight MLP.  
Run inference **every 1–2 seconds** in a soft real-time loop.

---

## 📌 Data Sources

- **Training (Historical)** – Binance REST Market Data API  
  - Trades & Aggregate Trades (`/api/v3/trades`, `/api/v3/aggTrades`)  
  - Candlesticks / Klines (`/api/v3/klines`)  
  - Book Ticker (`/api/v3/ticker/bookTicker`)  
  - Depth snapshots (`/api/v3/depth`) (optional, for order book features)

- **Inference (Live)** – Binance SBE Market Data Streams  
  - Raw Trades  
  - Best Bid/Ask (bookTicker equivalent with auto-culling)  
  - Depth updates  

---

## 🎯 Prediction Task

- **Frequency**: Every 1s (or 2s)
- **Horizon**: Predict price after 10s
- **Target options**:
  - **Regression**: log-return between now and 10s later  
  - **Classification**: up / down / flat (3-class with dead-zone threshold)

---

## 🔑 Features

### A) Trade-based (train via REST trades/aggTrades; infer via SBE raw trades)
- `ret_1s`, `ret_2s`, `ret_5s` – rolling returns  
- `vwap_5s_dev` – deviation of 5s VWAP from last price  
- `n_trades_1s`, `n_trades_5s` – trade counts  
- `buy_vol_1s`, `sell_vol_1s`, `tvi_1s` – trade volume imbalance  
- `buy_vol_5s`, `sell_vol_5s`, `tvi_5s` – longer imbalance  
- `avg_trade_size_1s` – microstructure intensity  
- `vol_ret_10s` – rolling volatility  
- `burst_1s` – abnormal activity flag  
- `large_trade_flag_5s` – presence of big outliers  
- `time_since_last_trade_ms`

### B) Order book-based (requires depth history)
- `spread` – ask1 − bid1  
- `mid` – (ask1+bid1)/2  
- `obi_top1`, `obi_top5` – order book imbalance  
- `microprice`, `microprice_dev`  
- `obi_slope_3s` – imbalance trend  
- `spread_changes_3s` – spread flips  
- `depth_to_move_0.1pct` – liquidity depth measure  

---

## 🏗️ Architecture

- **Model**: Light MLP
  - Input: 20–40 engineered features
  - Hidden: [64 → 32] with ReLU + Dropout(0.1)
  - Output: 
    - `3 logits` (classification) OR  
    - `1 scalar` (regression)

- **Export**: Torch → ONNX (fast inference)

---

## ✅ TODO List

### Data Prep
- [ ] Implement **REST fetchers** for klines, trades, aggTrades, bookTicker.  
- [ ] Build **feature generator** (trade-based features first).  
- [ ] Add **order book feature generator** (optional; requires depth history).  
- [ ] Define **label** (10s return/direction).  
- [ ] Ensure **no leakage** (use only past & current info).  

### Training
- [ ] Normalize inputs (StandardScaler/RobustScaler).  
- [ ] Train MLP (classification or regression).  
- [ ] Evaluate (accuracy, F1 for cls; MAE + directional hit-rate for reg).  
- [ ] Export model to ONNX + save scaler + feature schema JSON.  

### Inference Loop
- [ ] Subscribe to **SBE streams** (raw trades, bestBidAsk, depth).  
- [ ] Maintain rolling windows with **incremental updates**.  
- [ ] Every 1–2s:  
  - [ ] Assemble features (match schema exactly).  
  - [ ] Apply scaler.  
  - [ ] Run ONNX inference.  
  - [ ] Enforce deadline (skip if >100 ms).  

### Deployment
- [ ] Wrap into async service (e.g., `asyncio` loop).  
- [ ] Log predictions, latency, dropped ticks.  
- [ ] Add decision module (alerts/trading signal).  

---

