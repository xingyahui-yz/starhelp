# C 对最小共同接口候选的 S2 复核

## 最终语义确认（优先于下方过程意见）

同意按修订候选原始 UTF-8 SHA-256 `8116030eb600d58a091a52711b99d7788d45fed71fdbc1bfe02a01ca25233f68` 冻结有限技术范围；实现差异在 S3 交付。该确认已在本聊天回复协调会话，替代下方针对 6f21ac / 1bed5b 中间版本的待补文字意见。

最终 S3 装备类型限制采用 `public_type_id` 与非空去重 `public_type_ids` 二选一；无类型限制只能省略两键。旧 C 0.3.0 的双键 OR/空列表宽容属于已知实现差异，不是新 S3 包的合法形态。scope 闭合/类型、装备允许键/实体 kind/槽位精确匹配、`requirement`、A/C 谓词交集、partial 库存待确认、producer 元组和 stdio 关联边界均已在该摘要版本明确。

这是目标技术语义确认；当前代码与新样例仍须按 S3 有限适配清单交付和回放。本次只读核查时，协调清单仍标 S2 候选、S3 待生效；本次没有执行 S3、测试、构建或发布。

## 复核过程记录（最终确认以前）

审阅对象：协调目录 `docs/contracts/interop-min-v0.1.md`，标识 `starhelp.interop-min.v0.1`，候选日期 2026-10-20。

- 首轮候选原始 UTF-8 文件 SHA-256：`6f21ac51fa62dc8fba5c0c30395d0c58d3520026814e8c0a132404c112db3d11`。
- 收尾复核的修订候选 SHA-256：`1bed5b98d4bb656a1953e53e661b538967da48dfa3cf60f4acc114ad13c2b18b`，文内更新日期 2026-10-21。以下最终意见以此修订版为对象。
- C 代码/证据基线：`939818caf9ce93cbe56c5c7dc87fc0d1d20379b3`；组件 `0.3.0`、原生规则 `0.2.0`。
- C 已交付 wheel SHA-256：`f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`。
- B S1 源码静态核对：`aa2a2b152a6b961e4f547488ff3c9afc3701fc68`。该版本保留 worker 补缺失关联字段的修正；本轮没有运行它的测试或候选程序。63 项测试和候选证据属于 B 的交接记录。
- 本轮工作：读取候选、源码和已有证据，提出修订及未来矩阵。未实施 S3，未修改共享契约或 A/B，未新增/运行实现测试，未启动新 Goal。

## 结论

**确认 1bed5b 修订版的有限技术方向及已澄清语义，建议补入下述精确附件后冻结。** 修订版已解决原始候选中装备 OR 语义、A/C 算子交集、partial 库存锁定预期、revision 0 分析边界、B stdio 关联层级和批准证明的信任边界；这些不再作为未解决异议。

冻结前剩余的最小文字补充是：D1 将 scope 的闭合键集合/类型写全并登记 C 的同类实现差异；D2 明确装备要求允许键、类型及 slot 精确匹配；D3 将 hard/soft 精确键写成 `requirement`，并附当前 A `entity` 主体到 C `character` 的实际形状。其余 D4—D6 是可直接纳入兼容附件的确认和边界说明。

请按修订版 §7 区分“目标契约”“C 0.3.0 已实现部分”“S3 新 wheel 接入检查”。文档确认可以先完成；scope/装备校验、新 producer 接入及新 wheel 的证据在 S3 前补齐，不要求本轮实施。当前校验器的宽容行为不能写成已经实现的严格规则。

旧 `mvp-v0.1.md`、真实来源/ID、内容批准、生产信任及真实本机验收保持各自未完成关口。本复核不把旧 Goal 标完成，也不以 Goal 登记状态限制 S2 工作。

## 逐节意见

