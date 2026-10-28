# S4.1 A→B 分发与本地服务接口评审

**评审基线：** A `codex/mvp-knowledge-backend`，commit `ed0028c7e3a3ce00929cf7ae3db939cb137ced06`；提案 `production-integration-proposal-v0.1-draft.md`，blob `b6e09bdbfc2ea770bbcdb17940ea11ae0111a2fb`。提案标注为讨论稿，不冻结接口。

**结论：** 接受提案确定的两阶段 MVP 顺序：第一阶段由 B 管理同一 Windows 用户下的 loopback A 进程；第二阶段 A 由共享主机服务管理器托管，B 只连接配置好的 HTTPS 服务。S3 格式、B1 snapshot profile 和现有固定产物不变。开始生产实现前，A/B/C 需冻结独立的分发目录/撤回协议、兼容 tuple 与 readiness 语义。本文件仅为 B 侧接口评审，不实现 HTTP、目录签名或进程控制。

## B 现状对照

`src/starhelp_desktop/bundles.py` 当前提供：

- `PublicBundleSource.discover_release(current_release_id) -> str | None` 和 `fetch_release(release_id) -> object`。它没有目录响应、签名元数据或有类型的 HTTP 错误；无法表达 A 提案中的序号、签发/到期时间、撤回目录、digest/ETag 或服务端 profile tuple。
- `PublicBundleSynchronizer.sync(source)` 发现一个 release 后取回内容，使用固定的 `SignatureVerifier`、支持能力集合和 `BundleValidator` 验证，再调用 `PublicBundleCache.activate()`。`BundleSyncResult` 只有旧/新 release ID 与 `updated`；它不能向 UI 传达目录序号、在线撤回状态、过期状态或“状态未知”。
- `Ed25519Keyring` 仅按 `key_id` 取得原始公钥并验证 manifest 签名；接口没有签名用途、目录签名、信任版本或密钥轮换状态。`build_producer_analysis_request()` 的 `distribution_trust_purpose` 是显式传给 C 的用途字段，不能替代 B 对在线目录签名用途的校验。
- `ValidatedBundle` 保存 release、schema、原始 bundle bytes、coverage 与本次 `verified_at`。缓存最多保留两个 release；本地验证 receipt 绑定 payload SHA-256，但 receipt 未签名，不能证明远端撤回状态或 freshness。manifest 的 `valid_until` 等字段目前只用于展示，不形成启用/拒绝策略。
- `activate()` 可原子替换 current 指针，但没有 `rollback(target_release_id)`。`load_release()` 会重验签名和依赖闭包，却不检查在线撤回、目录有效期或精确的 A/B/C 兼容 tuple。因此“保留两份缓存”不能单独作为允许回滚的规则。

当前没有 `PublicBundleHTTPSSource` 或 `KnowledgeBackendController`。GUI 设置页已明确显示本地服务生命周期与邀请维护未接入。C worker 是按请求启动、经 stdio 调用的一次性本地进程，不应承担 A 的服务管理职责。

## 冻结协议的最小字段与错误

先定义独立版本的 signed distribution catalog；不要把目录字段塞进 S3 envelope，也不要改变 B1 snapshot。

| 对象 | 最小字段 |
|---|---|
| Catalog header | `schema_id`、`schema_version`、authority/service ID、严格递增 `sequence`、`issued_at`、`valid_until`、签名用途、`signing_key_id`、签名算法、签名。签名覆盖 canonical bytes 和固定 domain；验证规则要明确 duplicate key、canonicalization、UTC 时间与最大正文尺寸。 |
| Compatibility tuple | A producer package/version/commit、B envelope/distribution profile、C producer adapter profile 与 wheel SHA-256、B snapshot profile、必需 capability 集合。所有值精确匹配已批准白名单；仅同 schema/version 字符串不算兼容。 |
| Release descriptor | `release_id`、不可变内容 SHA-256、内容长度上限、受限下载标识、`published_at`、tuple/capabilities。下载标识应是服务内相对 ID 或受 allowlist 约束的 URL；禁止目录内容引导访问任意主机。 |
| Withdrawal record | `release_id` 和/或内容 SHA-256、撤回状态/原因码、`effective_at`、声明时间。撤回记录与最新 sequence 一起签名；规则说明全局撤回是否覆盖缓存、离线时如何显示，以及撤回后是否允许任何回滚。 |
| Health readiness | 独立 `/health/ready`，返回服务版本、schema/migration 状态、active release、catalog 是否可读及结果状态；不得返回密钥、UID、档案或其他用户数据。现有 `/health` 保持 liveness，不再被解释为业务就绪。 |

