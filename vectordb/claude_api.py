"""Claude.ai API client with read and write operations.

Handles cookie-based authentication via Firefox profile and provides
CRUD operations for projects, project docs (knowledge files), and
project instructions (prompt_template).

Uses curl_cffi for browser impersonation to match Claude.ai's
TLS fingerprint expectations.
"""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from curl_cffi.requests import get as http_get
from curl_cffi.requests import put as http_put
from curl_cffi.requests import post as http_post
from curl_cffi.requests import delete as http_delete

BASE_URL = "https://claude.ai"
FIREFOX_PROFILE_DIR = Path.home() / "Library/Application Support/Firefox/Profiles"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Safari/605.1.15"
)


class ClaudeAPIError(Exception):
    """Raised when a Claude.ai API call fails."""

    def __init__(self, status_code: int, message: str, path: str):
        self.status_code = status_code
        self.path = path
        super().__init__(f"Claude API {status_code} on {path}: {message}")


def _find_default_firefox_profile() -> Path:
    """Find the default Firefox profile directory."""
    profiles_ini = FIREFOX_PROFILE_DIR.parent / "profiles.ini"
    if not profiles_ini.exists():
        raise FileNotFoundError("Firefox profiles.ini not found")

    default_path = None
    for line in profiles_ini.read_text().splitlines():
        if line.startswith("Path="):
            default_path = line.split("=", 1)[1]
        if line.strip() == "Default=1" and default_path:
            break

    if not default_path:
        raise FileNotFoundError("No default Firefox profile found")

    profile_dir = FIREFOX_PROFILE_DIR.parent / default_path
    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile directory not found: {profile_dir}")

    return profile_dir


def _read_cookies() -> str:
    """Read claude.ai cookies from Firefox's SQLite database."""
    profile_dir = _find_default_firefox_profile()
    cookies_db = profile_dir / "cookies.sqlite"
    if not cookies_db.exists():
        raise FileNotFoundError(f"Cookies database not found: {cookies_db}")

    tmp_db = Path("/tmp/claude_cookies_copy.sqlite")
    shutil.copy2(cookies_db, tmp_db)

    try:
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, value FROM moz_cookies WHERE host LIKE '%claude.ai%'"
        )
        cookies = cursor.fetchall()
        conn.close()
    finally:
        tmp_db.unlink(missing_ok=True)

    if not cookies:
        raise RuntimeError("No claude.ai cookies found in Firefox. Log in first.")

    return "; ".join(f"{name}={value}" for name, value in cookies)


def _headers(cookie: str, content_type: Optional[str] = None) -> dict:
    """Build request headers."""
    h = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cookie": cookie,
        "Host": "claude.ai",
        "DNT": "1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": USER_AGENT,
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def _get(path: str, cookie: str):
    """GET request to Claude.ai API."""
    url = f"{BASE_URL}{path}"
    response = http_get(
        url, headers=_headers(cookie), timeout=60, impersonate="chrome110"
    )
    if response.status_code != 200:
        raise ClaudeAPIError(response.status_code, response.text[:200], path)
    return response.json()


def _put(path: str, cookie: str, body: dict):
    """PUT request to Claude.ai API."""
    url = f"{BASE_URL}{path}"
    response = http_put(
        url,
        headers=_headers(cookie, content_type="application/json"),
        data=json.dumps(body),
        timeout=60,
        impersonate="chrome110",
    )
    if response.status_code not in (200, 201, 202, 204):
        raise ClaudeAPIError(response.status_code, response.text[:200], path)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except (ValueError, TypeError):
        return None


def _post(path: str, cookie: str, body: dict):
    """POST request to Claude.ai API."""
    url = f"{BASE_URL}{path}"
    response = http_post(
        url,
        headers=_headers(cookie, content_type="application/json"),
        data=json.dumps(body),
        timeout=60,
        impersonate="chrome110",
    )
    if response.status_code not in (200, 201):
        raise ClaudeAPIError(response.status_code, response.text[:200], path)
    return response.json()