| 候选章节 | C 意见 | 具体影响与最小修改 | 已有依据 |
|---|---|---|---|
| §1 范围与版本 | 支持；补精确接入限制 | A 执行提交、A 产物提交、B serializer、B host、C wheel 分列。新 A 提交或新 B producer 提交当前会被 C 0.3.0 拒绝；见 D5。协调标识不进入旧已签名包。 | `adapters/a_distribution.py:18`、`b_snapshot.py:37`、`common.py:65`；既有锁文件 |
| §2 分发与完整性 | 确认修订后的分层与信任边界 | 接受新增的原始字节/parsed dict 区别及 actor attestation 限制。当前 C 强制复验签名且只接受 `synthetic-test`，精确封装为两个 objects；该实现限制列入 D5 兼容表。 | `a_distribution.py:29` / `:61`、`signature.py:11`；既有 A/B 验证及隔离 wheel 报告 |
| §3 任务、装备、条件 | 需修订 D1—D3 | 写明 scope 类型、装备精确键及槽位表、条件字段 `requirement`、属性表位置，以及原生算子与 A 发布交集。当前未知装备要求键可能被忽略，不能笼统宣称均已拒绝。 | `validation.py:83`、`engine.py:330` / `:412` / `:524`、`conditions.py:22`、`projection.py:49` |
| §4 快照与授权 | 确认修订；补 C 精确映射附件 | 接受本机 revision 0 与分析提交正修订的分离、角色路径及 source_confirmed→unconfirmed。固定 UUID/键集合及成本空列表边界见 D4；新增材料/面板表示仍需新版本。 | `b_snapshot.py:15`—`:95`、`conditions.py:132`、`cultivation.py:14` / `:95` |
| §5 请求、结果、stdio | 确认修订后的关联层级及 ready 区别 | 修订版已将三元组限定于 B stdio 层；原生 C 错误可省略快照/代次。尺寸按整个 UTF-8 外层消息计，错误分层保留。当前 B builder 的 feedback 缺项是正向覆盖边界。 | `adapters/entry.py:47`、`common.py:95`、`engine.py:833`；B aa2a2b worker；既有 c4def3b 回放 |
| §6 下一轮样例与锁定 | 确认修订；采用下述矩阵 | 新不可变 release；三模式完整主/替代/无匹配。新增的 partial 库存锁定预期正确；成本/面板缺失只验降级。负向案例记录实际触达层。 | 旧 A 样例只有一模式、零装备要求；原报告明确有 3 项未覆盖 |
| §7 冻结与生产关口 | 支持 | 修订文档后记录生效摘要、目标能力和待发布组件；B S1 的 63 项不能替代 C 对新 A/B/C 固定集合的 S3 回放。生产关口独立保留。 | 阶段清单及已有 C handoff 的证据范围 |

## D1：scope 的键集合和值类型

附件应明确：`task.scope` 恰好含 `game_version`、`environment`、`mode_id`、`cycle_id`、`stage_id`、`stage_revision`；前五项为非空字符串，`stage_revision` 为排除布尔值的正整数，六项值与所选关卡及模板一致。`public_goal` 必须与一项已声明目标的完整对象相等。

当前 C 检查六字段存在并比较值，但 `_scope_mismatch` 只遍历这六个名称，不检查额外键；任务 scope 也没有独立的上述类型闭合校验。B 已在自己的复核中指出选择边界同类问题。最小跟进是 B 选择/构造边界与 C 新消费边界采用同一附件规则；当前发布产物不改标签冒充已经满足。

## D2：装备要求、kind/slot 与公共实体

### 当前原生形状与实际匹配

```json
{
  "teams": {
    "fixture:partition:upper": [{
      "slot_id": "fixture:team-slot:upper-1",
      "character_id": "fixture:character:a",
      "equipment_requirements": [{
        "kind": "relic",
        "slot": "fixture:equipment-slot:body",
        "public_type_id": "fixture:relic-type:body-1"
      }]
    }]
  }
}
```

这是字段附件片段，不是完整可执行包或真实游戏资料。公共同 release 实体需声明 `id=fixture:relic-type:body-1`、正整数 `revision`、`entity_type=relic`。B 物品的 `public_type_id` 对应它，`slot` 必须逐字符相同；`local_instance_id` 是另一个 UUID。本机物品不进入公共实体表。

