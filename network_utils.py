"""网卡 IPv4 配置操作工具。

基于 Windows 自带的 netsh 命令实现：网卡列表查询、当前配置读取、
设置静态 IP、还原为 DHCP。所有方法均需管理员权限。

解析逻辑兼容中文/英文 Windows 系统的 netsh 本地化输出，并会把每次
netsh 的原始输出追加记录到 netsh_debug.log，便于在遇到未预期的输出
格式时快速定位问题。
"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional


# 诊断日志路径（与程序/exe 同目录）
_DEBUG_LOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "netsh_debug.log"
)
# 打包成 exe 后，__file__ 指向临时解压目录，日志应写到 exe 旁边
try:
    import sys

    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        _DEBUG_LOG = os.path.join(
            os.path.dirname(sys.executable), "netsh_debug.log"
        )
except Exception:
    pass


def _log(text: str, tag: str = "") -> None:
    """把 netsh 原始输出追加写入诊断日志，方便排查解析问题。"""
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            f.write(f"\n===== {stamp}  {tag} =====\n")
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        pass


def _run(cmd: str) -> str:
    """执行命令并返回标准输出文本（兼容 GBK/UTF-8）。"""
    proc = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    # Windows 中文系统 netsh 默认输出 GBK，这里依次尝试解码
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return proc.stdout.decode(encoding)
        except UnicodeDecodeError:
            continue
    return proc.stdout.decode("utf-8", errors="ignore")


def _after_colon(s: str) -> str:
    """取冒号后的内容，兼容中英文冒号。无冒号则返回原字符串去除首尾空格。"""
    for sep in (":", "："):
        if sep in s:
            return s.split(sep, 1)[1].strip()
    return s.strip()


@dataclass
class IpConfig:
    """单个网卡的 IPv4 配置快照。"""

    adapter: str = ""
    dhcp_enabled: bool = True
    ip: str = ""
    mask: str = ""
    gateway: str = ""
    dns: list[str] = field(default_factory=list)


class NetshManager:
    """封装 netsh 操作的网卡管理器。

    解析采用「关键字模糊匹配 + 启发式」，不依赖固定的英文表头文字，
    以兼容中文 Windows 系统的本地化输出（如「管理员状态」「DHCP 已启用」
    「默认网关」「DNS 服务器」等）。
    """

    # IP 地址正则
    _IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

    def list_adapters(self) -> list[str]:
        """返回可配置的网卡名称列表（过滤掉 Loopback / 环回）。"""
        cmd = "netsh interface show interface"
        text = _run(cmd)
        _log(text, tag=cmd)

        names: list[str] = []
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            # 跳过表头行：含 State/状态 或 Admin/管理员 等关键字
            low = stripped.lower()
            if (
                "admin state" in low
                or "管理员状态" in stripped
                or "interface name" in low
                or "接口名称" in stripped
                or "state" == low.split()[0]
            ):
                continue
            # 跳过分隔线（仅由 - = 空格 _ 组成）
            if set(stripped) <= set("-=_ "):
                continue
            # 数据行形如:
            #   Enabled     Connected     Dedicated     Ethernet
            #   已启用      已连接        专用          以太网
            # 前 3 列为 状态/状态/类型，第 4 列起为接口名（可能含空格）
            parts = stripped.split()
            if len(parts) < 4:
                continue
            name = " ".join(parts[3:]).strip()
            if not name:
                continue
            if "Loopback" in name or "环回" in name:
                continue
            names.append(name)

        # 去重并保持顺序
        seen: set[str] = set()
        unique: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return unique

    def get_config(self, adapter: str) -> IpConfig:
        """读取指定网卡当前的 IPv4 配置（兼容中英文关键字）。"""
        cmd = f'netsh interface ip show config name="{adapter}"'
        text = _run(cmd)
        _log(text, tag=cmd)

        cfg = IpConfig(adapter=adapter)
        current_section: Optional[str] = None

        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                current_section = None
                continue
            low = stripped.lower()

            # DHCP 是否启用: "DHCP enabled" / "DHCP 已启用"
            if "dhcp" in low and ("enabled" in low or "启用" in stripped):
                val = _after_colon(stripped).lower()
                cfg.dhcp_enabled = "yes" in val or "是" in _after_colon(stripped)
                current_section = None
                continue

            # 自动配置地址行跳过（APIPA 169.254），只取真正的 IP 地址行
            if "autoconfiguration" in low or "自动配置" in stripped:
                current_section = None
                continue

            # IP 地址: "IP Address" / "IP 地址" / "通过 DHCP 配置的 IP 地址"
            if ("ip address" in low or "ip 地址" in low or "ip地址" in low):
                val = _after_colon(stripped)
                if val and self._IP_RE.match(val):
                    cfg.ip = val
                current_section = None
                continue

            # 子网前缀: "Subnet Prefix" / "子网前缀"  形如 192.168.1.0/24 (mask 255.255.255.0)
            if "subnet" in low or "子网" in stripped:
                tail = _after_colon(stripped)
                m = (
                    re.search(r"mask\s+([0-9.]+)", tail)
                    or re.search(r"掩码\s*([0-9.]+)", tail)
                    or re.search(r"\(([^)]*255[^)]*)\)", tail)
                )
                if m:
                    # 第三种情况取括号内整体，再从中提取掩码
                    candidate = m.group(1)
                    mm = re.search(r"([01]?\d?\d|2[0-4]\d|25[0-5])"
                                   r"(\.([01]?\d?\d|2[0-4]\d|25[0-5])){3}", candidate)
                    cfg.mask = mm.group(0) if mm else candidate.strip()
                current_section = None
                continue

            # 默认网关: "Default Gateway" / "默认网关" / "通过 DHCP 配置的默认网关"
            if "default gateway" in low or "默认网关" in stripped:
                val = _after_colon(stripped)
                if val and self._IP_RE.match(val):
                    cfg.gateway = val
                current_section = None
                continue

            # DNS 服务器段落标记 (中英文, 模糊匹配)
            # 英文: Statically Configured DNS Servers / DNS Servers configured through DHCP
            # 中文: 静态配置的 DNS 服务器 / 通过 DHCP 配置的 DNS 服务器 / DNS 服务器
            if "dns" in low and ("server" in low or "服务器" in stripped):
                # 同一行冒号后可能直接跟了首个 DNS 地址, 一并提取
                val = _after_colon(stripped)
                if val and self._IP_RE.match(val) and val not in cfg.dns:
                    cfg.dns.append(val)
                if "dhcp" in low or "通过" in stripped:
                    current_section = "dns_dhcp"
                else:
                    current_section = "dns_static"
                continue

            # WINS 段落开始则结束 DNS 收集
            if "wins" in low or "wins 服务器" in stripped:
                current_section = None
                continue

            # DNS 续行：纯 IP 地址
            if current_section in {"dns_dhcp", "dns_static"}:
                if self._IP_RE.match(stripped):
                    if stripped not in cfg.dns:
                        cfg.dns.append(stripped)
                    continue
                # 括号注释行（如 "(已注册)"）跳过但不结束段落
                if stripped.startswith("(") and stripped.endswith(")"):
                    continue
                # 其它非空内容则结束 DNS 段
                current_section = None

        # 清理占位符
        if cfg.ip.lower() in {"none", "无"}:
            cfg.ip = ""
        if cfg.gateway.lower() in {"none", "无"}:
            cfg.gateway = ""
        cfg.dns = [d for d in cfg.dns if d.lower() not in {"none", "无"}]
        return cfg

    def set_static(
        self,
        adapter: str,
        ip: str,
        mask: str,
        gateway: str = "",
        dns: Optional[list[str]] = None,
    ) -> None:
        """设置静态 IPv4 地址（含网关与 DNS）。"""
        if not ip or not mask:
            raise ValueError("IP 地址和子网掩码不能为空")

        gw_part = f' gateway={gateway} gwmetric=1' if gateway else ""
        cmd = (
            f'netsh interface ip set address name="{adapter}" '
            f'source=static addr={ip} mask={mask}{gw_part}'
        )
        _run(cmd)

        # 先清掉旧的静态 DNS，再写入新的
        _run(f'netsh interface ip set dns name="{adapter}" source=static addr=none')
        dns = dns or []
        for i, server in enumerate(dns):
            if not server:
                continue
            if i == 0:
                _run(
                    f'netsh interface ip set dns name="{adapter}" '
                    f'source=static addr={server} primary'
                )
            else:
                _run(
                    f'netsh interface ip add dns name="{adapter}" '
                    f'addr={server} index={i + 1}'
                )

    def set_dhcp(self, adapter: str) -> None:
        """还原为 DHCP（自动获取 IP 与 DNS）。"""
        _run(f'netsh interface ip set address name="{adapter}" source=dhcp')
        _run(f'netsh interface ip set dns name="{adapter}" source=dhcp')


def is_admin() -> bool:
    """判断当前进程是否以管理员权限运行。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
