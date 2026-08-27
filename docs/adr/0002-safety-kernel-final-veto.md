# ADR-0002：安全内核拥有最终否决权

状态：Accepted

所有非等待动作必须经过同一安全入口。拒绝时不存在备用执行路径。当前 `RecordingInputBackend` 只记录动作，不发送操作系统输入。

