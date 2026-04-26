import os
import re
from datetime import datetime

from analyzer import Analyzer
from config import ProjectConfig
from delivery import create_delivery
from dispensary_client import fetch_dispensary_products
from product_matcher import match_products
from reddit_client import create_reddit_client
from table_generator import generate_match_table_html


class ResearchRunner:
    def run(self, project: ProjectConfig) -> None:
        print(f"Fetching Reddit posts (mode: {project.reddit.access_mode})...")
        client = create_reddit_client(project.reddit)
        posts = client.fetch_posts(project.reddit)
        print(f"Fetched {len(posts)} posts.")

        if not posts:
            print("No posts found for the given criteria. Skipping analysis.")
            return

        print(f"Analyzing with {project.llm.provider}/{project.llm.model}...")
        report = Analyzer(project.llm).analyze(project, posts)

        # Build match table before delivery so email can embed it
        mentions = report.all_mentions
        if mentions:
            print("Fetching Gardens Dispensary menu...")
            try:
                dispensary_products = fetch_dispensary_products()
                print(f"  {len(dispensary_products)} products on menu.")
                print(f"Matching {len(mentions)} Reddit mentions against dispensary inventory...")
                matches = match_products(mentions, dispensary_products)
                report.match_table_html = generate_match_table_html(
                    matches, project.name,
                    reddit_config=project.reddit,
                    posts_fetched=len(posts),
                )
                matched_count = sum(1 for m in matches if m.dispensary_product)
                print(f"  {matched_count}/{len(mentions)} mentions matched.")
            except Exception as e:
                print(f"  WARNING: Dispensary matching failed: {e}")
        else:
            print("No structured product mentions extracted; skipping match table.")

        # Deliver (email will include HTML body if match_table_html is set)
        for delivery_config in project.delivery:
            create_delivery(delivery_config).deliver(report)

        # Also save HTML to disk
        if report.match_table_html:
            html_path = self._html_path(project.name)
            os.makedirs(os.path.dirname(html_path) or ".", exist_ok=True)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(report.match_table_html)
            print(f"Match table saved: {html_path}")

    @staticmethod
    def _html_path(project_name: str) -> str:
        safe = re.sub(r"[^\w\-]", "_", project_name.lower())
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(".", "reports", f"{safe}_{ts}_matches.html")
