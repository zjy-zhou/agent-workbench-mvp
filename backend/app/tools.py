from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable, Dict

from backend.app.data import DEFAULT_ORDER_ID, ORDERS, POLICIES
from backend.app.models import (
    AuditLogPolicy,
    PermissionPolicy,
    RetryPolicy,
    TimeoutPolicy,
    ToolDefinition,
    ToolResult,
)


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

    def run(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        actor_role: str = "customer",
    ) -> ToolResult:
        started_at = time.perf_counter()
        definition = self._definitions.get(tool_name)
        handler = self._handlers.get(tool_name)
        if not definition or not handler:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                input=tool_input,
                error=f"Tool {tool_name} is not registered",
            )

        if actor_role not in definition.permission.allowed_roles:
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                input=tool_input,
                error="TOOL_PERMISSION_DENIED",
                attempts=0,
            )
            return self._finalize_result(result, definition, started_at)

        result: ToolResult | None = None
        for attempt in range(1, definition.retry.max_attempts + 1):
            try:
                result = self._run_with_timeout(
                    handler=handler,
                    tool_input=tool_input,
                    timeout_ms=definition.timeout.timeout_ms,
                )
            except FutureTimeoutError:
                result = ToolResult(
                    tool_name=tool_name,
                    success=False,
                    input=tool_input,
                    error="TOOL_TIMEOUT",
                )

            result.attempts = attempt
            if result.success or result.error not in definition.retry.retryable_errors:
                break

            if attempt < definition.retry.max_attempts and definition.retry.backoff_ms:
                time.sleep(definition.retry.backoff_ms / 1000)

        if result is None:
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                input=tool_input,
                error="TOOL_UNKNOWN_FAILURE",
            )

        return self._finalize_result(result, definition, started_at)

    def _run_with_timeout(
        self,
        handler: ToolHandler,
        tool_input: Dict[str, Any],
        timeout_ms: int,
    ) -> ToolResult:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(handler, tool_input)
            return future.result(timeout=timeout_ms / 1000)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _finalize_result(
        self,
        result: ToolResult,
        definition: ToolDefinition,
        started_at: float,
    ) -> ToolResult:
        result.duration_ms = round((time.perf_counter() - started_at) * 1000)
        if definition.audit_log.enabled:
            result.audit_log = build_audit_event(result, definition)
        return result


def redact_payload(payload: Dict[str, Any], redact_fields: list[str]) -> Dict[str, Any]:
    redacted: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in redact_fields:
            redacted[key] = "***"
        elif isinstance(value, dict):
            redacted[key] = redact_payload(value, redact_fields)
        else:
            redacted[key] = value
    return redacted


def build_audit_event(result: ToolResult, definition: ToolDefinition) -> Dict[str, Any]:
    audit_policy = definition.audit_log
    redact_fields = sorted(
        set(audit_policy.redact_fields) | set(definition.permission.sensitive_fields)
    )
    event: Dict[str, Any] = {
        "event_name": audit_policy.event_name,
        "tool_name": result.tool_name,
        "permission_scope": definition.permission.scope,
        "success": result.success,
        "attempts": result.attempts,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }
    if audit_policy.include_input:
        event["input"] = redact_payload(result.input, redact_fields)
    if audit_policy.include_output:
        event["output"] = redact_payload(result.output, redact_fields)
    else:
        event["output_keys"] = list(result.output.keys())
    return event


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
        permission=PermissionPolicy(
            scope="order.read",
            allowed_roles=["customer", "support"],
            require_owner_check=True,
            sensitive_fields=["user_id", "order_id"],
        ),
        retry=RetryPolicy(
            max_attempts=2,
            backoff_ms=100,
            retryable_errors=["TOOL_TIMEOUT", "TEMPORARY_ERROR"],
        ),
        timeout=TimeoutPolicy(timeout_ms=1200),
        audit_log=AuditLogPolicy(
            event_name="tool.query_order",
            include_input=True,
            include_output=False,
            redact_fields=["user_id"],
        ),
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
        permission=PermissionPolicy(
            scope="policy.read",
            allowed_roles=["customer", "support", "admin"],
        ),
        retry=RetryPolicy(max_attempts=1),
        timeout=TimeoutPolicy(timeout_ms=800),
        audit_log=AuditLogPolicy(
            event_name="tool.retrieve_policy",
            include_input=True,
            include_output=False,
        ),
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
        permission=PermissionPolicy(
            scope="eligibility.check",
            allowed_roles=["customer", "support"],
            require_owner_check=True,
            sensitive_fields=["user_id", "order_id"],
        ),
        retry=RetryPolicy(max_attempts=1),
        timeout=TimeoutPolicy(timeout_ms=1000),
        audit_log=AuditLogPolicy(
            event_name="tool.check_eligibility",
            include_input=False,
            include_output=True,
            redact_fields=["user_id"],
        ),
    ),
    check_eligibility,
)
