# ai-helper — Feature Suggestions & Roadmap

A phased plan for evolving `ai-helper` from an early prototype into a dependable
general-purpose dev assistant. Phases are ordered by dependency, not by
excitement — later phases get much better if earlier ones are in place.

Use the checkboxes to track progress. Re-prioritize freely; this is a menu,
not a contract.

---

## Phase 0 — Foundation

Unsexy, but everything else depends on it.

- [ ] Config system (YAML/TOML) with per-project overrides via `.aihelper.yaml`
- [ ] Provider abstraction (swap Claude / OpenAI / Gemini / local Ollama behind one interface)
- [ ] Token and cost tracking — per session and cumulative
- [ ] Move prompts out of code into a versioned `prompts/` directory
- [ ] Conversation history store (SQLite or JSONL) — unlocks resume, search, evals later
- [ ] Secrets handling with redaction in logs and crash dumps

---

## Phase 1 — Context Gathering

The single biggest quality lever. LLMs without context are shallow.

- [ ] File reader with `.gitignore` awareness and binary detection
- [ ] Repo tree sampler producing a compressed structure view for prompts
- [ ] Symbol/function extraction via tree-sitter (send only relevant code)
- [ ] Git state provider (branch, diff, recent commits, staged vs. unstaged)
- [ ] Stdout/stderr capture from running commands, fed back to the assistant
- [ ] File selection with a hard token budget
- [ ] Optional embedding search over the repo — start with ripgrep, upgrade later

---

## Phase 2 — Core Dev Workflows

The features that justify the tool existing at all.

- [ ] Explain this file / function / error
- [ ] Code review on a diff or staged changes
- [ ] Commit message generation from staged diff (conventional commits)
- [ ] PR description from branch commits
- [ ] Test generation for a selected function
- [ ] Refactor suggestions (naming, dead code, extract function)
- [ ] Docstring generation
- [ ] README and CHANGELOG generation / updating
- [ ] Stack trace analysis with proposed fixes
- [ ] Shell command generation from natural language

---

## Phase 2.5 — Firmware / IoT Flavor *(optional, given Mapit context)*

Useful specifically for embedded and IoT work. Skip if keeping strictly general.

- [ ] Serial log parser with pattern highlighting and anomaly flagging
- [ ] Hex / binary diff helper with human-readable annotations
- [ ] MCU datasheet Q&A (upload PDF, ask about registers, pinouts, errata)
- [ ] CAN / UART / SPI trace explainer
- [ ] AT-command session helper for cellular / GNSS modems
- [ ] Firmware release notes generator from git history
- [ ] Crash dump / coredump interpretation

---

## Phase 3 — Interactive Modes

UX matters more than feature count once the basics work.

- [ ] REPL / chat mode with history
- [ ] `--continue` to resume the last session
- [ ] Agent mode with shell execution behind confirmation prompts
- [ ] Streaming output (no staring at blank terminals)
- [ ] Syntax-highlighted output (rich / textual)
- [ ] Diff preview before any file edit
- [ ] Undo stack for file changes

---

## Phase 4 — Integrations

Meet users where they already work.

- [ ] Thin VS Code / Zed extension that just calls the CLI
- [ ] Git hooks for commit message and pre-push review
- [ ] Shell integration: last command failed → one keypress explains why
- [ ] Watch mode over a log file with rolling summary
- [ ] Minimal web UI (FastAPI + htmx) — only once the CLI is loved

---

## Phase 5 — Project Memory

Where the tool goes from useful to indispensable.

- [ ] Per-project knowledge file of facts the model should always know
- [ ] Auto-detected project conventions (language, formatter, test runner) cached in `.aihelper/`
- [ ] Persistent todos / tasks per project
- [ ] Rolling conversation summarization to stay under token limits

---

## Phase 6 — Quality & Longevity

Easy to skip, painful not to.

- [ ] Eval harness with input/expected-output pairs (prevents silent prompt regressions)
- [ ] Prompt versioning with A/B comparison
- [ ] Response cache keyed on input hash for deterministic prompts
- [ ] Plugin system — **only after** the core stabilizes

---

## Recommended Rollout

**Week 1:** Phase 0 foundation + two Phase 2 wins — commit-message generator
and diff review. Highest daily value for minimal surface area.

**Week 2:** Phase 1 context gathering. Every subsequent feature gets better
once this exists.

**Weeks 3+:** Pick one Phase 2 feature per week, driven by what you actually
reach for in daily work.

**Defer:** VS Code extension and plugin system until the CLI has been used
daily for a month. Otherwise you're maintaining surface area you don't
benefit from.

---

## Anti-Patterns to Avoid

- LangChain or similar frameworks at prototype stage — abstraction debt you can't afford yet
- Agent autonomy before single-turn features are solid
- "Support every provider" perfectionism — pick two and ship
- A web UI before the CLI feels good
- Building a plugin system speculatively
- Prompt changes without evals — you *will* regress silently

---

## Open Questions

Questions worth answering before committing to direction:

- [ ] Primary user: just me, my team, or public?
- [ ] Primary language stack to optimize for first?
- [ ] Hard budget ceiling per month (drives provider and caching choices)?
- [ ] Offline / on-prem requirement? (decides whether local models are Phase 0 or Phase 6)
- [ ] Single-binary distribution, or happy with `pip install` / `npm i -g`?
