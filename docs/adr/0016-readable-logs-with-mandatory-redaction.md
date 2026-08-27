# ADR-0016：保留 March7thAssistant 的可读日志体验并增加强制脱敏审计

状态：Accepted

日志层独立实现 March7thAssistant 已验证易用的 Python `logging` 路线：控制台彩色级别、`time | level | message` 文本、每日日志文件、阶段标题和默认 30 天清理。在此基础上，所有处理器前置不可关闭的敏感数据过滤，禁止 UID、账号指纹、Cookie、Token、API Key、原始 OCR 文本和本地绝对路径进入日志，调试级别也不例外。安全审计另行以 JSON Lines 记录脱敏事件，日志不自动附带截图，导出前必须再次扫描敏感字段。
