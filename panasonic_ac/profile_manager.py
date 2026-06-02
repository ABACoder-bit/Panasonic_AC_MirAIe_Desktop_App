import os
import json
from logging_manager import get_logger

logger = get_logger("profile_manager")

DEFAULT_PROFILES = {
    "sleep": {
        "name": "Sleep",
        "description": "Gradually cools and saves power during sleep",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 26},
            {"type": "convert", "value": "55"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Sleep profile started. Initial cooling: 26°C @ 55%"},
            {"type": "delay", "value": 7200},  # 2 hours
            {"type": "temperature", "value": 27},
            {"type": "convert", "value": "40"},
            {"type": "notification", "value": "Sleep profile phase 2: Temp increased to 27°C @ 40%"}
        ]
    },
    "power_saver": {
        "name": "Power Saver",
        "description": "High temperature and low power convert level for max savings",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 27},
            {"type": "convert", "value": "40"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Power Saver profile activated. 27°C @ 40%"}
        ]
    },
    "maximum_cooling": {
        "name": "Maximum Cooling",
        "description": "Full power cooling to chill the room quickly",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 18},
            {"type": "convert", "value": "HC"},
            {"type": "fan", "value": "HIGH"},
            {"type": "mode", "value": "COOL"},
            {"type": "notification", "value": "Maximum Cooling activated! 18°C @ High Speed"}
        ]
    },
    "guest_mode": {
        "name": "Guest Mode",
        "description": "Comfortable settings with normal speed operation",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 24},
            {"type": "convert", "value": "OFF"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Guest Mode activated: Comfort cooling at 24°C"}
        ]
    },
    "monsoon_mode": {
        "name": "Monsoon Mode",
        "description": "Dehumidification focus for humid rainy days",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "mode", "value": "DRY"},
            {"type": "temperature", "value": 25},
            {"type": "convert", "value": "70"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Monsoon Mode activated: Dehumidifying @ 25°C"}
        ]
    },
    "summer_day": {
        "name": "Summer Day",
        "description": "Robust cooling for hot afternoon temperatures",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 23},
            {"type": "convert", "value": "80"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Summer Day cooling active: 23°C @ 80%"}
        ]
    },
    "summer_night": {
        "name": "Summer Night",
        "description": "Optimal cooling profile for warm summer nights",
        "actions": [
            {"type": "power", "value": "ON"},
            {"type": "temperature", "value": 25},
            {"type": "convert", "value": "55"},
            {"type": "fan", "value": "AUTO"},
            {"type": "notification", "value": "Summer Night profile active: 25°C @ 55%"}
        ]
    }
}

class ProfileManager:
    def __init__(self, base_dir):
        self.profiles_dir = os.path.join(base_dir, "profiles")
        os.makedirs(self.profiles_dir, exist_ok=True)
        self.initialize_default_profiles()

    def initialize_default_profiles(self):
        """Creates the default profile JSON files if they don't already exist."""
        for slug, data in DEFAULT_PROFILES.items():
            file_path = os.path.join(self.profiles_dir, f"{slug}.json")
            if not os.path.exists(file_path):
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    logger.info("Created default profile: %s", slug)
                except Exception as e:
                    logger.error("Failed to write default profile %s: %s", slug, e)

    def list_profiles(self):
        """Lists all available profiles with their names and descriptions."""
        profiles = {}
        if not os.path.exists(self.profiles_dir):
            return profiles
            
        for file_name in os.listdir(self.profiles_dir):
            if file_name.endswith(".json"):
                slug = file_name[:-5]
                file_path = os.path.join(self.profiles_dir, file_name)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        profiles[slug] = {
                            "name": data.get("name", slug.replace("_", " ").title()),
                            "description": data.get("description", ""),
                            "actions": data.get("actions", [])
                        }
                except Exception as e:
                    logger.error("Error reading profile file %s: %s", file_name, e)
        return profiles

    def get_profile(self, slug):
        """Loads a specific profile by its slug."""
        file_path = os.path.join(self.profiles_dir, f"{slug}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Error reading profile %s: %s", slug, e)
        return None

    def save_profile(self, slug, name, description, actions):
        """Saves or updates a profile."""
        file_path = os.path.join(self.profiles_dir, f"{slug}.json")
        data = {
            "name": name,
            "description": description,
            "actions": actions
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            logger.info("Saved profile: %s", slug)
            return True
        except Exception as e:
            logger.error("Failed to save profile %s: %s", slug, e)
            return False

    def delete_profile(self, slug):
        """Deletes a profile file."""
        # Prevent deletion of default profiles if you want, but custom ones should be deletable.
        file_path = os.path.join(self.profiles_dir, f"{slug}.json")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info("Deleted profile: %s", slug)
                return True
            except Exception as e:
                logger.error("Failed to delete profile %s: %s", slug, e)
        return False
