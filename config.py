from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, List, Literal, Optional, Union

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class SubredditConfig(BaseModel):
    name: str
    topics: List[str] = Field(default_factory=list)  # empty = no keyword filter
    pinned_post_ids: List[str] = Field(default_factory=list)  # always-fetch post IDs or full URLs


class RelativeDateRange(BaseModel):
    type: Literal["relative"] = "relative"
    value: str  # "past_week", "past_7_days", "past_month", etc.

    def to_cutoff(self) -> datetime:
        v = self.value.lower().replace(" ", "_")
        if v in ("past_day", "past_1_day"):
            return datetime.utcnow() - timedelta(days=1)
        if v == "past_week":
            return datetime.utcnow() - timedelta(weeks=1)
        if v == "past_month":
            return datetime.utcnow() - timedelta(days=30)
        if v == "past_year":
            return datetime.utcnow() - timedelta(days=365)
        if v.startswith("past_") and v.endswith("_days"):
            n = int(v.split("_")[1])
            return datetime.utcnow() - timedelta(days=n)
        raise ValueError(f"Unknown relative date range: {self.value}")

    def to_praw_time_filter(self) -> str:
        v = self.value.lower()
        if "year" in v:
            return "year"
        if "month" in v:
            return "month"
        if "week" in v:
            return "week"
        if v.startswith("past_") and v.endswith("_days"):
            try:
                n = int(v.split("_")[1])
                if n > 30:
                    return "year"   # wide net so top feed covers the full window
                if n > 7:
                    return "month"
                return "day"
            except (ValueError, IndexError):
                pass
        if "day" in v:
            return "day"
        return "month"


class AbsoluteDateRange(BaseModel):
    type: Literal["absolute"] = "absolute"
    start: datetime
    end: datetime

    def to_cutoff(self) -> datetime:
        return self.start

    def to_praw_time_filter(self) -> str:
        return "all"


DateRange = Annotated[
    Union[RelativeDateRange, AbsoluteDateRange],
    Field(discriminator="type"),
]


class RedditConfig(BaseModel):
    access_mode: Literal["json", "api"] = "json"
    subreddits: List[SubredditConfig]
    date_range: DateRange
    max_posts_per_topic: int = 10


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"


class EmailDeliveryConfig(BaseModel):
    type: Literal["email"]
    to: str
    subject: Optional[str] = None


class DocumentDeliveryConfig(BaseModel):
    type: Literal["document"]
    path: str = "./reports/"


DeliveryConfig = Annotated[
    Union[EmailDeliveryConfig, DocumentDeliveryConfig],
    Field(discriminator="type"),
]


class ProjectConfig(BaseModel):
    name: str
    reddit: RedditConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    delivery: List[DeliveryConfig]


class AppConfig(BaseModel):
    projects: List[ProjectConfig]


def load_config(path: str) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AppConfig.model_validate(data)
