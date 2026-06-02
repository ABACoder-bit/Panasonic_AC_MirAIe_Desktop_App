import asyncio
import threading
import time
from miraie_ac import MirAIeHub
from miraie_ac.enums import PowerMode, HVACMode, FanMode, ConvertiMode, SwingMode
from logging_manager import get_logger
from mqtt_manager import CustomBroker

logger = get_logger("ac_controller")

class CommandQueue:
    """
    Thread-safe command queue with duplicate suppression.
    If a command of the same action type is already pending in the queue,
    it updates the target value in-place, preventing command flooding.
    """
    def __init__(self):
        self.commands = []
        self.condition = asyncio.Condition()

    async def put(self, cmd):
        async with self.condition:
            # Check for existing pending command of same action
            existing = None
            for c in self.commands:
                if c["action"] == cmd["action"]:
                    existing = c
                    break
            
            if existing:
                logger.info("Duplicate suppression: updated pending %s from %s to %s", 
                            cmd["action"], existing["value"], cmd["value"])
                existing["value"] = cmd["value"]
            else:
                self.commands.append(cmd)
                self.condition.notify_all()

    async def get(self):
        async with self.condition:
            while not self.commands:
                await self.condition.wait()
            return self.commands.pop(0)


class ACController:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.loop = None
        self.thread = None
        self.hub = None
        self.broker = None
        self.device = None
        self.last_comm_time = None
        self.last_command_sent = "None"
        
        # List of callbacks to run when status changes
        self.callbacks = []
        self.connected_event = threading.Event()
        
        # Start background event loop thread
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True, name="PanasonicAC-AsyncIO")
        self.thread.start()

    def _run_event_loop(self):
        """Runs the asyncio loop on a background thread."""
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.queue = CommandQueue()
        self.loop.create_task(self._command_worker())
        
        self.loop.run_forever()

    def register_callback(self, callback):
        """Register a callback to be notified of device state updates."""
        if callback not in self.callbacks:
            self.callbacks.append(callback)

    def remove_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def _notify_status_changed(self):
        """Triggers all registered status callbacks."""
        for cb in self.callbacks:
            try:
                cb()
            except Exception as e:
                logger.error("Error executing status callback: %s", e)

    def _mqtt_state_changed(self, connected):
        """Callback from CustomBroker on connection status changes."""
        logger.info("MQTT connection state changed: Connected = %s", connected)
        self.last_comm_time = time.time()
        self._notify_status_changed()

    def _device_status_changed(self):
        """Callback from miraie_ac Device when device status is updated."""
        logger.debug("Device status updated from MQTT broker.")
        self.last_comm_time = time.time()
        self._notify_status_changed()

    def connect(self, callback=None):
        """Thread-safe trigger to start the connection asynchronously."""
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self.loop)
        if callback:
            def done_cb(fut):
                try:
                    res = fut.result()
                    callback(res, None)
                except Exception as e:
                    callback(False, e)
            future.add_done_callback(done_cb)
        return future

    async def _connect_async(self):
        """Connects to the Panasonic cloud and initializes MQTT."""
        username = self.config_manager.get("username")
        password = self.config_manager.get_decrypted_password()
        
        if not username or not password:
            raise Exception("Username or password not configured.")

        # Custom Broker subclass to monitor connection status
        self.broker = CustomBroker(on_state_change=self._mqtt_state_changed)
        self.hub = MirAIeHub()
        
        logger.info("Authenticating with MirAIe cloud for user: %s", username)
        await self.hub.init(username, password, self.broker)
        
        if not self.hub.home or not self.hub.home.devices:
            raise Exception("Authentication succeeded but no AC devices were found in the account.")
            
        # Device Selection
        devices = self.hub.home.devices
        selected_id = self.config_manager.get("device_id")
        if selected_id:
            self.device = next((d for d in devices if d.id == selected_id), None)
            if not self.device:
                logger.warning("Configured device_id '%s' not found. Defaulting to first device.", selected_id)
                self.device = devices[0]
        else:
            self.device = devices[0]
            self.config_manager.set("device_id", self.device.id)
            
        logger.info("Selected device friendly name: %s (ID: %s)", self.device.friendly_name, self.device.id)
        
        # Register device status change callback
        self.device.register_callback(self._device_status_changed)
        
        self.last_comm_time = time.time()
        self.connected_event.set()
        
        # Inform listeners we are ready
        self._notify_status_changed()
        return True

    def is_connected(self):
        """Checks if the controller has initialized and MQTT is connected."""
        return self.device is not None and self.broker is not None and self.broker.is_connected

    def is_online(self):
        """Checks if the AC is online according to MQTT status."""
        if not self.is_connected() or not hasattr(self.device, "status") or not self.device.status:
            return False
        return self.device.status.is_online

    def get_room_temperature(self):
        if not self.device or not hasattr(self.device, "status") or not self.device.status:
            return 0.0
        return self.device.status.room_temperature

    def get_target_temperature(self):
        if not self.device or not hasattr(self.device, "status") or not self.device.status:
            return 25.0
        return self.device.status.temperature

    def _get_convert_string(self, mode_enum):
        convert_map = {
            ConvertiMode.HC: "HC",
            ConvertiMode.FC: "FC",
            ConvertiMode.C90: "90%",
            ConvertiMode.C80: "80%",
            ConvertiMode.C70: "70%",
            ConvertiMode.C55: "55%",
            ConvertiMode.C40: "40%",
            ConvertiMode.OFF: "OFF",
            ConvertiMode.NS: "Normal"
        }
        return convert_map.get(mode_enum, "OFF")

    def _get_swing_string(self, swing_enum):
        swing_map = {
            SwingMode.AUTO: "AUTO",
            SwingMode.ONE: "1",
            SwingMode.TWO: "2",
            SwingMode.THREE: "3",
            SwingMode.FOUR: "4",
            SwingMode.FIVE: "5"
        }
        return swing_map.get(swing_enum, "AUTO")

    def get_status(self):
        """Returns the current status dictionary of the AC."""
        if not self.device or not hasattr(self.device, "status") or not self.device.status:
            return {
                "online": False,
                "power": "OFF",
                "target_temperature": 25.0,
                "room_temperature": 0.0,
                "mode": "COOL",
                "fan_speed": "AUTO",
                "convert": "OFF",
                "v_swing": "AUTO",
                "h_swing": "AUTO",
                "last_command": self.last_command_sent,
                "last_comm_time": self.last_comm_time
            }
            
        status = self.device.status
        return {
            "online": self.is_online(),
            "power": "ON" if status.power_mode == PowerMode.ON else "OFF",
            "target_temperature": status.temperature,
            "room_temperature": status.room_temperature,
            "mode": status.hvac_mode.name if hasattr(status.hvac_mode, "name") else str(status.hvac_mode),
            "fan_speed": status.fan_mode.name if hasattr(status.fan_mode, "name") else str(status.fan_mode),
            "convert": self._get_convert_string(status.converti_mode),
            "v_swing": self._get_swing_string(status.v_swing_mode),
            "h_swing": self._get_swing_string(status.h_swing_mode),
            "last_command": self.last_command_sent,
            "last_comm_time": self.last_comm_time
        }

    # API Methods
    def turn_on(self):
        self._queue_command("turn_on", None)

    def turn_off(self):
        self._queue_command("turn_off", None)

    def set_temperature(self, temp):
        self._queue_command("set_temperature", float(temp))

    def set_fan_speed(self, speed):
        self._queue_command("set_fan_speed", speed.upper())

    def set_convert(self, level):
        self._queue_command("set_convert", level.upper())

    def set_mode(self, mode):
        self._queue_command("set_mode", mode.upper())

    def set_vertical_swing(self, mode):
        self._queue_command("set_vertical_swing", str(mode).upper())

    def set_horizontal_swing(self, mode):
        self._queue_command("set_horizontal_swing", str(mode).upper())

    def _queue_command(self, action, value):
        """Puts a command into the queue safely from any thread."""
        if not self.loop:
            logger.error("Asyncio loop not running. Command '%s' discarded.", action)
            return
        asyncio.run_coroutine_threadsafe(self.queue.put({"action": action, "value": value}), self.loop)

    # Worker Task
    async def _command_worker(self):
        """Processes queued commands with rate-limiting, retries, and duplicate suppression."""
        last_run_time = 0.0
        while True:
            cmd = await self.queue.get()
            action = cmd["action"]
            value = cmd["value"]
            
            # Rate limiting: minimum 1.5 seconds between command executions to prevent collision
            now = time.time()
            elapsed = now - last_run_time
            if elapsed < 1.5:
                await asyncio.sleep(1.5 - elapsed)
            
            logger.info("Executing queued command: %s(%s)", action, value if value is not None else "")
            self.last_command_sent = f"{action.replace('_', ' ').title()}" + (f": {value}" if value is not None else "")
            
            # Run command with up to 3 retries
            success = False
            for attempt in range(1, 4):
                try:
                    if not self.device:
                        raise Exception("Device not connected yet.")

                    if action == "turn_on":
                        await self.device.turn_on()
                    elif action == "turn_off":
                        await self.device.turn_off()
                    elif action == "set_temperature":
                        await self.device.set_temperature(value)
                    elif action == "set_fan_speed":
                        fan_map = {
                            "AUTO": FanMode.AUTO,
                            "LOW": FanMode.LOW,
                            "MEDIUM": FanMode.MEDIUM,
                            "HIGH": FanMode.HIGH,
                            "QUIET": FanMode.QUIET
                        }
                        await self.device.set_fan_mode(fan_map.get(value, FanMode.AUTO))
                    elif action == "set_convert":
                        convert_map = {
                            "HC": ConvertiMode.HC,
                            "FC": ConvertiMode.FC,
                            "90%": ConvertiMode.C90,
                            "80%": ConvertiMode.C80,
                            "70%": ConvertiMode.C70,
                            "55%": ConvertiMode.C55,
                            "40%": ConvertiMode.C40,
                            "OFF": ConvertiMode.OFF
                        }
                        await self.device.set_converti_mode(convert_map.get(value, ConvertiMode.OFF))
                    elif action == "set_mode":
                        mode_map = {
                            "COOL": HVACMode.COOL,
                            "AUTO": HVACMode.AUTO,
                            "DRY": HVACMode.DRY,
                            "FAN": HVACMode.FAN
                        }
                        await self.device.set_hvac_mode(mode_map.get(value, HVACMode.AUTO))
                    elif action == "set_vertical_swing":
                        swing_map = {
                            "AUTO": SwingMode.AUTO,
                            "1": SwingMode.ONE,
                            "2": SwingMode.TWO,
                            "3": SwingMode.THREE,
                            "4": SwingMode.FOUR,
                            "5": SwingMode.FIVE
                        }
                        await self.device.set_v_swing_mode(swing_map.get(value, SwingMode.AUTO))
                    elif action == "set_horizontal_swing":
                        swing_map = {
                            "AUTO": SwingMode.AUTO,
                            "1": SwingMode.ONE,
                            "2": SwingMode.TWO,
                            "3": SwingMode.THREE,
                            "4": SwingMode.FOUR,
                            "5": SwingMode.FIVE
                        }
                        await self.device.set_h_swing_mode(swing_map.get(value, SwingMode.AUTO))
                    
                    success = True
                    break
                except Exception as err:
                    logger.error("Command Execution Error (Attempt %d/3) for '%s': %s", attempt, action, err)
                    if attempt < 3:
                        await asyncio.sleep(attempt * 2) # Exponential backoff: 2s, 4s
            
            if success:
                logger.info("Command '%s' executed successfully.", action)
                self.last_comm_time = time.time()
                # Direct trigger to update status
                self._notify_status_changed()
            else:
                logger.error("Command '%s' failed permanently after 3 attempts.", action)
                
            last_run_time = time.time()