def _delete(path: str, cookie: str):
    """DELETE request to Claude.ai API."""
    url = f"{BASE_URL}{path}"
    response = http_delete(
        url,
        headers=_headers(cookie),
        timeout=60,
        impersonate="chrome110",
    )
    if response.status_code not in (200, 204):
        raise ClaudeAPIError(response.status_code, response.text[:200], path)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class ClaudeSession:
    """Authenticated session to Claude.ai API.

    Reads Firefox cookies on init and resolves the organization ID.
    All operations are instance methods to reuse the auth context.
    """

    def __init__(self):
        self._cookie = _read_cookies()
        orgs = _get("/api/organizations", self._cookie)
        if not orgs:
            raise RuntimeError("No organizations found. Cookie may be expired.")
        self._org_id = orgs[0]["uuid"]
        self._org_name = orgs[0].get("name", "Unknown")

    @property
    def org_id(self) -> str:
        return self._org_id

    @property
    def org_name(self) -> str:
        return self._org_name

    # -----------------------------------------------------------------------
    # Projects — read
    # -----------------------------------------------------------------------

    def list_projects(self) -> list[dict]:
        """List all projects in the organization."""
        return _get(
            f"/api/organizations/{self._org_id}/projects",
            self._cookie,
        )

    def get_project(self, project_uuid: str) -> dict:
        """Get full project detail including prompt_template."""
        return _get(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}",
            self._cookie,
        )

    def get_project_docs(self, project_uuid: str) -> list[dict]:
        """Get all knowledge docs for a project."""
        return _get(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}/docs",
            self._cookie,
        )

    def find_project_by_name(self, name: str) -> Optional[dict]:
        """Find a project by name (case-insensitive substring match)."""
        projects = self.list_projects()
        name_lower = name.lower()
        for p in projects:
            if p.get("name", "").lower() == name_lower:
                return p
        for p in projects:
            if name_lower in p.get("name", "").lower():
                return p
        return None

    # -----------------------------------------------------------------------
    # Projects — write
    # -----------------------------------------------------------------------

    def update_project_instructions(
        self, project_uuid: str, prompt_template: str
    ) -> dict:
        """Update a project's custom instructions (prompt_template)."""
        return _put(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}",
            self._cookie,
            {"prompt_template": prompt_template},
        )

    def update_project(
        self,
        project_uuid: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        prompt_template: Optional[str] = None,
    ) -> dict:
        """Update project metadata (name, description, instructions)."""
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if prompt_template is not None:
            body["prompt_template"] = prompt_template
        return _put(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}",
            self._cookie,
            body,
        )

    # -----------------------------------------------------------------------
    # Project docs (knowledge files) — write
    # -----------------------------------------------------------------------

    def create_doc(
        self, project_uuid: str, file_name: str, content: str
    ) -> dict:
        """Create a new knowledge doc in a project."""
        return _post(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}/docs",
            self._cookie,
            {"file_name": file_name, "content": content},
        )

    def update_doc(
        self,
        project_uuid: str,
        doc_uuid: str,
        file_name: Optional[str] = None,
        content: Optional[str] = None,
    ) -> dict:
        """Update an existing knowledge doc (delete + recreate).

        Claude.ai doesn't support PUT on individual docs, so this
        deletes the old doc and creates a new one with the updated content.
        If file_name is not provided, the original filename is preserved.
        """
        if file_name is None or content is None:
            existing_docs = self.get_project_docs(project_uuid)
            old_doc = next(
                (d for d in existing_docs if d["uuid"] == doc_uuid), None
            )
            if old_doc is None:
                raise ClaudeAPIError(404, "Doc not found", doc_uuid)
            if file_name is None:
                file_name = old_doc["file_name"]
            if content is None:
                content = old_doc.get("content", "")

        self.delete_doc(project_uuid, doc_uuid)
        return self.create_doc(project_uuid, file_name, content)

    def delete_doc(self, project_uuid: str, doc_uuid: str):
        """Delete a knowledge doc from a project."""
        return _delete(
            f"/api/organizations/{self._org_id}/projects/{project_uuid}/docs/{doc_uuid}",
            self._cookie,
        )

    def upsert_doc(
        self, project_uuid: str, file_name: str, content: str
    ) -> dict:
        """Create or update a doc by filename.

        Searches existing docs for a matching file_name. If found, updates
        it. Otherwise creates a new doc.
        """
        existing_docs = self.get_project_docs(project_uuid)
        for doc in existing_docs:
            if doc.get("file_name") == file_name:
                return self.update_doc(
                    project_uuid, doc["uuid"], content=content
                )
        return self.create_doc(project_uuid, file_name, content)

    # -----------------------------------------------------------------------
    # Convenience: sync Forge OS state to a project
    # -----------------------------------------------------------------------

    def sync_decisions_to_project(
        self, project_uuid: str, project_name: str
    ) -> dict:
        """Compile active decisions into a knowledge doc and push to Claude.ai."""
        from vectordb.decision_registry import get_active_decisions

        decisions = get_active_decisions(project_name)
        if not decisions:
            return {"status": "skipped", "reason": "no active decisions"}

        lines = [f"# Active Decisions — {project_name}\n"]
        lines.append(f"_Auto-synced from Forge OS. {len(decisions)} decisions._\n")

        for d in sorted(decisions, key=lambda x: x.get("local_id", "")):
            local_id = d.get("local_id", "?")
            text = d.get("text", "")
            tier = d.get("epistemic_tier", "?")
            status = d.get("status", "active")
            rationale = d.get("rationale", "")
            hops = d.get("hops_since_validated", 0)
            conflicts = d.get("conflicts_with", [])

            lines.append(f"## {local_id}: {text}\n")
            lines.append(f"- **Tier:** {tier}")
            lines.append(f"- **Status:** {status}")
            lines.append(f"- **Hops since validated:** {hops}")
            if rationale:
                lines.append(f"- **Rationale:** {rationale}")
            if conflicts:
                lines.append(f"- **Conflicts with:** {', '.join(conflicts)}")
            lines.append("")

        content = "\n".join(lines)
        result = self.upsert_doc(
            project_uuid, f"forge_decisions_{project_name}.md", content
        )
        return {"status": "synced", "decisions": len(decisions), "doc": result}

    def sync_threads_to_project(
        self, project_uuid: str, project_name: str
    ) -> dict:
        """Compile active threads into a knowledge doc and push to Claude.ai."""
        from vectordb.thread_registry import get_active_threads

        threads = get_active_threads(project_name)
        if not threads:
            return {"status": "skipped", "reason": "no active threads"}

        lines = [f"# Active Threads — {project_name}\n"]
        lines.append(f"_Auto-synced from Forge OS. {len(threads)} threads._\n")

        for t in sorted(threads, key=lambda x: x.get("local_id", "")):
            local_id = t.get("local_id", "?")
            title = t.get("title", "")
            status = t.get("status", "open")
            priority = t.get("priority", "medium")
            blocked_by = t.get("blocked_by", [])
            hops = t.get("hops_since_validated", 0)

            lines.append(f"## {local_id}: {title}\n")
            lines.append(f"- **Status:** {status}")
            lines.append(f"- **Priority:** {priority}")
            lines.append(f"- **Hops since validated:** {hops}")
            if blocked_by:
                lines.append(f"- **Blocked by:** {', '.join(blocked_by)}")
            lines.append("")

        content = "\n".join(lines)
        result = self.upsert_doc(
            project_uuid, f"forge_threads_{project_name}.md", content
        )
        return {"status": "synced", "threads": len(threads), "doc": result}

    def sync_all_to_project(
        self, project_uuid: str, project_name: str
    ) -> dict:
        """Sync decisions + threads to a Claude.ai project."""
        decisions_result = self.sync_decisions_to_project(
            project_uuid, project_name
        )
        threads_result = self.sync_threads_to_project(
            project_uuid, project_name
        )
        return {
            "project": project_name,
            "decisions": decisions_result,
            "threads": threads_result,
        }


# ---------------------------------------------------------------------------
# Module-level convenience functions (create session on demand)
# ---------------------------------------------------------------------------

_session: Optional[ClaudeSession] = None


def get_session() -> ClaudeSession:
    """Get or create a cached ClaudeSession."""
    global _session
    if _session is None:
        _session = ClaudeSession()
    return _session


def reset_session():
    """Force re-authentication on next call."""
    global _session
    _session = None
