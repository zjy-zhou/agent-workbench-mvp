from __future__ import annotations

import re
from typing import Optional

from backend.app.llm import llm_planner
from backend.app.models import LLMPlannerResult, PlanStep


ORDER_ID_PATTERN = re.compile(r"\b(20\d{10})\b")


def extract_order_id(message: str) -> Optional[str]:
    match = ORDER_ID_PATTERN.search(message)
    return match.group(1) if match else None


def rule_based_plan_for_message(message: str) -> list[PlanStep]:
    wants_return = any(word in message for word in ["退", "售后", "退款", "签收", "换货"])
    wants_order = any(word in message for word in ["订单", "查一下", "查询"])

    if wants_return:
        return [
            PlanStep(
                id="step_query_order",
                tool_name="query_order",
                title="查询订单",
                reason="售后判断需要先获取订单状态、商品品类和签收时间。",
            ),
            PlanStep(
                id="step_retrieve_policy",
                tool_name="retrieve_policy",
                title="检索售后规则",
                reason="需要根据商品品类找到对应售后规则。",
                depends_on=["step_query_order"],
            ),
            PlanStep(
                id="step_check_eligibility",
                tool_name="check_eligibility",
                title="校验售后资格",
                reason="结合订单状态和规则判断是否可退。",
                depends_on=["step_query_order", "step_retrieve_policy"],
            ),
        ]

    if wants_order or extract_order_id(message):
        return [
            PlanStep(
                id="step_query_order",
                tool_name="query_order",
                title="查询订单",
                reason="用户希望查看订单详情。",
            )
        ]

    return [
        PlanStep(
            id="step_retrieve_policy",
            tool_name="retrieve_policy",
            title="检索规则",
            reason="未识别到明确订单流程，先尝试检索电商规则知识。",
        )
    ]


def plan_for_message(message: str) -> tuple[list[PlanStep], LLMPlannerResult]:
    return llm_planner.plan(
        message=message,
        fallback_planner=rule_based_plan_for_message,
    )
