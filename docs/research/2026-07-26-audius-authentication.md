# Audius 鉴权与 Sonex 读取链路配置

日期：2026-07-26

## 结论

Sonex 当前只做公开曲目的 `tracks/search` 与普通公开 track stream，因此：

- 不需要 API Secret。
- 不需要开发者门户签发的 API Bearer Token。
- 不需要用户 OAuth access token。
- API Key 本身也不是公开读取的硬性前提；它是应用标识，并可获得 API plan 对应的速率额度。既然 Sonex 已提供 API Key 配置，应继续使用，但必须按 API Key 语义传递，不能把它冒充 Bearer Token。

最小配置仍可只有：

```text
SONEX_AUDIUS_API_KEY
```

不应为了修复当前公开读取链路新增 `AUDIUS_API_SECRET`。`AUDIUS_BEARER_TOKEN` 也不是修复该链路的必要条件；将来若 Sonex 要做后端写操作，再将它作为独立的服务端 secret 建模。

## 官方依据

### 公开读取

Audius 当前 [API Reference](https://docs.audius.co/api/) 和[官方 OpenAPI](https://api.audius.co/v1/swagger.yaml) 的鉴权概览说明：

- 大多数只读端点不带凭据也可工作。
- API Key 用于更高的速率额度。
- 当前生产 server 是 `https://api.audius.co/v1`。

OpenAPI 对两个 Sonex 端点的声明更具体：

- `GET /tracks/search` 没有 `security` 要求。
- `GET /tracks/{track_id}/stream` 的 security alternatives 包含空对象 `{}`，即允许匿名调用；OAuth `read` 是另一个可选分支。
- stream 的 `api_key` 是可选 query parameter。只有曲目配置为仅允许特定 API keys 时，它才是必需的。
- gated stream 可能另外要求 `user_signature`、`user_data` 或其他访问证明；Sonex 当前会排除 gated tracks，不属于普通公开流。

官方 SDK 的配置类型也把 API Key-only 模式描述为“read-only access with higher rate limits”，并允许仅用 `appName` 做只读访问：

- [SDK config schemas](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/types.ts#L131-L260)
- [Tracks search implementation](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/api/generated/default/apis/TracksApi.ts#L2557-L2633)
- [Tracks stream implementation](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/api/generated/default/apis/TracksApi.ts#L2693-L2766)

### API Key 的传递方式

官方 SDK 的 app-info middleware 把 API Key 作为 query parameter `api_key` 追加到 API 请求，同时附加 `app_name`：

- [addAppInfoMiddleware](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/middleware/addAppInfoMiddleware.ts#L15-L74)

因此，Sonex 当前配置的 API Key 不应这样发送：

```http
Authorization: Bearer <API_KEY>
```

如果选择 API Key-only 读取，使用：

```http
GET https://api.audius.co/v1/tracks/search?...&api_key=<API_KEY>&app_name=Sonex
```

公开 stream 可同样附带 `api_key`；它在官方 OpenAPI 中是显式的可选参数：

```http
GET https://api.audius.co/v1/tracks/<TRACK_ID>/stream?api_key=<API_KEY>&app_name=Sonex
```

### API Bearer Token

Audius 开发者门户当前会签发 API Key 与 API Bearer Token。官方 SDK 文档规定：

- API Key 可用于前端和后端。
- API Bearer Token 只能放在后端。
- 直接 REST 示例将真正的 API Bearer Token 放在 `Authorization: Bearer ...` 中。

来源：

- [Audius SDK Getting Started](https://docs.audius.co/sdk/)
- [官方 SDK README](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/README.md#L25-L32)
- [直接 REST Bearer 示例](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/README.md#L189-L207)

这个 Bearer Token 是独立凭据，不是给 API Key 添加 `Bearer` 前缀。它主要在后端需要以应用身份进行受保护操作时使用；公开 search/stream 不以它为前提。

### 用户 OAuth token

用户 OAuth access token 是另一类 Bearer Token，用于读取用户相关数据或代表用户执行操作：

- Audius 使用 OAuth 2.0 Authorization Code Flow with PKCE。
- OAuth PKCE 不需要 client secret。
- `read` scope 用于用户读取场景。
- `write` scope 用于 upload、favorite 等代表用户的 mutation；申请 `write` scope 时需要 API Key。
- token exchange 后的 access token 通过 `Authorization: Bearer <ACCESS_TOKEN>` 发送。

来源：

- [Log In with Audius](https://docs.audius.co/developers/guides/log-in-with-audius/)
- [OAuth SDK source](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/oauth/OAuth.ts#L95-L164)

Sonex 当前不登录 Audius 用户，也不读取用户私有数据或执行用户行为，因此不需要这类 token。

### API Secret

官方资料目前并存两套写操作表述：

- API Reference 概览仍写着 mutations 需要 API Key 与 secret。
- 当前 SDK/开发者门户入门文档主要使用 API Key 与 API Bearer Token。
- 官方 SDK 源码仍保留 `apiSecret` 模式，明确用于 Entity Manager writes，并使用 API Secret 生成请求签名；它还支持 Bearer Token 模式执行 API writes。

来源：

- [API Reference](https://docs.audius.co/api/)
- [SDK config schemas](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/types.ts#L162-L224)
- [request-signature middleware](https://github.com/AudiusProject/apps/blob/90b3c1fae2167a220ff8c009e18258133e0e8445/packages/sdk/src/sdk/middleware/addRequestSignatureMiddleware.ts#L15-L100)

这说明 API Secret 是特定写入架构的服务端签名材料，不是公开搜索或播放的补充字段。若未来需要写操作，应先选择 OAuth user writes、API Bearer writes 或 Entity Manager signed writes 中的一条明确路径，再按该路径增加 secret；不应提前把三类凭据混入同一个字段。

## 凭据边界

| 场景 | API Key | API Bearer Token | OAuth access token | API Secret |
| --- | --- | --- | --- | --- |
| 公开 track search | 可选，建议用于应用标识/额度 | 不需要 | 不需要 | 不需要 |
| 普通公开 track stream | 可选；allowlist track 例外 | 不需要 | 不需要 | 不需要 |
| 用户资料或用户私有读取 | OAuth client 标识可能需要 | 不等同于用户 token | 需要 `read` scope | 不需要 |
| 代表用户 favorite/upload 等 | `write` scope 需要 | 后端 API write 路径可用 | 前端/用户授权路径需要 `write` scope | OAuth PKCE 不需要 |
| Entity Manager 签名写入 | 使用 | 可作为另一后端路径 | 取决于业务授权 | 需要，且仅服务端保存 |

## 对 Sonex 的直接建议

1. 把 base URL 从旧的 discovery-provider 域名迁移到 `https://api.audius.co/v1`。
2. 给 HTTP 客户端设置稳定、非空的 `User-Agent`。
3. 继续保留单一 `audius_api_key` 配置，并通过 `api_key` query parameter 发送。
4. 删除“把 API Key 放入 Authorization Bearer header”的行为。
5. 暂不新增 API Secret 或 Bearer Token 配置；它们不能解决当前公开目录读取问题。
6. 若未来新增 `AUDIUS_BEARER_TOKEN`，必须与 `AUDIUS_API_KEY` 分开存储，只在服务端通过 `Authorization: Bearer <TOKEN>` 传递。

## 无凭据现场验证

在 2026-07-26，使用固定 `User-Agent: Sonex/1.0`、不带 API Key、Secret 或 Authorization header：

- `GET https://api.audius.co/v1/tracks/search?query=skrillex&limit=1` 返回结构有效的单条结果。
- 对该公开结果请求 `/tracks/{id}/stream` 时，Audius gateway 返回 `302` 音频重定向，说明请求已通过 gateway 的鉴权边界；本地继续访问重定向后的 storage host 时发生环境 SSL 错误，不能作为 Audius 鉴权失败。

这与官方 OpenAPI 的匿名读取声明一致，也说明当前 403 问题应优先归因于旧域名/请求头 transport，而不是缺少 API Secret 或 Bearer Token。
