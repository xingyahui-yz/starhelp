# 公开分发与本机服务契约候选 v0.1

- **编写日期：** 2026-10-28
- **状态：** S4.1 讨论候选；供 A/B/C owner 复核；接口未冻结，未授权开始 S4 实现或生产启用。
- **范围：** A→B 的公开知识包分发、撤回状态、本机 A 服务生命周期，以及公开 RAG 的后续可交付切片。
- **实现归属：** A 提供签名目录和只读制品；B 实现下载校验、缓存、回滚和第一阶段本机控制器；共享主机服务管理器负责第二阶段 A 进程生命周期；C 继续消费 B 本机已验证输入。

本文只提议新增接口，不修改 S3 共享契约、冻结源码或 artifact。A 当前只有原生 release 路由和 CLI 分发导出/校验；以下在线目录、撤回端点、readiness 字段及 B HTTPS adapter 都尚未实现。2026-10-21 的仓库报告属于历史证据，不能标成 2026-10-28 当日测试。根协调者现已确认 S3 最终技术验收：C final commit `fa512b6` 已远端核实；新集合为 83 checks（62 source + packaged），独立测量为 37/30；B2 commit 为 `c248daa`，B 报告为 65 tests/920 candidate/install。该结论关闭的是 S3 技术验收证据收口，不代表生产 tuple 获批、生产内容启用或生产验收。本候选仍只讨论未实现的 S4.1 接口。

## 1. 产品边界与阶段

| 阶段 | 服务拓扑 | 控制职责 | 公开数据边界 |
|---|---|---|---|
| 第一阶段：Windows 本机桌面端与后端验收 | Windows 桌面端启动 A 的 loopback 服务；B 同步公开分发包；C 仍由 B 按现有 one-shot 本机 worker 协议启动 | 新增的 B `KnowledgeBackendController` 管 A 的启动、readiness、健康探测和停止。A 只绑定 loopback；不在这个进程上终止公网 TLS。 | A 仅接收公开问题和公开证据；账号快照、UID、Cookie/token、角色拥有/面板/装备、报告及由其派生的条件始终留在 B/C 本机链路。 |
| 第二阶段：邀请制共享服务 | 主机服务管理器运行 A；A 通过 HTTPS 提供只读公开服务；B 作为客户端消费公开分发包 | 主机服务管理器负责 A 的部署、启停、readiness、TLS、日志与恢复。B 不管理共享主机进程，只做客户端同步。 | 默认服务身份只读。用户承担首轮内容 reviewer 与 publisher 责任；A 的发布仍须精确 revision/hash 审核、独立验证后显式激活。 |

两阶段都属于 MVP，顺序已确认。搜索或回答不自动创建 candidate，也不跳过审核/发布链。公开 RAG 是 MVP 的必需能力；真实来源 adapter、远程模型目的地、实际花费、生产密钥托管和真实内容许可另行逐项审阅，但这些确认不阻塞通用 RAG 的 synthetic/已获准证据实现。

## 2. 提议接口

以下接口路径和 JSON 均为候选，不代表 A 当前已提供。

| 方法与路径 | 调用方/用途 | 必要行为 |
|---|---|---|
| `GET /v1/distributions?profile=starhelp.local.v0.2&channel=<channel>` | B 发现目录 | 返回一个按第 3 节签名的目录。channel 来自本地固定配置，不允许服务端重定向到新 origin。目录含活动 release、可选回滚目标及绑定的撤回快照。 |
| `GET /v1/distributions/{release_id}` | B 下载确切 artifact | 只返回制品生成时保存的原始 envelope bytes。不得请求期间重新序列化或换签。支持 ETag/If-None-Match；ETag 只用于带宽优化，不替代目录 digest 或 envelope 签名校验。 |
| `GET /v1/distribution-revocations?profile=starhelp.local.v0.2&channel=<channel>` | B 获取目录引用的撤回快照 | 返回与目录内 `revocation_snapshot.sha256`、`sequence` 完全匹配的原始已签名快照。撤回不可达或不能验证时，不把状态显示为“当前有效”。 |
| `GET /health` | 本机进程 liveness | 保留现有 liveness 语义；只表示 HTTP 进程可响应，不代表数据库、迁移或分发就绪。 |
| `GET /health/ready` | B controller、主机服务管理器 | 返回第 8 节的最小 readiness 摘要。不得包含凭据、密钥、用户数据或请求正文。 |

所有下载限制为本地预配置的 HTTPS origin（第一阶段 loopback 例外仅限 A 本机），不带账号凭据或个性化字段。任何 3xx、跨 origin URL、嵌入式凭据、未知 scheme、路径逃逸和 query override 均拒绝。HTTPS 证书验证必须开启；不跟随重定向。

## 3. 签名对象与精确 schema

### 3.1 外层签名封装

目录与撤回快照使用相同外壳，不共用签名域：

```json
{
  "profile": "starhelp.public-distribution-catalog.v1",
  "payload": { "...": "profile-defined fields" },
  "signature": {
    "algorithm": "Ed25519",
    "key_id": "configured-public-key-id",
    "value": "lowercase-hex-signature"
  }
}
```

