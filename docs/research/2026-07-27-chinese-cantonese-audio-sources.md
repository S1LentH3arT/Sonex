# 华语 / 粤语音源渠道调研与 Sonex 接入建议

日期：2026-07-27

## 结论

**需要拓展音源渠道，但不能把目标定义成“再找一个能返回裸音频 URL 的公共曲库”。**

当前问题同时包含两个彼此独立的缺口：

1. **目录缺口**：Jamendo、Audius 的开放曲库无法稳定覆盖主流华语 / 粤语商业录音；SoundCloud 虽然能提供合规的公开音频流，但它的实际覆盖仍需样本测试，不能先验地当成主流商业曲库替代品。
2. **播放授权缺口**：Apple Music、KKBOX、QQ 音乐等更相关的目录并不把完整商业录音作为可任意交给 `mpv` 的 URL；完整播放通常被限定在官方 SDK、网页播放器、用户会员权益或企业授权场景内。

因此建议采用两条并行的 P1 路线：

- **补足用户自有完整播放层**：优先接入 Subsonic / Navidrome 音乐库，沿用 Sonex 的“搜索候选 → 置信度过滤 → URL 播放”模型。
- **完成 Apple Music 授权播放层**：仓库已经有 Apple Music API、用户 token 和 MusicKit bridge 客户端骨架；当前最值得投入的不是另起一个 Apple 适配器，而是补齐 storefront-aware 搜索和缺失的 bridge 服务，完成现有受控播放闭环。

SoundCloud 降为 P2 目录命中率试验；KKBOX 是华语 / 粤语目录方向的重要候选，但其公开 Open API 主要是元数据，播放接入资料陈旧且需要会员 / 用户授权，必须先向 KKBOX 确认当前第三方播放能力。腾讯音乐只应走正式商务或限定产品合作，不应逆向 QQ 音乐接口。

不建议把 TIDAL、网易云非官方 API 或 YouTube 音频提取当成新的可靠主链路。官方 YouTube 播放只能经嵌入式播放器，明确禁止分离音轨、下载和后台播放；它不能作为 `yt-dlp → mpv` 的合规等价替换。

## 研究边界

本报告严格区分四类能力：

| 能力 | 含义 |
| --- | --- |
| 元数据搜索 | 返回歌曲、艺人、专辑、地区可用性等，不代表可以播放 |
| 试听片段 | 通常约 30 秒，可用于确认候选，不是完整播放 |
| 授权播放器内完整播放 | 只能在官方 SDK / Embed / 指定终端内播放，通常依赖订阅 |
| 可交给 Sonex / `mpv` 的音频 URL | 返回可由通用音频播放器消费的媒体流；仍须遵守来源授权与用户权限 |

所有“华语 / 粤语覆盖较好”的判断均标注为**推断**；除 Apple 对本次四首失败歌曲的现场检索外，没有把厂商营销口径当成命中率数据。

## 渠道对比

