from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class ProtocolState:
    id: str
    type: Literal["shutdown", "plan_approval"]
    teammate: str
    status: Literal["pending", "submitted", "approved", "rejected"] = "pending"
    payload: str = ""


@dataclass(slots=True)
class TeammateState:
    name: str
    role: str
    status: Literal["working", "idle", "shutdown", "error"] = "working"
    summary: str = ""
