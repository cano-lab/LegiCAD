# Homestead SBC Recommendation
## What to Buy for the First 5-10 Prototypes

**Date:** September 9, 2026

---

## The Requirements

| Use Case | What It Needs |
|----------|---------------|
| **Five** (voice assistant) | Minimal — wake word + STT + TTS runs on any modern CPU |
| **4B-class LLM locally** | 32GB RAM, GPU with Vulkan/ROCm support for llama.cpp acceleration |
| **Emulators + Steam** | x86 CPU, strong iGPU (RDNA3), Linux compatibility |
| **Parent dashboard** | Web server + API, lightweight |
| **Call bigger LLM** | Internet connection, API keys (Claude/GPT-4 for game generation) |

**Critical insight:** Steam does not run on ARM Linux. If you want Steam + emulators, you need **x86**.

---

## Recommended: AMD Ryzen 7 7840HS Mini PC

### Why This Chip

| Spec | Detail |
|------|--------|
| CPU | 8 cores / 16 threads, Zen 4 |
| iGPU | AMD Radeon 780M (RDNA 3) — comparable to GTX 1650 |
| RAM | DDR5, up to 64GB |
| TDP | 35-54W (fanless possible with good chassis) |
| Linux support | Excellent — mainline kernel, Mesa drivers |
| Vulkan | Yes — llama.cpp uses Vulkan for GPU-accelerated inference |

### Specific Models (September 2026)

| Model | CPU | RAM | Price (est.) | Notes |
|-------|-----|-----|--------------|-------|
| **Beelink SER7** | Ryzen 7 7840HS | 32GB DDR5 | ~$450-500 | Quietest, best thermals, most polished |
| **Minisforum UM790 Pro** | Ryzen 9 7940HS | 32GB DDR5 | ~$500-550 | More CPU power, expandable to 64GB |
| **GMKtec NucBox K6** | Ryzen 7 7840HS | 32GB DDR5 | ~$400-450 | Budget pick, runs warmer |

**Our pick for prototyping:** Beelink SER7 or SER8 (if 8845HS refresh is out)

---

## What the 4B LLM Actually Means

You said "4B LLM" — but a 4B parameter dense model is pretty weak for game generation. What you actually want:

| Model | Real Size | Active Params | RAM Use | Speed | Quality |
|-------|-----------|---------------|---------|-------|---------|
| **Gemma 4 26B-A4B** (MoE) | 26B total | ~4B per token | ~15GB | 45+ tok/s | Excellent — Google's best open model |
| **Qwen 3.6 27B (Q4_K_M)** | 27B dense | 27B | ~16GB | 18-30 tok/s | Best all-rounder |
| **Qwen 3 14B (Q4_K_M)** | 14B dense | 14B | ~9.5GB | Faster | Good enough for many tasks |

**Recommendation:** Run **Gemma 4 26B-A4B** locally via Ollama. It's a Mixture-of-Experts model — only ~4B parameters are active per token, but it has the knowledge of a 26B model. Fast, high quality, fits in 32GB with room to spare.

For the "call bigger LLM to generate games" — that's an API call:
- Local model handles chat, voice, routine tasks
- API call to Claude 3.5 Sonnet / GPT-4o for creative game generation
- Parents write prompts in dashboard, system sends to API, returns game content

---

## The Architecture

```
┌─────────────────────────────────────────────┐
│           BEELINK SER7 (32GB RAM)            │
│                                              │
│  ┌─────────────┐  ┌─────────────────────┐   │
│  │  SemOS      │  │  Ollama             │   │
│  │  (kernel)   │  │  Gemma 4 26B-A4B    │   │
│  └─────────────┘  └─────────────────────┘   │
│                                              │
│  ┌─────────────┐  ┌─────────────────────┐   │
│  │  Five       │  │  Steam / Emulators  │   │
│  │  (voice)    │  │  (Radeon 780M)      │   │
│  └─────────────┘  └─────────────────────┘   │
│                                              │
│  ┌─────────────┐  ┌─────────────────────┐   │
│  │  Almanach   │  │  API Proxy          │   │
│  │  (tutor)    │  │  → Claude/GPT-4     │   │
│  └─────────────┘  └─────────────────────┘   │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │  Parent Dashboard (web UI)              │ │
│  │  - Write prompts for game generation    │ │
│  │  - Monitor kid's Almanach progress      │ │
│  │  - Configure Five voice settings        │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## BOM for First 5-10 Prototypes

| Item | Unit Cost | Qty 5 | Qty 10 |
|------|-----------|-------|--------|
| Beelink SER7 barebones (no RAM/SSD) | ~$350 | $1,750 | $3,500 |
| 32GB DDR5 SO-DIMM (2×16GB) | ~$80 | $400 | $800 |
| 1TB NVMe SSD (PCIe 4.0) | ~$60 | $300 | $600 |
| USB fingerprint sensor (SemOS auth) | ~$25 | $125 | $250 |
| 3D-printed enclosure (your design) | ~$15 | $75 | $150 |
| **Total per unit** | **~$530** | | |
| **Total batch** | | **$2,650** | **$5,300** |

Sell at cost (~$530) or slight markup (~$600) to early adopters.

---

## What About ARM? (Orange Pi 5 Plus)

You already have the Orange Pi 5 Plus. It has a role:

| Role | Why |
|------|-----|
| **SemOS development** | ARM is the long-term target architecture |
| **Low-power home server** | File storage, Home Assistant, lightweight services |
| **Almanach classroom pilot** | Proven, cheap, sufficient for tutoring |
| **NOT for Steam/gaming** | No x86 emulation performant enough for AAA |
| **NOT for big LLMs** | 8GB/16GB RAM too tight for 20B+ models |

**Two-track strategy:**
- **x86 prototypes now** (Beelink) — for Steam, emulators, 32GB LLMs
- **ARM v2 later** — when custom silicon or better ARM chips arrive

---

## Next Steps

1. **Order 1 Beelink SER7 barebones** — test the stack before buying 5
2. **Install Linux** (not Windows — SemOS target)
3. **Install Ollama + Gemma 4** — verify LLM performance
4. **Install Steam (Flatpak)** — verify emulation + gaming
5. **Install Five stack** — openWakeWord + whisper.cpp + piper TTS
6. **Build parent dashboard** — simple web UI for prompts and monitoring

---

*"The right hardware is the one that ships."*
