/*
 * Binance SBE message utility implementations.
 * 
 * This file provides the utility classes needed by the official
 * Binance SBE decoder integration.
 * 
 * Based on: https://github.com/binance/binance-sbe-cpp-sample-app
 */

#include <string>
#include <optional>
#include <span>
#include <cstring>

#include "spot_sbe/MessageHeader.h"
#include "spot_sbe/ErrorResponse.h"

using spot_sbe::MessageHeader;
using spot_sbe::ErrorResponse;

// Error class implementation (simplified from official sample)
class Error {
public:
    int code;
    std::string msg;
    std::optional<int64_t> server_time;
    std::optional<int64_t> retry_after;

    explicit Error(ErrorResponse& decoder) {
        code = decoder.code();
        msg = decoder.getMsgAsString();
        
        const auto server_time_val = decoder.serverTime();
        if (server_time_val != ErrorResponse::serverTimeNullValue()) {
            server_time = server_time_val;
        }
        
        const auto retry_after_val = decoder.retryAfter();
        if (retry_after_val != ErrorResponse::retryAfterNullValue()) {
            retry_after = retry_after_val;
        }
    }
};

// WebSocket metadata structure (simplified from official sample)
struct WebSocketMetadata {
    struct RateLimit {
        int rate_limit_type;
        int interval;
        int interval_num;
        int64_t rate_limit;
        int64_t current;
    };
    
    int64_t status;
    std::vector<RateLimit> rate_limits;
    std::string id;
    std::span<char> result;
};

// Utility template function for creating message decoders (from official sample)
template <typename T>
T message_from_header(const std::span<char> buffer, const MessageHeader& header) {
    return T{buffer.data(), MessageHeader::encodedLength(), buffer.size(), header.blockLength(),
             header.version()};
}