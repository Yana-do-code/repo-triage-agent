#!/usr/bin/env python3
"""
triage.py - GitHub Issue and PR Triage Agent CLI

Usage:
  python triage.py --repo owner/repo --type both --page 1
  python triage.py --repo owner/repo --type issues --page 2
  python triage.py --repo owner/repo --type prs
"""
import argparse
import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from github_client import GitHubClient
from analyzer import Analyzer

BATCH_SIZE = 10

ACTION_ICONS = {
    "CLOSE THIS": "X",
    "THIS NEEDS ATTENTION": "!",
    "REVIEW AND MERGE THIS": "+",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Triage open GitHub issues and PRs using Claude AI."
    )
    parser.add_argument(
        "--repo", required=True,
        help="Repository in owner/repo format (e.g. torvalds/linux)",
    )
    parser.add_argument(
        "--type", choices=["issues", "prs", "both"], default="both",
        help="Which items to fetch: issues, prs, or both (default: both)",
    )
    parser.add_argument(
        "--page", type=int, default=1,
        help="Page number to fetch (10 items per page, default: 1)",
    )
    return parser.parse_args()


def split_repo(repo_arg):
    parts = repo_arg.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        print("ERROR: --repo must be in owner/repo format (e.g. octocat/Hello-World)", file=sys.stderr)
        sys.exit(1)
    return parts[0], parts[1]


def fetch_batch(gh, owner, repo, item_type, page):
    """Fetch up to BATCH_SIZE items of the given type."""
    if item_type == "both":
        half = BATCH_SIZE // 2
        issues = gh.get_open_issues(owner, repo, page=page, per_page=half)
        prs = gh.get_open_prs(owner, repo, page=page, per_page=half)
        tagged = [dict(i, _item_type="ISSUE") for i in issues] + [dict(p, _item_type="PR") for p in prs]
        return tagged[:BATCH_SIZE]
    elif item_type == "issues":
        items = gh.get_open_issues(owner, repo, page=page, per_page=BATCH_SIZE)
        return [dict(i, _item_type="ISSUE") for i in items]
    else:
        items = gh.get_open_prs(owner, repo, page=page, per_page=BATCH_SIZE)
        return [dict(p, _item_type="PR") for p in items]


def enrich_items(gh, owner, repo, items):
    """Fetch comments and (for PRs) file diffs for each item."""
    enriched = []
    for item in items:
        number = item["number"]
        itype = item["_item_type"]
        comments = gh.get_issue_comments(owner, repo, number)
        pr_files = None
        if itype == "PR":
            try:
                pr_files = gh.get_pr_files(owner, repo, number)
                item["_pr_files"] = pr_files
            except Exception:
                pr_files = []
                item["_pr_files"] = []
        item["_comments"] = comments
        enriched.append(item)
    return enriched


def print_separator(char="-", width=72):
    print(char * width)


def format_result(result, idx, total):
    icon = ACTION_ICONS.get(result.action, "?")
    lines = [
        "",
        "--- ITEM " + str(idx) + " of " + str(total) + " ---",
        "[" + icon + "] [" + result.item_type + " #" + str(result.number) + "] " + result.title,
        "Action:  " + result.action,
        "Reason:  " + result.reason,
    ]
    if result.duplicate_of:
        lines.append("Duplicate of: #" + str(result.duplicate_of))
    if result.signals:
        lines.append("Signals: " + "; ".join(result.signals))
    return "\n".join(lines)


def print_summary(results, owner, repo, page, total_open):
    close_items = [r for r in results if r.action == "CLOSE THIS"]
    attention_items = [r for r in results if r.action == "THIS NEEDS ATTENTION"]
    merge_items = [r for r in results if r.action == "REVIEW AND MERGE THIS"]

    def fmt_list(items):
        if not items:
            return "(none)"
        return ", ".join("#" + str(r.number) for r in items)

    print("")
    print_separator("=")
    print("TRIAGE SUMMARY")
    print_separator("=")
    print("Repository:  " + owner + "/" + repo)
    print("Page:        " + str(page) + "  (batch size: " + str(BATCH_SIZE) + ")")
    print("Scanned:     " + str(len(results)) + " items")
    print("Date:        " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("")
    print("[X] CLOSE THIS (" + str(len(close_items)) + "):          " + fmt_list(close_items))
    print("[!] THIS NEEDS ATTENTION (" + str(len(attention_items)) + "): " + fmt_list(attention_items))
    print("[+] REVIEW AND MERGE THIS (" + str(len(merge_items)) + "): " + fmt_list(merge_items))
    if total_open is not None:
        remaining = max(total_open - (page * BATCH_SIZE), 0)
        print("")
        print("Total open items (approx): " + str(total_open))
        print("Items remaining:           ~" + str(remaining))
        if remaining > 0:
            next_page = page + 1
            print("  --> Run with --page " + str(next_page) + " to continue")
    print_separator("=")


def main():
    args = parse_args()
    owner, repo = split_repo(args.repo)
    item_type = args.type
    page = args.page

    gh = GitHubClient()
    analyzer = Analyzer()

    print("")
    print_separator("=")
    print("GITHUB TRIAGE AGENT")
    print_separator("=")
    print("Repository: " + owner + "/" + repo)
    print("Type:       " + item_type)
    print("Page:       " + str(page))
    print("Batch size: " + str(BATCH_SIZE))
    print("")

    # Optionally get total count for progress reporting
    total_open = None
    try:
        counts = gh.count_open_items(owner, repo)
        if item_type == "issues":
            total_open = counts["issues"]
        elif item_type == "prs":
            total_open = counts["prs"]
        else:
            total_open = counts["issues"] + counts["prs"]
        print("Open items found: " + str(total_open) + " total (" + str(counts["issues"]) + " issues, " + str(counts["prs"]) + " PRs)")
    except Exception as e:
        print("Note: Could not fetch total count: " + str(e))

    print("Fetching page " + str(page) + " ...")
    print("")

    items = fetch_batch(gh, owner, repo, item_type, page)
    if not items:
        print("No items found on page " + str(page) + " for type=" + item_type + ".")
        print("You may have reached the end of the list.")
        return

    print("Enriching " + str(len(items)) + " items (fetching comments and diffs) ...")
    items = enrich_items(gh, owner, repo, items)

    print("Analyzing with Claude Haiku ...")
    print_separator()

    results = []
    for idx, item in enumerate(items, start=1):
        itype = item.pop("_item_type")
        comments = item.pop("_comments", [])
        pr_files = item.pop("_pr_files", None)
        print("  Analyzing #" + str(item["number"]) + " [" + itype + "]: " + item.get("title", "")[:60] + " ...", end="", flush=True)
        try:
            result = analyzer.analyze(
                item=item,
                item_type=itype,
                comments=comments,
                pr_files=pr_files,
                all_items=items,
            )
            results.append(result)
            print(" [" + ACTION_ICONS.get(result.action, "?") + "]")
        except Exception as e:
            print(" ERROR: " + str(e))

    print_separator()
    print("")
    print("DETAILED RESULTS")
    print_separator()

    for idx, result in enumerate(results, start=1):
        print(format_result(result, idx, len(results)))

    print_summary(results, owner, repo, page, total_open)


if __name__ == "__main__":
    main()
