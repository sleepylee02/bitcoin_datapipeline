/*
 * Binance SBE message definitions and utilities.
 * 
 * This file contains utilities for working with Binance SBE binary messages
 * following the official Binance SBE schema 3:1 specification.
 * 
 * Reference: https://github.com/binance/binance-sbe-cpp-sample-app
 */

#include <string>
#include <vector>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <span>
#include <stdexcept>
#include <chrono>
#include <cctype>


namespace binance_sbe {

// SBE Protocol constants (schema 1:0)
constexpr uint16_t CURRENT_SCHEMA_ID = 1;
constexpr uint16_t CURRENT_SCHEMA_VERSION = 0;

// WebSocket SBE stream template IDs (from Binance schema 1:0)
enum class StreamTemplateId : uint16_t {
    TRADES_STREAM_EVENT = 10000,            // <symbol>@trade
    BEST_BID_ASK_STREAM_EVENT = 10001,      // <symbol>@bestBidAsk 
    DEPTH_DIFF_STREAM_EVENT = 10002,        // <symbol>@depth
    DEPTH_DIFF_STREAM_EVENT_V2 = 10003      // <symbol>@depth (schema variant)
};

// SBE message header structure
struct MessageHeader {
    uint16_t blockLength;
    uint16_t templateId;
    uint16_t schemaId;
    uint16_t version;
} __attribute__((packed));

// Utility functions for SBE message validation and parsing
class MessageValidator {
public:
    static bool isValidHeader(const char* buffer, size_t size) {
        if (size < sizeof(MessageHeader)) {
            return false;
        }
        
        const MessageHeader* header = reinterpret_cast<const MessageHeader*>(buffer);
        return header->schemaId == CURRENT_SCHEMA_ID && 
               header->version == CURRENT_SCHEMA_VERSION;
    }
    
    static StreamTemplateId getStreamTemplateId(const char* buffer) {
        const MessageHeader* header = reinterpret_cast<const MessageHeader*>(buffer);
        return static_cast<StreamTemplateId>(header->templateId);
    }
    
    static size_t getBlockLength(const char* buffer) {
        const MessageHeader* header = reinterpret_cast<const MessageHeader*>(buffer);
        return header->blockLength;
    }
    
    static uint16_t getSchemaId(const char* buffer) {
        const MessageHeader* header = reinterpret_cast<const MessageHeader*>(buffer);
        return header->schemaId;
    }
    
    static uint16_t getVersion(const char* buffer) {
        const MessageHeader* header = reinterpret_cast<const MessageHeader*>(buffer);
        return header->version;
    }
};

// Symbol string utilities for WebSocket streams
class SymbolUtils {
public:
    static constexpr size_t MAX_SYMBOL_LENGTH = 16;
    
    // Extract null-terminated symbol from character array
    static std::string extractSymbol(const char* symbolBuffer) {
        size_t length = 0;
        while (length < MAX_SYMBOL_LENGTH && symbolBuffer[length] != '\0') {
            length++;
        }
        return std::string(symbolBuffer, length);
    }
    
    // Validate symbol format (uppercase alphanumeric)
    static bool isValidSymbol(const std::string& symbol) {
        if (symbol.empty() || symbol.length() > MAX_SYMBOL_LENGTH) {
            return false;
        }
        
        return std::all_of(symbol.begin(), symbol.end(), [](char c) {
            return std::isalnum(c) && std::isupper(c);
        });
    }
};

// Decimal encoding/decoding utilities (Binance mantissa/exponent format)
class DecimalCodec {
public:
    struct Decimal {
        int64_t mantissa;
        int8_t exponent;
    };
    
    // Decode Binance decimal to double
    static double decode(int64_t mantissa, int8_t exponent) {
        return static_cast<double>(mantissa) * std::pow(10.0, exponent);
    }
    
    // Encode double to Binance decimal format
    static Decimal encode(double value, int8_t targetExponent = -8) {
        if (std::isnan(value) || std::isinf(value)) {
            throw std::runtime_error("Cannot encode NaN or infinite value");
        }
        
        double scaleFactor = std::pow(10.0, -targetExponent);
        int64_t mantissa = static_cast<int64_t>(std::round(value * scaleFactor));
        
        return {mantissa, targetExponent};
    }
    
    // Check if decimal value is valid
    static bool isValid(int64_t mantissa, int8_t exponent) {
        // Reasonable bounds check
        return exponent >= -18 && exponent <= 18;
    }
};

// Timestamp utilities for microsecond precision
class TimestampUtils {
public:
    // Convert microseconds to milliseconds
    static uint64_t microToMilli(uint64_t microseconds) {
        return microseconds / 1000;
    }
    
    // Convert milliseconds to microseconds
    static uint64_t milliToMicro(uint64_t milliseconds) {
        return milliseconds * 1000;
    }
    
    // Get current timestamp in microseconds
    static uint64_t getCurrentMicros() {
        return std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }
};

// Buffer validation utilities
class BufferValidator {
public:
    // Validate buffer has sufficient size for message type
    template<typename MessageType>
    static bool hasMinSize(std::span<const char> buffer) {
        return buffer.size() >= sizeof(MessageHeader) + sizeof(MessageType);
    }
    
    // Validate buffer has sufficient remaining size for variable data
    static bool hasRemainingSize(std::span<const char> buffer, size_t offset, size_t required) {
        return offset + required <= buffer.size();
    }
};

} // namespace binance_sbe
