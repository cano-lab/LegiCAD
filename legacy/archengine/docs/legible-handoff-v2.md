# Handoff v2 — Hardware-First Thesis

**Date:** May 24, 2026
**Supersedes:** legible-handoff-2026-05-23.md (the original software-first version)
**Context:** Multi-hour conversation that started as pitch prep for a Baukunst partner and ended in a rebuild of the company around hardware-as-product. Awaiting her reply.

---

## 1. The thesis (locked)

> Every layout in residential construction is still done with paper plans, a tape, and a person yelling measurements — a workflow unchanged since the 1950s. We're replacing paper plans. Legible Studio is the design software that produces the structured plan data. LegiView is the AR hardware that puts that plan in the worker's field of view on site. The wedge is software (sold today to design-build firms generating permit sets). The moat is hardware (worn tomorrow by every layout crew, every inspector, every site walk). The long arc is owning the structured spatial record of every building we touch — the data layer underneath layout, inspection, and as-builts.

**Why this is defensible:**

- Trimble has the workflow but not the form factor courage.
- Autodesk has the software but not the field.
- Magic Leap had the hardware but not the construction.
- Jer has all three because he lived all three: CS background, architectural technology diploma, 10 years on construction sites, teaches it at a college, runs AndOr.

That intersection is genuinely empty. That's the unfair advantage.

---

## 2. Pitch language

### Master line
> "We're replacing paper plans in construction. Software is the wedge, hardware is the product, the data layer is the moat."

### Credentials stack (the "why you")
> "I have a COSC background, an advanced diploma in architectural technology, ten years of construction experience, and I teach architectural technology at a college. I'm 31. Legible sits at the intersection of all of that — code, design, build, teach — and AI is what lets one person actually hold all four at once."

### The books — philosophical surface
- **Nothing Is the Impossibility** — physics book, constraint as how reality is structured. *Framed as intellectual rigor (built a framework, then had to crack it), not as new physics.*
- **What We Owe to the Air** — ethics for shared spaces. What we owe each other in the places we build.

> "They feed the work from opposite directions: the structure of design problems and the moral weight of solving them well."

### The headline ask (when she asks about money)
> "$1.59M USD pre-seed to ship v1 hardware to 10 workers across 5 sites with measured productivity improvement. Series A in 22 months."

### The "one bet, four surfaces" reframe (if asked how Jer manages it all)
> "In my head it's not multiple things. Physics, ethics, software, hardware — it's one bet, four surfaces. AI helps me ship faster, but the through-line is mine."

ADHD reframe: *"I see structure where others see scatter."* Still not a disclosure to lead with.

---

## 3. The product — current spec

### Legible Studio (software)
- Rust-based core (constraint solver, rules engine).
- Pipeline: location + constraints + budget → permit-ready drawings.
- Exports IFC/DWG for Revit import (decoupled from Revit, not live integration).
- v1 surface: OBC Part 9 (low-rise residential).
- Last-30% human-in-the-loop interface for judgment items (door swings, window placement, structural strategy).

### LegiView (hardware)
- **Form factor:** safety glasses (ANSI Z87.1+). Sub-100g. Hard-hat compatible. IP54+.
- **Display:** birdbath optic, monocular, micro-OLED ~3000 nits. 20-25° FoV (sufficient for plan overlay at known anchor points).
- **SLAM:** 2 grayscale wide-FoV global-shutter cameras + 6/9-axis IMU + optional ToF for low-texture environments.
- **Architecture:** glasses are display + sensors. Compute on tethered phone. **Battery + heat dissipation in a belt-clip puck** (innovation: offloads heat from temples, hot-swappable, ANSI-rated, ruggedized).
- **Tracking model:** anchor plan to one surveyed point on site (corner pin, foundation edge), visual-inertial SLAM keeps device locked to plan within ~1 inch. Tape confirms final placement.
- **v0 (months 6-12):** tethered off-the-shelf glasses + iPhone, software-driven workflow.
- **v0.5 (months 12-18):** ODM-built prototype with custom optics.
- **v1 (months 18-24):** safety-glasses form factor with custom puck.

### Customer lines (all share underlying platform)
- **Builder** — layout crew, framing, finish trades. Primary v1 customer.
- **Inspector** — municipal/third-party. Compare built reality to approved plan in real time. Strong regulatory tailwind, higher margins, easier ROI story. *Possibly the better wedge.*
- **Designer** — early phase plan walks. Sales/visualization tool.
- **Client** — homeowner walks lot pre-construction. Sales aid.

