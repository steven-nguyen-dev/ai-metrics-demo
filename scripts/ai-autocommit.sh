#!/usr/bin/env bash
#
# scripts/ai-autocommit.sh -- Local-side auto-commit for AI coding agents.
#
# Records the AI agent's working-tree changes as a single AI-identified commit,
# LOCALLY (never pushes), so that when the developer keeps editing and commits
# their own work, `git blame` still attributes the AI-written lines to the AI --
# and scripts/ai_attribution.py / the CI report count them correctly. Without
# this, AI output folded into a human commit is invisible to the metric.
#
# Called by:
#   - Claude Code `Stop` hook   (.claude/settings.json)  -> tool "Claude"
#   - Cursor `stop` hook        (.cursor/hooks.json)     -> tool "Cursor"
#
# Usage: ai-autocommit.sh [TOOL]
#   TOOL   Name of the agent (default "AI Agent"). Baked into the commit's
#          author + committer identity and a Co-Authored-By trailer, all of
#          which carry "(AI)" so the attribution classifier (AI_AUTHOR_REGEX)
#          matches them regardless of the tool name.
#
# The developer can amend, split, or discard the commit at any time -- this
# encourages correct attribution by default, it does not force anything.

set -euo pipefail

tool="${1:-AI Agent}"

# Operate only inside a git work tree.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Don't touch a repo that's mid-operation (rebase/merge/cherry-pick/revert) --
# committing there would clobber an in-progress state.
git_dir="$(git rev-parse --git-dir)"
for state in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
  [ -e "$git_dir/$state" ] && exit 0
done

# Nothing staged or unstaged -> nothing to do.
if git diff --quiet && git diff --cached --quiet; then
  exit 0
fi

git add -A

name="${tool} (AI)"
slug="$(printf '%s' "$tool" | tr '[:upper:] ' '[:lower:]-')"
email="${slug}@ai.local"

# Author AND committer AND trailer all carry the AI identity, so the commit is
# unambiguously classified AI however the regex is configured.
export GIT_AUTHOR_NAME="$name"    GIT_AUTHOR_EMAIL="$email"
export GIT_COMMITTER_NAME="$name" GIT_COMMITTER_EMAIL="$email"

git commit -q \
  -m "AI changes via ${tool}" \
  -m "Auto-committed locally by the ${tool} hook so AI line attribution survives later human edits. Amend, split, or discard freely." \
  --trailer "Co-Authored-By: ${name} <${email}>" \
  || exit 0

# Status to stderr so it never pollutes a hook's stdout (Cursor parses stdout).
echo "ai-autocommit: recorded working changes as '${name}' (local, no push)." >&2
