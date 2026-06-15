from __future__ import annotations

from datetime import date


ORDERS = {
    "202606150001": {
        "order_id": "202606150001",
        "user_id": "1001",
        "product_name": "星河 X1 手机",
        "category": "手机",
        "status": "已签收",
        "signed_days": 8,
        "signed_at": "2026-06-07",
        "amount": 3999,
    },
    "202606150002": {
        "order_id": "202606150002",
        "user_id": "1001",
        "product_name": "轻风蓝牙耳机",
        "category": "数码配件",
        "status": "已签收",
        "signed_days": 5,
        "signed_at": "2026-06-10",
        "amount": 299,
    },
    "202606150003": {
        "order_id": "202606150003",
        "user_id": "1002",
        "product_name": "云朵保温杯",
        "category": "日用品",
        "status": "待发货",
        "signed_days": 0,
        "signed_at": None,
        "amount": 89,
    },
}


POLICIES = {
    "手机": {
        "category": "手机",
        "rule_name": "手机类商品售后规则",
        "return_window_days": 7,
        "supports_no_reason_return": True,
        "notes": "手机类商品支持 7 天无理由，但签收超过 7 天后通常不能直接申请无理由退货。",
        "source": "demo_policy_mobile_v1",
    },
    "数码配件": {
        "category": "数码配件",
        "rule_name": "数码配件售后规则",
        "return_window_days": 7,
        "supports_no_reason_return": True,
        "notes": "数码配件支持 7 天无理由，需商品完好且配件齐全。",
        "source": "demo_policy_digital_accessory_v1",
    },
    "日用品": {
        "category": "日用品",
        "rule_name": "日用品售后规则",
        "return_window_days": 7,
        "supports_no_reason_return": True,
        "notes": "日用品支持 7 天无理由，特殊消耗品除外。",
        "source": "demo_policy_daily_v1",
    },
}


DEFAULT_USER_ID = "1001"
DEFAULT_ORDER_ID = "202606150001"
TODAY = date(2026, 6, 15)

