from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

import requests

from config import RedditConfig

_MAX_PER_FEED = 100  # Reddit API hard limit per request


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
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def fetch_posts(self, config: RedditConfig) -> List[RedditPost]:
        cutoff = config.date_range.to_cutoff()
        time_filter = config.date_range.to_praw_time_filter()
        posts = []

        for subreddit_cfg in config.subreddits:
            limit = config.max_posts_per_topic
            print(f"  Browsing r/{subreddit_cfg.name} (JSON)...")
            raw = self._browse(subreddit_cfg.name, time_filter, limit, cutoff)
            all_posts = self._to_posts(raw, subreddit_cfg.name, limit)
            print(f"    {len(all_posts)} posts fetched (sentiment filtering via Claude)")

            if subreddit_cfg.pinned_post_ids:
                existing_urls = {p.url for p in all_posts}
                pinned = self._fetch_pinned_posts(subreddit_cfg.name, subreddit_cfg.pinned_post_ids)
                added = 0
                for p in pinned:
                    if p.url not in existing_urls:
                        all_posts.append(p)
                        existing_urls.add(p.url)
                        added += 1
                print(f"    {added} pinned post(s) added")

            posts.extend(all_posts)
            time.sleep(1)

        return posts

    def _browse(self, subreddit: str, time_filter: str, limit: int, cutoff: datetime) -> list:
        """Fetch posts from hot + top + new feeds, deduplicated and date-filtered."""
        per_req = min(limit, _MAX_PER_FEED)
        seen: set = set()
        all_posts: list = []
        feeds = [
            (f"{self.BASE_URL}/r/{subreddit}/hot.json",  {"limit": per_req}),
            (f"{self.BASE_URL}/r/{subreddit}/top.json",  {"limit": per_req, "t": time_filter}),
            (f"{self.BASE_URL}/r/{subreddit}/new.json",  {"limit": per_req}),
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

    def _to_posts(self, raw_posts: list, subreddit: str, limit: int) -> List[RedditPost]:
        """Convert raw API dicts to RedditPost objects with no keyword filtering."""
        results = []
        for d in raw_posts:
            results.append(self._make_post(d, subreddit, topic="general"))
            if len(results) >= limit:
                break
        return results

    def _filter_by_topic(self, raw_posts: list, topic: str, subreddit: str, limit: int) -> List[RedditPost]:
        """Filter posts whose title or body contains any keyword from topic."""
        keywords = [kw.lower() for kw in topic.split()]
        matched = []
        for d in raw_posts:
            text = (d.get("title", "") + " " + d.get("selftext", "")).lower()
            if any(kw in text for kw in keywords):
                matched.append(self._make_post(d, subreddit, topic))
                if len(matched) >= limit:
                    break
        return matched

    def _make_post(self, d: dict, subreddit: str, topic: str) -> RedditPost:
        return RedditPost(
            subreddit=subreddit,
            topic=topic,
            title=d.get("title", ""),
            body=d.get("selftext", "")[:2000],
            score=d.get("score", 0),
            url=f"{self.BASE_URL}{d.get('permalink', '')}",
            created_utc=datetime.utcfromtimestamp(d["created_utc"]),
            num_comments=d.get("num_comments", 0),
            top_comments=self._fetch_top_comments(subreddit, d["id"]),
        )

    def _extract_post_id(self, id_or_url: str) -> str:
        """Accept a post ID or a full Reddit URL and return just the post ID."""
        if "/" not in id_or_url:
            return id_or_url
        parts = [p for p in id_or_url.rstrip("/").split("/") if p]
        try:
            return parts[parts.index("comments") + 1]
        except (ValueError, IndexError):
            return id_or_url

    def _fetch_pinned_posts(self, subreddit: str, id_or_urls: List[str]) -> List[RedditPost]:
        """Fetch specific posts by ID or URL, bypassing feed/date filters."""
        results = []
        for raw_id in id_or_urls:
            post_id = self._extract_post_id(raw_id)
            url = f"{self.BASE_URL}/r/{subreddit}/comments/{post_id}.json"
            delays = [2, 10, 30]
            for attempt, delay in enumerate(delays, 1):
                try:
                    time.sleep(delay)
                    resp = requests.get(
                        url,
                        params={"limit": 10, "sort": "top", "depth": 1},
                        headers=self.HEADERS,
                        timeout=15,
                    )
                    if resp.status_code == 429:
                        if attempt < len(delays):
                            print(f"  Rate limited on pinned post {post_id}, retrying in {delays[attempt]}s...")
                            continue
                        print(f"  WARNING: Rate limited on pinned post {post_id} after {attempt} attempts, skipping.")
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    d = data[0]["data"]["children"][0]["data"]
                    results.append(self._make_post(d, subreddit, topic="pinned"))
                    break
                except requests.HTTPError:
                    print(f"  WARNING: Could not fetch pinned post {post_id}: HTTP {resp.status_code}")
                    break
                except Exception as e:
                    print(f"  WARNING: Could not fetch pinned post {post_id}: {e}")
                    break
        return results

    def _fetch_top_comments(self, subreddit: str, post_id: str) -> List[str]:
        url = f"{self.BASE_URL}/r/{subreddit}/comments/{post_id}.json"
        try:
            resp = requests.get(url, params={"limit": 10, "sort": "top", "depth": 1}, headers=self.HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if len(data) < 2:
                return []
            comments = []
            for child in data[1]["data"]["children"][:10]:
                body = child.get("data", {}).get("body", "")
                if body and body != "[deleted]" and len(body) < 1000:
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
            topics = subreddit_cfg.topics or ["cannabis"]
            for topic in topics:
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
