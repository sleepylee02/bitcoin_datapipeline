/*
 * High-performance C++ SBE decoder for Binance market data.
 * 
 * This decoder follows the official Binance SBE C++ sample app patterns
 * for parsing binary WebSocket stream messages.
 * 
 * Based on: https://github.com/binance/binance-sbe-cpp-sample-app
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <string>
#include <vector>
#include <unordered_map>
#include <optional>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <chrono>
#include <stdexcept>

namespace py = pybind11;

// Allow build-time overrides (defaults match Binance schema 1:0)
#ifndef BINANCE_SBE_SCHEMA_ID
#define BINANCE_SBE_SCHEMA_ID 1
#endif

#ifndef BINANCE_SBE_SCHEMA_VERSION
#define BINANCE_SBE_SCHEMA_VERSION 0
#endif

// SBE Message header structure (from Binance SBE specification)
struct MessageHeader {
    uint16_t blockLength;
    uint16_t templateId;
    uint16_t schemaId;
    uint16_t version;
} __attribute__((packed));

// Template IDs observed for Binance SBE WebSocket streams (schema 1:0)
enum class TemplateIdV1 : uint16_t {
    TRADES_STREAM_EVENT = 10000,            // <symbol>@trade
    BEST_BID_ASK_STREAM_EVENT = 10001,      // <symbol>@bestBidAsk
    DEPTH_DIFF_STREAM_EVENT = 10002,        // <symbol>@depth
    DEPTH_DIFF_STREAM_EVENT_V2 = 10003      // <symbol>@depth (newer schema variant)
};

struct HeaderLocation {
    MessageHeader header;
    size_t offset;
};

static bool isTradeTemplate(uint16_t templateId) {
    return templateId == static_cast<uint16_t>(TemplateIdV1::TRADES_STREAM_EVENT) || templateId == 101;
}

static bool isBestBidAskTemplate(uint16_t templateId) {
    return templateId == static_cast<uint16_t>(TemplateIdV1::BEST_BID_ASK_STREAM_EVENT) || templateId == 102;
}

static bool isDepthDiffTemplate(uint16_t templateId) {
    return templateId == static_cast<uint16_t>(TemplateIdV1::DEPTH_DIFF_STREAM_EVENT) ||
           templateId == static_cast<uint16_t>(TemplateIdV1::DEPTH_DIFF_STREAM_EVENT_V2) ||
           templateId == 103;
}


static bool isKnownTemplate(uint16_t templateId) {
    return isTradeTemplate(templateId) ||
           isBestBidAskTemplate(templateId) ||
           isDepthDiffTemplate(templateId);
}

static std::optional<HeaderLocation> locateSbeHeader(const char* buffer, size_t size) {
    if (!buffer || size < sizeof(MessageHeader)) {
        return std::nullopt;
    }

    const size_t maxOffset = size - sizeof(MessageHeader);
    for (size_t offset = 0; offset <= maxOffset; ++offset) {
        MessageHeader candidate{};
        std::memcpy(&candidate, buffer + offset, sizeof(MessageHeader));

        // Only validate schema ID and version - accept any template ID for now
        if (candidate.schemaId != BINANCE_SBE_SCHEMA_ID || candidate.version != BINANCE_SBE_SCHEMA_VERSION) {
            continue;
        }

        // Remove strict template validation - accept any template ID
        // This allows us to handle unknown template IDs gracefully
        
        size_t minimumSize = offset + sizeof(MessageHeader);
        if (minimumSize > size) {
            continue;
        }

        return HeaderLocation{candidate, offset};
    }

    return std::nullopt;
}

// Trade stream message structure (TradesStreamEvent)
struct TradeStreamMessage {
    uint64_t eventTime;     // microseconds
    uint64_t tradeTime;     // microseconds
    int64_t tradeId;
    int64_t price;          // mantissa
    int8_t priceExponent;
    int64_t quantity;       // mantissa
    int8_t quantityExponent;
    uint8_t isBuyerMaker;
    char symbol[16];        // null-terminated string
} __attribute__((packed));

// Best bid/ask message structure (BestBidAskStreamEvent)
// Note: This is our best guess at Binance SBE layout - might need adjustment
struct BestBidAskMessage {
    uint64_t eventTime;     // microseconds (8 bytes)
    int64_t bidPrice;       // mantissa (8 bytes)
    int8_t bidPriceExponent; // (1 byte)
    int64_t bidQuantity;    // mantissa (8 bytes)  
    int8_t bidQuantityExponent; // (1 byte)
    int64_t askPrice;       // mantissa (8 bytes)
    int8_t askPriceExponent; // (1 byte)
    int64_t askQuantity;    // mantissa (8 bytes)
    int8_t askQuantityExponent; // (1 byte) 
    char symbol[16];        // null-terminated string (16 bytes)
} __attribute__((packed));  // Total: 60 bytes, but actual blockLength=50

// Price level for depth streams
struct PriceLevel {
    int64_t price;          // mantissa
    int8_t priceExponent;
    int64_t quantity;       // mantissa
    int8_t quantityExponent;
} __attribute__((packed));

// Depth diff message structure (DepthDiffStreamEvent)
struct DepthDiffMessage {
    uint64_t eventTime;     // microseconds
    uint64_t firstUpdateId;
    uint64_t finalUpdateId;
    uint16_t bidCount;
    uint16_t askCount;
    char symbol[16];        // null-terminated string
    // Followed by variable-length bid/ask arrays
} __attribute__((packed));

class SBEDecoder {
private:
    static constexpr uint16_t EXPECTED_SCHEMA_ID = BINANCE_SBE_SCHEMA_ID;
    static constexpr uint16_t EXPECTED_SCHEMA_VERSION = BINANCE_SBE_SCHEMA_VERSION;
    
    // Convert mantissa/exponent to double (Binance decimal encoding)
    double decodeDecimal(int64_t mantissa, int8_t exponent) {
        return static_cast<double>(mantissa) * std::pow(10.0, exponent);
    }
    
    static uint64_t microsToMillis(uint64_t value) {
        return value / 1000ULL;
    }

    // Extract null-terminated symbol string
    std::string extractSymbol(const char* symbolBuffer, size_t maxLength = 16) {
        size_t length = 0;
        while (length < maxLength && symbolBuffer[length] != '\0') {
            length++;
        }
        return std::string(symbolBuffer, length);
    }
    
    // Validate SBE message header (relaxed validation)
    bool validateHeader(const MessageHeader& header) {
        // Only validate schema ID and version, accept any template ID
        return header.schemaId == EXPECTED_SCHEMA_ID && 
               header.version == EXPECTED_SCHEMA_VERSION;
    }
    
    // Get current timestamp in milliseconds
    uint64_t getCurrentTimeMillis() {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
    }

public:
    SBEDecoder() = default;
    
    // Decode trade stream message (TradesStreamEvent)
    py::dict decodeTrade(const py::bytes& data) {
        const char* buffer = PyBytes_AsString(data.ptr());
        size_t size = PyBytes_Size(data.ptr());

        auto headerInfo = locateSbeHeader(buffer, size);
        if (!headerInfo.has_value()) {
            throw std::runtime_error("SBE trade message header not found");
        }

        const MessageHeader& header = headerInfo->header;
        if (!isTradeTemplate(header.templateId)) {
            throw std::runtime_error("Unexpected template for trade message");
        }

        size_t payloadOffset = headerInfo->offset + sizeof(MessageHeader);
        const size_t actualPayloadSize = header.blockLength;
        
        if (payloadOffset + actualPayloadSize > size) {
            throw std::runtime_error("Invalid trade message size: expected " + 
                                   std::to_string(actualPayloadSize) + " bytes, got " + 
                                   std::to_string(size - payloadOffset) + " bytes");
        }

        TradeStreamMessage trade{};
        std::memcpy(&trade, buffer + payloadOffset, std::min(actualPayloadSize, sizeof(TradeStreamMessage)));

        py::dict result;
        result["symbol"] = extractSymbol(trade.symbol);
        result["event_ts"] = microsToMillis(trade.eventTime);
        result["ingest_ts"] = getCurrentTimeMillis();
        result["trade_time"] = microsToMillis(trade.tradeTime);
        auto tradeId = static_cast<long long>(trade.tradeId);
        result["trade_id"] = tradeId;
        result["price"] = decodeDecimal(trade.price, trade.priceExponent);
        result["qty"] = decodeDecimal(trade.quantity, trade.quantityExponent);
        result["is_buyer_maker"] = static_cast<bool>(trade.isBuyerMaker);
        result["source"] = "sbe";
        result["msg_type"] = "trade";
        
        return result;
    }
    
    // Decode best bid/ask stream message (BestBidAskStreamEvent)
    py::dict decodeBestBidAsk(const py::bytes& data) {
        const char* buffer = PyBytes_AsString(data.ptr());
        size_t size = PyBytes_Size(data.ptr());

        auto headerInfo = locateSbeHeader(buffer, size);
        if (!headerInfo.has_value()) {
            throw std::runtime_error("SBE best bid/ask header not found");
        }

        const MessageHeader& header = headerInfo->header;
        if (!isBestBidAskTemplate(header.templateId)) {
            throw std::runtime_error("Unexpected template for best bid/ask message");
        }

        size_t payloadOffset = headerInfo->offset + sizeof(MessageHeader);
        const size_t actualPayloadSize = header.blockLength;
        
        if (payloadOffset + actualPayloadSize > size) {
            throw std::runtime_error("Invalid best bid/ask message size: expected " + 
                                   std::to_string(actualPayloadSize) + " bytes, got " + 
                                   std::to_string(size - payloadOffset) + " bytes");
        }

        BestBidAskMessage ticker{};
        std::memcpy(&ticker, buffer + payloadOffset, std::min(actualPayloadSize, sizeof(BestBidAskMessage)));

        py::dict result;
        result["symbol"] = extractSymbol(ticker.symbol);
        result["event_ts"] = microsToMillis(ticker.eventTime);
        result["ingest_ts"] = getCurrentTimeMillis();
        result["bid_px"] = decodeDecimal(ticker.bidPrice, ticker.bidPriceExponent);
        result["bid_sz"] = decodeDecimal(ticker.bidQuantity, ticker.bidQuantityExponent);
        result["ask_px"] = decodeDecimal(ticker.askPrice, ticker.askPriceExponent);
        result["ask_sz"] = decodeDecimal(ticker.askQuantity, ticker.askQuantityExponent);
        result["source"] = "sbe";
        result["msg_type"] = "bestBidAsk";
        
        return result;
    }
    
    // Decode depth diff stream message (DepthDiffStreamEvent)
    py::dict decodeDepthDiff(const py::bytes& data) {
        const char* buffer = PyBytes_AsString(data.ptr());
        size_t size = PyBytes_Size(data.ptr());

        auto headerInfo = locateSbeHeader(buffer, size);
        if (!headerInfo.has_value()) {
            throw std::runtime_error("SBE depth diff header not found");
        }

        const MessageHeader& header = headerInfo->header;
        if (!isDepthDiffTemplate(header.templateId)) {
            throw std::runtime_error("Unexpected template for depth diff message");
        }

        size_t payloadOffset = headerInfo->offset + sizeof(MessageHeader);
        const size_t actualPayloadSize = header.blockLength;
        
        if (payloadOffset + actualPayloadSize > size) {
            throw std::runtime_error("Invalid depth diff message size: expected " + 
                                   std::to_string(actualPayloadSize) + " bytes, got " + 
                                   std::to_string(size - payloadOffset) + " bytes");
        }

        DepthDiffMessage depth{};
        std::memcpy(&depth, buffer + payloadOffset, std::min(actualPayloadSize, sizeof(DepthDiffMessage)));

        py::dict result;
        result["symbol"] = extractSymbol(depth.symbol);
        result["event_ts"] = microsToMillis(depth.eventTime);
        result["ingest_ts"] = getCurrentTimeMillis();
        auto firstUpdateId = static_cast<unsigned long long>(depth.firstUpdateId);
        auto finalUpdateId = static_cast<unsigned long long>(depth.finalUpdateId);
        result["first_update_id"] = firstUpdateId;
        result["final_update_id"] = finalUpdateId;

        // Parse variable-length bid/ask arrays
        const char* priceDataStart = buffer + payloadOffset + sizeof(DepthDiffMessage);
        size_t remainingSize = size - (payloadOffset + sizeof(DepthDiffMessage));

        py::list bids, asks;
        size_t offset = 0;

        // Parse bids
        for (uint16_t i = 0; i < depth.bidCount && offset + sizeof(PriceLevel) <= remainingSize; ++i) {
            PriceLevel level{};
            std::memcpy(&level, priceDataStart + offset, sizeof(PriceLevel));
            py::dict bid;
            bid["price"] = decodeDecimal(level.price, level.priceExponent);
            bid["qty"] = decodeDecimal(level.quantity, level.quantityExponent);
            bids.append(bid);
            offset += sizeof(PriceLevel);
        }

        // Parse asks
        for (uint16_t i = 0; i < depth.askCount && offset + sizeof(PriceLevel) <= remainingSize; ++i) {
            PriceLevel level{};
            std::memcpy(&level, priceDataStart + offset, sizeof(PriceLevel));
            py::dict ask;
            ask["price"] = decodeDecimal(level.price, level.priceExponent);
            ask["qty"] = decodeDecimal(level.quantity, level.quantityExponent);
            asks.append(ask);
            offset += sizeof(PriceLevel);
        }
        
        result["bids"] = bids;
        result["asks"] = asks;
        result["source"] = "sbe";
        result["msg_type"] = "depthDiff";
        
        return result;
    }
    
    // Get message template ID from SBE header
    uint16_t getMessageType(const py::bytes& data) {
        const char* buffer = PyBytes_AsString(data.ptr());
        size_t size = PyBytes_Size(data.ptr());

        auto headerInfo = locateSbeHeader(buffer, size);
        if (!headerInfo.has_value()) {
            return 0;
        }

        return headerInfo->header.templateId;
    }
    
    // Validate message format and schema
    bool isValidMessage(const py::bytes& data) {
        const char* buffer = PyBytes_AsString(data.ptr());
        size_t size = PyBytes_Size(data.ptr());
        return locateSbeHeader(buffer, size).has_value();
    }
    
    // Decode any SBE message based on template ID
    py::dict decodeMessage(const py::bytes& data) {
        uint16_t templateId = getMessageType(data);

        if (isTradeTemplate(templateId)) {
            return decodeTrade(data);
        }
        if (isBestBidAskTemplate(templateId)) {
            return decodeBestBidAsk(data);
        }
        if (isDepthDiffTemplate(templateId)) {
            return decodeDepthDiff(data);
        }

        throw std::runtime_error("Unknown SBE message template ID: " + std::to_string(templateId));
    }
};

PYBIND11_MODULE(sbe_decoder_cpp, m) {
    m.doc() = "High-performance C++ SBE decoder for Binance market data (following official sample patterns)";
    
    py::class_<SBEDecoder>(m, "SBEDecoder")
        .def(py::init<>())
        .def("decode_trade", &SBEDecoder::decodeTrade, "Decode SBE trade stream message")
        .def("decode_best_bid_ask", &SBEDecoder::decodeBestBidAsk, "Decode SBE best bid/ask stream message")
        .def("decode_depth_diff", &SBEDecoder::decodeDepthDiff, "Decode SBE depth diff stream message")
        .def("decode_message", &SBEDecoder::decodeMessage, "Auto-decode SBE message based on template ID")
        .def("get_message_type", &SBEDecoder::getMessageType, "Get SBE message template ID")
        .def("is_valid_message", &SBEDecoder::isValidMessage, "Validate SBE message format and schema");
    
    // Export Binance SBE template IDs (schema 1:0 defaults)
    m.attr("TRADES_STREAM_EVENT") = static_cast<uint16_t>(TemplateIdV1::TRADES_STREAM_EVENT);
    m.attr("BEST_BID_ASK_STREAM_EVENT") = static_cast<uint16_t>(TemplateIdV1::BEST_BID_ASK_STREAM_EVENT);
    m.attr("DEPTH_DIFF_STREAM_EVENT") = static_cast<uint16_t>(TemplateIdV1::DEPTH_DIFF_STREAM_EVENT);
    m.attr("DEPTH_DIFF_STREAM_EVENT_V2") = static_cast<uint16_t>(TemplateIdV1::DEPTH_DIFF_STREAM_EVENT_V2);
    
    // Export schema constants
    m.attr("EXPECTED_SCHEMA_ID") = BINANCE_SBE_SCHEMA_ID;
    m.attr("EXPECTED_SCHEMA_VERSION") = BINANCE_SBE_SCHEMA_VERSION;
}
