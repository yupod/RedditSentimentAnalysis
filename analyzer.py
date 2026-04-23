from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import List

import anthropic

from config import LLMConfig, ProjectConfig
from reddit_client import RedditPost


@dataclass
class TopicSummary:
    subreddit: str
    topic: str
    summary: str
    post_count: int
    sentiment: str  # positive | negative | neutral | mixed


@dataclass
class ResearchReport:
    project_name: str
    date_range: str
    summaries: List[TopicSummary]

    def to_markdown(self) -> str:
        lines = [
            f"# Research Report: {self.project_name}",
            f"**Date Range:** {self.date_range}",
            f"**Generated:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for s in self.summaries:
            lines += [
                f"## r/{s.subreddit} — {s.topic}",
                f"**Sentiment:** {s.sentiment} | **Posts analyzed:** {s.post_count}",
                "",
                s.summary,
                "",
            ]
        return "\n".join(lines)


class Analyzer:
    def __init__(self, llm_config: LLMConfig):
        self.config = llm_config
        if llm_config.provider == "anthropic":
            self.client = anthropic.Anthropic()
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_config.provider}")

    def analyze(self, project: ProjectConfig, posts: List[RedditPost]) -> ResearchReport:
        # Deduplicate posts across topics before summarizing per subreddit
        seen = set()
        unique = []
        for p in posts:
            if p.url not in seen:
                seen.add(p.url)
                unique.append(p)

        summaries = []
        key = lambda p: p.subreddit
        for subreddit, group in groupby(sorted(unique, key=key), key=key):
            summaries.append(self._summarize_group(subreddit, list(group)))

        date_range_str = getattr(project.reddit.date_range, "value", "custom range")
        return ResearchReport(
            project_name=project.name,
            date_range=date_range_str,
            summaries=summaries,
        )

    def _summarize_group(self, subreddit: str, posts: List[RedditPost]) -> TopicSummary:
        if not posts:
            return TopicSummary(subreddit=subreddit, topic="products", summary="No posts found.", post_count=0, sentiment="neutral")

        posts_text = ""
        for i, p in enumerate(posts, 1):
            posts_text += f"\n---\nPost {i}: {p.title}\nScore: {p.score} | Comments: {p.num_comments}\n"
            if p.body:
                posts_text += f"Body: {p.body[:300]}\n"
            if p.top_comments:
                posts_text += "Top comments:\n" + "\n".join(f"  - {c[:200]}" for c in p.top_comments[:3]) + "\n"

        prompt = (
            f"You are analyzing Reddit posts from r/{subreddit} to find new cannabis products people are excited about.\n\n"
            f"Posts (past month):\n{posts_text}\n\n"
            "Extract the highlights. Respond in this exact format:\n\n"
            "PRODUCTS:\n"
            "- <Product Name> by <Brand/Cultivator>: <why people like it, 1-2 sentences>\n"
            "(list up to 10 products, only include ones with positive mentions)\n\n"
            "SUMMARY: <2-3 sentence overall summary of what's trending and what people are loving>\n"
            "SENTIMENT: <positive|negative|neutral|mixed>"
        )

        message = self.client.messages.create(
            model=self.config.model,
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": "You are a cannabis product research analyst. Extract specific product names, brands, and what people like about them from Reddit posts. Be specific and concise.",
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        response = message.content[0].text
        summary_line = next((l for l in response.splitlines() if l.startswith("SUMMARY:")), "SUMMARY: No summary available.")
        sentiment_line = next((l for l in response.splitlines() if l.startswith("SENTIMENT:")), "SENTIMENT: neutral")

        summary = summary_line.replace("SUMMARY:", "").strip()
        sentiment = sentiment_line.replace("SENTIMENT:", "").strip().lower()
        if sentiment not in ("positive", "negative", "neutral", "mixed"):
            sentiment = "neutral"

        # Include full product highlights in summary
        products_start = response.find("PRODUCTS:")
        summary_start = response.find("SUMMARY:")
        if products_start != -1 and summary_start != -1:
            products_section = response[products_start:summary_start].strip()
            summary = f"{products_section}\n\n{summary}"

        return TopicSummary(subreddit=subreddit, topic="new products", summary=summary, post_count=len(posts), sentiment=sentiment)
