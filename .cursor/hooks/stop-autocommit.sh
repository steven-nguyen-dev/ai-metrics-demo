#!/usr/bin/env bash
#
# Cursor `stop` hook -> shared Local-side auto-commit, tagged as Cursor (AI).
#
# Cursor invokes this when the agent finishes a turn and passes a JSON payload
# on stdin; we don't need it. An observational `stop` hook requires no stdout
# response, so we simply delegate to the shared script.

set -euo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
exec "$root/scripts/ai-autocommit.sh" Cursor
