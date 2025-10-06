/*
 * Python bindings for official Binance SBE C++ decoder.
 * 
 * This decoder follows the exact patterns from the official Binance SBE C++ sample app
 * with Python bindings for integration into the Bitcoin data pipeline.
 * 
 * Based on: https://github.com/binance/binance-sbe-cpp-sample-app
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <string>
#include <vector>
#include <optional>
#include <span>
#include <iostream>

// Include official Binance SBE headers (exactly as in the official sample)
#include "spot_sbe/MessageHeader.h"
#include "spot_sbe/ErrorResponse.h"
#include "spot_sbe/WebSocketResponse.h"
#include "spot_sbe/BoolEnum.h"
#include "spot_sbe/AccountResponse.h"
#include "spot_sbe/ExchangeInfoResponse.h"
#include "spot_sbe/NewOrderResultResponse.h"
#include "spot_sbe/OrderResponse.h"

// Include official utility headers
#include "util.h"
#include "error.h"
#include "exchange_info.h"
#include "account.h"
#include "post_order.h"
#include "get_order.h"
#include "web_socket_metadata.h"

namespace py = pybind11;

using spot_sbe::AccountResponse;
using spot_sbe::BoolEnum;
using spot_sbe::ErrorResponse;
using spot_sbe::ExchangeInfoResponse;
using spot_sbe::MessageHeader;
using spot_sbe::NewOrderResultResponse;
using spot_sbe::OrderResponse;
using spot_sbe::WebSocketResponse;

// Helper function to convert SBE BoolEnum to Python bool (from official sample)
bool as_bool(const BoolEnum::Value bool_enum) {
    switch (bool_enum) {
        case BoolEnum::Value::False: 
            return false;
        case BoolEnum::Value::True: 
            return true;
        case BoolEnum::Value::NULL_VALUE:
            return false;
    }
    return false;
}

// Read payload from Python bytes (equivalent to read_payload from official sample)
std::vector<char> read_payload_from_python(const py::bytes& data) {
    const char* buffer = PyBytes_AsString(data.ptr());
    size_t size = PyBytes_Size(data.ptr());
    return std::vector<char>(buffer, buffer + size);
}

// Main SBE decoder class (Python wrapper for official decoder logic)
class BinanceSBEDecoder {
public:
    BinanceSBEDecoder() = default;
    
    // Main decode function (follows official main.cpp logic exactly)
    py::dict decode_message(const py::bytes& data) {
        auto storage = read_payload_from_python(data);
        auto payload = std::span<char>{storage};
        MessageHeader message_header{payload.data(), payload.size()};
        
        // A separate "ErrorResponse" message is returned for errors and its format
        // is expected to be backwards compatible across all schema IDs.
        auto template_id = message_header.templateId();
        if (template_id == ErrorResponse::sbeTemplateId()) {
            const auto result = decode_error_response(payload, message_header);
            return convert_error_to_dict(result);
        }
        
        const auto schema_id = message_header.schemaId();
        if (schema_id != ExchangeInfoResponse::sbeSchemaId()) {
            throw std::runtime_error("Unexpected schema ID " + std::to_string(schema_id));
        }
        const auto version = message_header.version();
        if (version != ExchangeInfoResponse::sbeSchemaVersion()) {
            // Schemas with the same ID are expected to be backwards compatible.
            // Log warning but continue
        }
        
        std::optional<WebSocketMetadata> websocket_meta;
        if (template_id == WebSocketResponse::sbeTemplateId()) {
            websocket_meta = decode_websocket_response(payload, message_header);
            payload = websocket_meta->result;
            message_header = MessageHeader{payload.data(), payload.size()};
            template_id = message_header.templateId();
            
            if (template_id == ErrorResponse::sbeTemplateId()) {
                const auto result = decode_error_response(payload, message_header);
                auto dict = convert_error_to_dict(result);
                add_websocket_metadata(dict, websocket_meta);
                return dict;
            }
        }
        
        py::dict result;
        
        if (template_id == AccountResponse::sbeTemplateId()) {
            const auto account_result = decode_account(payload, message_header);
            result = convert_account_to_dict(account_result);
        } else if (template_id == ExchangeInfoResponse::sbeTemplateId()) {
            const auto exchange_info_result = decode_exchange_info(payload, message_header);
            result = convert_exchange_info_to_dict(exchange_info_result);
        } else if (template_id == NewOrderResultResponse::sbeTemplateId()) {
            const auto new_order_result = decode_post_order(payload, message_header);
            result = convert_new_order_to_dict(new_order_result);
        } else if (template_id == OrderResponse::sbeTemplateId()) {
            const auto order_result = decode_get_order(payload, message_header);
            result = convert_get_order_to_dict(order_result);
        } else {
            throw std::runtime_error("Unexpected template ID " + std::to_string(template_id));
        }
        
        if (websocket_meta) {
            add_websocket_metadata(result, websocket_meta);
        }
        
        return result;
    }
    
    // Get message template ID
    uint16_t get_template_id(const py::bytes& data) {
        auto storage = read_payload_from_python(data);
        auto payload = std::span<char>{storage};
        MessageHeader message_header{payload.data(), payload.size()};
        return message_header.templateId();
    }
    
    // Validate message format
    bool is_valid_message(const py::bytes& data) {
        try {
            auto storage = read_payload_from_python(data);
            auto payload = std::span<char>{storage};
            MessageHeader message_header{payload.data(), payload.size()};
            
            const auto schema_id = message_header.schemaId();
            return schema_id == ExchangeInfoResponse::sbeSchemaId();
        } catch (...) {
            return false;
        }
    }

private:
    // Convert Error to Python dict
    py::dict convert_error_to_dict(const Error& error) {
        py::dict result;
        result["msg_type"] = "error";
        result["source"] = "sbe";
        result["error"] = true;
        result["code"] = error.code;
        result["msg"] = error.msg;
        if (error.server_time) {
            result["server_time"] = *error.server_time;
        }
        if (error.retry_after) {
            result["retry_after"] = *error.retry_after;
        }
        return result;
    }
    
    // Convert Account to Python dict
    py::dict convert_account_to_dict(const Account& account) {
        py::dict result;
        result["msg_type"] = "account";
        result["source"] = "sbe";
        result["can_trade"] = account.can_trade;
        result["can_withdraw"] = account.can_withdraw;
        result["can_deposit"] = account.can_deposit;
        result["brokered"] = account.brokered;
        result["require_self_trade_prevention"] = account.require_self_trade_prevention;
        result["prevent_sor"] = account.prevent_sor;
        result["update_time"] = account.update_time;
        result["uid"] = account.uid;
        
        if (account.trade_group_id) {
            result["trade_group_id"] = *account.trade_group_id;
        }
        
        // Convert balances
        py::list balances;
        for (const auto& balance : account.balances) {
            py::dict balance_dict;
            balance_dict["asset"] = balance.asset;
            balance_dict["free"] = balance.free.mantissa * std::pow(10.0, balance.free.exponent);
            balance_dict["locked"] = balance.locked.mantissa * std::pow(10.0, balance.locked.exponent);
            balances.append(balance_dict);
        }
        result["balances"] = balances;
        
        // Convert permissions
        py::list permissions;
        for (const auto& permission : account.permissions) {
            permissions.append(permission);
        }
        result["permissions"] = permissions;
        
        return result;
    }
    
    // Convert ExchangeInfo to Python dict
    py::dict convert_exchange_info_to_dict(const ExchangeInfo& exchange_info) {
        py::dict result;
        result["msg_type"] = "exchangeInfo";
        result["source"] = "sbe";
        
        // Convert rate limits
        py::list rate_limits;
        for (const auto& rate_limit : exchange_info.rate_limits) {
            py::dict limit_dict;
            limit_dict["rate_limit_type"] = static_cast<int>(rate_limit.rate_limit_type);
            limit_dict["interval"] = static_cast<int>(rate_limit.interval);
            limit_dict["interval_num"] = rate_limit.interval_num;
            limit_dict["limit"] = rate_limit.rate_limit;
            rate_limits.append(limit_dict);
        }
        result["rate_limits"] = rate_limits;
        
        // Convert symbols
        py::list symbols;
        for (const auto& symbol : exchange_info.symbols) {
            py::dict symbol_dict;
            symbol_dict["symbol"] = symbol.symbol;
            symbol_dict["status"] = static_cast<int>(symbol.status);
            symbol_dict["base_asset"] = symbol.base_asset;
            symbol_dict["quote_asset"] = symbol.quote_asset;
            symbol_dict["base_asset_precision"] = symbol.base_asset_precision;
            symbol_dict["quote_asset_precision"] = symbol.quote_asset_precision;
            symbol_dict["iceberg_allowed"] = symbol.iceberg_allowed;
            symbol_dict["oco_allowed"] = symbol.oco_allowed;
            symbol_dict["is_spot_trading_allowed"] = symbol.is_spot_trading_allowed;
            symbol_dict["is_margin_trading_allowed"] = symbol.is_margin_trading_allowed;
            symbols.append(symbol_dict);
        }
        result["symbols"] = symbols;
        
        return result;
    }
    
    // Convert NewOrder to Python dict
    py::dict convert_new_order_to_dict(const NewOrder& new_order) {
        py::dict result;
        result["msg_type"] = "newOrder";
        result["source"] = "sbe";
        result["symbol"] = new_order.symbol;
        result["order_id"] = new_order.order_id;
        result["client_order_id"] = new_order.client_order_id;
        result["transaction_time"] = new_order.transaction_time;
        result["price"] = new_order.price.mantissa * std::pow(10.0, new_order.price.exponent);
        result["orig_qty"] = new_order.orig_qty.mantissa * std::pow(10.0, new_order.orig_qty.exponent);
        result["executed_qty"] = new_order.executed_qty.mantissa * std::pow(10.0, new_order.executed_qty.exponent);
        result["status"] = static_cast<int>(new_order.status);
        result["side"] = static_cast<int>(new_order.side);
        
        if (new_order.order_list_id) {
            result["order_list_id"] = *new_order.order_list_id;
        }
        
        return result;
    }
    
    // Convert GetOrder to Python dict
    py::dict convert_get_order_to_dict(const GetOrder& get_order) {
        py::dict result;
        result["msg_type"] = "order";
        result["source"] = "sbe";
        result["symbol"] = get_order.symbol;
        result["order_id"] = get_order.order_id;
        result["client_order_id"] = get_order.client_order_id;
        result["price"] = get_order.price.mantissa * std::pow(10.0, get_order.price.exponent);
        result["orig_qty"] = get_order.orig_qty.mantissa * std::pow(10.0, get_order.orig_qty.exponent);
        result["executed_qty"] = get_order.executed_qty.mantissa * std::pow(10.0, get_order.executed_qty.exponent);
        result["status"] = static_cast<int>(get_order.status);
        result["side"] = static_cast<int>(get_order.side);
        result["time"] = get_order.time;
        result["update_time"] = get_order.update_time;
        result["is_working"] = get_order.is_working;
        
        if (get_order.order_list_id) {
            result["order_list_id"] = *get_order.order_list_id;
        }
        
        return result;
    }
    
    // Add WebSocket metadata to result
    void add_websocket_metadata(py::dict& result, const std::optional<WebSocketMetadata>& websocket_meta) {
        if (websocket_meta) {
            result["ws_status"] = websocket_meta->status;
            result["ws_id"] = websocket_meta->id;
            
            py::list rate_limits;
            for (const auto& limit : websocket_meta->rate_limits) {
                py::dict limit_dict;
                limit_dict["rate_limit_type"] = limit.rate_limit_type;
                limit_dict["interval"] = limit.interval;
                limit_dict["interval_num"] = limit.interval_num;
                limit_dict["limit"] = limit.rate_limit;
                limit_dict["current"] = limit.current;
                rate_limits.append(limit_dict);
            }
            result["ws_rate_limits"] = rate_limits;
        }
    }
};

PYBIND11_MODULE(sbe_decoder_cpp, m) {
    m.doc() = "Python bindings for official Binance SBE C++ decoder";
    
    py::class_<BinanceSBEDecoder>(m, "SBEDecoder")
        .def(py::init<>())
        .def("decode_message", &BinanceSBEDecoder::decode_message, "Decode SBE message using official Binance patterns")
        .def("get_template_id", &BinanceSBEDecoder::get_template_id, "Get SBE message template ID")
        .def("is_valid_message", &BinanceSBEDecoder::is_valid_message, "Validate SBE message format");
    
    // Export official template IDs from Binance SBE
    m.attr("ACCOUNT_RESPONSE_TEMPLATE_ID") = AccountResponse::sbeTemplateId();
    m.attr("EXCHANGE_INFO_RESPONSE_TEMPLATE_ID") = ExchangeInfoResponse::sbeTemplateId();
    m.attr("NEW_ORDER_RESULT_RESPONSE_TEMPLATE_ID") = NewOrderResultResponse::sbeTemplateId();
    m.attr("ORDER_RESPONSE_TEMPLATE_ID") = OrderResponse::sbeTemplateId();
    m.attr("ERROR_RESPONSE_TEMPLATE_ID") = ErrorResponse::sbeTemplateId();
    m.attr("WEBSOCKET_RESPONSE_TEMPLATE_ID") = WebSocketResponse::sbeTemplateId();
    
    // Export official schema constants
    m.attr("EXPECTED_SCHEMA_ID") = ExchangeInfoResponse::sbeSchemaId();
    m.attr("EXPECTED_SCHEMA_VERSION") = ExchangeInfoResponse::sbeSchemaVersion();
}