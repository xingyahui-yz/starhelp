# 星铁公开知识库：SQLite 结构设计

> 状态：逻辑设计 v0.2，用户已确认方案；本次仅更新文档，未创建数据库、执行建表或采集网络内容。为保持既有链接，文件名保留 v0.1。
> 日期：2026-10-14
> 需求依据：截至 2026-10-14 用户确认的开发补全决策，以及《长期开发方案.md》和《星铁公开知识后端-开发方案-v0.1.md》。
> 本文是逻辑表结构、关系与约束设计；字段类型、建表 SQL、迁移和检索扩展在实施阶段确定。

## 1. 与 StarHelp 的边界

本后端提供公开基础资料、攻略候选、实用知识和 RAG 证据。SQLite 保存业务记录、资料修订、知识与索引元数据；向量索引的实际存储方式待选型。

- 玩家 UID/区服、凭据、账号快照、库存、构筑、战绩、账号派生特征、私有攻略报告和含账号信息的会话原文均不进入此数据库，也不进入知识后端查询参数、模型输入或日志。
- 本库中的角色、装备、配队和面板阈值是公开资料或攻略条件，不是任何玩家的持有记录。
- 授权后的 UID/区服公开面板查询由桌面端直接访问所选档案服务，UID 查询是单独授权的数据源请求，不经过知识后端。导入资料、字段冲突处理、账号数据加密和授权撤销由本机负责。
- StarHelp 的本地规划核心负责账号归属、装备冲突、条件匹配及通关目标检查；本库返回可追溯的公共证据、完整队伍变体与审核规则，不接收本地匹配结果。
- 桌面端缓存的最近两个有效发布版本仅含公开知识包；本机私有账号快照和报告使用独立存储，不混入本后端数据库或索引包。
- Nanoka 是完整人物、怪物资料的暂定来源；米游社、B站是攻略来源。热度来源为百度指数、微博指数、微信指数。
- 结构支持光锥、遗器、玩法和关卡资料，是为兼容 StarHelp 需求；对应数据源、覆盖范围与采集权限仍需确认，不因设计字段自动增加抓取范围。
- StarRailRes 可作为未来结构化资源 Adapter，独立管理资源包版本。此设计不导入上游代码或认定其数据源已经接入。

## 2. 四种版本与状态

必须分别保存游戏版本、来源资料修订、结构化资源包版本和知识索引版本，不共用一个 version 字段。

资料环境 `environment` 为 `live / beta / unknown`；实装状态 `release_status` 为 `released / unreleased / unknown`。二者独立：未来正式服预告可以是 live + unreleased，测试服对象可以是 beta + released。

对象身份保持稳定；环境、实装状态、属性和技能绑定到对象的具体资料修订与适用范围。测试服技能变化或正式实装时新增修订，保留历史资料。

默认生产检索使用 live + released，并要求适用的游戏版本；beta、unreleased 或 unknown 仅在显式请求对应范围时参与。未知版本不能偷偷并入当前版本。默认不跨环境、跨周期自动回退；需要回退时返回降级说明。

## 3. 来源与作者

下列 id 均为内部主键；`*_id` 为对应外键。日期字段在存储层采用统一 UTC，展示层按客户端时区转换。

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `sources` | id、name、platform、source_role、base_url、adapter_kind、enabled | role 区分基础资料、攻略和热度；来源被禁用不删除历史证据 |
| `source_policy_revisions` | id、source_id、allowed_domains、allowed_paths、permission_status、terms_reference、robots_check、rate_policy、storage_policy、checked_at | 记录来源策略历史；未确认、受限或不允许的处理方式不能发布内容；来源配置不是任意 URL 执行权限 |
| `authors` | id、source_id、external_author_id、display_name、profile_url、manual_state | UNIQUE(source_id, external_author_id)；不能凭同名合并跨站作者 |
| `author_priority_events` | id、author_id、document_id、knowledge_revision_id、analysis_run_id、review_id、index_release_id、event_kind、delta、reason、policy_version、idempotency_key、created_at | 有用知识加分事件仅在审核发布后形成；同一内容跨发布/回滚不能重复加分；人工调整以独立事件留痕，初期无暂定事件与自动衰减 |

