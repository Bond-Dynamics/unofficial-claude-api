import json
import os
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


def make_headers(cookie):
    return {
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


def api_get(path, cookie):
    url = f"{BASE_URL}{path}"
    headers = make_headers(cookie)
    response = http_get(
        url, headers=headers, timeout=60, impersonate="chrome110"
    )
    if response.status_code != 200:
        print(f"  Request failed: {response.status_code} for {path}")
        return None
    return response.json()


def format_date(date_str):
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return date_str


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

    # Fetch full data for each conversation
    print("Fetching full conversation data...")
    full_conversations = []
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
                print(f"  {progress} Skipped (unchanged): {name}")
                continue

        # Fetch full conversation with messages
        chat_data = api_get(
            f"/api/organizations/{org_id}/chat_conversations/{chat_id}",
            cookie,
        )

        if chat_data:
            # Add project name for convenience
            project_id = chat_data.get("project_uuid")
            chat_data["project_name"] = (
                project_map.get(project_id, "No Project") if project_id else "No Project"
            )

            # Save individual conversation
            chat_file.write_text(
                json.dumps(chat_data, indent=2, ensure_ascii=False)
            )
            full_conversations.append(chat_data)
            msg_count = len(chat_data.get("chat_messages", []))
            print(f"  {progress} Saved ({msg_count} msgs): {name}")
        else:
            print(f"  {progress} Failed to fetch: {name}")

        # Rate limiting — be polite
        time.sleep(0.3)

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
        "projects": {
            name: [
                {
                    "name": c.get("name") or "(Untitled)",
                    "uuid": c.get("uuid"),
                    "model": c.get("model"),
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                    "message_count": len(c.get("chat_messages", [])),
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
    print(f"  Conversations: {len(full_conversations)}")
    print(f"  Projects:      {len(project_map)}")
    print(f"  Data dir:      {DATA_DIR}")
    print(f"  Index:         {index_file}")
    print(f"  Conversations: {conversations_dir}/")


if __name__ == "__main__":
    main()