协议需定义的有类型失败至少包括：目录签名/用途无效、过期目录、序号回退或同序号不同摘要、release 已撤回、tuple/capability 不支持、摘要/长度不符、重定向或主机越界、超时、404/410、ETag/304、无网络和本地缓存损坏。UI 应区分“最后已验证目录仍有效”“在线撤回状态未知”“目录已过期，不能确认当前有效”等情况，不把网络失败映射成“无更新”或“未撤回”。TTL 与最长离线使用窗口由实现先给可审阅默认值和失败行为，再按运维策略冻结；配置值不能来自未签名 bundle。

## 两阶段边界

**第一阶段：本机 loopback。** B controller 只启动明确配置/随包批准的 A executable 和固定参数，不经 shell，不接受任意用户拼接命令；服务必须绑定 loopback。controller 持有自己启动的 process handle，并以 PID 加进程创建时间核对所有权，不能按端口或 PID 杀掉其他进程。`start()` 等待带版本/schema/active release 信息的 readiness，遇到端口冲突、错误版本、migration 未就绪、超时或子进程提前退出时失败关闭并清理自己创建的进程。`health()` 只报告非敏感运行状态。`stop(grace_seconds)` 只停止本 controller 拥有的进程，先走正常关闭、超时后终止并回收；应用退出和取消也需清理。管理操作显式可见，不能因下载失败而启动未配置服务。

**第二阶段：共享 HTTPS。** 主机服务管理器负责启动、停止、健康探测、部署和 TLS；桌面端不拥有、不停止共享 A 进程。B 使用固定 HTTPS origin 与只读请求身份，只发送公开查询/同步字段，不带 UID、档案、账号快照、Cookie 或玩家推导条件。只允许同源请求，不跟随跨 host 重定向；HTTPS 故障时显示离线/撤回状态未知，不回退到本机服务或其他网络目的地。controller 生命周期接口与 `PublicBundleHTTPSSource` 应分层，避免桌面端在两个阶段共享错误的进程所有权假设。

## 建议的实施拆分与验收

1. **协议冻结：** A/B/C 对目录 canonicalization、签名用途/信任更新、tuple 白名单、序号/撤回语义、错误码、ETag 与 TTL/离线策略达成版本化提案；固定 S3 bytes 不变。
2. **A 分发：** A 提供 signed catalog、按 descriptor 下载完全相同的 immutable envelope bytes、撤回目录与 readiness；线上不持有 release 私钥。A 为同一组 S3 fixture 固定目录/响应摘要和撤回/过期/错误样例。
3. **B HTTPS source/cache：** 先验目录签名、用途、序号、有效期和 tuple，再按受限标识下载；校验状态码/重定向/尺寸/ETag/digest，最后复用现有 `BundleValidator` 对 envelope 验签、release、能力与依赖闭包。扩展同步结果为可持久显示的 freshness/withdrawal 状态；离线读取只重验缓存字节，不能臆测最新撤回状态。
4. **B 原子恢复：** 新增显式 `rollback(target)`：只可恢复本地完整重验、兼容、未过期且未撤回的另一 release；先验证目标和目录状态，再原子更新 current 指针；失败时原 current 保持不变。对损坏指针、写入中断、撤回后回滚、版本淘汰给出可重复的 synthetic 测试。
5. **本地 controller：** 单独实现固定命令、loopback 检查、ready 等待、进程所有权、优雅停止/超时清理、退出/撤权处理；测试不得启动真实 A 服务或连接公网。端口冲突时确认 controller 不会终止外部进程。
6. **阶段验收：** 第一阶段验收 Windows 安装包启动/升级/关闭、loopback 绑定与 A readiness；第二阶段以 HTTPS mock 验收 host allowlist、只读身份、无敏感字段、重定向拒绝与目录撤回。每阶段分别记录服务状态、缓存 release 和 freshness，生产信任、真实 TLS/部署与签名仍单列 gate。

最小 synthetic 交叉用例包含：有效新版本更新；相同 catalog/ETag 不更新；错误签名或用途拒绝；过期/回退/同序号分叉拒绝；未知 tuple/capability 拒绝；digest/长度不符、redirect 与跨 host 拒绝；已撤回 current 不进入分析且不能 rollback；目录离线时显示未知并遵守过期策略；cache corruption/failure atomicity 保持旧 current；controller 子进程未 ready、版本不符、意外退出、端口冲突、优雅停止与强制停止；第二阶段不触碰本地进程。

