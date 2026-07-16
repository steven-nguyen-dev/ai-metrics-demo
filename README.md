# ai-metrics-demo

A working demo of an **AI-usage line-attribution** setup: measure *how much* of a
pull request's code was written by an AI agent, label the PR by that level, and
capture AI authorship locally so it survives later human edits.

It measures **AI usage, not effort**, and it does not rank people. A PR that is
mostly AI reads as **"AI code, human review"** — the human who owns the PR keeps
full credit. See [`ai-metrics-solution.md`](./ai-metrics-solution.md) for the pitch.

---

## Two sides

**CI side — attribution & reporting.** On every pull request,
[`.github/workflows/ai-attribution.yml`](./.github/workflows/ai-attribution.yml)
runs [`scripts/ai_attribution.py`](./scripts/ai_attribution.py), which `git blame`s
the PR's changed files, classifies each surviving line as AI or human (by matching
the last-touching commit's author, committer, or `Co-Authored-By` trailer against a
configurable pattern), posts a per-file breakdown comment, and applies one label:

| Label | AI usage | Colour |
|---|---|---|
| `ai-usage-low` | 0–29% | violet `#7B61C9` |
| `ai-usage-med` | 30–59% | blue `#3B82D9` |
| `ai-usage-high` | 60–79% | teal `#2AA594` |
| `ai-usage-optimal` | 80–100% | green `#41C363` |

The exact percentage is in the PR comment; the label carries only the level, so the
label catalog stays at four filterable names. The report is computed pre-merge, so
it is **squash-safe**.

**Local side — auto-commit.** [`scripts/ai-autocommit.sh`](./scripts/ai-autocommit.sh)
records an AI agent's working-tree changes as an AI-identified commit **locally (no
push)** the moment the agent finishes, so when you keep editing and commit your own
work, `git blame` still attributes the AI-written lines to the AI. Wired up for:

- **Claude Code** (incl. inside IntelliJ) — [`.claude/settings.json`](./.claude/settings.json) `Stop` hook.
- **Cursor** — [`.cursor/hooks.json`](./.cursor/hooks.json) + [`.cursor/hooks/stop-autocommit.sh`](./.cursor/hooks/stop-autocommit.sh) `stop` hook.

You can always amend, split, or discard the auto-commit — it encourages correct
attribution by default, it never forces anything.

---

## Try it

```bash
git clone https://github.com/steven-nguyen-dev/ai-metrics-demo
cd ai-metrics-demo
git checkout -b test-pr
```

Make a few commits mixing AI and human authorship, e.g.:

```bash
# an "AI" commit (identity matches the classifier)
printf 'ai line\n' >> ai-metrics-demo-1.md
git -c user.name='Claude (AI)' -c user.email='claude@ai.local' commit -am "AI: extend demo-1"

# a human commit (your normal git identity)
printf 'human line\n' >> ai-metrics-demo-1.md
git commit -am "Human: tweak demo-1"

git push -u origin test-pr
```

Open a PR against `main`. The **AI Contribution Report** workflow runs, posts the
AI/human breakdown, and applies the matching `ai-usage-*` label.

> With the Local-side hooks enabled in Claude Code or Cursor, the "AI" commit above
> happens automatically at the end of each agent turn — you just add your human
> edits on top.

---

## Setup notes

- **Actions must be enabled** (Settings → Actions → General → *Allow all actions*).
- The workflow must exist on `main` (it does) for PRs to trigger it.
- **Tune detection** without editing code via a repo Actions **variable**
  `AI_AUTHOR_REGEX` (Settings → Secrets and variables → Actions → Variables). Default
  matches `claude`, `copilot`, `cursor`, `gemini`, a bare `AI`, `-agent`, `[bot]`,
  `bot@`. Exclude generated files via `AI_EXCLUDE_GLOBS`.

## Files

```
.github/workflows/ai-attribution.yml   CI: label + report on each PR
scripts/ai_attribution.py              blame-based AI/human line classifier
scripts/ai-autocommit.sh               shared local auto-commit (AI identity, no push)
.claude/settings.json                  Claude Code Stop hook
.cursor/hooks.json                     Cursor stop hook config
.cursor/hooks/stop-autocommit.sh       Cursor hook wrapper
ai-metrics-solution.md                 the pitch / rationale
ai-metrics-demo-1..3.md                sample files to edit in test PRs
```
