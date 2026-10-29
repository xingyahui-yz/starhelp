# C 生产消费与兼容评审提案 v0.1

评审日期：2026-10-28。状态：**S4.1 技术评审稿，未实施、未冻结、未启用生产**。

评审对象：A `docs/production-integration-proposal-v0.1-draft.md`，Git 提交 `ed0028c7e3a3ce00929cf7ae3db939cb137ced06`，原始 SHA-256 `7265550d39a41c72b8ee662b72ec941bd2e24ebeaaf4dccec99b065034b35ac9`；工作区文件与该 Git blob 完全相同。该文的 77 项 C 检查是过程记录；最终 S3 C 证据已收口到 `fa512b6a874bba71bb52d59f610e4911d2cb22b9`：新 A 集合 83 项检查/62 次 source+packaged 用例执行，独立旧 A 测量集合 37/30，实际运行日期仍为 2026-10-21。

本次只核对该提案与现有 A/B/C 消费边界。来源许可、真实游戏 ID、生产服务可用性没有因本次文档评审获得证明。C 0.4.0 wheel、源代码、共享契约、S3 原始产物及锁均保持原样；本文中的候选名称不构成已支持的接口。

## 1. 评审结论

1. 同意把签名目录/撤回协议与不可变 envelope 分开版本化；目录不能使未登记的 producer、谓词、单位或 snapshot 自动获得兼容资格。
2. A 提议沿用 envelope v1 和 C native v0.2，须满足“原签名材料及执行语义不变”。新增签名域/用途、语义字段或原语的方案，必须明确采用新 profile/capability，不能给旧包加标签。
3. C 生产消费必须经**新组件版本、显式生产信任用途、受信配置来源和精确 producer tuple**交付；不能只把请求中的 purpose 字符串换掉，也不能把测试 key 改名当生产 key。
4. B 负责下载、目录/时序/缓存与授权生命周期；C 保持无网络、无持久状态，复核原包签名和可执行语义。B 的 `verified: true` 不能替代 C 验签。
5. 当前 B 快照不足以证明独立单位/语境、完整材料或最终面板。下一代本机 snapshot/request 须独立版本化，先确认最小语义与测试，不在本稿设计完整字段实现。
6. 先 Windows 本机验收、再邀请制共享，以及公开 RAG 均为已确认 MVP 范围。某个 collector 尚未获准不阻塞通用公开检索/证据回答；私有账号与派生信息始终只在 B/C 本机链路。

## 2. 当前 0.4.0 的事实边界

