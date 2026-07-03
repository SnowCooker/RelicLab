# RelicLab

> Open-source toolkit for composable AI agent identities: Personas, Skills, and Memory modules.
>
> 开源的可组合 AI Agent 身份工具箱：Persona（人格）、Skill（技能）与 Memory（记忆）模块。

[English](#english) | [中文](#中文)

---

## English

RelicLab is a modular, open-source framework for building and managing reusable AI agent identities. Instead of rewriting system prompts from scratch every time, RelicLab lets you define, store, and compose three core building blocks — Personas, Skills, and Memory — and mix them on demand for any LLM workflow.

### Why RelicLab

Current AI tooling forces you to choose between personality and capability. Chat interfaces excel at character but lack structured skill management. Agent frameworks offer powerful tooling but treat personality as an afterthought. There is no standard way to define, version, share, or reuse these components across projects.

RelicLab treats Personas, Skills, and Memory as first-class, composable assets.

### Core Modules

**Personas** — Structured character definitions for AI agents. A Persona describes how an agent thinks, communicates, and behaves — independent of what it can do. Personas are portable and can be shared, versioned, and reused across different LLM providers and workflows.

**Skills** — Modular capability units that define what an agent can do. A Skill encapsulates a prompt template, tool call definition, or behavioral instruction. Skills can be attached to any Persona or used standalone without any personality layer.

**Memory** — A persistent knowledge layer that connects agent context to your existing notes and documents. Memory modules can link to local Markdown files, enabling integration with tools like Obsidian and Logseq. Memory can be injected selectively into any agent session.

### Composition Model

RelicLab is designed around flexible, on-demand composition. Depending on your use case, you can use any combination of the three modules:

| Mode | Components |
|------|------------|
| Task-focused | Skills only |
| Character-focused | Persona only |
| Knowledge-focused | Memory only |
| Full agent | Persona + Skills + Memory |

### Roadmap

The project is in early design stage. Planned directions include:

- **Schema design** — standardized formats for Persona cards, Skill definitions, and Memory entries
- **CLI tool** — command-line composition and system prompt generation
- **Markdown sync** — bidirectional linking between Memory modules and local note files
- **Local management UI** — a lightweight web interface for creating, editing, and organizing modules
- **Module registry** — a community-driven repository for sharing Personas and Skills

### Contributing

RelicLab is in its early stages. Contributions, ideas, and discussion are welcome. If you have thoughts on the schema design, module format, or use cases, feel free to open an issue.

### License

MIT

---

## 中文

RelicLab 是一个模块化的开源框架，用于构建和管理可复用的 AI Agent 身份。你不必每次都从零重写 system prompt——RelicLab 让你定义、存储并组合三种核心构件（Persona、Skill、Memory），按需混搭，适用于任何 LLM 工作流。

### 为什么做 RelicLab

现有 AI 工具迫使你在"人格"与"能力"之间二选一：聊天界面擅长角色扮演，却缺乏结构化的技能管理；Agent 框架工具能力强大，却把人格当作事后补丁。目前没有一种标准方式来定义、版本化、分享和跨项目复用这些组件。

RelicLab 把 Persona、Skill 和 Memory 当作一等的、可组合的资产来对待。

### 核心模块

**Persona（人格）** — AI Agent 的结构化角色定义，描述 Agent 如何思考、表达与行事——与它"能做什么"解耦。Persona 可移植，可在不同 LLM 提供商与工作流之间分享、版本化和复用。

**Skill（技能）** — 定义 Agent 能力的模块化单元。一个 Skill 封装一段提示词模板、工具调用定义或行为指令。Skill 可以挂载到任意 Persona 上，也可以脱离人格层独立使用。

**Memory（记忆）** — 持久化知识层，把 Agent 上下文与你已有的笔记和文档连接起来。Memory 模块可以链接本地 Markdown 文件，与 Obsidian、Logseq 等工具集成，并可按需选择性地注入任意 Agent 会话。

### 组合模型

RelicLab 围绕灵活的按需组合设计，三种模块可任意搭配：

| 模式 | 组件 |
|------|------|
| 任务型 | 仅 Skill |
| 角色型 | 仅 Persona |
| 知识型 | 仅 Memory |
| 完整 Agent | Persona + Skill + Memory |

### 路线图

项目处于早期设计阶段。规划方向包括：Schema 设计（标准化格式）、CLI 工具（命令行组合与 prompt 生成）、Markdown 同步（Memory 与本地笔记双向链接）、本地管理界面（轻量 Web UI）、模块 Registry（社区共享仓库）。

### 参与贡献

RelicLab 尚在早期阶段，欢迎贡献、想法与讨论。如果你对 Schema 设计、模块格式或使用场景有想法，欢迎开 issue。

### 许可证

MIT
