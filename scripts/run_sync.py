"""CLI entry point for Forge OS manifest-driven sync to Claude.ai.

Usage:
    python scripts/run_sync.py                    # sync all enabled targets
    python scripts/run_sync.py --dry-run          # compile, show plan, don't push
    python scripts/run_sync.py --target UUID      # sync one project
    python scripts/run_sync.py --validate         # validate manifest only
    python scripts/run_sync.py --manifest path    # alternate manifest file
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vectordb.sync_manifest import load_manifest, resolve_all_targets, validate_manifest
from vectordb.sync_engine import sync_all, sync_one


def _print_plan(results: dict) -> None:
    """Pretty-print sync results / dry-run plan."""
    print(f"\n{'DRY RUN' if results.get('dry_run') else 'SYNC COMPLETE'}")
    print(f"  Targets: {results.get('targets_synced', 1)}")
    print(f"  Docs compiled: {results.get('total_docs_compiled', 0)}")
    print(f"  Docs cleaned up: {results.get('total_docs_cleaned', 0)}")

    for r in results.get("results", [results] if "docs" in results else []):
        name = r.get("claude_name", r.get("project_uuid", "?"))
        print(f"\n  [{name}]")

        if r.get("status") == "skipped":
            print(f"    Skipped: {r.get('reason', 'unknown')}")
            continue

        for doc in r.get("docs", []):
            size_kb = doc["content_length"] / 1024
            print(f"    {doc['file_name']}: {doc['item_count']} items ({size_kb:.1f} KB)")

        if r.get("docs_cleaned", 0) > 0:
            print(f"    Cleaned up {r['docs_cleaned']} stale doc(s)")


def main():
    parser = argparse.ArgumentParser(description="Forge OS manifest sync to Claude.ai")
    parser.add_argument("--dry-run", action="store_true", help="Compile only, don't push")
    parser.add_argument("--target", type=str, help="Sync single project UUID")
    parser.add_argument("--validate", action="store_true", help="Validate manifest only")
    parser.add_argument("--manifest", type=str, help="Alternate manifest path")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.validate:
            manifest = load_manifest(args.manifest)
            warnings = validate_manifest(manifest)
            targets = resolve_all_targets(manifest)

            if args.output_json:
                print(json.dumps({"warnings": warnings, "targets": len(targets)}, indent=2))
            else:
                print(f"Manifest valid. {len(targets)} enabled target(s).")
                if warnings:
                    print("\nWarnings:")
                    for w in warnings:
                        print(f"  - {w}")
                else:
                    print("No warnings.")

                print("\nResolved targets:")
                for t in targets:
                    print(f"  {t['claude_name']} ({t['project_uuid'][:8]}...)")
                    print(f"    Sources: {', '.join(t['internal_names'])}")
                    print(f"    Types: {', '.join(t['data_types'])}")
                    print(f"    Merge: {t['merge']}")
            return

        if args.target:
            result = sync_one(
                args.target,
                dry_run=args.dry_run,
                manifest_path=args.manifest,
            )
            if args.output_json:
                print(json.dumps(result, indent=2, default=str))
            else:
                _print_plan(result)
            return

        results = sync_all(dry_run=args.dry_run, manifest_path=args.manifest)
        if args.output_json:
            print(json.dumps(results, indent=2, default=str))
        else:
            _print_plan(results)

    except FileNotFoundError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"Sync failed: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
