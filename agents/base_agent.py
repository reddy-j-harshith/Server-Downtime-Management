# agents/base_agent.py
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def start(self):
        """Optional initialization hook"""
        pass

    @abstractmethod
    def stop(self):
        """Optional cleanup"""
        pass
