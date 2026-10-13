import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import time
import atexit
import signal
import sys
import os
import queue
import socket

from proxy_engine import ProxyEngine, SystemProxyManager
from config_manager import ConfigManager, PRESETS

import winreg

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

IPC_PORT = 8990
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

def check_existing_instance() -> bool:
    """Checks if FocusShield is already running in the background and tells it to show its window."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.8)
        s.connect(("127.0.0.1", IPC_PORT))
        s.sendall(b"SHOW\n")
        s.close()
        return True
    except Exception:
        return False

def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, "FocusShield")
            return bool(val)
    except Exception:
        return False

def set_autostart(enable: bool) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                if getattr(sys, "frozen", False):
                    exe_path = sys.executable
                else:
                    exe_path = os.path.abspath(sys.argv[0])
                cmd = f'"{exe_path}" --background'
                winreg.SetValueEx(key, "FocusShield", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "FocusShield")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"Error setting autostart: {e}")
        return False


def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class FocusShieldApp(ctk.CTk):
    def __init__(self, start_hidden: bool = False):
        super().__init__()

        self.title("FocusShield - Website Whitelist Blocker")
        self.geometry("920x720")
        self.minsize(860, 640)

        # Set window icon
        try:
            icon_path = get_resource_path("app_icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

        # Config & Proxy Engine
        self.config_mgr = ConfigManager()
        self.log_queue = queue.Queue()
        self.proxy_engine = ProxyEngine(
            port=self.config_mgr.port,
            whitelist=set(self.config_mgr.whitelist),
            on_log_callback=self._on_proxy_log,
        )
        self.proxy_engine.on_tamper_callback = self._on_proxy_tamper

        self.is_active = False
        self.timer_seconds = 0
        self.timer_running = False

        # IPC Listener so double-clicking .exe restores hidden window
        self._start_ipc_server()

        # Register cleanup on exit
        atexit.register(self._cleanup_on_exit)

        # Build UI
        self._build_header()
        self._build_hero_card()
        self._build_tabs()

        # Periodic background updates
        self.after(100, self._process_log_queue)
        self.after(1000, self._update_timer)

        # Window close handler
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)

        # If launched with start_hidden=True, immediately hide and start blocking
        if start_hidden:
            self.withdraw()
            if self.config_mgr.whitelist:
                self.after(50, self._start_blocking)

    def _start_ipc_server(self):
        try:
            self.ipc_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ipc_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.ipc_sock.bind(("127.0.0.1", IPC_PORT))
            self.ipc_sock.listen(5)
            threading.Thread(target=self._ipc_listen_loop, daemon=True).start()
        except Exception as e:
            print(f"IPC Server start error: {e}")

    def _ipc_listen_loop(self):
        while True:
            try:
                conn, _ = self.ipc_sock.accept()
                msg = conn.recv(1024).strip()
                conn.close()
                if msg == b"SHOW":
                    self.after(0, self.restore_from_hidden)
            except Exception:
                break

    def restore_from_hidden(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False))

    def _cleanup_on_exit(self):
        if self.proxy_engine:
            self.proxy_engine.stop(disable_system_proxy=True)
        SystemProxyManager.emergency_disable()

    def _on_proxy_log(self, timestamp: str, domain: str, is_allowed: bool):
        self.log_queue.put((timestamp, domain, is_allowed))

    def _on_proxy_tamper(self, count: int):
        self.after(0, lambda: self._handle_tamper(count))

    def _handle_tamper(self, count: int):
        if self.is_active:
            times = "time" if count == 1 else "times"
            self.status_desc_label.configure(
                text=f"STRICT WHITELIST ACTIVE • 🔒 Auto-Healed Proxy ({count} tamper attempt{'s' if count > 1 else ''} blocked!)",
                text_color="#f59e0b",
            )

    def _build_header(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=24, pady=(16, 8))

        # Title and branding
        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left")

        title_label = ctk.CTkLabel(
            title_box,
            text="🛡️ FocusShield",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#38bdf8",
        )
        title_label.pack(anchor="w")

        subtitle_label = ctk.CTkLabel(
            title_box,
            text="Strict Website Whitelist & Distraction Blocker",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
        )
        subtitle_label.pack(anchor="w")

        # Top Right Actions
        actions_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        actions_box.pack(side="right")

        self.btn_emergency = ctk.CTkButton(
            actions_box,
            text="🔄 Emergency Restore",
            fg_color="#334155",
            hover_color="#475569",
            text_color="#e2e8f0",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=150,
            height=32,
            command=self.emergency_restore_action,
        )
        self.btn_emergency.pack(side="right", padx=4)

    def _build_hero_card(self):
        self.hero_card = ctk.CTkFrame(self, fg_color="#1e293b", corner_radius=16, border_width=1, border_color="#334155")
        self.hero_card.pack(fill="x", padx=24, pady=8)

        inner = ctk.CTkFrame(self.hero_card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        # Left: Main Big Toggle Button
        left_box = ctk.CTkFrame(inner, fg_color="transparent")
        left_box.pack(side="left", fill="both", expand=True)

        self.btn_toggle = ctk.CTkButton(
            left_box,
            text="🚀 ACTIVATE & HIDE FROM TASKBAR",
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=48,
            corner_radius=12,
            command=self.toggle_blocking,
        )
        self.btn_toggle.pack(fill="x", pady=(0, 4))

        self.btn_hide_again = ctk.CTkButton(
            left_box,
            text="👁️ HIDE TO BACKGROUND (KEEP BLOCKING)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            height=30,
            corner_radius=8,
            command=self.withdraw,
        )
        # Not packed initially, only packed when active

        self.status_desc_label = ctk.CTkLabel(
            left_box,
            text="Normal Internet • All websites are currently accessible",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
        )
        self.status_desc_label.pack(anchor="w")

        self.switch_autostart = ctk.CTkSwitch(
            left_box,
            text="Always ON in this Profile (Auto-starts hidden on PC login)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
            progress_color="#0284c7",
            command=self.toggle_autostart_switch,
        )
        if is_autostart_enabled():
            self.switch_autostart.select()
        else:
            self.switch_autostart.deselect()
        self.switch_autostart.pack(anchor="w", pady=(6, 2))

        # Right: Mini Stat Cards
        stats_box = ctk.CTkFrame(inner, fg_color="transparent")
        stats_box.pack(side="right", padx=(16, 0))

        # Stat 1: Blocked
        self.card_blocked = self._create_stat_badge(stats_box, "🚫 Blocked", "0", "#ef4444")
        self.card_blocked.pack(side="left", padx=6)

        # Stat 2: Allowed
        self.card_allowed = self._create_stat_badge(stats_box, "✅ Allowed", "0", "#10b981")
        self.card_allowed.pack(side="left", padx=6)

        # Stat 3: Timer
        self.card_timer = self._create_stat_badge(stats_box, "⏱️ Active Time", "00:00:00", "#38bdf8")
        self.card_timer.pack(side="left", padx=6)

    def toggle_autostart_switch(self):
        val = bool(self.switch_autostart.get())
        set_autostart(val)
        if val:
            messagebox.showinfo(
                "Always ON Enabled",
                "FocusShield will now start automatically in the background\n"
                "every time you log in to this Windows profile!\n\n"
                "It will run completely silent without any taskbar icon."
            )
        else:
            messagebox.showinfo(
                "Always ON Disabled",
                "FocusShield will no longer start automatically on Windows login."
            )

    def _create_stat_badge(self, parent, label_text, default_val, text_color):
        badge = ctk.CTkFrame(parent, fg_color="#0f172a", corner_radius=10, width=105, height=62, border_width=1, border_color="#334155")
        badge.pack_propagate(False)

        val_label = ctk.CTkLabel(
            badge,
            text=default_val,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=text_color,
        )
        val_label.pack(pady=(8, 0))

        desc_label = ctk.CTkLabel(
            badge,
            text=label_text,
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8",
        )
        desc_label.pack(pady=(0, 6))
        badge.val_label = val_label
        return badge

    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(self, fg_color="#1e293b", corner_radius=14)
        self.tabview.pack(fill="both", expand=True, padx=24, pady=(8, 16))

        self.tab_whitelist = self.tabview.add("📋 Allowed Websites (Whitelist)")
        self.tab_traffic = self.tabview.add("⚡ Live Activity")
        self.tab_settings = self.tabview.add("⚙️ Settings & Security")

        self._build_whitelist_tab()
        self._build_traffic_tab()
        self._build_settings_tab()

    def _build_whitelist_tab(self):
        parent = self.tab_whitelist

        # Add Website Input Box
        input_frame = ctk.CTkFrame(parent, fg_color="transparent")
        input_frame.pack(fill="x", padx=12, pady=(12, 6))

        self.entry_domain = ctk.CTkEntry(
            input_frame,
            placeholder_text="Enter domain or URL (e.g. google.com, wikipedia.org, github.com)...",
            height=42,
            font=ctk.CTkFont(size=13),
            border_color="#334155",
            fg_color="#0f172a",
        )
        self.entry_domain.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_domain.bind("<Return>", lambda event: self.add_domain_action())

        self.btn_add = ctk.CTkButton(
            input_frame,
            text="+ Add Website",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=42,
            width=130,
            command=self.add_domain_action,
        )
        self.btn_add.pack(side="right")

        # Presets Bar
        presets_frame = ctk.CTkFrame(parent, fg_color="transparent")
        presets_frame.pack(fill="x", padx=12, pady=(0, 10))

        preset_title = ctk.CTkLabel(
            presets_frame,
            text="Quick Presets:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
        )
        preset_title.pack(side="left", padx=(0, 8))

        for name in PRESETS.keys():
            chip_btn = ctk.CTkButton(
                presets_frame,
                text=f"+ {name}",
                font=ctk.CTkFont(size=11),
                fg_color="#334155",
                hover_color="#475569",
                height=26,
                corner_radius=14,
                command=lambda p=name: self.add_preset_action(p),
            )
            chip_btn.pack(side="left", padx=3)

        # Counter and Action Bar
        list_header = ctk.CTkFrame(parent, fg_color="transparent")
        list_header.pack(fill="x", padx=12, pady=(4, 6))

        self.whitelist_count_label = ctk.CTkLabel(
            list_header,
            text=f"Whitelisted Domains ({len(self.config_mgr.whitelist)})",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e2e8f0",
        )
        self.whitelist_count_label.pack(side="left")

        actions_box = ctk.CTkFrame(list_header, fg_color="transparent")
        actions_box.pack(side="right")

        btn_import = ctk.CTkButton(
            actions_box,
            text="📥 Import",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            width=70,
            height=26,
            command=self.import_whitelist_action,
        )
        btn_import.pack(side="left", padx=3)

        btn_export = ctk.CTkButton(
            actions_box,
            text="📤 Export",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            width=70,
            height=26,
            command=self.export_whitelist_action,
        )
        btn_export.pack(side="left", padx=3)

        btn_clear = ctk.CTkButton(
            actions_box,
            text="🗑️ Clear All",
            font=ctk.CTkFont(size=11),
            fg_color="#991b1b",
            hover_color="#7f1d1d",
            width=80,
            height=26,
            command=self.clear_whitelist_action,
        )
        btn_clear.pack(side="left", padx=3)

        # Scrollable Whitelist List
        self.whitelist_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="#0f172a", corner_radius=10, border_width=1, border_color="#334155"
        )
        self.whitelist_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self._refresh_whitelist_ui()

    def _refresh_whitelist_ui(self):
        # Clear existing items
        for widget in self.whitelist_scroll.winfo_children():
            widget.destroy()

        self.whitelist_count_label.configure(
            text=f"Whitelisted Domains ({len(self.config_mgr.whitelist)})"
        )

        if not self.config_mgr.whitelist:
            empty_label = ctk.CTkLabel(
                self.whitelist_scroll,
                text="No websites in whitelist yet.\nAdd domains above to allow them during blocking mode.",
                font=ctk.CTkFont(size=13),
                text_color="#64748b",
            )
            empty_label.pack(pady=40)
            return

        for domain in self.config_mgr.whitelist:
            row = ctk.CTkFrame(self.whitelist_scroll, fg_color="#1e293b", corner_radius=8, height=38)
            row.pack(fill="x", pady=2, padx=4)
            row.pack_propagate(False)

            icon_lbl = ctk.CTkLabel(
                row,
                text="🌐",
                font=ctk.CTkFont(size=14),
                width=28,
            )
            icon_lbl.pack(side="left", padx=(8, 2))

            domain_lbl = ctk.CTkLabel(
                row,
                text=domain,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#38bdf8",
                anchor="w",
            )
            domain_lbl.pack(side="left", padx=4, fill="x", expand=True)

            subdomain_hint = ctk.CTkLabel(
                row,
                text="(includes *.subdomains)",
                font=ctk.CTkFont(size=11),
                text_color="#64748b",
            )
            subdomain_hint.pack(side="left", padx=8)

            btn_del = ctk.CTkButton(
                row,
                text="Remove",
                font=ctk.CTkFont(size=11),
                fg_color="#ef4444",
                hover_color="#dc2626",
                width=65,
                height=24,
                command=lambda d=domain: self.remove_domain_action(d),
            )
            btn_del.pack(side="right", padx=8)

    def _build_traffic_tab(self):
        parent = self.tab_traffic

        # Top Traffic Bar
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(12, 6))

        title = ctk.CTkLabel(
            bar,
            text="Real-Time Traffic Interceptor",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#e2e8f0",
        )
        title.pack(side="left")

        desc = ctk.CTkLabel(
            bar,
            text="• Blocked domains can be whitelisted with 1-click",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
        )
        desc.pack(side="left", padx=8)

        btn_clear_logs = ctk.CTkButton(
            bar,
            text="Clear Log",
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            width=80,
            height=26,
            command=self.clear_traffic_logs,
        )
        btn_clear_logs.pack(side="right")

        # Scrollable log view
        self.traffic_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="#0f172a", corner_radius=10, border_width=1, border_color="#334155"
        )
        self.traffic_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.traffic_rows = []

    def _build_settings_tab(self):
        parent = self.tab_settings

        scroll_settings = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll_settings.pack(fill="both", expand=True, padx=12, pady=12)

        # Section 1: Security PIN
        sec_card = ctk.CTkFrame(scroll_settings, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#334155")
        sec_card.pack(fill="x", pady=(0, 12), padx=4)

        sec_inner = ctk.CTkFrame(sec_card, fg_color="transparent")
        sec_inner.pack(fill="x", padx=16, pady=16)

        sec_title = ctk.CTkLabel(
            sec_inner,
            text="🔒 PIN Protection (Self-Control / Parental Lock)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#e2e8f0",
        )
        sec_title.pack(anchor="w", pady=(0, 4))

        sec_desc = ctk.CTkLabel(
            sec_inner,
            text="Require a 4-digit PIN to stop blocking or edit the whitelist.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
        )
        sec_desc.pack(anchor="w", pady=(0, 12))

        pin_controls = ctk.CTkFrame(sec_inner, fg_color="transparent")
        pin_controls.pack(fill="x")

        self.entry_pin = ctk.CTkEntry(
            pin_controls,
            placeholder_text="Enter 4-digit PIN...",
            show="*",
            width=180,
            height=34,
            font=ctk.CTkFont(size=13),
            fg_color="#1e293b",
        )
        self.entry_pin.pack(side="left", padx=(0, 8))

        self.btn_set_pin = ctk.CTkButton(
            pin_controls,
            text="Set / Update PIN",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            command=self.set_pin_action,
        )
        self.btn_set_pin.pack(side="left", padx=(0, 8))

        self.btn_remove_pin = ctk.CTkButton(
            pin_controls,
            text="Remove PIN",
            font=ctk.CTkFont(size=12),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=34,
            command=self.remove_pin_action,
        )
        self.btn_remove_pin.pack(side="left")

        self.pin_status_label = ctk.CTkLabel(
            sec_inner,
            text="PIN Status: " + ("PROTECTED 🔒" if self.config_mgr.pin_enabled else "Disabled (No PIN required)"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981" if not self.config_mgr.pin_enabled else "#f59e0b",
        )
        self.pin_status_label.pack(anchor="w", pady=(10, 0))

        # Section 2: Network & Proxy Info
        net_card = ctk.CTkFrame(scroll_settings, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#334155")
        net_card.pack(fill="x", pady=6, padx=4)

        net_inner = ctk.CTkFrame(net_card, fg_color="transparent")
        net_inner.pack(fill="x", padx=16, pady=16)

        net_title = ctk.CTkLabel(
            net_inner,
            text="🌐 Proxy & Network Configuration",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#e2e8f0",
        )
        net_title.pack(anchor="w", pady=(0, 4))

        net_info = ctk.CTkLabel(
            net_inner,
            text=f"Local Proxy Port: {self.config_mgr.port} (127.0.0.1:{self.config_mgr.port})\n"
            f"Windows WinINet API: Active Integration (Chrome, Edge, Brave, Opera supported)\n"
            f"HTTPS CONNECT Tunneling: Zero SSL decryption needed, safe and secure.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left",
        )
        net_info.pack(anchor="w", pady=(0, 10))

        btn_open_win_proxy = ctk.CTkButton(
            net_inner,
            text="Open Windows Proxy Settings",
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            height=32,
            command=lambda: os.system("start ms-settings:network-proxy"),
        )
        btn_open_win_proxy.pack(anchor="w")

        # Section 3: Emergency & Failsafe
        fail_card = ctk.CTkFrame(scroll_settings, fg_color="#0f172a", corner_radius=12, border_width=1, border_color="#334155")
        fail_card.pack(fill="x", pady=6, padx=4)

        fail_inner = ctk.CTkFrame(fail_card, fg_color="transparent")
        fail_inner.pack(fill="x", padx=16, pady=16)

        fail_title = ctk.CTkLabel(
            fail_inner,
            text="🚨 Emergency Recovery",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ef4444",
        )
        fail_title.pack(anchor="w", pady=(0, 4))

        fail_desc = ctk.CTkLabel(
            fail_inner,
            text="If you ever close the app unexpectedly or restart your PC and your internet feels restricted,\n"
            "click this button to immediately reset Windows proxy to disabled.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left",
        )
        fail_desc.pack(anchor="w", pady=(0, 10))

        btn_reset_net = ctk.CTkButton(
            fail_inner,
            text="Restore Normal Internet Immediately",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=34,
            command=self.emergency_restore_action,
        )
        btn_reset_net.pack(anchor="w")

    def _verify_pin_if_needed(self, action_name="proceed") -> bool:
        if not self.config_mgr.pin_enabled:
            return True

        dialog = ctk.CTkInputDialog(
            text=f"Enter 4-digit PIN to {action_name}:",
            title="PIN Verification",
        )
        pin_input = dialog.get_input()
        if pin_input is None:
            return False

        if self.config_mgr.verify_pin(pin_input):
            return True
        else:
            messagebox.showerror("Access Denied", "Incorrect PIN!")
            return False

    def toggle_blocking(self):
        if self.is_active:
            # Stopping blocking
            if not self._verify_pin_if_needed("stop blocking"):
                return
            self._stop_blocking()
            messagebox.showinfo(
                "Protection Stopped",
                "Website blocking has been STOPPED!\nNormal internet access is restored."
            )
        else:
            # Starting blocking
            if not self.config_mgr.whitelist:
                messagebox.showwarning(
                    "Empty Whitelist",
                    "Your whitelist is empty! Please add at least one allowed website before starting, otherwise all websites will be blocked."
                )
                return
            self._start_blocking()
            messagebox.showinfo(
                "Protection Active & Hidden",
                "Protection is now ACTIVE!\n\n"
                "• All websites are blocked except your whitelist.\n"
                "• This window is now HIDDEN from your taskbar.\n"
                "• To turn it OFF or edit websites, simply double-click FocusShield.exe again!"
            )
            self.withdraw()

    def _start_blocking(self):
        self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
        success = self.proxy_engine.start(enable_system_proxy=True)
        if success:
            self.is_active = True
            self.timer_seconds = 0
            self.timer_running = True

            self.btn_toggle.configure(
                text="🛑 STOP BLOCKING (RESTORE INTERNET)",
                fg_color="#ef4444",
                hover_color="#dc2626",
            )
            self.status_desc_label.configure(
                text="STRICT WHITELIST ACTIVE • 🔒 Anti-Tamper Proxy Lock Active",
                text_color="#ef4444",
            )
            self.btn_hide_again.pack(fill="x", pady=(2, 4))
            self.hero_card.configure(border_color="#10b981")
        else:
            messagebox.showerror("Error", "Failed to start proxy engine. Check if port is in use.")

    def _stop_blocking(self):
        self.proxy_engine.stop(disable_system_proxy=True)
        self.is_active = False
        self.timer_running = False

        self.btn_toggle.configure(
            text="🚀 ACTIVATE & HIDE FROM TASKBAR",
            fg_color="#0284c7",
            hover_color="#0369a1",
        )
        self.status_desc_label.configure(
            text="Normal Internet • All websites are currently accessible",
            text_color="#94a3b8",
        )
        self.btn_hide_again.pack_forget()
        self.hero_card.configure(border_color="#334155")

    def emergency_restore_action(self):
        if self.is_active:
            self._stop_blocking()
        else:
            SystemProxyManager.emergency_disable()
        messagebox.showinfo(
            "Internet Restored",
            "Windows system proxy has been completely disabled.\nNormal internet connection is restored!"
        )

    def add_domain_action(self):
        domain_text = self.entry_domain.get().strip()
        if not domain_text:
            return

        if self.config_mgr.add_domain(domain_text):
            self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
            self.entry_domain.delete(0, "end")
            self._refresh_whitelist_ui()
        else:
            messagebox.showinfo("Info", "Domain is already in whitelist or invalid.")

    def add_preset_action(self, preset_name: str):
        added = self.config_mgr.add_preset(preset_name)
        if added > 0:
            self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
            self._refresh_whitelist_ui()
            messagebox.showinfo("Preset Added", f"Added {added} domains from '{preset_name}'!")
        else:
            messagebox.showinfo("Info", f"All domains from '{preset_name}' are already in your whitelist.")

    def remove_domain_action(self, domain: str):
        if self.is_active and not self._verify_pin_if_needed("remove website"):
            return
        if self.config_mgr.remove_domain(domain):
            self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
            self._refresh_whitelist_ui()

    def clear_whitelist_action(self):
        if self.is_active and not self._verify_pin_if_needed("clear whitelist"):
            return
        if messagebox.askyesno("Confirm Clear", "Are you sure you want to remove all websites from whitelist?"):
            self.config_mgr.clear_whitelist()
            self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
            self._refresh_whitelist_ui()

    def export_whitelist_action(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="my_whitelist.json"
        )
        if filepath:
            import json
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"whitelist": self.config_mgr.whitelist}, f, indent=4)
            messagebox.showinfo("Exported", f"Saved {len(self.config_mgr.whitelist)} domains.")

    def import_whitelist_action(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("Text files", "*.txt")]
        )
        if filepath:
            try:
                import json
                added = 0
                if filepath.endswith(".json"):
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        domains = data.get("whitelist", [])
                else:
                    with open(filepath, "r", encoding="utf-8") as f:
                        domains = [line.strip() for line in f if line.strip()]

                for d in domains:
                    if self.config_mgr.add_domain(d):
                        added += 1

                self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
                self._refresh_whitelist_ui()
                messagebox.showinfo("Imported", f"Successfully added {added} new domains.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import: {e}")

    def set_pin_action(self):
        new_pin = self.entry_pin.get().strip()
        if not new_pin or len(new_pin) < 4:
            messagebox.showwarning("Invalid PIN", "PIN must be at least 4 digits.")
            return

        self.config_mgr.set_pin(new_pin)
        self.entry_pin.delete(0, "end")
        self.pin_status_label.configure(
            text="PIN Status: PROTECTED 🔒",
            text_color="#f59e0b",
        )
        messagebox.showinfo("PIN Set", "4-digit PIN protection is now active!")

    def remove_pin_action(self):
        if not self.config_mgr.pin_enabled:
            return
        if not self._verify_pin_if_needed("remove PIN protection"):
            return

        self.config_mgr.set_pin("")
        self.pin_status_label.configure(
            text="PIN Status: Disabled (No PIN required)",
            text_color="#10b981",
        )
        messagebox.showinfo("PIN Removed", "PIN protection has been disabled.")

    def clear_traffic_logs(self):
        for widget in self.traffic_scroll.winfo_children():
            widget.destroy()
        self.traffic_rows.clear()

    def _process_log_queue(self):
        while not self.log_queue.empty():
            try:
                timestamp, domain, is_allowed = self.log_queue.get_nowait()
                self._add_traffic_row(timestamp, domain, is_allowed)
            except queue.Empty:
                break

        # Update counter badges
        self.card_blocked.val_label.configure(text=str(self.proxy_engine.blocked_count))
        self.card_allowed.val_label.configure(text=str(self.proxy_engine.allowed_count))

        self.after(200, self._process_log_queue)

    def _add_traffic_row(self, timestamp: str, domain: str, is_allowed: bool):
        # Cap log rows at 100 for memory performance
        if len(self.traffic_rows) > 80:
            oldest = self.traffic_rows.pop(0)
            oldest.destroy()

        row = ctk.CTkFrame(
            self.traffic_scroll,
            fg_color="#1e293b",
            corner_radius=8,
            height=34,
        )
        row.pack(fill="x", pady=2, padx=4)
        row.pack_propagate(False)

        # Time
        time_lbl = ctk.CTkLabel(
            row,
            text=timestamp,
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
            width=60,
        )
        time_lbl.pack(side="left", padx=4)

        # Status Badge
        badge_text = "ALLOWED" if is_allowed else "BLOCKED"
        badge_color = "#10b981" if is_allowed else "#ef4444"
        status_lbl = ctk.CTkLabel(
            row,
            text=f"[{badge_text}]",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=badge_color,
            width=75,
        )
        status_lbl.pack(side="left", padx=4)

        # Domain
        domain_lbl = ctk.CTkLabel(
            row,
            text=domain,
            font=ctk.CTkFont(size=12),
            text_color="#f8fafc",
            anchor="w",
        )
        domain_lbl.pack(side="left", padx=6, fill="x", expand=True)

        # If blocked, quick "+ Allow" button
        if not is_allowed:
            clean = ProxyEngine.clean_domain(domain)
            if clean and clean not in self.config_mgr.whitelist:
                btn_allow = ctk.CTkButton(
                    row,
                    text="+ Whitelist",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    width=75,
                    height=22,
                    command=lambda d=clean: self._quick_whitelist_domain(d),
                )
                btn_allow.pack(side="right", padx=6)

        self.traffic_rows.append(row)

    def _quick_whitelist_domain(self, domain: str):
        if self.config_mgr.add_domain(domain):
            self.proxy_engine.update_whitelist(set(self.config_mgr.whitelist))
            self._refresh_whitelist_ui()
            messagebox.showinfo("Domain Allowed", f"'{domain}' added to Whitelist!")

    def _update_timer(self):
        if self.timer_running:
            self.timer_seconds += 1
            hrs = self.timer_seconds // 3600
            mins = (self.timer_seconds % 3600) // 60
            secs = self.timer_seconds % 60
            time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
            self.card_timer.val_label.configure(text=time_str)

        self.after(1000, self._update_timer)

    def on_window_close(self):
        if self.is_active:
            # If blocking is active, clicking [X] simply hides the window to background!
            self.withdraw()
        else:
            self.destroy()


def main():
    if check_existing_instance():
        # Told already-running background instance to restore window, exit this process
        sys.exit(0)

    start_hidden = "--background" in sys.argv or "--silent" in sys.argv
    app = FocusShieldApp(start_hidden=start_hidden)
    app.mainloop()


if __name__ == "__main__":
    main()
