from __future__ import annotations

from typing import Any, Callable, Dict

from backend.app.data import DEFAULT_ORDER_ID, ORDERS, POLICIES
from backend.app.models import ToolDefinition, ToolResult


ToolHandler = Callable[[Dict[str, Any]], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def run(self, tool_name: str, tool_input: Dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(tool_name)
        if not handler:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                input=tool_input,
                error=f"Tool {tool_name} is not registered",
            )
        return handler(tool_input)


def query_order(tool_input: Dict[str, Any]) -> ToolResult:
    user_id = str(tool_input.get("user_id") or "1001")
    order_id = str(tool_input.get("order_id") or DEFAULT_ORDER_ID)
    order = ORDERS.get(order_id)
    if not order:
        return ToolResult(
            tool_name="query_order",
            success=False,
            input=tool_input,
            error="ORDER_NOT_FOUND",
        )
    if order["user_id"] != user_id:
        return ToolResult(
            tool_name="query_order",
            success=False,
            input=tool_input,
            error="ORDER_PERMISSION_DENIED",
        )
    return ToolResult(
        tool_name="query_order",
        success=True,
        input=tool_input,
        output={
            "order": order,
            "assumed_order": "order_id" not in tool_input or not tool_input.get("order_id"),
        },
    )


def retrieve_policy(tool_input: Dict[str, Any]) -> ToolResult:
    category = str(tool_input.get("category") or "手机")
    policy = POLICIES.get(category)
    if not policy:
        return ToolResult(
            tool_name="retrieve_policy",
            success=False,
            input=tool_input,
            error="POLICY_NOT_FOUND",
        )
    return ToolResult(
        tool_name="retrieve_policy",
        success=True,
        input=tool_input,
        output={"policy": policy},
    )


def check_eligibility(tool_input: Dict[str, Any]) -> ToolResult:
    order = tool_input.get("order") or {}
    policy = tool_input.get("policy") or {}
    signed_days = int(order.get("signed_days") or 0)
    return_window_days = int(policy.get("return_window_days") or 0)
    status = order.get("status")

    if status != "已签收":
        eligible = False
        reason = f"当前订单状态为{status}，暂不进入已签收后的退货校验。"
    elif signed_days <= return_window_days:
        eligible = True
        reason = f"订单签收 {signed_days} 天，在 {return_window_days} 天规则范围内。"
    else:
        eligible = False
        reason = f"订单已签收 {signed_days} 天，超过 {return_window_days} 天无理由退货窗口。"

    return ToolResult(
        tool_name="check_eligibility",
        success=True,
        input=tool_input,
        output={
            "eligible": eligible,
            "reason": reason,
            "needs_human_confirmation": eligible,
            "suggested_next_action": "confirm_return" if eligible else "explain_policy",
        },
    )


registry = ToolRegistry()

registry.register(
    ToolDefinition(
        name="query_order",
        description="根据 user_id（用户ID）和 order_id（订单号）查询订单详情。",
        input_schema={
            "type": "object",
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "string"},
                "order_id": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "order": {"type": "object"},
                "assumed_order": {"type": "boolean"},
            },
        },
        permission="read:order",
    ),
    query_order,
)

registry.register(
    ToolDefinition(
        name="retrieve_policy",
        description="根据商品品类检索售后规则。",
        input_schema={
            "type": "object",
            "required": ["category"],
            "properties": {"category": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {"policy": {"type": "object"}},
        },
        permission="read:policy",
    ),
    retrieve_policy,
)

registry.register(
    ToolDefinition(
        name="check_eligibility",
        description="结合订单信息和售后规则，判断是否满足售后资格。",
        input_schema={
            "type": "object",
            "required": ["order", "policy"],
            "properties": {
                "order": {"type": "object"},
                "policy": {"type": "object"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "eligible": {"type": "boolean"},
                "reason": {"type": "string"},
                "needs_human_confirmation": {"type": "boolean"},
                "suggested_next_action": {"type": "string"},
            },
        },
        permission="read:eligibility",
    ),
    check_eligibility,
)