作者优先级、可信等级和流量是三个独立概念。来源角色也不能直接证明其为官方或其内容正确。

初始重点作者名单人工配置，以平台稳定作者 ID 管理；允许人工提升、降级和停用，不按同名跨站自动合并。作者与热度模块独立服务内容发现和选题，不能成为基础资料、知识或攻略模板发布的必经阻塞项。

## 4. 基础资料、别名与玩法周期

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `game_versions` | id、version_key、display_name、release_at、status | 使用稳定版本标识，不按字符串大小直接判断新旧 |
| `game_entities` | id、entity_type、canonical_name | type 支持 character、enemy、light_cone、relic_set、skill、mechanic、attribute；名称不是主键 |
| `entity_source_keys` | id、entity_id、source_id、entity_type、external_key、mapping_status | UNIQUE(source_id, entity_type, external_key)；entity_type 与关联实体一致；跨来源映射需要明确对应依据 |
| `aliases` | id、normalized_alias、language | 一个别名可以有多个实体候选，不强制全局唯一映射 |
| `entity_alias_links` | alias_id、entity_id、version_id、environment、mapping_status | 同名、简称歧义由检索上下文消解；未确认映射不自动绑定 |
| `entity_revisions` | id、entity_id、game_version_id、environment、release_status、payload_schema_version、payload_json、content_hash、supersedes_id、observed_at、validity_status | payload 保存该类实体的结构化资料；修订追加保存；同一版本不同证据可并存，不能用采集较晚代替可信度判断 |
| `entity_revision_evidence` | entity_revision_id、document_revision_id、locator、evidence_role | 原始出处可追溯；多个来源可以支持或反驳同一资料修订 |
| `entity_relations` | id、subject_revision_id、relation_kind、object_entity_id、qualifier_json | 表达角色拥有技能、敌人使用技能等关系；关联对象须在同一检索范围内解析到合适修订 |
| `resource_releases` | id、source_id、release_key、schema_version、hash、observed_at、coverage_json、status | 结构化资源包与网页修订分开管理；记录实际覆盖范围 |
| `resource_release_members` | resource_release_id、entity_revision_id | 记录资源包成员；只有完整验证后才启用该资源版本 |
| `game_modes` | id、mode_key、display_name | 混沌回忆、虚构叙事、末日幻影独立标识 |
| `mode_cycles` | id、mode_id、external_cycle_key、environment、game_version_id、starts_at、ends_at、status | UNIQUE(mode_id, environment, external_cycle_key)；未知时间可为空，不自行推算 |
| `stage_revisions` | id、cycle_id、external_stage_key、revision_no、game_version_id、rules_json、environment_effects_json、reward_conditions_json、status | 绑定玩法周期与版本；公开规则与玩家战绩分别处理 |
| `stage_enemy_groups` | id、stage_revision_id、side、wave_no、enemy_revision_id、count、condition_json | 支持上下半及波次；玩法不具备上下半时使用其实际结构，不强行补造 |
| `stage_evidence` | stage_revision_id、document_revision_id、locator、evidence_role | 关卡规则与环境效果均有来源 |

`payload_json` 只存版本化、经校验的类型特定字段，不用来代替实体 ID、版本、作者、证据或其他核心关联。角色技能、怪物行动、属性和抗性等详细字段在资料源覆盖验证后定义。

