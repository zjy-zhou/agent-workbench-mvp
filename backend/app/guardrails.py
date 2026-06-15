from __future__ import annotations

import re
from typing import Any, Dict

from backend.app.models import GuardrailFinding, GuardrailResult


PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
ORDER_PATTERN = re.compile(r"(?<!\d)20\d{10}(?!\d)")

PRIVACY_TERMS = ["别人", "他人", "其他用户", "手机号", "身份证", "地址", "收货人"]
LEAK_TERMS = ["泄露", "给我看", "查一下别人", "查别人", "导出", "全部用户"]
OUT_OF_DOMAIN_TERMS = ["天气", "股票", "彩票", "医疗诊断", "法律意见", "写论文"]
ABUSE_TERMS = ["傻逼", "垃圾客服", "滚", "废物"]


class GuardrailService:
    def check_input(self, message: str, user_id: str) -> GuardrailResult:
        findings: list[GuardrailFinding] = []

        if any(term in message for term in PRIVACY_TERMS) and any(term in message for term in LEAK_TERMS):
            findings.append(
                GuardrailFinding(
                    code="PRIVACY_LEAK_REQUEST",
                    severity="block",
                    message="用户请求获取他人隐私信息，必须拦截。",
                    evidence=message,
                )
            )

        if any(term in message for term in OUT_OF_DOMAIN_TERMS):
            findings.append(
                GuardrailFinding(
                    code="OUT_OF_DOMAIN",
                    severity="block",
                    message="问题超出电商客服 Agent（智能体）的服务范围。",
                    evidence=message,
                )
            )

        if any(term in message for term in ABUSE_TERMS):
            findings.append(
                GuardrailFinding(
                    code="ABUSE_LANGUAGE",
                    severity="warning",
                    message="用户表达包含不文明内容，回复时保持克制并引导回业务问题。",
                    evidence="命中不文明表达",
                )
            )

        sanitized = redact_sensitive_text(message)
        if sanitized != message:
            findings.append(
                GuardrailFinding(
                    code="INPUT_PII_REDACTED",
                    severity="info",
                    message="输入中包含疑似敏感信息，已在护栏结果中脱敏展示。",
                    evidence=sanitized,
                )
            )

        allowed = not any(finding.severity == "block" for finding in findings)
        return GuardrailResult(
            stage="input",
            allowed=allowed,
            findings=findings,
            sanitized_text=sanitized,
        )

    def check_action(
        self,
        context: Dict[str, Any],
        needs_confirmation: bool,
    ) -> GuardrailResult:
        findings: list[GuardrailFinding] = []
        eligibility = context.get("eligibility") or {}
        suggested_action = eligibility.get("suggested_next_action")

        requires_confirmation = bool(needs_confirmation)
        confirmation_reason = ""
        if suggested_action == "confirm_return" and eligibility.get("eligible"):
            requires_confirmation = True
            confirmation_reason = "退货申请属于会改变业务状态的动作，执行前必须让用户二次确认。"
            findings.append(
                GuardrailFinding(
                    code="CONFIRM_BEFORE_RETURN",
                    severity="warning",
                    message=confirmation_reason,
                    evidence="suggested_next_action=confirm_return",
                )
            )

        if context.get("assumed_order"):
            requires_confirmation = True
            confirmation_reason = "系统使用了推断订单，执行售后动作前必须确认订单归属。"
            findings.append(
                GuardrailFinding(
                    code="CONFIRM_ASSUMED_ORDER",
                    severity="warning",
                    message=confirmation_reason,
                    evidence="assumed_order=true",
                )
            )

        return GuardrailResult(
            stage="action",
            allowed=True,
            findings=findings,
            sanitized_text="",
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
        )

    def check_output(self, answer: str) -> GuardrailResult:
        sanitized = redact_sensitive_text(answer)
        findings: list[GuardrailFinding] = []
        if sanitized != answer:
            findings.append(
                GuardrailFinding(
                    code="OUTPUT_PII_REDACTED",
                    severity="warning",
                    message="输出中出现疑似敏感信息，已脱敏后再返回给前端。",
                    evidence=sanitized,
                )
            )
        return GuardrailResult(
            stage="output",
            allowed=True,
            findings=findings,
            sanitized_text=sanitized,
        )

    def policies(self) -> list[dict]:
        return [
            {
                "name": "privacy_request_block",
                "description": "拦截查询或泄露他人手机号、身份证、地址等隐私信息的请求。",
                "stage": "input",
            },
            {
                "name": "domain_guard",
                "description": "拦截天气、股票、医疗诊断、法律意见等非电商客服问题。",
                "stage": "input",
            },
            {
                "name": "dangerous_action_confirmation",
                "description": "退货、取消订单、修改地址等会改变业务状态的动作必须二次确认。",
                "stage": "action",
            },
            {
                "name": "output_pii_redaction",
                "description": "最终回复返回前，对手机号、身份证号、订单号做脱敏展示。",
                "stage": "output",
            },
        ]


def redact_sensitive_text(text: str) -> str:
    text = PHONE_PATTERN.sub(lambda match: mask_middle(match.group(0), keep_start=3, keep_end=4), text)
    text = ID_CARD_PATTERN.sub(lambda match: mask_middle(match.group(0), keep_start=4, keep_end=4), text)
    text = ORDER_PATTERN.sub(lambda match: mask_middle(match.group(0), keep_start=4, keep_end=3), text)
    return text


def mask_middle(value: str, keep_start: int, keep_end: int) -> str:
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return f"{value[:keep_start]}{'*' * (len(value) - keep_start - keep_end)}{value[-keep_end:]}"


guardrail_service = GuardrailService()
