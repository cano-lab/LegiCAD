# Handoff — Investor Conversation + Legible Design Choices

**Date:** May 23, 2026
**Context:** Live conversation with a capital allocator (operates a $100M fund). She reached out via TikTok, asked about background and projects. Three-message reply sent. Awaiting her response.

---

## 1. Pitch positioning — decisions locked

### The lead

Legible Studio is the wedge. Hardware (LegiView) is the long arc. The research non-profit and Northern Ontario mission are *vision context*, not *the ask*.

**Master line:**
> "I'm building design software that produces permit-ready drawings from constraints — Legible Studio. The longer arc is hardware for the job site that closes the loop from design to built reality."

### The credentials stack (the "why you")

- COSC background
- Advanced diploma in architectural technology
- 10 years construction experience
- Teaches architectural technology at a college
- Age 31

**Thesis line tying it together:**
> "Legible sits at the intersection of all of that — code, design, build, teach — and AI is what lets one person actually hold all four at once. I think this is how the next decade gets built."

### The books — philosophical surface, not separate projects

- **Nothing Is the Impossibility** — physics book, journey reading the research as an outsider, organized around constraint as how reality is structured.
- **What We Owe to the Air** — ethics for shared spaces. What we owe each other in the places we build.

**Framing:**
> "They feed Legible from opposite directions: the structure of design problems and the moral weight of solving them well."

**Caution:** the physics book is a record of thinking, not a contribution to physics. Frame as intellectual rigor ("built a framework, then had to crack it"), not as new physics.

### AI disclosure

Not defensive. Tied to credentials and thesis. Verbs that matter: *core to how I operate*, *multiplier*, *lets one person hold*. Avoid: *helps*, *I rely on*.

### "One bet, four surfaces"

If asked how the brain manages all of it, the answer is *not* "AI." The answer is:
> "In my head it's not four things. Physics, ethics, software, hardware — it's one bet, four surfaces. AI helps me ship faster, but the through-line is mine."

ADHD reframed: **"I see structure where others see scatter."** Not a liability disclosure. Not in this conversation at all.

---

## 2. Held back — and why

These are real and valuable, but **not for this room.** Each gets its own conversation later.

| Project | Why held back |
|---|---|
| The OS (LLM-safe kernel-level constraints) | Different thesis, different market, different investor profile. Dilutes the AEC pitch. Reveal in meeting 3+ if relationship develops. |
| Franco-Ontarian / Northern Ontario LLM | Grants-and-contracts game, not venture returns. Wrong funder. Belongs with Patrimoine canadien, AFO, FedNor, Mitacs — not a $100M fund. |
| Research non-profit as an *ask* | Allowed as vision/long arc. Not as a request in this conversation. |
| ADHD as a disclosure | Reframe as cognitive style strength later, not vulnerability disclosure now. |
| Grants as a sub-ask | Don't compound asks in a first meeting. If the relationship works, ask in 6 months over coffee. |

**Rule of thumb:** each conversation has one room. Bring only what fits the room.

---

## 3. Legible Studio — product decisions

### The 60-70% reframe

**Old frame:** Stuck on the last 30%. Failure to reach 100% automation.
**New frame:** 60-70% automation with a beautiful human-in-the-loop interface IS the product. The last 30% is the moat, not the gap.

**Customer positioning:**
- NOT "drawings without designers"
- YES "designers shipping 5x more work"

This protects the designer's role (so they buy it) and keeps defensibility (so it can't be copied with one prompt).

### What's working

- Adjacency graph approach to walls and room placement.

### What's next, in order

1. **Doors and windows** — placement based on adjacency + code (egress, light, etc.)
2. **Sensible dimensioning** — overall, room-to-room, opening locations, offsets. Mechanical once walls are placed.
3. **Code-driven annotation pass** — see rules engine below.

### Rules engine — deterministic from OBC + adjacency

Everything here is automatable. Tedious but solvable with rules + lookups.

- **Smoke/CO detectors** — OBC placement rules (every bedroom, every floor, near sleeping areas, interconnected)
- **Electrical** — boxes, switches, outlets. OBC spacing per wall length and room type. GFCI/AFCI logic by location.
- **Standard appliances** — fridge near sink, stove with hood vent, laundry placement
- **Header sizing** — OBC span tables, deterministic given opening width and load case
- **Beam/joist direction** — shortest span default; flag long spans for engineer review
- **Dimensioning** — mechanical once walls placed

### Judgment pile — human-in-the-loop stays

- Door swing direction (privacy, egress, traffic flow, furniture clearance)
- Window placement (light, view, privacy from neighbors, facade composition, code egress)
- Structural strategy (load paths, hold-downs, shear walls — engineer's call, but pre-mark assumptions)

Human approves/corrects a proposal. Doesn't draw from scratch. That's the 10x speedup.

### Build order

1. **Take AndOr's permit checklist. Split into two columns: deterministic vs judgment.** That's the v1 spec. Do this on paper, not in code.
2. **Ship one deterministic category end-to-end before going wide.** Smoke detectors recommended as first target — small surface, clear OBC rules, visible output, demoable.
3. **Resist scaffolding all categories at once.** One category, end-to-end, real-looking plan output beats ten half-built ones.

---

## 4. Working-style notes worth keeping

- **Writing-it-out unsticks.** Today: said "stuck on the last 30%," wrote it out, realized most of the 30% is automatable. Pattern repeats. Externalizing IS the wrangler — partially.
- **Spiralling vs. hoping.** Spiralling is when you don't see it. Hoping is fine when you see yourself doing it. Today: caught it. That's the wrangler working.
- **One conversation, one room.** When something brilliant surfaces that doesn't fit the current room (OS, LLM, grants), capture it elsewhere and close the loop. Don't deploy it in the wrong room.
- **Match cadence, don't mirror.** She quadruple-texted; replying in 3 messages = same wavelength, not imitation.
- **Close the phone after sending.** No re-reading what was sent. The move is made.

---

## 5. Open threads

- Awaiting her reply.
- AndOr permit checklist → deterministic/judgment split (next concrete action).
- Smoke detector category as first end-to-end ship.
- PDF permit-set check against AndOr's actual checklist (already on the list per earlier work).