撤回对象的 `profile` 固定为 `starhelp.public-revocations.v1`。B 必须拒绝额外/缺失字段、重复 JSON key、非 UTF-8、非 JSON 数值、未知算法、未知 key ID 和 profile 不匹配。`value` 是 128 个小写 hex 字符，解码为 64 字节 Ed25519 签名。

签名输入统一为：

```text
ASCII(profile) + LF + canonical_json_utf8({
  "profile": envelope.profile,
  "algorithm": envelope.signature.algorithm,
  "key_id": envelope.signature.key_id,
  "payload": envelope.payload
})
```

其中 `canonical_json_utf8` 定义为 UTF-8 编码、`ensure_ascii=false`、object key 按 Unicode 字符串排序、无空格 compact separators、禁止 NaN/Infinity。目录签名前缀严格为 `starhelp.public-distribution-catalog.v1\n`；撤回前缀严格为 `starhelp.public-revocations.v1\n`。外层 `signature` 不进入待签 JSON，`profile`、算法与 key ID 进入待签 JSON 并由域前缀再绑定一次。验签前解析器必须拒绝重复 key，避免不同解析器得到不同签名对象。

线上目录/撤回签名和现有 B envelope 签名是不同用途；目录签名不能替代 envelope 内 manifest 的签名。信任配置必须把 key ID 绑定到允许的 profile/purpose，并验证轮换后的旧 key 是否仍有效。单 key 配合域分离，或不同 purpose 使用独立 key，均可由技术复核决定；本产品候选不要求必须使用两把生产 key。生产密钥的实际托管、轮换与恢复方案仍待审阅后配置。

### 3.2 Catalog payload

`payload` 必须严格符合以下字段。时间均为带 `Z` 的 RFC 3339 UTC；SHA-256 是 64 位小写 hex；commit 是完整 40 位小写 hex。数组去重并按其 identity 字段稳定排序。

| 字段 | 类型 | 约束/含义 |
|---|---|---|
| `schema_version` | string | 固定 `starhelp.public-distribution-catalog.v1`。未知版本拒绝。 |
| `origin_id` | string | B 本地 trust config 中配置的稳定服务标识；不能由目录改变其对应的 host。 |
| `channel` | string | B 本地允许的 channel（建议分别使用 `local`、`shared`）；不能任意创建信任域。 |
| `consumer_profile` | string | 必须与请求 profile 及 B 的本地 allowlist 相同；本候选示例为 `starhelp.local.v0.2`。 |
| `sequence` | integer | 每个 `(origin_id, channel, consumer_profile)` 单调递增的 catalog 序号，最小为 1。 |
| `issued_at` | timestamp | 签名目录生成时间。 |
| `valid_until` | timestamp | 目录有效截止时间，必须晚于 `issued_at`。 |
| `active_release_id` | string | 必须指向 `distributions` 中恰好一个条目。自动同步只采用该 release。 |
| `distributions` | array | 一个活动 release，可包含最多一个显式 `rollback_allowed=true` 的兼容回滚目标；数组总数建议不超过 2，以匹配 B 现有最多两份本地缓存。所有条目都必须适配相同 consumer profile。 |
| `revocation_snapshot` | object | `{ "path": string, "sha256": hex64, "size_bytes": integer, "sequence": integer }`。路径须为同 origin 的固定相对路径；hash 覆盖完整原始撤回 envelope bytes。 |

每个 `distributions[]` 条目严格包含：

| 字段 | 类型 | 约束/含义 |
|---|---|---|
| `release_id` | string | A immutable release identity；目录内唯一，必须与下载 envelope 和其中 native release 完全相同。 |
| `download_path` | string | `/v1/distributions/{release_id}`，禁止绝对 URL、query、片段、路径编码绕过。 |
| `envelope_sha256` | string | SHA-256 of the exact downloaded raw bytes，包括空白与签名封装；不能对重新序列化后的 JSON 求 hash。 |
| `size_bytes` | integer | 原始 artifact byte length；正数且不大于 B 已有的 64 MiB 下载上限。 |
| `envelope_profile` | string | 候选接受 `starhelp.b-publicbundle-envelope.v1`；须和 envelope manifest 相同。 |
| `a_producer` | object | `{ "package": "starhelp-knowledge", "version": string, "commit": hex40 }`。包名、版本、commit 一起做 allowlist 比较。 |
| `required_capabilities` | array of string | 分发所需能力，唯一且排序；必须是 B 的本地 capability allowlist 子集。 |
| `planner` | object | `{ "profile": string, "producer_profile": string, "component_version": string, "wheel_sha256": hex64 }`。四项都精确匹配本地 C 支持表。 |
| `b_snapshot` | object | `{ "profile": string, "producer_commit": hex40 }`。profile 与 producer commit 都精确匹配已验证 B 快照 producer tuple。 |
| `rollback_allowed` | boolean | 只表示此条目可由用户显式选作回滚目标；不授权自动降级，也不覆盖撤回/过期/tuple 校验。活动条目必须为 `false`。 |

目录必须满足：无重复 release ID；`active_release_id` 指向且只指向一个条目；`rollback_allowed` 条目不超过一个；所有下载路径、大小、digest、tuple、能力和撤回引用完整。若发行方需要把服务切回旧 release，必须签发一个**更高 catalog sequence** 指向旧 release；B 不因 sequence 增长而误认为内容版本必须增长。

### 3.3 Revocation payload

