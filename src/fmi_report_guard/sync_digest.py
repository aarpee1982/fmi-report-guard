from __future__ import annotations

from .config import AppConfig
from .issues import GitHubIssueClient


def main() -> None:
    config = AppConfig.from_env()
    if not config.github_token:
        raise ValueError("GITHUB_TOKEN is required to sync the correction digest.")
    if not config.github_repository:
        raise ValueError("GITHUB_REPOSITORY is required to sync the correction digest.")

    github = GitHubIssueClient(token=config.github_token, repository=config.github_repository)
    github.sync_correction_digest()
    print("Synced FMI Guard correction digest.")


if __name__ == "__main__":
    main()
