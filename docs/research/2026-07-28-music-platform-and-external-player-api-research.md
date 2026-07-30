# 国内音乐平台与 Linux 外部播放器控制能力调研

日期：2026-07-28

## 结论

不能把“网络音乐平台 API”“控制已运行的独立播放器”和“让独立播放器播放 Sonex 指定的音频”视为同一种能力。

- **网易云音乐**已有官方开放平台和官方 `ncm-cli`，可做用户登录、用户信息、搜索、歌单和播放控制，是三家中最接近 Sonex Music Agent 的官方入口。默认后端仍是本地 `mpv`；直接调用网易云音乐 App 的 `orpheus` 后端仅支持 macOS。它不是跨设备的 Spotify Connect 等价物。
- **酷狗音乐**有面向第三方的官方曲库组件、搜索和嵌入播放 SDK，也有腾讯云 IoT 场景下的用户授权与设备播控；但控制目标是嵌入 Sonex/第三方应用的播放器或厂商接入的 IoT 设备，不是用户电脑上已经安装的酷狗客户端。
- **QQ 音乐**通过腾讯连连 / IoT Explorer 提供账号授权、会员权益、个人歌单、搜索、播放 URL 和向自有设备点播等能力；未找到控制用户现有 QQ 音乐桌面或手机客户端的公共远控 API。
- Linux 本地独立播放器中，**Clementine 和 Rhythmbox**同时具备 MPRIS 基础播控和 `OpenUri`，能接收 Sonex 提供的本地文件或受支持网络 URI；**Audacious**的 MPRIS 插件只做基础播控，不实现 `OpenUri`，但其官方命令行、`audtool` 和私有 D-Bus 接口可以打开 URI。
- 用户提到的 **Mineradio** 是 `XxHuberrr/Mineradio`。官方当前将桌面版描述为 Windows 应用，官网发布平台为 Windows、macOS、Android 和 Web，**没有 Linux 版，也没有公开的 MPRIS、CLI 或远控接口**。名称相近的 **Mini Radio Player** 确实提供 Linux x86_64 包，但官方帮助中心未公开 MPRIS、CLI、D-Bus 或 URI 注入能力，不能仅凭“已安装”将其列为 Sonex 可控播放器。

对 `/player` 的直接含义是：应把播放器建模为一组经过探测的能力，而不是一个可执行文件名。至少要区分 `transport_control`、`open_uri`、`queue`、`status`、`account` 和 `provider_catalog`；只有既能启动或连接、又能接受 Sonex 音频的适配器，才能作为普通模式的默认播放器。

## 研究边界

本报告只使用官方开放平台、官方开发者文档、官方仓库源码和 freedesktop.org 标准。没有使用网易云、QQ 音乐或酷狗的社区逆向 API 推导官方能力。

下表中的含义：

| 能力 | 判定标准 |
| --- | --- |
| 用户授权 / 信息 | 第三方应用有官方登录授权流程，并能取得用户或用户权益数据 |
| 曲库搜索 / 元数据 | 官方接口能搜索歌曲或返回曲目、歌手、专辑等数据 |
| 播放控制 | 能播放、暂停、切歌或指定歌曲；同时注明控制的是第三方自有播放器、IoT 设备还是平台官方客户端 |
| 控制已运行播放器 | 对播放器当前队列执行播放、暂停、上一首、下一首等 |
| 注入 Sonex 音频 | 把 Sonex 已取得的 `file://`、本地路径或 `http(s)://` 音频交给播放器打开 |

## 国内网络音乐平台

### 结论表

