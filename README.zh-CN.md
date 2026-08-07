<div align="center">
  <h1>Sonex</h1>
  <p><strong>运行于终端的 AI 音乐智能体。</strong></p>
  <p>
    <a href="README.md">English</a> ·
    <a href="README.zh-CN.md">简体中文</a>
  </p>
</div>

---

Sonex 是一个命令行音乐播放器，包含本地 React + Ink 终端界面，以及
FastAPI/WebSocket 后端。正常使用时只需要运行一个命令：`sonex` 会启动后端、
打开 TUI，并通过 WebSocket 同步聊天、设置提示、确认框和播放状态。

## 运行要求

运行 Sonex 安装脚本之前，请先安装这些系统运行时：

| 依赖 | 说明 |
| --- | --- |
| Python 3.12 | 必须可以通过 `python3.12` 调用 |
| Node.js 和 `npm` | 用于安装并构建终端界面 |
| Linux 或 WSL | 需要兼容的 shell 环境 |
| `vlc` 或 `mpv` | 可选；用于本地文件和 YouTube 播放 |

> [!NOTE]
> 安装脚本会检查 Python、Node.js 和 npm，但不会替你安装系统软件包。

## 安装

在项目 checkout 目录中运行：

```bash
./scripts/install.sh
```

安装脚本会：

- 创建或复用 `.venv`
- 安装 Python 包和依赖
- 使用 `npm ci` 安装 React + Ink TUI 依赖
- 构建 `src/cli-ui/dist/index.js`
- 在 `~/.local/bin/sonex` 创建用户可直接运行的 `sonex` 启动器

> [!TIP]
> 如果 `~/.local/bin` 不在你的 `PATH` 中，把它加入 shell 配置后重新打开 shell：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

安装脚本选项：

```bash
./scripts/install.sh --no-user-shim
./scripts/install.sh --force-user-shim
./scripts/install.sh --no-launch
```

使用 `--no-user-shim` 可以跳过创建 `~/.local/bin/sonex`。使用
`--force-user-shim` 可以把已有的 `sonex` shim 替换为当前 checkout 的启动器。
`--no-launch` 主要给 bootstrap 启动器使用，用于修复缺失的运行时组件。

## 开始使用

运行应用：

```bash
sonex
```

这会同时启动 FastAPI 后端和 React + Ink TUI，是推荐的启动方式。

调试时可以把后端和 TUI 拆到两个终端中运行：

```bash
sonex api
sonex tui
```

如果只运行 `sonex tui` 而后端没有启动，TUI 会提示 Sonex API 未运行。日常使用
请优先运行 `sonex`。

也可以直接运行 virtualenv 内部命令：

```bash
.venv/bin/sonex
```

## 验证安装

运行：

```bash
./scripts/doctor.sh
```

`doctor.sh` 会检查 Python 依赖、Node 依赖、TUI 构建产物、`sonex` 命令、
`~/.sonex`、可选本地播放器，以及 Spotify 配置状态。

## LLM Provider 设置

Sonex 默认把本地凭据保存到 `~/.sonex`。如果想使用其他状态目录，可以设置
`SONEX_HOME`。

Sonex 优先为主流云端 LLM provider 调用官方 API：

| Provider | 集成方式 |
| --- | --- |
| OpenAI | 官方 chat completions 接口 |
| Anthropic | 官方 messages 接口 |
| Gemini | 官方 generate content 接口，配置 OAuth 时包含 Authorization header |
| DeepSeek | 官方 API adapter |
| LiteLLM | 作为自定义或暂未 native 化 provider 的兼容 fallback 保留；不是以上云端 provider 的默认调用路径 |

使用以下命令管理 LLM provider 凭据：

```bash
sonex auth login openai
sonex auth set-key openai
sonex auth list
sonex auth set-default openai
sonex auth logout openai
```

也可以使用环境变量配置：

```bash
export SONEX_DEFAULT_PROVIDER=openai
export SONEX_DEFAULT_MODEL=gpt-5.5
export SONEX_OPENAI_API_KEY=sk-...
export SONEX_ANTHROPIC_API_KEY=sk-ant-...
export SONEX_GEMINI_API_KEY=...
export SONEX_DEEPSEEK_API_KEY=sk-...
```

> [!WARNING]
> 不要把 API Key 或 Sonex 保存的凭据提交到版本控制。建议使用 `sonex auth`
> 管理本地密钥；环境变量应通过安全的本地密钥存储或部署密钥系统提供。

