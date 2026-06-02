import os
import sys
import queue
import time
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Add current directory to path just in case
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from logging_manager import setup_logging, get_logger
from config_manager import ConfigManager
from ac_controller import ACController
from profile_manager import ProfileManager
from automation_engine import AutomationEngine
from scheduler import Scheduler
from tray_app import TrayApp

def get_base_dir():
    # If running as PyInstaller bundle
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            base_dir = os.path.join(appdata, "PanasonicACController")
        else:
            base_dir = os.path.join(os.path.dirname(sys.executable), "data")
    else:
        # Running in development mode
        base_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(base_dir, exist_ok=True)
    return base_dir

# Initialize logging first
BASE_DIR = get_base_dir()
logger = setup_logging(BASE_DIR)

class PanasonicACApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Panasonic MirAIe AC Controller")
        self.root.geometry("850x650")
        self.root.configure(bg="#121212")
        self.root.resizable(False, False)
        
        # Set icon if generated
        ico_path = os.path.join(BASE_DIR, "assets", "icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass

        # Thread-safe GUI event queue
        self.gui_queue = queue.Queue()

        # Initialize core managers
        self.config_manager = ConfigManager(BASE_DIR)
        self.profile_manager = ProfileManager(BASE_DIR)
        
        self.ac = ACController(self.config_manager)
        self.ac.register_callback(self._on_ac_status_updated)
        
        self.automation_engine = AutomationEngine(self.ac)
        self.automation_engine.register_notification_callback(self.show_toast)
        self.automation_engine.register_status_callback(self._on_automation_status_changed)
        
        self.scheduler = Scheduler(self.config_manager, self.profile_manager, self.automation_engine)
        self.scheduler.register_notification_callback(self.show_toast)
        self.scheduler.start()

        # Initialize Tray
        self.tray = TrayApp(
            self.ac,
            self.config_manager,
            open_dashboard_cb=self.restore_dashboard,
            exit_cb=self.exit_application
        )
        self.tray.start()

        # UI state variables
        self.active_automation_status = "None"
        self.log_file_pointer = 0
        self.connection_in_progress = False

        # Intercept window close to minimize to tray
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # Style Configuration
        self.setup_styles()

        # Build Main View Container
        self.container = tk.Frame(self.root, bg="#121212")
        self.container.pack(fill=tk.BOTH, expand=True)

        # Check startup argument (e.g. launched minimized via registry)
        if "--minimized" in sys.argv:
            self.root.withdraw()
            logger.info("Application started minimized to system tray.")
        else:
            # Check if username/password exist
            username = self.config_manager.get("username")
            password = self.config_manager.get_decrypted_password()
            if username and password:
                self.show_dashboard()
                self.trigger_background_connection()
            else:
                self.show_setup_screen()

        # Start GUI queue polling
        self.root.after(100, self.poll_gui_queue)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure Notebook Tab styles for Dark Theme
        style.configure('TNotebook', background='#121212', borderwidth=0)
        style.configure('TNotebook.Tab', 
                        background='#1E1E1E', 
                        foreground='#9CA3AF', 
                        padding=[12, 6], 
                        font=('Segoe UI', 10, 'bold'),
                        borderwidth=0)
        style.map('TNotebook.Tab', 
                  background=[('selected', '#0A5C99')], 
                  foreground=[('selected', '#FFFFFF')])
                  
        # Combobox styles
        style.configure('TCombobox', 
                        fieldbackground='#1E1E1E', 
                        background='#2D2D2D', 
                        foreground='#FFFFFF',
                        bordercolor='#2D2D2D',
                        darkcolor='#121212',
                        lightcolor='#1E1E1E')

    # Navigation Methods
    def show_setup_screen(self):
        """Displays credentials setup UI."""
        for widget in self.container.winfo_children():
            widget.destroy()
            
        frame = tk.Frame(self.container, bg="#121212")
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Header
        title = tk.Label(frame, text="Panasonic MirAIe AC Setup", font=("Segoe UI", 20, "bold"), bg="#121212", fg="#FFFFFF")
        title.pack(pady=(0, 20))

        subtitle = tk.Label(frame, text="Enter your MirAIe registered mobile number and password.", font=("Segoe UI", 10), bg="#121212", fg="#9CA3AF")
        subtitle.pack(pady=(0, 20))

        # Credentials Fields
        fields_frame = tk.Frame(frame, bg="#1E1E1E", bd=1, relief=tk.FLAT, padx=20, pady=20)
        fields_frame.pack(pady=10)

        # Phone
        tk.Label(fields_frame, text="Mobile Number (with +91 e.g. +91XXXXXXXXXX):", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#FFFFFF").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.phone_ent = tk.Entry(fields_frame, font=("Segoe UI", 12), width=30, bg="#121212", fg="#FFFFFF", insertbackground="white", bd=1, relief=tk.FLAT)
        self.phone_ent.grid(row=1, column=0, pady=(0, 15))
        self.phone_ent.insert(0, self.config_manager.get("username") or "+91")

        # Password
        tk.Label(fields_frame, text="MirAIe Password:", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#FFFFFF").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.pass_ent = tk.Entry(fields_frame, font=("Segoe UI", 12), show="*", width=30, bg="#121212", fg="#FFFFFF", insertbackground="white", bd=1, relief=tk.FLAT)
        self.pass_ent.grid(row=3, column=0, pady=(0, 15))

        # Error display label
        self.setup_err_lbl = tk.Label(frame, text="", font=("Segoe UI", 9, "bold"), bg="#121212", fg="#EF4444")
        self.setup_err_lbl.pack(pady=5)

        # Connect button
        self.conn_btn = tk.Button(
            frame, text="Authenticate & Connect", font=("Segoe UI", 11, "bold"), 
            bg="#0A5C99", fg="#FFFFFF", activebackground="#0D9488", activeforeground="#FFFFFF",
            relief=tk.FLAT, bd=0, padx=20, pady=10, command=self.handle_setup_connect
        )
        self.conn_btn.pack(pady=10)
        self._add_hover(self.conn_btn, "#0D9488", "#0A5C99")

    def handle_setup_connect(self):
        """Processes credentials verification and saves configuration."""
        phone = self.phone_ent.get().strip()
        password = self.pass_ent.get().strip()

        if not phone or not password or len(phone) < 10:
            self.setup_err_lbl.config(text="Please enter a valid phone number and password.")
            return

        self.setup_err_lbl.config(text="Authenticating... Please wait...", fg="#3B82F6")
        self.conn_btn.config(state=tk.DISABLED)

        # Temporarily set credentials
        self.config_manager.set("username", phone)
        self.config_manager.set_encrypted_password(password)

        def connect_done_cb(success, error):
            if success:
                self.gui_queue.put({"event": "setup_success"})
            else:
                self.gui_queue.put({"event": "setup_failed", "error": str(error)})

        # Fire connection
        self.ac.connect(connect_done_cb)

    def trigger_background_connection(self):
        """Initiates async connection silently in the background."""
        self.connection_in_progress = True
        self.ac.connect(lambda success, error: self.gui_queue.put({
            "event": "bg_connection_result",
            "success": success,
            "error": str(error) if error else None
        }))

    def show_dashboard(self):
        """Builds and displays the main dashboard view."""
        for widget in self.container.winfo_children():
            widget.destroy()

        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create Tab Frames
        self.tab_dash = tk.Frame(self.notebook, bg="#121212")
        self.tab_prof = tk.Frame(self.notebook, bg="#121212")
        self.tab_sched = tk.Frame(self.notebook, bg="#121212")
        self.tab_sett = tk.Frame(self.notebook, bg="#121212")

        self.notebook.add(self.tab_dash, text=" DASHBOARD ")
        self.notebook.add(self.tab_prof, text=" PROFILES & AUTOMATION ")
        self.notebook.add(self.tab_sched, text=" SCHEDULER ")
        self.notebook.add(self.tab_sett, text=" SETTINGS & LOGS ")

        # Draw UI Components
        self.build_dashboard_tab()
        self.build_profiles_tab()
        self.build_scheduler_tab()
        self.build_settings_tab()

        # Update displays
        self.update_dashboard_ui()
        self.refresh_schedules_list()

    # --- TAB 1: Dashboard UI ---
    def build_dashboard_tab(self):
        # Left Side (Status Monitor + Temp Control)
        left_frame = tk.Frame(self.tab_dash, bg="#121212", width=380)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)

        # Right Side (Controls grid)
        right_frame = tk.Frame(self.tab_dash, bg="#121212")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=10)

        # LEFT COLUMN CARDS
        # 1. Device Info Header Card
        header_card = tk.Frame(left_frame, bg="#1E1E1E", padx=15, pady=15)
        header_card.pack(fill=tk.X, pady=(0, 10))

        self.device_title_lbl = tk.Label(header_card, text="Panasonic Smart AC", font=("Segoe UI", 16, "bold"), bg="#1E1E1E", fg="#FFFFFF")
        self.device_title_lbl.pack(anchor=tk.W)

        # Status indicators
        stat_bar = tk.Frame(header_card, bg="#1E1E1E")
        stat_bar.pack(fill=tk.X, pady=(5, 0))

        self.online_dot = tk.Canvas(stat_bar, width=12, height=12, bg="#1E1E1E", highlightthickness=0)
        self.online_dot.pack(side=tk.LEFT, padx=(0, 5))
        self.online_dot.create_oval(2, 2, 10, 10, fill="#EF4444")  # Default red

        self.online_status_lbl = tk.Label(stat_bar, text="Disconnected (Cloud)", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#EF4444")
        self.online_status_lbl.pack(side=tk.LEFT)

        # 2. Main Thermostat Display Card
        thermo_card = tk.Frame(left_frame, bg="#1E1E1E", padx=20, pady=20)
        thermo_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Temperature Readings Layout
        readings_frame = tk.Frame(thermo_card, bg="#1E1E1E")
        readings_frame.pack(pady=10)

        # Big Target Temp
        self.target_temp_val_lbl = tk.Label(readings_frame, text="25", font=("Segoe UI", 48, "bold"), bg="#1E1E1E", fg="#FFFFFF")
        self.target_temp_val_lbl.grid(row=0, column=0, rowspan=2)
        
        tk.Label(readings_frame, text="°C", font=("Segoe UI", 20, "bold"), bg="#1E1E1E", fg="#0A5C99").grid(row=0, column=1, sticky=tk.N, padx=(0, 20))
        tk.Label(readings_frame, text="Target", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#9CA3AF").grid(row=1, column=1, sticky=tk.NW, padx=(0, 20))

        # Room Temperature Display
        room_temp_frame = tk.Frame(readings_frame, bg="#1E1E1E")
        room_temp_frame.grid(row=0, column=2, rowspan=2, padx=(10, 0))
        
        self.room_temp_val_lbl = tk.Label(room_temp_frame, text="--.-", font=("Segoe UI", 28, "bold"), bg="#1E1E1E", fg="#0D9488")
        self.room_temp_val_lbl.pack()
        
        tk.Label(room_temp_frame, text="Room Temp", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#9CA3AF").pack()

        # Temp increment buttons
        btn_frame = tk.Frame(thermo_card, bg="#1E1E1E")
        btn_frame.pack(pady=10)

        self.temp_down_btn = tk.Button(
            btn_frame, text="-", font=("Segoe UI", 16, "bold"), width=4,
            bg="#2D2D2D", fg="#FFFFFF", relief=tk.FLAT, bd=0, command=self.temp_decrease
        )
        self.temp_down_btn.grid(row=0, column=0, padx=10)
        self._add_hover(self.temp_down_btn, "#3B82F6", "#2D2D2D")

        self.temp_up_btn = tk.Button(
            btn_frame, text="+", font=("Segoe UI", 16, "bold"), width=4,
            bg="#2D2D2D", fg="#FFFFFF", relief=tk.FLAT, bd=0, command=self.temp_increase
        )
        self.temp_up_btn.grid(row=0, column=1, padx=10)
        self._add_hover(self.temp_up_btn, "#3B82F6", "#2D2D2D")

        # 3. Connection Monitor and Diagnostics Card
        diag_card = tk.Frame(left_frame, bg="#1E1E1E", padx=15, pady=15)
        diag_card.pack(fill=tk.X)

        self.power_btn = tk.Button(
            diag_card, text="Power OFF", font=("Segoe UI", 11, "bold"), height=2,
            bg="#EF4444", fg="#FFFFFF", relief=tk.FLAT, bd=0, command=self.toggle_power
        )
        self.power_btn.pack(fill=tk.X, pady=(0, 10))

        # Diagnostics Details
        diag_grid = tk.Frame(diag_card, bg="#1E1E1E")
        diag_grid.pack(fill=tk.X)

        tk.Label(diag_grid, text="Last Command Sent:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#9CA3AF").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.diag_last_cmd = tk.Label(diag_grid, text="None", font=("Segoe UI", 9), bg="#1E1E1E", fg="#FFFFFF")
        self.diag_last_cmd.grid(row=0, column=1, sticky=tk.E, pady=2)
        diag_grid.columnconfigure(1, weight=1)

        tk.Label(diag_grid, text="Communication Sync:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#9CA3AF").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.diag_last_sync = tk.Label(diag_grid, text="Never", font=("Segoe UI", 9), bg="#1E1E1E", fg="#FFFFFF")
        self.diag_last_sync.grid(row=1, column=1, sticky=tk.E, pady=2)

        # RIGHT COLUMN - MAIN CONTROLS
        # 1. Converti7 Control Panel
        conv_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        conv_card.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(conv_card, text="Converti7 Mode Control", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#0A5C99").pack(anchor=tk.W, pady=(0, 10))
        self.conv_btns = {}
        conv_btn_frame = tk.Frame(conv_card, bg="#1E1E1E")
        conv_btn_frame.pack(fill=tk.X)
        
        conv_modes = ["HC", "FC", "90%", "80%", "70%", "55%", "40%", "OFF"]
        for idx, mode in enumerate(conv_modes):
            btn = tk.Button(
                conv_btn_frame, text=mode, font=("Segoe UI", 9, "bold"), width=6, pady=6,
                bg="#2D2D2D", fg="#FFFFFF", relief=tk.FLAT, bd=0,
                command=lambda m=mode: self.ac.set_convert(m)
            )
            btn.grid(row=idx // 4, column=idx % 4, padx=4, pady=4, sticky="nsew")
            self._add_hover(btn, "#0A5C99", "#2D2D2D")
            self.conv_btns[mode] = btn
        for c in range(4):
            conv_btn_frame.columnconfigure(c, weight=1)

        # 2. Operating Mode
        mode_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        mode_card.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(mode_card, text="Operating Mode", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#0A5C99").pack(anchor=tk.W, pady=(0, 10))
        self.mode_btns = {}
        mode_btn_frame = tk.Frame(mode_card, bg="#1E1E1E")
        mode_btn_frame.pack(fill=tk.X)

        hvac_modes = ["COOL", "AUTO", "DRY", "FAN"]
        for idx, mode in enumerate(hvac_modes):
            btn = tk.Button(
                mode_btn_frame, text=mode, font=("Segoe UI", 9, "bold"), width=8, pady=6,
                bg="#2D2D2D", fg="#FFFFFF", relief=tk.FLAT, bd=0,
                command=lambda m=mode: self.ac.set_mode(m)
            )
            btn.grid(row=0, column=idx, padx=4, pady=4, sticky="nsew")
            self._add_hover(btn, "#0A5C99", "#2D2D2D")
            self.mode_btns[mode] = btn
        for c in range(4):
            mode_btn_frame.columnconfigure(c, weight=1)

        # 3. Fan Speed
        fan_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        fan_card.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(fan_card, text="Fan Speed", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#0A5C99").pack(anchor=tk.W, pady=(0, 10))
        self.fan_btns = {}
        fan_btn_frame = tk.Frame(fan_card, bg="#1E1E1E")
        fan_btn_frame.pack(fill=tk.X)

        fan_speeds = ["AUTO", "LOW", "MEDIUM", "HIGH"]
        for idx, speed in enumerate(fan_speeds):
            btn = tk.Button(
                fan_btn_frame, text=speed, font=("Segoe UI", 9, "bold"), width=8, pady=6,
                bg="#2D2D2D", fg="#FFFFFF", relief=tk.FLAT, bd=0,
                command=lambda s=speed: self.ac.set_fan_speed(s)
            )
            btn.grid(row=0, column=idx, padx=4, pady=4, sticky="nsew")
            self._add_hover(btn, "#0A5C99", "#2D2D2D")
            self.fan_btns[speed] = btn
        for c in range(4):
            fan_btn_frame.columnconfigure(c, weight=1)

        # 4. Swing Controls
        swing_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        swing_card.pack(fill=tk.X)
        
        tk.Label(swing_card, text="Air Swing Control", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#0A5C99").pack(anchor=tk.W, pady=(0, 10))
        
        swing_grid = tk.Frame(swing_card, bg="#1E1E1E")
        swing_grid.pack(fill=tk.X)

        # Vertical Swing dropdown
        tk.Label(swing_grid, text="Vertical Swing:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.v_swing_combo = ttk.Combobox(swing_grid, values=["AUTO", "1", "2", "3", "4", "5"], state="readonly", width=15)
        self.v_swing_combo.grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
        self.v_swing_combo.bind("<<ComboboxSelected>>", lambda e: self.ac.set_vertical_swing(self.v_swing_combo.get()))

        # Horizontal Swing dropdown
        tk.Label(swing_grid, text="Horizontal Swing:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.h_swing_combo = ttk.Combobox(swing_grid, values=["AUTO", "1", "2", "3", "4", "5"], state="readonly", width=15)
        self.h_swing_combo.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
        self.h_swing_combo.bind("<<ComboboxSelected>>", lambda e: self.ac.set_horizontal_swing(self.h_swing_combo.get()))

    # --- TAB 2: Profiles & Automation UI ---
    def build_profiles_tab(self):
        # Left Side (Profile Selector Cards)
        left_frame = tk.Frame(self.tab_prof, bg="#121212", width=350)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)

        # Right Side (Automation Engine status and details)
        right_frame = tk.Frame(self.tab_prof, bg="#121212")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=10)

        # Profiles List Frame
        prof_card = tk.Frame(left_frame, bg="#1E1E1E", padx=15, pady=15)
        prof_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(prof_card, text="Select Profile", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        # Profile selection listbox
        list_frame = tk.Frame(prof_card, bg="#1E1E1E")
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.profile_listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 11), bg="#121212", fg="#FFFFFF",
            selectbackground="#0A5C99", selectforeground="#FFFFFF",
            bd=0, highlightthickness=0
        )
        self.profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", self.on_profile_selected)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.profile_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.profile_listbox.config(yscrollcommand=scrollbar.set)

        # Load listbox items
        self.refresh_profiles_list()

        # Profile Action Controls
        act_btn_frame = tk.Frame(prof_card, bg="#1E1E1E", pady=10)
        act_btn_frame.pack(fill=tk.X)

        self.run_profile_btn = tk.Button(
            act_btn_frame, text="Run Profile", font=("Segoe UI", 10, "bold"),
            bg="#0D9488", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=8, command=self.run_selected_profile
        )
        self.run_profile_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._add_hover(self.run_profile_btn, "#0F766E", "#0D9488")

        # RIGHT COLUMN: Automation Engine Monitor
        engine_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        engine_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(engine_card, text="Automation Engine Monitor", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        # Status Card
        status_panel = tk.Frame(engine_card, bg="#121212", padx=15, pady=15)
        status_panel.pack(fill=tk.X, pady=(0, 15))

        tk.Label(status_panel, text="Engine Status:", font=("Segoe UI", 10, "bold"), bg="#121212", fg="#9CA3AF").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.engine_status_val = tk.Label(status_panel, text="Idle", font=("Segoe UI", 10, "bold"), bg="#121212", fg="#10B981")
        self.engine_status_val.grid(row=0, column=1, sticky=tk.W, padx=10, pady=3)

        tk.Label(status_panel, text="Active Task:", font=("Segoe UI", 10, "bold"), bg="#121212", fg="#9CA3AF").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.engine_task_val = tk.Label(status_panel, text="None", font=("Segoe UI", 10), bg="#121212", fg="#FFFFFF")
        self.engine_task_val.grid(row=1, column=1, sticky=tk.W, padx=10, pady=3)

        # Cancel button
        self.cancel_autom_btn = tk.Button(
            engine_card, text="Abort Active Automations", font=("Segoe UI", 10, "bold"),
            bg="#EF4444", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=8, command=self.automation_engine.stop_all
        )
        self.cancel_autom_btn.pack(fill=tk.X, pady=(0, 15))
        self._add_hover(self.cancel_autom_btn, "#DC2626", "#EF4444")

        # Action Steps Description text box
        tk.Label(engine_card, text="Profile Summary & Steps:", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#9CA3AF").pack(anchor=tk.W, pady=(0, 5))
        self.profile_desc_txt = tk.Text(engine_card, font=("Segoe UI", 10), bg="#121212", fg="#FFFFFF", bd=0, height=10, wrap=tk.WORD)
        self.profile_desc_txt.pack(fill=tk.BOTH, expand=True)

    def refresh_profiles_list(self):
        self.profiles = self.profile_manager.list_profiles()
        self.profile_listbox.delete(0, tk.END)
        for slug in sorted(self.profiles.keys()):
            name = self.profiles[slug]["name"]
            self.profile_listbox.insert(tk.END, name)

    def on_profile_selected(self, event):
        selection = self.profile_listbox.curselection()
        if not selection:
            return
            
        index = selection[0]
        # Map back to slug
        sorted_slugs = sorted(self.profiles.keys())
        slug = sorted_slugs[index]
        profile = self.profiles[slug]
        
        self.profile_desc_txt.config(state=tk.NORMAL)
        self.profile_desc_txt.delete("1.0", tk.END)
        
        # Write Profile description
        self.profile_desc_txt.insert(tk.END, f"Profile: {profile['name']}\n")
        self.profile_desc_txt.insert(tk.END, f"Description: {profile['description']}\n\n")
        self.profile_desc_txt.insert(tk.END, "Steps to execute:\n")
        
        for idx, act in enumerate(profile["actions"]):
            t = act.get("type", "")
            val = act.get("value", "")
            if t == "delay":
                m, s = divmod(int(val), 60)
                h, m = divmod(m, 60)
                dur = f"{h}h {m}m" if h else f"{m}m" if m else f"{s}s"
                self.profile_desc_txt.insert(tk.END, f"  {idx+1}. Wait for {dur}\n")
            elif t == "notification":
                self.profile_desc_txt.insert(tk.END, f"  {idx+1}. Send Notification: '{val}'\n")
            elif t == "condition":
                self.profile_desc_txt.insert(tk.END, f"  {idx+1}. If {act.get('variable')} {act.get('operator')} {act.get('value')} -> run nested actions\n")
            else:
                self.profile_desc_txt.insert(tk.END, f"  {idx+1}. Set {t.replace('_', ' ').title()} -> {val}\n")
                
        self.profile_desc_txt.config(state=tk.DISABLED)

    def run_selected_profile(self):
        selection = self.profile_listbox.curselection()
        if not selection:
            messagebox.showwarning("Run Profile", "Please select a profile from the list first.")
            return
            
        index = selection[0]
        sorted_slugs = sorted(self.profiles.keys())
        slug = sorted_slugs[index]
        profile = self.profiles[slug]
        
        self.automation_engine.run_sequence(profile["name"], profile["actions"])

    # --- TAB 3: Scheduler UI ---
    def build_scheduler_tab(self):
        # Grid layout: left column displays active list, right column is creation form
        left_frame = tk.Frame(self.tab_sched, bg="#121212", width=420)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)

        right_frame = tk.Frame(self.tab_sched, bg="#121212")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=10)

        # 1. Active Schedules List Card
        list_card = tk.Frame(left_frame, bg="#1E1E1E", padx=15, pady=15)
        list_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(list_card, text="Configured Schedules", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        # treeview for schedules
        self.sched_tree = ttk.Treeview(
            list_card, columns=("name", "type", "time", "profile", "status"), show="headings", height=10
        )
        self.sched_tree.heading("name", text="Schedule Name")
        self.sched_tree.heading("type", text="Type")
        self.sched_tree.heading("time", text="Time")
        self.sched_tree.heading("profile", text="Profile")
        self.sched_tree.heading("status", text="Status")
        
        self.sched_tree.column("name", width=120)
        self.sched_tree.column("type", width=70)
        self.sched_tree.column("time", width=100)
        self.sched_tree.column("profile", width=80)
        self.sched_tree.column("status", width=60)
        self.sched_tree.pack(fill=tk.BOTH, expand=True)
        
        # Row action buttons
        row_btn_frame = tk.Frame(list_card, bg="#1E1E1E", pady=10)
        row_btn_frame.pack(fill=tk.X)

        self.toggle_sched_btn = tk.Button(
            row_btn_frame, text="Toggle Status", font=("Segoe UI", 9, "bold"),
            bg="#0A5C99", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=6, command=self.toggle_selected_schedule
        )
        self.toggle_sched_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._add_hover(self.toggle_sched_btn, "#0D9488", "#0A5C99")

        self.del_sched_btn = tk.Button(
            row_btn_frame, text="Delete Schedule", font=("Segoe UI", 9, "bold"),
            bg="#EF4444", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=6, command=self.delete_selected_schedule
        )
        self.del_sched_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        self._add_hover(self.del_sched_btn, "#DC2626", "#EF4444")

        # 2. Schedule Creation Form Card (Right)
        form_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        form_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_card, text="Create New Schedule", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        # Fields
        tk.Label(form_card, text="Friendly Name:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(5, 2))
        self.sched_name_ent = tk.Entry(form_card, font=("Segoe UI", 10), bg="#121212", fg="#FFFFFF", insertbackground="white", bd=1, relief=tk.FLAT)
        self.sched_name_ent.pack(fill=tk.X, pady=(0, 10))

        tk.Label(form_card, text="Trigger Frequency:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(5, 2))
        self.sched_type_combo = ttk.Combobox(form_card, values=["Daily", "Weekdays", "Weekends", "Once"], state="readonly")
        self.sched_type_combo.pack(fill=tk.X, pady=(0, 10))
        self.sched_type_combo.set("Daily")
        self.sched_type_combo.bind("<<ComboboxSelected>>", self.on_sched_type_combo_changed)

        tk.Label(form_card, text="Time (24-Hour HH:MM or YYYY-MM-DD HH:MM):", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(5, 2))
        self.sched_time_ent = tk.Entry(form_card, font=("Segoe UI", 10), bg="#121212", fg="#FFFFFF", insertbackground="white", bd=1, relief=tk.FLAT)
        self.sched_time_ent.pack(fill=tk.X, pady=(0, 10))
        self.sched_time_ent.insert(0, "22:00")

        tk.Label(form_card, text="Run Profile on Trigger:", font=("Segoe UI", 9, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(5, 2))
        self.sched_prof_combo = ttk.Combobox(form_card, state="readonly")
        self.sched_prof_combo.pack(fill=tk.X, pady=(0, 15))
        self.refresh_schedules_form_combobox()

        self.add_sched_btn = tk.Button(
            form_card, text="Add Active Schedule", font=("Segoe UI", 10, "bold"),
            bg="#0D9488", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=8, command=self.create_schedule
        )
        self.add_sched_btn.pack(fill=tk.X)
        self._add_hover(self.add_sched_btn, "#0F766E", "#0D9488")

    def on_sched_type_combo_changed(self, event):
        t = self.sched_type_combo.get()
        self.sched_time_ent.delete(0, tk.END)
        if t == "Once":
            now = datetime.datetime.now()
            # Default to tomorrow same time
            tomorrow = now + datetime.timedelta(days=1)
            self.sched_time_ent.insert(0, tomorrow.strftime("%Y-%m-%d %H:%M"))
        else:
            self.sched_time_ent.insert(0, "22:00")

    def refresh_schedules_form_combobox(self):
        slugs = sorted(self.profile_manager.list_profiles().keys())
        self.sched_prof_combo.config(values=slugs)
        if slugs:
            self.sched_prof_combo.set(slugs[0])

    def refresh_schedules_list(self):
        self.sched_tree.delete(*self.sched_tree.get_children())
        for s in self.scheduler.schedules:
            status_text = "Enabled" if s.get("enabled", True) else "Disabled"
            self.sched_tree.insert(
                "", tk.END, iid=s.get("id"),
                values=(
                    s.get("name"),
                    s.get("type").title(),
                    s.get("time"),
                    s.get("profile"),
                    status_text
                )
            )

    def create_schedule(self):
        name = self.sched_name_ent.get().strip()
        stype = self.sched_type_combo.get().lower()
        stime = self.sched_time_ent.get().strip()
        profile = self.sched_prof_combo.get()

        if not name or not stime:
            messagebox.showwarning("New Schedule", "Please fill in all the details for the schedule.")
            return

        # Simple verification of time format
        try:
            if stype == "once":
                datetime.datetime.strptime(stime, "%Y-%m-%d %H:%M")
            else:
                datetime.datetime.strptime(stime, "%H:%M")
        except ValueError:
            messagebox.showerror(
                "Invalid Time",
                "Format mismatch:\n"
                "- Daily/Weekdays/Weekends: HH:MM (e.g. 22:00)\n"
                "- Once: YYYY-MM-DD HH:MM (e.g. 2026-06-03 10:00)"
            )
            return

        self.scheduler.add_schedule(name, stype, stime, profile)
        self.refresh_schedules_list()
        
        # Reset form fields
        self.sched_name_ent.delete(0, tk.END)
        messagebox.showinfo("Schedule Added", f"Successfully created schedule '{name}'")

    def toggle_selected_schedule(self):
        selected = self.sched_tree.selection()
        if not selected:
            messagebox.showwarning("Toggle Schedule", "Select a schedule row from the list first.")
            return
            
        sched_id = selected[0]
        # find schedule
        current_state = True
        for s in self.scheduler.schedules:
            if s.get("id") == sched_id:
                current_state = s.get("enabled", True)
                break
                
        self.scheduler.toggle_schedule(sched_id, not current_state)
        self.refresh_schedules_list()

    def delete_selected_schedule(self):
        selected = self.sched_tree.selection()
        if not selected:
            messagebox.showwarning("Delete Schedule", "Select a schedule row from the list first.")
            return
            
        sched_id = selected[0]
        if messagebox.askyesno("Delete Schedule", "Are you sure you want to delete the selected schedule?"):
            self.scheduler.delete_schedule(sched_id)
            self.refresh_schedules_list()

    # --- TAB 4: Settings & Logs UI ---
    def build_settings_tab(self):
        # Grid layout: left side is credentials configuration, right side is log terminal
        left_frame = tk.Frame(self.tab_sett, bg="#121212", width=350)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)

        right_frame = tk.Frame(self.tab_sett, bg="#121212")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=10)

        # 1. Config Card
        conf_card = tk.Frame(left_frame, bg="#1E1E1E", padx=15, pady=15)
        conf_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(conf_card, text="Account Settings", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        # Startup behaviors
        behav_frame = tk.Frame(conf_card, bg="#1E1E1E")
        behav_frame.pack(fill=tk.X, pady=10)

        self.startup_run_val = tk.BooleanVar(value=self.config_manager.get("run_on_startup", False))
        self.startup_chk = tk.Checkbutton(
            behav_frame, text="Run on Windows Startup", var=self.startup_run_val,
            bg="#1E1E1E", fg="#FFFFFF", selectcolor="#1E1E1E", activebackground="#1E1E1E", activeforeground="#FFFFFF",
            font=("Segoe UI", 10), command=self.save_startup_setting
        )
        self.startup_chk.pack(anchor=tk.W, pady=2)

        self.toast_notify_val = tk.BooleanVar(value=self.config_manager.get("tray_settings", {}).get("show_notifications", True))
        self.toast_chk = tk.Checkbutton(
            behav_frame, text="Show Toast Notifications", var=self.toast_notify_val,
            bg="#1E1E1E", fg="#FFFFFF", selectcolor="#1E1E1E", activebackground="#1E1E1E", activeforeground="#FFFFFF",
            font=("Segoe UI", 10), command=self.save_notification_setting
        )
        self.toast_chk.pack(anchor=tk.W, pady=2)

        # Disconnect Account
        tk.Label(conf_card, text="Account Actions", font=("Segoe UI", 10, "bold"), bg="#1E1E1E", fg="#9CA3AF").pack(anchor=tk.W, pady=(20, 5))
        
        self.log_out_btn = tk.Button(
            conf_card, text="Disconnect MirAIe Account", font=("Segoe UI", 10, "bold"),
            bg="#EF4444", fg="#FFFFFF", relief=tk.FLAT, bd=0, pady=8, command=self.logout_account
        )
        self.log_out_btn.pack(fill=tk.X, pady=(0, 10))
        self._add_hover(self.log_out_btn, "#DC2626", "#EF4444")

        # 2. Logs Console Card (Right)
        logs_card = tk.Frame(right_frame, bg="#1E1E1E", padx=15, pady=15)
        logs_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(logs_card, text="System Log Console", font=("Segoe UI", 12, "bold"), bg="#1E1E1E", fg="#FFFFFF").pack(anchor=tk.W, pady=(0, 10))

        self.logs_txt = scrolledtext.ScrolledText(
            logs_card, font=("Consolas", 9), bg="#121212", fg="#34D399", bd=0, wrap=tk.NONE
        )
        self.logs_txt.pack(fill=tk.BOTH, expand=True)
        
        # Trigger log poll
        self.root.after(1000, self.poll_system_logs)

    def save_startup_setting(self):
        val = self.startup_run_val.get()
        self.config_manager.set("run_on_startup", val)

    def save_notification_setting(self):
        val = self.toast_notify_val.get()
        tray_settings = self.config_manager.get("tray_settings", {})
        tray_settings["show_notifications"] = val
        self.config_manager.set("tray_settings", tray_settings)

    def logout_account(self):
        if messagebox.askyesno("Disconnect Account", "Disconnecting will erase username, password and settings. Proceed?"):
            self.scheduler.stop()
            self.ac.remove_callback(self._on_ac_status_updated)
            
            # Clean settings.json
            self.config_manager.set("username", "")
            self.config_manager.set("password", "")
            self.config_manager.set("device_id", "")
            self.config_manager.set("run_on_startup", False)
            self.config_manager.set("schedules", [])
            
            # Show setup screen
            self.show_setup_screen()

    def poll_system_logs(self):
        """Periodically reads new logs from file and updates text box."""
        log_file = os.path.join(BASE_DIR, "logs", "panasonic_ac.log")
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    # If file grew smaller, reset pointer
                    f.seek(0, os.SEEK_END)
                    end_pos = f.tell()
                    
                    if end_pos < self.log_file_pointer:
                        self.log_file_pointer = 0
                        
                    f.seek(self.log_file_pointer)
                    new_data = f.read()
                    
                    if new_data:
                        self.logs_txt.config(state=tk.NORMAL)
                        self.logs_txt.insert(tk.END, new_data)
                        self.logs_txt.see(tk.END)
                        self.logs_txt.config(state=tk.DISABLED)
                        
                    self.log_file_pointer = end_pos
            except Exception as e:
                logger.error("Error reading log file: %s", e)
                
        # Repeat every 2 seconds
        self.root.after(2000, self.poll_system_logs)

    # --- GUI Worker Queue Event Handling ---
    def poll_gui_queue(self):
        """Handles thread-safe events dispatched from background threads."""
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                event_type = msg.get("event")
                
                if event_type == "status_update":
                    self.update_dashboard_ui()
                elif event_type == "setup_success":
                    messagebox.showinfo("Authentication Success", "Successfully authenticated with Panasonic MirAIe cloud!")
                    self.config_manager.save_settings()
                    self.show_dashboard()
                    self.trigger_background_connection()
                elif event_type == "setup_failed":
                    self.setup_err_lbl.config(text=f"Auth Failed: {msg.get('error')}", fg="#EF4444")
                    self.conn_btn.config(state=tk.NORMAL)
                elif event_type == "bg_connection_result":
                    self.connection_in_progress = False
                    success = msg.get("success")
                    if success:
                        self.show_toast("Connection Restored", "AC Controller online with MirAIe cloud.")
                    else:
                        self.show_toast("Connection Lost", f"MirAIe connect failure: {msg.get('error')}")
                    self.update_dashboard_ui()
                elif event_type == "toast":
                    self.tray.notify(msg["title"], msg["message"])
                elif event_type == "automation_update":
                    self.engine_status_val.config(
                        text=msg["status"], 
                        fg="#EF4444" if msg["status"] in ["Failed", "Cancelled"] else "#10B981" if msg["status"] == "Completed" else "#3B82F6"
                    )
                    self.engine_task_val.config(text=msg["step"])
                    
        except queue.Empty:
            pass
            
        # Re-trigger poll in 100ms
        self.root.after(100, self.poll_gui_queue)

    def _on_ac_status_updated(self):
        """Triggered from background thread on device state changes."""
        self.gui_queue.put({"event": "status_update"})

    def _on_automation_status_changed(self, run_id, name, status, step_info):
        """Triggered from automation engine thread on step execution changes."""
        self.gui_queue.put({
            "event": "automation_update",
            "run_id": run_id,
            "name": name,
            "status": status,
            "step": f"{name} - {step_info}"
        })

    def update_dashboard_ui(self):
        """Refreshes the Dashboard elements with data from the AC controller."""
        if not hasattr(self, "notebook"):
            return  # Not on dashboard view

        status = self.ac.get_status()
        
        # 1. Update Connection Header
        is_online = status.get("online")
        self.online_dot.delete("all")
        if is_online:
            self.online_dot.create_oval(2, 2, 10, 10, fill="#10B981")  # Green
            self.online_status_lbl.config(text="Online (Cloud Sync)", fg="#10B981")
        else:
            if self.connection_in_progress:
                self.online_dot.create_oval(2, 2, 10, 10, fill="#3B82F6")  # Blue
                self.online_status_lbl.config(text="Connecting to MirAIe...", fg="#3B82F6")
            else:
                self.online_dot.create_oval(2, 2, 10, 10, fill="#EF4444")  # Red
                self.online_status_lbl.config(text="Offline / Broker Reconnect", fg="#EF4444")

        # 2. Update Temperatures
        target_temp = status.get("target_temperature")
        room_temp = status.get("room_temperature")
        
        self.target_temp_val_lbl.config(text=f"{int(target_temp) if target_temp else '--'}")
        self.room_temp_val_lbl.config(text=f"{room_temp:.1f}°C" if room_temp else "--.-°C")

        # 3. Update Diagnostic panel
        self.diag_last_cmd.config(text=status.get("last_command") or "None")
        
        sync_time = status.get("last_comm_time")
        if sync_time:
            dt = datetime.datetime.fromtimestamp(sync_time)
            self.diag_last_sync.config(text=dt.strftime("%H:%M:%S"))
        else:
            self.diag_last_sync.config(text="Never")

        # 4. Update Power state button styling
        power = status.get("power")
        if power == "ON":
            self.power_btn.config(text="Power ON (Click to Stop)", bg="#10B981")
            self._add_hover(self.power_btn, "#059669", "#10B981")
        else:
            self.power_btn.config(text="Power OFF (Click to Start)", bg="#EF4444")
            self._add_hover(self.power_btn, "#DC2626", "#EF4444")

        # 5. Grid button highlights
        # Converti7
        curr_conv = status.get("convert")
        for mode, btn in self.conv_btns.items():
            if curr_conv == mode:
                btn.config(bg="#0A5C99", fg="#FFFFFF")
            else:
                btn.config(bg="#2D2D2D", fg="#CCCCCC")

        # HVAC Mode
        curr_mode = status.get("mode")
        for mode, btn in self.mode_btns.items():
            if curr_mode == mode:
                btn.config(bg="#0A5C99", fg="#FFFFFF")
            else:
                btn.config(bg="#2D2D2D", fg="#CCCCCC")

        # Fan speed
        curr_fan = status.get("fan_speed")
        for speed, btn in self.fan_btns.items():
            if curr_fan == speed:
                btn.config(bg="#0A5C99", fg="#FFFFFF")
            else:
                btn.config(bg="#2D2D2D", fg="#CCCCCC")

        # Swing Dropdowns (avoid writing while editing)
        curr_v_swing = status.get("v_swing")
        if self.v_swing_combo.get() != curr_v_swing:
            self.v_swing_combo.set(curr_v_swing)

        curr_h_swing = status.get("h_swing")
        if self.h_swing_combo.get() != curr_h_swing:
            self.h_swing_combo.set(curr_h_swing)

    # Core AC action triggers
    def toggle_power(self):
        status = self.ac.get_status()
        if status.get("power") == "ON":
            self.ac.turn_off()
            self.show_toast("AC Turned Off", "Power command OFF dispatched.")
        else:
            self.ac.turn_on()
            self.show_toast("AC Turned On", "Power command ON dispatched.")

    def temp_increase(self):
        t = self.ac.get_target_temperature()
        if t < 30:
            self.ac.set_temperature(t + 1.0)

    def temp_decrease(self):
        t = self.ac.get_target_temperature()
        if t > 16:
            self.ac.set_temperature(t - 1.0)

    # --- Windows Tray Controls ---
    def minimize_to_tray(self):
        """Hides Tkinter GUI and sends notification."""
        self.root.withdraw()
        self.show_toast(
            "Panasonic AC Controller",
            "Application minimized to system tray. Right-click the tray icon to control, or choose Open Dashboard."
        )

    def restore_dashboard(self):
        """Restores Tkinter GUI window to foreground."""
        self.root.after(0, self._restore_dashboard_sync)

    def _restore_dashboard_sync(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def show_toast(self, title, message):
        """Dispatches a notification request to the tray icon."""
        self.gui_queue.put({
            "event": "toast",
            "title": title,
            "message": message
        })

    def exit_application(self):
        """Completes thread shutdown and exits."""
        logger.info("Terminating application background tasks...")
        self.scheduler.stop()
        self.automation_engine.stop_all()
        # Destroy TK Window
        self.root.after(0, self.root.destroy)

    # --- GUI Helper: Custom flat hover binding ---
    def _add_hover(self, widget, hover_color, normal_color):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_color))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal_color))


if __name__ == "__main__":
    # Ensure Tkinter runs on Main Thread
    root = tk.Tk()
    app = PanasonicACApp(root)
    root.mainloop()
