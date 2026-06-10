**Defining a shipping body**

I need to include various specifications like four corner orders (M0_S0, M1_S0, M0_S1, M1_S1) and ensure I have exactly six serial DF2T biquads with five packed u16 words per stage. The canonical body size should be 240 bytes, and both poles and zeros matter. I can't include random poles or zeros, and reference material should be studied, not copied. I should also ensure there's a clear distinction between editable representations and diagnostic ones while planning the patch-ready implementation.

**Designing final specifications**

I need to finalize the specifications, perhaps by including runtime format constraints, inferred UI semantics, and recommendations. I want to clarify the DF2T biquad packed format, which is structured as 4 corners multiplied by 6 stages multiplied by 5 u16, resulting in 240 bytes. I'll define the primary editable representation as the root-domain stage surface, which involves pole and zero pairs in root coordinates, along with gain normalization and metadata. I'll make sure to address diagnostic elements, like decoded coefficients and response plots from packed interpolation, since that's crucial.

**Clarifying construction details**

I'm realizing that the author edits roots for each corner and then compiles them into packed corners, while runtime involves interpolating packed words. For diagnostics, I want to include decoded roots at specific checkpoints, a coefficient table, and packed words. I must make zeros explicit in the UI, defining handles for poles and zeros per stage, ensuring visibility. Also, I need to decide on a smallest useful v0 constructor palette and specify how many serialized stage slots each operation would consume, starting with a blank normalized biquad, which likely consumes one slot.

**Defining constructor palette**

I’m considering a safe identity or gentle stage for manual pole and zero editing as a foundation. For the v0 constructor palette, I’d include options like a 2-pole Cliff for low/high pass, which would consume 1 slot, and a 4-pole Cliff that requires 2 slots. I might want to add a 6-pole option since I have exactly six stages available. It seems I also need to include the "Swept EQ width law" and "Peak/Shelf Morph" for variety. I’ll ensure the palette remains minimal while still meeting requirements.

**Defining v0 constructors**

I’m thinking about including a "Two-Frame Sweep" in the two-frame constructor that writes M0 and M1 while duplicating S0 and S1, maybe as part of the foundational operations. For v0 constructors, I’ll outline a few options: 

A. Identity/Manual Stage, which consumes 1 slot and initializes neutral roots and gains.  
B. Resonant Pair, consuming 1 slot, for an editable biquad that peaks, dips, or notches around a center.  
C. Cliff Foundation for low/high pass filters, consuming 1-3 slots with distributed poles.  
D. Shelf/Tilt Foundation, which consumes 1 slot for low/high shelf approximations and might need 2 slots for tilts.

**Finalizing constructor slots**

I’m deciding that the "Tilt/Shelf" should consume 1 slot for a single shelf and 2 slots for opposed tilts (low and high). I want to keep this minimal. The "Two-Frame Morph Program" would consume the same number of slots as the selected constructor in both M0 and M1, but I'm not sure if it counts as a constructor itself. It might be better classified within foundation operations, not the palette. 

For the v0 minimal palette, I’m considering the following: 
1. Manual biquad (1 slot)
2. Cliff Foundation with 2/4/6 pole LP/HP (1/2/3 slots)
3. Shelf/Tilt stage (1 slot, or 2 if both are used)
4. Peak/Canyon / Swept EQ Actor (1 slot).

**Defining constructor operations**

For the "Two-Frame Morph Program," I'm thinking this will duplicate across Secondary without consuming extra slots. I might also include a "Band window" that functions as a bandpass/notch filter, consuming 1 slot. 

I want to define a "Foundation Operations" section with various constructors:

1. Insert Manual Stage (1)
2. Cliff Foundation (1/2/3)
3. Shelf/Tilt Foundation (1 slot, or 2 for opposed tilts)
4. Resonant Peak/Canyon Actor (1)
5. Swept EQ Actor (1)
6. Two-Frame Program wrapper, which has the same slots as the enclosed constructor.