## 5. 原始内容、分析与上下文

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `documents` | id、source_id、external_content_id、canonical_url、author_id、source_state | 同站外部内容 ID 优先去重，URL 规范化作为补充；来源删除标记状态而非抹除出处 |
| `document_revisions` | id、document_id、revision_no、title、published_at、fetched_at、content_type、raw_reference、clean_text、content_hash、trust_tier、permission_policy_revision_id、cleaning_version、validation_status、coverage_json | 默认保存最小许可摘录、出处、定位和哈希；仅许可明确时保存全文/快照；网页、视频字幕与简介区分类型和覆盖 |
| `contexts` | id、game_version_id、environment、release_status、mode_id、cycle_id、stage_revision_id、coverage_status | 表达一组适用范围；关卡、周期、玩法、版本必须一致；通用内容可无玩法，未知范围仍明确标记 |
| `document_context_links` | document_revision_id、context_id、locator、mapping_status | 同一攻略可以覆盖多个版本或玩法；范围标注可绑定具体正文位置 |
| `document_entity_mentions` | id、document_revision_id、entity_id、context_id、locator、resolution_status | 记录人物、怪物等实体引用，不将一个视频默认绑定所有角色 |
| `keywords` | id、group_key、canonical_term、definition、status | group 为内容类别、关联对象、战斗问题、适用范围、热度查询词；实体词链接实体而非仅保存字符串 |
| `document_keyword_mentions` | id、document_revision_id、keyword_id、entity_id、locator、extraction_run_id、confidence、review_status | 模型提取与人工调整留痕；保留原文依据 |
| `duplicate_links` | id、document_revision_id、other_revision_id、kind、similarity、decision_status、reason | 转载、近似攻略与视频/图文转写保留各自出处；不因近似直接删除证据 |

内容类别为多标签，暂定配队攻略、角色攻略、怪物与战斗机制、实用战斗技巧。可操作方法摘要存于分析结果或知识修订，不能仅靠标题生成事实。

## 6. 流量、热度、模型评价与人工调整

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `traffic_observations` | id、document_id、metric_key、value、observed_at、window_start、window_end、availability、source_reference | 指标按来源实际能力记录；缺失为 NULL + 状态，不是 0；不跨平台直接比较裸数值 |
| `trend_queries` | id、source_id、query_text、context_id、window_start、window_end、requested_at、match_status、query_policy_version | 查询词与匹配范围可复核；不把角色总热度直接认作某条技巧的热度 |
| `document_trend_links` | document_revision_id、trend_query_id、match_kind、match_status、reason | 一次查询可服务多个相关条目；相似词不等于同一趋势 |
| `trend_observations` | id、trend_query_id、metric_key、value、bucket_start、bucket_end、availability、fetched_at、response_reference | 保存趋势序列和失败状态；不可用平台不会生成虚假验证成功记录 |
| `scoring_policy_revisions` | id、policy_key、revision_no、dimension_definitions_json、weights_json、normalization_json、gate_rules_json、calibration_status、effective_at | 评分规则版本化；完整与部分指标内容分组；部分组不计算综合选题分，组内按发布时间排序并标记缺项 |
| `analysis_runs` | id、document_revision_id、context_id、task_kind、provider_name、model_version、prompt_version、scoring_policy_id、input_hash、output_json、status、created_at | task 区分关键词、筛选、评分、入库判断；不保存模型服务凭据；JEV 具体服务仍待确认 |
| `assessment_dimensions` | id、analysis_run_id、dimension_key、score、probability、data_status、reason、evidence_locator | 模型质量维度按 0～5 级保存；数据计算维度保存规范化值与计算依据；概率与分数不混用 |
| `human_reviews` | id、document_revision_id、analysis_run_id、decision、override_json、reason、reviewer_key、created_at | 保存模型原结果与人工修改；可调整候选、标签、适用范围与评分；形成有效结果投影，不篡改原评价 |

已确认的规则：

