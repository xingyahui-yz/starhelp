# StarHelp 首版三线程协作契约 v0.1

> 状态：工程契约初稿，供三个隔离线程共同实施前核对；不是已冻结 API，也不表示存在真实来源 Adapter、真实攻略模板或可发布的软件。
> 依据：用户确认的开发方案 v1.3。本文只定义职责、交换面和约束；真实来源字段、玩法/周期/关卡 ID、谓词枚举、哈希规范及 HTTP 路径在 M0 核验并冻结。
> 所有 `fixture:` ID、人物、装备、数值及规则示例均为合成数据，不是游戏资料。示例是契约说明，不能冒充审核通过的生产包。

## 1. 三个线程与文件所有权

三个线程各自使用独立 clone、工作目录和分支。各线程从协调方给定的共同基线及同一版契约开始工作；不合并到 main，不互相合并功能分支，不覆盖另一个线程的工作区。

| 线程 | 分支 | 独占目录与 Python 包 | 责任 |
|---|---|---|---|
| A 公共知识后端 | `codex/mvp-knowledge-backend` | `packages/starhelp-knowledge/`；导入名 `starhelp_knowledge` | 公开查询、来源/证据、知识及完整模板/变体/排障、审核发布、完整公共 bundle 与 manifest、禁用及覆盖状态 |
| B Windows 桌面与账号 | `codex/mvp-desktop-account` | `packages/starhelp-desktop/`；导入名 `starhelp_desktop` | GUI、公开数据客户端、逐档案授权、公开 UID 档案直连、本地导入预览/合并/冲突、最新快照、加密撤销、主动报告、两个公共缓存、调用本地规划器 |
| C 本地规划核心 | `codex/mvp-local-planner` | `packages/starhelp-planner/`；导入名 `starhelp_planner` | 纯本地 `analyze(request) -> result`；完整变体匹配、三态条件、硬限制、角色/装备占用、当前配装与调装分类、解释/培养/审核排障 |

- 每个目录包含自己的包配置、源码、合成样例及开发说明，可在自己的 clone 独立安装和验证；不依赖其他线程尚未交付的同工作区文件。
- 根配置、README、主开发方案、本文、其他线程目录属于协调区；修改需求先提交契约变更提案，不由功能线程直接修改。
- 旧 `src/abyss_ai` 是只读参考与可复用材料。三个线程不跨分支改旧包；需要复用时在各自包边界内适配并记录来源、许可证和行为差异，不假装旧模拟器已有真实推荐能力。
- A 不接收或存放玩家私有数据；B 管理所有账号生命周期；C 不实现网络、GUI、数据库、文件读写或游戏输入，不调用模型/工具，也不记录私有输入到日志。
- 功能线程的交付包括本分支提交、接口说明、样例版本与限制，供协调方以后集成。用户另行决定何时启动 goal、运行持续任务或合并。

## 2. 数据流与隐私边界

允许的数据流：B 发送 `PublicQuery` 给 A；A 返回公共 `PublicBundle`；B 在本机把公共 bundle、私有 `AccountSnapshot`、目标/硬限制和可选反馈组成 `AnalysisRequest` 传给 C；C 将 `AnalysisResult` 返回 B。B 展示结果，用户主动保存后才写本机加密报告。

公开档案是另一条单独授权的数据流：B 将 UID/区服直接发送给玩家选择的公开档案服务，结果回到本机。UID 不经 A，不授权游戏登录；不收密码、Cookie、会话令牌。

以下内容禁止出现在 A 的请求、URL/路径、请求头、业务表、模型输入、共享索引或日志中：UID、档案/快照 ID、持有名单、构筑、装备实例、仓库、当前成绩、锁定设置、缺口、适配分/匹配状态、私有报告和反馈。匿名构筑仍属私有信息。