`payload` 严格包含：

| 字段 | 类型 | 约束/含义 |
|---|---|---|
| `schema_version` | string | 固定 `starhelp.public-revocations.v1`。 |
| `origin_id` / `channel` / `consumer_profile` | string | 与目录上下文逐字相等。 |
| `sequence` | integer | 此 trust scope 下单调递增的撤回序号，最小为 1。 |
| `issued_at` / `valid_until` | timestamp | 签发与截止时间；有效期内不得早于签发时间。 |
| `revoked_releases` | array | release 级撤回记录：`{ "release_id": string, "envelope_sha256": hex64, "reason_code": enum, "effective_at": timestamp }`。同 release ID 不允许绑定多个 digest。 |
| `revoked_public_refs` | array | 公共对象/证据撤回记录：`{ "kind": string, "id": string, "revision": integer, "content_hash": string, "reason_code": enum, "effective_at": timestamp }`。identity 为完整 revision/hash，不允许用模糊标题匹配。 |

`reason_code` 候选枚举：`rights_withdrawn`、`source_correction`、`integrity_issue`、`policy_change`。不得加入个人信息或自由文本敏感说明。release 撤回使整个 envelope 不可新装、不可继续作为当前有效包、不可回滚；public ref 撤回使该精确对象/证据不可作为有效依据。适配层只有在 C 当前 `latest_known_validity.withdrawn_public_refs` schema 能表达同一 identity 时才映射给 C；若字段形状不兼容，须另提有版本号的跨组件复核，不能在本候选中暗改 S3 契约。

撤回不可“取消”或让同一 release/object revision 重新有效。修正内容须新建 revision/hash；若整个包被撤回，修复后以新 release identity 发布。撤回条目可继续保留在后续快照中，避免丢失撤回历史。

## 4. 校验顺序、序号与有效期

B `PublicBundleHTTPSSource` 候选同步顺序。持久化分成三段：认证目录进入 pending、已验证撤回状态提交并立即生效、新 artifact 验证后原子激活。撤回状态不能依赖替代 artifact 下载成功：

1. 确认本地 origin、channel、consumer profile、允许的 HTTPS host 与证书；不跟随重定向。任何 metadata 网络请求前先持久化 `sync_in_progress=true` 并 flush；写入失败就不发请求、不接受新 metadata。
2. 有界读取 catalog 原始 representation bytes；强制 `Content-Encoding: identity`，校验大小、UTF-8/JSON 严格性、schema、签名 purpose/key/profile、origin/channel、issued/expiry 时间和 catalog sequence。签名无效、时间非法、序号倒退或同序号不同 bytes 时不得更新任何高水位。
3. 对签名与时间均有效且 sequence 合法的 catalog，先原子持久化其原始 bytes、raw digest、sequence 及 `pending_revocation_snapshot` 状态。此时只接受了认证后的发现元数据，不激活 artifact，也不把新 catalog 所指 release 视作当前可用。若撤回快照暂时不可取，保持最后一次完整接受的撤回状态；标记 `revocation_unknown`，仅按上一份完整状态的离线宽限提供 stale 行为，且不刷新 `last_complete_check`。
4. 下载 catalog 指定的完整撤回 envelope bytes；先校验精确 byte size 和 SHA-256，再校验 schema、签名 purpose/key/profile、上下文、issued/expiry 时间与 sequence。快照 sequence 必须等于 catalog 声明值，且不得低于已持久化的撤回高水位。任何一项失败都不修改撤回高水位或撤回集合。
5. 对已完整验证的撤回快照，先将原始签名 bytes 写入 durable journal 并 flush；再用一个原子事务写入 catalog/revocation high-water `(sequence, raw_sha256)`、完整已知撤回集合、目录到撤回快照的绑定及 `last_complete_check`，并清除 `sync_in_progress`。**事务提交后立即让撤回集合成为运行时 gate**：被撤回 release/object 在新分析、缓存选择、回滚和回答引用检查中不可用。撤回提交不等待 artifact 下载，不会被后续失败回滚。
6. 若当前 active release 已被撤回，先禁用它；只可改用当前 catalog 明确列出的另一个兼容、未撤回、未过期缓存目标。没有合格目标时保持无 active public bundle。已知撤回不能因离线、artifact 404 或校验错误而恢复。
7. 只对 catalog active release 下载 envelope 到临时文件；流式计数不得超过 `size_bytes` 或 64 MiB。先比对 raw byte 长度和 SHA-256，再解析 JSON 和调用现有 B envelope verifier。
8. B verifier 检查可信 envelope key、预期 release ID、manifest/member hash、native A release、C planner view 和 dependency closure；再次将其 A/B/C tuple 与 signed catalog 逐字段比较。
9. 只有所有检查通过，且 catalog/revocation sequence 仍与开始下载时相同，才原子写入缓存并切换 active pointer。artifact 失败只丢弃临时包、记录错误并保留 metadata 高水位/已知撤回；未被撤回的旧 active 是否可继续使用仍由离线宽限决定。

#### 提交、崩溃恢复与失败语义

