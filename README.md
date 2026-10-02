# RelicLab

> Open-source toolkit for composable AI agent identities: Personas, Skills, and Memory modules.
>
> 开源的可组合 AI Agent 身份工具箱：Persona（人格）、Skill（技能）与 Memory（记忆）模块。

[English](#english) | [中文](#中文)

---

## English

### Development Status

The engineering foundation is now implemented: independently buildable Core,
Runtime, CLI, and Server packages, locked development dependencies, quality checks,
and isolated wheel-installation tests. S01 adds strict asset models, validation,
JSON Schema export, and public examples through the `reliclab.schema` Python API.
S02 adds safe Markdown parsing, source coordinates, configurable limits, and
deterministic serialization through `reliclab.codec`.
See [SPEC.md](./SPEC.md) for the format, codec API, and semantic validation requirements.
Only `relic --version` and `relic doctor` are available in the CLI;
asset management, agent execution, and the Web UI are not implemented.
See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup and verification commands.

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

The project is in early development. Planned directions include:

- **Asset schemas (implemented, pre-release)** — strict models, format specification, JSON Schema, and examples; cross-platform acceptance tracked separately
- **Markdown codec (implemented, pre-release)** - restricted YAML parsing, source maps, bounded input, and canonical serialization; no file writes
- **CLI tool** — command-line composition and system prompt generation
- **Markdown sync** — bidirectional linking between Memory modules and local note files
- **Local management UI** — a lightweight web interface for creating, editing, and organizing modules
- **Module registry** — a community-driven repository for sharing Personas and Skills
- **Optional runtime** — agent execution, tool approvals, sessions, and task orchestration in a separate package

### Contributing

RelicLab is in its early stages. Contributions, ideas, and discussion are welcome. If you have thoughts on the schema design, module format, or use cases, feel free to open an issue.

### License

MIT

---

## 中文

### 开发状态

工程基础已实现：Core、Runtime、CLI、Server 四个可独立构建的包、锁定的开发依赖、质量检查和隔离 wheel 安装测试。S01 新增严格资产模型、校验、JSON Schema 导出与公开样例，Python API 位于 `reliclab.schema`；S02 在 `reliclab.codec` 中提供安全 Markdown 解析、源码位置、可配置限制及确定性序列化。格式、API 与语义校验要求见 [SPEC.md](./SPEC.md)。CLI 目前仍仅提供 `relic --version` 和 `relic doctor`；资产管理、Agent 执行与正式 Web UI 尚未实现。环境准备与验证命令见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

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

项目处于早期开发阶段。资产 Schema、严格模型、格式规范和样例，以及安全 Markdown 编解码（受限 YAML、源码映射、资源限制、规范序列化，不执行文件写入）已实现，属于预发布功能，跨平台验收单独记录。后续方向包括：CLI 工具（命令行组合与 prompt 生成）、Markdown 同步（Memory 与本地笔记双向链接）、本地管理界面（轻量 Web UI）、模块 Registry（社区共享仓库），以及独立可选 Runtime 包（Agent 执行、工具审批、会话及任务编排）。

### 参与贡献

RelicLab 尚在早期阶段，欢迎贡献、想法与讨论。如果你对 Schema 设计、模块格式或使用场景有想法，欢迎开 issue。

### 许可证

MIT
