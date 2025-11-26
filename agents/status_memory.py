from .base_agent import BaseAgent
from collections import defaultdict

class StatusMemoryAgent(BaseAgent):
    def __init__(self, name="status_memory"):
        super().__init__(name)
        self.node_status = defaultdict(dict)

    def update_status(self, node_id, status):
        self.node_status[node_id].update(status)

    def get_node_context(self, node_id):
        return self.node_status.get(node_id, {})

    def start(self): pass
    def stop(self): pass
