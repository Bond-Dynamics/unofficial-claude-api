import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from curl_cffi.requests import get as http_get

BASE_URL = "https://claude.ai"
DATA_DIR = Path(__file__).parent.parent / "data"
FIREFOX_PROFILE_DIR = Path.home() / "Library/Application Support/Firefox/Profiles"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Safari/605.1.15"
)

# Artifact type to file extension mapping
_ARTIFACT_EXTENSIONS = {
    "application/vnd.ant.react": ".jsx",
    "application/vnd.ant.code": None,  # uses language attribute
    "application/vnd.ant.mermaid": ".mmd",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/css": ".css",
    "image/svg+xml": ".svg",
    "application/json": ".json",
    "application/xml": ".xml",
    "application/x-latex": ".tex",
    "text/vnd.graphviz": ".dot",
}

_LANGUAGE_EXTENSIONS = {
    "javascript": ".js", "typescript": ".ts", "python": ".py",
    "java": ".java", "c": ".c", "cpp": ".cpp", "ruby": ".rb",
    "php": ".php", "swift": ".swift", "go": ".go", "rust": ".rs",
    "tsx": ".tsx", "jsx": ".jsx", "shell": ".sh", "bash": ".sh",
    "sql": ".sql", "kotlin": ".kt", "scala": ".scala", "r": ".r",
    "json": ".json", "xml": ".xml", "yaml": ".yaml", "yml": ".yml",
    "markdown": ".md", "html": ".html", "css": ".css", "scss": ".scss",
    "svg": ".svg", "mermaid": ".mmd", "latex": ".tex", "toml": ".toml",
    "lua": ".lua", "dart": ".dart", "haskell": ".hs",
}


def find_default_firefox_profile():
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


def read_cookies_from_firefox(profile_dir):
    """Read claude.ai cookies directly from Firefox's SQLite database."""
    cookies_db = profile_dir / "cookies.sqlite"
    if not cookies_db.exists():
        raise FileNotFoundError(f"Cookies database not found: {cookies_db}")

    # Copy the db to avoid locking issues if Firefox is open
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


def make_headers(cookie, extra=None):
    headers = {
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
    if extra:
        headers.update(extra)
    return headers


def api_get(path, cookie, extra_headers=None):
    url = f"{BASE_URL}{path}"
    headers = make_headers(cookie, extra=extra_headers)
    try:
        response = http_get(
            url, headers=headers, timeout=60, impersonate="chrome110"
        )
    except Exception as err:
        print(f"  Request error for {path}: {err}")
        return None
    if response.status_code != 200:
        print(f"  Request failed: {response.status_code} for {path}")
        return None
    try:
        return response.json()
    except (ValueError, TypeError) as err:
        print(f"  Invalid JSON from {path}: {err}")
        return None


def api_get_v1(path, cookie, org_id):
    """GET request to the /v1/ API namespace (Claude Code sessions)."""
    return api_get(
        path,
        cookie,
        extra_headers={
            "x-organization-uuid": org_id,
            "anthropic-version": "2023-06-01",
        },
    )


def format_date(date_str):
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return date_str


def _extract_artifacts_from_text(text):
    """Extract artifacts from <antArtifact> XML tags in message text (old format)."""
    pattern = re.compile(
        r'<antArtifact\s+([^>]*)>([\s\S]*?)</antArtifact>', re.DOTALL
    )
    artifacts = []
    for match in pattern.finditer(text):
        attrs_str, content = match.group(1), match.group(2).strip()
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))

        artifact_type = attrs.get("type", "")
        language = attrs.get("language", "")
        ext = _ARTIFACT_EXTENSIONS.get(artifact_type)
        if ext is None:
            ext = _LANGUAGE_EXTENSIONS.get(language, ".txt")

        artifacts.append({
            "identifier": attrs.get("identifier", ""),
            "title": attrs.get("title", "Untitled"),
            "type": artifact_type,
            "language": language,
            "extension": ext,
            "content": content,
        })
    return artifacts