- 要求数组位于 `variants[].teams[partition_id][].equipment_requirements`。
- 匹配键为 `kind`、`slot`、`public_type_id`、`public_type_ids`。`kind` 只支持 `light_cone` / `relic`；同一角色槽位的 `(kind, slot)` 对不能重复。
- `public_type_id` 表达单个类型，`public_type_ids` 表达类型列表。当前 `_equipment_matches` 对两者同存按**并集**匹配；都没有或列表为空时没有类型过滤。
- B adapter 从同 release 公共实体的 `entity_type` 得到 kind，保留原 slot 字符串，不作槽位重命名。类型未解析为 `light_cone` / `relic` 时跳过该物品并输出 `unresolved_public_equipment_kind`，仓库仍为 partial。
- C 没有原生全局 slot 枚举。现有 C demo 的 `body` 是合成值；B 当前公开档案路径输出 `light_cone` 或 `relic:<type>`，未知为 `relic:unknown`。不能据 demo 自动推出这些值互为同义词。

### 冻结附件的最小规则

1. S3 为公共要求及 B 合成快照提供同一张有限 `(kind, slot, public_type_id, entity_type)` 表，声明它是合成协议语义。真实槽位映射留给 S4；未知槽位不猜译。
2. 装备要求的语义键闭合为上述四键；若允许 `evidence_refs`，单列为非匹配元数据，并执行已有 revisioned 引用闭合。额外匹配键必须拒绝。
3. 接受修订候选明确的**两种限制同存时为 OR/并集**；不再要求互斥。S3 优先使用单一形式以减少样例歧义。exact 值须非空字符串，list 须非空、去重字符串数组；引用同 release 实体且实体 `entity_type` 与 kind 相符。无类型限制若允许，应作为明确形态；错误类型/空列表不能退化成无类型过滤。
4. 当前 C 0.3.0 只检查 kind/slot 对及通用引用，尚无上述完整闭合、类型和 kind 一致性校验。未知要求键不会自动变成 `unsupported_condition_field`。这是 C 新 wheel 的具体校验跟进，A 导出也应执行同一规则。修订版已正确要求 A 验证具体要求；请将 C 对应差异也加入 §7 有限适配清单。

## D3：条件字段与 A 发布交集

- 精确字段为 `requirement: "hard" | "soft"`；属性定义在 `manifest.attribute_definitions[attribute]`。定义含 `value_type`、`unit`、`phases`、`loadout_dependent`；类型集合为 `number/integer/string/boolean/array`。
- `measurement_context` 含 `phase` 与 `assumptions` 数组。条件值与注册属性的类型、单位、phase 对应；账号字段与该条件的单位/完整 context 比较，assumptions 顺序不影响比较。

| 层 | 已实现算子/主体 |
|---|---|
| C 原生 0.2 | `eq/neq/gt/gte/lt/lte/in/contains`；`team_slot/character/equipment_slot` |
| 当前 A v1 → C 显式映射 | 原始 `eq/ne/gt/gte/lt/lte/in`；仅 `ne → neq`。原始 `entity` 必须是声明的 character，再映射为 `character`；原始 `team_slot` 保留。 |
| 当前 A 通道不接受 | 原始 `neq`、`contains`、`not_in`、`equipment_slot`、team-wide 主体等未实现映射 |

C 原生 `equipment_slot` 条件另用 `subject.slot_id`、`subject.equipment_kind`、`subject.equipment_slot`，不是把要求的 `kind/slot` 直接改名复制。S3 可以用已支持的装备要求触发分配，无需引入这个尚未接通的 A 条件主体。

修订候选已正确拆分原生算子与当前 A 发布交集，C 确认这一修订。请在精确附件写明 A 的 character 主体实际是 `{"kind":"entity","entity_id":"<character entity ID>"}`，映射成 C 的 `{"kind":"character","character_id":"<same ID>"}`。新增映射需生产者 profile/capability 及 C 消费确认。公有规则不兼容与本地值 unknown 分开：原生无效变体可进入 `rejected_variants` 的 `invalid_variant`，而未知必需能力/原包完整性失败可使整个包拒绝；不应把每一种不兼容都规定成同一个顶层 code。

## D4：B snapshot 的实际可表达范围及预期

