"""Chain of Responsibility for tender ingestion.

Each handler either processes the batch or forwards it to the next handler
in the chain.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseHandler(ABC):
    """Base handler in the ingestion chain of responsibility."""

    def __init__(self, next_handler: "BaseHandler | None" = None) -> None:
        self._next_handler = next_handler

    def set_next(self, next_handler: "BaseHandler") -> "BaseHandler":
        self._next_handler = next_handler
        return next_handler

    @abstractmethod
    def handle(self, batch: Any) -> Any:
        """Process the batch, or delegate to the next handler."""
        if(self._next_handler):
            return self._next_handler.handle(batch)
        return batch
