import os, sys
import requests

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Thin read-only wrapper around the GitHub REST API v3."""

    def __init__(self, token=None):
        raw_token = token or os.environ.get("GITHUB_TOKEN", "")
        if not raw_token:
            print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
            sys.exit(1)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": "Bearer " + raw_token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, path, params=None):
        url = GITHUB_API_BASE + path
        resp = self._session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            print("ERROR: GitHub returned 401 — check your token.", file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            print("ERROR: GitHub 403. Rate-limit remaining: " + remaining, file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 404:
            print("ERROR: GitHub 404 for " + url + ". Check repo name and token access.", file=sys.stderr)
            sys.exit(1)
        resp.raise_for_status()
        return resp.json()

    def get_open_issues(self, owner, repo, page=1, per_page=10):
        """Return open issues (excluding PRs) sorted by creation date asc."""
        data = self._get(
            "/repos/" + owner + "/" + repo + "/issues",
            params={"state": "open", "sort": "created", "direction": "desc", "page": page, "per_page": per_page},
        )
        return [item for item in data if "pull_request" not in item]

    def get_open_prs(self, owner, repo, page=1, per_page=10):
        """Return open pull requests sorted by creation date asc."""
        return self._get(
            "/repos/" + owner + "/" + repo + "/pulls",
            params={"state": "open", "sort": "created", "direction": "desc", "page": page, "per_page": per_page},
        )

    def get_issue_comments(self, owner, repo, issue_number):
        return self._get(
            "/repos/" + owner + "/" + repo + "/issues/" + str(issue_number) + "/comments",
            params={"per_page": 100},
        )

    def get_pr_files(self, owner, repo, pr_number):
        return self._get(
            "/repos/" + owner + "/" + repo + "/pulls/" + str(pr_number) + "/files",
            params={"per_page": 100},
        )

    def get_repo_info(self, owner, repo):
        return self._get("/repos/" + owner + "/" + repo)

    def count_open_items(self, owner, repo):
        """Return {"issues": N, "prs": M} — counts all open issues and PRs."""
        pr_count = self._count_all("/repos/" + owner + "/" + repo + "/pulls", {"state": "open"})
        all_count = self._count_all("/repos/" + owner + "/" + repo + "/issues", {"state": "open"})
        return {"issues": max(all_count - pr_count, 0), "prs": pr_count}

    def _count_all(self, path, params):
        params = dict(params)
        params["per_page"] = 100
        params["page"] = 1
        total = 0
        while True:
            batch = self._get(path, params=params)
            if not batch:
                break
            total += len(batch)
            if len(batch) < 100:
                break
            params["page"] += 1
        return total
