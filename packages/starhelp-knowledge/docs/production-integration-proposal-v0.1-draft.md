# 生产接入提案（讨论稿 v0.1）

**核查日期：** 2026-10-21
**状态：** 供用户审阅；不冻结接口、不启动 S4、不代表生产验收。
**范围：** 只讨论 A（公开知识后端）与 B（桌面端）的生产接入，以及 A 的公开资料检索与证据回答。账号快照仍只在 B/C 本机链路中使用。本提案没有启用采集器、访问真实账号、创建真实审批或配置生产密钥。

## 当前实现与缺口

| 部分 | 仓库中已有的实现 | 生产缺口 |
|---|---|---|
| A 发布与分发 | SQLite 已保存来源策略/能力快照、证据、候选及不可变修订；审核绑定精确修订哈希；构建、验证、激活、回滚是分开的、需权限的审计操作。`export-bundle` 导出 A 原生 bundle；`export-distribution` 使用外部 Ed25519 私钥导出 B `PublicBundle` envelope；`verify-distribution` 可独立校验 envelope 签名、A release、C 投影、能力与依赖闭包。 | HTTP `GET /v1/releases` 发现的是 A index release 元数据；`GET /v1/releases/{id}/bundle` 返回 A 原生 bundle。HTTP 目前没有 B 签名 envelope 的发现或下载路由，也没有签名撤回/时效目录。不能把这两个现有路由当成 B/C 分发协议。私钥当前由 CLI 文件参数读取，部署时应在受控发布作业签名，线上服务只提供不可变产物。 |
| B 校验与缓存 | `PublicBundleSource`、`PublicBundleSynchronizer` 已定义发现/下载接口；同步时校验预期 release ID、签名和支持能力，再以原始验证字节写入缓存并切换当前指针。缓存最多保留两个版本。B 构造 C 请求时显式传入用途、信任公钥、A/B producer commit 与格式 profile。 | 没有实现面向 A 的 HTTPS `PublicBundleSource`。同步适配器没有验证签名目录、撤回状态或时效期限的在线协议；缓存只有本地、未签名的验证时间回执和 manifest 中可选时效字段。没有显式的 B 回滚 API；两份缓存不等于已批准的回滚行为。 |
| C 本机执行 | B 通过 `LocalPlannerProcess` 为一次分析启动固定本地 worker，stdio 通信有超时、尺寸上限和 profile 撤权取消；worker 校验请求后加载固定 C 0.4.0 wheel。C 的 producer adapter 对 A commit `dcb1e3e…` / package 0.3.0 和 B1 `103741e…` 有明确兼容项。 | C worker 是每次请求启动的一次性子进程，没有常驻 health endpoint。S3 记录中的 C 0.4.0 安装轮 replay 已通过；B2 host 最终集成门仍待验收，不能据此宣布三方或生产接入完成。 |
| A 服务进程 | CLI `serve` 启动本机 WSGI 服务，默认绑定 `127.0.0.1:8765`；`GET /health` 固定返回 `status: ok`。 | WSGI 入口不是公网 TLS 终止器。当前 health 不检查数据库迁移、读写能力、签名目录或发布可用性；没有 B 对 A 服务的 start/stop 管理接口。共享部署应由服务管理器控制 A，桌面端只消费 HTTPS 服务。 |
| A 检索与回答 | `/v1/query` 在单个固定 release 内查实体、关卡/模板或做确定性关键词包含匹配；`/v1/public-search` 先跑本地关键词检索，无命中只返回 `triggered`。 | 无真实外部搜索 provider、语义/向量索引或答案生成器；`/v1/public-search` 明确返回 `provider_status: not_configured`、`candidate_queue: not_created`。当前能力是本地检索，不是完整 RAG 回答链。 |