| 输入 | C 当前行为/附件应固定的解释 |
|---|---|
| 顶层 | 提交 C 分析时固定十键：`schema_id/schema_version/profile_id/snapshot_id/revision/generated_at/fields/ownership/coverage/equipment`；两个 ID 为 UUID，revision 为排除 bool 的正整数。B 的本机初始状态可为 0，提交边界原样拒绝 0，不加 1。这与修订候选一致。 |
| FieldFact | 精确七键：`value/status/source_kind/source_id/observed_at/confirmed_at/scope`。observed_at 带时区；confirmed_at 可为 null，否则带时区；scope 为字符串或 null。新增键会触发固定 profile 拒绝。 |
| 扁平角色路径 | `character:<完整角色实体ID>.<属性ID>`；必须唯一匹配 ownership 中的角色前缀；属性后缀保留。不能唯一解析则记 `unmapped_flat_field_path`。装备 facts 的键直接作为属性 ID。 |
| 状态 | `confirmed → confirmed`、`needs_review → unknown`、`conflict → conflict`、`stale → stale`。原 status/source/time/scope 作为 provenance 保留。 |
| 所有权/覆盖 | 原样保留 owned/not_owned/unknown；缺角色保持未知。observed path list 不变成完整覆盖；规范化固定 `roster=partial, inventory=partial, materials=unknown`。 |
| 物品身份 | `player_confirmed → player_confirmed`、`source_confirmed → unconfirmed`、ambiguous/unconfirmed 保持；UUID 不能重复。未确认/歧义只可能用于原持有者当前配装，不跨角色调装。 |
| 单位/面板 | 固定 serializer 没有 unit/context，所有 confirmed 数值也会在受支持条件中因 `missing_unit` 等保持 unknown；不从公共阈值或 scope 字符串补数据。换装后的相关角色面板没有匹配的确认 loadout view 时仍 unknown。 |
| 培养/材料 | 当前 adapter 不提供结构化 materials 或 loadout_views。存在培养要求但进度/适用依据不足时 cost 为 not_calculated；库存不足以确认时净缺口不计算。空培养列表的空 aggregate/零成本不能计作材料正向覆盖。 |

**锁定预期已在修订候选中消歧，C 确认。** 在当前 partial inventory 下，未锁定可用的实际调装，在锁定后可以变为 `confirmation_required`，而非必然 `no_feasible_variant`。C 禁止那次移动，但不能证明未观测仓库中不存在另一件装备。S3 应断言“锁定改变可用分配且不产生违规 action”；若要断言全仓库不可行，需要有依据的完整覆盖新表示。

当前 partial 分支的 pending reason 主要是 `inventory_coverage_incomplete`，不保证逐件列出锁定/身份原因。若冻结附件要求更细的分配诊断，应列为 C 新 wheel 的输出改进，并与覆盖未知原因分开。

原生培养正向计算还需整数进度属性、适用 subject/entity/unit/context，以及带 ID/revision/evidence/scope 的 `cost_rule.transitions`；每条 `from=n,to=n+1` 的材料整数数量覆盖完整区间。gross 汇总后才扣一次完整确认库存。现有 B 表示无法覆盖的正向项应明确未执行；单独在 C 原生测试中通过不能替代跨组件正向覆盖。

## D5：producer、摘要与信任接入

| 检查 | C 0.3.0 的实际限制 | 下一轮动作 |
|---|---|---|
| A producer | 仅 `b790a52...`、`00d4a584...`；source_proof 的 producer_package_version 必须为 `0.2.0` | 新 A 执行 commit、package version 及 source proof 一起复核并进入新 C wheel；`31e2665...` 是交付提交，不填成执行 producer。 |
| B producer | 仅 `045965bce4fbc38a3baa79b594535c9dd983d776` 与 `starhelp.desktop.snapshot.045965b` | 原固定文件可保留其来源。若由 aa2a2b 等新代码生成新数据，记录实际 producer；先证明字段/语义/编码，再由 C 显式支持该 tuple。host commit 单独列。 |
| 封装 | 当前 exact objects 集合是 `native-release:<release>` 和 `planner-view:<release>`；分发 required capabilities 精确为既有 distribution v1 | 新对象、能力、原生/投影布局须先声明，不因 profile 字符串相同而放行。 |
| 批准出处 | source_members、approved_reviews 覆盖精确原始成员；review hash/revision、publication audit、evidence 闭合与发布状态均检查 | A 新样例通过自己的真实导出入口提供这些字段；不补 approved。投影当前证据 revision 1 映射也是版本限制。 |
| 三层摘要 | 原始传输及 B objects 为普通 SHA-256 hex；C 成员用 `sha256:` + `sha256-json-v1`，投影 manifest 自身 hash 另列；A 原生算法另标 | 各自保存原值及所属层。新字节编码有独立 capture/hash；不重排已锁原始输入。 |
| 签名 | C 强制按 caller-pinned key 复验 Ed25519；purpose 目前只接受 `synthetic-test`，签名依赖为可选 extra `cryptography>=43,<47`，缺失即拒绝 | S2 技术路径可以保持现状；S4 生产 trust policy 需独立设计和版本化支持，不把 purpose 改成 production 就宣称可用。 |

