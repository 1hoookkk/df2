---
name: trench-interface
description: Plugin and workstation UI work in the df2-workstation checkout (C:\Users\hooki\df2-workstation only, not sibling checkouts) - interaction design, layout, visualization, control behavior, view-wired assets, and the frontend-to-audio-engine connection. Use when a task there changes what users see or touch on any current product surface, asks how a surface should look or behave, or weighs interface technology and architecture choices.
---

# TRENCH Interface

Inspect the actual surface first, design with current practice for the toolkit actually in use, and prove material changes with real built evidence.

## Orient

- Discover the active surface for the task: find the entry points and view code that build and run today, not a remembered layout. More than one frontend may exist; confirm which one the user means before editing.
- Read how the surface talks to the engine — parameter and state flow across the frontend/runtime boundary — before changing either side.

## Design

- Translate the user's intent, even when given as vibes or reference images, into concrete visual and interaction goals, then choose suitable current patterns for the toolkit the surface is built with. Do not port habits from a different toolkit unchanged.
- Consider when relevant: DPI and scaling across monitors, keyboard access, accessibility basics (contrast, focus, hit targets), host and window-embedding behavior, resize/responsiveness, and feedback latency.
- The real-time boundary is part of the interface: UI code must not block or allocate on the audio thread, and visualizations read engine state through a safe channel (existing or deliberately added), never by reaching into audio-thread data directly.
- Toolkit and architecture questions get a decisive, evidence-based recommendation (product requirements, host constraints, maintenance and migration cost) — then proceed on it when it fits the authorized scope. Ask first only when the move would materially expand scope or change product direction.
- Treat checked-in art assets as someone's work product: modify them only when the task calls for it, through the pipeline that produced them when one exists, and never silently replace a curated asset with a procedural approximation.

## Evidence

- Must: judge material visual or interaction changes on real built output — a screenshot, capture, or interaction run of the actually built artifact, at true screen scale — not a mock, a description, or an unbuilt patch.
