"""网卡 IPv4 配置操作工具。

基于 Windows 自带的 netsh 命令实现：网卡列表查询、当前配置读取、
设置静态 IP、还原为 DHCP。所有方法均需管理员权限。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional


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
    """封装 netsh 操作的网卡管理器。"""

    # netsh interface show interface 输出表头之后才是数据行
    _LIST_HEADER_RE = re.compile(r"Admin State\s+State\s+Type\s+Interface Name")

    def list_adapters(self) -> list[str]:
        """返回可配置的网卡名称列表（过滤掉 Loopback）。"""
        text = _run('netsh interface show interface')
        names: list[str] = []
        header_seen = False
        sep_seen = False
        for line in text.splitlines():
            if not header_seen:
                if self._LIST_HEADER_RE.search(line):
                    header_seen = True
                continue
            if not sep_seen:
                # 表头下方的分隔线
                if set(line.strip()) <= {"-"}:
                    sep_seen = True
                continue
            line = line.strip()
            if not line:
                continue
            # 形如: Enabled  Connected  Dedicated  Ethernet
            m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.+)$", line)
            if not m:
                continue
            name = m.group(4).strip()
            if "Loopback" in name:
                continue
            names.append(name)
        return names

    def get_config(self, adapter: str) -> IpConfig:
        """读取指定网卡当前的 IPv4 配置。"""
        cfg = IpConfig(adapter=adapter)
        text = _run(f'netsh interface ip show config name="{adapter}"')

        current_section: Optional[str] = None
        for raw in text.splitlines():
            line = raw.strip()
            low = line.lower()

            if low.startswith("dhcp enabled"):
                cfg.dhcp_enabled = "yes" in low.split(":", 1)[-1].strip().lower()
                current_section = None
            elif low.startswith("ip address") and "autoconfiguration" not in low:
                cfg.ip = line.split(":", 1)[-1].strip()
                current_section = None
            elif low.startswith("subnet prefix"):
                # 形如: 192.168.1.0/24 (mask 255.255.255.0)
                tail = line.split(":", 1)[-1]
                mm = re.search(r"mask\s+([0-9.]+)", tail)
                if mm:
                    cfg.mask = mm.group(1)
                current_section = None
            elif low.startswith("default gateway"):
                cfg.gateway = line.split(":", 1)[-1].strip()
                current_section = None
            elif low.startswith("dns servers configured through dhcp"):
                current_section = "dns_dhcp"
            elif low.startswith("dns servers configured through static") or (
                low.startswith("statically configured dns servers")
            ):
                current_section = "dns_static"
            elif low.startswith("wins servers"):
                current_section = None
            else:
                # 续行：DNS 多个地址时，后续行只有缩进和 IP
                if current_section in {"dns_dhcp", "dns_static"} and re.match(
                    r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", line
                ):
                    if line and line not in cfg.dns:
                        cfg.dns.append(line)
                else:
                    current_section = None

        # 清理占位符
        for attr in ("ip", "gateway"):
            if getattr(cfg, attr).lower() in {"", "none"}:
                setattr(cfg, attr, "")
        cfg.dns = [d for d in cfg.dns if d.lower() not in {"none", ""}]
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
