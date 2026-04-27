from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from typing import List

import anthropic

from config import LLMConfig, ProjectConfig
from reddit_client import RedditPost

_JSON_BLOCK_RE = re.compile(
    r"PRODUCTS_JSON:\s*(\[.*?\])\s*(?=SUMMARY:)", re.DOTALL
)


@dataclass
class ProductMention:
    name: str
    brand: str
    kind: str        # flower, pre-roll, concentrate, edible, vape, tincture, topical, other
    note: str        # why people like it
    source_url: str  # Reddit thread URL
    source_date: datetime


@dataclass
class TopicSummary:
    subreddit: str
    topic: str
    summary: str
    post_count: int
    sentiment: str  # positive | negative | neutral | mixed
    product_mentions: List[ProductMention] = field(default_factory=list)


@dataclass
class ResearchReport:
    project_name: str
    date_range: str
    summaries: List[TopicSummary]
    match_table_html: str = ""   # populated by runner after dispensary matching

    @property
    def all_mentions(self) -> List[ProductMention]:
        return [m for s in self.summaries for m in s.product_mentions]

    def to_markdown(self) -> str:
        lines = [
            f"# Research Report: {self.project_name}",
            f"**Date Range:** {self.date_range}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
        seen: set = set()
        unique: List[RedditPost] = []
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
            return TopicSummary(
                subreddit=subreddit, topic="products",
                summary="No posts found.", post_count=0, sentiment="neutral",
            )

        posts_text = ""
        for i, p in enumerate(posts, 1):
            posts_text += (
                f"\n---\n[Post {i}] {p.created_utc.strftime('%Y-%m-%d')} | "
                f"r/{subreddit}\n"
                f"Title: {p.title}\n"
                f"Score: {p.score} | Comments: {p.num_comments}\n"
            )
            if p.body:
                posts_text += f"Body: {p.body[:800]}\n"
            if p.top_comments:
                posts_text += "Top comments:\n"
                posts_text += "\n".join(f"  - {c[:500]}" for c in p.top_comments[:7])
                posts_text += "\n"

        prompt = (
            f"You are analyzing Reddit posts from r/{subreddit} to identify "
            "cannabis products that people are enthusiastically recommending or praising.\n\n"
            f"Posts (each labeled [Post N] with date):\n{posts_text}\n\n"
            "Respond in this EXACT format (no extra text before PRODUCTS_JSON):\n\n"
            "PRODUCTS_JSON:\n"
            "[\n"
            '  {"name": "Product Name", "brand": "Brand Name", '
            '"type": "flower|pre-roll|concentrate|vaporizers|edible|tincture|topical|other", '
            '"note": "4-6 sentences with rich detail on WHY people love this product: '
            "(1) specific effects users describe using their exact words — e.g. 'euphoric', 'heavy body buzz', 'clear-headed and functional'; "
            "(2) flavor and aroma profile with specific descriptors; "
            "(3) potency, quality, and consistency feedback; "
            "(4) value for money or price-to-quality ratio if mentioned; "
            "(5) how it compares to other products if users make comparisons; "
            'include at least one direct user quote in quotes if available", '
            '"post_num": 1},\n'
            "  ...\n"
            "]\n\n"
            "STRICT RULES for PRODUCTS_JSON:\n"
            "- ONLY include products that receive clearly positive reactions "
            "(praised, recommended, hyped, or highly rated by commenters).\n"
            "- EXCLUDE any product that is complained about, criticised, called overpriced, "
            "disappointing, or mentioned neutrally without enthusiasm.\n"
            "- If the OP is asking a question (e.g. 'what brands do you like?'), "
            "DO NOT exclude the post — instead extract products from the COMMENTS where people respond with enthusiastic recommendations. "
            "Only skip a post entirely if neither the body nor any comment contains an enthusiastic product recommendation.\n"
            "- Draw details from both the post body AND the comments — comments are often the richest source of praise.\n"
            "- List up to 15 products. post_num references the [Post N] label above.\n\n"
            "SUMMARY: <2-3 sentence overall summary of what people are loving and why — mention specific themes like effects, flavors, or value that keep coming up>\n"
            "SENTIMENT: <positive|negative|neutral|mixed>"
        )

        message = self.client.messages.create(
            model=self.config.model,
            max_tokens=5000,
            system=[{
                "type": "text",
                "text": (
                    "You are a cannabis product research analyst. "
                    "Extract specific product names, brands, types, and what people like "
                    "about them from Reddit posts. Return valid JSON. Be specific and concise."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        response = message.content[0].text
        product_mentions, products_text = self._parse_products(response, posts)

        summary_line = next(
            (l for l in response.splitlines() if l.startswith("SUMMARY:")),
            "SUMMARY: No summary available.",
        )
        sentiment_line = next(
            (l for l in response.splitlines() if l.startswith("SENTIMENT:")),
            "SENTIMENT: neutral",
        )
        summary_text = summary_line.replace("SUMMARY:", "").strip()
        sentiment = sentiment_line.replace("SENTIMENT:", "").strip().lower()
        if sentiment not in ("positive", "negative", "neutral", "mixed"):
            sentiment = "neutral"

        combined_summary = f"{products_text}\n\n{summary_text}"

        return TopicSummary(
            subreddit=subreddit,
            topic="new products",
            summary=combined_summary,
            post_count=len(posts),
            sentiment=sentiment,
            product_mentions=product_mentions,
        )

    def _parse_products(
        self, response: str, posts: List[RedditPost]
    ) -> tuple[List[ProductMention], str]:
        """Parse PRODUCTS_JSON block; returns (mentions, markdown_text)."""
        mentions: List[ProductMention] = []
        text_lines = ["PRODUCTS:"]

        match = _JSON_BLOCK_RE.search(response)
        if not match:
            return mentions, "\n".join(text_lines)

        try:
            items = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  WARNING: Could not parse PRODUCTS_JSON: {e}")
            return mentions, "\n".join(text_lines)

        for item in items[:15]:
            name = str(item.get("name", "")).strip()
            brand = str(item.get("brand", "")).strip()
            kind = str(item.get("type", "")).strip()
            note = str(item.get("note", "")).strip()
            post_num = item.get("post_num", 1)

            if not name:
                continue

            idx = max(0, min(int(post_num) - 1, len(posts) - 1))
            src = posts[idx]

            mentions.append(ProductMention(
                name=name,
                brand=brand,
                kind=kind,
                note=note,
                source_url=src.url,
                source_date=src.created_utc,
            ))

            line = f"- **{name}** by {brand}"
            if kind:
                line += f" ({kind})"
            if note:
                line += f": {note}"
            text_lines.append(line)

        return mentions, "\n".join(text_lines)
