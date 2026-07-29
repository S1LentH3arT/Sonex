# Codex CLI 与 Pi CLI 的 Bash 命令配色调研

日期：2026-07-29

## 结论

Codex CLI 与 Pi CLI 代表两种不同的设计：

- **Codex CLI 对命令本体做 Bash 语法高亮**。可执行命令、字符串、操作符、变量、注释等由 Bash grammar 分段，再由当前 syntax theme 决定颜色；不是一份固定的“参数蓝色、路径绿色”硬编码表。审批面板和已执行命令单元都复用这条高亮路径。
- **Pi 的 Agent `bash` 工具不做 shell 语法高亮**。`$ ` 与整条原始命令统一使用 `toolTitle` 并加粗，只有 `timeout` 等外围信息切换到 `muted`；命令内部的选项、路径、字符串、管道和重定向不会分别着色。
- **Pi 的用户手动 `!command` 又是另一套语义色**：整条命令与边框使用 `bashMode`，默认是绿色；`!!command` 的初始边框和命令使用 `dim`，表示“不送入模型上下文”。
- 两者都没有在命令行前显示 `Bash` 工具名。Codex 审批面板显示 `$ `，Pi 的两种 Bash 展示也显示 `$ `。

因此，不能概括为“主流终端工具都会给 Bash 不同字段固定配色”。准确说法是：

1. Codex 采用**语法级、多色、主题驱动**方案；
2. Pi 的 Agent 工具采用**整条命令单色 + 元数据后缀弱化**方案；
3. Pi 的手动 shell 模式采用**整条命令模式色 + 状态色**方案。

本报告固定到以下官方仓库提交：

