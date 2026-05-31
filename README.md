# GStack Local Multi-Agent Sprint Console

A premium, state-of-the-art Single Page Web Application and local FastAPI server orchestrating a virtual engineering team inspired by Y Combinator CEO Garry Tan's **GStack** framework. 

The console operates entirely locally, routing all multi-agent reasoning tasks to your high-performance remote GPU workstation (`Jacks-Mac-Studio.local` serving a 30B `nvidia/nemotron-3-nano-omni` model) via **LM Link** mesh VPN connectivity over port `1234` on `Jacks-MacBook.local`.

---

## 🏗️ Premium Visual Architecture

```
                      ┌──────────────────────────────────────┐
                      │  Stunning Glassmorphic Dashboard UI  │ (Obsidian Dark Mode, HSL Curated Palette)
                      └──────────────────┬───────────────────┘
                                         │ REST API / WebSockets
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    FastAPI Orchestration Backend     │ (Python 3.11 / server.py)
                      └──────────────────┬───────────────────┘
                                         │
                                         ├──────────────────────────┐
                                         ▼                          ▼
                      ┌──────────────────────────────────────┐ ┌──────────────────────────────────────┐
                      │     Google Antigravity SDK Agent     │ │      Custom Local Agent Loop         │
                      │  (Configured with GStack Skills)     │ │   (Direct OpenAI-compatible driver)   │
                      └──────────────────┬───────────────────┘ └────────────┬─────────────────────────┘
                                         │                                  │
                                         └────────────────┬─────────────────┘
                                                          │ HTTP client
                                                          ▼
                      ┌──────────────────────────────────────┐
                      │     LM Link local API Router         │ (localhost:1234/v1)
                      └──────────────────┬───────────────────┘
                                         │ Tailscale VPN (Mesh network)
                                         ▼
                      ┌──────────────────────────────────────┐
                      │       Jacks-Mac-Studio.local         │ (High-performance remote GPU node)
                      │    (nvidia/nemotron-3-nano-omni)     │
                      └──────────────────────────────────────┘
```

---

## 🔥 Key Features

- **Staged YC Sprint Stages Workflow:** Coordinates agents sequentially through Garry Tan's sprint phases: **Think → Plan → Design → Build → Review → Test → Ship → Reflect**.
- **Virtual Sprint Team Personas (`skills/`):**
  - 🧠 **CEO Agent:** Analyzes product requirements and compiles structured Product Requirements Documents (PRDs).
  - 📋 **Engineering Manager Agent:** Handles layout specification, files mapping, and technical constraints.
  - 🎨 **Designer Agent:** Generates HSL style systems, layout styling, and CSS animations.
  - 🔨 **Coder Agent:** Implements code blocks and performs contiguous workspace edits.
  - 🧪 **QA Lead Agent:** Validates semantic code, accessibility (a11y) standards, and logs bug reports.
  - 🔍 **Release Engineer Agent:** Inspects diffs, conducts security audits, and writes official release logs.
- **Obsidian Dark-Mode UI:** Premium frosted-glass paneling, background animated flows, a glowing stages timeline, streaming typewriter agent logs, and code-diff viewer.
- **XML-Based Local ReAct Tools Loop:** Equips agents with reliable filesystem and terminal tools (`<read_file>`, `<write_file>`, `<list_directory>`, `<run_command>`) designed for high compliance on local-inference models.
- **Defensive Model Resolver:** Resolves active models directly from LM Studio and gracefully falls back to available non-embedding targets if needed.

---

## ⚡ Setup & Run Instructions

### Prerequisites
1. Ensure your remote GPU server (`Jacks-Mac-Studio.local`) is active and connected via Tailscale.
2. Launch your local LM Studio server on `Jacks-MacBook.local` to bind standard OpenAI traffic:
   ```bash
   lms server start --port 1234
   ```

### Quick Start
1. Navigate to the project directory and activate the python environment:
   ```bash
   cd /Users/jack/Documents/gstack-agents
   source .venv/bin/activate
   ```
2. Start the async FastAPI gateway server:
   ```bash
   python server.py
   ```
3. Open your browser and head to: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**
4. Compose your goal and launch the sprint!

---

## 🛠️ Folder Layout

```
gstack-agents/
├── skills/                  # Garry Tan's GStack agent roles config
│   ├── ceo/SKILL.md
│   ├── eng_manager/SKILL.md
│   ├── designer/SKILL.md
│   ├── coder/SKILL.md
│   ├── qa_lead/SKILL.md
│   └── release_engineer/SKILL.md
├── workspace/               # Physical workspace folder where agents build code
├── logs/                    # Sprint states and live-streaming logs
│   ├── sprint_state.json    # Shared orchestrator sprint telemetry
│   └── *.log                # Individual typewriter agent stream targets
├── server.py                # Async FastAPI gateway console backend
├── gstack_core.py           # Core agent orchestrator & ReAct loops
├── requirements.txt         # Required python packages
├── index.html               # Stunning obsidian dashboard UI
├── index.css                # Visual theme styling and animations
└── app.js                   # Client-side state manager and SSE/polling handlers
```