- 目录高水位只在 catalog 签名、purpose、上下文、时间和序号均验证后持久化；撤回高水位只在 exact raw digest 与独立撤回签名、上下文、时间和序号均验证后持久化。单纯下载到的 JSON、签名错误数据或无法通过时间/序号校验的数据不能写入任何 high-water mark。
- `sync_in_progress`、`pending_revocation_snapshot` 和 durable journal 让进程崩溃后的恢复顺序确定：启动时先扫描并重新验签 journal；任何已验证待提交快照必须在缓存暴露或分析开始前应用。若 `sync_in_progress` 未清除、journal 缺失/损坏或恢复状态不明，B controller 不 ready；联网成功重取完整 catalog+revocation pair 前，不开放缓存分析。正常完成 metadata pair 提交后 marker 与高水位/撤回集合在同一事务中落定，之后 artifact 下载即使失败也不影响它们。
- catalog 已验证且高水位已写入、但撤回快照网络错误：不尝试 artifact 激活，不降回更低 catalog；运行中的客户端保留先前完整接受的撤回集合，状态为 `revocation_unknown`。仍未撤回的旧 active 仅可在上一份完整 pair 的离线宽限内以 stale 状态使用；若此时进程异常退出，持久化的 `sync_in_progress` 会要求下次启动先完成在线 metadata pair 校验。
- 撤回快照验签通过但 durable journal/原子事务失败：当前进程立即在内存 gate 中屏蔽受影响 release/ref，停止相关新分析，controller/readiness 标记不可用；不能继续使用未确认持久化的撤回状态。重启恢复必须检查 journal；无法确认则先在线重取完整 metadata pair，离线时保持 not-ready。
- 快照已持久化并生效、artifact 后续 404/超限/digest/兼容校验失败：撤回集合与两个 high-water 不变；被撤回的旧 active 保持禁用。若旧 active 未撤回且仍在离线宽限内，可按 stale policy 继续；否则无 active。
- artifact 下载期间若有更新的撤回状态提交，使用预期 sequence 的 compare-and-swap 阻止旧下载切换指针；重新发现最新 metadata 后再判断。

同一 catalog 或 revocation `sequence` 必须对应同一份不可变原始 representation bytes 和同一 SHA-256。服务端从发布时保存并原样返回这些 bytes，不得按请求重新序列化或换签；同 sequence 的 bytes/digest 不同视作完整性冲突。若要刷新 `issued_at`/`valid_until` 或以其他方式改变内容，即使语义未变，也必须递增 sequence。签名元数据和 envelope 下载禁止 HTTP 内容压缩；hash 覆盖 HTTP representation entity bytes（剥除传输 framing 后、解析前），避免客户端/代理的压缩与 JSON 重序列化造成歧义。

高水位按 `(origin_id, channel, consumer_profile)` 分别持久化；目录和撤回快照各存 `(sequence, raw_sha256)`。序号规则：

- 更低 sequence：拒绝为 replay/rollback。
- 相同 sequence、相同 raw digest：允许重复获取，不改变状态。
- 相同 sequence、不同 raw digest：完整性冲突，拒绝并告警；服务端改变 metadata bytes 必须升 sequence。
- 更高 catalog sequence：在 catalog 自身签名、purpose、时间和上下文通过后，先持久化 catalog high-water/pending 状态；不等 artifact 校验。
- 更高 revocation sequence：在快照与当前 catalog 的 digest/sequence 绑定、签名、purpose、时间和上下文全部通过后，先持久化撤回集合并立即生效；不等 artifact 校验。
- 更高 artifact/release：只有 tuple、撤回状态、内部签名与所有 hash 全部通过后才激活。
- A 想回退发布内容时，使用更高 sequence 的目录指向旧的、未撤回的 release。B 不接受旧 catalog 来完成回退。
- 高水位状态应保存在 B 的 durable application state，不能随清理两份内容缓存而清零。若重新安装导致可信高水位丢失，必须在线取得并验证当前签名目录；不能仅凭旧缓存自称已掌握最新撤回状态。

时钟以 UTC 为准；在线接受目录/撤回快照时，服务端 `issued_at` 不得比设备时钟超前 5 分钟以上（候选建议），且当前时间不得晚于 `valid_until`。到达 `valid_until` 后，已缓存的最近有效状态转为 `offline_stale`，只有在最近一次完整成功核验起仍处于离线宽限内才能继续使用；宽限结束后为 `expired`。不能用本机重新签发时间延长服务端签名有效期。

### 推荐的初始新鲜度配置（待技术复核）

| 参数 | 建议初值 | 行为 |
|---|---:|---|
| catalog TTL | 24 小时 | 超时后尝试刷新；在线接受新目录的硬边界是签名 `valid_until`，已缓存内容是否可在 stale mode 临时使用由单独的离线宽限控制。 |
| 启动刷新 / 后台刷新 | 启动时刷新；之后每 6 小时 | 以服务端 sequence 为准，避免使用客户端轮询序号推断撤回。 |
| 最大离线宽限 | 最近一次**目录与撤回快照均成功核验**起 72 小时 | 宽限内显示 `offline_stale` 与上次成功核验时间；不宣称最新。超出后状态 `expired`，停止把本地包用于“当前有效”结论或新 RAG 回答。 |
| 服务端时间未来偏差 | 5 分钟 | `issued_at` 超前于本机 UTC 超过 5 分钟时拒绝目录/撤回快照，并显示设备时间异常。 |
| catalog 最大原始尺寸 | 1 MiB | 超限拒绝，不解析部分内容。 |
| revocation snapshot 最大原始尺寸 | 4 MiB | 超限拒绝；大规模撤回需另设计分页/压缩 profile。 |
| envelope 最大原始尺寸 | 64 MiB | 延续 B 已有下载边界；目录声明更大时拒绝。 |
| 网络重试 | 最多 3 次 | 仅超时、连接错误、429、5xx 可重试；指数退避并遵守有界 `Retry-After`。验签、兼容、撤回、digest/序号冲突不重试。 |
| timeout | connect 3 秒、read 10 秒、同步轮次整体 15 秒（含重试） | 超过则视为本轮网络不可用；不阻塞启动既有缓存状态的展示。 |

