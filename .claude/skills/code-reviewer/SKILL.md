---
name: code-reviewer
description: Cold review of a pull request or branch diff — the ask first, then the codebase's own standard, then the floor beneath it. Tuned for Java Spring Boot backends, applies to any stack. Use on a PR or Jira URL or number, "review this branch / diff / PR", "review since <ref>", or at the end of implementation before the pull request.
version: 1.3.0
disable-model-invocation: false
context: fork
background: false
---

# Code review

**Diagnostic only** — name the defect, where it is, and what it contradicts. The fix is the author's.

**Cold means cold.** If the conversation that produced this code is in your context, report that and
stop.

**Priority when findings compete:** business correctness → security → the documented standard → code
quality.

**Review one tree.** Resolve the PR head or ref to a SHA and cite every line against it. Stop if it
does not resolve, or the diff is empty.

**Run the diff twice.** **Conformance** — the diff against the requirement documents §1 finds.
**Regression** — the same diff with those documents set aside, answering one question: what worked at
the base and does not now. Give the regression pass its own context, so the requirement never frames
it. *Done when* both passes have returned and every finding names the pass that produced it.

---

## 1. The ask, before the diff

- **Documents the human supplied** — in full, before opening the diff.
- **A PR URL or number** — the description, its linked issues, and every file it links.
- **A Jira key anywhere** — title, body, branch name, commit messages — the issue and its attachments.
- **Nothing named** — the commit messages, and any spec sitting beside the changed code.

Mark each source **read**, **`not found`** (searched; absent), or **`unreachable`** (exists, no
access — no connector, no auth, dead link). A failed fetch is `unreachable`, and the answer stays
unsupplied. Only `unreachable` is something the human fixes in a minute, so it never hides inside
`not found`.

With no requirement anywhere, say so at the head of the report and hold the diff against its own
names, commit messages and tests.

---

## 2. The standard

Nearest the changed files wins over the repo root:

1. **A quality document** — guidelines, contributing rules, `CLAUDE.md` / `AGENTS.md`, a constraining
   ADR. Found, it is the authority.
2. **Lint, static analysis, compiler settings** — what a rule there already fails on, you do not
   report. Confirm the rule is *enabled* before crediting it.
3. **The nearest working sibling**, read at the diff's base. With no document, a consistent local
   convention is the standard; name the file per finding.
4. **The stack's accepted practice**, then §4.

Name what you found, or write `none found` — a verdict earned against no authority says so out loud.

---

## 3. What review overlooks

Correctness, edges, failure paths, concurrency, resource lifecycle and naming you already read for.
These are the ones that go missing:

- **Scope creep** — a behaviour in the diff that no requirement asked for.
- **Business meaning over green tests** — code that satisfies its tests and still violates what the
  requirement meant. The highest-value finding available.
- **Terminus** — every field the diff moves reaches one: a column, an outbound field, a response, a
  log line. Account for each at its terminus, in the shape and unit it arrived in. A field landing
  nowhere, or landing changed, is a **silent drop**, and the count is its only signal — no exception
  is thrown and no test goes red. A requirement naming the field makes it a `blocker`; otherwise
  raise it as a question, since intent lives outside the code.
- **Provenance** — every value the diff touches had a supplier at the base. For each read the diff
  removes, each field a framework or mapper filled before the new code runs, and each condition the
  diff rewrote: name who supplied the value then, and who supplies it now. A supplier with no
  successor is a silent regression — no exception thrown, no test red. Count remaining references to
  any member the diff stopped reading; zero across the module is the finding. *Done when* every
  deleted read, every pre-filled field, and every rewritten condition is accounted for at both ends.
- **Weakened tests** — a test deleted, disabled, or made to pass by relaxing an assertion. Look for it
  deliberately; it is a `blocker`.
- **Both versions running** — through the rollout and on the rollback: does the old code still work
  against this schema, field or message shape?
- **Authorisation per entry point**, not authentication once.
- **The stack's own traps** — name the stack and version from the build file, list its traps *before*
  reading for them, then read. Java Spring Boot is the expected target.

---

## 4. The floor

Every run, standard or not. Fowler ch.3, matched against the diff:

Mysterious Name · Duplicated Code · Long Function · Long Parameter List · Feature Envy · Data Clumps ·
Primitive Obsession · Repeated Switches · Shotgun Surgery · Divergent Change · Speculative Generality ·
Message Chains · Middle Man · Refused Bequest

- **Never a blocker alone** — a smell is `note` until a documented rule or a requirement lifts it, and
  it names itself in *what it contradicts*.
- **Suppressed only by something earned** — a documented rule, an enabled tooling rule, or a sibling
  making the choice on purpose. A sibling repeating the habit is evidence *for* the finding.
- **Say what you suppressed** — one line, each smell dropped and what dropped it.

---

## 5. The report

Head it with three lines: **target** — PR number and head SHA, or the fixed-point SHA, with file and
commit counts · **authorities** — requirement sources · standard · stack, carrying `none found` or
`unreachable (<why>)` where that is the truth · **verdict** — `blockers: n · defects: n · notes: n`.

A finding is five things:

1. **What is wrong** — one sentence.
2. **Where** — `path:line` on the added lines, read from the pinned SHA, then the quoted line. A line
   you cannot pin says so in place of the number.
3. **What it contradicts** — the requirement source, the standard's rule, the named sibling, the stack
   practice, the named smell, or `quality`.
4. **Severity** — `blocker` (no merge without a human disposition), `defect` (fix before merge, or
   take a disposition), `note`.
5. **Blast radius** — where the failure surfaces: the catch that swallows the throw, the status the
   caller receives, the row persisted, the value sent onward. Severity is argued from the blast
   radius; a contradicted requirement raises it one step. *Done when* every finding names a boundary a
   human can observe it at.

Group them under three headings in this order — **Blockers**, **Defects**, **Notes**. Within a group,
requirement findings first, then standard, then quality. A group holding nothing reads `0 findings`
rather than disappearing. One finding per place, filed at the worse severity where it turns up twice.

Close with coverage — files reviewed, anything out of scope, and §4's suppression line.

Post it in chat, and write `code-review-report.md` every run — beside the requirement documents you
read, else to a path the repo's own ignore rules exclude. Name that path in the report. A tracked path
puts the review into the next pull request diff; where every candidate path is tracked, say so and
name the one you used.
