# Panasonic MirAIe AC Controller for Windows

A lightweight, native Windows desktop application that controls a Panasonic MirAIe-enabled air conditioner via the cloud. Designed with a stunning dark mode interface, this application minimizes to the system tray, supports encrypted passwords using Windows DPAPI, displays live temperatures, and includes custom profile, scheduling, and automation engines.

## Key Features
* **Zero-config secure encryption**: Credentials are protected using Windows Data Protection API (DPAPI), meaning no plain-text passwords on disk.
* **Non-blocking background thread**: Run commands and MQTT subscriptions asynchronously on a separate thread, keeping the GUI fast and fluid.
* **Smart Command Queue**: Spacing publishes by 1.5s (rate limiting), retrying failed commands up to 3 times, and automatically suppressing duplicate commands (such as rapid temperature adjustments).
* **System Tray Minimization**: Closing the application minimizes it to the Windows system tray with right-click control shortcuts.
* **Profile & Automation Engine**: Execute timed sequences (e.g. sleep cooling curve) and room-temperature conditional checks.
* **Lightweight**: Optimized to run with `<100MB RAM` and `<1% CPU` idle usage (no Electron, no Chromium).

---

## Directory Structure
```text
panasonic_ac/
├── app.py                  # Main entry point and Tkinter GUI
├── ac_controller.py        # Core API wrapper and Command Queue worker
├── mqtt_manager.py         # Subclassed MirAIeBroker connection hooks
├── scheduler.py            # Date/Time evaluation loop for recurring tasks
├── tray_app.py             # System tray icon and dynamic right-click menu
├── config_manager.py       # Configuration and DPAPI encryption utility
├── automation_engine.py    # Sequential action and condition runner
├── profile_manager.py      # Default profile builder and custom manager
├── logging_manager.py      # Rotating file logging system
├── settings.json           # Active configuration (auto-created)
├── profiles/               # Profile JSON templates (auto-created)
├── logs/                   # System runtime log files (auto-created)
└── assets/                 # Custom compiled icons (auto-created)
```

---

## Installation Instructions

### Prerequisites
1. **Windows 11 or 10**
2. **Python 3.13** (or 3.10+): Make sure Python is added to your system `PATH`.

### Installation Steps
1. Open PowerShell and navigate to the project directory:
   ```powershell
   cd "d:\Projects_all\In_Progress\AC"
   ```
2. Install the required dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Configuration & Usage Instructions

### 1. First Time Run & Authentication
Simply run:
```powershell
python panasonic_ac/app.py
```
On your first startup, the app will detect missing credentials and present an **Authentication Setup** screen.
* Enter your registered **MirAIe Mobile Number** (must include the country code prefix, e.g., `+91XXXXXXXXXX`).
* Enter your **MirAIe Password**.
* Click **Authenticate & Connect**.

Once verified, the app will discover your AC unit and load the main control dashboard. The password is DPAPI-encrypted and saved inside `panasonic_ac/settings.json`.

### 2. Main Dashboard Controls
* **Power Button**: A large styled status button toggling the AC. (Green represents ON, Red represents OFF).
* **Temperature Grid**: Circular target temperature readout with `+` and `-` buttons. Live Room Temperature is shown in teal.
* **Quick Selectors**: Click grids for Fan Speed (Auto, Low, Medium, High), Modes (Cool, Auto, Dry, Fan), and Converti7 (HC, FC, 90%, 80%, 70%, 55%, 40%, OFF).
* **Air Swing**: Use the dropdown menus to select vertical and horizontal swings (Auto or Positions 1 to 5).
* **Sync Indicators**: Displays the last command dispatched and the precise timestamp of the last communication with the Panasonic server.

### 3. System Tray Usage
When you click the `[X]` button on the top right of the dashboard, the window hides and minimizes to the system tray.
* Double-click the tray icon (Panasonic Blue circle with a power symbol) to restore the dashboard.
* Right-click the tray icon to quickly trigger Power Toggle, select target temperatures, change Converti7 modes, or completely exit the application.

---