**交接边界：** 本评审是 B 对 A 提案的技术输入，未冻结目录 wire schema、离线窗口或 production trust；未改代码、契约、A/C 文件、S3 fixtures、B1 serializer 或已生成候选。获得协调方冻结的新修订后，再按上列拆分实现并重新生成候选。

## A 候选协议逐项复核（2026-10-28）

**复核基线：** A 本地 checkout commit `243a9e04a243124a75d76efc4a20edb989c8eaec`，文件
`packages/starhelp-knowledge/docs/public-distribution-local-service-contract-candidate-v0.1.md`。
此 commit 在本地 A checkout 可读，但当前 GitHub A branch head 仍是 `ed0028c`；候选还不是
已发布/冻结的共同接口。以下只是 B owner 的逐项意见。

| 候选内容 | B 意见 | 最小补充/边界 |
|---|---|---|
| 两阶段拓扑与职责 | 同意。Phase 1 由 B controller 管 loopback A；Phase 2 由 host manager 管 A、B 只连 HTTPS。C one-shot worker 不承担 A 生命周期。 | 明确 controller、HTTPS source 分层；HTTP 故障不触发本机/其他 origin 自动回退。 |
| catalog/revocation 签名外壳、canonicalization、profile/purpose、严格 JSON | 同意。B 当前 `Ed25519Keyring` 只有 key ID → 公钥映射，不支持按 profile/purpose 授权新目录或撤回签名。 | 冻结 trust config 如何把 `(origin_id, profile, purpose, key_id)` 绑定，以及 key rotation/旧 key 有效范围。Catalog、revocation 和 bundle 三个签名用途必须分别校验；不能拿 bundle 验签成功代替目录信任。 |
| catalog 字段及 exact A/B/C tuple | 同意。候选的完整 commit、package version、envelope/profile、C wheel hash、B snapshot producer tuple、能力集合比 B 现有 `PublicBundleSource`/`BundleSyncResult` 丰富且必要。 | 所有 tuple 都由 B 本地 allowlist 决策；目录不能授权一个新 producer。B2 snapshot producer commit 的冻结值须等协调最终证明，不能将候选表中的 S3/B1 锚点自动改写为 B2。 |
| release descriptor、固定相对下载路径、raw `size_bytes`/SHA-256 与 ETag | 同意。ETag 只作优化，B 仍需原始响应长度、digest、envelope 签名及成员闭包验证；现有 64 MiB 上限可沿用。 | A 必须把同一 release 的 envelope bytes 作为不可变制品保存/返回。目录引用 digest 必须覆盖传输的原始 bytes，不能对下载后的重新序列化 JSON 求 hash。 |
| revocation snapshot、release/object exact identity 及 C `withdrawn_public_refs` mapping | 同意分离撤回快照并签名；撤回 identity 用 release+digest 或对象 kind/id/revision/content hash，不能模糊匹配。 | C/B 当前 validity 输入的精确形状与候选 `kind/id/revision/content_hash` 尚需实值对照；映射不闭合或 C 不支持时不得丢弃撤回项并继续给出有效报告，应返回兼容错误/禁用结果，另行版本化接口。 |
| 校验先后顺序与失败行为 | 大体同意：配置 origin → 验 catalog → 验其引用的撤回快照 → 检查 tuple/revocation → 下载并校验 raw bytes → 现有 envelope/member 验证 → 原子激活。 | 必须把签名安全状态持久化从 artifact 激活事务中拆出，见下节；candidate 当前第 4 节步骤 7 的“任何失败均保持 high-water 不变”与先前已接受的签名目录/撤回事实冲突。 |
| sequence 重放、有效期、离线态与 error taxonomy | 同意逐 `(origin, channel, consumer_profile)` 维护 catalog/revocation 两条单调 high-water；lower 拒绝、same sequence/same raw digest 幂等、same sequence/different raw digest 冲突；过期与离线状态必须可见。 | 对 24h TTL、启动/6h 刷新、72h 离线宽限、5m clock skew、重试/timeout 等均先作为候选策略讨论，不把建议值写成已确认生产策略。catalog 已可读但 revocation endpoint 失败，应单独定义 partial/unknown 状态，不能把 HTTP 200 的 catalog 视作撤回核验成功。 |
| 双版本 cache、显式 rollback、readiness/controller | 同意候选边界；rollback 需来自当前有效签名 catalog 的 allowed 目标，重新验证 tuple、时间和撤回；readiness 区分 liveness 与迁移/目录就绪。 | Durable safety checkpoint 不属于两个 artifact slots，也不随 slot 淘汰、档案撤权或普通 app upgrade 清除。checkpoint 缺失/损坏时须标未知并在线重新取证；旧 cache 不能单独证明最新撤回状态。readiness 的 null active-release 策略仍待 A owner 说明。 |
| RAG-1…RAG-6、候选来源和后续真实启用 | 对 B S4.1 transport 本轮无异议。 | RAG 在 A 负责；B 只消费批准的公共 bundle/证据。不得因此把账号字段、UID 或玩家推导条件放入 catalog、RAG question 或 source request。 |

