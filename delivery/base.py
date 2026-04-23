from abc import ABC, abstractmethod
from analyzer import ResearchReport


class BaseDelivery(ABC):
    @abstractmethod
    def deliver(self, report: ResearchReport) -> None: ...
