from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_id: str = "1001"
    session_id: str = "demo-session"


class PlanStep(BaseModel):
    id: str
    tool_name: str
    title: str
    reason: str
    status: Literal["pending", "running", "success", "failed"] = "pending"
    depends_on: List[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    permission: str = "read"
    timeout_ms: int = 3000
    retry: int = 1


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    input: Dict[str, Any]
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class TraceEvent(BaseModel):
    type: str
    message: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    answer: str
    plan: List[PlanStep]
    tool_results: List[ToolResult]
    trace: List[TraceEvent]
    needs_human_confirmation: bool = False

