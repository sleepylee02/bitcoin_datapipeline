# WebSocket Client for Binance Real-time Market Data

# TODO: Implement async WebSocket connection to Binance
# - Connect to wss://stream.binance.com:9443/ws/
# - Subscribe to multiple streams: trade, depth, kline
# - Handle connection lifecycle (connect, disconnect, reconnect)
# - Implement exponential backoff for reconnection attempts
# - Parse incoming JSON messages
# - Emit heartbeat messages every 30s to detect connection health
# - Handle ping/pong frames
# - Graceful shutdown on SIGTERM/SIGINT

# TODO: Implement message handlers
# - Trade stream handler (individual trades)
# - Depth stream handler (order book updates)
# - Kline stream handler (candlestick data)
# - Convert raw Binance format to internal MarketData schema

# TODO: Error handling
# - Network errors (connection lost, timeout)
# - Invalid message format
# - Rate limiting from Binance
# - Log all errors with proper context