| 平台 | 用户授权 / 信息 | 曲库搜索 / 元数据 | 播放控制 | 商业接入 | 对 Sonex 的判定 |
| --- | --- | --- | --- | --- | --- |
| 网易云音乐 | **支持**。开放平台申请 `appId` / `privateKey`，`ncm-cli login` 完成用户授权；官方能力列出查看用户信息、歌单和推荐 | **支持**。歌曲、歌单、专辑搜索及歌单管理 | **支持，但有边界**。CLI 支持播放、暂停、上/下一首、音量、队列、状态；播放器后端为本地 `mpv`，或仅 macOS 可用的 `orpheus` 网易云 App | 个人开发者可入驻并申请 API Key；存在请求总量和曲目 `visible` / 版权限制。未找到公开的商业再封装定价与授权承诺 | 最值得先做官方 PoC；Linux 上本质仍是“网易目录 + Sonex/CLI 驱动 mpv”，不是发现并遥控网易云客户端 |
| 酷狗音乐 | **分产品支持**。腾讯云 TME SDK 可按 `deviceId` 跳转酷狗授权并取得用户 ID、昵称、头像、VIP 状态 | **支持**。mini 酷狗有搜索 API；TME 内容接口有歌曲、歌单和播放状态数据 | **支持嵌入/IoT 播放，不支持现有客户端远控**。mini 酷狗支持播放、暂停、多首连播；TME SDK 支持播放、暂停、上/下一首、进度、音量、音质和指定歌曲，但命令下发到接入的 IoT 设备 | 曲库组件按歌曲千次有效播放计费；IoT 路线还涉及腾讯云设备接入、实例计费、测试和审核 | 可作为商业 SDK / IoT provider 研究，不应当作 Linux 已安装酷狗客户端适配器 |
| QQ 音乐 | **部分支持**。腾讯连连 H5 SDK 支持 QQ 音乐授权状态、用户听歌数据、会员权益、个人歌单和最近播放；公开页未列完整通用 profile 接口 | **支持**。歌曲、专辑、MV 搜索，歌曲详情、歌词、推荐和播放链接 | **支持向自有 IoT 设备点播，不支持现有客户端远控**。可下发播放列表并指定 `PlaySongId`；未找到 QQ 音乐桌面/手机 App 的公共 play/pause/next/设备发现接口 | 需进入腾讯云 IoT Explorer / 腾讯连连产品与设备体系，涉及审核及设备接入计费；未找到 QQ 音乐内容能力单独的公开自助价格 | 适合正式 IoT/硬件合作，不适合作为 `/player` 的本地 QQ 音乐客户端选项 |

### 网易云音乐

网易官方仓库将 `ncm-cli` 定义为网易云音乐的 CLI 工具，并明确要求：

- 在网易云音乐开放平台入驻并申请 API Key（`appId` 和 `privateKey`）；
- 执行 `ncm-cli login` 完成登录授权；
- 使用搜索歌曲 / 歌单 / 专辑、歌单管理、每日推荐和查看用户信息等能力；
- 对播放使用播放、暂停、上一首、下一首、音量、队列和状态命令。

来源：

