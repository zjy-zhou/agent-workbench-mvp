from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from backend.app.data import DEFAULT_ORDER_ID
from backend.app.models import ChatResponse, PlanStep, ToolResult, TraceEvent
from backend.app.planner import extract_order_id, plan_for_message
from backend.app.tools import registry


def run_agent(message: str, user_id: str) -> ChatResponse:
    trace: list[TraceEvent] = []
    plan = plan_for_message(message)
    results: list[ToolResult] = []
    context: Dict[str, Any] = {}

    trace.append(
        TraceEvent(
            type="planner",
            message="Planner（规划器）已生成任务链表。",
            payload={"steps": [step.model_dump() for step in plan]},
        )
    )

    for index, step in enumerate(plan):
        step.status = "running"
        tool_input = build_tool_input(step, message, user_id, context)
        trace.append(
            TraceEvent(
                type="tool_call",
                message=f"调用工具：{step.tool_name}",
                payload={"input": tool_input},
            )
        )
        result = registry.run(step.tool_name, tool_input)
        step.status = "success" if result.success else "failed"
        results.append(result)
        merge_result(context, result)
        trace.append(
            TraceEvent(
                type="tool_result",
                message=f"工具完成：{step.tool_name}",
                payload=result.model_dump(),
            )
        )

        if not result.success:
            for pending in plan[index + 1 :]:
                pending.status = "failed"
            break

    answer, needs_confirmation = compose_answer(message, context, results)
    return ChatResponse(
        answer=answer,
        plan=plan,
        tool_results=results,
        trace=trace,
        needs_human_confirmation=needs_confirmation,
    )


def build_tool_input(
    step: PlanStep,
    message: str,
    user_id: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    if step.tool_name == "query_order":
        return {
            "user_id": user_id,
            "order_id": extract_order_id(message) or DEFAULT_ORDER_ID,
        }
    if step.tool_name == "retrieve_policy":
        order = context.get("order") or {}
        return {"category": order.get("category") or "手机", "query": message}
    if step.tool_name == "check_eligibility":
        return {
            "order": deepcopy(context.get("order") or {}),
            "policy": deepcopy(context.get("policy") or {}),
        }
    return {}


def merge_result(context: Dict[str, Any], result: ToolResult) -> None:
    if not result.success:
        context["last_error"] = result.error
        return
    if result.tool_name == "query_order":
        context["order"] = result.output.get("order")
        context["assumed_order"] = result.output.get("assumed_order", False)
    elif result.tool_name == "retrieve_policy":
        context["policy"] = result.output.get("policy")
    elif result.tool_name == "check_eligibility":
        context["eligibility"] = result.output


def compose_answer(
    message: str,
    context: Dict[str, Any],
    results: list[ToolResult],
) -> tuple[str, bool]:
    if context.get("last_error") == "ORDER_PERMISSION_DENIED":
        return "这个订单不在当前用户名下，出于隐私和权限保护，我不能展示该订单信息。", False
    if context.get("last_error") == "ORDER_NOT_FOUND":
        return "没有查到这个订单。请确认订单号是否正确。", False

    order = context.get("order")
    policy = context.get("policy")
    eligibility = context.get("eligibility")

    if eligibility and order and policy:
        prefix = ""
        if context.get("assumed_order"):
            prefix = f"我先按最近订单 {order['order_id']}（{order['product_name']}）做判断；正式申请前需要您确认订单。\n\n"
        decision = "可以进入退货确认流程" if eligibility["eligible"] else "暂不满足无理由退货条件"
        answer = (
            f"{prefix}订单商品：{order['product_name']}。\n"
            f"订单状态：{order['status']}，已签收 {order['signed_days']} 天。\n"
            f"适用规则：{policy['rule_name']}，{policy['notes']}\n"
            f"判断结果：{decision}。\n"
            f"原因：{eligibility['reason']}"
        )
        if eligibility["needs_human_confirmation"]:
            answer += "\n\n请确认是否继续申请退货。"
        return answer, bool(eligibility["needs_human_confirmation"] or context.get("assumed_order"))

    if order:
        return (
            f"查到订单 {order['order_id']}：{order['product_name']}，"
            f"当前状态是 {order['status']}，金额 {order['amount']} 元。"
        ), False

    if policy:
        return f"检索到规则：{policy['rule_name']}。{policy['notes']}", False

    return "当前没有找到可执行的任务结果，请补充订单号或售后问题。", False

