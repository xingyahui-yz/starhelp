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
