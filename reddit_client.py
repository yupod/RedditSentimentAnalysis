from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

import requests

from config import RedditConfig


@dataclass
class RedditPost:
    subreddit: str
    topic: str
    title: str
    body: str
    score: int
    url: str
    created_utc: datetime
    num_comments: int
    top_comments: List[str] = field(default_factory=list)


def create_reddit_client(config: RedditConfig) -> BaseRedditClient:
    if config.access_mode == "api":
        return PrawRedditClient()
    return JsonRedditClient()


class BaseRedditClient:
    def fetch_posts(self, config: RedditConfig) -> List[RedditPost]:
        raise NotImplementedError


# ── JSON endpoint (no credentials required) ───────────────────────────────────

class JsonRedditClient(BaseRedditClient):
    BASE_URL = "https://www.reddit.com"
    HEADERS = {"User-Agent": "RedditSentimentAnalyzer/1.0"}

    def fetch_posts(self, config: RedditConfig) -> List[RedditPost]:
        cutoff = config.date_range.to_cutoff()
        time_filter = config.date_range.to_praw_time_filter()
        posts = []

        for subreddit_cfg in config.subreddits:
            print(f"  Browsing r/{subreddit_cfg.name} (JSON)...")
            raw = self._browse(subreddit_cfg.name, time_filter, config.max_posts_per_topic * 3, cutoff)
            for topic in subreddit_cfg.topics:
                matched = self._filter_by_topic(raw, topic, subreddit_cfg.name, config.max_posts_per_topic)
                print(f"    '{topic}': {len(matched)} posts matched")
                posts.extend(matched)
            time.sleep(1)

        return posts

    def _browse(self, subreddit: str, time_filter: str, limit: int, cutoff: datetime) -> list:
        """Fetch recent posts from hot + top feeds, deduplicated."""
        seen = set()
        all_posts = []
        feeds = [
            (f"{self.BASE_URL}/r/{subreddit}/hot.json", {"limit": 50}),
            (f"{self.BASE_URL}/r/{subreddit}/top.json", {"limit": 50, "t": time_filter}),
            (f"{self.BASE_URL}/r/{subreddit}/new.json", {"limit": 50}),
        ]
        for url, params in feeds:
            try:
                resp = requests.get(url, params=params, headers=self.HEADERS, timeout=10)
                resp.raise_for_status()
                for child in resp.json().get("data", {}).get("children", []):
                    d = child["data"]
                    if d["id"] in seen:
                        continue
                    created = datetime.utcfromtimestamp(d["created_utc"])
                    if created < cutoff:
                        continue
                    seen.add(d["id"])
                    all_posts.append(d)
                time.sleep(0.5)
            except requests.RequestException as e:
                print(f"  WARNING: {url} failed: {e}")
        return all_posts

    def _filter_by_topic(self, raw_posts: list, topic: str, subreddit: str, limit: int) -> List[RedditPost]:
        """Filter posts whose title or body contains any topic keyword."""
        keywords = [kw.lower() for kw in topic.split()]
        matched = []
        for d in raw_posts:
            text = (d.get("title", "") + " " + d.get("selftext", "")).lower()
            if any(kw in text for kw in keywords):
                matched.append(RedditPost(
                    subreddit=subreddit,
                    topic=topic,
                    title=d.get("title", ""),
                    body=d.get("selftext", "")[:1000],
                    score=d.get("score", 0),
                    url=f"{self.BASE_URL}{d.get('permalink', '')}",
                    created_utc=datetime.utcfromtimestamp(d["created_utc"]),
                    num_comments=d.get("num_comments", 0),
                    top_comments=self._fetch_top_comments(subreddit, d["id"]),
                ))
                if len(matched) >= limit:
                    break
        return matched

    def _fetch_top_comments(self, subreddit: str, post_id: str) -> List[str]:
        url = f"{self.BASE_URL}/r/{subreddit}/comments/{post_id}.json"
        try:
            resp = requests.get(url, params={"limit": 5, "sort": "top", "depth": 1}, headers=self.HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if len(data) < 2:
                return []
            comments = []
            for child in data[1]["data"]["children"][:5]:
                body = child.get("data", {}).get("body", "")
                if body and body != "[deleted]" and len(body) < 500:
                    comments.append(body)
            return comments
        except Exception:
            return []


# ── PRAW (requires Reddit API credentials) ────────────────────────────────────

class PrawRedditClient(BaseRedditClient):
    def __init__(self):
        import praw
        self.reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.getenv("REDDIT_USER_AGENT", "RedditSentimentAnalyzer/1.0"),
            username=os.getenv("REDDIT_USERNAME") or None,
            password=os.getenv("REDDIT_PASSWORD") or None,
        )

    def fetch_posts(self, config: RedditConfig) -> List[RedditPost]:
        cutoff = config.date_range.to_cutoff()
        time_filter = config.date_range.to_praw_time_filter()
        posts = []

        for subreddit_cfg in config.subreddits:
            sub = self.reddit.subreddit(subreddit_cfg.name)
            for topic in subreddit_cfg.topics:
                print(f"  Searching r/{subreddit_cfg.name} for '{topic}' (API)...")
                results = sub.search(topic, time_filter=time_filter, limit=config.max_posts_per_topic * 2, sort="relevance")
                count = 0
                for submission in results:
                    if count >= config.max_posts_per_topic:
                        break
                    created = datetime.utcfromtimestamp(submission.created_utc)
                    if created < cutoff:
                        continue
                    submission.comments.replace_more(limit=0)
                    top_comments = [
                        c.body for c in submission.comments.list()[:5]
                        if hasattr(c, "body") and len(c.body) < 500
                    ]
                    posts.append(RedditPost(
                        subreddit=subreddit_cfg.name,
                        topic=topic,
                        title=submission.title,
                        body=submission.selftext[:1000] if submission.selftext else "",
                        score=submission.score,
                        url=f"https://reddit.com{submission.permalink}",
                        created_utc=created,
                        num_comments=submission.num_comments,
                        top_comments=top_comments,
                    ))
                    count += 1

        return posts