- 选题基础分：热度与趋势 30%、原内容流量 20%、实用价值 25%、新颖性 15%、版本时效性 10%。
- 最终选题分：95% × 选题基础分 + 5% × 作者优先级规范化分；统一映射到 0～100。作者优先级规范化方法待样本确定。
- 知识保留价值：准确性 30%、证据充分程度 25%、可复现性 20%、条件完整性 15%、补充价值 10%。
- 入库判断另存概率、模型信息和校准状态，不能将保留价值分数除以 100 当作入库概率。
- 热度数据缺失时，完整与部分数据分组展示；缺失不填零、不重分配权重。部分组不计算综合选题分，按发布时间排序并注明缺项；实用知识继续独立评价与发布。
- 入库概率未校准时，模型只产生入库候选，由人工批准具体知识修订后才允许进入发布集合；批准记录与模型评价分别保存。
- 版本明确、来源可追溯、关键结论有依据为入库必要条件；关键机制错误或证据不足进入待核实。
- 重点作者加分仅来自已审核发布的有用知识，并生成幂等、可追溯事件；模型筛选阶段不产生暂定加分事件。初期无自动衰减，人工提升、降级、停用与错误证据留痕；具体增量和阈值待样本校准。

## 7. 正式知识、证据与冲突

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `knowledge_items` | id、knowledge_type、canonical_title、topic_key | 表示知识身份；type 为技巧、配队、机制说明等，不保存私有账号方案 |
| `knowledge_revisions` | id、knowledge_item_id、revision_no、summary、body、payload_schema_version、structured_payload_json、assessment_run_id、review_id、status、supersedes_id、created_at | 追加修订；status 区分 draft、pending_review、approved、quarantined、withdrawn；未通过质量门槛不进入已发布索引 |
| `knowledge_evidence` | id、knowledge_revision_id、document_revision_id、locator、excerpt、claim_key、relation_kind、trust_state | relation 为支持/反驳/限定条件；一条知识可关联多来源，一份攻略可产出多条知识 |
| `knowledge_context_links` | knowledge_revision_id、context_id、claim_key | 具体结论的版本、玩法周期和适用条件可细分；避免整篇攻略被误判为全部适用 |
| `knowledge_entity_links` | knowledge_revision_id、entity_id、role、context_id | 队伍成员、替代角色、装备与敌人均使用稳定 ID |
| `strategy_templates` | id、knowledge_item_id、template_key、mode_id | 公共攻略模板的稳定身份，支持三种高难模式；不保存玩家匹配结果 |
| `strategy_template_revisions` | id、template_id、knowledge_revision_id、context_id、payload_schema_version、required_capabilities_json、complete_payload_json、content_hash、status | 模板修订绑定公共知识、版本/周期/关卡和证据；完整对象包含队伍、条件、机制、打法与已审核变体引用 |
| `strategy_variant_revisions` | id、template_revision_id、variant_key、context_id、complete_payload_json、evidence_status、review_id、content_hash、status | 每个替代方案保存整队完整变体、条件与证据；多处替代必须整体审核，不能在客户端叠加孤立替换规则拼成未经审查队伍 |
| `troubleshooting_rule_revisions` | id、knowledge_revision_id、context_id、payload_schema_version、required_capabilities_json、condition_payload_json、advice_payload_json、review_id、content_hash、status | 公共排障规则经审核，限定触发条件、适用范围、建议及证据；只用于本机解释和匹配，不接收玩家失败记录 |
| `knowledge_reviews` | id、target_kind、target_revision_id、analysis_run_id、expected_revision、decision、override_json、reason、reviewer_key、created_at | 按单条知识、完整模板/变体或排障规则审查；目标恰好一个且明确，批准绑定不可变内容，不自动发布 |
| `conflict_groups` | id、claim_key、context_id、status、resolution_reason、resolved_at | 相同范围内矛盾归组；不同版本机制差异不自动判为事实冲突 |
| `conflict_members` | conflict_group_id、knowledge_revision_id、entity_revision_id、document_revision_id、claim_locator、position | 至少有一个明确修订目标；解决冲突保留依据，不以高流量或较晚采集自动胜出 |

