# REST API Client for Binance Historical Data

# TODO: Implement REST API client for historical data backfill
# - Base URL: https://api.binance.com
# - Endpoints needed:
#   - /api/v3/klines (historical candlestick data)
#   - /api/v3/trades (historical trades)
#   - /api/v3/depth (current order book snapshot)
# - Add retry logic with exponential backoff
# - Handle rate limiting (weight-based limits from Binance)
# - Add request/response logging

# TODO: Implement backfill logic
# - Fetch historical data for specified time range
# - Handle pagination for large time ranges
# - Deduplicate data if overlapping with real-time stream
# - Support resuming from last successful timestamp

# TODO: Error handling
# - HTTP errors (4xx, 5xx)
# - Rate limit exceeded (HTTP 429)
# - Invalid API response
# - Network timeouts