---

## 4. The team — pre-seed structure

| Role | Hired | Why |
|---|---|---|
| Founder (Jer) | Day 1 | Plays engineer + builder + customer wrangler for first 6 months. |
| Wrangler / COO / Chief of Staff | Month 3 | Full-time. Operations, customer success, scheduling. Internal hire first (AndOr, former student, peer from arch tech program). |
| Engineer 1 (Python/Rust) | Month 6 | Core pipeline, constraint solver, rules engine. |
| Hardware Lead | Month 6 | Has shipped consumer AR/wearable hardware through ODM. Former Magic Leap/Vuzix/Focals/Bose Frames profile. Non-negotiable for hardware credibility. |
| Engineer 2 (iOS/AR + Revit bridge) | Month 14 | Owns the AR app and the export bridge. |

---

## 5. Budget (v3 — hardware-first)

**Total:** $2.18M CAD ≈ $1.59M USD over 24 months.
**Position:** Top of Baukunst's $500K-$2M USD range, not over the ceiling.

See `legible-budget-v3.xlsx` and `legible-budget-v3.md` for the line-item breakdown and milestones.

---

## 6. Held back (still)

These are real and valuable but not for this room. Each gets its own conversation later.

| Project | Why held back |
|---|---|
| The OS (LLM-safe kernel-level constraints) | Different thesis. Different investor. Reveal in meeting 3+ if relationship develops. |
| Franco-Ontarian / Northern Ontario LLM | Grants game, not venture. Wrong funder. Belongs with Patrimoine canadien / AFO / FedNor. |
| Research non-profit as an ask | Allowed as vision/long arc. Not as a request. |
| ADHD as disclosure | Reframe as cognitive style strength later, not vulnerability now. |
| Grants as sub-ask | Don't compound asks. If relationship works, ask in 6 months. |

---

## 7. Why Baukunst specifically

- **They literally helped start Revit.** Their partners played instrumental roles in Solidworks, Onshape, and Revit. They speak the AEC software language fluently.
- **Their thesis is "creative technologists"** — founders who blur engineering, product design, and artistic vision. Jer's exact shape.
- **Hardware-friendly heritage** (Bolt lineage). Portfolio includes Tonal, Pair (eyewear), Desktop Metal. They hunt hardware.
- **They lead and often invest the full round** out of $100M fund. Single conviction can close it.
- **Check size $500K-$2M USD, sweet spot ~$1.5M.** Pre-seed target lands at $1.59M — right in the sweet spot, near the top.

---

## 8. Tactical notes

- **Don't lead with the number.** First conversation = who/what/why. Money is conversation 2 or 3.
- **Don't volunteer hardware-company complexity.** Lead with software, let her pull on hardware. When she does, the answer is the full vision.
- **The Vision Pro demo is the artifact** to bring to a face-to-face. Build it as part of months 1-3 work.
- **The inspector channel is the underused angle.** Most AEC pitches focus on builders. Inspectors have budget authority, regulatory tailwind, and a much cleaner ROI story. Worth mentioning when the conversation has room.
- **Match her cadence.** She quadruple-texted; she's not in interview mode. Same wavelength wins.
- **Close the phone after sending anything.** No rereading.

---

## 9. Working-style notes (still true)

- **Writing-it-out unsticks.** This entire document is a record of that working repeatedly across a single day.
- **Spiralling vs. hoping.** Hoping is fine when you see yourself doing it. Today: caught it multiple times.
- **One conversation, one room.** Capture other ideas elsewhere; don't deploy them in the wrong room.
- **"I see structure where others see scatter."** That's the wrangler-in-Jer. Externalizing (this doc, the budget) is part of that.

---

## 10. Open threads

- Awaiting her reply.
- AndOr permit checklist → deterministic/judgment split (concrete next action, can start today).
- Smoke detector category as first end-to-end ship.
- Hardware Lead shortlist — start LinkedIn research now, even before money.
- ODM longlist — Vuzix, Realwear, Brilliant Labs, Even Realities, and 2-3 Shenzhen-based smart-glasses ODMs.
- Vision Pro for the demo — buy one in month 1.
- Talk to one AndOr framer + one Ontario building inspector about the workflow. Both conversations matter.
