from datetime import datetime
from pathlib import Path

from analyzer import ResearchReport
from config import DocumentDeliveryConfig
from delivery.base import BaseDelivery


class DocumentDelivery(BaseDelivery):
    def __init__(self, config: DocumentDeliveryConfig):
        self.path = Path(config.path)

    def deliver(self, report: ResearchReport) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        filename = f"{report.project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = self.path / filename
        filepath.write_text(report.to_markdown(), encoding="utf-8")
        print(f"Report saved: {filepath}")
