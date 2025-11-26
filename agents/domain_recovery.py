from .base_agent import BaseAgent

class DomainRecoveryAgent(BaseAgent):
    def execute_action(self, action: dict):
        # dummy execution
        return {"action": action, "result": "ok"}

    def execute_plan(self, plan: dict):
        results = []
        for a in plan["actions"]:
            results.append(self.execute_action(a))
        return {"success": True, "results": results}