公共模板集合按玩家明确选择的公共关卡/目标类别批量获取；不能先在本地计算缺角、配装或候选，再以这些账号特征向后端筛队伍。客户端能力和已有公共发布版本可以用于兼容/同步，不夹带账号特征。混合了私有内容的自由输入不直接发给 A，无法可靠分离时由 B 请玩家确认公开问题。

## 3. 共同约定与版本

下列对象使用 UTF-8 JSON 可表达的字段和值；Python 内部类型可不同，但序列化语义一致。字段名是本初稿的建议，不宣告已冻结真实来源 schema。

| 通用项 | 语义 |
|---|---|
| `contract_version` | 本协作契约的交换版本；示例使用 `0.1-draft`，生产版本由 M0 冻结 |
| `schema_id` / `schema_version` | 每类对象自己的结构/语义版本；不能与游戏版本、资料修订或 index release 混用 |
| `id` / `revision` | 对象稳定身份与不可变修订；不以名称、URL 或采集顺序替代身份 |
| `index_release_id` | 一次公共发布集合的身份；一个分析请求仅使用一个 release 的完整公共对象 |
| `required_capabilities` | 对象语义所需的能力名及版本；客户端/规划器公布自身支持集合，未知必须能力不能忽略 |
| 时间 | 带时区的 UTC 时间；B 按客户端时区显示。观测、确认、采集、验证及发布时刻分别保留 |
| `null` 与状态 | 缺失用 `null` 加原因/状态；不补零，不把“未展示/未读取”当“没有/未通关” |
| 引用 | 类别、稳定 ID、修订与所属 release 明确；公共引用不得指向私有档案或本地物品 |

未知必需 schema/能力、损坏包、依赖不闭合或跨 release 引用禁止模板适配；可在理解外层格式且安全的情况下显示来源/覆盖提示或纯文本资料，不能执行未知规则。版本支持决定必须显式，不以“字段似乎相同”猜测兼容。

## 4. PublicQuery：B → A，仅公开字段

最小逻辑字段：

- 交换版本、查询种类、固定的公共 `index_release_id`，或在首次发现发布时明确使用发布发现操作。
- 公共范围：游戏版本、资料环境、玩法、周期、关卡、公开问题类别、玩家明确选择的公共实体；范围不明时返回未解析，不自动跨环境/跨期补齐。
- 目标只可表达公共奖励档位、目标类别或成绩门槛，不含玩家当前成绩、与目标的差距或账号推导的目标。
- 同步可另带客户端支持的 schema/capabilities 与已缓存的公共 release ID。精确请求字段白名单与 HTTP 路径由 M0 确定，未声明字段默认拒绝。

示例：

```json
{
  "contract_version": "0.1-draft",
  "schema_id": "PublicQuery",
  "schema_version": "0.1-draft",
  "query_kind": "stage_templates",
  "index_release_id": "fixture:release:1",
  "scope": {
    "game_version": "fixture:game:v1",
    "environment": "live",
    "mode_id": "fixture:mode:alpha",
    "cycle_id": "fixture:cycle:1",
    "stage_id": "fixture:stage:1"
  },
  "public_goal": {"kind": "fixture:goal:clear"}
}
```

`fixture:mode:alpha` 和目标均是假标识，不是星铁真实模式 ID。A 返回适用的公共候选集合；未知角色、具体配装、固定/排除条件留给 B/C，不扩展查询字段承载。

## 5. PublicBundle：A → B → C，完整公共对象

`PublicBundle` 至少包含 `manifest` 以及完整公共实体、关卡、模板、整队变体、证据、排障规则。RAG chunks 可帮助发现和定位，不是完整模板替代物。bundle 不含任何私有字段。