如果默认 provider 还没有配置好就开始聊天，TUI 会先进入交互式设置流程，不会
直接开始 planner 或 agent 工作。把 `ollama` 配置为默认 provider 时，可以作为
本地 provider 使用。

Sonex 会加载 `.env`，然后按以下顺序解析运行时配置：环境变量、`sonex auth`
保存的凭据，最后是 JSON 配置文件。设置 `SONEX_CONFIG_PATH` 可以使用
`~/.sonex/thinking.json` 之外的配置文件。

高级用户仍然可以在 `~/.sonex/thinking.json` 中按 provider 覆盖
`base_url`、`model`、`timeout`、`extra_headers` 和 `options`：

```json
{
  "default_provider": "openai",
  "default_model": "gpt-5.5",
  "providers": {
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-5.5",
      "timeout": 60,
      "extra_headers": {},
      "options": {}
    }
  },
  "beads": {
    "brand": "hama"
  }
}
```

## 音乐服务设置

执行 `/connect` 会打开交互式音乐账号连接面板，其中列出 Spotify、网易云音乐、
Jamendo 和 Audius。可用性检查由各服务独立完成，不会静默改变当前播放 provider。

> [!NOTE]
> 连接记录只保存非敏感的账号标识与健康状态；OAuth token 仍由现有本地组件持有。

> [!NOTE]
> Sonex 会自动清除自身状态中已保存的 `apple_music`、`apple_mode` 凭据、连接记录和
> 模式意图。如果此前设置过 `SONEX_APPLE_*` 环境变量，需要从 shell 配置中手动移除；
> Sonex 不会删除外部 `.p8` 文件。

### Spotify

在 TUI 中输入：

```text
setup spotify
```

Sonex 会引导你创建 Spotify app、添加 loopback Redirect URI、输入 Client ID 和
Client Secret，并完成浏览器授权。

也可以从 CLI 启动 Spotify OAuth 流程：

```bash
sonex auth login spotify
```

Spotify app credentials 可以来自 `SPOTIFY_CLIENT_ID` 和
`SPOTIFY_CLIENT_SECRET`，也可以通过 TUI 引导设置保存。Spotify 播放控制需要
Spotify 账号和可用的 Spotify Connect 设备；播放控制需要 Premium。

设置完成后，可用 `/spotify` 进入持久化 Spotify 模式。进入前会检查已登录
Premium 账号、播放控制、playlist read scopes 和 `user-library-read` scope，以及
至少一个可用的 Spotify Connect 设备。成功进入后，Sonex 会在后续对话中恢复
Spotify mode，直到本地 Spotify token 过期、缺少必要 scopes，或你执行 `/spotify`
并在退出面板中确认。启动时的恢复只检查本地 token 和已保存设备信息，不调用 Spotify
账号或设备 API。模式开启后，播放/搜索、推荐、歌单和当前播放都会只使用 Spotify 工具。
在 Spotify mode 下，`/recommend [taste]` 会展示 5 首编号 Spotify 推荐，并把它们加入
所选设备的 Spotify 队列，不会直接开始播放。在 Spotify 模式下，`/playlist` 会立即打开本地歌单浏览器，
仅在持久化镜像过期时才在后台刷新 Spotify 数据。已点赞歌曲在每周全量校准之间采用增量合并，
`snapshot_id` 未变化的 Spotify 歌单不会重复下载曲目。成功镜像的有效期为 6 小时；连接失败后
至少退避 15 分钟，如果 Spotify 返回更长的 `Retry-After` 则按其执行。普通 Sonex 模式仍可浏览
已导入的 Spotify 镜像，但 `/playlist save`
只会写入可编辑的 Sonex 歌单。`/queue` 会打开 Spotify 实时播放队列。如果 Spotify 返回
`429 Too Many Requests`，Sonex 会保留服务端返回的重试时间，并在冷却期内避免重复触发同步请求。
代理不可用、连接超时、TLS 错误和读取超时会显示不同的诊断信息。
如果已保存 token 缺少新增的 Spotify scopes，Sonex 会在当前聊天区启动 Spotify 授权引导，
帮助你授予更新后的权限。

### 本地和 YouTube 播放