**S3 现状核对：** A 的 producer commit 为 `dcb1e3ee220b85229bedc6c79d72ebe495825f37`，不可变样例 artifact commit 为 `4610573ee9720f2b5e4760a9336263362446b800`。C 0.4.0 的固定 wheel SHA-256 为 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`；截至本提案日期，C 的已安装回放覆盖该 A 0.3.0 与 B1 serializer 的固定合成样例。协调锁仍记录 B2 host final gate 未收口、three-party replay 与 production acceptance 未通过。旧的 A handoff 中早先写的“C 尚未支持 A 0.3.0”描述已被 C 0.4.0 的后续固定证据更新；应以版本和 capture lock 为准，不能抹去 B2 待验收状态。

## 建议的 A→B 分发闭环

继续使用现有 B envelope 与 C planner profile；新增的在线传输和撤回目录应作为单独版本化接口，不能改变已冻结的 S3 样例或 A/B/C 共享契约。

```mermaid
sequenceDiagram
    participant Curator as A 审核/发布
    participant Signer as 受控签名作业
    participant A as A HTTPS 分发服务
    participant B as B 桌面端
    participant C as C 本机 worker
    Curator->>A: 审核精确修订，验证并显式激活 release
    A->>Signer: 导出不可变 PublicBundle
    Signer->>A: 签名 envelope 与签名目录
    B->>A: 读取签名目录与候选 release
    A-->>B: 返回 profile、版本、时效、撤回状态及下载标识
    B->>A: 下载不可变签名 envelope
    B->>B: 验签、核对兼容性/时效/撤回，再原子切换缓存
    B->>C: 本机发送已验证公共包与本机快照
    C-->>B: 返回本机分析结果
