from .base_agent import BaseAgent
import networkx as nx

class DependencyGraphAgent(BaseAgent):
    def __init__(self, name="dep_graph"):
        super().__init__(name)
        self.G = nx.DiGraph()

    def update_from_event(self, parsed_event: dict):
        # populate nodes & edges from topology info in event
        n = parsed_event.get("node_id")
        self.G.add_node(n, **parsed_event.get("meta", {}))

    def find_root_cause_candidates(self, failed_nodes):
        # naive: return upstream nodes with highest in_degree
        candidates = []
        for node in failed_nodes:
            preds = list(self.G.predecessors(node))
            candidates.extend(preds)
        return list(set(candidates))

    def start(self): pass
    def stop(self): pass