- [NetEase/skills 官方仓库：入驻、API Key、登录与能力概览](https://github.com/NetEase/skills)
- [网易官方 `netease-music-cli` skill：登录、搜索、播控、可播性与请求上限](https://raw.githubusercontent.com/NetEase/skills/master/netease-music-cli/SKILL.md)
- [网易官方 `ncm-cli-setup` skill：mpv 与 orpheus 后端边界](https://raw.githubusercontent.com/NetEase/skills/master/ncm-cli-setup/SKILL.md)
- [网易云音乐开放平台个人开发者入驻入口](https://developer.music.163.com/st/developer/apply/account?type=INDIVIDUAL)

这里有两个不能省略的限制：

1. 搜索结果同时有 API 用的加密 ID 和唤起客户端用的原始 ID，且 `visible=false` 的曲目不能播放；官方 skill 还要求遇到“请求总量超限”时停止后续请求。
2. `ncm-cli` 的官方配置只列出 `mpv` 和 `orpheus`。`orpheus` 是“调用本地网易云音乐客户端”，但只支持 macOS；Linux 端没有公开的网易云客户端远控等价能力。

因此可以把网易云作为 **provider adapter** 接入 Sonex，但不能把“官方 API 存在”写成“Linux 上可遥控网易云音乐客户端”。商业 Sonex 是否可以再封装其曲库和用户播放能力，也不能从个人开发者入驻页直接推出，需要向平台确认协议、配额、内容授权和收费。

#### 增量核查：官方 Skills、`ncm-cli` 与 MCP 的边界

**可以说网易有官方认可的 CLI 接入路径，但应避免把证据说得过头。**

网易官方 GitHub 组织 `NetEase/skills` 的 README 将项目命名为“网易云音乐 Agent Skills”，明确写明技能包“基于 `ncm-cli`”，安装命令为 `npm install -g @music163/ncm-cli`，并把它称为网易云音乐 CLI。官方 `ncm-cli-setup` skill 也将 `ncm-cli` 定义为支持音乐搜索、播放控制、歌单管理和 TUI 的网易云音乐命令行工具。因此，产品文档可以使用以下表述：

> `ncm-cli` 是网易官方 GitHub 明确认可并提供使用流程的网易云音乐 CLI 接入路径。

但 `NetEase/skills` **不是 `ncm-cli` 源码仓库**。截至本次核查，其固定提交只包含 README、三个 `SKILL.md`、许可证和一个 mpv 安装辅助脚本；没有 CLI 源码。npm 注册表显示 `@music163/ncm-cli` 最新标签为 `0.1.6`，提供 `ncm-cli` 可执行入口并要求 Node.js 18 以上，但包元数据没有 `repository` 或 `homepage`。维护者列表中包含 `grp.music-fe@corp.netease.com`，仍不足以单独完成 npm 发布账户的公司法务归属证明。因此不应写成“网易已公开维护 ncm-cli 源码”或“已验证 npm 包由网易公司企业账号直接发布”。

来源：

- [网易官方 `NetEase/skills` 仓库](https://github.com/NetEase/skills)
- [固定提交的 README：Skills → CLI 操作层 → setup 依赖关系](https://github.com/NetEase/skills/blob/58ff0771d6977feb847d6bfe322280eec4bec004/README.md)
- [固定提交的 `ncm-cli-setup` skill](https://github.com/NetEase/skills/blob/58ff0771d6977feb847d6bfe322280eec4bec004/ncm-cli-setup/SKILL.md)
- [固定提交的 `netease-music-cli` skill](https://github.com/NetEase/skills/blob/58ff0771d6977feb847d6bfe322280eec4bec004/netease-music-cli/SKILL.md)
- [`@music163/ncm-cli` npm 包页](https://www.npmjs.com/package/@music163/ncm-cli)
- [`@music163/ncm-cli` npm 注册表元数据](https://registry.npmjs.org/@music163%2Fncm-cli)
- [网易云音乐开放平台 CLI 使用指南](https://developer.music.163.com/st/developer/document?docId=c5cb8108c73b42c8bec8869b26a15738)

其公开连接与鉴权分为三层：

1. **开发者鉴权**：到网易云音乐开放平台申请 `appId` 和 `privateKey`，使用 `ncm-cli config set appId ...` 与 `ncm-cli config set privateKey ...` 配置。
2. **用户授权**：使用 `ncm-cli login --check` 检查登录状态；未登录时执行 `ncm-cli login --background` 完成用户授权。官方公开 skill 没有披露底层 token 交换、刷新机制或 HTTP API 端点，因此不能自行把它命名为标准 OAuth，也不能绕过 CLI 直接复刻协议。
3. **播放连接**：CLI 把实际音频交给本地 `mpv`，或在 macOS 上通过 `orpheus` 调用网易云音乐 App。公开材料没有提供 Spotify Connect 式设备发现、播放转移或多设备控制接口。

`NetEase/skills` 的角色是 **Agent 工作流和命令编排层**：

```text
netease-music-assistant skill
        ↓
netease-music-cli skill
        ↓ shell command
@music163/ncm-cli
        ↓
网易开放平台 / 登录授权 / mpv 或 macOS orpheus
```

Skills 会检查 CLI 是否安装、引导配置和登录，然后直接执行 `ncm-cli ...`。官方还要求运行时通过 `ncm-cli commands` 获取当前命令树、用 `ncm-cli <command> --help` 查询参数，不允许凭文档猜测参数；除播控外的命令需要携带概括用户意图的 `--userInput`，并遵循该 skill 的内容安全检查。这些都是 Sonex 若复用 CLI 时必须评估的运行契约，而不是普通静态 REST SDK。

**未发现网易官方音乐 MCP Server。** 对 `NetEase/skills` 固定提交的完整文件树核查没有发现 MCP server 源码、`mcp.json`、stdio / HTTP transport 或 MCP tool schema；官方说明的执行路径是 Skills 调用本地 CLI 和安装脚本。截至本次限定的一手来源检索，也没有在网易官方 GitHub / 开发者站找到网易云音乐 MCP Server。准确表述应是：

> 当前公开官方方案是 `Skills → ncm-cli`，不是 MCP；本次官方公开范围未发现网易云音乐 MCP Server。

这不能证明网易内部或未来绝对不存在 MCP。若 Sonex 需要 MCP 边界，需要自行实现一个受控的 MCP / tool adapter 包装 `ncm-cli`，不能宣称在接入网易官方 MCP。

作为 Sonex 集成边界，近期可行方案是把 `ncm-cli` 封装成独立 **provider subprocess adapter**，而不是外部播放器 adapter：

- 启动时探测 `ncm-cli --version`，并在每个受支持版本读取 `ncm-cli commands` / `--help`；
- 凭据与 Sonex 普通播放器配置分开保存，`privateKey` 不进入聊天、日志或前端；
- 登录只委托给 CLI 的 `login --check` / `login --background`，不复刻未公开的 token 协议；
- 搜索、用户资料、歌单和推荐由 CLI provider 负责；Linux 播放是 CLI / Sonex 驱动本地 `mpv`，不是控制独立网易云客户端；
- 在正式采用前验证 CLI 是否有稳定的结构化输出、退出码、超时和取消语义。官方 Skills 只展示命令流程，未承诺机器可读输出或长期兼容性；
- 另行确认商业再封装、用户数据、请求额度和内容授权，官方 GitHub 背书不等于商业许可。

### 酷狗音乐

酷狗提供两类正式能力：

1. **嵌入播放组件**：mini 酷狗支持 Android、iOS、H5 和微信小程序，提供搜索 API，支持播放、暂停、多首连播以及时长、封面和歌名。无界面曲库组件面向 Android / iOS，仅限在线播放，按有效播放次数计费。
2. **腾讯云 IoT 音乐服务**：TME SDK 可按 `deviceId` 完成酷狗授权、用户信息查询和完整播控；命令通过设备物模型下发并要求设备回报 `control_seq`。

来源：

- [酷狗官方 mini 播放器](https://open.kugou.com/docs/mini-player/)
- [酷狗官方无界面曲库开放组件及计费说明](https://open.kugou.com/docs/open-player/)
- [腾讯云 IoT Explorer：TME 音乐服务 SDK](https://cloud.tencent.com/document/product/1081/68800)
- [腾讯云 IoT Explorer：搜索数据结构](https://cloud.tencent.com/document/product/1081/40780)
- [腾讯云 IoT Explorer：用户信息接口](https://cloud.tencent.com/document/product/1081/60575)
- [腾讯云 IoT Explorer：歌曲播放 URL 接口](https://cloud.tencent.com/document/product/1081/60559)
- [腾讯云 IoT Explorer：计费概述](https://cloud.tencent.com/document/product/1081/51938)
- [腾讯连连设备接入和发布流程](https://cloud.tencent.com/document/product/1081/51807)

这些接口证明酷狗有官方第三方播放方案，但不能证明用户电脑里的酷狗客户端提供外部控制接口。Sonex 若采用它，承担的是播放器或 IoT 设备集成方角色，而不是一个通用桌面遥控器。

### QQ 音乐

腾讯连连自定义 H5 SDK 的音乐服务文档明确提供 QQ 音乐账号授权后的听歌数据和会员权益，并支持歌曲详情、歌词、个人歌单、最近播放、推荐、歌曲 / 专辑 / MV 搜索和播放链接。它还能向关联的 IoT 设备下发播放列表，并用 `PlaySongId` 指定开始歌曲。

来源：

- [腾讯云 IoT Explorer：腾讯连连 H5 SDK QQ 音乐服务](https://cloud.tencent.com/document/product/1081/67456)
- [腾讯云 IoT Explorer：设备接入说明](https://cloud.tencent.com/document/product/1081/103590)
- [腾讯云 IoT Explorer：计费概述](https://cloud.tencent.com/document/product/1081/51938)

这是“QQ 音乐账号权益 + 开发者自有设备”的正式方案。官方公开材料没有给出面向普通桌面程序的 QQ Music OAuth，也没有用于发现或控制用户现有 QQ 音乐客户端的跨设备远控 API。腾讯音乐官网还将 TME 音乐云定位为云端曲库、版权授权和定制服务，进一步说明商业产品应走合作方案而非逆向客户端协议：

- [腾讯音乐官网：TME 音乐云和商用音乐服务](https://www.tencentmusic.com/)

## Linux 独立播放器

### MPRIS 的能力边界

MPRIS 是 Linux Session D-Bus 上的媒体播放器远控标准。标准 `Player` 接口定义 `Play`、`Pause`、`PlayPause`、`Stop`、`Next`、`Previous`、进度、音量、状态和元数据；可选的 `OpenUri` 用于让播放器打开一个 URI。

关键点是：**实现基础 MPRIS 播控不等于实现 `OpenUri`**。即使实现了 `OpenUri`，客户端仍必须读取 `SupportedUriSchemes` 和 `SupportedMimeTypes`，并在调用后等待 `Metadata` 的 `mpris:trackid` 变化，不能把 D-Bus 方法返回当作已经成功开始播放。

来源：

- [MPRIS Player 接口规范](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html)
- [MPRIS 根接口规范](https://specifications.freedesktop.org/mpris/latest/Media_Player.html)

### 结论表

| 播放器 | Linux 发现方式 | 控制已运行播放器 | 注入 Sonex 本地 / 网络音频 | 结论 |
| --- | --- | --- | --- | --- |
| Clementine | 可执行文件 / desktop entry；运行后 D-Bus 名 `org.mpris.MediaPlayer2.clementine` | MPRIS 2；官方 CLI 也有 play/pause/stop/next/previous/seek/volume | **支持**。MPRIS `OpenUri`；声明支持 `file`、`http`、`cdda`、`smb`、`sftp`；CLI 可接收 URL 并 load/append | 可做完整 external-player adapter |
| Rhythmbox | `rhythmbox` / `rhythmbox-client`；运行后 MPRIS 服务 | 官方 MPRIS 插件；`rhythmbox-client` 支持 play/pause/next/previous/stop/seek | **支持**。MPRIS `OpenUri` 调用 `rb_shell_load_uri(..., TRUE)`；`rhythmbox-client --play-uri` 可导入并播放 URI | 可做完整 external-player adapter；应同时探测 MPRIS 插件是否启用 |
| Audacious | `audacious` / `audtool`；MPRIS 插件启用后有 `org.mpris.MediaPlayer2.audacious` | MPRIS 插件支持基本播控；`audtool` 和私有 D-Bus 能做更完整控制 | **MPRIS 不支持 `OpenUri`**。官方 `audacious <file/URI>`、`audtool playlist-addurl` / 临时播放列表和私有 D-Bus 可打开 URI | 可做完整 adapter，但注入路径必须用 CLI / 私有 D-Bus，不能统一走 MPRIS `OpenUri` |
| Mineradio (`XxHuberrr/Mineradio`) | 官方没有 Linux 发布物 | 未找到公开官方接口 | 未找到公开官方接口 | 不应出现在 Linux `/player` 可用列表 |
| Mini Radio Player (`miniradioplayer.net`) | 官方提供 Linux x86_64 `.deb` / `.rpm` / tar.gz | **未找到公开官方能力** | **未找到公开官方能力** | 安装存在不等于 Sonex 可控；在厂商提供接口或现场验证前排除 |

### Clementine

Clementine 官方源码注册 `org.mpris.MediaPlayer2.clementine`，实现 MPRIS 2 的基础播控、元数据、状态、`OpenUri` 和受支持 URI / MIME 声明。`OpenUri` 会把 URI 插入当前播放列表并设为播放。官方 CLI 同时提供 `--play`、`--pause`、`--play-pause`、`--stop`、`--previous`、`--next`、音量、seek、`--append` 和 `--load`。

来源（固定到本次核查提交）：

- [Clementine MPRIS 2 实现](https://github.com/clementine-player/Clementine/blob/6690b8a8647d4a69320e69d3218610873276631c/src/core/mpris2.cpp#L81-L95)
- [Clementine `SupportedUriSchemes` 与 MIME](https://github.com/clementine-player/Clementine/blob/6690b8a8647d4a69320e69d3218610873276631c/src/core/mpris2.cpp#L221-L240)
- [Clementine `OpenUri`](https://github.com/clementine-player/Clementine/blob/6690b8a8647d4a69320e69d3218610873276631c/src/core/mpris2.cpp#L422-L470)
- [Clementine CLI 选项](https://github.com/clementine-player/Clementine/blob/6690b8a8647d4a69320e69d3218610873276631c/src/core/commandlineoptions.cpp#L38-L73)

### Rhythmbox

Rhythmbox 的官方 MPRIS 插件实现基础播控与 `OpenUri`，后者直接调用 `rb_shell_load_uri(shell, uri, TRUE)`。官方 `rhythmbox-client` 还提供 `--check-running`、`--no-start`、基础播控、`--play-uri`、`--enqueue` 和状态输出。

来源（固定到本次核查提交）：

- [Rhythmbox MPRIS 插件：播控与 `OpenUri`](https://gitlab.gnome.org/GNOME/rhythmbox/-/blob/43659e0f8bf3eb01277fe0c4b084c02cf74b14c2/plugins/mpris/rb-mpris-plugin.c#L628-L700)
- [Rhythmbox MPRIS 的 URI / MIME 声明](https://gitlab.gnome.org/GNOME/rhythmbox/-/blob/43659e0f8bf3eb01277fe0c4b084c02cf74b14c2/plugins/mpris/rb-mpris-plugin.c#L276-L318)
- [Rhythmbox client 命令行选项](https://gitlab.gnome.org/GNOME/rhythmbox/-/blob/43659e0f8bf3eb01277fe0c4b084c02cf74b14c2/remote/dbus/rb-client.c#L93-L125)
- [Rhythmbox client 的 URI 导入与播放](https://gitlab.gnome.org/GNOME/rhythmbox/-/blob/43659e0f8bf3eb01277fe0c4b084c02cf74b14c2/remote/dbus/rb-client.c#L1281-L1364)
- [GNOME 官方插件目录：MPRIS 与 Web remote](https://wiki.gnome.org/Apps/Rhythmbox/Plugins)

Rhythmbox 对 `SupportedUriSchemes` 的源码注释写着“不准备认真支持此声明”，因此 Sonex 应以 `OpenUri` 调用后的实际元数据和播放状态确认结果，不能只信静态 scheme 列表。

### Audacious

Audacious 的官方 MPRIS 插件自述为“track information and basic playback control”，其接口 XML 没有 `OpenUri`。不过 Audacious 主程序接受文件 / URI 参数；如果已有实例，命令会通过官方私有 D-Bus 执行 open/add-list。`audtool` 也提供基础播控、播放列表跳转、`playlist-addurl`、`playlist-insurl` 和临时 “Now Playing” 播放列表。

来源（固定到本次核查提交）：

- [Audacious CLI 选项与已运行实例的 D-Bus 打开逻辑](https://github.com/audacious-media-player/audacious/blob/9d5ab90219cc678eed769788ccbf774eff3b62ca/src/audacious/main.cc#L50-L99)
- [Audacious 向现有实例打开文件 / URI](https://github.com/audacious-media-player/audacious/blob/9d5ab90219cc678eed769788ccbf774eff3b62ca/src/audacious/main.cc#L240-L283)
- [`audtool` 官方命令表](https://github.com/audacious-media-player/audacious/blob/9d5ab90219cc678eed769788ccbf774eff3b62ca/src/audtool/main.c#L32-L105)
- [Audacious MPRIS Player 接口 XML：没有 `OpenUri`](https://github.com/audacious-media-player/audacious-plugins/blob/f70d7ba42a3a5ee8981027bba6d25cc706dca871/src/mpris2/mpris2-player.xml)
- [Audacious MPRIS 插件说明和 D-Bus 注册](https://github.com/audacious-media-player/audacious-plugins/blob/f70d7ba42a3a5ee8981027bba6d25cc706dca871/src/mpris2/plugin.cc#L361-L476)
- [Audacious 私有 D-Bus 接口](https://github.com/audacious-media-player/audacious/blob/9d5ab90219cc678eed769788ccbf774eff3b62ca/src/dbus/aud-dbus.xml)

### Mineradio 与 Mini Radio Player

`Mineradio` 的准确项目身份是 `XxHuberrr/Mineradio`。官方仓库当前把它称为 Windows 桌面播放器，构建命令只有 `build:win`；官网虽然另列 macOS、Android 和 Web，但两处都没有 Linux。仓库还明确说明其网易云 / QQ 接入只用于个人学习、本地客户端体验和用户自有账号辅助，并非平台官方客户端。

来源：

- [Mineradio 官方仓库](https://github.com/XxHuberrr/Mineradio)
- [Mineradio 官方网站与发布平台](https://mineradio.cn/)

不要把它与 `miniradioplayer.net` 的 Mini Radio Player 混淆。后者确实提供 Linux x86_64 包，并列出 WebKitGTK、GTK、AppIndicator 和 GStreamer 依赖；但其官方帮助中心和下载页没有公开 MPRIS、D-Bus、CLI、remote control 或从外部打开 URI 的说明。

来源：

- [Mini Radio Player 官方 Linux 包页面](https://www.miniradioplayer.net/packages?lg=en-GB)
- [Mini Radio Player 官方帮助中心](https://www.miniradioplayer.net/support)

在没有官方接口或实际 D-Bus introspection 证据前，应记录为“已安装但不可控”，不能进入默认播放器选项。

## 对 Sonex `/player` 架构的直接含义

### 1. 把“安装检测”拆成三层

1. **installed**：已知适配器对应的可执行文件或 desktop entry 存在。
2. **running**：Session D-Bus 上存在 `org.mpris.MediaPlayer2.*` 或播放器私有服务。
3. **controllable / injectable**：运行时 introspection 显示有基础播控；普通模式默认播放器还必须有可验证的 URI 注入路径。

只扫描 `PATH` 会漏掉 Flatpak / desktop entry，也无法知道 MPRIS 插件是否启用；只扫描 MPRIS 又只能看到已运行程序，无法陈列可启动但尚未运行的播放器。两种探测必须合并。

### 2. 采用 capability-based adapter

建议每个选项至少返回：

```text
id
display_name
installed
running
launch_command
control_transport       # mpris | cli | private_dbus | managed_process
can_open_uri
supported_uri_schemes
can_queue
can_seek
can_report_status
provider                # local | netease | kugou_iot | qq_iot ...
```

普通 `/player` 默认项应要求：

- Sonex 能启动或连接该播放器；
- Sonex 有明确的 `open_uri` / CLI / 私有 D-Bus 注入路径；
- 注入后能根据元数据或状态确认真实播放；
- URI scheme 与 MIME 在播放器能力范围内。

只有 `PlayPause` 的任意 MPRIS 应用可以作为“当前媒体会话遥控目标”，但不能自动成为“默认播放器”。

### 3. 适配器优先级

建议首批实现顺序：

1. **MPRIS 2 通用控制层**：负责运行实例发现、状态、元数据、播放/暂停、切歌、seek、音量。
2. **Clementine adapter**：MPRIS `OpenUri`，CLI 作为启动和回退。
3. **Rhythmbox adapter**：MPRIS `OpenUri`，`rhythmbox-client --play-uri` 回退。
4. **Audacious adapter**：MPRIS 只负责状态 / 基础播控；URI 注入使用 `audacious <URI>` 或 `audtool` / 私有 D-Bus。
5. **网易云 provider PoC**：独立于普通 URI 播放器注册表，复用官方 `ncm-cli` 登录和搜索；Linux 播放先明确采用 `mpv`，不要伪装成网易云客户端远控。

酷狗和 QQ 音乐应作为需要正式产品 / IoT 凭据的 provider integration，不应通过 `/player` 本地应用检测进入列表。

### 4. 成功语义与安全

- MPRIS `OpenUri` 返回只表示调用被接受；成功应等待 `Metadata` track ID / URL 和 `PlaybackStatus` 变化，并设置超时。
- `http(s)` URI 可能过期、需要请求头或 Cookie，外部 GUI 播放器未必能复用 Sonex 的下载鉴权；此时应优先交给播放器可直接访问的公开 URL，或使用受控的本地临时文件 / 代理方案，并单独评估安全与生命周期。
- 不要向所有运行中的 MPRIS 客户端广播命令；选择后持久化精确 bus name / adapter ID，并处理播放器重启后 bus owner 变化。
- provider 账号凭据与本地播放器默认项必须分开存储。选择 Clementine 不应改变网易云 / QQ / 酷狗授权状态，provider 登录也不应覆盖普通模式默认播放器。

## 不确定项与下一步验证

1. **网易云商业条款**：个人开发者入驻、API Key 和官方 CLI 已确认；商业 Sonex 的再封装、收费、内容呈现和用户数据条款仍需平台书面确认。
2. **网易云 Linux 官方客户端控制**：当前官方材料只确认 macOS `orpheus`；未找到 Linux 客户端远控接口。
3. **酷狗 / QQ 桌面客户端**：未找到官方 MPRIS、CLI、D-Bus 或 Connect 类公共接口。若未来客户端发布此类接口，应重新核查，不应使用逆向协议填补空白。
4. **Flatpak / sandbox**：宿主 Sonex 是否能访问播放器的 Session D-Bus、文件 URI 和网络 URI，取决于安装方式与 portal 权限，需要分别做原生包和 Flatpak 现场测试。
5. **播放器版本差异**：上述源码对应 2026-07-28 前后的上游最新提交；发行版打包版本可能更旧，MPRIS 插件也可能默认关闭。实际选项必须以运行时 introspection 为准。
6. **Mini Radio Player**：官方未公开外部控制能力。可在用户确实安装后做一次只读现场核查（desktop file、进程、Session D-Bus names）；在取得正面证据前不列入 `/player`。