```

### 候选接口

| 接口 | 目的与约束 |
|---|---|
| `GET /v1/distributions?profile=starhelp.local.v0.2` | 新增的签名目录读取接口，返回 release ID、A producer 版本/commit、B envelope profile、C profile、能力集、不可变下载标识、签发时间和 `valid_until`。目录还带单调递增序号及撤回的 release ID/content hash。返回体由独立的目录签名 key 签名；B 先验目录签名，再用已有的分发信任 key 验 envelope。 |
| `GET /v1/distributions/{release_id}` | 下载该 release 的原始、不可变 B `PublicBundle` envelope；支持 ETag/If-None-Match，但响应内容必须与已签名目录中的 digest 一致。重定向、跨主机 URL、未知 profile、尺寸超限都拒绝。路由不能重新生成不同字节的 envelope。 |
| `GET /health/ready` | 新增 readiness 检查：服务版本、数据库 schema/migration 状态、可读的 active release、分发目录可用性。不得返回密钥、token、用户数据。现有 `/health` 保持 liveness 语义或逐步兼容；不要继续用静态 `ok` 表示已可生产服务。 |
| B 内部 `PublicBundleHTTPSSource` | 实现现有 `PublicBundleSource` protocol。仅请求固定配置的 HTTPS host，不带 bearer token、UID、cookie 或账号字段；提供 `discover_release(current)` 和 `fetch_release(id)`。先校验目录与兼容 tuple，再取 envelope；校验签名、exact release、A/B/C profile、能力和 hash 后才激活。 |
| B 内部 `PublicBundleCache.rollback(target_release_id)` | 只在目标是本地已验签、未撤回、未过期且兼容的缓存版本时原子恢复。新版本验签或兼容性失败时保留当前版本；已撤回版本禁止回滚。在线撤回不可达时，界面显示“撤回状态未知”和上次核验时间，不伪称已确认安全。 |
| B 本地 `KnowledgeBackendController`（仅当选择桌面内嵌 A） | 候选 `start() / health() / stop(grace_seconds)` 进程控制契约：固定 executable/参数、无 shell、只绑定 loopback；start 需等待 readiness，health 返回 pid/版本/schema/active release 这类非敏感状态，stop 先请求正常结束、超时再结束进程。当前 B 没有这个 A 进程控制器，C 的 one-shot worker 不能替代。若采用共享服务，start/stop 由主机服务管理器负责，B 只访问 HTTPS。 |

签名目录建议至少包含 `schema_version`、`sequence`、`issued_at`、`valid_until`、受支持的 producer/profile tuple、latest release 的 envelope digest、撤回列表和签名用途。分发签名与目录/撤回签名应有清楚区分的 key ID 与用途；私钥轮换、撤回 key 的信任锚更新需单独设计。目录 TTL 与最大离线使用时长是待用户决定的产品策略，不在本文替用户设定。

兼容性以精确 tuple 白名单判定：A commit + package version + B envelope profile + C producer adapter profile/wheel hash + B snapshot profile。不得仅凭 `schema_version` 或兼容字符串推断支持。首次在线对接应先用当前固定的 S3 artifact 和测试公钥跑通传输；测试公钥不能进入生产信任锚。B2 host replay 完成前，仍按未验收处理。

## 公开资料 RAG 与证据回答

建议将 RAG 拆成「已发布本地知识检索」和「获准来源的临时公开检索」两层。先实现与来源无关的处理接口，使用 synthetic fixtures 或人工添加且有许可的证据验证；来源授权不清时不接真实 collector，也不阻塞通用检索/引用代码。

1. **问题输入：** 使用单独的 public question schema，只接受公开问题、游戏版本/模式/周期/关卡等公开 scope、结果数上限。不允许 UID、账号快照、角色拥有/面板/装备、报告、Cookie/token 或从账号派生的过滤条件。A 不接收 B 的个性化数据。
2. **检索：** 第一阶段在指定 `index_release_id` 上做结构化字段、确定性关键词和可解释排序；后续可插入语义检索接口，但只有当训练/向量化、保留和供应商条款覆盖来源文本及向量用途后才启用 embedding。结果必须保留证据 ID/revision、原 URL、locator、内容 hash、来源状态和发布时间/观测时间。
3. **临时来源结果：** 命中已允许且能力已核实的来源后，临时证据默认只在本次回答上下文中使用。内容是否可缓存、可摘要、可生成向量、可展示原文，分别由该来源的 policy 明确允许；HTTP 传输成功或 `VerifiedJSONSourceAdapter` 的 capability snapshot 不等于来源授权或完整覆盖证明。
4. **回答：** 只用检索到的公开 evidence 生成回答；每个可核查事实带来源 URL、标题/定位符和版本/日期。回答指出观点冲突与信息缺口；证据不足时明确回答未找到可靠依据，不补写事实。来源状态未知、过期或撤回时，不把内容当作当前有效答案。
5. **候选、审核、发布隔离：** 一次搜索/回答不得自动创建 candidate。需要沉淀时，操作者从回答中明确选择事实和证据，再单独调用 candidate 创建；candidate 形成不可变 revision/hash；reviewer 对精确 hash 作出审核；publisher 再独立 build、validate、activate。回答引用不代表候选获批，审核也不等于发布。

### 最小留存建议

来源 policy 允许后，优先只保留规范 URL/稳定外部 ID、标题、署名所需的公开作者标识、精确 locator（章节/时间戳/JSON pointer）、游戏版本、发布时间、首次/最近观测时间、原文 hash、审核状态及最短必要 excerpt。A 当前 evidence 记录已有 URL/title/author/excerpt/locator/license/scope 字段，并限制 excerpt 大小；生产默认 excerpt 可进一步按每个 source policy 收紧。

未获明确许可时不保存整篇攻略、音视频、转录、图片/游戏素材、评论或完整镜像。embedding 也是源内容的派生存储，只有在许可覆盖后才加入。引用本身用于可追溯，不等于获得复制、缓存或再发布权。用户主动给出的内容也需记录其来源和使用授权范围。

## 候选来源核查（截至 2026-10-21）

这里只检查第一方/官方文档与仓库说明，没有调用任何候选数据 API、没有登录或使用凭据。文档中没找到接口或许可，不代表断言该来源不存在；状态应保持 `unknown`，等待明确材料。

| 来源 | 本次核查到的材料 | 接入建议 |
|---|---|---|
| HoYoverse 官方 HSR 公告/角色页 | 官网发布版本公告、角色说明，可作人工核验后的 canonical citation；本次未核实可供第三方批量同步的机器接口或批量复用许可。[官方公告](https://hsr.hoyoverse.com/en-us/news/166468)、[角色页](https://hsr.hoyoverse.com/en-us/character)、[服务条款](https://hsr.hoyoverse.com/en-us/company/terms)。 | 可先手工录入最小事实并附官方链接、具体版本/发布日期和 locator；不自动抓取或镜像。正式自动同步前要确认许可和接口。 |
| Nanoka `static.nanoka.cc` | 维护者 README 记录静态 JSON API 和 beta 数据，并声明数据版权属于原始数据方与 HoYoverse、仅供学习研究；仓库 MIT license 标的是 skill 代码。[README](https://github.com/Run2zZ/hsr-nanoka)、[schema](https://github.com/Run2zZ/hsr-nanoka/blob/main/references/schema.md)、[代码许可证](https://github.com/Run2zZ/hsr-nanoka/blob/main/LICENSE)。 | 可用于离线 schema 评估；生产导入保持禁用，等待数据许可、再发布/缓存条件、频率和 beta 范围的书面澄清。即使许可获准，也按版本固定数据并仅留必要字段、原 JSON pointer 和 hash。 |
| Mar-7th/StarRailRes 与 DimbreathBot/TurnBasedGameData | StarRailRes README 列出多类 JSON 索引，并把游戏数据来源指向 StarRailData；仓库页面标 AGPL-3.0。StarRailData README 将自身描述为 HSR release data，并欢迎工具/网站致谢，但没有授予游戏数据或素材的生产再分发权。[StarRailRes README](https://github.com/Mar-7th/StarRailRes/blob/master/README.md)、[StarRailRes LICENSE](https://github.com/Mar-7th/StarRailRes/blob/master/LICENSE)、[StarRailData README](https://github.com/DimbreathBot/TurnBasedGameData/blob/main/README.md)。 | 保持禁用直到厘清 AGPL 对仓库代码的范围、源数据/美术素材权利和可否服务端再发布。不要把 AGPL 仓库代码许可外推成原始游戏数据许可；不下载或保存图片素材。 |
| Bilibili 攻略/开放平台 | 官方用户协议 §5.6(3) 规定自动程序获取平台服务、内容或数据前需明确书面许可。[用户协议](https://www.bilibili.com/blackboard/protocal/licence.html)。Open Platform 文档显示账号授权、公开用户信息、稿件管理和用户授权数据等应用能力；开发者协议把用户数据限制在关联 UP 主明确同意的范围和应用目的内。[Open Platform](https://open.bilibili.com/doc)、[开发者协议](https://open.bilibili.com/agreement/developer-service)。 | 不启用公开攻略搜索/爬虫。只有官方确认具体 API 权限、字段、稿件/转录范围、存储展示、保留期限、频率、用途和托管地域后再评估；仅有 API access 不代表有攻略内容再发布权。 |
| HoYoLAB / 米游社 HSR Wiki | HoYoLAB 官方站链接社区条款和隐私政策；本次动态条款正文无法读取，也未在所查官方材料中找到一般公开搜索/攻略采集的开发 API。单篇 Wiki/社区页面的署名或转载提示应逐页核对。[HoYoLAB](https://www.hoyolab.com/?v=157)、[HoYoverse 隐私政策入口](https://hsr.hoyoverse.com/en-us/company/privacy)。 | 暂作人工 click-through 引用，不镜像攻略/评论。向 HoYoverse 确认可用 API、自动访问、excerpt/缓存和展示条款后才新增 adapter。 |
| Mihomo / Enka 等玩家档案 | 这是 B 的逐档案资料流，不是 A 的公开知识来源；公开 profile 仍含用户相关数据。 | 留在 B/C 授权的本机链路；A RAG 不采集、不索取 UID、不存档案或派生信号。 |

## 交付顺序建议

1. **先冻结范围，不碰来源：** 用 synthetic fixture 定义 `PublicBundleHTTPSSource`、签名目录、撤回/过期验证、兼容性拒绝和双版本本地恢复。协议先补版本化文档，待 A/B/C owner 复核后再改代码。
2. **完成本地服务候选：** 用户选择是否把 A 嵌入桌面本地模式；若是，补 B `KnowledgeBackendController` 与 A readiness health。若选择共享后端，保持进程由主机服务管理器托管，B 不负责启动服务器。
3. **完成公共 RAG 通用路径：** 先用已授权人工证据/合成证据建立 chunk/retrieval/ranking/answer/citation/abstention 管线；用户可先 review 所有输出，再决定是否启用语义检索及任何外部回答模型。
4. **逐来源开放：** 每个来源单独核对条款/许可、接口、覆盖、存储、频率和撤回流程；只有 `allowed` policy 与 dated/verified capability 成对存在才允许 adapter。变更条款则暂停该来源，已发布内容走 disable/撤回和重建 release。
5. **独立生产门：** 配置 production signing/catalog trust、key rotation、TLS、监控备份、部署恢复、B2 host replay、客户端离线策略和真实人工内容审核。未逐项通过前仍是集成候选，不称生产验收。

## 需要用户决定的事项

以下每项都对应上文的具体材料，供后续单独确认：

1. **首批知识语料：** 是否批准“官方 HSR 公告人工校验的小型事实集”为首批来源；Nanoka、StarRailRes、Bilibili、HoYoLAB 继续禁用，直到拿到许可/API 证据？审阅材料：来源表和对应官方/维护者链接。
2. **公开答案执行位置：** 首版是否先只做本地检索与可引用摘要；若启用生成模型，是否允许向指定远程模型发送脱敏后的公共问题与获准公开证据？审阅材料：RAG 输入白名单、保存字段和引用样例。账号字段在所有选项下均不得发送到 A。
3. **分发信任：** 谁保管生产 release signing key、谁保管独立目录/撤回签名 key、key 轮换由谁批准？审阅材料：上述签名目录草案、key-purpose/rotation 流程和 A/B exact compatibility tuple。
4. **新鲜度与离线：** 分发目录有效期、客户端最长离线使用时长、目录不可达时能否继续用上次已验证 release、release 过期或撤回后如何降级？审阅材料：目录字段、缓存两版行为及恢复演练用例。建议默认展示“上次核验时间/在线状态未知”，数值窗口由用户定。
5. **本地还是共享部署：** 第一轮生产候选采用 B 桌面托管的 loopback A，还是已有主机服务管理器托管的 HTTPS A？审阅材料：两个 start/stop/health 责任边界及当前 WSGI/TLS 限制。
6. **Bilibili 权限与托管地区：** 是否排除自动公开搜索，直到取得书面 API/内容许可并明确用户数据托管地域？审阅材料：官方用户协议 §5.6(3)、Open Platform 能力目录与开发者协议。

## 依据与仓库锚点

- A 实现核查基于当前 A `codex/mvp-knowledge-backend` 提交 `0e8a6f7`，重点文件：`packages/starhelp-knowledge/src/starhelp_knowledge/http.py`、`cli.py`、`distribution.py`、`sources.py`、`service.py`、`migrations/001_initial.sql`。
- B/C 实现状态以只读仓库核对及 S3 固定证明为准：A producer `dcb1e3e…`、artifact `4610573…`；C source `f627590468154cc8622dad8647fefe9f6fd3c4ee`、wheel SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`；B1 source `103741e02c90ac672017f783058bdd8dacae982e`。星铁协调仓库中的 `docs/operations/S3产物锁定-2026-10-21.json` 仍显示 B2 host final gate 与生产验收未通过。
- 来源网页与仓库页面均于 2026-10-21 检查；上表的链接是来源材料，不代表授权或法律意见。页面可变，启用 collector 前需重新核对当前条款并保存对应版本/日期及授权证据。
