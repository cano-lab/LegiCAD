# Legible Engine — Quick Start

**When you're ready to begin.**

---

## What You Need

- [ ] **Rhino 7/8** installed on MacBook M1
- [ ] **Grasshopper** (included with Rhino)
- [ ] This repo checked out or open
- [ ] A Sudbury zoning bylaw PDF (or any zoning doc to practice on)

---

## Phase 1: Grasshopper Prototype

### Step 1 — The Subtractive Regime Script

Create a Grasshopper script that takes:
1. **Site boundary** (closed polygon)
2. **Zoning rules** (as slider inputs):
   - Front setback (m)
   - Rear setback (m)
   - Side setback (m)
   - Max height (m)
   - Max FSR (floor space ratio)
   - Max coverage (%)
3. **Program brief** (as slider inputs):
   - Unit count
   - Target unit size (sqm)
   - Parking spaces required

And outputs:
1. **Feasible envelope** (the raw site minus setbacks)
2. **Residual massing** (envelope minus height/FSR/coverage limits)
3. **Unit layouts** (sliced into floors)
4. **Compliance check** (pass/fail for each rule)

### Step 2 — Negative Space Sculpting

Add a manual sculpting layer:
- User draws exclusion zones (voids) in the massing
- Script recalculates FSR, coverage, unit count in real-time
- Warns if a cut violates a hard constraint

### Step 3 — Export

Export the final massing as:
- Rhino geometry (for further work)
- JSON (for Legible Engine compliance check)
- Screenshot (for sharing)

---

## Phase 2: Data Link

### Step 4 — Structured Zoning Data

Encode Sudbury zoning as JSON:
```json
{
  "jurisdiction": "Greater Sudbury",
  "zone": "R1-Residential",
  "rules": {
    "front_setback": { "value": 6.0, "unit": "m" },
    "rear_setback": { "value": 7.5, "unit": "m" },
    "side_setback": { "value": 1.2, "unit": "m" },
    "max_height": { "value": 10.0, "unit": "m" },
    "max_fsr": 0.5,
    "max_coverage": 0.35,
    "parking_per_unit": 2
  }
}
```

Feed this JSON into Grasshopper instead of manual sliders.

### Step 5 — OBC Validation

Feed the Grasshopper output into `ls-obc` (Rust crate):
- Ceiling heights
- Egress widths
- Fire separation distances
- Span tables (if structural members are sized)

Return: compliance report + permit drawing set.

---

## Phase 3: Software UI

### Step 6 — Standalone Interface

Build a lightweight UI (web or Tauri) that:
- Collects user input (questions)
- Sends to Rhino Compute (or local Grasshopper)
- Displays 3D massing
- Shows compliance status
- Exports permit documents

---

## Files You Need

| File | Purpose |
|------|---------|
| `VISION.md` | The big picture |
| `questions.md` | Open questions for agents |
| `/root/.openclaw/workspace/legible-studio/rust/` | Existing Rust codebase |
| `/root/.openclaw/workspace/regime-architecture.md` | Regime methodology |

---

## Reminders

- **Don't build a geometry kernel.** Grasshopper is your kernel.
- **Don't build a CAD program.** Rhino is your CAD.
- **Build the regime.** The rules, the constraints, the subtractive logic.
- **Build the bridge.** Between questions and geometry, between geometry and compliance.
- **Start small.** One zone, one typology, one municipality.

---

*"Don't worry. Even if the world forgets, I'll remember for you."*
