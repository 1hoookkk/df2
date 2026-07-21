# TRENCH Workspace Contract

> **RULE #1 — USE THE TOOLCHAIN, NEVER HAND-ROLL.** Every number that ends up in
> a body must be read from a table or computed by the real authoring tool — never
> hand-typed to get a result on screen fast. If you catch yourself typing a
> frequency, radius, or coefficient you did not read or compute, STOP and go find
> the tool that produces it. Optimizing for looking done over being correct
> through the tools is THE recurring failure. Slower-but-real beats fast-but-invented.

1. **The DSP Bible:** `C:\Users\hooki\df2-workstation\FILTER_NOTEBOOK.md` holds the absolute DSP laws, historical verdicts, dead ends, and architecture rules. Read the relevant section before authoring, fitting, or judging. Do not invent new doctrine.

2. **The Engine:** `trench-core` is the only audio engine, compiler, codec, and runtime authority. Validate through the code and bytes that actually ship.

3. **Evidence Boundaries:** P2K/X3/reference material is study evidence only. Never copy protected bytes, names, or assets into this branch. Follow the notebook's provenance and clean-room rules.

4. **Start From Reality:** Inspect the live worktree, current artifact, runtime path, and existing tools before changing anything. Reuse proven scripts and code paths. Never infer the current state from memory, a handoff summary, or a plausible story when the repository can answer directly.

5. **Hold the Literal Task:** Keep the current target, locked constraints, and next concrete proof in view. Tyson's latest wording overrides your interpretation. When he names a file, preset, stage, law, render, or prior version, inspect that exact thing before generalising. If redirected, drop assumptions from the old interpretation and continue from the correction; do not merely rename the old plan.

6. **No Invented Abstractions:** Do not create new laws, stage classes, families, vocabularies, schemas, wrappers, pipelines, or architectural layers unless they already exist in the repository or Tyson explicitly asks for them. Use the repository's actual nouns and data structures. Treat every inferred model as a temporary hypothesis, not a foundation. One successful example never proves a universal decode, mapping, or law.

7. **Momentum Loop:** Work in a tight loop: inspect → make the smallest reversible change → run it → inspect the real evidence → decide the next change. Keep one scoped change per verification step. Do not stop for a long explanation, retrospective, report, or menu of options while the next evidence-bearing action is clear and authorised. Continue until the result passes, a real blocker is proven, or an explicit approval boundary is reached.

8. **Smallest Real Proof First:** Before a batch, generator, refactor, full bake, roster change, asset swap, install, or success report, prove one representative case end-to-end. Test on the surface that makes the decision:

   * DSP: packed shipping runtime, then the ear on suitable broadband material.
   * Visuals: true runtime/plugin scale and context, not an attractive viewport or enlarged proxy.
   * Formats and serialization: emitted bytes, round-trip/no-op identity, parity tests, and the shipping reader.

   A plot, stability gate, successful build, or proxy metric proves only itself; it does not prove musical character, visual correctness, or usefulness.

9. **Method Before Tuning:** When repeated parameter changes preserve the same failure, stop tuning and challenge the method, representation, target, or decoder. Do not force different sources through one generic transform and then claim the outputs are meaningfully different. Prefer a direct null, comparison, render, or audition against the real target over an aggregate model or family average.

10. **Corrections Are Constraints:** A user correction is new ground truth. Apply it immediately and invalidate downstream conclusions built on the old assumption. Do not defend the prior interpretation, over-explain the mistake, or continue work that depended on it. If Tyson says “stay on track,” resume the active target and next proof immediately.

11. **Productive Tooling Only:** Search for an existing implementation before writing an analyzer, decoder, framework, or helper. Create tooling only when it directly enables the next proof or is clearly durable. Exploration must end in one of three useful outcomes: a changed artifact, a confirmed or falsified hypothesis, or a proven blocker. Do not manufacture activity through broad scans, rankings, taxonomies, or documentation that do not change the next decision.

12. **Scale Only After Validation:** Do not fan one unproven idea into many presets, files, frames, or installed artifacts. First prove that the representative result is genuinely distinct and correct on the final decision surface. Respect explicit approval boundaries for accepted assets, roster changes, builds, installs, and promotion. Preserve the dirty worktree, backups, and accepted masters.

13. **Interaction:** Be direct and concise. Status updates should state what changed, what the evidence says, and what happens next. Answer subjective opinions, visual judgments, and casual questions directly without triggering an audit unless requested. Do not repeatedly ask permission already given, and do not ask Tyson to choose between technical branches that repository evidence can decide.

14. **No Premature Success:** Never call something done, fixed, correct, decoded, approved, or “the one” on a first pass. Review the actual rendered, measured, audible, or byte-level evidence first. Show the proof, invite the verdict where taste or approval is required, and correct your own claim before Tyson has to. A confident wrong claim costs far more than an honest “not there yet.”

15. **Durable Memory:** Record only verified, reusable truths. Do not write a success report while the result is still moving. When work changes a durable DSP rule, verdict, tool path, or dead end, update the pointer in `FILTER_NOTEBOOK.md` in the same commit. Remove or correct stale claims as soon as they are disproven.

16. **Finish Cleanly:** Leave the workspace with scoped changes, clean evidence, and no unrelated churn. Report the artifacts changed, the exact proofs run, the current result, and any honest remaining caveat. Ensure byte-identical no-op saves, body/cart parity, and clean Git history.

17. **Suspect the Representation Before the Dead End:** When a decode or interpretation yields degenerate results (unstable poles, features in the wrong place, collapsed corners, nonsense values), the prime suspect is the REPRESENTATION — codec, word layout, scale, byte order, axis mapping — not the data, the engine, or the idea. Read the authoritative on-disk spec for how the bytes actually decode (the Ghidra RE oracles under `df2/ref/`, the codex, the shipped `trench-core`/`pyruntime` decoder) and reuse that exact path before declaring a dead end or substituting an indirect proxy (an audio render, a curve fit) for a decode the code already specifies. A wrong representation can read plausibly for one case and collapse on another — one "looks right" is never validation.
