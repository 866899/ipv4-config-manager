"""IPv4 配置管理器 - Windows 桌面工具。

功能：
  - 自动检测可用网卡
  - 设置静态 IPv4（IP / 子网掩码 / 网关 / DNS）
  - 一键还原为 DHCP（自动获取）
  - 保存多个预设方案，一键切换（如 办公 / 家庭 / 现场）
  - 修改前自动备份当前配置，便于一键还原
  - 启动时自检并以管理员权限运行

UI 风格: 现代深色科技风, 青色强调, 左操作区 + 右信息卡布局。
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
# 配色体系 (现代深色科技风)
# ---------------------------------------------------------------------------
class Theme:
    BG = "#1a1d23"              # 主背景
    BG_ELEVATED = "#252932"     # 卡片/面板背景
    BG_INPUT = "#1f232b"        # 输入框背景
    BORDER = "#353a45"          # 描边
    BORDER_FOCUS = "#3ddbd9"    # 聚焦描边 (青色)

    TEXT = "#e6e8eb"            # 主文字
    TEXT_DIM = "#9aa0aa"        # 次要文字
    TEXT_FAINT = "#6b7280"      # 提示文字

    ACCENT = "#3ddbd9"          # 强调色 青
    ACCENT_DARK = "#2bb5b3"     # 强调色按下
    SUCCESS = "#4ade80"         # 成功 绿
    WARNING = "#fbbf24"         # 警告 黄
    DANGER = "#f87171"          # 危险 红
    INFO = "#60a5fa"            # 信息 蓝

    FONT_UI = "Microsoft YaHei UI"      # 中文 UI 字体
    FONT_MONO = "Consolas"              # 等宽字体 (IP/配置)
    FONT_UI_SIZE = 9
    FONT_TITLE_SIZE = 11


# ---------------------------------------------------------------------------
# 配置文件路径（与程序同目录）
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 打包成 exe 后, 日志/配置应写到 exe 旁边, 而非临时解压目录
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
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
# 自定义组件
# ---------------------------------------------------------------------------
class FlatButton(tk.Frame):
    """扁平按钮: 主操作填充强调色, 次操作描边, 带 hover 效果。"""

    def __init__(
        self,
        master,
        text: str,
        command=None,
        style: str = "secondary",  # primary | secondary | danger
        width: Optional[int] = None,
        **kwargs,
    ):
        bg, fg, hover_bg, press_bg = self._colors(style)
        super().__init__(master, bg=bg, highlightthickness=0)
        self._cmd = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._press_bg = press_bg
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=(Theme.FONT_UI, Theme.FONT_UI_SIZE, "bold"),
            padx=14,
            pady=7,
            cursor="hand2",
        )
        self._label.pack(fill="both", expand=True)
        if width:
            self._label.configure(width=width)
        for w in (self, self._label):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_press)
            w.bind("<ButtonRelease-1>", self._on_release)

    @staticmethod
    def _colors(style: str):
        if style == "primary":
            return (Theme.ACCENT, "#0d1b1a", Theme.ACCENT_DARK, Theme.ACCENT_DARK)
        if style == "danger":
            return (Theme.DANGER, "#1a0d0d", "#dc4a4a", "#dc4a4a")
        # secondary
        return (Theme.BG_ELEVATED, Theme.TEXT, Theme.BORDER, Theme.BORDER)

    def _on_enter(self, _e):
        self._label.configure(bg=self._hover_bg)
        self.configure(bg=self._hover_bg)

    def _on_leave(self, _e):
        self._label.configure(bg=self._bg)
        self.configure(bg=self._bg)

    def _on_press(self, _e):
        self._label.configure(bg=self._press_bg)
        self.configure(bg=self._press_bg)

    def _on_release(self, _e):
        self._label.configure(bg=self._hover_bg)
        self.configure(bg=self._hover_bg)
        if self._cmd:
            self._cmd()


class Card(tk.Frame):
    """圆角感卡片容器(实际用描边+背景模拟)。"""

    def __init__(self, master, title: str = "", **kwargs):
        super().__init__(
            master,
            bg=Theme.BG_ELEVATED,
            highlightbackground=Theme.BORDER,
            highlightthickness=1,
            bd=0,
        )
        if title:
            hdr = tk.Frame(self, bg=Theme.BG_ELEVATED)
            hdr.pack(fill="x", padx=14, pady=(10, 4))
            tk.Label(
                hdr,
                text=title,
                bg=Theme.BG_ELEVATED,
                fg=Theme.ACCENT,
                font=(Theme.FONT_UI, Theme.FONT_TITLE_SIZE, "bold"),
                anchor="w",
            ).pack(side="left")
            # 标题下方分隔线
            tk.Frame(self, bg=Theme.BORDER, height=1).pack(
                fill="x", padx=14, pady=(2, 6)
            )


class StatusBar(tk.Frame):
    """状态栏: 左侧圆点指示 + 文字, 颜色随状态变化。"""

    def __init__(self, master):
        super().__init__(master, bg=Theme.BG, height=26, highlightthickness=0)
        self._dot = tk.Label(self, text="●", bg=Theme.BG, fg=Theme.TEXT_DIM,
                             font=(Theme.FONT_UI, 8))
        self._dot.pack(side="left", padx=(10, 6))
        self._label = tk.Label(
            self,
            text="就绪",
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            font=(Theme.FONT_UI, 8),
            anchor="w",
        )
        self._label.pack(side="left", fill="x", expand=True)

    def set(self, text: str, level: str = "info") -> None:
        color_map = {
            "info": Theme.TEXT_DIM,
            "working": Theme.ACCENT,
            "success": Theme.SUCCESS,
            "warning": Theme.WARNING,
            "error": Theme.DANGER,
        }
        c = color_map.get(level, Theme.TEXT_DIM)
        self._dot.configure(fg=c)
        self._label.configure(text=text, fg=c)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IPv4 配置管理器  By LiaoZiHao")
        self.root.geometry("880x600")
        self.root.minsize(820, 560)
        self.root.configure(bg=Theme.BG)

        self.mgr = NetshManager()
        self.profiles = load_profiles()

        self.adapter_var = tk.StringVar()
        self.ip_var = tk.StringVar()
        self.mask_var = tk.StringVar()
        self.gateway_var = tk.StringVar()
        self.dns1_var = tk.StringVar()
        self.dns2_var = tk.StringVar()
        self.profile_name_var = tk.StringVar()
        self.current_config: Optional[IpConfig] = None

        self._apply_dark_theme()
        self._build_ui()
        self._refresh_adapters()
        self._refresh_profile_dropdown()

    # ----- 主题 -----
    def _apply_dark_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=Theme.BG, foreground=Theme.TEXT,
                        font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), borderwidth=0)
        style.configure("TFrame", background=Theme.BG)
        style.configure("Card.TFrame", background=Theme.BG_ELEVATED)
        style.configure("TLabel", background=Theme.BG, foreground=Theme.TEXT)
        style.configure("Dim.TLabel", background=Theme.BG, foreground=Theme.TEXT_DIM)
        style.configure("Card.TLabel", background=Theme.BG_ELEVATED,
                        foreground=Theme.TEXT)
        style.configure("CardDim.TLabel", background=Theme.BG_ELEVATED,
                        foreground=Theme.TEXT_DIM)
        style.configure("CardTitle.TLabel", background=Theme.BG_ELEVATED,
                        foreground=Theme.ACCENT,
                        font=(Theme.FONT_UI, Theme.FONT_TITLE_SIZE, "bold"))

        # 输入框
        style.configure("TEntry", fieldbackground=Theme.BG_INPUT,
                        foreground=Theme.TEXT, insertcolor=Theme.ACCENT,
                        bordercolor=Theme.BORDER, lightcolor=Theme.BORDER,
                        darkcolor=Theme.BORDER, padding=6)
        style.map("TEntry",
                  bordercolor=[("focus", Theme.BORDER_FOCUS)],
                  lightcolor=[("focus", Theme.BORDER_FOCUS)],
                  darkcolor=[("focus", Theme.BORDER_FOCUS)])

        # Combobox
        style.configure("TCombobox", fieldbackground=Theme.BG_INPUT,
                        background=Theme.BG_ELEVATED, foreground=Theme.TEXT,
                        bordercolor=Theme.BORDER, lightcolor=Theme.BORDER,
                        darkcolor=Theme.BORDER, padding=6, arrowcolor=Theme.ACCENT)
        style.map("TCombobox",
                  bordercolor=[("focus", Theme.BORDER_FOCUS)],
                  lightcolor=[("focus", Theme.BORDER_FOCUS)],
                  darkcolor=[("focus", Theme.BORDER_FOCUS)],
                  fieldbackground=[("readonly", Theme.BG_INPUT)])
        style.configure("TCombobox.fieldbg", background=Theme.BG_INPUT)
        # 让下拉列表也用深色 (通过 option_add)
        self.root.option_add("*TCombobox*Listbox.background", Theme.BG_ELEVATED)
        self.root.option_add("*TCombobox*Listbox.foreground", Theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", Theme.ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#0d1b1a")

    # ----- UI 构建 -----
    def _build_ui(self) -> None:
        # 顶部品牌横幅
        self._build_banner()

        # 主体: 左操作区 + 右信息卡
        body = tk.Frame(self.root, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        body.columnconfigure(0, weight=3, uniform="col")
        body.columnconfigure(1, weight=2, uniform="col")
        body.rowconfigure(0, weight=1)

        # 左侧操作区 (网卡 + 配置 + 操作 + 预设)
        left = tk.Frame(body, bg=Theme.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(3, weight=1)
        self._build_adapter_card(left)
        self._build_config_card(left)
        self._build_action_bar(left)
        self._build_profile_card(left)

        # 右侧信息卡
        right = tk.Frame(body, bg=Theme.BG)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_info_card(right)

        # 底部状态栏
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill="x", side="bottom")

    def _build_banner(self) -> None:
        banner = tk.Frame(self.root, bg=Theme.BG_ELEVATED, height=64,
                          highlightbackground=Theme.BORDER, highlightthickness=1)
        banner.pack(fill="x", padx=14, pady=(12, 8))
        banner.pack_propagate(False)

        # 左: 标题 + 副标题
        left = tk.Frame(banner, bg=Theme.BG_ELEVATED)
        left.pack(side="left", padx=16, pady=10)
        tk.Label(
            left, text="IPv4 配置管理器", bg=Theme.BG_ELEVATED,
            fg=Theme.TEXT, font=(Theme.FONT_UI, 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left, text="快速设置 / 还原 IPv4 地址", bg=Theme.BG_ELEVATED,
            fg=Theme.TEXT_DIM, font=(Theme.FONT_UI, 8),
        ).pack(anchor="w")

        # 右: 署名徽标
        right = tk.Frame(banner, bg=Theme.BG_ELEVATED)
        right.pack(side="right", padx=16, pady=10)
        badge = tk.Frame(right, bg=Theme.BG_INPUT, highlightbackground=Theme.ACCENT,
                         highlightthickness=1)
        badge.pack()
        tk.Label(
            badge, text=" By LiaoZiHao ", bg=Theme.BG_INPUT, fg=Theme.ACCENT,
            font=(Theme.FONT_MONO, 9, "bold"), padx=10, pady=4,
        ).pack()

    # ----- 网卡卡片 -----
    def _build_adapter_card(self, parent) -> None:
        card = Card(parent, title="网卡选择")
        card.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(card, bg=Theme.BG_ELEVATED)
        inner.pack(fill="x", padx=14, pady=(4, 12))

        tk.Label(inner, text="网卡", bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), width=6).grid(
            row=0, column=0, sticky="w", pady=4)
        self.adapter_combo = ttk.Combobox(
            inner, textvariable=self.adapter_var, state="readonly"
        )
        self.adapter_combo.grid(row=0, column=1, sticky="we", padx=(6, 8), pady=4)
        FlatButton(inner, text="刷新", command=self._refresh_adapters,
                   style="secondary").grid(row=0, column=2, padx=2, pady=4)
        FlatButton(inner, text="读取当前", command=self._load_current,
                   style="primary").grid(row=0, column=3, padx=2, pady=4)
        inner.columnconfigure(1, weight=1)

    # ----- 配置输入卡片 -----
    def _build_config_card(self, parent) -> None:
        card = Card(parent, title="IPv4 配置")
        card.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(card, bg=Theme.BG_ELEVATED)
        inner.pack(fill="x", padx=14, pady=(4, 12))

        rows = [
            ("IP 地址", self.ip_var, "192.168.1.100"),
            ("子网掩码", self.mask_var, "255.255.255.0"),
            ("默认网关", self.gateway_var, "192.168.1.1"),
            ("主用 DNS", self.dns1_var, "8.8.8.8"),
            ("备用 DNS", self.dns2_var, "8.8.4.4"),
        ]
        for i, (label, var, ph) in enumerate(rows):
            tk.Label(inner, text=label, bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                     font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), width=8).grid(
                row=i, column=0, sticky="w", pady=3)
            entry = ttk.Entry(inner, textvariable=var, font=(Theme.FONT_MONO, 10))
            entry.grid(row=i, column=1, sticky="we", padx=(6, 8), pady=3)
            tk.Label(inner, text=ph, bg=Theme.BG_ELEVATED, fg=Theme.TEXT_FAINT,
                     font=(Theme.FONT_MONO, 8)).grid(row=i, column=2, sticky="w", pady=3)
        inner.columnconfigure(1, weight=1)

    # ----- 操作按钮栏 -----
    def _build_action_bar(self, parent) -> None:
        bar = tk.Frame(parent, bg=Theme.BG)
        bar.pack(fill="x", pady=(0, 8))
        FlatButton(bar, text="应用静态 IP", command=self._apply_static,
                   style="primary").pack(side="left", padx=(0, 6))
        FlatButton(bar, text="还原为 DHCP", command=self._apply_dhcp,
                   style="secondary").pack(side="left", padx=6)
        FlatButton(bar, text="还原上次备份", command=self._restore_backup,
                   style="secondary").pack(side="left", padx=6)

    # ----- 预设方案卡片 -----
    def _build_profile_card(self, parent) -> None:
        card = Card(parent, title="预设方案")
        card.pack(fill="both", expand=True, pady=(0, 8))
        inner = tk.Frame(card, bg=Theme.BG_ELEVATED)
        inner.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        tk.Label(inner, text="方案名", bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), width=6).grid(
            row=0, column=0, sticky="w", pady=3)
        ttk.Entry(inner, textvariable=self.profile_name_var).grid(
            row=0, column=1, sticky="we", padx=(6, 8), pady=3)
        FlatButton(inner, text="保存当前", command=self._save_profile,
                   style="primary").grid(row=0, column=2, padx=2, pady=3)

        tk.Label(inner, text="已有", bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), width=6).grid(
            row=1, column=0, sticky="w", pady=3)
        self.profile_combo = ttk.Combobox(inner, state="readonly")
        self.profile_combo.grid(row=1, column=1, sticky="we", padx=(6, 8), pady=3)
        FlatButton(inner, text="载入", command=self._load_profile,
                   style="secondary").grid(row=1, column=2, padx=2, pady=3)
        FlatButton(inner, text="应用", command=self._apply_profile,
                   style="primary").grid(row=1, column=3, padx=2, pady=3)
        FlatButton(inner, text="删除", command=self._delete_profile,
                   style="danger").grid(row=1, column=4, padx=2, pady=3)
        inner.columnconfigure(1, weight=1)

    # ----- 信息卡 -----
    def _build_info_card(self, parent) -> None:
        card = Card(parent, title="当前网卡配置")
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=Theme.BG_ELEVATED)
        inner.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        # 模式徽标
        badge_row = tk.Frame(inner, bg=Theme.BG_ELEVATED)
        badge_row.pack(fill="x", pady=(0, 8))
        tk.Label(badge_row, text="模式", bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                 font=(Theme.FONT_UI, Theme.FONT_UI_SIZE)).pack(side="left")
        self.mode_badge = tk.Label(
            badge_row, text=" 未知 ", bg=Theme.BG_INPUT, fg=Theme.TEXT_DIM,
            font=(Theme.FONT_UI, 8, "bold"), padx=8, pady=2,
            highlightbackground=Theme.BORDER, highlightthickness=1,
        )
        self.mode_badge.pack(side="left", padx=(8, 0))

        # 键值对信息
        self.info_labels: dict[str, tk.Label] = {}
        info_rows = [
            ("adapter", "网卡"),
            ("ip", "IP 地址"),
            ("mask", "子网掩码"),
            ("gateway", "默认网关"),
            ("dns1", "主用 DNS"),
            ("dns2", "备用 DNS"),
        ]
        for key, label in info_rows:
            row = tk.Frame(inner, bg=Theme.BG_ELEVATED)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=Theme.BG_ELEVATED, fg=Theme.TEXT_DIM,
                     font=(Theme.FONT_UI, Theme.FONT_UI_SIZE), width=8,
                     anchor="w").pack(side="left")
            val = tk.Label(row, text="—", bg=Theme.BG_ELEVATED, fg=Theme.TEXT,
                           font=(Theme.FONT_MONO, 10), anchor="w")
            val.pack(side="left", fill="x", expand=True)
            self.info_labels[key] = val

    # ----- 网卡 -----
    def _refresh_adapters(self) -> None:
        self._set_status("正在读取网卡列表...", "working")
        threading.Thread(target=self._do_refresh_adapters, daemon=True).start()

    def _do_refresh_adapters(self) -> None:
        try:
            names = self.mgr.list_adapters()
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"读取网卡失败:\n{e}", "error")
            self._set_status("读取网卡失败", "error")
            return
        if not names:
            self._safe_msgbox(
                "未读到网卡",
                "未能从 netsh 输出中解析出任何网卡。\n\n"
                "请把程序所在目录下的 netsh_debug.log 文件内容发回，"
                "我将据此调整解析逻辑。\n"
                "(该日志记录了 netsh 的原始输出)",
                "warning",
            )
            self._set_status("未读到网卡, 请查看 netsh_debug.log", "warning")
            return
        self.root.after(0, lambda: self._update_adapters(names))

    def _update_adapters(self, names: list[str]) -> None:
        self.adapter_combo["values"] = names
        if names:
            if self.adapter_var.get() not in names:
                self.adapter_var.set(names[0])
            self._load_current()
        self._set_status(f"共 {len(names)} 个网卡", "info")

    # ----- 当前配置 -----
    def _load_current(self) -> None:
        adapter = self.adapter_var.get()
        if not adapter:
            return
        self._set_status(f"正在读取 {adapter} 的当前配置...", "working")
        threading.Thread(
            target=self._do_load_current, args=(adapter,), daemon=True
        ).start()

    def _do_load_current(self, adapter: str) -> None:
        try:
            cfg = self.mgr.get_config(adapter)
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"读取配置失败:\n{e}", "error")
            self._set_status("读取配置失败", "error")
            return
        self.current_config = cfg
        self.root.after(0, lambda: self._fill_from_config(cfg))
        self._set_status("已读取当前配置", "success")

    def _fill_from_config(self, cfg: IpConfig) -> None:
        self.ip_var.set(cfg.ip)
        self.mask_var.set(cfg.mask)
        self.gateway_var.set(cfg.gateway)
        self.dns1_var.set(cfg.dns[0] if len(cfg.dns) > 0 else "")
        self.dns2_var.set(cfg.dns[1] if len(cfg.dns) > 1 else "")
        self._render_info(cfg)

    def _render_info(self, cfg: IpConfig) -> None:
        # 模式徽标
        if cfg.dhcp_enabled:
            self.mode_badge.configure(
                text=" DHCP (自动获取) ", bg="#0d2818", fg=Theme.SUCCESS,
                highlightbackground=Theme.SUCCESS,
            )
        else:
            self.mode_badge.configure(
                text=" 静态 IP ", bg="#0d1f2d", fg=Theme.INFO,
                highlightbackground=Theme.INFO,
            )
        # 键值对
        vals = {
            "adapter": cfg.adapter or "—",
            "ip": cfg.ip or "—",
            "mask": cfg.mask or "—",
            "gateway": cfg.gateway or "—",
            "dns1": cfg.dns[0] if len(cfg.dns) > 0 else "—",
            "dns2": cfg.dns[1] if len(cfg.dns) > 1 else "—",
        }
        for key, label in self.info_labels.items():
            label.configure(text=vals.get(key, "—"))

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
        self._set_status("正在应用静态 IP...", "working")
        threading.Thread(
            target=self._do_apply_static,
            args=(adapter, ip, mask, self.gateway_var.get().strip(), dns),
            daemon=True,
        ).start()

    def _do_apply_static(
        self, adapter: str, ip: str, mask: str, gateway: str, dns: list[str]
    ) -> None:
        try:
            try:
                cur = self.mgr.get_config(adapter)
                save_backup(cur)
            except Exception:  # noqa: BLE001
                pass
            self.mgr.set_static(adapter, ip, mask, gateway, dns)
        except Exception as e:  # noqa: BLE001
            self._safe_msgbox("错误", f"应用失败:\n{e}", "error")
            self._set_status("应用失败", "error")
            return
        self.root.after(0, self._on_applied_success)
        self._set_status("静态 IP 已应用", "success")

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
        self._set_status("正在还原为 DHCP...", "working")
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
            self._set_status("还原失败", "error")
            return
        self.root.after(
            0, lambda: (messagebox.showinfo("成功", "已还原为 DHCP"), self._load_current())
        )
        self._set_status("已还原为 DHCP", "success")

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
        self._set_status("正在还原上次备份...", "working")
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
            self._set_status("还原失败", "error")
            return
        self.root.after(
            0,
            lambda: (messagebox.showinfo("成功", "已还原为上次备份"), self._load_current()),
        )
        self._set_status("已还原为上次备份", "success")

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
        self._set_status(f"已载入方案 [{name}]", "info")

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
            self._set_status(f"已删除方案 [{name}]", "info")

    # ----- 辅助 -----
    def _set_status(self, text: str, level: str = "info") -> None:
        self.root.after(0, lambda: self.status_bar.set(text, level))

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
