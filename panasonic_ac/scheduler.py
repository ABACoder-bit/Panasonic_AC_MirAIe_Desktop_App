import time
import datetime
import threading
from logging_manager import get_logger

logger = get_logger("scheduler")

class Scheduler:
    def __init__(self, config_manager, profile_manager, automation_engine):
        self.config_manager = config_manager
        self.profile_manager = profile_manager
        self.automation_engine = automation_engine
        self.schedules = []
        self.last_runs = {}  # Map of schedule_id -> "YYYY-MM-DD HH:MM"
        
        self.running = False
        self.thread = None
        self.notification_callback = None
        
        self.load_schedules()

    def register_notification_callback(self, cb):
        self.notification_callback = cb

    def load_schedules(self):
        """Loads schedules from settings config."""
        self.schedules = self.config_manager.get("schedules", [])
        logger.info("Loaded %d schedules from settings.", len(self.schedules))

    def save_schedules(self):
        """Saves current schedules list back to settings."""
        self.config_manager.set("schedules", self.schedules)
        logger.info("Saved %d schedules to settings.", len(self.schedules))

    def start(self):
        """Starts the scheduler evaluation thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="PanasonicAC-Scheduler")
        self.thread.start()
        logger.info("Scheduler background loop started.")

    def stop(self):
        """Stops the scheduler evaluation thread."""
        self.running = False
        logger.info("Scheduler background loop stopping.")

    def add_schedule(self, name, sched_type, sched_time, profile_slug, enabled=True):
        """Adds a new schedule and saves it."""
        schedule_id = f"sched_{int(time.time())}"
        schedule = {
            "id": schedule_id,
            "name": name,
            "type": sched_type,  # "daily", "weekdays", "weekends", "once"
            "time": sched_time,  # "HH:MM" or "YYYY-MM-DD HH:MM"
            "profile": profile_slug,
            "enabled": enabled
        }
        self.schedules.append(schedule)
        self.save_schedules()
        return schedule_id

    def delete_schedule(self, schedule_id):
        """Deletes a schedule by its ID."""
        original_len = len(self.schedules)
        self.schedules = [s for s in self.schedules if s.get("id") != schedule_id]
        if len(self.schedules) < original_len:
            self.save_schedules()
            self.last_runs.pop(schedule_id, None)
            return True
        return False

    def toggle_schedule(self, schedule_id, enabled):
        """Enables or disables a schedule."""
        for s in self.schedules:
            if s.get("id") == schedule_id:
                s["enabled"] = enabled
                self.save_schedules()
                return True
        return False

    def _scheduler_loop(self):
        """Main loop checking for schedule triggers every 10 seconds."""
        while self.running:
            try:
                now = datetime.datetime.now()
                current_time_str = now.strftime("%H:%M")
                current_date_str = now.strftime("%Y-%m-%d")
                day_of_week = now.weekday()  # Monday is 0, Sunday is 6
                
                for s in self.schedules:
                    if not s.get("enabled", True):
                        continue
                        
                    schedule_id = s.get("id")
                    
                    # Prevent multiple triggers within the same minute
                    minute_key = now.strftime("%Y-%m-%d %H:%M")
                    if self.last_runs.get(schedule_id) == minute_key:
                        continue
                        
                    trigger = False
                    sched_type = s.get("type")
                    sched_time = s.get("time")
                    
                    if sched_type == "daily":
                        if current_time_str == sched_time:
                            trigger = True
                    elif sched_type == "weekdays":
                        # Mon-Fri (0 to 4)
                        if day_of_week < 5 and current_time_str == sched_time:
                            trigger = True
                    elif sched_type == "weekends":
                        # Sat-Sun (5 or 6)
                        if day_of_week >= 5 and current_time_str == sched_time:
                            trigger = True
                    elif sched_type == "once":
                        # Format is expected to be "YYYY-MM-DD HH:MM"
                        try:
                            target_dt = datetime.datetime.strptime(sched_time, "%Y-%m-%d %H:%M")
                            # If we are in the matching minute
                            if now.year == target_dt.year and now.month == target_dt.month and \
                               now.day == target_dt.day and current_time_str == target_dt.strftime("%H:%M"):
                                trigger = True
                                # Disable the schedule so it doesn't run again
                                s["enabled"] = False
                                self.save_schedules()
                        except ValueError:
                            logger.error("Schedule '%s' has invalid once-time format: %s. Expected 'YYYY-MM-DD HH:MM'", 
                                         s.get("name"), sched_time)
                                         
                    if trigger:
                        self.last_runs[schedule_id] = minute_key
                        profile_slug = s.get("profile")
                        
                        logger.info("Schedule Triggered: '%s' -> Running Profile: %s", s.get("name"), profile_slug)
                        
                        profile_data = self.profile_manager.get_profile(profile_slug)
                        if profile_data:
                            # Run actions in the automation engine
                            self.automation_engine.run_sequence(
                                f"Schedule: {s.get('name')}",
                                profile_data.get("actions", [])
                            )
                            if self.notification_callback:
                                self.notification_callback(
                                    "Schedule Executed",
                                    f"Schedule '{s.get('name')}' ran profile '{profile_data.get('name')}'"
                                )
                        else:
                            logger.error("Triggered profile '%s' not found.", profile_slug)
                            
            except Exception as e:
                logger.error("Error in scheduler tick: %s", e)
                
            # Sleep 10 seconds before next check
            time.sleep(10)
