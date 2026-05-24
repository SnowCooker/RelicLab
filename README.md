# RelicLab

> Open-source toolkit for composable AI agent identities: Personas, Skills, and Memory modules.

RelicLab is a modular, open-source framework for building and managing reusable AI agent identities. Instead of rewriting system prompts from scratch every time, RelicLab lets you define, store, and compose three core building blocks — Personas, Skills, and Memory — and mix them on demand for any LLM workflow.

---

## Why RelicLab

Current AI tooling forces you to choose between personality and capability. Chat interfaces excel at character but lack structured skill management. Agent frameworks offer powerful tooling but treat personality as an afterthought. There is no standard way to define, version, share, or reuse these components across projects.

RelicLab treats Personas, Skills, and Memory as first-class, composable assets.

---

## Core Modules

### Personas
Structured character definitions for AI agents. A Persona describes how an agent thinks, communicates, and behaves — independent of what it can do. Personas are portable and can be shared, versioned, and reused across different LLM providers and workflows.

### Skills
Modular capability units that define what an agent can do. A Skill encapsulates a prompt template, tool call definition, or behavioral instruction. Skills can be attached to any Persona or used standalone without any personality layer.

### Memory
A persistent knowledge layer that connects agent context to your existing notes and documents. Memory modules can link to local Markdown files, enabling integration with tools like Obsidian and Logseq. Memory can be injected selectively into any agent session.

---

## Composition Model

RelicLab is designed around flexible, on-demand composition. Depending on your use case, you can use any combination of the three modules:

| Mode | Components |
|------|------------|
| Task-focused | Skills only |
| Character-focused | Persona only |
| Knowledge-focused | Memory only |
| Full agent | Persona + Skills + Memory |

---

## Roadmap

The project is in early design stage. Planned directions include:

- **Schema design** — standardized formats for Persona cards, Skill definitions, and Memory entries
- **Local management UI** — a lightweight web interface for creating, editing, and organizing modules
- **CLI tool** — command-line composition and system prompt generation
- **Markdown sync** — bidirectional linking between Memory modules and local note files
- **Module registry** — a community-driven repository for sharing Personas and Skills

---

## Contributing

RelicLab is in its early stages. Contributions, ideas, and discussion are welcome. If you have thoughts on the schema design, module format, or use cases, feel free to open an issue.

---

## License

MIT