以上数值均为供复核的建议，不是已确认产品策略或实现事实。网络不可用时，只能按配置宽限继续使用上一次通过完整验证且未发现撤回的缓存；界面显示最近核验时间和 `offline_stale`/`unknown`。已知 revoked 永远不可用，离线状态不能撤销已知撤回。宽限过期后保留文件供诊断/回滚取证，但不得把它用于当前有效的计划或证据回答。

**B 本机分发离线策略与 A 服务器 RAG 新鲜度是两套状态。** catalog/revocation 离线宽限只管理 B 本地 cache、以及 B/C 的本机分析；它不能替 A 的服务器证据延寿。A RAG 依据自己的来源 policy、capability/观测时间、evidence revision/hash 和撤回 tombstone 判断新鲜度；来源新鲜度未知或超期时，A 必须把证据标 stale/unknown、限制当前性结论或 abstain。A `/health/ready` 只表示服务依赖就绪，不代表证据新鲜或 RAG 可作出当前事实结论。A 共享 RAG 不读取 B 的离线 cache；B 离线时也不把自己的 cache 当作 A 服务端来源。

## 5. 兼容元组与当前可用锚点

schema/profile 名称只是元组的一部分，必须同时比对包版本、完整 commit、能力集合、planner wheel digest 和 B snapshot producer。任何未知值 fail closed，不从“相近版本”推断兼容。