Since "Peak/Canyon" and "Swept EQ" overlap, I could combine them into a "Resonant Actor / Swept EQ" that consumes one slot. This actor would include controls for center frequency, pole radius, and width law, allowing it to morph into a peak, dip, notch, or formant. The idea of a "Peak/Shelf Morph" also sounds interesting—it could be an evolution from peak/canyon to shelf, consuming 1 slot.

**Deciding on the v0 constructor palette**

I'm considering whether the "Peak?Shelf Two-Frame Program" should consume 1 serialized stage slot, writing different root layouts at M0 and M1 while duplicating across Secondary. It seems useful and aligns with the requirement for two-frame, but I wonder if it adds too much complexity. 

For the v0 palette, I’m outlining the following:

- Identity/Manual Biquad: 1 slot
- Cliff Foundation (LP/HP order 2/4/6): 1/2/3 slots
- Shelf/Tilt Foundation: 1 slot for a single shelf, 2 for opposed tilts
- Resonant Peak/Canyon (Swept EQ Actor): 1 slot
- Peak?Shelf Two-Frame Program: 1 slot (keeping it simple)

I think of the "Bundle wrapper" as an operation rather than a constructor but still useful to clarify. I'm focusing on keeping the smallest useful palette to about five constructors, ensuring that each consumes slots based on corners while noting that the compiled runtime can still have 6 slots per corner.

**Defining the Two-Frame Program Behavior**

The two-frame program will consume one serialized slot at the same index across all four corners. I want to mention that it utilizes one of the six available serial stage slots. For editing, when dragging a pole or zero, I think the default edit scope should be set to "Current Corner only." This avoids hidden changes, especially if the active stage has a link.

If the default drag scope is just the current corner, it won’t propagate unless explicitly set with a link lock/scope selector. 

So, I’ll state: the default for any manual drag of a pole or zero handle is "Current corner, selected stage, selected root pair only." The modifier or toolbar can change this to Edge or Whole Field to prevent hidden degenerate surfaces. Lastly, after creating the two-frame program, the secondary duplicates won't be live links by default, although lawful constructors could start degenerating across Secondary.

**Defining Duplication and Corner Semantics**

If duplication is a copy, dragging one corner won't update others across the stages, allowing for natural expansion. If links are active, I should define that we need to break those links. Constructors can create copies with optional "soft recipe link" metadata, ensuring there's no live DSP link unless the author activates it. 

When dragging, it should break the recipe lock on the touched corner, editing only that corner. 

I think we’ll order the corners specifically as `M0_S0`, `M1_S0`, `M0_S1`, and `M1_S1`. For visualization, a 2x2 screen layout with the top row for S0 (left M0/M1) and the bottom for S1 sounds effective. 

Concerning packed-domain interpolation, we must consider interpolating packed u16 data carefully to avoid unintended decoding. A "release proof" should utilize packed-domain interpolation alongside trench_core FFI plots. We need to specify audits that compile into 240 packed bytes and evaluate the runtime response based on the actual interpolation path, including endpoints, corners, edges, center, and possibly a dense grid.

**Establishing Hard Gates for Stability**

I need to ensure stability at endpoints and throughout the audit grid by using runtime decoding. Both poles and zeros are essential, so I might need to decode roots at checkpoints as well. 

Regarding hard export gates, here are the specifics I want to check: 

1. The body must have four corners in the correct order.
2. There should be exactly six stages per corner, with five u16 per stage, totaling 240 bytes.
3. There should be no empty or unfilled slots (identity is okay), and no disabled stages.
4. Any packing/unpacking must be a round trip that remains finite and within format bounds.
5. Packed-domain interpolation using trench_core FFI must return a finite response and stable poles for all stages. 

If runtime FFI can reveal roots, that might help, but I'll also need to ensure that any decoded pole radius stays below one at all endpoints and checkpoints, setting a threshold of radius less than 0.999999 to account for quantization.

**Implementing Stability Gate Protocols**

I need to set specific gates like ensuring `r < 1.0` with warnings for values exceeding `0.995`. It's crucial to prevent NaN or Inf values in coefficients, gain, and plots while avoiding overflows in packed data.