- OpenAI Codex：[`3725f02cf38d856bc82bb46dd68ab61bb96ec6fc`](https://github.com/openai/codex/commit/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc)
- Pi：[`4f0437e2d58d651dd934119ecabea2893975f62f`](https://github.com/earendil-works/pi/commit/4f0437e2d58d651dd934119ecabea2893975f62f)

## 项目身份与研究边界

这里的 Pi 指 **Pi Agent Harness 的交互式编码代理 CLI**：

- 官方仓库 README 将 `@earendil-works/pi-coding-agent` 定义为 “Interactive coding agent CLI”；
- 包的 `bin` 字段把命令名定义为 `pi`，描述明确包含 `read`、`bash`、`edit` 和 `write` 工具；
- 本次固定提交中的包版本是 `0.82.1`。

来源：

- [Pi 官方仓库对 coding-agent 包的定义](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/README.md#L10-L28)
- [Pi coding-agent 的包名、描述和 `pi` executable](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/package.json#L1-L10)
- [Pi coding-agent README：四个默认工具与 `!command` 入口](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/README.md#L52-L81)

旧的 `badlogic/pi-mono` GitHub URL 当前会重定向到 `earendil-works/pi`。在“编码代理终端 CLI”这一上下文中，项目身份没有剩余歧义；其他同名 Pi 项目不在本报告范围内。

本报告只研究交互式终端中的命令本体、前缀、后缀和紧邻状态，不把 Markdown code block、普通聊天文本或命令自身输出的 ANSI 配色当成“Bash 命令配色”。

## Codex CLI

### 审批面板中的命令

当前审批面板执行以下步骤：

1. 去掉外层 `bash -lc` 等 shell wrapper，取得实际脚本；
2. 用 `highlight_bash_to_lines()` 做 Bash 语法高亮；
3. 只在首行前插入 `$ `；
4. 不显示 `Bash` 工具名。

`$ ` 在审批面板中没有额外颜色样式，继承终端默认前景色；脚本本体由 syntax theme 逐 token 着色。

来源：

- [审批面板构造命令行并调用 Bash highlighter](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/bottom_pane/approval_overlay.rs#L701-L709)
- [`highlight_bash_to_lines()` 明确使用 `bash` grammar](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/render/highlight.rs#L663-L692)

### 命令字段的颜色来源

Codex 没有为“命令名、选项、路径、字符串、管道、重定向”各写一条固定的 Ratatui 颜色规则。实际流程是：

```text
原始 Bash 脚本
  -> two_face 的 Bash grammar / syntect scope
  -> 当前 syntax theme 的 scope style
  -> Ratatui foreground + bold
```

因此可确认的是**字段类别会被语法分段**，但具体 RGB 会随主题变化。当前默认主题会根据终端背景自动选择：

- 深色背景：`catppuccin-mocha`
- 浅色背景：`catppuccin-latte`

用户还可以通过 `[tui].theme`、`/theme` 或 `$CODEX_HOME/themes/*.tmTheme` 改写。官方源码列出 32 个 bundled themes，并支持自定义 `.tmTheme`；所以产品设计不应把某个 Codex 截图中的 RGB 当成稳定协议。

Codex 转换 theme style 时只保留 foreground 和 bold，明确丢弃 background、italic 与 underline。这意味着即使上游 theme 把 comment 或 function 标成斜体，终端命令行也不会继承这些装饰。

来源：

- [highlighter 使用 grammar scope 与当前 theme 生成 styled spans](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/render/highlight.rs#L597-L660)
- [深浅背景的自适应默认主题](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/render/highlight.rs#L189-L229)
- [bundled theme 名单](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/render/highlight.rs#L140-L175)
- [theme style 转换只保留 foreground 与 bold](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/render/highlight.rs#L453-L527)
- [`[tui].theme` 配置和自定义 theme 入口](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/config/src/types.rs#L745-L750)

官方 snapshot 给出一个可复核的默认深色主题实例：

| Bash 片段 | 当前 snapshot 样式 |
| --- | --- |
| `echo`（可执行命令） | RGB `137, 180, 250`，即 `#89b4fa` |
| ` output`（普通参数及前导空格） | RGB `205, 214, 244`，即 `#cdd6f4` |

这只能证明当前 Catppuccin Mocha 对这个输入的结果，不能推广成所有主题的固定色表。

来源：

- [Codex 官方 exec-cell snapshot 中的 token 级 RGB](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/snapshots/codex_tui__exec_cell__render__tests__truncated_live_output_preview_and_transcript.snap#L5-L14)

### 已执行命令的前缀、状态和后缀

| 字段 | Codex 样式 | 语义 |
| --- | --- | --- |
| 活动中 bullet / spinner | 动画状态；静态 fallback 为 `dim` 的 `•` | 正在执行 |
| 成功 bullet | `green + bold` | exit code 为 0 |
| 失败 bullet | `red + bold` | exit code 非 0 |
| `Running` / `Ran` / `You ran` | `bold`，默认前景色 | Agent 正在运行 / 已运行 / 用户手动运行 |
| 命令本体 | Bash syntax theme | 语法级字段区分 |
| 多行命令延续缩进 | `dim` | 结构辅助 |
| 命令或输出省略提示 `… +N lines (...)` | `dim` | 次要元信息 |
| transcript 的 `$ ` | `magenta` | Codex 品牌 / Agent 前缀语义 |
| transcript 成功符号 `✓` | `green + bold` | 成功 |
| transcript 失败符号 `✗` | `red + bold` | 失败 |
| transcript 失败码 ` (N)` | 默认前景色 | 具体 exit code |
| transcript 耗时 ` • duration` | `dim` | 次要元信息 |

来源：

- [active/completed command header、成功/失败 bullet 和命令 highlighter](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/render.rs#L352-L429)
- [transcript 的 magenta `$ `、成功/失败符号、exit code 和耗时](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/render.rs#L195-L235)
- [省略提示使用 `dim`](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/render.rs#L621-L646)
- [Codex TUI 官方颜色语义：cyan、green、red、magenta 与 dim](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/styles.md#L1-L19)

命令输出不是按 Bash 字段重新着色。Codex 解析输出中已有的 ANSI 样式，然后给整个 output preview 叠加 `dim`；因此输出中的红绿可能来自被执行程序，而不是 Codex 为 stdout/stderr 固定指定的颜色。

来源：

- [command output 保留 ANSI span 并追加 `DIM`](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/render.rs#L103-L168)

### 用户手动 `!command` 输入

在输入阶段，Codex 把 `!` prompt 和 footer 的 `Shell mode` 显示为 `LightRed`；输入的命令文本本身没有在 composer 中做 Bash syntax highlighting。提交后，它进入上述 exec cell 并按 Bash grammar 着色，标题使用 `You ran`。

来源：

- [`!` prompt 使用 `light_red + bold`](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/bottom_pane/chat_composer.rs#L4706-L4728)
- [`Shell mode` footer 使用 `light_red`](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/bottom_pane/chat_composer.rs#L3401-L3409)
- [exec cell 区分用户命令并显示 `You ran`](https://github.com/openai/codex/blob/3725f02cf38d856bc82bb46dd68ab61bb96ec6fc/codex-rs/tui/src/exec_cell/render.rs#L365-L387)

## Pi CLI

### Agent `bash` 工具调用

Pi 的 Agent Bash 调用格式是：

```text
$ <raw command> (timeout Ns)
```

字段映射如下：

| 字段 | Pi theme token / 样式 | 默认 dark | 默认 light |
| --- | --- | --- | --- |
| `$ ` + 原始命令 | `toolTitle + bold` | `text` → `#d4d4d4` | `text` → `#1f2328` |
| ` (timeout Ns)` | `muted` | `gray` → `#808080` | `mediumGray` → `#6c6c6c` |
| 命令尚未完整时的 `...` | `toolOutput` | `gray` → `#808080` | `mediumGray` → `#6c6c6c` |
| 参数类型非法时的 `[invalid arg]` | `error` | `red` → `#cc6666` | `red` → `#aa5555` |

关键边界：

- 命令本体内部没有字段级配色；`git`、`status`、`--short`、路径、引号、`&&` 和 `|` 都在同一个 `toolTitle` span 中。
- `timeout` 是唯一直接附加在命令行上的常规元数据后缀，使用 `muted`，不随命令加粗。
- 此行不显示 cwd，也不显示 `Bash` 工具名。

来源：

- [Pi `formatBashCall()` 的完整字段和 token 映射](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/core/tools/bash.ts#L222-L232)
- [`[invalid arg]` 使用 `error`](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/core/tools/render-utils.ts#L66-L84)
- [默认 dark theme 的 `toolTitle`、`toolOutput`、`muted` 和颜色变量](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/theme/dark.json#L4-L45)
- [默认 light theme 的对应 token](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/theme/light.json#L4-L44)

### Agent `bash` 结果与外围状态

这些不是命令本体字段，但解释了 Pi 为何不需要在命令内部承载过多状态色：

| 字段 | Pi token |
| --- | --- |
| stdout/stderr 展示 | `toolOutput` |
| `... (N earlier lines, key to expand)` 的普通提示 | `muted` |
| 提示中的按键 | `dim` |
| `[Full output: ... / Truncated: ...]` | `warning` |
| `Elapsed Ns` / `Took Ns` | `muted` |
| 工具执行中背景 | `toolPendingBg` |
| 成功背景 | `toolSuccessBg` |
| 错误背景 | `toolErrorBg` |

非零 exit code、abort 和 timeout 会成为工具错误文本；Bash renderer 将结果文本按 `toolOutput` 显示，错误状态主要再由 `toolErrorBg` 表达，而不是把命令行尾部的 exit code 单独染红。

来源：

- [output、折叠提示、warning 与 elapsed/took token](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/core/tools/bash.ts#L248-L313)
- [abort、timeout 与 non-zero exit 的错误文本生成](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/core/tools/bash.ts#L424-L454)
- [工具 pending/success/error 背景切换](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/tool-execution.ts#L253-L266)
- [按键为 `dim`、说明为 `muted`](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/keybinding-hints.ts#L34-L48)

### 用户手动 `!command` / `!!command`

Pi README 的契约是：

- `!command`：运行并把输出送入 LLM；
- `!!command`：运行但不把输出送入 LLM。

两者使用独立的 `BashExecutionComponent`，而不是 Agent `bash` 工具的 `formatBashCall()`。

| 字段 | `!command` | `!!command` |
| --- | --- | --- |
| `$ ` + 整条命令 | `bashMode + bold` | 初始 frame 为 `dim + bold` |
| 上下边框 | `bashMode` | `dim` |
| spinner | `bashMode` | `dim` |
| `Running...` | `muted` | `muted` |
| output | `muted` | `muted` |
| `(cancelled)` | `warning` | `warning` |
| `(exit N)` | `error` | `error` |
| `Output truncated. Full output: path` | `warning` | `warning` |

默认 dark/light theme 都把 `bashMode` 指向各自的 `green`：

- dark：`#b5bd68`
- light：`#588458`

来源：

- [`!` 与 `!!` 的公开语义](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/README.md#L139-L148)
- [手动 Bash 组件的命令、边框、spinner 和 running token](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/bash-execution.ts#L32-L64)
- [output、cancelled、exit code 和 truncation warning token](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/bash-execution.ts#L119-L203)
- [官方 theme 文档对 `bashMode` 的定义](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/docs/themes.md#L234-L238)

当前源码有一个应谨慎记录的细节：`!!command` 在 constructor 中把命令 header 设为 `dim`，但第一次 output/status 更新重建 header 时使用了固定的 `bashMode`；边框仍保留 `dim`。所以其稳定完成态更接近“绿色命令 + dim 边框”，而不是整块始终 dim。这是当前源码行为，不应当被当作值得复制的设计规范。

来源：

- [constructor 根据 `excludeFromContext` 选择 `dim` / `bashMode`](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/bash-execution.ts#L32-L52)
- [update 时 header 固定回 `bashMode`](https://github.com/earendil-works/pi/blob/4f0437e2d58d651dd934119ecabea2893975f62f/packages/coding-agent/src/modes/interactive/components/bash-execution.ts#L134-L150)

## 对 Sonex 确认面板决策的直接参考

如果目标是“只显示原始命令，不显示 Bash 工具名”，两套先例都支持这个边界，但后续有两条可选路线：

| 路线 | 参考实现 | 优点 | 代价 |
| --- | --- | --- | --- |
| 整条命令主色，后缀弱化 | Pi Agent `bash` | 稳定、容易控制对比度；多行脚本不会出现过多颜色；适合确认面板 | 扫描命令结构的帮助较少 |
| Bash syntax highlighting | Codex CLI | 能快速区分 command、string、operator、variable、comment 等语法角色 | 需要 grammar、主题、深浅背景、fallback、超长行和 ANSI 安全策略；具体 RGB 不能只定一套 |

无论选哪条路线，一手源码都不支持“只把工具名染色、命令保持白色”作为这两个 CLI 的现行做法：

- Codex 不显示工具名，直接高亮命令；
- Pi 不显示工具名，整条命令统一走 `toolTitle`；
- 可选元数据如 timeout、耗时、折叠数量和路径提示才使用 `muted` / `dim` / `warning` 等外围语义色。
