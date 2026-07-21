---
name: trench-engineering
description: Reasoning-first software engineering in the df2-workstation checkout (C:\Users\hooki\df2-workstation only, not sibling checkouts) - architecture, backend and runtime code, cross-component integration, refactoring, bug diagnosis, performance, and code review. Use for any substantive code task there that is not primarily filter/DSP math (trench-dsp), user-facing UI (trench-interface), or build/install/smoke-testing (trench-deliver); it is also the base discipline those skills assume.
---

# TRENCH Engineering

Aim at the user's actual outcome, reached by the strongest current approach — not by replaying whatever pattern happens to be nearby.

## Orient before editing

- Read `AGENTS.md` at the repo root; it is the live contract (runtime facts, ownership boundaries, evidence rules). If a plan conflicts with it, surface the conflict explicitly rather than silently obeying or silently ignoring.
- Discover the current system instead of assuming it: locate the live build roots (`Cargo.toml`, `CMakeLists.txt`, build scripts), then read the specific code the task touches end to end. The repo hosts more than one independent build root; confirm which one the task lives in.
- Check git state and possible concurrent work before editing, and preserve it.

## Constraints vs choices

Separate what must stay true from what merely is true today:

- A **constraint** traces to a live authority: `AGENTS.md`, a test, an on-disk or wire format, an external interface, or behavior users depend on.
- Everything else — module layout, helper style, which crate hosts a function — is a **choice**. Existing patterns are evidence that a way works, not proof it is best. Follow them when sound; improve them when the task warrants it and the diff stays scoped.

When unsure which you are facing, probe (run a test, grep for consumers, exercise the code) before deciding.

## Decide, then act

- Pick the strongest reasonable approach by current engineering practice and state the rationale in a sentence or two. Do not present option menus for decisions the evidence already settles.
- Ask the user only when a consequential fork genuinely needs product authority: scope changes, user-visible behavior tradeoffs, destructive or hard-to-reverse steps.
- Keep the diff scoped to the request. No drive-by refactors, dependency churn, or unrelated cleanup.

## Verify in proportion

- Match verification to risk and choose the smallest check that gives real confidence for the specific change — anywhere from no execution at all to a targeted test, a runtime probe, or byte-level evidence for byte-format code.
- Must: report results truthfully. Failing tests are reported as failing, skipped verification as skipped, and inferences labeled as inference — never claim behavior that was not observed.
