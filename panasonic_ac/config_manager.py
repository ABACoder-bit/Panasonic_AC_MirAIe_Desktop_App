import os
import json
import base64
import sys
import winreg
import win32crypt
from logging_manager import get_logger

logger = get_logger("config_manager")

DEFAULT_SETTINGS = {
    "username": "",
    "password": "",  # Stored as base64-encoded encrypted DPAPI bytes
    "device_id": "", # Selected device ID (empty means auto-select first)
    "preferred_temperature": 25,
    "default_convert": "OFF",
    "startup_behavior": "open_dashboard",  # "open_dashboard" or "minimize_to_tray"
    "run_on_startup": False,
    "tray_settings": {
        "show_notifications": True
    },
    "automation_settings": {
        "enabled": True
    },
    "schedules": []
}

class ConfigManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.settings_file = os.path.join(base_dir, "settings.json")
        self.settings = DEFAULT_SETTINGS.copy()
        self.load_settings()

    def load_settings(self):
        """Loads settings from settings.json or creates a default one if missing."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge defaults for backward compatibility
                    for k, v in DEFAULT_SETTINGS.items():
                        if k not in loaded:
                            loaded[k] = v
                        elif isinstance(v, dict) and isinstance(loaded[k], dict):
                            for sub_k, sub_v in v.items():
                                if sub_k not in loaded[k]:
                                    loaded[k][sub_k] = sub_v
                    self.settings = loaded
            except Exception as e:
                logger.error("Failed to parse settings.json, resetting to defaults. Error: %s", e)
                self.settings = DEFAULT_SETTINGS.copy()
                self.save_settings()
        else:
            logger.info("settings.json not found. Creating default configuration.")
            self.settings = DEFAULT_SETTINGS.copy()
            self.save_settings()

    def save_settings(self):
        """Saves current settings to settings.json."""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logger.error("Failed to write settings.json: %s", e)

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save_settings()
        
        # If startup registry value changes, apply it
        if key == "run_on_startup":
            self.apply_startup_behavior(value)

    def encrypt_password(self, password: str) -> str:
        """Encrypts a password string using Windows DPAPI and returns it as a Base64 string."""
        if not password:
            return ""
        try:
            data_bytes = password.encode('utf-8')
            # DPAPI Encrypt
            encrypted_bytes = win32crypt.CryptProtectData(data_bytes, "Panasonic AC Password", None, None, None, 0)
            # Base64 encode for JSON compatibility
            return base64.b64encode(encrypted_bytes).decode('utf-8')
        except Exception as e:
            logger.error("DPAPI Encryption failed: %s", e)
            raise e

    def decrypt_password(self, encrypted_str: str) -> str:
        """Decrypts a Base64-encoded DPAPI-encrypted password string."""
        if not encrypted_str:
            return ""
        try:
            encrypted_bytes = base64.b64decode(encrypted_str.encode('utf-8'))
            # DPAPI Decrypt
            description, decrypted_bytes = win32crypt.CryptUnprotectData(encrypted_bytes, None, None, None, 0)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error("DPAPI Decryption failed: %s", e)
            raise e

    def get_decrypted_password(self) -> str:
        """Retrieves and decrypts the password stored in settings."""
        encrypted_pw = self.get("password")
        if not encrypted_pw:
            return ""
        return self.decrypt_password(encrypted_pw)

    def set_encrypted_password(self, password: str):
        """Encrypts and stores the password in settings."""
        encrypted_pw = self.encrypt_password(password)
        self.set("password", encrypted_pw)

    def apply_startup_behavior(self, run_on_startup: bool):
        """Configures the Windows registry to run the app on startup."""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "PanasonicACController"
        
        # Build command depending on whether running frozen (PyInstaller) or raw script
        if getattr(sys, 'frozen', False):
            # Running as executable
            cmd = f'"{sys.executable}" --minimized'
        else:
            # Running as python script
            script_path = os.path.abspath(sys.argv[0])
            # If the entry point is app.py in parent directory or child
            cmd = f'"{sys.executable}" "{script_path}" --minimized'

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if run_on_startup:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
                logger.info("Added startup registry entry: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    logger.info("Removed startup registry entry.")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            logger.error("Failed to modify startup registry key: %s", e)
