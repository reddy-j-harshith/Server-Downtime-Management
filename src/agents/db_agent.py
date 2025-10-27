from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import BaseMessage

from src.agents.base import build_messages


def db_agent_messages(event: Any, extra_context: Dict[str, Any] | None = None) -> List[BaseMessage]:
	return build_messages("db", event, extra_context)