公开配队的完整 payload 包含：上下半或玩法实际分区、完整队伍、完整替代变体、光锥和遗器建议、跨队调装条件、速度/面板阈值、行动顺序、技能点/终结技原则、机制应对、失败条件及证据映射。条件的公共证据状态 `evidence_status` 可表达 confirmed / suggested / unknown；它描述证据是否支持条件，不代表玩家已经满足条件。玩家条件匹配状态 `match_status`、匹配依据和缺项只在本机计算，不存本库。

条件与排障规则采用受限的声明式表达：字段、单位、比较操作和条件组合必须通过版本化 schema 与客户端能力列表校验，不含脚本、任意函数、可执行指令或外部工具调用。客户端遇到未知条件/能力不得默认为通过；完整语义、枚举和字段名在接口冻结时确定。任一替代改变队伍协同、装备/光锥、阈值或打法时，发布完整审核变体，不发布可任意连用的替换片段。

第 6 节现有趋势表的 `match_status` 仅表示公共查询词与内容范围的匹配，不表示玩家账号条件匹配；接口冻结时分别命名，避免两种语义混用。

默认高可信事实不能被低可信建议覆盖。新知识须经过清洗、去重、版本/周期校验、证据校验与冲突处理；流量和选题潜力不能替代这些门槛。

## 8. RAG 切片与可回滚索引

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `chunks` | id、document_revision_id、knowledge_revision_id、entity_revision_id、stage_revision_id、context_id、claim_key、ordinal、text、locator、content_hash、chunking_version、trust_tier、status | 每片段具有一个明确父修订；完整元数据可通过父记录关联，保留原文定位和适用范围；片段拆分不能丢失限定条件 |
| `embedding_models` | id、provider_name、model_key、model_version、dimension、distance_metric、status | 记录向量模型配置，不存密钥；不同模型和维度不能混搜 |
| `embedding_records` | id、chunk_id、embedding_model_id、input_hash、vector_reference、status | 实际向量可在选定扩展或外部索引；SQLite 保存引用与完整性元数据 |
| `index_releases` | id、release_key、parent_release_id、status、manifest_schema_version、payload_schema_versions_json、required_capabilities_json、keyword_index_reference、vector_index_reference、manifest_hash、created_at、published_at、coverage_json | building / validated / published / failed；封存完整对象、检索索引及依赖清单；已发布清单不可原地修改 |
| `index_release_members` | index_release_id、member_kind、member_revision_id、entity_revision_id、stage_revision_id、knowledge_revision_id、template_revision_id、variant_revision_id、troubleshooting_revision_id、document_revision_id、chunk_id、embedding_record_id、object_hash、object_reference、required | 成员类型明确指向一个不可变主目标；实体/关卡/知识/模板/完整变体/排障规则及其证据组成闭合依赖，片段与向量是派生检索成员；具体外键实现待冻结 |
| `active_index` | channel_key、index_release_id、updated_at | 独立 live 与 experimental 通道；通过原子切换启用和回滚，游戏版本过滤仍不可省略 |
| `publication_events` | id、index_release_id、operation_kind、expected_active_release_id、operator_key、permission_key、reason、result、created_at | 记录构建、校验、发布、禁用与回滚；审核权和发布权分开，初期可由同一维护者持有，但操作与审计分别保存 |

关键词检索建议采用 SQLite FTS5，索引经校验的标题、正文与别名；FTS 是派生检索结构而非事实主表。中文分词方案、FTS5 可用性、向量组件和重排方式在实施前验证。

发布顺序：选择已批准的完整对象 → 构建对象及证据依赖清单 → 完成派生切片与向量 → 校验证据、许可、范围、schema/capabilities、对象哈希和依赖完整性 → 封存发布包 → 经独立发布权限操作原子切换 active_index。实体、关卡、知识、模板、完整变体和排障规则使用同一发布版本；检索片段只用于召回和定位，不能作为本地规划器拼装攻略的完整对象来源。发布失败保留上一个成功版本，回滚不删除新采集记录或评分记录。

