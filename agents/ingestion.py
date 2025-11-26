from .base_agent import BaseAgent
import pandas as pd
from typing import Iterator

class IngestionAgent(BaseAgent):
    def __init__(self, name="ingestion", buffer_size=1000):
        super().__init__(name)
        self.buffer = []
        self.buffer_size = buffer_size

    def ingest_from_dataframe(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            self.buffer.append(row.to_dict())

    def get_batch(self, n=100):
        batch, self.buffer = self.buffer[:n], self.buffer[n:]
        return batch

    def start(self): pass
    def stop(self): pass