确认修订候选新增的批准证明信任边界：当前账本证明 producer 所断言的精确 revision/hash 批准及发布事件；没有导出 actor identity，也没有由 C 独立验证“四眼分离”。C 不要求 publisher 与作者/审核者为不同人；A 本地额外限制的修正不要求 C 增加 actor 字段。真实内容批准和未来外部 actor attestation 各有独立关口。

既有 sorted+newline 和 native-order compact B 样例分别固定为 `a0c9fd98...` 与 `7bf8f156...`，后者由固定 045965b 实际序列化器独立产生，值相同且原文件均保留。这证明那两个具体编码，不是任意当前 serializer 的普遍兼容证明。

### 是否需要新 schema/profile

- 新 A commit/package，且字段与语义完全保持已约定子集：必须发布新 C 组件/wheel 并更新显式 producer 兼容表；不必仅为 commit 变化重命名所有 wire schema。
- 同语义 B 字节编码或新执行提交：独立记录实际来源/编码/hash；新 commit 需要 C 显式兼容，不用旧身份替新代码背书。
- B 增加 unit/context、材料完整性或最终配装面板：当前精确键集合不能表达，需新 snapshot schema/profile 与显式 adapter/capability。
- A 增加当前发布通道不支持的算子、主体或新执行要求：需新增/修订生产者 profile/capability 后再消费。
- D1/D2 的输入校验收紧及诊断改进：列入新 C wheel。是否复用原生 profile，取决于协调方是否将其定为既有约定的类型检查修正；有新规则语义时必须增加版本能力。当前已签名包保持原样。

## D6：结果层级、传输界限与反馈

1. `analyze_producers` 返回 `ProducerAnalysisResult`。适配失败是顶层 error 且 `analysis=null`；原生失败保留在 `analysis.error`。外层 `component_version=0.3.0` 与原生 `planner_version=0.2.0` 独立。
2. 当前原生错误和适配错误不保证附齐 snapshot_revision/generation。候选的关联三元组应限定为**B worker 输出的 stdio result**：仅从已验证 wrapper 补缺值，已有矛盾值保留并由 parent 拒绝。aa2a2b 静态代码保留该修正；既有运行证据是 c4def3b，不宣称本轮重放了 S1。
3. 8 MiB/16 MiB 指整个外层请求/响应 UTF-8 编码。外层同时带解析 bundle 与 raw_json，转义和重复数据也计入。C 另有单个 raw_json 8,000,000 字符、100,000 JSON 节点、深度 48 的限制；不能将这些限制当作同一字节预算。
4. 未执行、不支持、传输失败与领域失败分别保留；拒绝新必需能力，未知错误不改写为成功。引用和 release 相关性由 B 报告阶段再检查；no-match/withdrawn 不生成成功报告。
5. C 当前可选顶层 `feedback` 会传给有限原生排障器；B aa2a2b 的 builder 未暴露 feedback 参数。S2 不宣称该端到端正向路径已交付，后续本地表示需明确字段状态、单位/语境和能力；不学习阈值、不回传 A。

## S3 未来回放矩阵（本轮均未新增执行）