I should ensure that the reference or AI metadata is not included in the output body, and there should be no external dependencies. It might be tricky to enforce no source audio or images, but we can require exports to exclude these elements.

We can't have random or generated taste sources either. If a constructor shows some random attributes or proves AI selection, we have to block the export until human edits are made. 

Also, the validity of sample rates is crucial; if the body is sample-rate independent, we still need to ensure normalized frequencies are valid for the target Fs. Roots must be real-coefficient, valid, and in conjugate pairs with pole radii below 1 before packing.

Lastly, for FFI plot endpoint verification, I need proof that bundle hashes meet standards, with warnings for near-unit poles exceeding `0.995` or response magnitudes above +18 dB.

**Establishing Warning Protocols**

I’m considering using warnings instead of gates unless there are nonfinite values involved. For thresholds, I think setting a caution at +18 dB and a severe warning at +36 dB could work, but should we allow warnings even beyond that? Maybe a hard gate if the response exceeds certain numeric caps, like over +96 dB for overflow reporting.

For warnings, I can set them at max magnitudes over +24 dB and severe at +48 dB. Regarding sharp notches or zeros on the unit circle, I need to define what a zero radius should be as well.

**Clarifying Warning Conditions**

I think warnings for zero radius should apply outside of 1.25 since zeros don’t impact stability. There might also be a warning for pole-zero cancellation since that's fragile. I need to consider overlaps, unused roles, and degenerate secondaries—those could be allowed warnings. 

It's also important that if a constructor recipe doesn't expand into a true surface, it should trigger a warning rather than a gate. Plus, any imported body that can’t reconstruct semantic roles should receive a warning. I need to incorporate quantization details and foundation operations, along with explicit zero annotations.

**Defining Authoring Document Schema**

I need to establish the schema for the authoring document. It’s going to be an editable artifact, either in JSON or CBOR format. I'll ensure it's patch-ready and define a versioned schema. This will store root surfaces by stage and corner, along with links, scope, constructors, notes, and sample rates. 

The runtime artifact must be exactly 240 bytes, labeled as `.df2body` or `.body240`, but this won't include reference material—only notes or hashes. I'll incorporate a specific format that includes an ID, target sample rates, and normalized frequency handling, ensuring roots display in Hz accurately!

**Outlining the Compile Path**

I need to clarify the compile path, ensuring each step is outlined. First, author the roots, then resolve the links and parameters for four corners. Next, I’ll canonicalize the roots into real coefficients and their conjugates, followed by converting them to direct-form coefficients with normalization.

Then, I’ll quantize and pack into the needed u16 format. After assembling the order, I'll run an FFI release proof to plot the packed body for stability checks. If everything passes, we can export. For previews, I might compile in memory and allow edits, even while monitoring for stability issues!

**Structuring Implementation Phases**

I need to ensure that I don't send unstable code to the plugin since the preview relies on FFI plots and a private host. I’ll compile a "safe preview" only when there are no catastrophic failures; otherwise, the local UI will display an error. 

I’m outlining a phased implementation with eight clear tasks: 

1. Constants and tests 
2. Body parser/packer wrapper 
3. .df2forge schema definition 
4. Root-to-coefficient conversions and constructors 
5. A six-lane UI with handles 
6. Packed audit and plotting 
7. Compile/export gates 
8. Preview and hot reload

Lastly, I'll avoid certain rejected approaches, like coefficient-first GUIs or AI-generated references, keeping it precise while marking any necessary open experiments.

**Identifying Captures for Experiments**

I need to establish captures for experiments related to our project, specifying which ones are necessary before reaching version 0. I won't have any questions about it but I should keep it to a maximum of six bounded captures.

1. Pre-v0: Capture the packed interpolation roots and responses across 9 points to verify plot API and endpoint order.
2. Pre-v0: Conduct a round-trip sweep on pack quantization for root-to-coefficient conversions, measuring metrics.
3. Pre-v0: Capture the preview latency and hot reload with under 20 edits per second.
4. Pre-v0: Evaluate UI legibility with complex/real pole/zero handles at the six stages.
5. Post-v0: Measure the stability of dense grids versus sparse checkpoints to identify false negatives.
6. Post-v0: Outline the workflow for expanding from two-frame to four-corner configurations.

