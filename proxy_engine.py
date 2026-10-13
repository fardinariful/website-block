"""
FocusShield - Proxy Engine
A high-performance local HTTP/HTTPS tunneling proxy with domain whitelisting
and Windows System Proxy integration.
"""

import socket
import select
import threading
import time
import winreg
import ctypes
import re
from typing import Set, Callable, Optional

INTERNET_SETTINGS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

HTML_BLOCK_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Website Blocked - FocusShield</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
        }
        .icon {
            font-size: 56px;
            margin-bottom: 20px;
            display: inline-block;
        }
        h1 {
            font-size: 24px;
            font-weight: 700;
            color: #ef4444;
            margin-bottom: 12px;
        }
        p {
            font-size: 15px;
            color: #94a3b8;
            line-height: 1.6;
            margin-bottom: 20px;
        }
        .domain-badge {
            display: inline-block;
            background-color: #0f172a;
            color: #fca5a5;
            padding: 6px 16px;
            border-radius: 20px;
            font-family: monospace;
            font-size: 14px;
            margin-bottom: 24px;
            border: 1px solid #7f1d1d;
            word-break: break-all;
        }
        .footer-note {
            font-size: 12px;
            color: #64748b;
            border-top: 1px solid #334155;
            padding-top: 16px;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#128737;&#65039;</div>
        <h1>Website Blocked</h1>
        <p>This website is not on your allowed whitelist. FocusShield whitelist protection is currently active.</p>
        <div class="domain-badge">{{DOMAIN}}</div>
        <p style="font-size: 13px; color: #cbd5e1;">To access this site, add it to your Whitelist in the FocusShield app.</p>
        <div class="footer-note">FocusShield Protection &bull; Safe Browsing Mode</div>
    </div>
</body>
</html>"""


class SystemProxyManager:
    """Manages Windows Internet Settings (WinINet) system proxy."""

    @staticmethod
    def set_proxy(enable: bool, host: str = "127.0.0.1", port: int = 8989) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
                if enable:
                    proxy_server = f"{host}:{port}"
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)
                    winreg.SetValueEx(
                        key, "ProxyOverride", 0, winreg.REG_SZ, "<local>;localhost;127.0.0.1"
                    )

            wininet = ctypes.windll.wininet
            wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
            return True
        except Exception as e:
            print(f"[SystemProxyManager] Error setting proxy: {e}")
            return False

    @staticmethod
    def get_proxy_status() -> tuple[bool, str, str]:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_KEY, 0, winreg.KEY_READ
            ) as key:
                enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                try:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                except FileNotFoundError:
                    server = ""
                try:
                    override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                except FileNotFoundError:
                    override = ""
                return bool(enable), server, override
        except Exception:
            return False, "", ""

    @staticmethod
    def emergency_disable() -> bool:
        """Completely disables system proxy."""
        return SystemProxyManager.set_proxy(False)


class ProxyWatchdog:
    """
    Monitors Windows Internet Settings in real-time.
    If ProxyEnable is disabled or ProxyServer/ProxyOverride is changed while active,
    it automatically and immediately restores the proxy settings within milliseconds.
    """
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8989,
        check_interval: float = 0.4,
        on_tamper_callback: Optional[Callable[[int], None]] = None,
    ):
        self.host = host
        self.port = port
        self.check_interval = check_interval
        self.on_tamper_callback = on_tamper_callback
        self.tamper_count = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="ProxyWatchdog")
        self._thread.start()

    def stop(self):
        self._running = False

    def _watch_loop(self):
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        REG_NOTIFY_CHANGE_LAST_SET = 4
        expected_server = f"{self.host}:{self.port}"
        expected_override = "<local>;localhost;127.0.0.1"

        while self._running:
            h_key = None
            h_event = None
            try:
                h_key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    INTERNET_SETTINGS_KEY,
                    0,
                    winreg.KEY_NOTIFY | winreg.KEY_READ,
                )
                h_event = kernel32.CreateEventW(None, True, False, None)
                if not h_event:
                    time.sleep(self.check_interval)
                    self._verify_and_restore(expected_server, expected_override)
                    continue

                advapi32.RegNotifyChangeKeyValue(
                    int(h_key), False, REG_NOTIFY_CHANGE_LAST_SET, h_event, True
                )

                timeout_ms = int(self.check_interval * 1000)
                kernel32.WaitForSingleObject(h_event, timeout_ms)

                if not self._running:
                    break

                self._verify_and_restore(expected_server, expected_override)

            except Exception:
                time.sleep(self.check_interval)
            finally:
                if h_event:
                    kernel32.CloseHandle(h_event)
                if h_key:
                    winreg.CloseKey(h_key)

    def _verify_and_restore(self, expected_server: str, expected_override: str):
        if not self._running:
            return
        enabled, server, override = SystemProxyManager.get_proxy_status()
        if not enabled or server != expected_server or override != expected_override:
            if not self._running:
                return
            self.tamper_count += 1
            print(f"[ProxyWatchdog] Tamper detected! Auto-healing proxy (Attempt #{self.tamper_count})")
            SystemProxyManager.set_proxy(True, self.host, self.port)
            if self.on_tamper_callback:
                try:
                    self.on_tamper_callback(self.tamper_count)
                except Exception:
                    pass


class ProxyEngine:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8989,
        whitelist: Optional[Set[str]] = None,
        on_log_callback: Optional[Callable[[str, str, bool], None]] = None,
    ):
        self.host = host
        self.port = port
        self.whitelist: Set[str] = set(whitelist or [])
        self.on_log_callback = on_log_callback  # callback(timestamp, domain, is_allowed)
        self.on_tamper_callback: Optional[Callable[[int], None]] = None
        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.listen_thread: Optional[threading.Thread] = None

        # Anti-Tamper Watchdog
        self.watchdog = ProxyWatchdog(
            host=self.host,
            port=self.port,
            on_tamper_callback=self._on_watchdog_tamper,
        )

        # Statistics
        self.allowed_count = 0
        self.blocked_count = 0
        self.start_time: Optional[float] = None
        self._lock = threading.Lock()

    def _on_watchdog_tamper(self, count: int):
        if self.on_tamper_callback:
            try:
                self.on_tamper_callback(count)
            except Exception:
                pass

    DOMAIN_DEPENDENCIES = {
        "youtube.com": ["youtube.com", "googlevideo.com", "ytimg.com", "youtu.be", "google.com", "gstatic.com"],
        "google.com": ["google.com", "gstatic.com", "googleapis.com", "googleusercontent.com", "1e100.net"],
        "facebook.com": ["facebook.com", "fbcdn.net", "fbsbx.com", "facebook.net"],
        "github.com": ["github.com", "githubassets.com", "githubusercontent.com"],
        "chatgpt.com": ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"],
    }

    @classmethod
    def expand_dependencies(cls, domain: str) -> set[str]:
        clean = cls.clean_domain(domain)
        result = {clean}
        for parent_domain, deps in cls.DOMAIN_DEPENDENCIES.items():
            if clean == parent_domain or clean.endswith("." + parent_domain):
                result.update(deps)
        return result

    def update_whitelist(self, new_whitelist: Set[str]):
        with self._lock:
            cleaned = set()
            for d in new_whitelist:
                deps = self.expand_dependencies(d)
                cleaned.update(deps)
            self.whitelist = cleaned

    @staticmethod
    def clean_domain(domain_or_url: str) -> str:
        """Extract clean hostname/domain from URLs or user inputs."""
        s = domain_or_url.strip().lower()
        if "://" in s:
            s = s.split("://", 1)[1]
        s = s.split("/")[0].split("?")[0].split("#")[0]
        if ":" in s:
            s = s.split(":")[0]
        if s.startswith("www."):
            s = s[4:]
        # If user typed just 'youtube' or 'facebook' without tld
        if "." not in s and len(s) > 1:
            s = s + ".com"
        return s

    def is_domain_allowed(self, target_host: str) -> bool:
        host = self.clean_domain(target_host)
        if not host:
            return False

        if host in ("localhost", "127.0.0.1", "::1"):
            return True

        with self._lock:
            for allowed in self.whitelist:
                allowed_clean = self.clean_domain(allowed)
                if not allowed_clean:
                    continue
                if host == allowed_clean:
                    return True
                if host.endswith("." + allowed_clean):
                    return True
                if allowed.startswith("*.") and host.endswith(allowed[1:]):
                    return True

        return False

    def _log_event(self, domain: str, is_allowed: bool):
        with self._lock:
            if is_allowed:
                self.allowed_count += 1
            else:
                self.blocked_count += 1

        if self.on_log_callback:
            timestamp = time.strftime("%H:%M:%S")
            try:
                self.on_log_callback(timestamp, domain, is_allowed)
            except Exception:
                pass

    def start(self, enable_system_proxy: bool = True) -> bool:
        if self.running:
            return True

        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind((self.host, self.port))
            self.server_sock.listen(256)
            self.running = True
            self.start_time = time.time()

            self.listen_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.listen_thread.start()

            if enable_system_proxy:
                SystemProxyManager.set_proxy(True, self.host, self.port)
                self.watchdog.start()

            return True
        except Exception as e:
            print(f"[ProxyEngine] Failed to start: {e}")
            self.running = False
            return False

    def stop(self, disable_system_proxy: bool = True):
        self.running = False
        self.watchdog.stop()
        if disable_system_proxy:
            SystemProxyManager.set_proxy(False)

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, _ = self.server_sock.accept()
            except Exception:
                if not self.running:
                    break
                time.sleep(0.05)
                continue

            try:
                t = threading.Thread(
                    target=self._handle_client, args=(client_sock,), daemon=True
                )
                t.start()
            except Exception:
                pass

    def _handle_client(self, client_sock: socket.socket):
        remote_sock: Optional[socket.socket] = None
        try:
            client_sock.settimeout(6.0)
            header_data = b""
            while b"\r\n\r\n" not in header_data and len(header_data) < 16384:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                header_data += chunk

            if not header_data:
                client_sock.close()
                return

            first_line = header_data.split(b"\r\n")[0].decode("latin1", errors="ignore")
            parts = first_line.split(" ")
            if len(parts) < 2:
                client_sock.close()
                return

            method, target = parts[0].upper(), parts[1]

            if method == "CONNECT":
                # HTTPS Request
                if ":" in target:
                    target_host, target_port_str = target.split(":", 1)
                    try:
                        target_port = int(target_port_str)
                    except ValueError:
                        target_port = 443
                else:
                    target_host = target
                    target_port = 443

                if not self.is_domain_allowed(target_host):
                    self._log_event(target_host, False)
                    # Return 403 Forbidden with custom block message
                    block_resp = (
                        b"HTTP/1.1 403 Forbidden\r\n"
                        b"Content-Type: text/plain; charset=utf-8\r\n"
                        b"Connection: close\r\n\r\n"
                        b"FocusShield: Blocked (Site is not in whitelist)\r\n"
                    )
                    client_sock.sendall(block_resp)
                    client_sock.close()
                    return

                # Allowed HTTPS
                self._log_event(target_host, True)
                try:
                    remote_sock = socket.create_connection(
                        (target_host, target_port), timeout=6.0
                    )
                    client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                except Exception:
                    client_sock.close()
                    return

                self._tunnel_sockets(client_sock, remote_sock)

            else:
                # Regular HTTP Request
                host = None
                for line in header_data.split(b"\r\n")[1:]:
                    if line.lower().startswith(b"host:"):
                        host = line.split(b":", 1)[1].strip().decode("latin1", errors="ignore")
                        if ":" in host:
                            host = host.split(":")[0]
                        break

                if not host and "://" in target:
                    host = target.split("://", 1)[1].split("/")[0]
                    if ":" in host:
                        host = host.split(":")[0]

                target_host = host or "unknown"

                if not self.is_domain_allowed(target_host):
                    self._log_event(target_host, False)
                    html_content = HTML_BLOCK_TEMPLATE.replace("{{DOMAIN}}", target_host)
                    html_bytes = html_content.encode("utf-8")
                    block_resp = (
                        b"HTTP/1.1 403 Forbidden\r\n"
                        b"Content-Type: text/html; charset=utf-8\r\n"
                        b"Content-Length: " + str(len(html_bytes)).encode("ascii") + b"\r\n"
                        b"Connection: close\r\n\r\n" + html_bytes
                    )
                    client_sock.sendall(block_resp)
                    client_sock.close()
                    return

                # Allowed HTTP
                self._log_event(target_host, True)
                port = 80
                try:
                    remote_sock = socket.create_connection((target_host, port), timeout=6.0)
                    remote_sock.sendall(header_data)
                    self._tunnel_sockets(client_sock, remote_sock)
                except Exception:
                    client_sock.close()

        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            if remote_sock:
                try:
                    remote_sock.close()
                except Exception:
                    pass

    def _tunnel_sockets(self, s1: socket.socket, s2: socket.socket):
        s1.settimeout(60.0)
        s2.settimeout(60.0)
        sockets = [s1, s2]
        try:
            while self.running:
                readable, _, exceptional = select.select(sockets, [], sockets, 2.0)
                if exceptional:
                    break
                for s in readable:
                    other = s2 if s is s1 else s1
                    data = s.recv(32768)
                    if not data:
                        return
                    other.sendall(data)
        except Exception:
            pass
        finally:
            try:
                s1.close()
            except Exception:
                pass
            try:
                s2.close()
            except Exception:
                pass
