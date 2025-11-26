from .base_agent import BaseAgent

class ReActPlanner(BaseAgent):
    def __init__(self, dep_graph_agent, status_memory_agent, name="react_planner"):
        super().__init__(name)
        self.dep_graph = dep_graph_agent
        self.status_memory = status_memory_agent

    def plan_recovery(self, classified_fault: dict):
        # produce simple plan
        node = classified_fault.get("node_id")
        plan = {
            "plan_id": f"plan_{node}",
            "actions": [{"action_type": "restart", "target": node}],
            "confidence": 0.8
        }
        return plan

    def execute_plan(self, plan: dict):
        # hand off to domain recovery in orchestrator
        return {"success": True, "executed": plan}