| 渠道 | 华语 / 粤语相关性 | 搜索 | 完整播放边界 | 可直接给 `mpv` | 鉴权 / 地域 / 订阅 | Sonex 适配结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Apple Music / MusicKit | 高；本次四首样本均可在 HK / TW / CN 检出 | Apple Music API 目录搜索 | MusicKit 官方播放器内播放，需检查用户订阅能力 | **否（推断）**；官方资料只给 API 元数据和 MusicKit 播放器，没有通用媒体 URL 接口 | Developer Token；用户库需要 Music User Token；完整目录播放依赖可播放订阅 | **优先完成仓库已有 Apple Music 受控播放闭环** |
| iTunes Search API | 高；本次四首样本在 HK / TW / CN 均返回精确记录 | 公共商店搜索 | `previewUrl` 仅可用于合规的商店内容推广 | **技术上仅为 preview URL；条款只许推广，不能作娱乐音源** | 无用户登录；按 country 返回；Promo Content 有展示、归因和用途限制 | 仅作研发期目录覆盖代理；产品播放不用 |
| KKBOX Open API | 高（推断）；官方 API 覆盖台湾、香港等服务地区 | 曲目 / 专辑 / 艺人 / 歌单元数据搜索 | client credentials 不能播放；官方文档称播放需要 Premium | **公开资料未证明可用** | Client ID + Secret；播放需用户会员 / 授权；地区化目录 | **商务 / 技术确认后再做 KKBOX Mode** |
| 腾讯音乐 / QQ 音乐 | 很高（推断） | 腾讯连连 IoT H5 SDK 支持搜索；AME 提供企业曲库接口 | 用户 QQ 音乐权益或 AME 场景授权内播放 | IoT SDK 会返回播放链接；AME 使用专用加密 / 译码，不是通用公共 API | 绑定腾讯连连设备、QQ 音乐登录 / 会员，或企业备案、按量付费与场景授权 | **只走正式产品 / 商务合作，不做通用抓取适配器** |
| 网易云音乐 | 高（产品定位推断） | 未发现面向第三方的官方公共目录 / 播放 API | 未发现官方第三方完整播放方案 | 否 | 网络上的常见接口为社区逆向方案，不属于官方开发者产品 | **排除非官方 API；若有合作需求直接联系厂商** |
| SoundCloud | 未知；更偏创作者上传内容，需实测 | 官方 API 支持搜索并可筛 `access=playable` | public playable track 可完整播放；也可能是 preview / blocked / 地域限制 | **是**；官方 stream / streams 端点返回转码流 | 注册应用；Client ID + Secret 换 OAuth token；公开资源可用 client credentials | **最适合加入现有在线 URL 链路的公共候选** |
| TIDAL | 中低（未发现华语区域优势证据） | 官方 API 可查目录元数据 | 只能通过官方 Player SDK / Embed；非订阅用户或 Embed 外最多试听 | 否 | OAuth 2.1；完整 Embed 播放需订阅 | **不接入**；条款还禁止把 TIDAL Content 用于 AI 服务 / 工具 |
| YouTube Data API + IFrame Player | 高（现有命中经验）；但内容类型混杂 | 官方 `search.list` | 只能在 YouTube 嵌入式播放器中播放 | 否 | API key / quota；Embed 需要可见播放器、Referer 与标准播放体验 | 可做浏览器播放面板，不可替换 CLI 后台音频 |
| Subsonic / Navidrome | 由用户曲库决定；对收藏华语 / 粤语的用户可最高 | `search3` | 用户自有服务器直接流式播放 / 转码 | **是** | 服务器账号；建议 HTTPS；无第三方目录订阅 | **近期最高优先级的可靠完整播放扩展** |
| Jellyfin | 由用户曲库决定 | Jellyfin 库检索 | 用户自有服务器 direct play / transcode | **是** | Jellyfin 用户 / token；自托管网络 | 第二阶段个人媒体服务器适配 |

## 逐项依据

### 1. Apple Music / MusicKit

Apple Music API 能搜索 storefront 目录，并通过 Developer Token 调用；用户私有库则需要 Music User Token。MusicKit 在 Apple 平台、Android 和网页端提供目录检索及播放能力，应用应先检查用户订阅是否允许播放目录内容：