| 部分 | 最小内容与关系 |
|---|---|
| `manifest` | release ID、父 release、包 schema、对象 schema、所需能力、适用范围、覆盖、新鲜度、发布/验证时间、members 与依赖、内容校验信息 |
| `entities` | 公共稳定 ID、不可变修订、实体类别、版本/环境及已验证公共资料；装备实体 ID 表示类型，不是玩家物品副本 |
| `stages` | 玩法/周期/关卡修订、分区/槽位与共享限制、敌人/机制、奖励条件、证据；实际结构由来源核实 |
| `templates` | 稳定 ID/修订、适用范围、公开目标、完整体/变体引用、有效和审核状态、证据与能力要求 |
| `variants` | 每项都是整队审核过的完整方案：全部分区/槽位/角色、装备类型条件、联合条件、有序打法、机制、失败条件、培养依据和证据映射 |
| `evidence` | 来源 URL/标题、许可允许的最小摘录、locator/hash、来源等级、适用范围、支持/反驳/限定关系及时间；全文需有许可 |
| `troubleshooting` | 已审核的声明式触发条件、适用完整变体、证据、建议或可切换的完整变体；不含玩家实际失败记录 |

manifest 的每个 member 指明类别、ID/修订、内容哈希、获取位置及依赖。所有成员、引用和证据在同一 release 内形成完整依赖；不得从另一个 release 补“最新”关卡或模板。内容规范化/哈希算法、传输和签名方式由 M0 确定，不能仅信任外层 `verified: true` 标记。

完整变体的条件最少表达主体、属性、受限运算、值/单位、面板语境（战斗前/战斗内及 buff 假设）、硬/软要求和证据。`evidence_status` 是 confirmed / suggested / unknown 的公共证据语义；`match_status` 是 C 依据私有输入计算的满足/不满足/未知，不能写进 bundle。

条件和排障仅允许冻结白名单中的声明式结构；没有脚本、表达式求值器逃逸、任意函数、动态 import、命令或网络调用。两个单独替换各自有效不能推出组合有效，多处替换必须已有完整审核变体。

下面是顶层结构示意；占位对象不表示可发布完整模板，实际合成 fixture 必须补全成员、依赖和可校验哈希：

```json
{
  "contract_version": "0.1-draft",
  "schema_id": "PublicBundle",
  "schema_version": "0.1-draft",
  "manifest": {
    "index_release_id": "fixture:release:1",
    "parent_release_id": null,
    "required_capabilities": ["fixture:complete-variant:v1"],
    "object_schemas": {
      "entity": "0.1-draft",
      "stage": "0.1-draft",
      "template": "0.1-draft",
      "variant": "0.1-draft",
      "evidence": "0.1-draft",
      "troubleshooting": "0.1-draft"
    },
    "coverage": {"status": "unknown", "reason": "contract-example-only"},
    "members": []
  },
  "entities": [],
  "stages": [],
  "templates": [],
  "variants": [],
  "evidence": [],
  "troubleshooting": []
}
```

此空包只演示覆盖不足的表示，不可生成队伍。一个正向合成 fixture 还必须具有完整关卡分区与队伍、全部实体/证据引用，以及至少一个声明式条件，例如：

```json
{
  "condition_id": "fixture:condition:speed",
  "subject": {"kind": "team_slot", "slot_id": "fixture:slot:upper-1"},
  "attribute": "fixture:stat:speed",
  "operator": "fixture:gte",
  "value": 100,
  "unit": "fixture:flat",
  "measurement_context": {"phase": "pre_battle", "assumptions": []},
  "requirement": "hard",
  "evidence_status": "confirmed",
  "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]
}
```

这里的属性、运算符、阈值都是假数据，不能据此冻结真实谓词或认定真实角色达标。未注册语义返回不兼容；已支持谓词但账号缺值才是条件匹配未知。

## 6. AccountSnapshot：B → C，仅本机

B 只维护一份最新合并快照，版本更新不自动归档旧原始快照。字段对象至少有 `value`、字段状态、来源摘要、观测时间、确认时间和适用范围；冲突保留待确认候选，不能静默挑一个值。部分刷新只更新实际覆盖字段，其余保留原值及原时间。

