from __future__ import annotations

import re

DANGEROUS_PATTERNS = [
    (r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*-rf\b|.*--force)", "强制删除文件"),
    (r"\brm\s+-[a-zA-Z]*r", "递归删除"),
    (r"\brm\s+[^;\n]*--recursive\b", "递归删除"),
    (r"\bsudo\b", "提权操作"),
    (r"\bmkfs\b", "格式化磁盘"),
    (r"\bdd\s+.*of=/dev/", "直接写设备"),
    (r":\(\)\s*\{.*\|.*&\s*\}", "Fork bomb"),
    (r">\s*/dev/sd[a-z]", "覆写磁盘设备"),
    (r"\bchmod\s+777\b", "开放所有权限"),
    (r"\bcurl\b.*\|\s*(ba)?sh", "远程脚本执行"),
    (r"\bwget\b.*\|\s*(ba)?sh", "远程脚本执行"),
    (r"\beval\b", "eval 动态执行"),
    (r">\s*/etc/", "覆写系统配置"),
]
MODERATE_PATTERNS = [
    (r"\brm\b", "删除文件"),
    (r"\bmv\b", "移动/重命名文件"),
    (r"\bchmod\b", "修改权限"),
    (r"\bchown\b", "修改所有者"),
    (r"\bkill\b", "终止进程"),
    (r"\bpkill\b", "批量终止进程"),
    (r"\bgit\s+push\b", "Git 推送"),
    (r"\bgit\s+reset\s+--hard\b", "Git 硬重置"),
    (r"\bpython\s+-m\s+build\b", "发布构建"),
    (r"\bdocker\s+rm\b", "删除容器"),
]


def classify_bash_command(command: str) -> dict[str, str]:
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {"level": "dangerous", "reason": reason}
    for pattern, reason in MODERATE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {"level": "moderate", "reason": reason}
    return {"level": "safe"}