如果需要可控制的本地文件或在线播放，请安装 `mpv` 或 VLC。每个会话初次执行
`/player` 时，Sonex 会检测已安装且受支持的应用。Sonex 管理的 mpv/VLC，以及
Clementine、Rhythmbox、Audacious 等受支持的独立播放器，都可以设为设备默认播放器；
只能遥控、不能接收音频的 MPRIS 应用仍会显示为不可选项。Spotify Connect 仍使用
独立的 provider mode，不使用这些本地播放器。

### 在线音频回退

普通模式会优先使用本地文件，随后通过在线音频源解析选中的歌曲。Spotify 播放归属
Spotify Mode。iTunes Search 仍属于普通搜索链路中的元数据发现能力，不是播放模式。
至少配置一个在线音频 provider：

执行 `/connect` 并选择 Jamendo 或 Audius。

也可以通过环境变量提供凭据：

```bash
export SONEX_JAMENDO_CLIENT_ID=...
export SONEX_AUDIUS_API_KEY=...
```

解析器会把用户选中的歌曲身份和 provider 元数据分开保存，会重新校验缓存音频，并
在候选不可用时把 provider fallback 原因显示到 TUI 中。

## 播放教程

使用自然语言播放请求：

```text
play Space Oddity David Bowie
play Mitski Nobody
播放 方大同 忘了美丽
```

Sonex 会先检查匹配的本地文件；没有本地结果或跳过本地后，普通模式会直接展示最多
五个元数据候选并进入 Sonex 在线音频流程，不再询问播放 provider。`/recommend [taste]` 会先返回编号
文本列表，默认 5 首；有 taste 时优先按用户输入推荐，再参考最近播放和 `USER.md`
偏好，并把推荐曲目加入 Sonex 播放队列但不直接播放。之后可以继续要求播放某一项，
例如 `play number 2` 或 `播放第2首`。

本地或在线曲目播放时，可以使用：

```text
/pause
/resume
/stop
/progress
/volume 65
/player
```

每个会话初次执行 `/player` 时会检测受支持且已安装的应用，并打开默认播放器面板。
选择兼容播放器后，后续本地和在线音频播放会直接使用持久化的设备默认项，不再重复
选择；取消则保持当前默认值不变。

## 封面珠子图

TUI 可以把专辑封面渲染成静态实体拼豆图。Sonex 会优先使用官方封面，随后生成
`40x40`、`48x48`、`56x56`、`64x64`、`80x80`、`96x96` 这几档缓存方形变体。
当前算法使用共享、无抖动的 32 到 72 色调色板，并提高 80 和 96 预览尺寸的权重；
旧算法 profile 的缓存会自动失效并重新生成。

支持的拼豆目录是 5 mm Hama Midi、Perler Classic 和 Mard Standard Opaque。
Mard 的品牌/色号身份来自打包的官方品牌参考，RGB 近似值继续来自可再分发的社区
`beadcolors` 目录。可以在 `~/.sonex/thinking.json` 或 `SONEX_CONFIG_PATH`
指向的文件中配置品牌：

```json
{
  "beads": {
    "brand": "perler"
  }
}
```

如果省略 `beads.brand`，Sonex 使用 `hama`。生成的图案保存在
`~/.sonex/cache/cover_patterns`，该缓存不会保存原始封面图片字节。

## 故障排查

- **`sonex: command not found`：**确认 `~/.local/bin` 在 `PATH` 中，然后运行
  `./scripts/doctor.sh`。
- **找到了其他 `sonex` 命令：**在当前 checkout 中运行
  `./scripts/install.sh --force-user-shim`。
- **运行时文件缺失：**再次运行 `sonex`，bootstrap 启动器可以修复 `.venv`、TUI
  依赖和已构建的 TUI；也可以重新运行 `./scripts/install.sh`。
- **TUI 提示 API 未运行：**日常使用运行 `sonex`；调试时先运行 `sonex api`，再运行
  `sonex tui`。
- **Spotify 无法播放：**scope 缺失时按 TUI 中的重授权引导操作，或重新运行
  `sonex auth login spotify`；检查账号 product，并确认 Spotify 已在某个设备上打开。
- **本地或在线播放无法启动：**安装 `mpv` 或 VLC，启动新会话后执行 `/player`，
  再选择检测到的应用。
- **封面珠子图没有出现：**检查 `beads.brand`，用带官方封面的曲目重新播放，并查看
  `~/.sonex/log` 中的封面生成错误。
