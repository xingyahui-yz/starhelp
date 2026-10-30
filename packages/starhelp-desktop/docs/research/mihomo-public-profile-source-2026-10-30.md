# Mihomo public Star Rail profile: M0 source evidence

查阅日期：2026-10-30
范围：B 当前使用的 Mihomo parsed public profile endpoint。只检查服务方维护的 March7th API 文档、MetaCubeX 上游客户端/模型源码和服务 API 的公开文档入口；未请求任何真实 UID 或账号数据。

## 已由一手来源证明

### Endpoint、query 与响应版本

- 服务文档将 endpoint 定义为 `GET /sr_info_parsed/{uid}`，host 为 `api.mihomo.me`；`uid` 是玩家 UID。查询参数为 `language`（别名 `l`、`lang`，默认 `cn`）、`version`（别名 `v`、`ver`，默认 `v2`）和 `is_force_update`（默认 `false`）。服务文档示例使用 `?l=en`。[March7th Parsed Data API](https://march7th.xyz/en/api/parsed.html)（查阅于 2026-10-30）
- 服务方文档称接口返回 parsed player data，并区分 Raw Data API 与 Parsed Data API；后者返回带文本描述和图片路径的解析数据。[MiHoMo API overview](https://march7th.xyz/en/api/)（查阅于 2026-10-30）
- B 当前请求 `https://api.mihomo.me/sr_info_parsed/{uid}?lang=cn`，与服务文档的 host、endpoint、language alias 和默认 v2 一致。MetaCubeX 上游 client 源码也将 `BASE_URL` 设为同一地址、将 UID 附加到 path、以 `lang` query 发 GET；`fetch_user` 不传 version 参数，`fetch_user_v1` 传 `version=v1`。[MetaCubeX client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py)（查阅于 2026-10-30）
- 服务文档列出的语言为 `cn`、`chs`、`cht`、`de`、`en`、`es`、`fr`、`id`、`jp`、`kr`、`pt`、`ru`、`th`、`vi`。MetaCubeX client enum 使用 `cn` 而未列 `chs`；服务文档更直接描述服务侧支持值。[Parsed Data API](https://march7th.xyz/en/api/parsed.html)、[client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py)（均查阅于 2026-10-30）
- 服务文档公开 `is_force_update` 参数并说明其作用是立即刷新缓存；默认值 `false` 表示正常请求走非强制刷新路径。文档没有说明缓存 TTL、刷新频率或多久能看到游戏侧变更，因此不能据此承诺数据新鲜度。[Parsed Data API](https://march7th.xyz/en/api/parsed.html)（查阅于 2026-10-30）

### 文档示例明确展示的字段覆盖

服务方 parsed endpoint 的示例和数据模型展示了以下字段族；这证明文档描述了这些形状，不证明每个 UID 都返回每个字段，也不证明这些字段构成游戏账号全量数据：[Parsed Data API example and reference model](https://march7th.xyz/en/api/parsed.html)（查阅于 2026-10-30）。

- `player`：UID、昵称、开拓等级、均衡等级、好友数、头像、签名、展示状态；`space_info` 示例含忘却之庭摘要（`level`、`chaos_id`、`chaos_level`、`chaos_star_count`）、模拟宇宙等级，以及角色、光锥、遗器、成就、书籍、音乐数量。
- `characters`：展示角色的 ID、名称、稀有度、命座/星魂 rank、等级、晋升、路径、属性、技能与技能树、光锥、遗器、套装、数值属性和位置。文档将此列表描述为角色数据示例，并用省略号表示还有其他角色/条目。
- 文档的 parsed 结构将 `characters` 解释为展示列表；公开展示中没有出现的角色、物品不能推断为未拥有。总数是摘要数量，不是每件物品的逐项清单。
- MetaCubeX V2 model 的顶层对象为 `player` 和 `characters`；其 Character model 映射了等级、rank、skills、skill_trees、light_cone、relics、relic_sets、attributes、additions、properties 等。该模型体现上游客户端预期解析的字段，不是服务方的稳定性保证。[V2 base.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/base.py)、[V2 player.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/player.py)、[V2 character.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/character.py)（均查阅于 2026-10-30）

### 新鲜度、频率提示、隐私和使用条款

- 服务文档说明高频使用 API 时应在 `User-Agent` 中包含应用信息，以避免被封锁。文档未给出数字限额、配额、SLA、响应时间、封锁申诉流程或限制头定义，因此只能证明有频率/封锁提示，不能据此算出安全请求速率。[MiHoMo API overview](https://march7th.xyz/en/api/)（查阅于 2026-10-30）
- `is_force_update` 的服务文档说明仅证明可以请求立即刷新缓存；TTL、底层数据何时同步、缓存键、缓存隔离及强刷限频均未知。[Parsed Data API](https://march7th.xyz/en/api/parsed.html)（查阅于 2026-10-30）
- 在本次检查的服务方 API 文档和上游仓库中，没有找到针对该服务的隐私政策、数据保留/删除说明、数据处理地域、访问日志内容、再发布许可或适用于 B 的使用条款。搜索范围是上述公开文档/仓库，故结论是“未找到/未证明”，不能断言不存在其他约定。
- 服务方文档介绍 Raw Data API 为原始玩家数据，Parsed Data API 为解析后的玩家公开数据；这不足以证明匿名化、同意机制、用途限制或商业再使用授权。[MiHoMo API overview](https://march7th.xyz/en/api/)（查阅于 2026-10-30）
- `MetaCubeX/mihomo` 是解析数据的 Python 客户端和数据模型仓库。其 README、源码或开源许可证并非 `api.mihomo.me` 服务运营者的使用条款或隐私承诺；不能把客户端文档当成服务许可。[MetaCubeX/mihomo README](https://github.com/MetaCubeX/mihomo/blob/main/README.md)、[MetaCubeX client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py)（查阅于 2026-10-30）

## 未知或尚未证明的 M0 项

1. **UID、服区和路由**：文档 endpoint 只有 UID path 参数，没有地区/服务器参数；未证明服务怎样从 UID 判断服区、跨区 UID 表现如何或是否总能命中正确账号。B 的 server label 是本地信息，不会随请求传给 Mihomo。
2. **字段保障与任务映射**：字段样例没有冻结版本/兼容策略，未保证可选字段在缺省、展示设置变化、版本更新或部分错误时的行为；也没有证明 `memory_data` 等摘要对应当前三个挑战模式、周期或完整历史。角色展示/装备样例不能证明是背包全量，也没有证明具体任务/玩法输入输出映射。
3. **数据新鲜度及失败语义**：缓存 TTL、游戏侧更新时间、强制刷新代价及限制、服务可用性、维护通知、错误码合同、429/403 退避策略均未被上述来源充分说明。MetaCubeX client 识别 200/400/404 仅是客户端对响应的处理，不是服务方完整的错误合同。[client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py)（查阅于 2026-10-30）
4. **隐私/条款/许可**：服务收集哪些请求元数据、是否及多久记录 UID/IP/User-Agent、保留/删除机制、数据处理者/地域、公开资料是否允许被第三方自动读取及用于本产品、缓存/展示/衍生数据再分发规则，都未从本次检查的一手来源得到证明。
5. **生产可靠性**：无服务侧服务等级、兼容承诺、限额数字、联系/支持升级路径；`User-Agent` 建议仅说明高频可能被封，不等于已批准 B 的生产使用。

## 对 B 的建议

- 将本接口维持为明确用户确认后的可选公开展示档案读取；首次调用前说明会把 UID 发送给 `api.mihomo.me`，提供取消，并把请求错误、未展示字段和未知值维持为 unknown。服务方文档只描述公开玩家数据，不能替代对处理目的和边界的用户说明。
- 服区标签继续只作本地元数据，直到服务方或可靠一手协议明确 UID 路由和目标区核验；不可依据格式自行选区或将三种挑战模式从 `memory_data` 摘要推断出来。
- 遵从服务方的 `User-Agent` 说明；采用保守、可配置的请求节流和失败退避，不启用 `is_force_update` 作为定期刷新捷径。正式请求频率上限和缓存新鲜度需由服务方确认。
- M0 映射应把“可由公开展示 endpoint 取得”与“完整账号事实/可用于规划”分开：只将实际返回、文档支持并经用户预览确认的字段导入；未显示角色不代表未拥有；聚合计数不能创建具体装备实例；服务字段名不自动决定业务任务含义。
- 生产启用前补齐并冻结：服务运营者身份/正式使用许可或适用条款、隐私与保留说明、频率上限/缓存语义/错误处理、UID-to-region 路由，以及逐个 M0 字段到 B 内部模型和 C 任务的映射。若无法获得服务方证据，把生产承诺标记为未解决，不将 MetaCubeX 客户端 README 当授权依据。

## 来源查阅清单

| 一手来源 | 用途 | 查阅日期 |
|---|---|---|
| [March7th MiHoMo API overview](https://march7th.xyz/en/api/) | API 方法、高频 User-Agent 提醒、接口类型与 host | 2026-10-30 |
| [March7th Parsed Data API](https://march7th.xyz/en/api/parsed.html) | endpoint/query、默认值、语言、缓存刷新参数、字段示例与参考模型 | 2026-10-30 |
| [MetaCubeX mihomo README](https://github.com/MetaCubeX/mihomo/blob/main/README.md) | 上游客户端版本说明和 API URL 示例；非服务条款 | 2026-10-30 |
| [MetaCubeX mihomo client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py) | 上游客户端 HTTP 构造、query 与状态码映射 | 2026-10-30 |
| [MetaCubeX V2 base.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/base.py) | V2 顶层结构 | 2026-10-30 |
| [MetaCubeX V2 player.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/player.py) | V2 玩家字段和旧字段转换 | 2026-10-30 |
| [MetaCubeX V2 character.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/models/character.py) | V2 展示角色、装备、技能与属性模型 | 2026-10-30 |
| [Mar-7th Mihomo-Docs repository](https://github.com/Mar-7th/Mihomo-Docs) | 检查是否存在额外服务方文档仓库；仓库页面显示为空 | 2026-10-30 |
