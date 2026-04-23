from analyzer import Analyzer
from config import ProjectConfig
from delivery import create_delivery
from reddit_client import create_reddit_client


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

        for delivery_config in project.delivery:
            create_delivery(delivery_config).deliver(report)
