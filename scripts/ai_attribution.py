#!/usr/bin/env python3
"""AI vs human line attribution for one PR -- simple, single-stage.

Blames the PR's changed files, attributes each surviving line to the commit
that last touched it, aggregates, and prints a Markdown block (coverage-report
style) or JSON. Meant to run at PR time and post one comment on the PR.

Classifier -- read this:
    Blame alone tells us *which commit* a line came from along with its author.
    We classify a commit as AI if its author/committer identity (name or email)
    OR any `Co-Authored-By` trailer on the commit matches the configured AI
    pattern (`--ai-author-regex`). The trailer check matters because agentic
    tools (e.g. Claude Code) commit as the human operator and only disclose
    themselves via a `Co-Authored-By: Claude <noreply@anthropic.com>` trailer --
    author/committer identity alone would misclassify that work as human.

Basis: final-state -- a line the PR added then a human rewrote counts once, as
human (its last touch). This avoids double-counting churn across commits.
Run before a squash merge; squash collapses the commits and erases the signal.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys

# Matches the header line `git blame --line-porcelain` emits before each
# content line, e.g. "abc123...deadbeef 4 4 1" -> group(1) is the commit SHA
# that last touched that line.
SHA_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ \d+")


def run(a):
    """Run a git/gh command and return stdout; raises if it exits non-zero."""
    return subprocess.run(a, capture_output=True, text=True, check=True).stdout


def run_ok(a):
    """Run a command tolerant of failure (e.g. blame on a binary file)."""
    p = subprocess.run(a, capture_output=True, text=True)
    return p.returncode, p.stdout


def is_ai_commit(identity, ai_re):
    """Return True if a commit is AI-authored.

    `identity` combines the commit's author/committer info (`%an <%ae> %cn <%ce>`)
    with any `Co-Authored-By` trailer values, so a commit that a human authored
    but an AI co-authored (the normal case for agentic coding tools) still
    matches `--ai-author-regex` (e.g. `gemini`, `claude`, `AI`)."""
    return bool(ai_re.search(identity))


def blame_shas(merge_base, head, path):
    """Last-touching commit SHA for every line of `path` at `head` (None if binary).

    Runs `git blame --line-porcelain`, which repeats a full header block
    (starting with the SHA_HEADER line) before each content line. Content
    lines are prefixed with a tab, so we track the SHA from the most recent
    header and append it once per content line -- one entry per line in the
    file, in order. `-w` ignores whitespace-only changes, `-M` follows lines
    moved/copied within the file, so reformatting doesn't fake a rewrite.

    Blame is bounded to the `merge_base..head` range rather than the file's
    whole history: lines the PR touched still carry their exact PR-commit SHA,
    while every older line collapses onto the range's boundary commit (its SHA
    is not in the PR set, so the caller discards it anyway). The tally is
    identical to walking full history, but blame stops at the merge-base
    instead of walking back to the file's creation -- the big win on repos with
    deep file history.
    """
    code, out = run_ok(
        ["git", "blame", "-w", "-M", "--line-porcelain",
         f"{merge_base}..{head}", "--", path]
    )
    if code != 0:
        return None
    shas, cur = [], None
    for line in out.split("\n"):
        m = SHA_HEADER.match(line)
        if m:
            cur = m.group(1)
        elif line.startswith("\t"):
            shas.append(cur)
    return shas


def meter(pct):
    """Render `pct` (0-100) as a 10-cell filled/empty block bar for the MD report."""
    filled = int(round(pct / 10.0))
    return "█" * filled + "░" * (10 - filled)


def compute_label(tot_ai, tot_hu):
    """PR label describing this run's level of AI usage (AI share of attributed lines).

    Four fixed levels spanning the whole 0-100% range of AI usage:

        AI usage  0-29%   -> "ai-usage-low"
        AI usage 30-59%   -> "ai-usage-med"
        AI usage 60-79%   -> "ai-usage-high"
        AI usage 80-100%  -> "ai-usage-optimal"

    Fixed level names (not the raw percentage) keep the repo's label catalog to
    exactly four names, each filterable in the PR list; the exact percentage is
    reported in the PR comment. Returns None when there is nothing to attribute
    (the workflow then leaves the PR unlabeled).
    """
    total = tot_ai + tot_hu
    if total == 0:
        return None
    pct = 100.0 * tot_ai / total
    if pct < 30:
        return "ai-usage-low"
    if pct < 60:
        return "ai-usage-med"
    if pct < 80:
        return "ai-usage-high"
    return "ai-usage-optimal"


def render_md(files, pa, ph, total):
    """Render the coverage-style Markdown PR-comment body (returns a string)."""
    files = sorted(files, key=lambda f: f["ai"] + f["human"], reverse=True)
    out = [
        "## \U0001F916 AI Contribution Report",
        "",
        "| Scope | AI | Human |",
        "|---|---:|---:|",
        f"| **Overall (this PR)** | **{pa}%** | **{ph}%** |",
        "",
        f"`{meter(pa)}`  {pa}% AI · {ph}% human · {total:,} attributed lines",
        "",
        f"<details><summary>Per-file breakdown ({len(files)} files)</summary>",
        "",
        "| File | AI % | Human % | Lines |",
        "|---|---:|---:|---:|",
    ]
    for f in files:
        t = f["ai"] + f["human"]
        fa = round(100.0 * f["ai"] / t, 1)
        out.append(f"| `{f['path']}` | {fa}% | {round(100.0 - fa, 1)}% | {t} |")
    out += [
        "",
        "</details>",
        "",
        "<sub>Final-state basis: each surviving line attributed to the commit "
        "that last touched it; a commit counts as AI when its author/committer "
        "identity or a Co-Authored-By trailer matches the AI pattern. Directional "
        "signal, computed at PR time (squash-safe).</sub>",
    ]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    ap.add_argument("--head", default="HEAD", help="PR head ref or SHA")

    # Case-insensitive; matched against author/committer name+email AND any
    # Co-Authored-By trailer (see is_ai_commit()). Covers the common agentic
    # tools/bots by name (claude, copilot, cursor, gemini), a bare "AI" word,
    # and generic bot conventions ("-agent" suffix, "[bot]" GitHub App
    # accounts, "bot@" email prefix). Override per-repo via the
    # AI_AUTHOR_REGEX env var (wired to a GitHub Actions repo variable in
    # the workflow) without editing this file.
    default_ai_regex = r"(?i)(claude|copilot|cursor|gemini|\bAI\b|-agent|\[bot\]|bot@)"
    env_ai_regex = os.environ.get("AI_AUTHOR_REGEX", "").strip()
    ap.add_argument(
        "--ai-author-regex",
        default=env_ai_regex if env_ai_regex else default_ai_regex,
        help="Regex matched against author/committer name and email, "
             "and against any Co-Authored-By trailer",
    )

    # Files whose diffs are noise for this stat: lockfiles are machine-
    # generated/reformatted wholesale by tooling (not hand- or AI-written
    # line by line), minified JS is unreadable, and SVGs are usually
    # exported by design tools. Override via AI_EXCLUDE_GLOBS (comma-
    # separated fnmatch globs) if a repo needs a different set.
    default_exclude = "package-lock.json,yarn.lock,pnpm-lock.yaml,*.min.js,*.lock,*.svg"
    env_exclude = os.environ.get("AI_EXCLUDE_GLOBS", "").strip()
    ap.add_argument(
        "--exclude",
        default=env_exclude if env_exclude else default_exclude,
    )
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    # merge-base (not --base directly) is what GitHub's own PR diff uses --
    # if the base branch has moved on since the PR was opened, we still only
    # attribute the PR's own commits, not unrelated upstream history.
    merge_base = run(["git", "merge-base", args.base, args.head]).strip()

    regex_str = args.ai_author_regex.strip() if args.ai_author_regex and args.ai_author_regex.strip() else default_ai_regex
    ai_re = re.compile(regex_str)

    # One git-log call classifies every commit in the PR range up front, so
    # the per-file blame loop below only needs cheap set membership checks.
    # Record fields are separated by \x1f (unit separator) and records by
    # \x1e (record separator) -- control chars that will never appear in a
    # commit message, so no escaping/quoting is needed to split reliably.
    # The trailers field can itself hold multiple Co-Authored-By values,
    # joined with \x1d (group separator).
    log = run(["git", "log", "--no-color",
               "--format=%H%x1f%an <%ae> %cn <%ce>%x1f"
               "%(trailers:key=Co-Authored-By,valueonly,separator=%x1d)%x1e",
               f"{merge_base}..{args.head}"])
    ai_shas, pr_shas = set(), set()
    for rec in log.split("\x1e"):
        sha, _, rest = rec.strip("\n").partition("\x1f")
        sha = sha.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue  # trailing empty record from the final \x1e
        author_info, _, trailers = rest.partition("\x1f")
        pr_shas.add(sha)
        if is_ai_commit(f"{author_info} {trailers}", ai_re):
            ai_shas.add(sha)

    excludes = [g.strip() for g in args.exclude.split(",") if g.strip()]
    changed = run(["git", "diff", "--name-only",
                   f"{merge_base}..{args.head}"]).split("\n")

    files, tot_ai, tot_hu = [], 0, 0
    for path in changed:
        path = path.strip()
        if not path or any(fnmatch.fnmatch(path, g) for g in excludes):
            continue
        code, _ = run_ok(["git", "cat-file", "-e", f"{args.head}:{path}"])
        if code != 0:
            continue  # deleted at head
        shas = blame_shas(merge_base, args.head, path)
        if shas is None:
            continue  # binary
        # Final-state attribution: every line currently in the file gets
        # credited to whichever PR commit last touched it. Lines whose SHA
        # isn't in pr_shas predate the PR entirely (blame walked past the
        # PR's commits to pre-existing history) and are excluded from both
        # counts -- only the PR's own contribution is measured.
        ai = sum(1 for s in shas if s in ai_shas)
        hu = sum(1 for s in shas if s in pr_shas and s not in ai_shas)
        if ai + hu == 0:
            continue  # only pre-existing lines touched
        files.append({"path": path, "ai": ai, "human": hu})
        tot_ai += ai
        tot_hu += hu

    total = tot_ai + tot_hu
    pa = round(100.0 * tot_ai / total, 1) if total else 0.0
    ph = round(100.0 - pa, 1) if total else 0.0
    label = compute_label(tot_ai, tot_hu)
    markdown = render_md(files, pa, ph, total)

    if args.format == "json":
        # `label` and `markdown` let the workflow do everything from one
        # (single-blame-pass) invocation: post `markdown` as the PR comment and
        # apply `label` to the PR. `label` is null when there's nothing to
        # attribute -- the workflow reads that as "leave the PR unlabeled".
        json.dump({"pct_ai": pa, "pct_human": ph, "ai_lines": tot_ai,
                   "human_lines": tot_hu, "total_lines": total,
                   "merge_base": merge_base, "label": label,
                   "markdown": markdown, "files": files}, sys.stdout)
        print()
        return

    print(markdown)


if __name__ == "__main__":
    main()