manifest 至少声明发布 ID、父版本、包 schema、各类对象 schema、所需客户端能力、适用范围/覆盖、新鲜度信息及 members。每个完整成员有明确类别、身份/修订、内容哈希、获取位置和依赖；模板引用的实体、关卡、变体与证据必须同包可解析。缺失完整对象、依赖不闭合或客户端不支持必须能力时，拒绝切换或返回明确的受限状态，不能补取另一发布版本的“最新”对象拼接。

桌面端可校验并原子同步两个有效公开发布包；这些缓存不包含私有账号快照/报告。包清单与查询结果均受最新禁用记录约束；离线缓存显示其最近一次禁用校验时间与过期状态，不能声称离线时已获知新的服务端禁用。

失效许可、必须删除的内容及被隔离的有害内容还需在查询时受最新禁用状态过滤；回滚不能把它们重新暴露。需要删除正文或向量时，保留合法的最小审计记录，并明确旧索引的可用性变化。

## 9. 更新任务与二十条采集规则

| 表 | 核心字段 | 关系与约束 |
|---|---|---|
| `collection_policy_revisions` | id、source_id、revision_no、categories_json、total_limit、priority_quota、discovery_quota、per_author_limit、quota_transfer_policy、query_templates_json、effective_at | 米游社和B站分别保存 20 / 8 / 12 / 3；8/12 为基础名额，重点缺口只可转给普通；Nanoka 采用全量发现与资料变更更新，策略分开 |
| `update_runs` | id、trigger_kind、requested_scope_json、collection_policy_ids、scoring_policy_id、state、started_at、finished_at、result_summary_json、published_index_id | button / schedule / query_refresh；用户刷新不能绕过来源策略；定时任务只是接口支持，尚未创建自动化 |
| `update_tasks` | id、run_id、source_id、stage、target_key、state、attempts、next_retry_at、error_code、error_summary、started_at、finished_at | 来源失败隔离、有限重试；日志不存凭据或完整私有上下文 |
| `run_candidates` | id、run_id、document_id、document_revision_id、selection_bucket、priority_snapshot、rank、selected、selection_reason、review_id | 每来源最多二十个不同 document；配额按去重后的条目计数；同作者每轮最多三条 |
| `update_events` | id、run_id、task_id、event_kind、payload_summary_json、created_at | 记录阶段变化、人工继续、发布与回滚等审计事件 |
| `source_discovery_runs` | id、source_id、run_id、expected_count、discovered_count、verified_count、failed_count、completeness_status、manifest_reference | 对基础库全量覆盖核验；无法枚举全站时标记完整性未知，不宣称完整 |

配额流程：各类别分别搜索 → 合并并识别同站重复条目 → 重点八条/普通十二条基础名额 → 各桶内按已确认规则选最新相关内容 → 重点不足部分转给普通搜索 → 每来源总计最多二十条、同一作者最多三条。普通十二条不是禁止承接重点缺口的硬上限；新来源尚无重点作者时，普通搜索最多二十条。

如果可用相关内容不足、普通桶不足或作者上限导致无法填满，记录缺口；不重复凑数、不悄悄放宽三条上限。普通不足不反向补给重点桶，允许实际结果少于二十条。

作者优先级与普通发现名额分别保留，避免已入库作者包揽所有来源。跨站转载可以作为补充证据，但是否占用采集名额及是否补采需要独立去重策略，不能与站内同链接去重混为一谈。

