from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from backend.app.models import LLMPlannerResult, PlanStep

import certifi


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
ALLOWED_TOOLS = {"query_order", "retrieve_policy", "check_eligibility"}


def load_local_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class QwenClient:
    def __init__(self) -> None:
        load_local_env()
        self.model = os.getenv("QWEN_MODEL", "qwen-plus")
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY", "")
        self.endpoint = os.getenv("QWEN_BASE_URL", QWEN_ENDPOINT)
        self.timeout_seconds = float(os.getenv("QWEN_TIMEOUT_SECONDS", "8"))
        self.enabled = os.getenv("QWEN_ENABLED", "true").lower() != "false" and bool(self.api_key)

    def chat_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        if not self.enabled:
            raise RuntimeError("Qwen client is disabled or DASHSCOPE_API_KEY is missing")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Qwen API HTTP {exc.code}: {body[:300]}") from exc

        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        return parse_json_object(content), data.get("usage") or {}, content

    def status(self) -> dict[str, Any]:
        return {
            "provider": "qwen",
            "model": self.model,
            "enabled": self.enabled,
            "has_api_key": bool(self.api_key),
            "endpoint": self.endpoint,
        }


class LLMPlanner:
    def __init__(self, client: QwenClient | None = None) -> None:
        self.client = client or QwenClient()

    def plan(
        self,
        message: str,
        fallback_planner: Callable[[str], list[PlanStep]],
    ) -> tuple[list[PlanStep], LLMPlannerResult]:
        result = LLMPlannerResult(
            enabled=self.client.enabled,
            provider="qwen",
            model=self.client.model,
        )
        if not self.client.enabled:
            result.error = "DASHSCOPE_API_KEY is missing or QWEN_ENABLED=false"
            return fallback_planner(message), result

        try:
            payload, usage, raw_response = self.client.chat_json(
                system_prompt=build_system_prompt(),
                user_prompt=build_user_prompt(message),
            )
            steps = build_plan_steps(payload)
            if not steps:
                raise ValueError("LLM returned no executable steps")
            result.used = True
            result.fallback_used = False
            result.intent = str(payload.get("intent") or "unknown")
            result.confidence = float(payload.get("confidence") or 0)
            result.reason = str(payload.get("reason") or "")
            result.raw_response = raw_response
            result.usage = usage
            return steps, result
        except Exception as exc:  # noqa: BLE001 - fallback is intentional in the planner.
            result.error = str(exc)
            result.fallback_used = True
            return fallback_planner(message), result


def build_system_prompt() -> str:
    return """
你是电商智能客服 Agent（智能体）的 Planner（规划器）。
你的任务是把用户自然语言规划成 Tool（工具）任务链表。

只能使用以下工具：
1. query_order（查订单）：查询订单状态、商品品类、签收天数。
2. retrieve_policy（检索规则）：检索售后、退货、退款、物流等规则。
3. check_eligibility（校验资格）：结合订单和规则判断是否满足售后资格。

规划规则：
- 查订单/订单详情：只调用 query_order。
- 售后/退货/退款/签收几天还能退：依次调用 query_order -> retrieve_policy -> check_eligibility。
- 只问规则/政策/七天无理由：只调用 retrieve_policy。
- 地址、寄送、长期偏好这类问题，可以调用 retrieve_policy，长期记忆由 Memory Router（记忆路由器）处理。
- 不要生成不存在的工具。
- 只输出 JSON，不要输出 Markdown。

JSON schema:
{
  "intent": "query_order | return_order | policy_search | shipping_preference | unsupported",
  "confidence": 0.0,
  "reason": "一句话解释为什么这么规划",
  "steps": [
    {
      "tool_name": "query_order",
      "title": "查询订单",
      "reason": "为什么需要这个工具",
      "depends_on": []
    }
  ]
}
""".strip()


def build_user_prompt(message: str) -> str:
    return f"用户问题：{message}"


def parse_json_object(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    if not content.startswith("{"):
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise ValueError("Qwen response does not contain a JSON object")
        content = match.group(0)
    return json.loads(content)


def build_plan_steps(payload: dict[str, Any]) -> list[PlanStep]:
    steps: list[PlanStep] = []
    known_step_ids: dict[str, str] = {}
    for index, item in enumerate(payload.get("steps") or [], start=1):
        tool_name = str(item.get("tool_name") or "")
        if tool_name not in ALLOWED_TOOLS:
            continue
        step_id = f"step_{tool_name}_{index}"
        depends_on = [
            known_step_ids[dep]
            for dep in item.get("depends_on") or []
            if dep in known_step_ids
        ]
        known_step_ids[tool_name] = step_id
        steps.append(
            PlanStep(
                id=step_id,
                tool_name=tool_name,
                title=str(item.get("title") or default_title(tool_name)),
                reason=str(item.get("reason") or "LLM Planner（大模型规划器）认为需要调用该工具。"),
                depends_on=depends_on,
            )
        )
    return steps


def default_title(tool_name: str) -> str:
    return {
        "query_order": "查询订单",
        "retrieve_policy": "检索规则",
        "check_eligibility": "校验资格",
    }.get(tool_name, tool_name)


qwen_client = QwenClient()
llm_planner = LLMPlanner(qwen_client)
