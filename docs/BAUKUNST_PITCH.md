# HOMESTEAD
## The Home Computer for Local AI

**For Baukunst** — September 2026

---

### What Changed

You saw LegiView — AR glasses for construction. Good idea, wrong sequencing.

We spent six months building the OS stack (SemOS), the voice layer (Five), and the AI tutor (Almanach). The same stack that would have powered LegiView works even better for a market 100× larger: **families who want AI without surveillance.**

We're not abandoning construction AR. We're building the platform first. The home is where families pay.

---

### The Product

A designed, powerful home computer that runs your family's AI entirely on-device.

| What it replaces | How it's different |
|---|---|
| Siri / Alexa | No cloud. No wake-word surveillance. Your voice never leaves the house. |
| iCloud Family | Your photos, calendars, documents — on a drive you own. No subscription. |
| Khan Academy + tutoring apps | Almanach: an AI tutor that knows your child's curriculum and adapts offline. |
| HomeKit / Google Home | Zigbee/Z-Wave hub built in. Rules run locally. |
| Xbox Live / Minecraft Realms | Minetest server, retro emulation, AI dungeon master — hosted at home. |

**The pitch to parents:** *"Your kid's homework runs on a server in your basement. Their AI tutor has never heard of terms of service. And when their friends come over, they game on your server, not Microsoft's."*

---

### What Exists Today

| Component | Status | Proof Point |
|---|---|---|
| **SemOS** — Custom kernel | WiFi works. Rust toolchain (semos-rustc) nearly self-hosting. T540p dev station running daily. | `github.com/cano-lab/semos` |
| **Almanach** — AI tutor | Full Ontario Grade 9 math curriculum seeded. Student/teacher dashboards built. Classroom pilot Fall 2026. | `github.com/cano-lab/almanach01` |
| **Five** — Voice assistant | Wake word (openWakeWord) + local STT (whisper.cpp) + OpenClaw agent integration. Prototyping on T540p. | Voice demos available |
| **LegiCAD** — Parametric design | Grasshopper prototype running Sudbury zoning constraints. Rust compliance layer (`ls-obc`) with 600+ tests. | `github.com/cano-lab/LegiCAD` |

We're not a deck. We're a stack that boots.

---

### The Hardware

Not a $299 appliance. A **designed home computer**.

| Spec | Target |
|---|---|
| CPU | ARM (RK3588-class) or x86 mini-ITX |
| RAM | 16-32GB DDR4/DDR5 |
| Storage | 1TB NVMe SSD |
| Connectivity | WiFi 6, Zigbee/Z-Wave hub, 2× Gigabit Ethernet |
| Form | Silent, fanless, designed enclosure (furniture-grade, not plastic box) |
| Display | Optional e-ink status panel on device |

**Retail: $999 (Base) / $1,299 (Pro)**  
**BOM: ~$500-650**  
**Margin: ~40-50%**

---

### The Market

| Segment | Size | Entry Point |
|---|---|---|
| **Privacy-conscious parents** | Millions | Direct online, TikTok/YouTube |
| **Homeschool families** | ~3M US, growing | Curriculum integrations |
| **Smart home early adopters** | ~15M US | Home Assistant migration |
| **School districts (Almanach)** | Institutional | Annual license, self-hosted |

The homeschool segment alone is underserved — they already distrust cloud platforms and pay for curriculum.

---

### The Bootstrapped Path (Before Pre-Seed)

We're not waiting for funding to validate demand.

**Phase 0: Hand-built prototypes (Now - Month 3)**
- 5-10 units using off-the-shelf SBCs (Orange Pi 5 Plus, N100 mini-PCs) in custom 3D-printed enclosures
- Sell to early adopters at cost (~$600-800) or slight margin
- Gather feedback on SemOS, Almanach, Five integration
- Prove the stack works in real homes

**What this proves before we raise:**
- People will pay for a local AI home computer
- The software stack is stable enough for non-technical users
- We can source and assemble hardware without a factory
- Demand signal for Baukunst to evaluate

**Then pre-seed ($500K) becomes:** Scale the 10-unit proof into a 500-unit production run with proper tooling, hired hardware lead, and polished industrial design.

---

### Why Baukunst

You're the only pre-seed fund that treats hardware as a design discipline, not a supply-chain problem.

We need:
- **$500K** to get to a sellable v1 (board bringup, enclosure design, production tooling)
- **18-month runway** for two full-time (hardware lead + systems engineer)

In return, you get a team that ships — not slides, not prototypes, but bootable kernels, running classrooms, and voice assistants that answer to "Hey Five" at 3 AM without calling Google.

> **Note on silicon:** We will eventually design custom silicon optimized for the SemOS security model. That's a Series A problem. Pre-seed is about proving the stack on commodity hardware.

---

### The Ask

**$500K pre-seed**  
For: hardware lead hire, first 500-unit production run, Almanach classroom pilot expansion.

**Milestone 1 (Month 6):** 50 beta units in homes. Almanach in 5 classrooms.  
**Milestone 2 (Month 12):** First production run. Revenue from direct sales + school licenses.  
**Milestone 3 (Month 18):** Series A or profitability. LegiView (construction AR) re-enters roadmap.

---

### Contact

**Jer** — jer@cano-lab.io  
GitHub: `github.com/cano-lab`  
Based: Sudbury, Ontario / Remote

---

*The walled garden was never the product. The key was.*