### 必须拆开的 durable safety state 与 artifact activation

A 候选第 4 节目前要求“所有检查成功后”一起原子写 cache/current pointer，并称失败时 current release、high-water 与文件都不变。该事务边界会丢失已经验证到的新撤回：例如 B 已验出更高 sequence 的撤回快照，发现当前包已撤回，但随后新 active artifact 下载、hash 或 envelope 验证失败；如果此时整体回滚，B 重启后仍持旧撤回 high-water，旧 catalog/未撤回缓存可能重新进入可用判定。

建议 A 在下一修订中把流程拆为三个不可倒退的状态变化：

1. **Authenticated catalog checkpoint：** catalog 签名、scope、profile、sequence、时间和 raw digest 验证通过后，先单独、耐崩溃地持久化 `(origin, channel, consumer_profile, sequence, raw_sha256)`。即使撤回下载或 artifact 下载失败，也不能接受更低 catalog sequence。若 catalog 高水位已推进但其撤回快照尚未验证，状态明确为 `revocation_unknown`，不声称本轮安全核验完成。
2. **Verified safety checkpoint：** 只有撤回快照与 catalog 引用的 raw digest/size/sequence 完全匹配，且自身签名、scope、有效期及撤回项验证通过后，持久化独立 revocation high-water/raw digest、撤回集合及最近完整安全核验时间。先写这个 checkpoint，再开始 artifact 下载。之后任何 artifact 失败都不得回滚或删除它；若它撤回当前缓存 release，当前指针文件可留作取证，但分析入口必须立即判为 revoked。
3. **Artifact activation transaction：** 临时文件完整通过字节摘要、envelope 签名、exact tuple、成员/依赖闭包后，才原子加入双槽缓存并更新 artifact pointer。此失败只回滚候选临时文件/候选槽，不回滚上述两类 safety checkpoint。分开记录 authenticated catalog 的 `active_release_id` 与本地 `installed/current release_id`，防止把旧缓存显示成服务当前活动版本。

Catalog high-water 与 revocation high-water 是两个独立维度。Catalog 已验签但撤回端点断网/缺失/签名错误时，catalog replay 水位仍推进；撤回 high-water 保持最后完整验证值，并将服务端撤回状态标为 unknown/partial。对旧缓存能否暂时使用需按“真断网 offline grace”和“收到不可信/不完整安全响应”分别冻结；后者不得被伪装成一次成功 freshness 更新。缓存中已知有效、未撤回的旧包是否可以 stale 使用，也不能仅由“旧 current pointer 尚在”决定。

同 sequence 的 raw bytes 规则应进一步明确为 immutable-bytes invariant：相同 sequence + 相同原始 SHA-256 为幂等重放；相同 sequence + 不同原始 SHA-256 一律冲突，即使解析后的 JSON 语义相同。A 必须固定保存并原样返回 catalog 与 revocation envelope bytes，不能每次重新序列化改变空白/键序/封装；B 应把每条 high-water 的 raw digest 与独立 checkpoint 一起耐崩溃提交。checkpoint 丢失、损坏、重装或从旧备份恢复时，B 只能显示 unknown/expired 并在线重获当前签名状态，不能用旧 artifact 或本机时间自证“没有更新”。

此差异是实现前的安全语义修订，不要求改变 S3/B1。当前 B review 中的两阶段拓扑、严格 tuple/原始 hash、双版本缓存、显式 rollback 和 readiness 结论继续成立；**当前 B 不实现候选 wire 或 controller**，等待 A 修订并由 A/B/C 对同一修订 hash 共同确认。候选开头列的 C “77 checks”也早于已发布 C `fa512b6` report（83 passed / 0 failed），应在 A 后续修订中改引用或标为历史，不能用旧数覆盖最新 packaged evidence。
