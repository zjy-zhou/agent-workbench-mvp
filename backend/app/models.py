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


class PermissionPolicy(BaseModel):
    scope: str
    allowed_roles: List[str] = Field(default_factory=lambda: ["customer"])
    require_owner_check: bool = False
    sensitive_fields: List[str] = Field(default_factory=list)


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff_ms: int = Field(default=0, ge=0)
    retryable_errors: List[str] = Field(default_factory=lambda: ["TOOL_TIMEOUT", "TEMPORARY_ERROR"])


class TimeoutPolicy(BaseModel):
    timeout_ms: int = Field(default=3000, ge=100, le=30000)


class AuditLogPolicy(BaseModel):
    enabled: bool = True
    event_name: str
    include_input: bool = True
    include_output: bool = False
    redact_fields: List[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    permission: PermissionPolicy
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    audit_log: AuditLogPolicy


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    input: Dict[str, Any]
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    attempts: int = 1
    duration_ms: int = 0
    audit_log: Optional[Dict[str, Any]] = None


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