| 字段组 | 最小语义 |
|---|---|
| 快照身份 | 本地 `profile_id`、`snapshot_id`、单调修订/代次、生成时间；不用于任何公共请求 |
| 授权上下文 | 本地授权状态与代次；B 在分析前检查授权，撤销后取消任务并拒收旧代次异步结果。C 的输入字段不能替代 B 的授权检查 |
| `coverage` | 分别说明角色名单、角色字段、已装备/未装备物品、材料、三模式记录覆盖范围及时间；“完整”必须有来源证据 |
| 角色 | 公共角色实体 ID + 本地所有权 owned / not_owned / unknown；构筑字段有独立质量与时间状态 |
| 装备 | 公共类型 ID + 本地具体副本身份/身份状态、来源映射、穿戴者和属性；类型 ID 或相同词条/hash 不能充当实例 ID |
| 记录 | 三模式实际取得的周期/关卡、成绩/奖励和来源；公开动态事件不假装完整历史，缺失不记零 |

无可靠来源实例 ID 时，玩家可确认建立本地物品身份。身份待确认或重复歧义记录可以用于原角色当前配装分析，不进入跨角色调装。重新读取不凭外观/词条自动合并同件，C 不替 B 确认身份。

局部示例（不是完整可分析请求）：

```json
{
  "profile_id": "fixture:local-profile:1",
  "snapshot_id": "fixture:local-snapshot:1",
  "snapshot_revision": 3,
  "authorization_generation": 2,
  "coverage": {"roster": "partial", "inventory": "unknown"},
  "characters": [{
    "entity_id": "fixture:character:1",
    "ownership": "owned",
    "fields": {
      "fixture:stat:speed": {
        "value": 101,
        "state": "confirmed",
        "observed_at": "2026-01-01T00:00:00Z",
        "confirmed_at": "2026-01-01T00:01:00Z",
        "sources": [{"source_kind": "manual", "local_source_id": "fixture:input:1"}]
      }
    }
  }],
  "equipment_instances": [{
    "local_instance_id": "fixture:local-relic:1",
    "public_type_id": "fixture:relic-type:1",
    "identity_state": "player_confirmed",
    "equipped_by": "fixture:character:1"
  }]
}
```

`player_confirmed` 仅说明玩家确认本地副本身份，不说明装备属性/所有权所有字段均已核实。本机来源标识和确认记录不得出现在公开 bundle。

## 7. AnalysisRequest 与 AnalysisResult：B ↔ C，仅本机

建议最小调用为 `analyze(request) -> result`。C 接收已物化的 JSON 可表达对象，不接收文件路径、数据库连接、网络地址或回调让其自行读取资料。

`AnalysisRequest` 至少包含：

- 交换 schema、本地请求 ID、B 已检查的有效授权代次。
- 一个完整 `public_bundle`，其单一 `index_release_id`、覆盖和最新已知禁用状态及校验时间；B 校验获取完整性，C 再检查引用闭合与语义支持。
- 当前 `account_snapshot`，以及本地选择的目标、固定/排除角色、锁定装备/光锥和允许的调装范围。
- 本次任务可选的实际队伍、成绩和失败现象；仅用于审核排障，不生成学习参数，不自动保存。
- 本地规则/规划器版本与支持能力。相同已固定输入和规则版本应得到稳定解释，不依赖隐含网络或全局持久状态。

B 将前述对象直接嵌入请求；不能只传 bundle/snapshot ID 让 C 去远端或本机文件查找。

最小无资料请求示意如下；预期是明确的覆盖不足，不能生成任何个性化队伍。时间、身份及目标仍是假数据，字段集合等待 M0 冻结：

