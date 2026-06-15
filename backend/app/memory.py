from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from backend.app.models import (
    BusinessFlowState,
    MemoryDecision,
    MemoryRecord,
    MemorySnapshot,
    PlanStep,
    SessionState,
    ToolResult,
)
from backend.app.planner import extract_order_id


CN_TZ = timezone(timedelta(hours=8))
RUNTIME_DIR = Path(__file__).resolve().parents[2] / ".runtime"
BUSINESS_FLOW_DB = RUNTIME_DIR / "business_flows.sqlite"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def infer_intent(plan: list[PlanStep]) -> str:
    tool_names = {step.tool_name for step in plan}
    if "check_eligibility" in tool_names:
        return "return_order"
    if "query_order" in tool_names:
        return "query_order"
    if "retrieve_policy" in tool_names:
        return "knowledge_search"
    return "unknown"


class RedisSessionStore:
    """MVP local implementation of Redis（缓存数据库）session state."""

    def __init__(self, ttl_seconds: int = 24 * 60 * 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._states: Dict[str, SessionState] = {}
        self._expires_at: Dict[str, datetime] = {}

    def get(self, session_id: str, user_id: str) -> SessionState:
        self._drop_expired(session_id)
        state = self._states.get(session_id)
        if state:
            return state
        return SessionState(user_id=user_id, session_id=session_id, updated_at=now_iso())

    def update(
        self,
        session_id: str,
        user_id: str,
        active_intent: str,
        slots: Dict[str, Any],
        last_message: str,
    ) -> SessionState:
        current = self.get(session_id=session_id, user_id=user_id)
        merged_slots = {**current.slots, **slots}
        state = SessionState(
            user_id=user_id,
            session_id=session_id,
            active_intent=active_intent,
            slots=merged_slots,
            turn_count=current.turn_count + 1,
            last_message=last_message,
            updated_at=now_iso(),
        )
        self._states[session_id] = state
        self._expires_at[session_id] = datetime.now(CN_TZ) + timedelta(seconds=self.ttl_seconds)
        return state

    def _drop_expired(self, session_id: str) -> None:
        expires_at = self._expires_at.get(session_id)
        if expires_at and expires_at < datetime.now(CN_TZ):
            self._states.pop(session_id, None)
            self._expires_at.pop(session_id, None)


class BusinessFlowStore:
    """MVP local relational store. Production can swap this adapter to MySQL（关系型数据库）."""

    def __init__(self, db_path: Path = BUSINESS_FLOW_DB) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS business_flows (
                    flow_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    flow_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    required_slots TEXT NOT NULL,
                    collected_slots TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_business_flows_user_status "
                "ON business_flows(user_id, status, updated_at)"
            )

    def get_open_flow(self, user_id: str) -> Optional[BusinessFlowState]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT flow_id, user_id, flow_type, status, required_slots,
                       collected_slots, summary, updated_at
                FROM business_flows
                WHERE user_id = ? AND status = 'open'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return BusinessFlowState(
            flow_id=row[0],
            user_id=row[1],
            flow_type=row[2],
            status=row[3],
            required_slots=json.loads(row[4]),
            collected_slots=json.loads(row[5]),
            summary=row[6],
            updated_at=row[7],
        )

    def upsert_open_flow(
        self,
        user_id: str,
        flow_type: str,
        required_slots: list[str],
        collected_slots: Dict[str, Any],
        summary: str,
    ) -> BusinessFlowState:
        existing = self.get_open_flow(user_id=user_id)
        flow_id = existing.flow_id if existing and existing.flow_type == flow_type else str(uuid4())
        state = BusinessFlowState(
            flow_id=flow_id,
            user_id=user_id,
            flow_type=flow_type,
            status="open",
            required_slots=required_slots,
            collected_slots=collected_slots,
            summary=summary,
            updated_at=now_iso(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO business_flows (
                    flow_id, user_id, flow_type, status, required_slots,
                    collected_slots, summary, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(flow_id) DO UPDATE SET
                    status = excluded.status,
                    required_slots = excluded.required_slots,
                    collected_slots = excluded.collected_slots,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (
                    state.flow_id,
                    state.user_id,
                    state.flow_type,
                    state.status,
                    json.dumps(state.required_slots, ensure_ascii=False),
                    json.dumps(state.collected_slots, ensure_ascii=False),
                    state.summary,
                    state.updated_at,
                ),
            )
        return state


class VectorMemoryStore:
    """Small Vector DB（向量数据库）style store for preferences and history summaries."""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []
        self._seed_demo_records()

    def search(self, user_id: str, query: str, top_k: int = 3) -> list[MemoryRecord]:
        scored: list[MemoryRecord] = []
        for record in self._records:
            if record.user_id != user_id:
                continue
            score = score_text(query=query, text=record.text)
            if score <= 0:
                continue
            item = record.model_copy(deep=True)
            item.score = round(score, 3)
            scored.append(item)
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    def add(self, user_id: str, kind: str, text: str, metadata: Dict[str, Any]) -> MemoryRecord:
        record = MemoryRecord(
            id=str(uuid4()),
            user_id=user_id,
            kind=kind,
            text=text,
            metadata=metadata,
        )
        self._records.append(record)
        return record

    def _seed_demo_records(self) -> None:
        if self._records:
            return
        self._records.extend(
            [
                MemoryRecord(
                    id="demo-pref-address-1001",
                    user_id="1001",
                    kind="preference",
                    text=(
                        "用户确认过常用收货偏好：当用户说“给我寄过来”或“寄到常用地址”时，"
                        "优先提示使用演示常用收货地址：杭州市演示区星河路 88 号。"
                    ),
                    metadata={"source": "seed", "memory_type": "shipping_preference"},
                ),
                MemoryRecord(
                    id="demo-summary-return-1001",
                    user_id="1001",
                    kind="summary",
                    text=(
                        "历史摘要：用户最近多次咨询手机订单售后，偏好先给明确结论，"
                        "再解释七天无理由规则和下一步操作。"
                    ),
                    metadata={"source": "seed", "memory_type": "conversation_summary"},
                ),
            ]
        )


class MemoryRouter:
    """Decides whether to query long-term Memory（长期记忆）."""

    LONG_TERM_SIGNALS = {
        "上次",
        "之前",
        "历史",
        "继续",
        "刚刚",
        "偏好",
        "习惯",
        "常用",
        "地址",
        "寄过来",
        "寄到",
        "送到",
        "默认",
        "我平时",
    }

    def decide(self, message: str, plan: list[PlanStep]) -> MemoryDecision:
        active_intent = infer_intent(plan)
        signals = [signal for signal in self.LONG_TERM_SIGNALS if signal in message]
        if signals:
            return MemoryDecision(
                should_query_long_term=True,
                reason=f"用户表达包含长期偏好或历史承接信号：{', '.join(signals)}。",
                target_store="vector_db",
                query=message,
                signals=signals,
            )
        if active_intent == "return_order" and any(word in message for word in ["这个", "那个", "它"]):
            return MemoryDecision(
                should_query_long_term=True,
                reason="售后流程中出现指代词，需要尝试读取历史摘要帮助消解上下文。",
                target_store="vector_db",
                query=message,
                signals=["指代词", active_intent],
            )
        return MemoryDecision(
            should_query_long_term=False,
            reason="当前问题可由当前会话状态和业务工具处理，不查询长期记忆。",
            target_store="none",
            query=message,
        )


class MemorySystem:
    def __init__(self) -> None:
        self.sessions = RedisSessionStore()
        self.business_flows = BusinessFlowStore()
        self.vector_memories = VectorMemoryStore()
        self.router = MemoryRouter()

    def before_turn(
        self,
        message: str,
        user_id: str,
        session_id: str,
        plan: list[PlanStep],
    ) -> MemorySnapshot:
        session_state = self.sessions.get(session_id=session_id, user_id=user_id)
        active_flow = self.business_flows.get_open_flow(user_id=user_id)
        decision = self.router.decide(message=message, plan=plan)
        memories = (
            self.vector_memories.search(user_id=user_id, query=decision.query)
            if decision.should_query_long_term
            else []
        )
        return MemorySnapshot(
            router_decision=decision,
            session_state=session_state,
            active_flow=active_flow,
            long_term_memories=memories,
        )

    def after_turn(
        self,
        message: str,
        user_id: str,
        session_id: str,
        plan: list[PlanStep],
        results: list[ToolResult],
        context: Dict[str, Any],
        snapshot: MemorySnapshot,
    ) -> MemorySnapshot:
        active_intent = infer_intent(plan)
        slots = collect_slots(message=message, context=context)
        snapshot.session_state = self.sessions.update(
            session_id=session_id,
            user_id=user_id,
            active_intent=active_intent,
            slots=slots,
            last_message=message,
        )
        maybe_flow = self._persist_business_flow(
            user_id=user_id,
            active_intent=active_intent,
            context=context,
        )
        if maybe_flow:
            snapshot.active_flow = maybe_flow
        self._maybe_write_long_term_preference(message=message, user_id=user_id)
        return snapshot

    def overview(self, user_id: str, session_id: str) -> MemorySnapshot:
        session_state = self.sessions.get(session_id=session_id, user_id=user_id)
        active_flow = self.business_flows.get_open_flow(user_id=user_id)
        decision = MemoryDecision(
            should_query_long_term=False,
            reason="只查看当前记忆状态，不执行长期记忆检索。",
            target_store="none",
        )
        return MemorySnapshot(
            router_decision=decision,
            session_state=session_state,
            active_flow=active_flow,
            long_term_memories=self.vector_memories.search(user_id=user_id, query="偏好 历史 售后 地址"),
        )

    def _persist_business_flow(
        self,
        user_id: str,
        active_intent: str,
        context: Dict[str, Any],
    ) -> Optional[BusinessFlowState]:
        if active_intent != "return_order":
            return None
        eligibility = context.get("eligibility") or {}
        order = context.get("order") or {}
        should_keep_open = bool(eligibility.get("needs_human_confirmation") or context.get("assumed_order"))
        if not should_keep_open:
            return None
        return self.business_flows.upsert_open_flow(
            user_id=user_id,
            flow_type="return_order",
            required_slots=["order_id", "user_confirmation"],
            collected_slots={
                "order_id": order.get("order_id"),
                "product_name": order.get("product_name"),
                "eligibility": eligibility.get("eligible"),
            },
            summary="用户正在申请退货，已完成订单查询和资格校验，等待用户确认。",
        )

    def _maybe_write_long_term_preference(self, message: str, user_id: str) -> None:
        if "记住" not in message and "以后" not in message:
            return
        if not any(word in message for word in ["地址", "寄", "偏好", "习惯"]):
            return
        self.vector_memories.add(
            user_id=user_id,
            kind="preference",
            text=f"用户显式表达长期偏好：{message}",
            metadata={"source": "chat", "memory_type": "explicit_preference", "created_at": now_iso()},
        )


def collect_slots(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    order_id = extract_order_id(message)
    if order_id:
        slots["order_id"] = order_id
    order = context.get("order") or {}
    if order.get("order_id"):
        slots["last_order_id"] = order["order_id"]
    if order.get("category"):
        slots["last_category"] = order["category"]
    eligibility = context.get("eligibility") or {}
    if "eligible" in eligibility:
        slots["last_eligibility"] = eligibility["eligible"]
    return slots


def score_text(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens or not text_tokens:
        return 0
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)


def tokenize(text: str) -> Iterable[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    normalized = re.sub(r"[，。！？、；：,.!?;:（）()“”\"'`]", "", normalized)
    for word in ["寄过来", "常用地址", "售后", "退货", "七天无理由", "手机", "偏好", "历史摘要"]:
        if word in normalized:
            yield word
    for char in normalized:
        if char.strip():
            yield char


memory_system = MemorySystem()
