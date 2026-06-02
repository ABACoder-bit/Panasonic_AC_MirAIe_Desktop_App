import time
import threading
from logging_manager import get_logger

logger = get_logger("automation_engine")

class AutomationEngine:
    def __init__(self, ac_controller):
        self.ac = ac_controller
        self.active_runs = {}  # Map of run_id -> (thread, stop_event)
        self.lock = threading.Lock()
        self.notification_callback = None
        self.status_callback = None

    def register_notification_callback(self, cb):
        self.notification_callback = cb

    def register_status_callback(self, cb):
        """Callback to notify UI about automation step changes."""
        self.status_callback = cb

    def run_sequence(self, name, actions):
        """Starts executing a list of actions in a background thread."""
        run_id = f"{name}_{int(time.time())}"
        stop_event = threading.Event()
        
        thread = threading.Thread(
            target=self._execute_thread,
            args=(run_id, name, actions, stop_event),
            daemon=True,
            name=f"Automation-{name}"
        )
        
        with self.lock:
            self.active_runs[run_id] = (thread, stop_event)
            
        thread.start()
        logger.info("Started automation sequence: %s (Run ID: %s)", name, run_id)
        return run_id

    def stop_sequence(self, run_id):
        """Cancels a running automation sequence."""
        with self.lock:
            if run_id in self.active_runs:
                thread, stop_event = self.active_runs[run_id]
                stop_event.set()
                logger.info("Requested stop for sequence Run ID: %s", run_id)
                return True
        return False

    def stop_all(self):
        """Cancels all active automation sequences."""
        with self.lock:
            for run_id, (thread, stop_event) in list(self.active_runs.items()):
                stop_event.set()
            logger.info("Requested stop for all running sequences.")

    def get_active_sequences(self):
        with self.lock:
            # Clean up dead threads first
            for run_id in list(self.active_runs.keys()):
                thread, _ = self.active_runs[run_id]
                if not thread.is_alive():
                    self.active_runs.pop(run_id)
            return list(self.active_runs.keys())

    def _execute_thread(self, run_id, name, actions, stop_event):
        try:
            self._notify_status(run_id, name, "Running", "Starting sequence")
            self._execute_actions(run_id, name, actions, stop_event)
            if stop_event.is_set():
                logger.info("Sequence %s (ID: %s) was cancelled.", name, run_id)
                self._notify_status(run_id, name, "Cancelled", "Sequence stopped by user")
            else:
                logger.info("Sequence %s (ID: %s) completed successfully.", name, run_id)
                self._notify_status(run_id, name, "Completed", "All actions finished")
                
                # Show final notification
                self._trigger_notification(f"Automation Completed", f"Sequence '{name}' finished executing.")
        except Exception as e:
            logger.error("Error executing sequence %s: %s", name, e)
            self._notify_status(run_id, name, "Failed", f"Error: {e}")
        finally:
            with self.lock:
                self.active_runs.pop(run_id, None)

    def _execute_actions(self, run_id, name, actions, stop_event):
        for idx, action in enumerate(actions):
            if stop_event.is_set():
                break

            action_type = action.get("type", "").lower()
            val = action.get("value")
            
            logger.info("Automation [%s] step %d: %s -> %s", name, idx + 1, action_type, val)
            self._notify_status(run_id, name, "Running", f"Step {idx + 1}/{len(actions)}: {action_type}")

            if action_type == "power":
                if str(val).upper() == "ON":
                    self.ac.turn_on()
                else:
                    self.ac.turn_off()
            elif action_type == "temperature":
                self.ac.set_temperature(float(val))
            elif action_type == "fan":
                self.ac.set_fan_speed(str(val))
            elif action_type == "mode":
                self.ac.set_mode(str(val))
            elif action_type == "convert":
                self.ac.set_convert(str(val))
            elif action_type == "vertical_swing":
                self.ac.set_vertical_swing(str(val))
            elif action_type == "horizontal_swing":
                self.ac.set_horizontal_swing(str(val))
            elif action_type == "delay":
                # Sleep in small slices so that we can cancel quickly
                delay_sec = float(val)
                slices = int(delay_sec * 10)  # 100ms slices
                logger.info("Automation delay active: sleeping for %s seconds...", delay_sec)
                for _ in range(slices):
                    if stop_event.is_set():
                        break
                    time.sleep(0.1)
                # Handle remainder
                remainder = delay_sec - (slices * 0.1)
                if remainder > 0 and not stop_event.is_set():
                    time.sleep(remainder)
            elif action_type == "notification":
                self._trigger_notification(f"Automation Update", str(val))
            elif action_type == "condition":
                # Nested actions if condition evaluates to True
                var = action.get("variable", "")
                op = action.get("operator", "==")
                cond_val = action.get("value")
                sub_actions = action.get("actions", [])
                
                if self._eval_condition(var, op, cond_val):
                    logger.info("Condition passed (%s %s %s). Executing nested actions.", var, op, cond_val)
                    self._execute_actions(run_id, name, sub_actions, stop_event)
                else:
                    logger.info("Condition failed (%s %s %s). Skipping nested actions.", var, op, cond_val)
            
            # Wait a brief moment between queueing commands in automation
            if action_type != "delay" and not stop_event.is_set():
                time.sleep(1.0)

    def _eval_condition(self, variable, operator, value) -> bool:
        ac_val = None
        if variable == "room_temperature":
            ac_val = self.ac.get_room_temperature()
        elif variable == "target_temperature":
            ac_val = self.ac.get_target_temperature()
        elif variable == "power":
            ac_val = self.ac.get_status().get("power", "OFF")
        elif variable == "online":
            ac_val = "ON" if self.ac.is_online() else "OFF"
        
        if ac_val is None:
            return False

        try:
            if operator == "==":
                return str(ac_val).upper() == str(value).upper()
            elif operator == "!=":
                return str(ac_val).upper() != str(value).upper()
            elif operator == ">":
                return float(ac_val) > float(value)
            elif operator == "<":
                return float(ac_val) < float(value)
            elif operator == ">=":
                return float(ac_val) >= float(value)
            elif operator == "<=":
                return float(ac_val) <= float(value)
        except Exception as e:
            logger.error("Condition evaluation error: %s (comparing %s %s %s)", e, ac_val, operator, value)
        return False

    def _trigger_notification(self, title, message):
        logger.info("Automation Notification: %s - %s", title, message)
        if self.notification_callback:
            self.notification_callback(title, message)

    def _notify_status(self, run_id, name, status, step_info):
        if self.status_callback:
            try:
                self.status_callback(run_id, name, status, step_info)
            except Exception as e:
                logger.error("Error executing status callback: %s", e)
