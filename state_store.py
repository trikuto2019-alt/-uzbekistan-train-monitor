"""Durable state in one GitHub issue, with no repository commits or cache dependency."""

from __future__ import annotations

import json
import os
import requests

TITLE = "[train-monitor-state] 2026-11-10 751M"


class StateStoreError(Exception):
    pass


class GitHubIssueStateStore:
    def __init__(self, *, session=None, repository=None, token=None):
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY")
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.repository or not self.token or "/" not in self.repository:
            raise StateStoreError("GitHub repository/token configuration is missing")
        self.session = session or requests.Session()
        self.base = f"https://api.github.com/repos/{self.repository}/issues"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "UzbekistanTrainAvailabilityMonitor/1.0",
        }
        self.issue_number = None

    def _request(self, method, url, *, params=None, payload=None, expected=(200,)):
        try:
            response = self.session.request(
                method, url, headers=self.headers, params=params,
                json=payload, timeout=(5, 20),
            )
        except requests.RequestException as exc:
            raise StateStoreError("GitHub state API request failed") from exc
        if response.status_code not in expected:
            raise StateStoreError(f"GitHub state API HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise StateStoreError("GitHub state API returned invalid JSON") from exc

    def load(self) -> str | None:
        matches = []
        for page in range(1, 21):
            issues = self._request(
                "GET", self.base,
                params={"state": "all", "per_page": 100, "page": page},
            )
            if not isinstance(issues, list):
                raise StateStoreError("GitHub state issue list has changed")
            matches.extend(issue for issue in issues if issue.get("title") == TITLE and "pull_request" not in issue)
            if len(issues) < 100:
                break
        else:
            raise StateStoreError("Too many GitHub issues to locate state safely")
        if len(matches) > 1:
            raise StateStoreError("Duplicate state issues found")
        if not matches:
            return None
        issue = matches[0]
        self.issue_number = issue.get("number")
        if not isinstance(self.issue_number, int):
            raise StateStoreError("State issue number is invalid")
        try:
            record = json.loads(issue.get("body") or "")
        except (ValueError, TypeError) as exc:
            raise StateStoreError("State issue body is invalid") from exc
        if not isinstance(record, dict) or record.get("version") != 1 or record.get("state") not in ("AVAILABLE", "UNAVAILABLE"):
            raise StateStoreError("State issue schema is invalid")
        return record["state"]

    def save(self, state: str) -> None:
        if state not in ("AVAILABLE", "UNAVAILABLE"):
            raise StateStoreError("Refusing to persist an unknown state")
        body = json.dumps({"version": 1, "state": state}, separators=(",", ":"))
        if self.issue_number is None:
            issue = self._request(
                "POST", self.base,
                payload={"title": TITLE, "body": body}, expected=(201,),
            )
            self.issue_number = issue.get("number")
            if not isinstance(self.issue_number, int):
                raise StateStoreError("GitHub did not return a state issue number")
        else:
            self._request("PATCH", f"{self.base}/{self.issue_number}", payload={"body": body})