## Windows Executable Build Instructions
To build a standalone executable (`.exe`) that runs natively on Windows 11 with no console window popping up:
1. Install **PyInstaller**:
   ```powershell
   pip install pyinstaller
   ```
2. Navigate to the project root and compile the application:
   ```powershell
   pyinstaller --noconsole --onefile --add-data "panasonic_ac;panasonic_ac" --icon="panasonic_ac/assets/icon.ico" panasonic_ac/app.py
   ```
3. The executable will be compiled inside the `dist/` directory as `app.exe`. Copy `app.exe` to any folder on your machine and run it. It will automatically build its `profiles/`, `logs/`, and `assets/` subdirectories locally in its execution directory.

---

## Error Handling & Resiliency
* **Authentication Failures**: Handled on setup. If connection credentials fail, the UI unlocks, outputs the error reason, and allows you to retry.
* **MQTT Reconnects**: The `mqtt_manager.py` subclass intercepts disconnections. If a connection drops, it will trigger a background retry loop (every 5 seconds) and auto-refresh auth tokens, updating the dashboard status dot to blue/red and notifying the user.
* **Command Queue Fault Tolerances**: If an MQTT publish fails, the queue worker backs off and retries the command up to 3 times with exponential delays. If it permanently fails after 3 tries, it logs the error, flashes a diagnostic sync failure, and continues processing the next command.
* **Duplicate Suppression**: Multiple clicks to change temperature (e.g. pressing `+` multiple times) are compressed. The queue worker will only send the final desired temperature to the server, preventing command stack-ups.

---

## Logging
Logs are maintained locally inside `panasonic_ac/logs/panasonic_ac.log`.
* Log outputs use a rotating file handler capped at **5MB** (storing up to 3 backup rotations) to prevent running out of disk space.
* Logs track:
  * Setup & Authentication results
  * Background queue tasks and command dispatches
  * Reconnections and broker errors
  * Active schedules and automation steps
* Real-time logs can be viewed directly from the **Settings & Logs** tab in the GUI.

---

## Default Profiles & Automation Sequences

The app pre-populates default profile JSON templates under `panasonic_ac/profiles/`. You can edit these files or run them directly from the **Profiles** tab.

### 1. Sleep Profile (`sleep.json`)
* **Initial cooling**: Turns ON, sets Temp to 26°C, Converti7 to 55%, Fan to AUTO.
* **Delay**: Waits for 2 hours (cancellable delay).
* **Power Saver Adjustment**: Sets Temp to 27°C and Converti7 to 40% (keeping the room comfortable while saving electricity).

### 2. Power Saver (`power_saver.json`)
* Sets AC power to ON.
* Targets a high-efficiency temperature of 27°C.
* Sets Converti7 to 40% (the maximum power-saving level).
* Fan speed set to AUTO.

### 3. Maximum Cooling (`maximum_cooling.json`)
* Sets AC power to ON, mode to COOL.
* Targets a maximum cooling temperature of 18°C.
* Sets Converti7 to HC (High Cooling, 110% capacity).
* Fan speed set to HIGH.

---

## Example Custom Automation Actions

You can create custom sequences by writing JSON files inside `panasonic_ac/profiles/`. A sequence consists of an array of action steps.

### Action Types supported:
1. `{"type": "power", "value": "ON"}` (ON or OFF)
2. `{"type": "temperature", "value": 24}` (16 to 30)
3. `{"type": "convert", "value": "55"}` (HC, FC, 90%, 80%, 70%, 55%, 40%, OFF)
4. `{"type": "fan", "value": "HIGH"}` (AUTO, LOW, MEDIUM, HIGH)
5. `{"type": "mode", "value": "COOL"}` (COOL, AUTO, DRY, FAN)
6. `{"type": "delay", "value": 1800}` (Wait duration in seconds)
7. `{"type": "notification", "value": "Message to show in tray"}`
8. `{"type": "condition", "variable": "room_temperature", "operator": ">", "value": 28.0, "actions": [...]}` (Evaluates room temperature before executing nested actions)
