# AI Usage Metrics — Measure How Much, Credit the Human

**Audience:** Architecture Board
**Status:** Pitch
**In one line:** Count lines of code to see *how much AI we're using* — while the human who owns the PR keeps 100% of the credit.

---

## The pitch

We already know **whether** AI is used — adoption is near-universal. PR count answered that
and is now saturated. The open question is **how much** of the code AI actually produces.

**Lines of code are the right unit for that question** — but only for that question:

- **They scale with output.** A 500-line feature and a 3-line fix aren't equal; lines
  capture the difference, commits and PRs don't.
- **They compose cleanly.** AI% = Σ(AI lines) / Σ(all lines), aggregated across PRs, sprints,
  or modules with no weighting.
- **They're git-native.** `git blame` already knows which commit last touched each line.

### What we are — and are not — measuring

We are measuring **AI usage**: how much of the code was produced by AI.

We are **not** measuring **effort**, and we are **not** ranking people. Trying to price the
"effort" behind a line is a trap — it punishes clarity, rewards verbosity, and turns an
observability signal into a performance stick. We refuse that on purpose.

### Reading a high AI number — the part that matters

When a PR comes back **95% AI**, it does **not** mean "no human here."

It means **AI wrote the code; a human reviewed, corrected, and shipped it.**

The PR is owned by a developer. They read it, they signed off, they put their name on the
merge — so **100% of the credit is theirs, with certainty.** AI usage being high doesn't
subtract human value; it **relocates** it to the place senior engineering value increasingly
lives: judgment, review, and ownership.

That's also why we **do not try to measure reviewer effort.** We don't need to. Ownership
already settles credit — the PR belongs to a person, and that person is fully accountable and
fully credited. The AI% only describes **how the work was produced**, never **who deserves
the credit.** Nobody is being replaced by their own tools; a high number is a developer
using leverage well.

> **AI code, human review.** The number is about the tool. The credit is about the person.

---

## How it works, in two layers

The signal is only trustworthy if AI work is recorded as AI work *before* it blends into a
human's commit. So the system has two sides that form a pipeline:

```
   Local side                                CI side
   (your machine)                            (pull request)
   AI output is committed        ─────▶      At PR time, blame classifies
   as an AI commit the                       every surviving line AI vs human
   moment it's authored                      and labels the PR
```

- **Local side** records AI work at authoring time — so AI authorship isn't lost.
- **CI side** classifies and reports at PR time — squash-safe, automatic, zero developer effort.

---

## Solution

### 1. CI side — attribution & reporting *(shipping today)*

Runs automatically on every pull request. No developer action, not on the build's critical
path.

- **What it counts.** Every line surviving in the PR's changed files is attributed to the
  commit that last touched it, and that commit is classified **AI or human** by matching its
  author, committer, and any `Co-Authored-By` trailer against a configurable identity pattern
  (`AI_AUTHOR_REGEX`). Lines a human rewrote move to the human's bucket automatically — the
  review step, made visible.
- **What it posts.** A single PR comment with the AI/human split, plus one of four
  **AI-usage level** labels:

  | Label | AI usage | Colour | Reading |
  |---|---|---|---|
  | `ai-usage-low` | 0–29% | violet `7B61C9` | Mostly human-written |
  | `ai-usage-med` | 30–59% | blue `3B82D9` | Balanced |
  | `ai-usage-high` | 60–79% | teal `2AA594` | AI-heavy |
  | `ai-usage-optimal` | 80–100% | green `41C363` | **AI code, human review** |

  The colours form a sequential violet→blue→teal→green ramp that climbs to a vivid green
  at *optimal* — tuned for GitHub's dark theme, where labels render as bright accents, so a
  PR's level reads at a glance and the target state stands out.

  ```
  ## 🤖 AI Contribution Report
  | Scope                  | AI  | Human |
  | Overall (this PR)      | 78% |  22%  |
  ████████░░  78% AI · 22% human · 1,247 attributed lines     [label: ai-usage-high]
  ```

  The label carries only the level, so the repo's label catalog stays at exactly four
  filterable names; the exact percentage lives in the comment.

- **Trustworthy at scale.** Computed pre-merge so it's **squash-safe**; generated/vendored
  files (lockfiles, minified JS, SVG…) are excluded; blame is bounded to the PR's own commit
  range and the checkout uses a partial clone, so it stays fast on large monorepos;
  superseded runs cancel so only the latest push is scored.
- **Its role.** Pure **observability, not a KPI.** It reports a trend; it never feeds
  performance review. The moment it becomes a scoreboard it corrupts the very labeling it
  depends on.

### 2. Local side — auto-commit on the developer's machine *(proposed)*

**The problem it solves.** AI writes code, the developer keeps editing, then commits
everything under their own name — and the AI signal is gone before CI ever sees it. Not
malice, just friction: making a separate commit is one more step nobody wants to take.

**The fix.** The agent commits **its own output as an AI commit** the instant it finishes —
locally, **no push**. The developer keeps editing on top and commits normally; `git blame`
then splits the two naturally. Even a "lazy" developer keeps correct attribution by default,
because the AI baseline was already recorded. The developer can always amend or overwrite —
**this encourages, it never forces**, and human override always wins.

Why this beats an instruction in a config file: a written rule is a *request* the agent may
skip. A hook is run by the tool itself, every time — deterministic, not dependent on anyone
remembering.

**Targets first — both deterministic via the tool's own hooks:**

| Environment | Trigger | Notes |
|---|---|---|
| **IntelliJ + Claude Code CLI** | Claude Code `Stop` hook | The agent is the CLI; IntelliJ is just the host. Commits each finished turn as an AI commit. |
| **Cursor IDE** | Cursor Agent Hook (`stop` / after-edit) | Deterministic where Hooks are enabled; a soft `.cursor/rules` line is the fallback. |

Both use the **same AI identity/trailer**, so the CI side classifies their commits
identically — same commits from either tool, one CI rule, no divergence.

---

## Boundaries (so the number stays honest)

- **Trend, not precision.** Line counts ignore deletions and weight verbose code. Good for
  direction; never for comparing people.
- **Self-declared identity.** Attribution rests on commit identity; the Local side makes
  the honest path the default, and a periodic audit sampling merged PRs keeps it calibrated.
- **Pair with quality.** AI code reverted next sprint still counted as shipped this sprint —
  read the AI trend next to revert and defect rates.
- **Credit is not computed here.** The PR owner holds it, in full, by definition. This system
  measures usage; it does not — and must not — arbitrate who did the work.
