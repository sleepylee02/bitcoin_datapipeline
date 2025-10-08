# Binance Ingestion: REST (Historical) + WS (JSON/SBE) — Project Skeleton

This repo provides:
- **REST backfill** for historical market data (klines, trades, depth).
- **SBE** stream skeleton (requires decoding with Binance SBE schemas).

Docs:
- REST market data endpoints (base/public info, params, weights):  
  - https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints  
  - https://developers.binance.com/docs/binance-spot-api-docs/rest-api  ← *market-data-only base host & timestamp rules*.
- SBE streams + FAQ (how to receive & decode):  
  - https://developers.binance.com/docs/binance-spot-api-docs/sbe-market-data-streams  
  - https://developers.binance.com/docs/binance-spot-api-docs/faqs/sbe_faq
