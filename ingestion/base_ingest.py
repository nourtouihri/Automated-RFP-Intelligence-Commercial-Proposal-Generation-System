from abc import ABC, abstractmethod
from .base_handler import BaseHandler
from typing import Any

class BaseIngest(ABC):
    def __init__(self,handler:"BaseHandler", api_key:str="")->None:
        self._handler = handler
        self._api_key = api_key

    @abstractmethod
    def ingest(self, page: int = 1)->Any:
        """Ingests Data"""
        ...

    def run(self, page: int = 1)-> Any:
        """Runs the chain of responsibility"""
        batch = self.ingest(page)
        return self._handler.handle(batch)