I need to clearly mark which of the first three are needed before version 0 as "Needed before v0: Yes/No."

**Deciding on Biquad Coefficients**

I need to determine if we should use "Trench_core FFI plots" for our release proof and if capturing FFI experiments is essential. I want a concise verdict that includes the decision to ship version 0 as a private root-domain stage composer with a packed runtime audit, without developing a general EQ or generative selector.

Next, I must specify detailed stage roots and coefficient definitions for a real-coefficient biquad, represented by the formula:

\(H(z) = g * \frac{(1 - z_1 z^{-1})(1 - z_2 z^{-1})}{(1 - p_1 z^{-1})(1 - p_2 z^{-1})}\)

The coefficients and calculations are critical, so I’ll ensure normalization and stage gain are prioritized, but I might include additional diagnostic coefficients. Each packed u16 could correspond to the five biquad coefficients: b0, b1, b2, a1, and a2, but I don’t want to overcomplicate things.

**Defining Word Roles and Constructors**

I want to clarify that "word roles" will adhere to the current DF2T packer, where they are treated as opaque `w0..w4`, except in diagnostic tables. However, I’m considering the possibility of using direct coefficients since the format constraints require exactly five packed u16 per stage—no guesses allowed!

We need to ensure our release proof utilizes packed-domain interpolation and Trench_core FFI plots. It's good to note that all preview plots for release will come from the same packed bytes and interpolation equations used in runtime, while local plots are just drafts. 

Let’s also note that a lawful constructor or two-frame program can start in a degenerate state across Secondary but can be deliberately expanded to a true four-corner DF2 surface. Additionally, v0 constructors can write `S0==S1` to create a one-dimensional morph, which is perfectly legal and exportable!

**Clarifying UI Labels and Commands**

I’ve decided to label the UI as "Secondary degenerate." The "Expand Secondary" command allows users to clone the M-edge into an editable S1. It includes offset handles or unlinks S corners and prompts set differences, effectively transforming it into a true four-corner structure.

Authors can manually edit S1 at the current corner to break degeneracy, and the default drag feature supports expansion. I want to note that this isn't a hard gate.

Now, about the "four-corner edit semantics": 

- Coordinates and corner order must be established.
- Stage identity across corners will be represented by slot index, ensuring that stage slot N interpolates consistently across corners. There won’t be stage insertion per corner; it will occupy the same slot across all corners, ensuring consistency.
- There should be exactly six serial stages at each corner with interpolated slot index.
- It’s crucial that stage roles remain the same across corners to prevent dissimilar filter morphing. The UI should warn users about any role mismatches.

Finally, dragging poles/zeros will default to the current corner, and scope options will include Corner and Morph edge (M0/M1 at the current S).

**Defining Edges and Link Semantics**

I’m thinking about the edge definitions. It seems that editing across the M edge should allow movement of both M endpoints, so let’s clarify: 

- A Corner is defined as one endpoint.
- A Morph Edge consists of the pair `M0_Sx` and `M1_Sx`. If I edit both endpoints along a Secondary row, I should maintain the delta.
- A Secondary Edge is defined by the pair `Mx_S0` and `Mx_S1`.
- The Whole Field includes all four corners.
- Diagonal connections are optional for now and may not be included in v0.

For link semantics, I want a copy option rather than a hidden link; live links should be explicit with a chain icon and initially turned off.

When it comes to stage insertions or deletions, "delete" means replacing it with an identity without changing count or order.

I need to ensure that there’s a packed audit system always active with details like structural audits, root/coefficient audits, pack quantization audits, runtime interpolation audits, and plot audits. The UI should run these audits after every edit, possibly asynchronously.

For checkpoints, I’ll include four endpoints, four midpoints, a center, and possibly some diagonals, totalling around 13 points for a summary. I’ll need to finalize this.

**Setting Up Release Proof and Interpolation**

I’m considering using a "default release grid" of 5x5 or a specific 13-point grid. I want it to be rigorous but not overly complex. For v0, a 5x5 setup gives us 25 points, and I can include curve plots along M and S.