- [Apple Music API 概览](https://developer.apple.com/documentation/applemusicapi)
- [请求结构与 catalog / me 边界](https://developer.apple.com/documentation/applemusicapi/handling-requests-and-responses)
- [MusicKit 用户鉴权](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit)
- [MusicKit 播放与订阅能力](https://developer.apple.com/documentation/musickit)
- [MusicSubscription.canPlayCatalogContent](https://developer.apple.com/documentation/musickit/musicsubscription)
- [网页版 MusicKit 可使用网页组件或 JavaScript 播放器流播放](https://developer.apple.com/cn/musickit/)

Apple 的官方接口把“目录信息”和“MusicKit 播放器”分开提供。**没有发现官方 Apple Music API 返回可交给通用播放器的完整歌曲 URL；因此“不能直接给 `mpv`”是基于官方接口表面的架构推断，不是对隐藏实现的断言。**

#### 本次失败样本

2026-07-27 使用官方 iTunes Search API，分别以 `country=HK`、`country=TW`、`country=CN` 和 `media=music&entity=song` 复核：

- `愛不來 (feat. MISS KO)` / 方大同 / `危險世界`
- `特別的人` / 方大同 / `危險世界`
- `三人遊` / 方大同 / `橙月`
- `愛愛愛` / 方大同 / `愛愛愛`

三地均能找到四首准确标题并返回 `previewUrl`。这个现场结果只把 iTunes Search 当作 Apple 分区目录覆盖的代理，**不表示 `previewUrl` 可用于 Sonex 娱乐播放**。Apple Music 香港 / 台湾官方目录页也能看到对应专辑或歌曲，例如：

- [方大同 Apple Music 香港艺人页](https://music.apple.com/hk/artist/%E6%96%B9%E5%A4%A7%E5%90%8C/201549024)
- [《危險世界》香港目录](https://music.apple.com/hk/album/%E5%8D%B1%E9%9A%AA%E4%B8%96%E7%95%8C/1579903639)
- [《特別的人》香港目录](https://music.apple.com/hk/song/1579903651)
- [《三人遊》香港目录](https://music.apple.com/hk/song/313404860)
- [《愛愛愛》香港目录](https://music.apple.com/hk/album/%E6%84%9B%E6%84%9B%E6%84%9B/220365864)

这只能证明**本次四首样本**的目录覆盖，不能外推为所有华语 / 粤语歌曲的覆盖率；但它足以说明当前失败并非“主流服务也没有这些歌曲”，而是 Sonex 缺少可授权播放这些目录的渠道。

#### Sonex 当前代码事实

仓库当前已经不是从零开始：

- [`src/tools/apple_music.py`](../../src/tools/apple_music.py) 已实现 Apple Music API 搜索、developer / user token 头、订阅能力检查和播放控制客户端。
- `apple_music_play()` 在确认 `canPlayCatalogContent` 后，把 Apple Music URI 和 track 交给 `APPLE_MUSIC_BRIDGE_URL` 的 `/play`；pause / resume / next / previous 也都走同一 bridge。
- 当前仓库搜索只找到 bridge **客户端调用和测试**，没有找到响应 `/play`、`/current` 等端点的 bridge 服务实现。因此现状是“有受控播放协议骨架，没有可运行的 MusicKit 播放执行端”。这是本次源码快照的结论；若 bridge 由仓库外私有组件提供，需要部署方另行确认。

还有一个直接影响华语覆盖的缺陷：

- `APPLE_MUSIC_DEFAULT_STOREFRONT = "us"`；
- `apple_music_search()` 会把传入 storefront 原样用于 `/catalog/{storefront}/search`；
- `apple_music_account()` 虽调用 `/me/storefront`，但只提取 `subscription`，没有把返回的用户 storefront ID 反馈给默认搜索；
- `apple_music_play()` 未指定 storefront 时仍以 `us` 搜索。

因此优先工作应是完成现有 Apple Music 受控播放闭环：

1. 保留 provider-native 边界，不把 Apple Music 候选塞入 `online_play` 或 `mpv`。
2. 实现并部署本地 MusicKit bridge，完成 `/play`、`/current`、`/pause`、`/resume`、`/next`、`/previous`。
3. 搜索优先使用 `/me/storefront` 返回的用户 storefront；未登录时允许显式配置，并将 HK / TW / CN 作为可观测的区域回退，而不是硬编码 US。
4. 对简体、繁体、英文艺名和 `feat.` 形式生成受限的查询变体，但仍以标题 / 艺人 / 专辑严格匹配。
5. 用户明确授权 MusicKit，并检查 `canPlayCatalogContent` 后才允许 bridge 播放。

HK / TW / CN 回退顺序需要按目标用户地域和 Apple 实际可用性配置；“三个 storefront 都查一遍”不应成为无界默认行为，否则会增加延迟并混入地区不可播版本。

### 2. iTunes Search API

iTunes Search API 的 `previewUrl` 官方定义是 30 秒预览文件，但 Apple 同时把它定义为 Promo Content：只能用于推广对应商店内容，需要邻近商店 badge / 直达链接和 Apple 归因，只能流式传输，不能缓存，也不能脱离推广目的提供独立娱乐价值：

- [iTunes Search API Overview 与 Promo Content 使用条件](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/)
- [iTunes Search API 返回字段说明](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/UnderstandingSearchResults.html)

因此本报告只用它做**研发期目录覆盖验证**。Sonex 不应把 `previewUrl` 放入 `online_play`，不能给中置信度候选当试听器，更不能标记成“播放成功”。如果未来要在带 Apple 商店跳转的推广页面中使用，必须单独按上述展示与归因条件设计。

### 3. KKBOX

KKBOX 的官方 SDK 将 Open API 定义为曲目、专辑、艺人、歌单和电台的**元数据**访问；client credentials 使用 Client ID / Client Secret 换取 access token。官方 Python SDK 明确说明 client credentials 不能进行媒体播放，播放需要 Premium：

- [KKBOX JavaScript SDK：client credentials 与元数据搜索示例](https://kkbox.github.io/OpenAPI-JavaScript/)
- [KKBOX Python SDK：OAuth、搜索与媒体播放限制](https://kkbox.github.io/OpenAPI-Python/kkbox_developer_sdk.html)
- [KKBOX 官方 GitHub 组织与 Open API SDK](https://github.com/KKBOX)

SDK 列出的服务 territory 包含台湾、香港、新加坡、马来西亚和日本；台湾 / 香港区域加上官方搜索示例中的华语曲目，使 KKBOX 成为华语 / 粤语方向的重要候选。**“覆盖可能较好”仍是区域与产品定位推断，实施前必须用 Sonex 的真实失败样本跑目录命中率。**

KKCompany 的 [2023 Annual Report（PDF，第 97–98 页）](https://ir.kkcompany.com/files/uploads/%E5%85%AC%E9%96%8B%E8%AA%AA%E6%98%8E%E6%9B%B8/2023%20Annual%20Report%2020240607_Final.pdf) 进一步把 KKBOX 描述为台湾、香港的领先串流服务，并称其具有“最完整的华语音乐产品”和大量内容方授权。它为“KKBOX 值得做华语 / 粤语样本验证”提供了一手厂商依据，但仍是招股 / 年报中的公司自述，不是独立市场审计，也不是 Sonex 搜索命中数据。

风险是公开 SDK 多年未活跃，且目前公开资料没有清晰展示第三方在 Web / Linux CLI 中取得完整播放能力的现代流程。建议先向 KKBOX 确认：

1. 新应用是否仍可注册 Open API；
2. 是否开放用户 OAuth 和完整播放 SDK；
3. Linux / Web / 桌面端支持面；
4. Premium、territory、品牌展示与商业使用要求；
5. 播放是否只能发生在官方 SDK 内。

确认前可做元数据 PoC，不应假设 track object 中存在完整音频 URL。

### 4. 腾讯音乐 / QQ 音乐

腾讯目前可查到的官方能力是**场景化产品**，不是供任意桌面应用调用的通用 QQ 音乐公共 API。

腾讯连连物联网平台的 QQ 音乐 H5 SDK 支持歌曲搜索、歌曲信息和播放链接；除免登录区外需要跳转 QQ 音乐授权，授权后使用用户账号的听歌数据和会员权益。它还明确区分完整质量链接、30 秒试听链接及不可播放状态：

- [腾讯连连物联网开发平台 QQ 音乐 H5 SDK](https://cloud.tencent.com/document/product/1081/67456)
- [腾讯连连音乐服务客户端 API 目录](https://cloud.tencent.com/document/product/1081/60545)

这说明腾讯具备第三方授权播放技术，但该能力绑定物联网产品、H5 面板、设备与 QQ 音乐用户权益，不能据此推定普通 CLI 应用可以直接注册调用。

腾讯云正版曲库直通车 / AME 面向语聊房、线上 KTV、直播互动和内容素材等企业场景，提供 API / SDK、应用备案、按有效播放量计费和专用加密译码：

- [腾讯云正版内容直通车方案](https://cloud.tencent.com/solution/authorized-content)
- [正版曲库直通车产品说明](https://cloud.tencent.com/developer/techpedia/1138)

AME 的千万级、多版权方、跨语种曲库描述使它在目录上值得商务评估，但：

- 这是厂商产品口径，不是 Sonex 实测命中率；
- 授权场景和计费可能不包含“个人 AI 音乐播放器”；
- 专用加密 / 译码意味着它不能自然落入当前 `mpv` URL 链路。

建议仅在 Sonex 准备商业化且能承担内容授权成本时发起正式咨询。不得调用 QQ 音乐网页 / App 内部接口或复用用户 Cookie。

### 5. 网易云音乐

在网易云音乐官方域名与公开开发者入口中，本次没有找到面向第三方应用的公开音乐目录搜索及完整播放 API；搜索结果主要指向音乐人上传入口。网络上常见的 “NeteaseCloudMusicApi”、`weapi` / `eapi` 包装和歌曲 URL 解析服务均是社区逆向或第三方代理，不能作为可靠、授权的生产音源。

这里的结论严格限定为：

> 截至 2026-07-27，本次官方来源检索未发现可自助接入的第三方完整播放产品。

它不等于网易从未向硬件、车载或企业伙伴提供接口。若网易目录对产品重要，应直接询问正式合作，而不是把非官方 API 加入 fallback。

### 6. SoundCloud

SoundCloud 当前官方 API 对 Sonex 的技术适配度最高：

- public search 可用 client credentials token；
- `/tracks` 支持关键词搜索和 `access=playable` 过滤；
- public playable track 可以通过 stream / streams 端点取得转码流；
- private、paywalled、geo-blocked 曲目可能只提供 preview 或 metadata；
- stream 请求当前限额为每个 client ID 每 24 小时 15,000 次；超额返回 `429`；
- 注册应用目前要求 SoundCloud Artist Pro，获得 Client ID / Client Secret，再通过 OAuth 2.1 获取 token。

官方依据：

- [SoundCloud API Guide：鉴权、搜索、access 与 streaming](https://developers.soundcloud.com/docs/api/)
- [SoundCloud OpenAPI：search、preview 与 streams 端点](https://developers.soundcloud.com/docs/api/explorer/)
- [SoundCloud API rate limits](https://developers.soundcloud.com/docs/api/rate-limits)
- [SoundCloud API key 注册](https://developers.soundcloud.com/docs/api/register-app.html)

它可以实现为现有 provider：

1. client credentials token 集中缓存和刷新，不能每次搜索都换 token；
2. 搜索时直接要求 `access=playable`；
3. 仍执行 Sonex 的严格 title / artist / duration / remix-live 噪声过滤；
4. stream URL 只在最终播放时获取；
5. 对 `preview` / `blocked` / geo restriction 返回明确状态；
6. 按 `429` reset 信息做 provider cooldown。

但“SoundCloud 会显著补足主流华语 / 粤语”目前没有一手数据支持。建议用至少 100 首分层样本（内地、港台、粤语经典、新歌、独立音乐）做命中率 / 正确率试验，再决定是否进入高优先级自动 fallback。

### 7. TIDAL

TIDAL API 可以通过 OAuth 2.1 client credentials 查询非用户目录资源；但第三方播放只能使用官方、未修改的 Player module。官方资料还限定：

- SDK quick start 展示的是试听播放；
- Embed 内只有订阅用户可听完整歌曲；
- 非订阅用户或 Embed 外最多是 30 秒；
- 不得从官方 SDK 以外取得播放内容；
- Developer Terms / Guidelines 禁止把 TIDAL Content 用于 AI 服务或工具。

来源：

- [TIDAL API / SDK 概览](https://developer.tidal.com/documentation/api-sdk/api-sdk-overview)
- [TIDAL OAuth 2.1 鉴权](https://developer.tidal.com/documentation/api-sdk/api-sdk-authorization)
- [TIDAL quick start](https://developer.tidal.com/documentation/api-sdk/api-sdk-quick-start)
- [TIDAL Developer Terms](https://developer.tidal.com/documentation/guidelines/guidelines-developer-terms)
- [TIDAL Design Guidelines](https://developer.tidal.com/documentation/guidelines/guidelines-design-guidelines)

Sonex 是 AI agent，TIDAL 条款边界与当前产品形态直接冲突；同时它也不能提供通用音频 URL。结论是排除，而不是投入适配。

### 8. YouTube 官方 API

YouTube 提供一条合规、稳定但产品形态不同的路线：

- Data API `search.list` 搜索视频；
- IFrame Player API 在网页中播放并控制队列、暂停、音量；
- 当前默认搜索 quota 是每日 100 次 `search.list`，需要申请扩容；
- Embed 要有至少 200×200 的播放器视口，并传递可识别来源的 `HTTP Referer`。

来源：

- [YouTube Data API search.list](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube Data API quota 概览](https://developers.google.com/youtube/v3/getting-started)
- [YouTube IFrame Player API](https://developers.google.com/youtube/iframe_api_reference)
- [Embed 最低功能与 client identity](https://developers.google.com/youtube/terms/required-minimum-functionality)

但 YouTube Developer Policies 明确不允许：

- 下载或缓存视听内容；
- 分离 / 提取视频中的音频；
- 在播放器窗口关闭或最小化时做后台播放；
- 修改或遮蔽标准播放器体验。

来源：

- [YouTube Developer Policies](https://developers.google.com/youtube/terms/developer-policies)
- [YouTube policy compliance guide](https://developers.google.com/youtube/terms/developer-policies-guide)

所以官方 YouTube 可用于**用户可见的网页播放面板**，不能为 `yt-dlp` 提供合规的“只换 API 不换架构”修复。若 Sonex 仍保留 `yt-dlp`，它只能被视为易受 bot challenge 影响的非授权提取 fallback，必须有 cooldown、有限重试和明确降级，不能继续承担主流曲库 SLA。

### 9. 用户自有 Subsonic / Navidrome / Jellyfin

Subsonic API 提供：

- `search3` 按 ID3 元数据搜索 artist / album / song；
- `stream` 返回二进制媒体并支持码率与格式转码；
- `download` 返回原始媒体；
- token + salt 鉴权，避免把明文密码直接发送。

Navidrome 与 Subsonic API v1.16.1 兼容，并实现 `search3`、`stream`、`download` 等音乐端点：

- [Subsonic API：鉴权、search3、stream 与 download](https://www.subsonic.org/pages/api.jsp)
- [Navidrome Subsonic API compatibility](https://www.navidrome.org/docs/developers/subsonic-api/)
- [Navidrome 产品定位：个人音乐库与 Subsonic-compatible server](https://www.navidrome.org/docs/overview/)

这条路线没有公共商业目录，覆盖完全取决于用户合法拥有的文件；但它正好解决“用户有华语 / 粤语收藏、Sonex 却无法稳定播放”的问题，而且可以直接复用 `mpv`：

1. 用户配置 server URL、username 和单独的 app password / token；
2. Sonex 调 `search3` 获取结构化 artist / album / title / duration；
3. 继续执行现有高置信度匹配；
4. 把带短期鉴权参数的 `stream` URL 交给播放器，或通过 Sonex 代理避免凭据出现在日志 / 进程列表；
5. 只允许 HTTPS，或明确限制为可信局域网。

Jellyfin 同样是用户个人媒体服务器，支持 HTTP(S) 流式播放，并在客户端不兼容时转码：

- [Jellyfin Quick Start：个人媒体库](https://jellyfin.org/docs/general/quick-start/)
- [Jellyfin networking：HTTP(S) streaming 与自托管边界](https://jellyfin.org/docs/general/post-install/networking/)
- [Jellyfin codec support：direct play / transcode](https://jellyfin.org/docs/general/clients/codec-support/)

Sonex 应先做 Subsonic 协议，因为一个适配器即可覆盖 Navidrome 及多个兼容服务器；Jellyfin 可作为第二个个人媒体后端。

## 推荐的目标架构

不要把所有来源压平成同一种 “audio URL provider”。建议明确三层：

```text
用户播放意图
  ├─ 用户拥有的音频
  │    ├─ 本地文件（现有 local-first）
  │    └─ Subsonic / Navidrome / Jellyfin
  ├─ 授权订阅服务
  │    ├─ Spotify Mode（现有）
  │    ├─ Apple Music Mode（建议验证）
  │    ├─ KKBOX Mode（待厂商确认）
  │    └─ TME enterprise / IoT（仅正式合作）
  └─ 公共在线音频
       ├─ SoundCloud（建议实测后接入）
       ├─ Audius / Jamendo（现有开放曲库）
       └─ yt-dlp（最后 fallback，熔断且不承诺可靠）
```

其中：

- “授权订阅服务”返回 provider track ID，由 provider-native player 执行；
- “公共在线音频”才返回可交给通用播放器的 URL；
- Apple Music API、KKBOX Open API 可以参与各自授权范围内的元数据消歧，但元数据来源不得伪装成音频来源；iTunes Search 仅保留为研发期覆盖探针，除非产品另行满足 Apple 的推广使用条件；
- 只有 high confidence 才能自动播放；provider-native 播放同样不能绕过确认和来源展示。

## 实施优先级

### P0：先量化，而不是继续猜目录

建立固定的华语 / 粤语基准集，至少 100 首，包含：

- 内地 / 台湾 / 香港；
- 国语 / 粤语；
- 经典与近两年新歌；
- 主流厂牌与独立音乐；
- 简繁体、英文艺名、feat.、现场 / 翻唱等歧义。

对每个 provider 记录：

- search 命中率；
- high-confidence 精确率；
- 完整可播放率；
- 首字节延迟；
- 地域 / 会员 / blocked 比例；
- 7 天重复请求稳定性。

### P1：Apple Music 受控播放闭环

现有仓库已经具备 API、用户 token、订阅检查和 bridge 客户端骨架，而且本次四首样本在 HK / TW / CN 都是 4/4 目录命中。先让搜索使用用户 storefront、补简繁体查询，再实现 bridge E2E；这是修复主流华语商业目录播放缺口的最短授权路径。

实现时同时验证 MusicKit Web 是否可嵌入 Sonex 的实际 CLI / TUI 交互：

- 登录与授权回调；
- 订阅能力检查；
- 后台 / 前台播放约束；
- 队列与播放状态回传；
- Linux 桌面浏览器或伴随 WebView 的可用性。

如果必须弹出网页播放器，应把它作为明确的 provider mode 产品决策，而不是伪装成 `mpv` 播放。

### P1：Subsonic / Navidrome

最小实现只有配置、`search3`、`stream` 和凭据脱敏，且不依赖第三方商业目录授权。它不会帮助没有自有曲库的用户，但能提供最确定的完整播放 SLA。

### P2：SoundCloud 小规模 PoC

先取得正式 API key，用基准集测量后再决定 fallback 顺序。若主流华语命中率低，仍可作为独立音乐 / 用户上传内容补充源，但不应提高到 Apple / KKBOX 的目录预期。

### P2：联系 KKBOX

在写播放代码前取得当前官方答复。公开 Open API 足以做目录 PoC，但不能据旧 SDK 推断完整播放现在仍向新第三方应用开放。

### P3：TME 商务评估

只有当 Sonex 有明确商业主体、用户地域、授权场景和播放量模型时，才评估腾讯连连 / AME / 其他 TME 合作。否则接入成本、加密播放器和版权范围都无法进入工程排期。

## 最终判断

**需要扩展，而且应该把“华语 / 粤语播放能力”列为独立产品能力，而不是继续依赖开放曲库和 YouTube 提取的偶然覆盖。**

但扩展的正确顺序是：

1. 同列 P1：完成已有 Apple Music storefront-aware + bridge E2E，并接入 Subsonic / Navidrome；
2. SoundCloud 正式 API 做 P2 命中率 PoC；
3. KKBOX / TME 走当前官方确认或商业合作；
4. iTunes Search 只作研发期覆盖验证，不作为试听或娱乐播放；
5. 网易非官方 API、TIDAL 和 YouTube 音频提取不进入“可靠音源”清单。

这会把当前单一的“URL 能不能下载”问题改造成清晰的能力边界：**谁拥有音频、谁授权播放、在哪里播放、Sonex 能否控制播放器**。只有这样，华语 / 粤语覆盖提升才不会用新的风控、版权或稳定性问题替换旧问题。
