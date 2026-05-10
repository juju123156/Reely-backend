"""NXT-aware reporting schema for Excel/export layers."""

NXT_REPORT_SHEETS: dict[str, list[str]] = {
    "nxt_market_context": [
        "timestamp", "symbol", "nxt_session", "nxt_price", "nxt_volume",
        "nxt_turnover", "nxt_spread", "nxt_vwap", "krx_reference_price",
        "venue_price_gap", "data_quality",
    ],
    "venue_gap_monitor": [
        "timestamp", "symbol", "krx_price", "nxt_price", "venue_price_gap",
        "venue_liquidity_ratio", "signal", "action",
    ],
    "nxt_aftermarket_log": [
        "timestamp", "symbol", "nxt_after_price", "nxt_after_volume",
        "nxt_after_turnover", "nxt_after_spread", "nxt_after_signal",
    ],
    "nxt_premarket_log": [
        "timestamp", "symbol", "nxt_pre_price", "nxt_pre_volume",
        "nxt_pre_turnover", "nxt_pre_spread", "nxt_pre_signal",
    ],
    "venue_execution_quality": [
        "order_id", "symbol", "preferred_venue", "actual_venue",
        "expected_price", "fill_price", "slippage", "spread",
        "latency_ms", "routing_result",
    ],
    "sor_routing_log": [
        "timestamp", "order_id", "symbol", "preferred_venue", "actual_venue",
        "venue_policy", "routing_result", "fallback_reason",
    ],
}