知识更新主流程：按来源策略采集/刷新 → 许可校验、清洗、去重和证据提取 → 版本/周期/实体核验 → 形成知识、完整模板/变体或排障规则候选 → awaiting_knowledge_review → 人工批准、拒绝或补证据 → 对已批准集合构建/校验 → 独立发布操作。热点/作者模块另行执行筛选复核、热度验证、评分与排序，不阻塞基本知识发布。重试从失败任务继续，已确认记录不能被覆盖。

受控问题检索可产生短期候选证据，但不会绕过人工复核和发布门槛自动变成永久知识。没有人工继续的定时任务停在待复核状态，除非后续单独确定自动复核策略。

## 10. 完整性、索引与查询契约

### 10.1 核心约束

- 实施时启用外键校验；采用类型、枚举、范围与 JSON schema 校验。概率限 0～1，模型维度分限 0～5，归一化分限 0～100。
- 修订编号在父对象内唯一；索引成员、资源包成员和证据关联避免重复。
- 多目标关联（如 chunk 父修订、冲突成员目标）需以 CHECK 或应用校验明确至少/恰好一个目标，不能成为无出处的孤立记录。
- 含玩家账号字段或派生特征的内容由客户端阻止进入知识请求；后端边界也拒绝这些内容，不将其保留在业务表或日志。原始网页文本保持数据属性，不能成为执行指令。
- 权限未知、覆盖未知、版本未知、指标不可用、冲突未解决均有显式状态；不存在记录不等于事实为否。
- 发布读请求绑定单一 index_release_id；完整实体、关卡、知识、模板、变体、排障规则及证据均从该发布清单解析，不能通过 chunks 或跨发布的“最新”对象拼凑。
- 每个正式对象批准绑定其具体不可变修订与内容哈希；发布另需发布权限。热度分、作者分或模型置信度不能替代知识批准，也不能成为本地账号条件已满足的证明。

### 10.2 建议查询索引

- 文档：source_id + external_content_id、canonical_url；修订：document_id + revision_no、content_hash。
- 实体映射：source_id + entity_type + external_key；别名：normalized_alias；资料修订：entity_id + game_version_id + environment + release_status。
- 周期：mode_id + environment + external_cycle_key；关卡：cycle_id + external_stage_key + revision_no。
- 上下文：game_version_id + environment + mode_id + cycle_id；知识修订：knowledge_item_id + revision_no + status。
- 流量/趋势：目标 ID + metric_key + 统计时间；任务：run_id + stage + state；索引成员：index_release_id + member_kind + member_revision_id。
- 模板/变体/排障：稳定身份 + 修订号 + context_id + status；批准：target_kind + target_revision_id；发布审计：index_release_id + operation_kind + created_at。

### 10.3 给 StarHelp 返回的数据

基础资料检索、知识检索与选题查询分开。RAG 结果至少返回：

- 实体/知识/切片稳定 ID 和对应修订 ID；
- 证据文本、原文定位、URL、标题、作者、来源等级和许可状态；
- 游戏版本、资料环境、实装状态、玩法、周期和关卡；
- 发布时间、采集时间、最近验证时间、覆盖范围；
- 有效状态、冲突与未验证假设、模型置信度及校准状态；
- 本次 index_release_id 和新鲜度/回退说明。

选题潜力不是 RAG 事实排序的唯一标准。RAG 主要按问题相关性、适用范围、证据等级、有效性与新鲜度检索；选题分可用于创作候选排序。

### 10.4 公共完整模板 API 与索引包契约

具体 URL、字段类型与 schema 在接口冻结时确定，本节只定义职责与语义：

