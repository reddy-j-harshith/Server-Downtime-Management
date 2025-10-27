from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def make_agent_prompt(service: str) -> List[BaseMessage]:
	"""Return a ReAct-style system prompt guiding the agent for the given service (web or db)."""
	system = SystemMessage(
		content=(
			f"You are a Site Reliability Agent responsible for the {service} service.\n"
			"Use ReAct: think step-by-step, call tools when needed (metrics, restart, scale, notify),\n"
			"then conclude with a short JSON 'proposals' list of actions to take, where each proposal has: \n"
			"{{ 'service': str, 'action': str, 'rationale': str, 'priority': int (1-3) }}.\n"
			"Keep tool usage minimal and justified by metrics. If no action is needed, return proposals=[].\n"
		)
	)
	opener = HumanMessage(
		content=(
			"You will be given a log event and current context.\n"
			"1) Reason about likely cause.\n"
			"2) Inspect metrics (get_service_metrics) before acting.\n"
			"3) If needed, take actions (restart_service, scale_service, purge_cache, open_incident, send_notification).\n"
			"4) Finish with JSON proposals only at the end.\n"
		)
	)
	return [system, opener]


def build_messages(service: str, event: Any, extra_context: Dict[str, Any] | None = None) -> List[BaseMessage]:
	msgs = make_agent_prompt(service)
	ctx = {"event": event}
	if extra_context:
		ctx.update(extra_context)
	msgs.append(HumanMessage(content=f"Context:\n{ctx}"))
	return msgs