def _extract_artifacts_from_content(content_blocks):
    """Extract artifacts from message content array (new format with rendering_mode=messages)."""
    artifacts = []
    for block in content_blocks:
        # New format: tool_use with display_content
        if block.get("type") == "tool_use" and block.get("display_content"):
            dc = block["display_content"]

            # code_block format (newer)
            if dc.get("type") == "code_block" and dc.get("code"):
                language = dc.get("language", "txt")
                filename = dc.get("filename", "artifact")
                ext = _LANGUAGE_EXTENSIONS.get(language, ".txt")
                title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                artifacts.append({
                    "identifier": block.get("id", ""),
                    "title": title,
                    "type": f"application/vnd.ant.code",
                    "language": language,
                    "extension": ext,
                    "content": dc["code"].strip(),
                })

            # json_block format (older new-format)
            elif dc.get("type") == "json_block" and dc.get("json_block"):
                try:
                    data = json.loads(dc["json_block"])
                    if data.get("filename"):
                        language = data.get("language", "txt")
                        ext = _LANGUAGE_EXTENSIONS.get(language, ".txt")
                        title = data["filename"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
                        artifacts.append({
                            "identifier": block.get("id", ""),
                            "title": title,
                            "type": "application/vnd.ant.code",
                            "language": language,
                            "extension": ext,
                            "content": data.get("code", "").strip(),
                        })
                except (json.JSONDecodeError, TypeError):
                    pass

        # Also check text blocks for old-format <antArtifact> tags
        if block.get("type") == "text" and block.get("text"):
            artifacts.extend(_extract_artifacts_from_text(block["text"]))

    return artifacts


def extract_artifacts(message):
    """Extract all artifacts from a message, handling both old and new formats.

    Returns list of artifact dicts with: identifier, title, type, language,
    extension, content.
    """
    artifacts = []

    # New format: message has content array
    if isinstance(message.get("content"), list):
        artifacts.extend(_extract_artifacts_from_content(message["content"]))

    # Old format: message has text string
    if isinstance(message.get("text"), str):
        artifacts.extend(_extract_artifacts_from_text(message["text"]))

    # Deduplicate by identifier (old format might also appear in content)
    seen = set()
    unique = []
    for a in artifacts:
        key = a.get("identifier") or a.get("content", "")[:100]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    return unique


def save_artifacts(artifacts, conversation_id, artifacts_dir):
    """Save extracted artifacts to disk as individual files.

    Returns list of saved artifact metadata (without content, for the index).
    """
    saved = []
    used_filenames = set()

    for artifact in artifacts:
        title = artifact.get("title", "artifact")
        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
        ext = artifact.get("extension", ".txt")
        filename = f"{safe_title}{ext}"

        # Handle duplicates
        counter = 1
        base = safe_title
        while filename in used_filenames:
            filename = f"{base}_{counter}{ext}"
            counter += 1
        used_filenames.add(filename)

        filepath = artifacts_dir / filename
        filepath.write_text(artifact["content"], encoding="utf-8")

        saved.append({
            "filename": filename,
            "identifier": artifact.get("identifier", ""),
            "title": artifact.get("title", ""),
            "type": artifact.get("type", ""),
            "language": artifact.get("language", ""),
            "size": len(artifact["content"]),
        })

    return saved


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting conversation sync")

    # Read cookies from Firefox
    print("Reading cookies from Firefox profile...")
    profile_dir = find_default_firefox_profile()
    cookie = read_cookies_from_firefox(profile_dir)
    print("Cookies loaded successfully")

    # Get organization
    print("Fetching organization info...")
    orgs = api_get("/api/organizations", cookie)
    if not orgs:
        print("Failed to fetch organizations. Cookie may be expired.")
        print("Open Firefox and visit claude.ai to refresh your session.")
        raise SystemExit(1)

    org_id = orgs[0]["uuid"]
    org_name = orgs[0].get("name", "Unknown")
    print(f"Organization: {org_name}")

    # Fetch projects with full details, docs, and instructions
    print("Fetching projects...")
    projects = api_get(f"/api/organizations/{org_id}/projects", cookie)
    project_map = {}
    projects_dir = DATA_DIR / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    if projects:
        for p in projects:
            pid = p["uuid"]
            pname = p.get("name", "Untitled Project")
            project_map[pid] = pname

            # Fetch full project detail (includes prompt_template)
            detail = api_get(
                f"/api/organizations/{org_id}/projects/{pid}", cookie
            )

            # Fetch project knowledge docs
            docs = api_get(
                f"/api/organizations/{org_id}/projects/{pid}/docs", cookie
            )

            project_data = detail or p
            project_data["docs"] = docs or []

            # Save each project
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in pname)
            project_file = projects_dir / f"{safe_name}.json"
            project_file.write_text(
                json.dumps(project_data, indent=2, ensure_ascii=False)
            )

            doc_count = len(docs) if docs else 0
            has_prompt = bool(project_data.get("prompt_template"))
            print(f"  Saved: {pname} ({doc_count} docs, prompt: {has_prompt})")
            time.sleep(0.3)

    print(f"Found {len(project_map)} projects")

    # Fetch all conversation summaries
    print("Fetching conversation list...")
    conversations = api_get(
        f"/api/organizations/{org_id}/chat_conversations", cookie
    )
    if not conversations:
        print("No conversations found or request failed.")
        raise SystemExit(1)

    print(f"Found {len(conversations)} conversations")

    # Set up data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conversations_dir = DATA_DIR / "conversations"
    conversations_dir.mkdir(exist_ok=True)
    artifacts_dir = DATA_DIR / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)

    # Fetch full data for each conversation (with artifacts via rendering_mode=messages)
    print("Fetching full conversation data (with artifacts)...")
    full_conversations = []
    total_artifacts = 0
    for i, chat in enumerate(conversations):
        chat_id = chat.get("uuid", "")
        name = chat.get("name") or "(Untitled)"
        progress = f"[{i + 1}/{len(conversations)}]"

        # Check if we already have this conversation and it hasn't been updated
        chat_file = conversations_dir / f"{chat_id}.json"
        if chat_file.exists():
            existing = json.loads(chat_file.read_text())
            if existing.get("updated_at") == chat.get("updated_at"):
                full_conversations.append(existing)
                total_artifacts += existing.get("_artifact_count", 0)
                print(f"  {progress} Skipped (unchanged): {name}")
                continue

        # Fetch with artifact-aware endpoint
        # tree=True returns message tree, rendering_mode=messages returns
        # structured content array with artifacts, render_all_tools=true
        # includes tool use blocks (artifacts are tool_use with display_content)
        chat_data = api_get(
            f"/api/organizations/{org_id}/chat_conversations/{chat_id}"
            f"?tree=True&rendering_mode=messages&render_all_tools=true",
            cookie,
        )

        if chat_data:
            # Add project name for convenience
            project_id = chat_data.get("project_uuid")
            chat_data["project_name"] = (
                project_map.get(project_id, "No Project") if project_id else "No Project"
            )

            # Extract and save artifacts from all messages
            # Clear stale artifacts from previous fetch to avoid duplicates
            conv_artifacts_dir = artifacts_dir / chat_id
            if conv_artifacts_dir.exists():
                shutil.rmtree(conv_artifacts_dir)
            conv_artifact_count = 0

            for msg in chat_data.get("chat_messages", []):
                artifacts = extract_artifacts(msg)
                if artifacts:
                    conv_artifacts_dir.mkdir(exist_ok=True)
                    saved = save_artifacts(artifacts, chat_id, conv_artifacts_dir)
                    conv_artifact_count += len(saved)

                    # Attach artifact metadata to the message for reference
                    msg["_artifacts"] = saved

            if conv_artifact_count > 0:
                chat_data["_artifact_count"] = conv_artifact_count
                total_artifacts += conv_artifact_count

            # Save individual conversation
            chat_file.write_text(
                json.dumps(chat_data, indent=2, ensure_ascii=False)
            )
            full_conversations.append(chat_data)
            msg_count = len(chat_data.get("chat_messages", []))
            artifact_note = f", {conv_artifact_count} artifacts" if conv_artifact_count else ""
            print(f"  {progress} Saved ({msg_count} msgs{artifact_note}): {name}")
        else:
            print(f"  {progress} Failed to fetch: {name}")

        # Rate limiting — be polite
        time.sleep(0.3)

    # --- Fetch published artifacts ---
    print("\nFetching published artifacts...")
    published_dir = DATA_DIR / "published_artifacts"
    published_dir.mkdir(exist_ok=True)
    published_artifacts = api_get(
        f"/api/organizations/{org_id}/published_artifacts", cookie
    )
    total_published = 0
    if published_artifacts:
        for artifact in published_artifacts:
            artifact_uuid = artifact.get("published_artifact_uuid", "")
            if not artifact_uuid:
                continue
            artifact_file = published_dir / f"{artifact_uuid}.json"
            artifact_file.write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False)
            )
            total_published += 1
        print(f"  Saved {total_published} published artifacts")
    else:
        print("  No published artifacts found (or endpoint unavailable)")

    # --- Fetch Claude Code sessions ---
    print("\nFetching Claude Code sessions...")
    sessions_dir = DATA_DIR / "code_sessions"
    sessions_dir.mkdir(exist_ok=True)
    code_sessions = api_get(
        f"/api/organizations/{org_id}/code/sessions", cookie
    )
    total_sessions = 0
    if code_sessions:
        session_list = code_sessions if isinstance(code_sessions, list) else code_sessions.get("sessions", code_sessions.get("data", []))
        for session in session_list:
            session_id = session.get("id") or session.get("uuid", "")
            if not session_id:
                continue

            # Check if already fetched and unchanged
            session_file = sessions_dir / f"{session_id}.json"
            if session_file.exists():
                existing = json.loads(session_file.read_text())
                if existing.get("updated_at") == session.get("updated_at"):
                    total_sessions += 1
                    continue

            session_file.write_text(
                json.dumps(session, indent=2, ensure_ascii=False)
            )
            total_sessions += 1

        print(f"  Saved {total_sessions} Claude Code sessions")
    else:
        print("  No Claude Code sessions found (or endpoint unavailable)")

    # --- Fetch code repos ---
    print("\nFetching connected code repos...")
    repos_file = DATA_DIR / "code_repos.json"
    code_repos = api_get(
        f"/api/organizations/{org_id}/code/repos?skip_status=true", cookie
    )
    total_repos = 0
    if code_repos:
        repo_list = code_repos if isinstance(code_repos, list) else code_repos.get("repos", [])
        repos_file.write_text(
            json.dumps(repo_list, indent=2, ensure_ascii=False)
        )
        total_repos = len(repo_list)
        print(f"  Saved {total_repos} connected repos")
    else:
        print("  No code repos found (or endpoint unavailable)")

    # --- Count starred conversations ---
    total_starred = sum(1 for c in full_conversations if c.get("is_starred"))

    # Group by project
    grouped = {}
    for chat in full_conversations:
        project_name = chat.get("project_name", "No Project")
        if project_name not in grouped:
            grouped[project_name] = []
        grouped[project_name].append(chat)

    for project_name in grouped:
        grouped[project_name].sort(
            key=lambda c: c.get("updated_at", ""), reverse=True
        )

    # Save projects summary
    projects_summary_file = DATA_DIR / "projects_summary.json"
    projects_summary_file.write_text(
        json.dumps(projects or [], indent=2, ensure_ascii=False)
    )

    # Save index file
    index = {
        "synced_at": datetime.now().isoformat(),
        "organization": org_name,
        "organization_id": org_id,
        "total_conversations": len(full_conversations),
        "total_projects": len(project_map),
        "total_artifacts": total_artifacts,
        "total_starred": total_starred,
        "total_published_artifacts": total_published,
        "total_code_sessions": total_sessions,
        "total_code_repos": total_repos,
        "projects": {
            name: [
                {
                    "name": c.get("name") or "(Untitled)",
                    "uuid": c.get("uuid"),
                    "model": c.get("model"),
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                    "message_count": len(c.get("chat_messages", [])),
                    "artifact_count": c.get("_artifact_count", 0),
                    "is_starred": c.get("is_starred", False),
                    "settings": c.get("settings", {}),
                    "project_name": name,
                }
                for c in chats
            ]
            for name, chats in sorted(grouped.items())
        },
    }

    index_file = DATA_DIR / "index.json"
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))

    # Summary
    print(f"\nSync complete!")
    print(f"  Conversations:      {len(full_conversations)} ({total_starred} starred)")
    print(f"  Projects:           {len(project_map)}")
    print(f"  Artifacts:          {total_artifacts}")
    print(f"  Published:          {total_published}")
    print(f"  Code sessions:      {total_sessions}")
    print(f"  Code repos:         {total_repos}")
    print(f"  Data dir:           {DATA_DIR}")
    print(f"  Index:              {index_file}")
    print(f"  Conversations:      {conversations_dir}/")
    print(f"  Artifacts:          {artifacts_dir}/")
    print(f"  Published:          {published_dir}/")
    print(f"  Code sessions:      {sessions_dir}/")

    # Auto-embed if MongoDB is available
    try:
        from vectordb.db import is_mongodb_available

        if is_mongodb_available():
            print("\nMongoDB detected. Running embedding pipeline...")
            from vectordb.pipeline import run_pipeline

            run_pipeline()
        else:
            print("\nMongoDB not running. Skipping embedding step.")
            print("  Start it with: scripts/start_mongodb.sh")
    except ImportError:
        print("\nVector search not installed. Skipping embedding.")
        print("  Install with: pip3 install pymongo voyageai")
    except Exception as err:
        print(f"\nEmbedding step failed (sync still succeeded): {err}")


if __name__ == "__main__":
    main()