- 发布发现接口返回可用公开发布版本、manifest、覆盖范围与所需能力，不接收 UID、账号快照、装备清单或本地匹配结果。
- 公共检索接口只接收游戏版本、环境、玩法、周期、关卡、公共关键词及明确的 index_release_id；命中返回对象 ID/修订与证据定位，客户端据此获取完整对象。
- 完整对象接口在指定发布版本下返回模板及整队变体、所依赖的实体/关卡/知识/排障规则、条件语义、证据映射、哈希、schema/capabilities 与有效状态。它不只返回 chunks，也不根据玩家资料生成或存储个性化模板。
- 快照包接口提供与 manifest 一致的完整公开对象及派生检索索引。校验不通过、对象被最新规则禁用、范围不匹配或能力不兼容时返回显式状态；失败不能静默换版本。
- 公共条件的 evidence_status 与本地 match_status 分开；后端只发布前者及声明式条件，本机依据玩家资料判断满足、不满足或未知，并形成私有报告。
- 用户查询时补搜的未审核证据可以明确标记后用于临时公开回答并进入候选队列，不能自动变为正式模板或写入已发布成员清单。

## 11. 仍需确定的实施事项

1. 数据源可采集字段、许可与可用接入方式；不能依据文档字段假定网站/API 已支持。
2. Nanoka 对人物和怪物完整枚举的方式，以及光锥、遗器、关卡等补充资料来源。
3. 查询词典、实体映射、玩法周期 ID 与 StarHelp 本地域 ID 的兼容策略。
4. 流量和指数的规范化及完整数据组评分可比性；部分指标组按发布时间排列且不计算综合选题分，知识独立评价/发布已确认。
5. 作者优先级规范化、已审核发布事件的增量/阈值、入库概率阈值和校准样本；无暂定加分事件、初期无自动衰减已确认。
6. 中文关键词检索、向量存储、嵌入模型、重排、SQLite 并发及后端部署条件。
7. 正文/字幕保存策略、备份与删除保留期限、来源撤销对历史引用的处理。
8. 完整模板/整队变体/排障规则的字段、条件语义、单位、schema/capabilities 版本、领域 ID 对接、manifest 封装和公共 API 契约。
9. 索引包体积、离线检索能力与分发完整性校验方式；最新禁用策略、离线时效提示和删除要求的落地方式。

以上未确定项均保留为设计缺口，不阻止当前表关系设计，也不视为自动授权实施。

## 12. 后端流程设计补充

参见《星铁公开知识后端-开发方案-v0.1.md》的流程补充：保留来源能力快照、命令幂等、任务租约/检查点、人工复核并发版本以及按单条知识评价/批准的目标关系。本文增加下列逻辑关系；实施稿需合并后再生成迁移，不能将逻辑清单直接视为建表 SQL。

| 表/关系 | 逻辑信息 | 约束 |
|---|---|---|
| `source_capability_snapshots` | source_id、能力版本、可采字段/覆盖、许可与速率状态、验证时间、证据引用 | 采集策略关联能力快照；未知能力不能假定可用 |
| `command_receipts` | idempotency_key、请求类型、仅公开的范围、状态、关联 run/release、结果摘要 | 同一命令重试返回原结果，不能重复启动采集、批准、发布或作者加分 |
| `update_tasks` 的租约/检查点 | lease_owner、lease_expires_at、checkpoint、输入/输出哈希、阶段版本 | 崩溃后可回收租约并从有效检查点恢复；不得重复提交阶段副作用 |
| `human_reviews` / `knowledge_reviews` 的并发版本 | expected_revision、当前目标内容哈希、复核版本、状态转换 | 目标变化或并发修改时拒绝覆盖；批准针对具体不可变内容，不是模糊的“最新” |
| `publication_events` 与角色权限 | 独立审核/发布权限、请求幂等键、预期 active_index、操作者及结果 | 允许同一维护者持有两种权限，但不合并操作；过期活动版本的发布/回滚请求须重新读取状态 |

后端已确认先在本机运行、验证后部署为受邀小范围服务。Laya/JEV 仅用于采集后的分析/筛选候选，真实服务身份与接口能力待核实；玩家侧公共回答使用独立 Agent 接口，个性化条件匹配留在本机。缺失热度分组展示、基本知识独立发布、概率未校准时的人工批准以及独立发布权限均已确认。
