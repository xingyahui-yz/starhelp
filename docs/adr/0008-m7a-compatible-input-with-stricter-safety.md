# ADR-0008：借鉴 March7thAssistant 的输入兼容性路线但采用更严格安全边界

状态：Accepted

受限扫描模式将独立实现 PyAutoGUI 本地按键、约 0.2 秒默认按压时长、按窗口标题定位以及 Win32/MSS 截图路线，以获得与 March7thAssistant 类似的 Windows 兼容性。不复制其 GPL 源码，也不采用关闭 PyAutoGUI failsafe、字符串 `eval`、未知页面自动按 Esc 或页面失败后盲目重试。本项目保留鼠标角落与全局紧急停止，每个翻页输入前后均校验白名单页面，转换失败立即终止扫描会话。
