"""IPv4 配置管理器 - Windows 桌面工具。

功能：
  - 自动检测可用网卡
  - 设置静态 IPv4（IP / 子网掩码 / 网关 / DNS）
  - 一键还原为 DHCP（自动获取）
  - 保存多个预设方案，一键切换（如 办公 / 家庭 / 现场）
  - 修改前自动备份当前配置，便于一键还原
  - 启动时自检并以管理员权限运行
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from network_utils import IpConfig, NetshManager, is_admin


# ---------------------------------------------------------------------------
# 配置文件路径（与程序同目录）
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_FILE = os.path.join(APP_DIR, "profiles.json")
BACKUP_FILE = os.path.join(APP_DIR, "last_backup.json")


# ---------------------------------------------------------------------------
# 预设方案持久化
# ---------------------------------------------------------------------------
def load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_profiles(profiles: dict) -> None:
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


def load_backup() -> Optional[dict]:
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_backup(cfg: IpConfig) -> None:
    data = {
        "adapter": cfg.adapter,
        "dhcp_enabled": cfg.dhcp_enabled,
        "ip": cfg.ip,
        "mask": cfg.mask,
        "gateway": cfg.gateway,
        "dns": cfg.dns,
    }
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 管理员权限自检与自动提权
# ---------------------------------------------------------------------------
def ensure_admin() -> None:
    """若非管理员则尝试以管理员身份重新启动本程序。"""
    if is_admin():
        return
    try:
        params = " ".join(f'"{a}"' for a in sys.argv)
        # SW_SHOWNORMAL = 1
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    except Exception:
        messagebox.showerror(
            "权限不足",
            "设置 IP 需要管理员权限，且自动提权失败。\n请右键「以管理员身份运行」。",
        )
    sys.exit(0)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IPv4 配置管理器")
        self.root.geometry("640x620")
        self.root.minsize(560, 580)

        self.mgr = NetshManager()
        self.profiles = load_profiles()

        self.adapter_var = tk.StringVar()
        self.ip_var = tk.StringVar()
        self.mask_var = tk.StringVar()
        self.gateway_var = tk.StringVar()
        self.dns1_var = tk.StringVar()
        self.dns2_var = tk.StringVar()
        self.profile_name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.current_config: Optional[IpConfig] = None

        self._build_ui()
        self._refresh_adapters()
        self._refresh_profile_dropdown()

    # ----- UI 构建 -----
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # 网卡选择
        frm_adapter = ttk.LabelFrame(self.root, text="网卡选择")
        frm_adapter.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(frm_adapter, text="网卡:").grid(row=0, column=0, **pad, sticky="w")
        self.adapter_combo = ttk.Combobox(
            frm_adapter, textvariable=self.adapter_var, state="readonly", width=40
        )
        self.adapter_combo.grid(row=0, column=1, **pad, sticky="we")
        ttk.Button(frm_adapter, text="刷新", command=self._refresh_adapters).grid(
            row=0, column=2, **pad
        )
        ttk.Button(frm_adapter, text="读取当前", command=self._load_current).grid(
            row=0, column=3, **pad
        )
        frm_adapter.columnconfigure(1, weight=1)

        # IPv4 配置输入
        frm_cfg = ttk.LabelFrame(self.root, text="IPv4 配置")
        frm_cfg.pack(fill="x", padx=10, pady=6)

        rows = [
            ("IP 地址:", self.ip_var, "示例: 192.168.1.100"),
            ("子网掩码:", self.mask_var, "示例: 255.255.255.0"),
            ("默认网关:", self.gateway_var, "可空, 示例: 192.168.1.1"),
            ("主用 DNS:", self.dns1_var, "可空, 示例: 8.8.8.8"),
            ("备用 DNS:", self.dns2_var, "可空, 示例: 8.8.4.4"),
        ]
        for i, (label, var, hint) in enumerate(rows):
            ttk.Label(frm_cfg, text=label).grid(row=i, column=0, **pad, sticky="w")
            entry = ttk.Entry(frm_cfg, textvariable=var, width=30)
            entry.grid(row=i, column=1, **pad, sticky="we")
            ttk.Label(frm_cfg, text=hint, foreground="gray").grid(
                row=i, column=2, **pad, sticky="w"
            )
        frm_cfg.columnconfigure(1, weight=1)

        # 操作按钮
        frm_act = ttk.Frame(self.root)
        frm_act.pack(fill="x", padx=10, pady=6)
        ttk.Button(frm_act, text="应用静态 IP", command=self._apply_static).pack(
            side="left", padx=4
        )
        ttk.Button(frm_act, text="还原为 DHCP", command=self._apply_dhcp).pack(
            side="left", padx=4
        )
        ttk.Button(frm_act, text="还原上次备份", command=self._restore_backup).pack(
            side="left", padx=4
        )

        # 预设方案
        frm_prof = ttk.LabelFrame(self.root, text="预设方案")
        frm_prof.pack(fill="x", padx=10, pady=6)
        ttk.Label(frm_prof, text="方案名:").grid(row=0, column=0, **pad, sticky="w")
        ttk.Entry(frm_prof, textvariable=self.profile_name_var, width=20).grid(
            row=0, column=1, **pad, sticky="we"
        )
        ttk.Button(frm_prof, text="保存当前为方案", command=self._save_profile).grid(
            row=0, column=2, **pad
        )
        ttk.Label(frm_prof, text="已有方案:").grid(row=1, column=0, **pad, sticky="w")
        self.profile_combo = ttk.Combobox(
            frm_prof, state="readonly", width=20
        )
        self.profile_combo.grid(row=1, column=1, **pad, sticky="we")
        ttk.Button(frm_prof, text="载入", command=self._load_profile).grid(
            row=1, column=2, **pad
        )
        ttk.Button(frm_prof, text="应用", command=self._apply_profile).grid(
            row=1, column=3, **pad
        )
        ttk.Button(frm_prof, text="删除", command=self._delete_profile).grid(
            row=1, column=4, **pad
        )
        frm_prof.columnconfigure(1, weight=1)

        # 当前状态显示
        frm_info = ttk.LabelFrame(self.root, text="当前网卡配置")
        frm_info.pack(fill="both", expand=True, padx=10, pady=6)
        self.info_text = tk.Text(frm_info, height=8, wrap="word", relief="flat")
        self.info_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.info_text.configure(state="disabled")

        # 状态栏
        ttk.Label(
            self.root, textvariable=self.status_var, relief="sunken", anchor="w"
        ).pack(fill="x", side="bottom")

    # ----- 网卡 -----
    def _refresh_adapters(self) -> None:
        self._set_status("正在读取网卡列表...")
        threading.Thread(target=self._do_refresh_adapters, daemon=True).start()

    def _do_refresh_adapters(self) -> None:
        try:
            names = self.mgr.list_adapters()
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"读取网卡失败:\n{e}", "error")
            self._set_status("读取网卡失败")
            return
        if not names:
            # 解析为空：提示用户查看诊断日志，把 netsh 原始输出发回以便修复
            self._safe_msgbox(
                "未读到网卡",
                "未能从 netsh 输出中解析出任何网卡。\n\n"
                "请把程序所在目录下的 netsh_debug.log 文件内容发回，"
                "我将据此调整解析逻辑。\n"
                "(该日志记录了 netsh 的原始输出)",
                "warning",
            )
            self._set_status("未读到网卡, 请查看 netsh_debug.log")
            return
        self.root.after(0, lambda: self._update_adapters(names))

    def _update_adapters(self, names: list[str]) -> None:
        self.adapter_combo["values"] = names
        if names:
            if self.adapter_var.get() not in names:
                self.adapter_var.set(names[0])
            self._load_current()
        self._set_status(f"共 {len(names)} 个网卡")

    # ----- 当前配置 -----
    def _load_current(self) -> None:
        adapter = self.adapter_var.get()
        if not adapter:
            return
        self._set_status(f"正在读取 {adapter} 的当前配置...")
        threading.Thread(
            target=self._do_load_current, args=(adapter,), daemon=True
        ).start()

    def _do_load_current(self, adapter: str) -> None:
        try:
            cfg = self.mgr.get_config(adapter)
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"读取配置失败:\n{e}", "error")
            self._set_status("读取配置失败")
            return
        self.current_config = cfg
        self.root.after(0, lambda: self._fill_from_config(cfg))
        self._set_status("已读取当前配置")

    def _fill_from_config(self, cfg: IpConfig) -> None:
        self.ip_var.set(cfg.ip)
        self.mask_var.set(cfg.mask)
        self.gateway_var.set(cfg.gateway)
        self.dns1_var.set(cfg.dns[0] if len(cfg.dns) > 0 else "")
        self.dns2_var.set(cfg.dns[1] if len(cfg.dns) > 1 else "")
        self._render_info(cfg)

    def _render_info(self, cfg: IpConfig) -> None:
        mode = "DHCP (自动获取)" if cfg.dhcp_enabled else "静态 IP"
        dns_text = ", ".join(cfg.dns) if cfg.dns else "无"
        content = (
            f"网卡: {cfg.adapter}\n"
            f"模式: {mode}\n"
            f"IP 地址: {cfg.ip or '(无)'}\n"
            f"子网掩码: {cfg.mask or '(无)'}\n"
            f"默认网关: {cfg.gateway or '(无)'}\n"
            f"DNS: {dns_text}\n"
        )
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", content)
        self.info_text.configure(state="disabled")

    # ----- 应用静态 IP -----
    def _apply_static(self) -> None:
        adapter = self.adapter_var.get()
        if not adapter:
            messagebox.showwarning("提示", "请先选择网卡")
            return
        ip = self.ip_var.get().strip()
        mask = self.mask_var.get().strip()
        if not ip or not mask:
            messagebox.showwarning("提示", "IP 地址和子网掩码不能为空")
            return
        if not messagebox.askyesno(
            "确认", f"将把网卡 [{adapter}] 设为静态 IP:\n{ip}\n确定继续吗?"
        ):
            return
        dns = [d for d in (self.dns1_var.get().strip(), self.dns2_var.get().strip()) if d]
        self._set_status("正在应用静态 IP...")
        threading.Thread(
            target=self._do_apply_static,
            args=(adapter, ip, mask, self.gateway_var.get().strip(), dns),
            daemon=True,
        ).start()

    def _do_apply_static(
        self, adapter: str, ip: str, mask: str, gateway: str, dns: list[str]
    ) -> None:
        try:
            # 修改前备份当前配置
            try:
                cur = self.mgr.get_config(adapter)
                save_backup(cur)
            except Exception:  # noqa: BLE001
                pass
            self.mgr.set_static(adapter, ip, mask, gateway, dns)
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"应用失败:\n{e}", "error")
            self._set_status("应用失败")
            return
        self.root.after(0, self._on_applied_success)
        self._set_status("静态 IP 已应用")

    def _on_applied_success(self) -> None:
        messagebox.showinfo("成功", "静态 IP 已应用")
        self._load_current()

    # ----- 还原 DHCP -----
    def _apply_dhcp(self) -> None:
        adapter = self.adapter_var.get()
        if not adapter:
            messagebox.showwarning("提示", "请先选择网卡")
            return
        if not messagebox.askyesno(
            "确认", f"将把网卡 [{adapter}] 还原为 DHCP(自动获取)?"
        ):
            return
        self._set_status("正在还原为 DHCP...")
        threading.Thread(
            target=self._do_apply_dhcp, args=(adapter,), daemon=True
        ).start()

    def _do_apply_dhcp(self, adapter: str) -> None:
        try:
            try:
                cur = self.mgr.get_config(adapter)
                save_backup(cur)
            except Exception:  # noqa: BLE001
                pass
            self.mgr.set_dhcp(adapter)
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"还原失败:\n{e}", "error")
            self._set_status("还原失败")
            return
        self.root.after(
            0, lambda: (messagebox.showinfo("成功", "已还原为 DHCP"), self._load_current())
        )
        self._set_status("已还原为 DHCP")

    # ----- 还原上次备份 -----
    def _restore_backup(self) -> None:
        data = load_backup()
        if not data:
            messagebox.showinfo("提示", "没有可用的上次备份")
            return
        adapter = data.get("adapter") or self.adapter_var.get()
        info = (
            f"上次备份:\n"
            f"  网卡: {adapter}\n"
            f"  模式: {'DHCP' if data.get('dhcp_enabled') else '静态'}\n"
            f"  IP: {data.get('ip', '')}\n"
            f"  掩码: {data.get('mask', '')}\n"
            f"  网关: {data.get('gateway', '')}\n"
            f"  DNS: {', '.join(data.get('dns', []))}\n\n"
            f"确认还原吗?"
        )
        if not messagebox.askyesno("还原备份", info):
            return
        self._set_status("正在还原上次备份...")
        threading.Thread(
            target=self._do_restore_backup, args=(data,), daemon=True
        ).start()

    def _do_restore_backup(self, data: dict) -> None:
        adapter = data.get("adapter") or self.adapter_var.get()
        try:
            if data.get("dhcp_enabled"):
                self.mgr.set_dhcp(adapter)
            else:
                self.mgr.set_static(
                    adapter,
                    data.get("ip", ""),
                    data.get("mask", ""),
                    data.get("gateway", ""),
                    data.get("dns", []),
                )
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"还原失败:\n{e}", "error")
            self._set_status("还原失败")
            return
        self.root.after(
            0,
            lambda: (messagebox.showinfo("成功", "已还原为上次备份"), self._load_current()),
        )
        self._set_status("已还原为上次备份")

    # ----- 预设方案 -----
    def _refresh_profile_dropdown(self) -> None:
        names = list(self.profiles.keys())
        self.profile_combo["values"] = names
        if names:
            self.profile_combo.current(0)

    def _save_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入方案名")
            return
        adapter = self.adapter_var.get()
        if not adapter:
            messagebox.showwarning("提示", "请先选择网卡")
            return
        self.profiles[name] = {
            "adapter": adapter,
            "ip": self.ip_var.get().strip(),
            "mask": self.mask_var.get().strip(),
            "gateway": self.gateway_var.get().strip(),
            "dns1": self.dns1_var.get().strip(),
            "dns2": self.dns2_var.get().strip(),
        }
        save_profiles(self.profiles)
        self._refresh_profile_dropdown()
        self.profile_combo.set(name)
        messagebox.showinfo("成功", f"方案 [{name}] 已保存")

    def _load_profile(self) -> None:
        name = self.profile_combo.get()
        if not name or name not in self.profiles:
            messagebox.showwarning("提示", "请选择一个方案")
            return
        p = self.profiles[name]
        self.adapter_var.set(p["adapter"])
        self.ip_var.set(p.get("ip", ""))
        self.mask_var.set(p.get("mask", ""))
        self.gateway_var.set(p.get("gateway", ""))
        self.dns1_var.set(p.get("dns1", ""))
        self.dns2_var.set(p.get("dns2", ""))
        self.profile_name_var.set(name)
        self._set_status(f"已载入方案 [{name}]")

    def _apply_profile(self) -> None:
        self._load_profile()
        self._apply_static()

    def _delete_profile(self) -> None:
        name = self.profile_combo.get()
        if not name or name not in self.profiles:
            return
        if messagebox.askyesno("确认", f"删除方案 [{name}]?"):
            del self.profiles[name]
            save_profiles(self.profiles)
            self._refresh_profile_dropdown()
            self._set_status(f"已删除方案 [{name}]")

    # ----- 辅助 -----
    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _safe_msgbox(self, title: str, msg: str, kind: str = "info") -> None:
        self.root.after(0, lambda: getattr(messagebox, kind)(title, msg))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    ensure_admin()
    root = tk.Tk()
    try:
        # Windows 下让 DPI 感知，避免模糊
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