| 案例 | 必要生产者输入 | 必须断言的结果/边界 |
|---|---|---|
| 三模式各主方案/完整替代/无匹配 | A 新不可变 release；每 mode 完整分区/槽位、goal、main/alternate、批准与证据 | 仅完整已审核组合；无匹配只资料/缺口；与旧 rel_fixture_0001 分开 |
| player_confirmed 实际移动 | A 非空装备要求和同 release 类型；B 两个已拥有角色、实例当前穿在非目标角色 | 有 from/to/实例 action；当前与调装分类准确 |
| 同输入只改变锁定 | 同一 public bundle、同一 snapshot，仅 task.locked IDs 改变 | 可用调装消失且无违规移动；partial coverage 可待确认，不伪证全仓库不可行 |
| 同类型不同实例/重复占用 | 两个 UUID 与同公共类型；另例联合队伍竞争同一 UUID | 两个副本可分别分配；同一实例 stage-wide 不重复 |
| ambiguous / source_confirmed | 相同 owner/type/slot，改变实际 B identity 模型后由 serializer 输出 | 不跨角色分配；原角色当前配装按已知信息单独判断 |
| unknown / not_owned 与角色限制 | B ownership 真实 serializer 案例，task fixed/excluded | 未知仅待确认；确认未拥有及已知硬冲突不放宽 |
| 公共要求 malformed | A 测试产物明确包含未知键、错误类型/类型 kind 矛盾等 | 新 C 明确拒绝该规则；不能将未知类型键忽略成无类型限制 |
| scope/谓词/主体不兼容 | 六字段错值/类型/额外语义；A/C 支持交集外规则 | 明确拒绝相应层，不标为本地条件 unknown |
| 缺值/冲突/stale/缺单位语境 | B 固定状态及真实可表达字段 | hard unknown 待确认，soft unknown 警告；confirmed 数值不自动达标 |
| 换装相关面板与材料缺失 | A 非空相关条件/培养要求；B 当前表示缺项 | unknown / not_calculated；空 aggregate 不计正向材料覆盖 |
| 完整成本/净缺口正向 | 只有新版本 B 表示与完整适用 A 成本依据到位才执行 | gross 与一次扣库存均可复核；未到位明确未执行 |
| 篡改/错误 key/缺依赖/跨 release | A 实际产物或明确的测试负向生成入口，逐份锁原始 hash | 记录实际触达层；早在 transport hash 拒绝的案例不冒充 dependency 分支验证；不修损坏 hash 凑通过 |
| 撤回及迟到授权代次 | 同 release 引用与 latest-known validity；B lifecycle 场景 | 无可用方案/无成功报告；完整错误关联；撤权后拒收迟到结果 |
| 报告与不可变回放 | 同一锁集合、隔离安装新 C wheel、B S1 固定 host/候选 | 引用/版本/输入不变；报告暂存与主动保存分开；源码/包/样例验收分列 |

下一轮锁文件至少分列：A 执行代码/包版本/产物提交、release、全部原始文件 hash、profile 与必需能力、审批/发布出处；B serializer commit/profile/编码及 host/候选；C wheel 版本/hash/源码提交/原生规则；测试 key 用途、请求/预期/命令和实际校验层。未公布的新 A producer 仍由当前 C 正常拒绝。

## 已有证据入口及本轮限制

- [隔离 wheel 62 项测试记录](../../interop/reports/c-0.3.0-installed-tests.json)：既有运行，不是本轮重跑。
- [原固定 A/B producer 回放](../../interop/reports/c-0.3.0-wheel-replay.json)：12 passed、3 not_exercised；仍不覆盖三模式/非空装备。
- [c4def3b 桥接与候选观察](../../interop/reports/c-0.3.0-b-c4def3b-bridge.json)：九案例×两个 transport，18 passed。
- [c4def3b 源码与临时报告](../../interop/reports/c-0.3.0-b-c4def3b-source-bridge.json)：9 bridge + 2 report staging；固定 compact snapshot 编码另有 producer proof。
- [当前生产者接口说明](../producer-adapter-api-v0.1.md)、[原生 0.2 说明](../local-profile-v0.2.md)、[桥接证据范围](../desktop-bridge-evidence-v0.1.md)。

上述源码差异是静态复核结论；本轮没有运行新反例、测试、构建或任何真实账号/网络资料流程。协调方可从本文件及 C handoff 直接读取回执，无需用户转发。