运行源码来自 `f627590468154cc8622dad8647fefe9f6fd3c4ee`；wheel SHA-256 为 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`。

| 边界 | 当前实现事实 | 不能据此宣称 |
|---|---|---|
| 签名用途 | `signature.py` 只接受 `distribution_trust.purpose == synthetic-test`；以调用方传入的 keyring 数学验证 canonical manifest 的 Ed25519 签名；输出 `production_trust_established=false` | 已支持生产用途、已认证实际密钥运维人或真实内容审核者 |
| 用途绑定 | purpose 是本机信任输入的门限，不是独立加入当前签名输入的域分离前缀 | 任意更名后的 purpose/key ID 已有密码学用途隔离 |
| A 兼容 | 明确登记 b790a52/00d4a58 → package 0.2.0、dcb1e3e → 0.3.0；envelope profile 为 `starhelp.b-publicbundle-envelope.v1` | 同 schema 的任意 A commit、文档提交或未来生产发布自动受支持 |
| B 兼容 | 045965b/旧 profile 与 103741e/interop-min profile 是两个固定 tuple；B2 c248daa 是经源码指纹证明的 host，不冒充 serializer | 结构相似即可换 producer 标签，或 source_confirmed 自动等于可靠实例 |
| 目录/撤回 | C 使用调用方给出的 `withdrawn_public_refs`，检查静态禁用状态和依赖传播；结果保留 supplied checked_at/online 状态 | C 已验证在线目录签名、最新序号、全局最新撤回、目录 TTL 或安全时钟 |
| 数据质量 | B 规范化后 roster/inventory 为 partial、materials 为 unknown；scope 字符串只是 provenance；缺单位/面板语境的统计字段保持 unknown | 确认一个数值即已达标，空培养 aggregate 即材料正向覆盖 |
| 准备结果 | `prepare_producer_request.status=ready` 表示建立了消费视图；native analysis 另有领域状态 | 整体任务可行、包在线有效或已通过生产验收 |

现有内部消费视图 hash 与 A 原始 transport/member/release hash 分层保存。内部归一化重新计算的摘要不赋予原包信任、批准或新鲜度。

## 3. 生产支持的版本与信任提案

以下为待 A/B/C 确认的交付方式，不注册实际版本或 key。

### 3.1 新组件与兼容登记

- 生产支持发布新 C 组件及固定 wheel/source/hash；0.4.0 和 S3 历史回归保持不变。候选组件号例如 0.5.0、候选生产 adapter profile 例如 `starhelp.producers.production.v1`，均需协议复核后确定，当前代码不接受这些名称。
- 生产 adapter 显式登记：A **实际执行源码 commit + package version + envelope profile + native schema/profile/capabilities**，以及 B **实际 serializer/encoder commit + snapshot profile**；B host 和 C wheel 单列。签名目录只声明候选 tuple，不能自行扩展 C 白名单。
- 原生有限算子、主体、三态、条件单位/语境、资源规则完全不变时，可评审保留 native v0.2。新增执行语义或无法等价表达的事实须新 native profile/capability；不能通过新增可选键隐式开启。
- envelope v1 若字节/签名规则完全不变，可在新生产 adapter 下评审复用，同时严格隔离 release key 的生产用途。若给签名加入新的域、purpose 字段或更改 canonicalization，则应采用明确的新 envelope profile/capability，并由 A/B/C 各自实现、固定样例回放。HTTP 目录有独立版本，不等于 envelope 版本。

### 3.2 用途与信任来源

- 建议区分 release 与 catalog 的信任用途；候选用途名 `production-release`、`production-catalog` 仅为讨论标签。测试 key 的实际公钥指纹必须被生产策略拒绝，不能仅检查 key ID 名称。
- 生产信任锚由受控本机配置/安装更新路径明确配置和审计。B 读取并解析该配置，worker 从受信 host 边界向纯内存 C 注入不可变策略；普通请求不能凭自带公钥、purpose 或 verified 布尔值建立自己的生产信任。
- C 可以复核策略允许的 key ID/指纹/用途、算法、签名和 producer 绑定；其信任依据应准确写为“配置的生产 release 锚”，不声称 C 认证了配置发布者或独立证明某个人完成审核。配置的认证、更新与落盘由 B/安装运维承担。
- 单 key 加经评审的密码学域分离、两把独立用途 key，均可进入技术复核。前者须在签名材料中绑定对象类型/协议版本/用途并拒绝跨域；后者仍须严格检查对象类型和各自 key 用途。**本稿不预设必须两把 key**。
- 轮换、撤销/恢复信任锚、旧 key 的有效期与旧缓存处理，由 A/B 给出可审阅策略。目录不能凭自己携带的新公钥自举信任。历史签名仍数学有效，不代表已撤销 key 下的内容仍可执行。

## 4. B 与 C 的验证责任

| 步骤 | A/B 责任 | C 责任与限制 |
|---|---|---|
| 产物生成 | A 对精确公开修订独立审核/发布，受控签名作业产出不可变原始 envelope 与目录 | 验证导出 provenance/内容绑定；不添加批准标记或替 A 审核真实内容 |
| 在线获取 | B 选择固定服务身份/host，处理 TLS、允许的重定向、下载与解压限制、ETag，保留原始字节；304 不是新撤回证明 | 不访问 HTTP、不管理 A 服务，不由本地分析结果驱动账号派生的公开查询 |
| 目录/时序 | B 验签名、用途、schema、序号及有效期；按来源/环境/策略保存已接受序号和可信时间依据；处理撤回与离线规则 | 不持久保存序号或自称知道在线最新状态。若 C 要独立验证目录，应在新版本接收有界原始签名目录与受信上下文，复核其签名和 release/digest 绑定；仅传 B 状态摘要时必须标明是 B 声明 |
| envelope | B 在缓存激活前校验目录 digest、签名、精确 release、兼容 tuple、成员与完整性，失败不覆盖当前有效缓存 | 仍对同一原始 envelope 验 release 用途签名、字节 hash、成员/依赖/原生投影和有限语义；不信任缓存目录名、已验证布尔值或内部归一化 hash |
| 本机任务 | B 提供用户当前授权的快照、任务与可信策略上下文，提交前/接收后检查生命周期 | 纯内存执行；保持 unknown、硬限制、完整审核变体和原始来源，不自动补全单位/拥有/材料/面板 |
| 结果与报告 | B 校验 request/revision/generation；显式保存报告，更新/撤回后标时效；撤权拒收迟到结果并清理关联私有资料 | 保持 adapter 错误、native 领域错误和可行性状态分层；策略/公共依据版本需通过新版本明确绑定，不把不兼容当无可行队伍 |

A 提案中“HTTP source 不带 bearer token”与第二阶段的**邀请制、默认只读服务身份**需要 A/B 澄清：本机 loopback 读取与共享服务的认证策略可以不同；共享阶段应明确专用只读服务凭据的允许位置、目标、权限与保管方式。它不是游戏 UID/Cookie/token，且不应进入 C 请求、普通日志或模型输入。不能由该句推导为取消已确认的邀请制，也不能把游戏凭据用于 A 服务认证。

## 5. 新鲜度、撤回和离线的准确含义

目录签发/到期、目录是否为已知最新、内容自身适用周期/新鲜度、签名 key 状态、私有字段观测时间是不同维度。B 的本地验证时间回执和 C 的 supplied checked_at 都不是新的签名目录。

| 状态 | 建议行为（待 A/B 固定具体策略） | 不可夸大的结论 |
|---|---|---|
| 目录和包有效，范围/策略均匹配 | 允许受支持的本机分析；展示目录序号、核验时间、release 与数据覆盖 | 不因下载成功或签名有效就宣称真实攻略/账号字段当前完整 |
| 已知撤回或 key/包失效 | 禁止相关内容形成新的可用方案；依赖传播，历史报告明确失效；禁止回滚至该包 | 离线、两份缓存或旧签名不能解除已知撤回 |
| 网络不可达，缓存仍在明确离线窗口内 | 只有预先约定策略允许时才可限定使用，并标上次已知状态和“最新撤回未知” | 计算结果不证明在线可用性或当前未撤回 |
| 超出窗口、可信时间不足、目录倒退/缺失 | 明确阻止或降级生产执行，保留可安全显示的公共资料/缺口 | 不把未知解释为安全、不默认为永不过期，不把网络错误转为 no_feasible_variant |
| 新包验证失败，旧包仍符合独立策略 | 可保留旧当前指针并显示更新失败；回滚须显式检查目标资格 | 保留旧文件本身不证明它未撤回、未过期或适用当前周期 |

具体 TTL、最长离线时间、时钟回退容忍、目录跨环境序号规则及 key 撤销传播窗口，须先由 A/B 给出实现和运维建议，再按需要确认具体运行值；本稿不猜数值。C 0.4.0 没有目录 TTL/序号验证器，不能把上述建议套成已实现保证。

## 6. 下一代 B 本机 snapshot/request 的最小语义清单

当前固定快照为十键、FieldFact 为七键闭合形状。把新事实塞入 scope 字符串、额外可选键或 coverage 路径集合，不能获得兼容。B 定义新 schema/profile 和实际 serializer/encoder 版本，A/C 确认语义、能力与原始字节样例后，C 才通过新组件明确接入。以下是必须表达的事实，不规定完整字段名或猜测真实游戏值。

| 最小范围 | B 必须明确 | A/C 接受条件 |
|---|---|---|
| 独立单位与测量语境 | 类型、单位标识、测量阶段、buff/假设、主体、观测/确认时间、来源及冲突/过期状态独立表达 | 对齐 A 同版本属性定义；无隐式单位换算，布尔不当数值；不从字符串 scope 或 confirmed 数值推导语境 |
| 三模式记录 | 模式/周期/关卡/修订、成绩/奖励的含义与单位、实际覆盖及来源时间；未观察与未取得分开 | 公共 ID/适用性由 A 已验证映射提供，B 本机展示/选择；不推断全历史、不补零，不把成绩变为通关概率 |
| 材料和完整性 | 材料身份、数量/单位、确认状态与时间、覆盖范围及完整性依据；部分读取不宣称完整仓库 | A 提供适用且经审核的成本表/修订；C 只有目标、进度、材料及覆盖均适用完整时才计算净缺口，跨四类培养汇总后只扣库存一次；缺项保留 unknown/not_calculated |
| 最终配装面板 | 角色、精确最终实例分配、明确指纹规范/版本、测量语境和确认来源；区分当前与模拟/最终面板 | 与 C 实际最终映射逐项绑定；旧面板不复用为换装后面板，歧义实例不自动取得可靠身份；缺失只能降级 |
| 本机反馈 | 当前任务的实际队伍、成绩/失败现象、字段状态/单位/语境和来源；任务绑定与授权生命周期 | 宜作为版本化本机 request 的伴随对象，不必强塞进长期 snapshot；仅使用已审核排障规则，不自动学习/改公共模板，主动保存报告前不自动留存，不发送 A/RAG |

新版本仍须保留 profile/snapshot/revision/generation 关联、未变更字段的原来源/时间、部分更新和冲突处理、本地 UUID 实例身份及锁。新角色记录不顺带确认拥有，新导入事实不顺带确认装备身份。增加模式/材料/反馈表示不自动扩展 A 的条件算子、主体或 C 的执行能力。

## 7. 需 A/B 明确的字段、错误与验收计划

此表是**未执行的后续验收计划**；不增加当前测试计数或开启实现任务。具体新字段和错误枚举在版本确定后冻结。

| 待定项 | 责任 | 必须交付/验证 |
|---|---|---|
| 目录签名协议 | A 提供、B/C 复核 | schema、原始签名字节/域/算法、用途、key ID/指纹、序号作用域、issued/valid 时间、release/digest/tuple/capability、撤回目标是 release/hash 还是对象修订；缺项和未知必需能力拒绝 |
| 信任配置与轮换 | A/B 运维、C 消费复核 | 配置来源和认证、用途隔离、轮换/撤销/恢复及旧缓存规则；用测试 key 或其别名冒充生产、错误用途/域、未知或已撤销 key 均拒绝；新生产 profile 不使旧 0.4.0 默许接受 |
| 网络与身份 | A/B | loopback controller/readiness 与共享 HTTPS 的边界；邀请制只读凭据；重定向/host、压缩/大小、304、超时和错误分层；不将服务凭据或账号数据交给 C/RAG |
| 时序与离线 | A/B 持久状态、C 有界复核 | 目录回放/倒退、跨环境序号、过期/时钟异常、撤回后离线/回滚、旧缓存资格；禁止把网络不可达记成已确认未撤回 |
| 跨层绑定 | A/B/C | 目录 digest 与下载原始字节不符、A producer/package 不符、schema/profile/capability 不符、签名通过但成员/依赖/投影损坏；记录实际触达层，digest 失败不算已测到依赖失败 |
| 大小与计算预算 | A/B/C | A 下载/B 缓存上限与 B stdio 整体 UTF-8 8 MiB 请求/16 MiB 响应、C 单 raw_json 8,000,000 字符/100k 节点/深度48 分开；重复与转义字节计入，测试多字节/边界/超限及超时，不只比较未编码包大小 |
| 新本机事实 | B 产样、A 定义公共语义、C 评审 | 各最小范围的完整正例、缺值/冲突/过期/错误单位/语境反例；部分覆盖不得算净缺口；当前/最终面板不等价；反馈不支持规则时说明无法判断 |
| 错误与报告 | B/C | 传输不可用、trust/adapter 不兼容、native 领域错误和 no-template/confirmation_required 分层；request/revision/generation 全路径绑定，拒绝已有矛盾值，撤权拒收迟到结果，生产策略/依据版本在新结果中明确关联 |

现有 code（如 signature_trust_unavailable、invalid_signature、producer_digest_mismatch、unsupported_producer_version、withdrawn_public_object）只按当前所属层解释。新的目录过期、回放或生产 key-policy 错误需 A/B/C 确认枚举，不借旧无可行状态隐藏这些错误。

## 8. 后续交付界面与公开 RAG

A 提供版本化目录/envelope 与明确原始字节、签名/撤回/许可/公共 ID 依据；B 提供受信配置注入、网络/缓存/授权/报告与下一代本机事实样例；C 在协议复核后形成新组件的兼容表和精确运行验收集合。随后才安排对应有限实现，不由本文批准实际 key 配置、真实 collector、部署或账号读取。

公开 RAG 的通用检索/证据回答属于 MVP。C 可消费的个性化方案仍只能来自已发布完整审核模板/变体/排障；临时检索片段或模型回答不能替代该发布链。不得把 C 的未知字段、持有/锁定/成绩/缺口、匹配分或用户反馈发送给 A/远程模型来补事实。服务只处理明确公开的问题和 scope，具体 provider/目的地/费用方案由相应 owner 交付审阅后确定。

## 9. A 逐字段候选的具体复核

新增评审对象：A `docs/public-distribution-local-service-contract-candidate-v0.1.md`。先核对 `243a9e04a243124a75d76efc4a20edb989c8eaec` 的原始 SHA `8ece54502ee4fa5730fe21a7fbda0c1569072e0c6efbbb57433ac6f72577711c`；随后已读取修订提交 **`012d69508588b0800053108ef38c4bc753bebc14`** 的完整候选及两版 diff，修订版原始 SHA 为 **`88071e56a4b49c3d3cf6dda89aca912559a353139d74e4f81b9f548af7ff989b`**，与当次工作区字节相同。以下意见针对该修订 hash，不把后续同名文件自动视为同一版本。

**已解决：** 修订 §4 将认证目录 pending、已验证撤回提交/立即 gate、artifact 激活分开；artifact 404/损坏不能回滚已知撤回；journal/flush/恢复不明时阻止开放缓存；同 sequence 原始 bytes 不变，重签/改时间/重序列化必须升序号。赞成这些修订。它们是未来 B 的安全状态要求，不是 C 0.4.0 新能力。

**当前结论：有条件认可候选方向，尚不确认该 hash 为 C 可直接实施的生产消费契约。** 冻结前需明确下列 P1—P4；其余为后续版本/验收应固定的细则，不要求本轮生成新 wheel、实际生产 commit/key 或完整实现。

### 9.1 逐字段意见

| 候选字段/段落 | C 意见及必要约束 |
|---|---|
| 外层 `profile`、`signature.algorithm/key_id/value`、签名输入 | 认可 catalog 与 revocation 两个明确 profile 域；它们与现有 release manifest 签名的输入/形状不同，不能直接复用 C 0.4.0 的 release verifier 来“验证目录”。key ID 须绑定配置中的允许用途/指纹；跨用途重放和测试 key 别名必须拒绝。A/B 需给 canonical 原始签名测试向量，覆盖 Unicode、重复键、数值/非法 UTF-8；不是泛称 RFC 8785。 |
| `origin_id`、`channel`、`consumer_profile` | 应逐字绑定本机配置和请求上下文；目录不得更换 host 或自建信任域。`consumer_profile` 对应 native profile，不等于 `planner.producer_profile`。B 不把账号/锁定/缺口派生为这些公开请求参数。 |
| `sequence`、`issued_at`、`valid_until` | catalog/revocation 独立高水位和 raw digest 的规则认可；所有 integer（也包括 size/revision）排除 bool，必须有边界。相同序号/原始 bytes 的重复读取不能用来延长签名时间或离线期限。当前 C 不持久保存高水位。 |
| `active_release_id`、`distributions[].rollback_allowed` | 活动项唯一、自动同步只选 signed active 的边界认可。修订 §4 第6步“改用另一个缓存目标”须与 §7 的用户显式回滚保持一致：optional rollback 条目存在不授权自动切换。已撤回 active 且无已授权合格目标时应无 active，不能自动放宽。 |
| `release_id`、`download_path`、`envelope_sha256`、`size_bytes` | 认可 exact 原始 representation bytes、长度与不可变下载路径；digest 不取 JSON 重序列化值。生产中同一 release identity 不能因换 producer/重签/换行而原位换 raw hash；需要明确的新发布 identity。64 MiB 是下载/存储边界，不是可分析保证，见 P4。 |
| `envelope_profile`、`a_producer.package/version/commit` | 包名、实际执行源码、版本和 profile 共同登记；不能用 artifact/doc commit 替代 producer commit。`starhelp-knowledge` 包名与 wire 的 `starhelp_knowledge` producer 名须由明确映射比较，不靠字符串近似或目录自授权。 |
| `planner.profile/producer_profile/component_version/wheel_sha256`、`b_snapshot.profile/producer_commit` | 精确绑定的结构认可；当前示例 0.4.0/producers.v0.1/3b5…只能是 synthetic-test 锚点。生产支持走 §3 的新组件/profile/受信策略，不能保留测试用途后由 UI 改标生产。B 验实际加载/安装产物，不只信 worker 版本字符串；B2 host 与 B1 serializer 分列。 |
| `required_capabilities` | 须说明是 distribution、native planner 还是本机 transport 的能力层，并与 envelope/投影和本机实际支持集对应。只做 B 自身 subset 判断不能替 C 承认未知执行能力；不同层的能力列表也不应无条件当作相同集合。 |
| `revocation_snapshot.path/sha256/size_bytes/sequence` | 认可目录绑定 exact 原始撤回 envelope，再独立验签/用途/上下文；sequence 必须与目录相同且不倒退。404 不是空集合，pending pair 不刷新完整核验时间；当前 B 撤回集合不得随两份内容缓存清理而消失。 |
| `revoked_releases[].release_id/envelope_sha256` | 身份是完整 envelope 的 raw digest，不能用 A native release digest、planner manifest hash 或 C 归一化 hash 替代。它撤回整包，不可简单转成 C 的裸对象 ID；应由 B gate 以及新 C production adapter 的 release 级依据检查阻止执行。 |
| `revoked_public_refs[].kind/id/revision/content_hash` | **P1：当前 C 不能无损接入。** `_withdrawn_refs` 实际折叠成裸 ID 或 `id@revision`，不保存 kind/hash/release；不同 kind 可有同 ID。候选须明确 `content_hash` 的算法/材料/层级，建议固定为已验 A 原生记录/证据的对应 hash，并以原件/provenance 绑定；它与 C projected/normalized hash 不等价。不可丢掉 kind/hash 再声称保留同一身份。 |
| `reason_code`、`effective_at`、撤回集合 | 固定 reason 枚举、禁止敏感自由文本的方向认可。需定义 effective_at 是否必须为已生效时刻及与 issued_at 的关系；若允许未来定时撤回，须有明确离线时钟语义。新快照省略旧 tombstone 不得恢复旧 identity；应明确完整累积/单调合并语义，4 MiB 装不下时不能静默截断。 |
| 缓存条目的 sequence/digest 与 `last_complete_check` | **P2：离线依据必须绑定所选 artifact。** 验证新目录/撤回 pair、但新 artifact 下载失败，不能用新的全局 last_complete_check 给一个未获该目录列明资格的旧包延长离线宽限。需分别记录已验 metadata pair 与实际选中包的原始资格/tuple/basis。 |
| 新撤回事务与运行中的 worker/report | **P3：还需结果接收端 gate。** 除下载激活的 sequence CAS 外，B 应在发送任务和接受/保存结果时比较公开 validity basis/epoch；新撤回已提交后，按旧依据完成的 worker 不能成为当前可用报告。不能借 snapshot revision 或授权 generation 冒充公开依据 epoch。 |
| `status=ready`、controller/journal 状态 | A `/health/ready` 只表示 A 服务依赖就绪，不能表示某个 B 客户端已取得最新撤回。修订稿中 journal 不明导致 not-ready，应明确为 B 的本机分发/分析 gate，不能把 B 私有状态传给 A readiness。C 仍是 one-shot worker。 |

### 9.2 撤回 identity 的版本化处理（P1）

冻结前请在候选直接写明：C 0.4.0 的 `latest_known_validity.withdrawn_public_refs` **不承诺表达该 rich identity**；生产 C 消费契约需另行版本化。

- release 级：在同 origin/channel/consumer context 中绑定 `(release_id, envelope_sha256)`，命中即整包不可分析/回滚；不能仅塞入一个 release 字符串让现有对象过滤器“尝试匹配”。
- object/evidence 级：保留 `(kind,id,revision,content_hash)`，同时绑定发布/原生 hash profile；验证其与原始 A 记录/证据和 C 消费对象的对应关系后，才可应用禁用和依赖传播。
- 若未来 adapter 提议投影至旧 native `id@revision`，必须先证明目标在选中 release 内唯一且 hash/kind 已校验；碰撞或无法等价时拒绝，不能过度撤回其他 kind 或忽略撤回。更直接的 typed native validity 扩展需显式新 profile/capability。本文不改 S3 的 ID 规则。
- 当前 `_withdrawn_refs` 与 `disabled_objects` 的真实行为是评审证据，不是对生产 typed mapping 的实现承诺。A 的 schema 将 `content_hash` 写成 string 尚不能确定绑定材料。

### 9.3 向 C 传递的 offline basis（P2、P3）

这部分是新消费契约的最小语义清单，不是把额外字段加进现有 S3 schema：

1. 受信 origin/channel/native consumer profile、策略版本/摘要，选中 release 与 envelope raw digest、精确 producer/planner/snapshot tuple。
2. 所依据 catalog 和 revocation 的各自 sequence/raw digest/issued_at/valid_until、二者绑定；C 若声称独立验这些元数据，还需有界原始签名 bytes 和受信用途策略。
3. 已持久化完整 pair 与 pending/sync/recovery 状态的区分、所选 artifact 的实际验证/资格依据，可信 evaluation time、最后一次适用的完整核验时间与离线截止依据。旧缓存、latest metadata 和新 artifact 下载结果分别表达。
4. 明确 `offline_stale`、`revocation_unknown`、`expired`、known revoked 的含义及执行 gate；仅 supplied checked_at/online bool 无法证明这些状态。已知撤回优先于任何离线窗口。
5. B 为任务绑定公开 validity basis/epoch，并在结果接收、暂存/保存与显示当前适用性时复核；C 纯内存返回自己实际使用的版本/依据，不自称观察到之后的在线变化。

目录24h、刷新6h、离线72h、时钟偏差5min目前仅作为候选测试参数认可，不在本次确认其为生产默认。需要 A/B 明确时间组合的硬边界，不能通过重新读取本地文件、重复序号或无关 artifact 的同步来重置宽限。修订稿把 A 服务端 RAG 新鲜度与 B 离线 cache 分开的说明正确；B 的宽限不能延长 A 的证据有效性。

### 9.4 消费大小与错误层（P4）

候选的 `size_bytes<=64 MiB` 仅证明 B 下载限制，不能证明 C 可以处理。B stdio 的 **8 MiB** 是完整外层 UTF-8 消息，包含 materialized bundle、raw_json 的重复/转义和本机快照；C 另有单 raw_json **8,000,000字符**、100k 节点、深度48 的限制。若未来让 C 同时重验最大1 MiB catalog 和4 MiB撤回原文，这些内容也占本机预算。A/B/C 需固定可分析交付/本机请求的预算或新版本传输方案，并给出超限前的明确兼容失败；不能下载成功后默认为 C 可执行，也不能将私有 payload 发 A 来协商大小。

候选 §6 的 `distribution_*`、`revocation_state_unknown`、`device_clock_invalid` 是 B 同步层候选码；C 现有 adapter/native code 不因此改名。新消费者应保留错误所属层、原始 code 和使用的 basis。新增 trust/freshness/typed-revocation 失败绝不能包装成 no_feasible_variant。P1—P4 所列字段和 negative cases 属于后续有限协议复核/版本任务，本轮未编写或运行测试。

### 本次只读代码锚点

- [signature.py](../src/starhelp_planner/adapters/signature.py)：synthetic-test 门限、canonical manifest 数学验签、生产信任为 false。
- [a_distribution.py](../src/starhelp_planner/adapters/a_distribution.py)：commit/package/profile、原始签名/哈希/依赖/审核 provenance 与投影校验。
- [b_snapshot.py](../src/starhelp_planner/adapters/b_snapshot.py)：两个固定 B tuple、闭合快照/事实形状、部分覆盖和身份降级。
- [entry.py](../src/starhelp_planner/adapters/entry.py)、[engine.py](../src/starhelp_planner/engine.py)：prepare/native 分层、调用方撤回状态、局部适用性、可选反馈入口。
- [S3 证据](interop-s3-evidence.md) 与 [最终打包锁](../interop/b2-c248daa/packaged-lock.json)：技术合成证据与生产/材料/面板未覆盖边界。

## 10. B 新 builder、feedback 与开发候选的来源澄清

本节为 **2026-10-28 静态兼容评审**。读取 B 固定源码 `16ea426b312992de308d2d7646a9c592b894b525`、feedback 引入提交 `080e11fc40e67b4297034dfa3bd6337ff62153e7`，以及仅补来源说明的 `125f2ac9f0c1545940c30522cc9fc863bae76140`；不随 B 工作分支 HEAD 自动改换评审对象。未执行这些版本、未重跑旧 S3，也未构建/接纳新候选。

### 10.1 应分别记录的精确来源

| 层级 | 本轮核对的身份 | 结论 |
|---|---|---|
| 历史 S3 B host / candidate | `c248daab22255a069464a6d277757d01df5d49f3`；manifest `30e4820db6b3a97b193b29b225591758a1e424828b8f55be6094c68046bc19c3` | 原 S3 结论仅对应该锁定集合，不适用于以下新开发包 |
| 新 B 实际源码基线 | `16ea426b312992de308d2d7646a9c592b894b525`；`packages/starhelp-desktop` Git tree `58e4679dd3458e2518751228f15983ba91dee6f6` | 新 host/source tuple；不能将整个新 builder 声称为 B1 `103741e` |
| snapshot serializer/format 兼容锚点 | `103741e02c90ac672017f783058bdd8dacae982e` / `starhelp.desktop.snapshot.interop-min.v0.1` | models/profiles/bundles/storage 四个完整 blob 仍相同，十键快照/七键 fact 和 builder 内排序紧凑 UTF-8+LF 编码逻辑未变；只支持快照格式兼容结论 |
| 实际 request builder | `16ea426…` 中 `producer_request.py` Git blob **`0086d9121b9506ddcd3d6144f41a530b59bd8073`**；该 blob 首次由 `080e11f…` 引入 | B1 对应 blob 为 `5f1a89db3588573537bfce9af09172deb70ba524`；五项固定 seam 已有一项改变。080e11f 是引入修订，实际新 host 源码基线仍记录 16ea426 |
| 报告与 worker | `analysis.py` blob `c607e20aabf216a33c30ff04b6e97ed476f919c1`；`planner_worker.py` blob `bce4819941ea04a29725b9faa4ce167c3ae94e96` | 报告新增 feedback 留存；worker 与报告属于需要共同核对的新 host，不由 snapshot 格式证明 |
| synthetic demo 声明 | `synthetic_demo.py` blob `2b3ece32c57aba11d3bbd019ea7d0e6a307f5a4a`，仍传入旧 snapshot commit/profile | 该常量只覆盖嵌入快照声明，当前 wire 没有独立 builder 来源字段 |
| 新开发 candidate | manifest **`9076fd151141a9f1a5eba4907d3187fd7bc45380f5c48dfa208eb4407b406e3e`**；B 声明 worker `34b1ff7f2e779dea9cedb9854b352abb8ad417c669418ec5852fe10b74fb79a9`、920 文件、构建源码 16ea426 | C 本轮只读核对本机 manifest 文件的原始 SHA 与该声明一致；未逐项验 920 文件、运行 worker、复核构建过程或证明二进制源码对应 |
| C 固定消费端 | 0.4.0；wheel SHA `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2` | 保持固定，不因 B 新 candidate 使用同一 wheel 就获得新的 builder/生产准入 |

表内 `blob/tree` 是 Git 对象 ID，manifest/wheel 摘要为原始字节 SHA-256，不混作同一种 hash。B 的 125f2ac 说明补充了来源声明；它没有建立独立的二进制构建证明。后续若源码/候选改变，须重新给精确 tuple，不能让版本标签替代原始 hash。

**C 0.4.0 的真实限制：** `adapt_snapshot` 只登记旧 045965b 与 B1 103741e 两个 snapshot tuple；将 `account_snapshot.producer_commit` 改为 080e11f/16ea426 会得到 `unsupported_producer_version`。但保持旧 snapshot tuple 的新 builder 请求，当前 C **无法识别其 builder 来源**，并不因此自动拒绝。当前成功结果中的 snapshot provenance 不能扩写成“已验证新 builder”。无 feedback 时生成同样字节，也不能证明执行源码仍为 B1。旧 S3 五项 seam 等同前提已不成立。

### 10.2 feedback 已有能力与尚未证明的边界

- **C 已有：** producer adapter 将 `feedback` 转给 native v0.2；只有审核发布且有证据、范围/关卡适用的排障规则能求值。`user_reported` 只在 feedback 主体中被允许；字段仍须满足已登记属性类型、单位、测量语境、scope 和时间。建议目标还须是适用且重新通过拥有/锁定/条件等检查的完整已发布变体；不能从一句失败描述发明换人/配装方案。
- **B 新增接线：** builder 接收可选 feedback，最多 64 fields / 64 KiB UTF-8；顶层只允许 `fields/scope/variant_id/variant_revision`，fact 只允许有限键，必须非空值、`user_reported`、明确 unit 和 `{phase,assumptions}`。可选顶层 scope 必须等于任务，variant ID/revision 必须成对；复制至外层报告请求和内层 C 请求。报告只在已有可保存方案时暂存，并由显式保存进入加密存储。字段业务类型、实际属性/单位/时间适用性仍由 C 检查，B 形状检查不等于条件已经满足。
- **证据强度：** B 新测试代码及 handoff 记录了 synthetic failure 穿过固定 wheel、未保存报告和显式保存的接线检查。固定 S3 包没有排障规则，测试也未断言审核替代方案触发；这不是新 A/B/C 真实排障验收。C 既有 native 排障测试不能替代新实际 builder/worker 的组合验证。本轮未运行这些测试。
- **需修正的跨层绑定：** 16ea426 的 `_validate_wrapper` 比较外/内 task、身份及原始 public bundle，但没有比较两处 feedback；C 使用内层，`analysis.py` 使用外层保存。builder 正常构造相同值仍不足以防止重序列化/篡改/异步修改后保存另一份反馈。新协议应只保留一个权威 feedback，或强制两处存在性和值一致，分析和报告使用同一不可变请求副本；差异必须拒绝且不得生成可保存报告。request ID/revision/generation 相等不能替代此检查。
- **玩家进度笔记：** 16ea426 的新增记录是本机加密、受授权管理的自述，包含显示模式名、自由文本周期/关卡、达成标签和 note。它们未进入 snapshot/生产分析，也不构成经验证的 mode/cycle/stage ID、数值成绩、来源覆盖、材料或最终面板。不得自动转换成 confirmed 快照字段、排障触发事实或 A/RAG 输入。若未来显式选取为反馈，仍需另行映射、语义版本与用户任务绑定。

本节更新 §6 的进度判断：反馈的既有 native 形状已有 B 构建接线；单位/语境的新 snapshot、三模式可信记录、材料完整性和最终面板仍未交付。历史 S3 的“未验证 B feedback 接线”结论继续限定于原先固定源码，不否认后续开发实现。

### 10.3 最小版本与准入提案（未实施、未冻结）

1. **新 C component：需要。** 新 builder 来源验证/准入与结果 provenance 属于新增行为，走后续显式组件和新 wheel；不重写 0.4.0、不放宽其旧 tuple，也不把 9076 包追认为 S3。具体版本号待共同契约固定；可与 §3 的生产消费者版本合并安排，但 feedback 接线本身不授予生产信任。
2. **独立 builder 身份：需要，且在新 producer request profile 中强制。** 建议新 schema/profile 明确 `request_producer`，由受信 host 的已登记策略核对 producer/package、实际 `source_commit`、builder blob/依赖锁及本机能力；16ea426 是本轮候选 source，0086d912 是 builder blob，080e11f 仅作为引入修订说明。它独立于 `account_snapshot` 的 serializer/format；无 feedback 的新请求也必须声明。C 结果回传所用 builder/profile/策略身份供 B 关联。单纯往旧 v0.1 塞一个可被忽略的 optional provenance，不构成强制来源门限。自报 commit/hash 不是认证或构建证明，仍须 B 的实际加载/构建锁和受信配置；未知/缺失/矛盾 identity 在新 profile 拒绝。
3. **snapshot/native profile：本次 feedback 不单独要求升级。** 在快照原始形状、编码、语义确实保持时，可保留 `starhelp.desktop.snapshot.interop-min.v0.1` 格式锚点，另记实际新 host/builder；既有 feedback 谓词不变时可保留 native `starhelp.local.v0.2` / rules 0.2.0。不得以保留格式锚点声称新 producer 整体就是旧 103741e；单位/材料/模式记录/最终面板等未来扩展仍按 §6 分别版本化。
4. **capability：分层登记。** 新 producer profile 的来源门限必须成为 worker 明确支持的协议能力；仅接入既有 feedback 不需要虚构一个新 native 排障算子能力。若为 B 的 feedback 接收/报告一致留存增加能力标识，它应表示该端到端行为，并待一致性修正和有限验收后才宣称支持；不能与 A `required_capabilities` 或 C native profile 能力混作一个集合。新增反馈类型/单位/主体/动作超出现有 native 语义时才须另提 native profile/capability。所有新名称均待注册，不由本节发布。
5. **完整 source/artifact tuple：另立新锁。** 共同登记 A 实际 producer/profile/release/raw hash、B 实际 host/package tree、snapshot 格式及 encoder、request builder/profile/blobs、C component/wheel/native/adapter、候选 manifest/worker 与信任用途。B 应提供明确构建时的源码/依赖/vendor 清单及对应声明/原始样例；C 不用旧 c248daa/30e482 锁替新 16ea426/9076 作证。构建证据缺项标为未建立，不反推已建立。

### 10.4 后续有限验收清单（本轮未运行）

待上述协议与 tuple 固定后，再给新 host/source 与新 candidate 分别产证据；不重跑/重建旧 S3：

- 新实际 builder 的无 feedback 请求；有反馈但无审核规则时明确无法判断；与旧快照格式兼容不等于新来源准入。
- 审核规则触发正例、未登记属性/错误类型/单位/语境/过期/冲突/跨任务反例；建议目标受完整变体、拥有、锁定、条件、公共撤回检查。A 须先交付相应审核 fixture，不能修改旧 signed S3 包塞入规则。
- 新 producer/profile/实际 source 未登记、缺 provenance 或冒用旧 builder 来源均拒绝；旧 v0.1 作为历史兼容路径时明确其未验证 builder，不能绕过新消费者的准入策略。
- 外/内反馈存在性或值不一致、请求在发送至报告暂存之间被修改、request/revision/generation 或公共 validity basis 改变均拒收；无可用方案/领域错误不产生可保存报告。
- 本地内存、主动保存前零私有持久化、显式加密保存、撤权拒收迟到结果与清理；feedback/进度笔记不进入 A/PublicQuery/RAG/普通日志。源码与打包 worker 各自固定 manifest/加载来源，单独记录执行结果和未证明项。

结论：认可 B 的“快照格式与 request builder 分列”方向；建议强制版本化 producer profile，而非在旧协议中增加可忽略的来源声明。新 B 开发成果保留，9076 候选仍是待新 tuple/协议验收的开发包。A 候选 P1—P4 和完整 Goal/M0 的真实来源、审核、生产信任与本机实测缺口仍未关闭。

### 10.5 B 后续修复的静态复核（2026-10-30）

§10.1—10.4 的来源和未修复描述针对当时固定的 16ea426，不自动代表后续代码。本次另读 B **`9f619e88e77412df24233080da5eaf41d8ffe33b`**：包 Git tree **`b80cbca0cd1cd1e327ad5da1e44789951d2aa892`**，与 `41b5e711a5129812df7198535e0ab90af85b2b24` 的包 tree 相同；9f619e8 只补根目录 handoff。以下是该固定源码的静态结论，未运行 B 测试、GUI、worker 或安装器。

| 评审项 | 新源码证据 | 当前判断 |
|---|---|---|
| 外/内 feedback 存在性与值不一致 | `9c51720a91d9dc25847cddd53f220fb60ca7b075` 在 `ProducerAnalysisRunner.run` 调 planner 前调用 `_require_matching_feedback`；逐侧存在性一致，`allow_nan=False`、排序紧凑 JSON 值比较 | §10.2 所指 runner 路径已增加拒绝门限；静态认可该修正，不能继续称当前 runner 完全缺此检查 |
| 发送后原请求/worker 参数被修改影响报告 | `dd904e3edc11177e735381d454c1b8e3b114897d` 的 `_snapshot_request` 对完整请求有界编码一次，再解析出分离的 worker/report 副本；检查 report 副本并从它读取快照、task、bundle、feedback | 原调用方与 worker 可变 dict 不再是报告读取来源。`analysis.py` 当前 blob **`d3961b47844a44a0a3dfb9bb1b228836d608d528`**；不能继续拿旧 c607e20 作为该修复后的实际来源 |
| 回归代码的证明范围 | 9c51720 测试覆盖不同值/两种单侧缺失，并断言 planner 未调用；dd904e3 测试以 Mock 修改 worker 入参后返回构造结果，检查原请求及暂存报告保留原值 | 这是已读的回归代码与 B 执行记录，不是 C 新执行结果。Mock 隔离检查不能证明实际 worker 消费字节、结果反馈摘要或公开 validity basis 已绑定 |
| 五项 seam / snapshot 格式 | builder blob 仍为 `0086d9121b9506ddcd3d6144f41a530b59bd8073`；profiles blob 改为 **`e07f0829b3109c4f624ae3323264d249df7e680b`**，diff 是自动刷新配置失败恢复 | 相对 B1，五项完整文件中已有 builder、profiles 两项不同；旧五文件等同前提仍不能使用。对 B1/16ea426/9f619e8 的 `_snapshot_to_dict` 做静态 AST 比较相同；该函数不变不证明整个 profiles 或新 host 与 B1 相同 |
| 独立 stdio worker 边界 | `planner_worker.py` 仍为 blob `bce4819941ea04a29725b9faa4ce167c3ae94e96`；`_validate_wrapper` 没有新增外/内 feedback 比较 | runner 的修正不能表述为 worker 任意入口已有同一检查。新协议须定义唯一权威 feedback 或在实际消费边界检查一致性；直接 worker、正常 runner、报告保存分别有验收项 |
| builder 身份准入 | 新 handoff 同意 C 的强制 profile/source/artifact 方向；builder wire 仍没有独立必需身份，C wheel 仍为 0.4.0 | §10.3 的新 component/producer profile 提案仍待共同固定和实施；不把 runner 修复、synthetic UI 重算或旧快照 tuple 当作新 builder 准入 |

AST 比较仅用于核对固定函数语义形状，`ast.dump(..., include_attributes=False)` UTF-8 的 SHA-256 为 `06af62f70fd4e59b41c664f3bfcdb631eb5a67203b5588ce43f2fbd3396b8d55`；它不是 snapshot raw bytes digest、Git blob ID 或完整 serializer 运行证明。

**本机当前开发候选另行固定：** manifest 原始 SHA-256 **`6cf00caf71d861ee01af48d68c8a07ffcf6c1c6e1d9e094b7de4f979f4fc0a55`**，实际 `planner-worker/StarHelpPlannerWorker.exe` 原始 SHA-256 **`6900ff39072a05ff16f74aab18867202581b931f8a6a79a3d174326606177fbe`**；C 本次只读重算这两个文件，均与 B handoff 相同。B 记录 71 项包测试、920 文件校验与合成候选 smoke；C 未复跑、未逐项验当前 920 文件，也未独立确认二进制构建来源。该集合既不是 9076 开发候选，也不是已验 S3 30e482 集合；不迁移任何旧 source/packaged 对照结论。

**仍开放的依赖：** A 固定候选仍为 `012d69508588b0800053108ef38c4bc753bebc14` / raw SHA `88071e56a4b49c3d3cf6dda89aca912559a353139d74e4f81b9f548af7ff989b`，本轮重新核对；P1 typed identity/hash、P2 所选 artifact 离线资格、P3 公开依据 epoch 的结果/保存 gate、P4 整体 stdio 字节预算均未由 B runner 修复关闭。B 9f619e8 也明确真实来源/ID/条件语义、生产信任和新 builder 契约未冻结。按现有 S4.1 顺序先收敛同一契约 hash/tuple，再安排新组件实施；本轮只更新这份评审及 C handoff，固定 wheel、源码、fixture、共享契约、原 S3 证据保持原样。