```json
{
  "contract_version": "0.1-draft",
  "schema_id": "AnalysisRequest",
  "schema_version": "0.1-draft",
  "request_id": "fixture:local-request:empty",
  "authorization_generation": 2,
  "public_bundle": {
    "contract_version": "0.1-draft",
    "schema_id": "PublicBundle",
    "schema_version": "0.1-draft",
    "manifest": {
      "index_release_id": "fixture:release:empty",
      "required_capabilities": [],
      "object_schemas": {},
      "coverage": {"status": "unknown", "reason": "synthetic-empty-fixture"},
      "members": []
    },
    "entities": [], "stages": [], "templates": [],
    "variants": [], "evidence": [], "troubleshooting": []
  },
  "account_snapshot": {
    "schema_id": "AccountSnapshot",
    "schema_version": "0.1-draft",
    "profile_id": "fixture:local-profile:1",
    "snapshot_id": "fixture:local-snapshot:empty",
    "snapshot_revision": 1,
    "authorization_generation": 2,
    "authorization_state": "active",
    "generated_at": "2026-01-01T00:00:00Z",
    "coverage": {"roster": "unknown", "inventory": "unknown", "mode_records": "unknown"},
    "characters": [], "equipment_instances": [], "mode_records": []
  },
  "task": {
    "public_goal": {"kind": "fixture:goal:clear"},
    "fixed_character_ids": [], "excluded_character_ids": [],
    "locked_local_instance_ids": [], "allow_rearrangement": false
  },
  "latest_known_validity": {
    "withdrawn_public_refs": [],
    "checked_at": "2026-01-01T00:00:00Z",
    "online_confirmation_available": false
  },
  "feedback": null
}
```

空包例子不展示生产 manifest 的完整性摘要；正式模板适配必须补全第 5 节信息并校验，不能因这里省略而在实现中放行缺失哈希/校验信息。

`AnalysisResult` 至少包含本地请求/档案/快照修订及授权代次、公共 release/关卡/模板/变体修订、本地规则版本、覆盖/有效状态，以及以下结果：

| 结果项 | 语义 |
|---|---|
| 当前配装方案 | 仅来自已有完整审核变体；主方案角色确认拥有，没有硬限制违例或重复资源占用；未知条件明确列出，不标作已达标 |
| 调装方案 | 单独分组，遵守锁定、可靠本地实例身份和实际关卡共享规则；列清调装动作，不执行游戏操作 |
| 待确认候选 | 含未知所有权/关键资料的候选，与主方案分开；不假设玩家缺少或拥有未展示角色 |
| 条件结果 | 条件引用、match_status 为 satisfied / not_satisfied / unknown、本地依据字段、缺项/过期/冲突原因、公共 evidence_refs；原 evidence_status 另保留 |
| 解释 | 队伍/配装适配、机制和步骤、风险、缺口、培养优先级和已审核排障建议；不存在证据的收益或通关概率不输出 |
| 降级 | 无模板、无可行变体、未知能力、输入不完整或依据失效的明确状态；提供公共资料/补充入口，不拼凑队伍 |

结果局部示例：

```json
{
  "contract_version": "0.1-draft",
  "schema_id": "AnalysisResult",
  "schema_version": "0.1-draft",
  "request_id": "fixture:local-request:1",
  "snapshot_revision": 3,
  "authorization_generation": 2,
  "index_release_id": "fixture:release:1",
  "status": "coverage_insufficient",
  "current_equipment_plans": [],
  "rearrangement_plans": [],
  "pending_confirmation_candidates": [],
  "condition_results": [{
    "condition_id": "fixture:condition:1",
    "evidence_status": "confirmed",
    "match_status": "unknown",
    "reason_code": "missing_field",
    "local_field_refs": ["fixture:local-field:1"],
    "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]
  }]
}
```

此例只说明“证据确认、账号匹配未知”可以并存，不是与前述空包一起使用的可运行样例。只有对象完整、引用闭合的同套 fixture 才能验证正向结果。

C 不自动放宽硬限制、创建未审核替代组合、学习阈值或更新账号。排序先排除硬限制违例，再按适配、证据质量与调整成本；数值/并列细则待样本冻结，不能把排序分称为成功率。材料或库存不完整时不算净资源缺口，或明确成本未扣库存。

