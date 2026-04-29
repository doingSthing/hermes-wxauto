from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WxResponse:
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    def __bool__(self) -> bool:
        return self.is_success

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }

    @classmethod
    def success(cls, message: str = "", data: dict[str, Any] | None = None) -> "WxResponse":
        return cls("success", message, data or {})

    @classmethod
    def failure(cls, message: str, data: dict[str, Any] | None = None) -> "WxResponse":
        return cls("failure", message, data or {})

    @classmethod
    def error(cls, message: str, data: dict[str, Any] | None = None) -> "WxResponse":
        return cls("error", message, data or {})