I’m thinking that maybe the release proof should utilize packed-domain interpolation and FFI plots, but a sparse grid might miss some critical data. The 5x5 endpoints cover all bases, and I can establish a "hard gate release grid" at 5x5 while offering a quick preview grid of 3x3, focusing on plots at corners, edges, centers, and selected paths.

It’s essential that pole stability is maintained at all release grid points, and if FFI only returns responses and not roots, I need to add the necessary FFI function. Given that the spec is patch-ready, I should "add/consume FFI endpoints" and implement a hard gate if any are missing. For v0, it seems necessary to ensure that "packed-domain interpolation" refers to interpolating packed u16 values as integers.

**Clarifying Runtime Interpolation and References**

I’m considering the runtime process—maybe it should unpack first and then interpolate coefficients. The rule states that release proof uses packed-domain interpolation, which might mean interpolating between packed values before decoding. I don’t need to define everything exactly, but I’ll stick to the same runtime FFI.

For the "trench_core FFI plots", I'll ensure that the function returns magnitude and phase vectors for the body at M and S. I need to clarify that reference materials should only be for study and not copied into shipped bodies, so I'll include just descriptions and hashes, avoiding any sample or body bytes.

I also want to avoid any random poles, zeros, or AI-driven selections; everything must remain deterministic, driven by constructors or manual edits. There's a potential issue with “authoritative packed runtime artifact”—they might expect a `.df2` body. 

I can label them generically as `*.body240` based on the title. The report will need to be titled appropriately, and to format claims consistently, I could prefix each bullet with **OBSERVED:**, **INFERRED:**, or **RECOMMENDED:**. I wonder if I need to include all claims or just ones that are significant.

**Structuring Claims and Finalizing Content**

I need to make sure to label claims clearly, focusing on major points instead of every single sentence. The goal is to be concise yet firm in decisions while avoiding an overly detailed document—so aiming for clarity is key. 

I'll structure the content with a title followed by numbered sections, ensuring enough detail. In my draft for Section 1, the verdict includes several recommended points. I observe that the canonical shipped body has four corners, and I recommend that Forge should remain a private plot-first authoring bench rather than another shipping format or driven by AI.

Also, the editable representation should focus on poles and zeros rather than coefficients. The release proof must derive from packed bytes using trench_core, limiting the export to just 240 bytes. Finally, I can state that the v0 version ships with a six-stage composer and won’t include a seven or eight-corner setup.

**Defining Author Edits and Screen Anatomy**

In Section 2, I need to clarify what the author edits. This includes primary elements like per stage and corner root domains, pairs for poles and zeros, stage gain, normalization, role labels, and corner links. The poles and zeros need to be explicit, with visible zero handles, and we’ll designate diagnostic elements such as DF2 coefficients and packed checkpoints as non-editable. 

For the stage slot model, we should have six serial slots with maintained identity and order. 

Moving to Section 3, I’ll outline the screen anatomy, starting with a header status and a body surface plot featuring corner cards. I should include a live plot, stage composer with mute and solo options, a root editor for selected stages, a constructor palette, and an audit panel that warns of issues. The UI needs to highlight zeros with colored handles, labels, a zero map, and a numerator response overlay.

**Establishing Foundation Operations**

For Section 4, I need to create a table detailing foundation operations. It should include the operation or constructor, the number of stage slots consumed per corner, v0 controls, and any relevant notes. 

I'll elaborate on the rows: 
1. **Identity/manual biquad (1 slot)**: This will be neutral for poles/zeros, and if bypassing, it consumes one slot as a compiled identity.
2. **Cliff Foundation LP/HP (2-pole, 4-pole, 6-pole)**: Consuming 1 to 3 slots, it requires parameters like cutoff, order, pole spread, gain, and zeros should be explicit at Nyquist for LP or DC for HP.
3. **Shelf/Tilt Foundation**: This takes 1 slot for a single shelf and 2 for an opposed tilt, including corner frequency, gain, slope, and visible pole/zero separation.
