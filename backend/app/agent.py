from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from backend.app.data import DEFAULT_ORDER_ID
from backend.app.guardrails import guardrail_service
from backend.app.memory import memory_system
from backend.app.models import (
    ChatResponse,
    GuardrailSnapshot,
    MemorySnapshot,
    PlanStep,
    ToolResult,
    TraceEvent,
)
from backend.app.planner import extract_order_id, plan_for_message
from backend.app.tools import registry


def run_agent(message: str, user_id: str, session_id: str = "demo-session") -> ChatResponse:
    trace: list[TraceEvent] = []
    input_guard = guardrail_service.check_input(message=message, user_id=user_id)
    guardrails = GuardrailSnapshot(input=input_guard)
    trace.append(
        TraceEvent(
            type="input_guard",
            message="Input Guard（输入护栏）已完成安全检查。",
            payload=input_guard.model_dump(),
        )
    )
    if not input_guard.allowed:
        block_answer = build_guardrail_block_answer(input_guard)
        output_guard = guardrail_service.check_output(block_answer)
        guardrails.output = output_guard
        return ChatResponse(
            answer=output_guard.sanitized_text,
            plan=[],
            tool_results=[],
            trace=trace,
            needs_human_confirmation=False,
            guardrails=guardrails,
        )

    plan, llm_result = plan_for_message(message)
    memory_snapshot = memory_system.before_turn(
        message=message,
        user_id=user_id,
        session_id=session_id,
        plan=plan,
    )
    results: list[ToolResult] = []
    context: Dict[str, Any] = {}

    trace.append(
        TraceEvent(
            type="llm_planner",
            message="LLM Planner（大模型规划器）已完成任务规划。",
            payload=llm_result.model_dump(exclude={"raw_response"}),
        )
    )
    trace.append(
        TraceEvent(
            type="planner",
            message="Planner（规划器）已生成任务链表。",
            payload={"steps": [step.model_dump() for step in plan]},
        )
    )
    trace.append(
        TraceEvent(
            type="memory_router",
            message="Memory Router（记忆路由器）已判断是否查询长期记忆。",
            payload=memory_snapshot.router_decision.model_dump(),
        )
    )
    if memory_snapshot.long_term_memories:
        trace.append(
            TraceEvent(
                type="memory_read",
                message="已从 Vector DB（向量数据库）读取长期偏好/历史摘要。",
                payload={
                    "memories": [memory.model_dump() for memory in memory_snapshot.long_term_memories]
                },
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

    memory_snapshot = memory_system.after_turn(
        message=message,
        user_id=user_id,
        session_id=session_id,
        plan=plan,
        results=results,
        context=context,
        snapshot=memory_snapshot,
    )
    answer, needs_confirmation = compose_answer(message, context, results, memory_snapshot)
    action_guard = guardrail_service.check_action(
        context=context,
        needs_confirmation=needs_confirmation,
    )
    guardrails.action = action_guard
    trace.append(
        TraceEvent(
            type="action_guard",
            message="Action Guard（动作护栏）已判断是否需要二次确认。",
            payload=action_guard.model_dump(),
        )
    )
    output_guard = guardrail_service.check_output(answer)
    guardrails.output = output_guard
    trace.append(
        TraceEvent(
            type="output_guard",
            message="Output Guard（输出护栏）已完成最终回复脱敏检查。",
            payload=output_guard.model_dump(),
        )
    )
    return ChatResponse(
        answer=output_guard.sanitized_text,
        plan=plan,
        tool_results=results,
        trace=trace,
        needs_human_confirmation=bool(needs_confirmation or action_guard.requires_confirmation),
        llm=llm_result,
        memory=memory_snapshot,
        guardrails=guardrails,
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
    memory_snapshot: MemorySnapshot | None = None,
) -> tuple[str, bool]:
    if memory_snapshot and memory_snapshot.long_term_memories and any(word in message for word in ["寄", "地址"]):
        memory = memory_snapshot.long_term_memories[0]
        return (
            "Memory Router（记忆路由器）判断这个问题需要读取长期偏好。\n"
            f"检索到的长期记忆：{memory.text}\n\n"
            "涉及地址或寄送动作时，系统不能直接替用户执行，需要先让用户确认。"
        ), True

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


def build_guardrail_block_answer(guard_result) -> str:
    codes = {finding.code for finding in guard_result.findings}
    if "PRIVACY_LEAK_REQUEST" in codes:
        return (
            "这个请求涉及他人隐私信息，我不能帮你查询或泄露手机号、身份证、地址等内容。\n"
            "如果是查询你自己的订单，请提供本人账号下的订单号。"
        )
    if "OUT_OF_DOMAIN" in codes:
        return "我目前只处理电商客服相关问题，比如查订单、查物流、退货、退款和售后规则。"
    return "这个请求暂时不能处理，请换一种安全、明确的方式描述你的问题。"
