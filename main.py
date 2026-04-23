import argparse
import sys

from config import load_config
from runner import ResearchRunner


def main():
    parser = argparse.ArgumentParser(description="Reddit Sentiment Analyzer")
    parser.add_argument("--config", default="research_config.yaml", help="Path to YAML config file")
    parser.add_argument("--project", help="Run a specific project by name (default: all)")
    args = parser.parse_args()

    config = load_config(args.config)
    projects = config.projects

    if args.project:
        projects = [p for p in projects if p.name == args.project]
        if not projects:
            print(f"Project '{args.project}' not found in config.")
            sys.exit(1)

    runner = ResearchRunner()
    for project in projects:
        print(f"\n{'='*60}\nRunning: {project.name}\n{'='*60}")
        runner.run(project)


if __name__ == "__main__":
    main()
