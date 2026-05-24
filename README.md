# repo-triage-agent

A Python CLI that fetches open GitHub issues and pull requests (10 at a time), uses Claude Haiku to analyze each one against real GitHub metadata, and outputs a human-readable triage report — with clear verdicts on what to close, what needs attention, and what's ready to merge.

No automated actions. Pure analysis output for human review.

**Author**: [yana pandey](https://github.com/yanapandey)

---

## How It Works

1. Fetches open issues/PRs from any GitHub repository (most recent first)
2. For each item, reads the title, description, comments, and files touched
3. Sends that data to Claude Haiku for analysis
4. Detects duplicates using rule-based signals (requires 2+ signals — never relies on LLM alone)
5. Prints a verdict for each item — no writes back to GitHub

---

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Set up environment variables**
```bash
cp .env.example .env
```
Edit `.env` and fill in:
```
GITHUB_TOKEN=ghp_your_token_here
ANTHROPIC_API_KEY=sk-ant-your_key_here
```

- GitHub token: [github.com → Settings → Developer settings → Tokens (classic)](https://github.com/settings/tokens) — needs `repo` scope (read-only is fine)
- Anthropic API key: [console.anthropic.com](https://console.anthropic.com)

---

## Usage

```bash
python triage.py --repo owner/repo [--type issues|prs|both] [--page N]
```

| Flag | Description | Default |
|------|-------------|---------|
| `--repo` | GitHub repo in `owner/repo` format (required) | — |
| `--type` | `issues`, `prs`, or `both` | `both` |
| `--page` | Page number (10 items per page, most recent first) | `1` |

### Examples

```bash
# Triage latest 10 issues and PRs
python triage.py --repo acme-org/backend-api --type both --page 1

# Next batch
python triage.py --repo acme-org/backend-api --type both --page 2

# Only PRs
python triage.py --repo acme-org/backend-api --type prs --page 1

# Only issues
python triage.py --repo acme-org/backend-api --type issues --page 1
```

---

## Output

Each item gets one of three verdicts:

```
[X] CLOSE THIS           — Duplicate, already resolved, or not needed
[!] THIS NEEDS ATTENTION — Valid open issue/PR that needs work or a decision
[+] REVIEW AND MERGE THIS — PR ready for human review and merge
```

Example output:
```
========================================================================
GITHUB TRIAGE AGENT
========================================================================
Repository : acme-org/backend-api
Type       : both
Page       : 1 (items 1–10, most recent first)
========================================================================

--- ITEM 1 of 10 ---
[X] [PR #204] Fix user session timeout
Action : CLOSE THIS
Reason : DUPLICATE of #198 — same files touched (session.py, auth.py),
         near-exact title match. PR #198 already merged.

--- ITEM 2 of 10 ---
[!] [ISSUE #201] API returns 500 on empty payload
Action : THIS NEEDS ATTENTION
Reason : No existing fix found in comments or linked PRs. Reproducible
         with curl. Needs investigation and a fix.

--- ITEM 3 of 10 ---
[+] [PR #199] Add rate limiting to /login endpoint
Action : REVIEW AND MERGE THIS
Reason : Well-scoped change, no duplicates found, tests passing, approved
         by one reviewer.

========================================================================
TRIAGE SUMMARY
[X] CLOSE THIS (1):            #204
[!] THIS NEEDS ATTENTION (1):  #201
[+] REVIEW AND MERGE THIS (1): #199

Items remaining: ~27  →  Run with --page 2 to continue
========================================================================
```

---

## Cost

- **GitHub API**: Free (rate limit: 5,000 req/hour)
- **Claude Haiku**: ~$0.03 per 10-item run (~$2–3/month at 2 runs/week)

---

## Project Structure

```
repo-triage-agent/
├── triage.py          Main CLI entry point
├── github_client.py   GitHub REST API wrapper (read-only)
├── analyzer.py        Claude Haiku integration and duplicate detection
├── requirements.txt   Python dependencies
├── .env.example       Environment variable template
└── README.md
```

---

## Notes

- The agent is **read-only** — it never closes issues, merges PRs, posts comments, or writes anything back to GitHub
- Duplicate detection requires **at least 2 signals** (linked reference, same files, same error message, title match) — LLM semantic match alone is never enough to call something a duplicate
- Works with any public GitHub repository; private repos require a token with `repo` scope