| 元组成员 | 当前 S3 锚点 | 当前证据边界 |
|---|---|---|
| A producer | `starhelp-knowledge` `0.3.0`；commit `dcb1e3ee220b85229bedc6c79d72ebe495825f37` | 该 commit 是已记录的 A producer 锚点，不代表线上 HTTP 已支持目录。 |
| B envelope | `starhelp.b-publicbundle-envelope.v1`；能力 `starhelp.knowledge-distribution.v1` | 现有 A exporter/verifier 可生成/校验 envelope；生产 HTTP 发现/下载尚不存在。 |
| C planner | profile `starhelp.local.v0.2`；producer adapter `starhelp.producers.v0.1`；component `0.4.0`；wheel SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2` | 只接受 C wheel 与 producer profile 精确匹配；不能把 schema 版本当作 wheel identity。 |
| B snapshot | B1 profile `starhelp.desktop.snapshot.interop-min.v0.1`；producer commit `103741e02c90ac672017f783058bdd8dacae982e` | 是此前 S3 样例的兼容锚点。 |
| B2 replay | B2 source commit `c248daab22255a069464a6d277757d01df5d49f3` | 根协调者已确认其 S3 技术验收证据收口；该 replay identity 及报告不是生产 tuple 批准。 |

这些值用于讨论测试夹具和 allowlist 结构。候选文档不冻结 B2 生产 tuple；需要 B/C owners 根据最终证明确认实际 producer commit、profile 和 C digest。更新兼容项必须通过显式 reviewed allowlist 变更；运行时从目录学到的新 commit 不能自我授权。

## 6. 失败响应与客户端动作

以下是 B 客户端的规范化错误码候选；底层 HTTP 状态不是安全决策依据。

| 条件 | 错误码 | 新 release 是否激活 | 重试/恢复 |
|---|---|---:|---|
| connect/read/overall timeout、断网 | `distribution_unavailable` | 否 | 最多 3 次网络重试；之后按离线宽限展示现有缓存及其状态。 |
| HTTP 429 / 5xx | `distribution_temporarily_unavailable` | 否 | 遵守上限内的 `Retry-After`；宽限与超时同上。 |
| catalog/revocation 404 | `distribution_metadata_not_found` | 否 | catalog 404 不重试；revocation 404 不得当作“空撤回集”。 |
| catalog 已验签并持久化，但对应撤回快照暂不可达/校验未完成 | `revocation_state_unknown` | 否 | 保留上一份完整接受的撤回集合与新 catalog high-water；不刷新完整核验时间。旧 active 仅可按上一份完整 pair 的离线宽限 stale 使用。 |
| artifact 404 | `distribution_artifact_not_found` | 否 | 可刷新一次目录并重试其当前活动 artifact；仍 404 时失败。 |
| 3xx、跨 host、非 HTTPS、主机名不匹配 | `distribution_origin_rejected` | 否 | 不跟随、不重试；只接受修正后的本地 trust config。 |
| oversized response、声明长度/实际长度不匹配 | `distribution_size_invalid` | 否 | 不重试；删除临时文件。 |
| invalid JSON/schema/duplicate key/unknown profile | `distribution_format_invalid` | 否 | 不重试；保留旧 active。 |
| unknown key、wrong purpose/domain、签名失败 | `distribution_signature_invalid` | 否 | 不重试；记录 key ID/profile，不能降级为 unsigned。 |
| catalog 或撤回 sequence 降低 | `distribution_replay_rejected` | 否 | 不重试；保留高水位与 active，并提示在线状态异常。 |
| same sequence with different digest | `distribution_sequence_conflict` | 否 | 不重试；按完整性事件处理。 |
| metadata expired / clock skew 超限 | `distribution_metadata_expired` / `device_clock_invalid` | 否 | 可在线重新获取更高有效目录；不得延长旧签名。 |
| raw envelope digest、size、内部 manifest/member hash 不匹配 | `distribution_integrity_failed` | 否 | 不重试；删除临时文件并保留 active。 |
| unknown tuple/capability/component digest | `distribution_unsupported` | 否 | 不重试；更新客户端 allowlist/实现需正式发布。 |
| release 或所需 public ref 已撤回 | `distribution_revoked` | 否 | 永不回滚到已知 revoked release；重新获取目录只可找到新 identity。 |

所有拒绝都保留当前可用且未撤回的 active 文件，不切换指针。不得把 catalog 解析失败当成“目录为空”，不得把撤回查询失败当成“没有撤回”，不得在校验错误后继续用部分下载内容。

## 7. 本机缓存、回滚与分发身份

- 默认缓存最多保留两个完整 envelope，与 B 现有 cache cap 一致。每个条目记录来源 origin/channel/profile、catalog sequence/digest、revocation sequence/digest、原始 artifact hash/size、tuple 和最近完整验证时间。
- 自动同步只获取 signed catalog 的 `active_release_id`。`rollback_allowed` 目标只能由用户在 UI 明确选择，且必须仍出现在当前签名目录、未撤回、未过期并通过现行 tuple/envelope 校验。
- 回滚是本地缓存指针的原子切换，不重签、不更改 artifact、不降低 catalog/revocation high-water。A 侧发布回滚则以较高 catalog sequence 指回旧的 nonrevoked release。
- catalog 更新成功但 artifact 校验失败时，不删除旧 active，不把“最新可见”误作“最新已验证”。
- 离线宽限中只有本地已验证并且没有已知撤回的 active 可继续按 stale 标记使用；一旦知道 release 被撤回，立即禁用当前与回滚路径。
- A 共享服务的 runtime service identity 默认只拥有读取发布目录/制品的权限；candidate/review/build/validate/activate/rollback 等管理动作走单独的 curator/publisher 身份和审计通道。用户是首轮内容 reviewer/publisher；目录签名作业只签已显式激活的 immutable release，线上服务不持有目录私钥。

## 8. 服务 readiness 与生命周期边界

候选 `GET /health/ready` 响应：

```json
{
  "status": "ready",
  "service": "starhelp-knowledge",
  "application_version": "0.3.0",
  "schema_version": "<current-db-schema-version>",
  "database": "ready",
  "migration": "current",
  "active_release_id": "<release-id-or-null>",
  "distribution_catalog": "available",
  "checked_at": "2026-10-28T00:00:00Z"
}
```

字段约束：`status` 是 `ready|not_ready`；`database` 是 `ready|unavailable`；`migration` 是 `current|pending|failed`；`distribution_catalog` 是 `available|unavailable|not_configured`。数据库不可读、迁移未完成/失败，或本地配置声明需提供 distribution 但目录不可构建时，`status=not_ready`。若 A 部署模式不托管在线目录，明确返回 `not_configured`，不能谎称 `available`。无 active release 可作为“空服务”运行的决定尚待 A owner 复核；readiness 必须明确其策略，不能只检查 socket。

### 第一阶段 B controller 候选接口

```text
KnowledgeBackendController.start() -> StartResult
KnowledgeBackendController.health() -> HealthResult
KnowledgeBackendController.stop(grace_seconds) -> StopResult
```

`start` 使用固定安装路径和 argument vector，不使用 shell；A 只绑定 `127.0.0.1`/本机 loopback，等待 `/health/ready` 到达 ready 或明确超时失败。重复 start 必须幂等，不启动第二个同库写进程。`health` 只回传 pid、应用/schema 版本、readiness、active release ID 和 last error code，不暴露环境变量/路径凭据/请求内容。`stop` 先请求正常退出，宽限超时后才结束该 controller 拥有的进程，并确认端口释放；不能杀掉同名但不属于本应用的进程。

第二阶段由 Windows/Linux host service manager 或部署平台管理 A；B 不调用跨网络 start/stop endpoint。共享 A 的 liveness/readiness 供负载均衡与运维探测，HTTPS/TLS 在受支持的反向代理/平台边界终止。C 继续按现有 B `LocalPlannerProcess` 的 per-request one-shot 生命周期运行；它不是 A 服务 controller，也不因本提案变成长驻 worker。

## 9. 字段来源与缺口矩阵

| 契约字段/动作 | 当前来源或实现 | 责任模块 | 尚缺工作 |
|---|---|---|---|
| `release_id`、A release body、candidate/review/activate 状态 | A service/SQLite immutable release；review 绑定 exact hash | A domain/service | 在线目录 builder 读取已验证 active release，不能直接从候选队列构造目录。 |
| B envelope、A/C 投影与内部签名 | A `distribution.py` / CLI export-verify；profile `starhelp.b-publicbundle-envelope.v1` | A distribution adapter + offline signer | A HTTP 目前没有 envelope catalog/distribution routes；需离线/受控签名发布流程。 |
| `envelope_sha256`、`size_bytes`、immutable download bytes | 当前 CLI 导出文件；HTTP 未提供 | A immutable artifact store/route | 制品生成后原字节落盘/存储，计算 digest/size 并禁止原位覆盖。 |
| catalog/revocation schema、签名、sequence、TTL | 当前不存在 | A catalog signer/builder 与 B verifier | 新增 profile、purpose-bound trust、持久 high-water 和严格 parser。 |
| A/B/C producer tuple 与 required capabilities | envelope manifest 和现有 A/B/C profiles | A exporter，B `PublicBundleSynchronizer`，C producer adapter | B HTTPS adapter 需与本地精确 allowlist 比对；B2 replay tuple 尚未获批为生产兼容元组。 |
| revocation -> C withdrawn public refs | C 消费 `latest_known_validity.withdrawn_public_refs`；B 候选输入已支持最新撤回 refs | A revocation publisher，B mapping/validation，C existing adapter | 确认 exact C shape；不兼容时通过独立 review 调整，不编辑 S3 共享契约。 |
| B 本地 cache 最多两个版本/原子 current pointer | `PublicBundleCache` 已有基础实现 | B cache/synchronizer | 加入 online sequence/revocation metadata、用户可控显式 rollback 与 stale/expired/revoked UI。 |
| B→A HTTPS source | `PublicBundleSource` protocol 只有 discover/fetch 抽象；无 A HTTPS adapter | B adapter | 实现固定 origin、签名目录/撤回、raw hash、redirect/size/timeout 拒绝路径。 |
| A liveness `/health` | 静态 WSGI `status=ok` | A HTTP | 保持 liveness 含义；新增 `/health/ready` 及 DB/migration/catalog 可用性检查。 |
| A 进程 start/stop | A CLI `serve` 默认 loopback WSGI；无 B controller | B Windows controller（Phase 1）；host manager（Phase 2） | 生命周期、超时、重复启动、崩溃恢复和只终止自有进程的规则。 |
| 公共检索 | A 本地确定性关键词查询；`/v1/public-search` 无命中不会建候选 | A query/service | 尚无语义索引、引用检索 rerank 或回答生成。 |
| 内容来源许可/采集覆盖 | 来源 policy/capability 模型 + `VerifiedJSONSourceAdapter` 通用 HTTPS transport；没有具体 live adapter | A source adapter per source | 权限证据与能力快照各自核实；不因 transport 成功启用真实采集。 |

## 10. 验收矩阵（候选，未执行）

| 场景 | 输入/前提 | 预期结果 |
|---|---|---|
| 正常首次同步 | trusted key、合法 catalog/revocation、精确 tuple、raw artifact hash/签名有效 | B 原子安装活动 release；保存 sequence/digest 与核验时间。 |
| 重复同步 | 与本地相同 sequence 和 raw digest | 幂等成功，不重写身份或降低高水位。 |
| 服务端回退到旧 release | 更高 catalog sequence 指向仍被允许的旧 release | 自动更新按签名活动指针处理；如果要回滚现有缓存则由用户明确操作。 |
| 显式本地回滚 | 目录中 `rollback_allowed=true`，目标在双槽缓存内、tuple/撤回/时间仍有效 | 原子切换；保留 high-water；审计目标 release ID。 |
| 目录/撤回离线 | 已有已验证 release，仍处于离线宽限 | 保留本地内容；UI 显示 stale/unknown 和上次核验时间；不说撤回状态最新。 |
| 新鲜有效撤回 | 当前快照撤回当前 release 或引用对象 | release 撤回时阻止使用/回滚；对象撤回时输出中移除相关依据并进入 C validity input。 |
| 撤回已验证、替代 artifact 失败 | 更高 sequence 的有效撤回快照撤回当前 release；新 artifact 404、超限或 hash 无效 | 撤回 high-water 和 tombstone 仍已提交；旧 release 仍禁用；不回滚撤回状态。 |
| tampered bytes / size | 单字节变化、长度超限/不符、下载中断 | 候选拒绝，不写缓存、不切换 active；临时文件清理。 |
| 伪造/用途混淆签名 | 错 key、catalog key 用于 revocation purpose、非法 profile、signature 错 | `distribution_signature_invalid`，fail closed。 |
| sequence replay/conflict | lower sequence；或 same seq with different digest | 拒绝并保留持久 high-water/current release。 |
| 同序号重序列化 | payload 语义相同但 whitespace/字节表示不同 | 按 same-sequence digest conflict 拒绝；服务端必须升 sequence 并发布新的不可变 bytes。 |
| stale/expired/revoked | 过期 metadata、越界未来时钟、已知撤回 artifact | 不激活；无离线宽限可用后不得再宣称当前有效。 |
| tuple 漂移 | 相同 schema 但不同 A commit、C wheel hash、B producer commit 或未支持 capability | `distribution_unsupported`；不猜兼容，不激活。 |
| 重定向/换 host | 3xx、绝对外链、跨 host 下载 URL | 无请求跟随/不激活；安全日志不含凭据。 |
| 双阶段 lifecycle | 重复 start、readiness 未就绪、stop 超时、其他同名进程存在 | 只管理本应用进程；ready 前启动失败；stop 不误杀外部进程。 |

上述是未来 A/B/C 实现的验收设计，不代表这次运行了代码或测试。当前 turn 仅形成文档候选。

## 11. 公开 RAG 后续切片

通用 public RAG 按可单独审阅与验证的模块拆分。第一轮用 deterministic synthetic fixtures 和已获准人工证据；未确认许可的真实来源与远程模型都保持禁用。语义检索是通用实现能力选项，不是额外产品权限 gate；来源条款只限定对应证据的处理、派生向量、缓存与展示。

| 切片 | 范围与完成证据 |
|---|---|
| RAG-1：公开证据接入与规范化 | 接受公开 question scope 与 evidence provenance；支持 synthetic/明确 allowed 来源；保留原 URL、locator、content hash、source status、发布日期和观测时间。不读账号快照，不启动 live source collector。 |
| RAG-2：切块与索引 | 以 `(source_id, evidence_id, revision, content_hash, chunker_profile)` 生成稳定 chunk identity；索引版本可重建、可比较；实现 lexical 路径并留出 semantic/hybrid adapter；fixture 覆盖重复、更新和删除。 |
| RAG-3：检索与排序 | 按公开 scope、游戏版本、证据状态、时间和撤回 tombstone 过滤；返回候选及可解释排序理由；不得把 stale/withdrawn evidence 当作当前事实。 |
| RAG-4：有据回答与拒答 | 每条可核查事实引用 evidence ID、URL、标题、locator 与版本/日期；证据不足、冲突或范围不符时明确 abstain；不得添加检索证据无法支持的结论。 |
| RAG-5：隔离与发布链 | question/answer 不自动创建 candidate；操作者明确挑选事实和 evidence 后才进入 immutable candidate revision/hash，再走用户 reviewer 精确 hash 审核和独立 publisher build/validate/activate。 |
| RAG-6：可复现实验 | 用 synthetic/approved corpus 做正例、无命中、冲突、陈旧、撤回、版本范围、重复证据、prompt injection/来源内指令等正负案例；记录 retrieval recall/ranking、citation coverage、abstention 和资源成本。 |

可选 provider 必须遵守 public-only payload allowlist。若采用远程模型，具体目的地、脱敏、用量上限与费用方案先形成可审阅配置；这些业务确认不阻塞 RAG-1 到 RAG-6 的本地/synthetic 实现。

## 12. 复核项与决策状态

**已确认：** 两阶段顺序及其都属于 MVP；默认共享服务身份只读；用户负责首轮 reviewer/publisher；公开 RAG 必须进入 MVP；先提交可审阅配置/实现提案，再请用户执行真实来源、账号、远程 provider 或生产密钥操作。以上不再列为用户待决项。

**请 A/B/C owners 技术复核：** catalog/revocation schema 与错误码；目录/撤回签名复用同 key 的域分离或 purpose-separated keys；catalog 24h/refresh 6h/offline grace 72h/clock skew 5m；size/time/retry 上限；B2 实际 replay tuple 与 C wheel digest；撤回引用到 C `withdrawn_public_refs` 的精确 adapter mapping；catalog/revocation journal 的 durable commit 与启动恢复实现；controller executable/readiness/upgrade/stop 细节；目录是否只公开当前 active 或同时发布一个 rollback candidate。

**仍需以后逐项提供方案后确认的真实操作：** 各来源许可/接口启用，具体远程 provider/费用，生产信任根和密钥托管，真实内容的人工 review/publish，任何真实账号授权。它们都不构成阻塞先做 synthetic/approved fixture 与 generic public RAG 的理由。

## 13. 当前实现锚点与证据说明

- A 当前实现锚点：`packages/starhelp-knowledge/src/starhelp_knowledge/http.py`、`distribution.py`、`cli.py`、`service.py`、`sources.py`。目前 `/v1/releases` 与 `/v1/releases/{id}/bundle` 是 A 原生 release 路由，不等于本文候选的 B envelope 在线目录/下载协议；`/health` 当前只返回静态 liveness。`VerifiedJSONSourceAdapter` 是受策略与 capability snapshot 约束的 generic transport，不是已获许可的具体来源 adapter。
- B 已有 `PublicBundleSource`、`PublicBundleSynchronizer` 和最多两份 cache 的基础；未有 A HTTPS adapter、签名在线 catalog/revocation 校验或明确 rollback API。C 是现有 one-shot worker，不是 A service controller。
- 2026-10-21 记录的运行结果是历史结果，不能标成 2026-10-28 当日测试。根协调者已确认 S3 final 技术验收：C final commit `fa512b6` 已远端核实；新集合 83 checks（62 source + packaged）；独立测量 37/30；B2 source commit `c248daa`；B 65 tests/920 candidate/install report。此技术验收不等于生产 tuple 批准。本文没有重跑相关包，也未改动 S3 代码、artifact、共享契约/协调锁。
- 本文新增内容只是一份 A 包内的契约候选，所有新 endpoint/schema/数值都尚未冻结、尚未实现。