B 对返回代次再核验，撤销或快照更新后不能将旧结果当作新分析；用户点击保存才保留必要结论/证据和版本，不能为保存报告额外归档整份历史快照。旧报告过期、撤回或无法完全重现时显式标记。

## 8. 错误、兼容与撤回

错误信封建议有 `code`、可理解的说明、是否可重试、缺失能力/范围和安全详情。初稿类别如下，枚举名称待 M0 冻结：

- 结构/兼容：unsupported_contract、unsupported_schema、unsupported_capability、invalid_payload。
- 公共包：release_mismatch、missing_member、integrity_failed、withdrawn_evidence、scope_mismatch、coverage_insufficient。
- 本地输入：authorization_inactive、superseded_generation、snapshot_conflict、identity_ambiguous；一般字段缺失优先体现在三态/覆盖中，不一律抛致命错误。
- 正常无结果：no_reviewed_template、no_feasible_variant；与程序错误分开，不返回伪造空成功报告。

A 的错误、请求 ID 和日志均不回显私有输入；B/C 的私有错误也不能通过遥测或云端异常上报离机。授权撤销由 B 立即拒绝新分析、取消任务、删除私有快照/配置/缓存/临时副本及关联报告，旧异步结果不能恢复它们。

B 校验并保留两个有效公开 release 后原子切换，失败沿用上一个有效包；两个缓存不是账号历史。A 的回滚和 B 的旧缓存/报告都不能绕过最新已知禁用状态。离线显示最后校验时间与覆盖/时效缺口，不能声称已知服务器刚发生的撤回。

## 9. 独立样例与真实集成边界

三个线程不需要互相 merge 即可开发：协调方确认同一版契约和合成公共 fixture 标识/摘要，A 只交付公共 fixture；B/C 各自维护无真实玩家数据的合成本地快照与预期三态样例。样例变更也走版本提案，不偷偷改同名 fixture。

建议同套样例覆盖：完整主方案、缺值未知、确认未拥有、锁定冲突、相同类型不同副本、身份歧义、独立替代不可组合、无模板、跨 release、未知 schema/capability、证据撤回，以及 B 的撤销后异步返回。A 不接收 B/C 的私有快照来验证自己的公开接口。

B 可先用显式标记的样例规划器验证界面，但必须显示“模拟结果”，不能计作真实集成。实际联调时，由 B 明确加载 C 交付的本地包/可审查构建产物，或通过受控本机子进程的标准输入/输出传递完整请求；限定同一 Windows 用户、校验版本/能力、约束消息大小/超时，并禁止私有载荷落到普通日志。C 本身仍无网络与存储。缺少真实 C 时报告依赖未接入，不回退为云端个性化分析。

## 10. M0 冻结与变更提案

M0 需要三方对照验证：真实来源许可及公开字段、实际三模式周期/关卡/实体 ID 映射、快照质量和实例身份、声明式谓词/单位/面板语境、公共目标表达、完整成员/依赖、哈希与封包、schema/capabilities、错误分类和传输契约。HTTP 路径、Python 公共类型与所有枚举此时共同冻结。

变更先在提案方独占目录的 `docs/contract-proposals/` 提交说明：问题、旧/新 JSON 示例、是否改变语义/隐私边界、影响的生产者/消费者、兼容方案及样例更新。通知协调方，由协调方合并意见、更新本文和契约版本并向三个线程分发；功能线程不直接覆盖共享契约。

修改必需字段、条件语义、三态/身份含义、发布绑定或隐私边界属于不兼容变更，不能以新增可选字段掩盖。即使字段可选，新的模板能力也必须声明且经消费者确认；未支持前明确拒绝适配。三方交付报告列出所实现契约版本、fixture 版本、尚缺依赖和实际验证范围，不把 M0 文档确认、样例通过或模拟界面分别当成真实来源接入和最终集成完成。
