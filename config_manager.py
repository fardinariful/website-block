"""
FocusShield - Configuration & Whitelist Manager
Handles saving/loading of allowed domains, presets, and PIN protection.
"""

import json
import os
import sys
import hashlib
from typing import List, Set, Dict, Any

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_PATH = os.path.join(get_base_dir(), "whitelist_config.json")

PRESETS: Dict[str, List[str]] = {
    "Google Suite": [
        "google.com",
        "gstatic.com",
        "googleapis.com",
        "googleusercontent.com"
    ],
    "AI Tools (ChatGPT & Claude)": [
        "chatgpt.com",
        "openai.com",
        "oaistatic.com",
        "oaiusercontent.com",
        "claude.ai",
        "anthropic.com"
    ],
    "Developer Suite": [
        "github.com",
        "githubassets.com",
        "githubusercontent.com",
        "stackoverflow.com",
        "python.org",
        "pypi.org",
        "npmjs.com"
    ],
    "Study & Wikipedia": [
        "wikipedia.org",
        "wikimedia.org",
        "khanacademy.org",
        "coursera.org",
        "edx.org"
    ],
    "Productivity (Notion, Trello)": [
        "notion.so",
        "notion.site",
        "trello.com"
    ]
}


class ConfigManager:
    def __init__(self, filepath: str = DEFAULT_CONFIG_PATH):
        self.filepath = filepath
        self.whitelist: List[str] = [
            "google.com",
            "gstatic.com",
            "wikipedia.org"
        ]
        self.port: int = 8989
        self.pin_enabled: bool = False
        self.pin_hash: str = ""
        self.load()

    @staticmethod
    def hash_pin(pin: str) -> str:
        return hashlib.sha256(pin.encode("utf-8")).hexdigest()

    def verify_pin(self, pin: str) -> bool:
        if not self.pin_enabled:
            return True
        return self.hash_pin(pin) == self.pin_hash

    def set_pin(self, pin: str):
        if not pin.strip():
            self.pin_enabled = False
            self.pin_hash = ""
        else:
            self.pin_enabled = True
            self.pin_hash = self.hash_pin(pin.strip())
        self.save()

    def add_domain(self, domain_or_url: str) -> bool:
        from proxy_engine import ProxyEngine
        clean = ProxyEngine.clean_domain(domain_or_url)
        if clean and clean not in self.whitelist:
            self.whitelist.append(clean)
            self.whitelist.sort()
            self.save()
            return True
        return False

    def remove_domain(self, domain: str) -> bool:
        clean = domain.strip().lower()
        if clean in self.whitelist:
            self.whitelist.remove(clean)
            self.save()
            return True
        return False

    def add_preset(self, preset_name: str) -> int:
        if preset_name not in PRESETS:
            return 0
        added = 0
        for domain in PRESETS[preset_name]:
            if domain not in self.whitelist:
                self.whitelist.append(domain)
                added += 1
        if added > 0:
            self.whitelist.sort()
            self.save()
        return added

    def clear_whitelist(self):
        self.whitelist.clear()
        self.save()

    def load(self):
        if not os.path.exists(self.filepath):
            self.save()
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.whitelist = data.get("whitelist", self.whitelist)
                self.port = data.get("port", 8989)
                self.pin_enabled = data.get("pin_enabled", False)
                self.pin_hash = data.get("pin_hash", "")
        except Exception as e:
            print(f"[ConfigManager] Error loading config: {e}")

    def save(self):
        try:
            data = {
                "whitelist": self.whitelist,
                "port": self.port,
                "pin_enabled": self.pin_enabled,
                "pin_hash": self.pin_hash,
            }
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
