import os
import threading
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem
from logging_manager import get_logger

logger = get_logger("tray_app")

class TrayApp:
    def __init__(self, ac_controller, config_manager, open_dashboard_cb, exit_cb):
        self.ac = ac_controller
        self.config_manager = config_manager
        self.open_dashboard_cb = open_dashboard_cb
        self.exit_cb = exit_cb
        self.icon = None
        
        # Load or generate the icon image
        self.icon_image = self._load_or_generate_icon()

    def _load_or_generate_icon(self):
        """Loads assets/icon.png or generates a beautiful default icon using Pillow."""
        assets_dir = os.path.join(self.config_manager.base_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        
        png_path = os.path.join(assets_dir, "icon.png")
        ico_path = os.path.join(assets_dir, "icon.ico")
        
        if os.path.exists(png_path):
            try:
                return Image.open(png_path)
            except Exception as e:
                logger.error("Failed to load icon image: %s", e)
        
        # Draw a beautiful modern icon
        # Size 64x64 is optimal for Windows system tray
        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw Panasonic blue circle base
        draw.ellipse([4, 4, 60, 60], fill=(10, 92, 153, 255), outline=(255, 255, 255, 255), width=2)
        
        # Draw a white power symbol inside the circle
        # Arc for the circle cut
        draw.arc([16, 16, 48, 48], start=-60, end=240, fill=(255, 255, 255, 255), width=4)
        # Line for the power stick
        draw.line([32, 12, 32, 28], fill=(255, 255, 255, 255), width=4)
        
        try:
            img.save(png_path, "PNG")
            # Save ICO with multiple sizes for Windows binary compatibility
            img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            logger.info("Generated default asset icons in: %s", assets_dir)
        except Exception as e:
            logger.error("Could not write generated icon files: %s", e)
            
        return img

    def make_temp_menu(self):
        def set_temp(t):
            return lambda item: self.ac.set_temperature(t)
            
        def is_temp_active(t):
            return lambda item: int(self.ac.get_target_temperature()) == t

        items = []
        for t in range(16, 31):
            items.append(MenuItem(
                f"{t}°C",
                set_temp(t),
                checked=is_temp_active(t)
            ))
        return Menu(*items)

    def make_convert_menu(self):
        levels = ["HC", "FC", "90%", "80%", "70%", "55%", "40%", "OFF"]
        
        def set_conv(l):
            return lambda item: self.ac.set_convert(l)
            
        def is_conv_active(l):
            return lambda item: self.ac.get_status().get("convert") == l

        items = []
        for level in levels:
            items.append(MenuItem(
                level,
                set_conv(level),
                checked=is_conv_active(level)
            ))
        return Menu(*items)

    def make_fan_menu(self):
        speeds = ["AUTO", "LOW", "MEDIUM", "HIGH"]
        
        def set_fan(s):
            return lambda item: self.ac.set_fan_speed(s)
            
        def is_fan_active(s):
            return lambda item: self.ac.get_status().get("fan_speed") == s

        items = []
        for s in speeds:
            items.append(MenuItem(
                s,
                set_fan(s),
                checked=is_fan_active(s)
            ))
        return Menu(*items)

    def make_mode_menu(self):
        modes = ["COOL", "AUTO", "DRY", "FAN"]
        
        def set_mode(m):
            return lambda item: self.ac.set_mode(m)
            
        def is_mode_active(m):
            return lambda item: self.ac.get_status().get("mode") == m

        items = []
        for m in modes:
            items.append(MenuItem(
                m,
                set_mode(m),
                checked=is_mode_active(m)
            ))
        return Menu(*items)

    def toggle_power(self):
        status = self.ac.get_status()
        if status.get("power") == "ON":
            self.ac.turn_off()
        else:
            self.ac.turn_on()

    def start(self):
        """Starts the tray application in a background thread."""
        logger.info("Initializing system tray icon...")
        
        menu = Menu(
            MenuItem("Power (Toggle)", lambda item: self.toggle_power(), 
                     checked=lambda item: self.ac.get_status().get("power") == "ON"),
            Menu.SEPARATOR,
            MenuItem("Temperature", self.make_temp_menu()),
            MenuItem("Converti7", self.make_convert_menu()),
            MenuItem("Fan Speed", self.make_fan_menu()),
            MenuItem("Operating Mode", self.make_mode_menu()),
            Menu.SEPARATOR,
            MenuItem("Open Dashboard", lambda item: self.open_dashboard_cb()),
            MenuItem("Exit", lambda item: self.exit_app())
        )
        
        self.icon = Icon(
            "PanasonicAC",
            self.icon_image,
            "Panasonic AC Controller",
            menu
        )
        
        self.thread = threading.Thread(target=self.icon.run, daemon=True, name="PanasonicAC-TrayIconLoop")
        self.thread.start()
        logger.info("System tray icon thread started.")

    def notify(self, title, message):
        """Triggers a Windows balloon toast notification via the tray icon."""
        if not self.config_manager.get("tray_settings", {}).get("show_notifications", True):
            return
            
        if self.icon:
            try:
                self.icon.notify(message, title)
                logger.info("Toast notification shown: [%s] %s", title, message)
            except Exception as e:
                logger.error("Failed to show toast notification: %s", e)

    def exit_app(self):
        """Handles Exit option from tray menu."""
        logger.info("Exit requested from system tray menu.")
        if self.icon:
            self.icon.stop()
        self.exit_cb()
