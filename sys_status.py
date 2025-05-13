# sys_status.py
# Handles the main dashboard screen: multi-room simulation, activity log,

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import threading
import time
import random
import collections # For deque data structure
import utils # Shared utility functions
import logging
from datetime import datetime, timedelta # For timestamps and scheduling

# Matplotlib imports for embedded graphs
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt # Usually imported for stand-alone plotting, but good practice

# Obtain a logger instance for this module
logger = logging.getLogger(__name__)

# --- Simulation Constants ---
INITIAL_TEMP_CELSIUS = 20.0
INITIAL_HUMIDITY_PERCENT = 50.0
AMBIENT_TEMP_TARGET = 22.0  # Temperature the environment naturally tends towards
AMBIENT_HUMIDITY_TARGET = 45.0 # Humidity the environment naturally tends towards

# Climate control rates (per simulation tick)
HEAT_RATE = 0.2  # Degrees Celsius increase per tick when heating
COOL_RATE_AC = 0.3 # Degrees Celsius decrease per tick during AC Boost
AC_HUMIDITY_REDUCTION_RATE = 0.2 # Percentage RH decrease per tick during AC Boost

# Ambient drift rates (per simulation tick)
AMBIENT_DRIFT_RATE_TEMP = 0.05 # Rate of temperature drift for the currently viewed room
BACKGROUND_AMBIENT_DRIFT_RATE_TEMP = 0.02 # Simpler/slower drift rate for non-viewed rooms
AMBIENT_DRIFT_RATE_HUMIDITY = 0.1 # Rate of humidity drift for the currently viewed room
BACKGROUND_AMBIENT_DRIFT_RATE_HUMIDITY = 0.04 # Simpler/slower drift rate for non-viewed rooms

# Timing and Display Constants
SIMULATION_TICK_INTERVAL_SECONDS = 1 # Frequency of simulation updates
GRAPH_DATA_POINTS = 60 # Number of historical points to display on graphs
DEFAULT_ROOMS_FALLBACK = ["Living Room", "Bedroom", "Kitchen"] # Used if no rooms found in config
MAX_ROOM_NAME_LENGTH = 20 # Validation limit for new room names
MAX_TIMED_HEAT_MINUTES = 60 # Maximum duration for timed heating requests


class SystemStatusScreen:
    """
    Manages the main dashboard UI and the multi-room climate simulation.

    Handles displaying room data, controlling heating/cooling, managing rooms,
    scheduling events, logging activity, and persisting state.
    """
    def __init__(self, root, on_logout_callback):
        """
        Initialises the SystemStatusScreen.

        Args:
            root: The main Tkinter window or parent frame.
            on_logout_callback: Function to call when the user logs out.
        """
        self.root = root
        self.on_logout_callback = on_logout_callback
        logger.info("SystemStatusScreen initialising.")

        # Main frame for this screen
        self.dashboard_frame = ttk.Frame(self.root, padding="5")
        self.dashboard_frame.pack(expand=True, fill=tk.BOTH)

        # Simulation control flag and thread reference
        self._simulation_running = False
        self.simulation_thread = None
        
        # Load configuration, including password hash, room list, and persisted states
        self.config_data = utils.load_config() 
        
        # Initialise room list from config or use fallback
        self.rooms = self.config_data.get(utils.DEFAULT_ROOM_KEY, list(DEFAULT_ROOMS_FALLBACK))
        if not self.rooms: 
            self.rooms = list(DEFAULT_ROOMS_FALLBACK)
            self.config_data[utils.DEFAULT_ROOM_KEY] = self.rooms
            # Config will be saved later if needed (e.g., on adding room or exit)

        # Track the currently selected room in the UI
        self.current_room = self.rooms[0] if self.rooms else None
        
        # Load full room states from config, merging with defaults for robustness
        persisted_room_states = self.config_data.get(utils.ROOM_STATES_KEY, {})
        self.room_states = {}
        for room_name in self.rooms:
            default_state = self._get_default_room_state()
            loaded_state = persisted_room_states.get(room_name, default_state) 
            
            # Merge loaded state with defaults to ensure all keys exist
            final_state = {**default_state, **loaded_state} 

            # Ensure graph data structures are deques after loading from JSON (which saves them as lists)
            for dq_key in ['time_data', 'temp_data', 'humidity_data']:
                if dq_key in final_state and isinstance(final_state[dq_key], list):
                    final_state[dq_key] = collections.deque(final_state[dq_key], maxlen=GRAPH_DATA_POINTS)
                elif dq_key not in final_state or not isinstance(final_state[dq_key], collections.deque): 
                     final_state[dq_key] = default_state[dq_key]
            
            # Ensure scheduled_events is always a list
            if not isinstance(final_state.get('scheduled_events'), list):
                final_state['scheduled_events'] = []

            self.room_states[room_name] = final_state
        
        # In-memory store for recent activity log messages (not persisted)
        self.activity_log_messages = collections.deque(maxlen=100) 

        # Construct the UI elements
        self._build_ui() 

        self.add_activity_log("System dashboard initialised. Loaded room states if available.")
        # Set initial UI state based on the loaded/default current room
        if self.current_room:
            self.update_all_ui_for_current_room()
        else:
            self.add_activity_log("No rooms configured. Please add a room.")
            logger.warning("No rooms available to display after initialisation.")


    def _get_default_room_state(self):
        """
        Returns a dictionary holding the default state variables for a room.
        Used for newly added rooms or when loading fails for a room.
        """
        return {
            'temp': INITIAL_TEMP_CELSIUS,
            'humidity': INITIAL_HUMIDITY_PERCENT,
            'heat_on': False,                  # Manual heating state
            'ac_boost_on': False,              # AC boost state
            'ac_boost_timer': 0,               # Remaining seconds for AC boost
            'timed_heat_active': False,        # Timed heating state
            'timed_heat_remaining_seconds': 0, # Remaining seconds for timed heat
            'scheduled_events': [],            # Stores {'start_time_iso', 'action', 'params', 'triggered', 'description'}
            # Deques for graph data history
            'time_data': collections.deque(maxlen=GRAPH_DATA_POINTS),
            'temp_data': collections.deque(maxlen=GRAPH_DATA_POINTS),
            'humidity_data': collections.deque(maxlen=GRAPH_DATA_POINTS),
            'simulation_time_elapsed': 0       # Tracks time for the current room's graph x-axis
        }

    def _build_ui(self):
        """Constructs and arranges all Tkinter widgets for the dashboard."""
        
        # --- Main Layout Panes (Horizontal split: Left=Controls/Graphs, Right=Activity Log) ---
        self.main_horizontal_pane = ttk.PanedWindow(self.dashboard_frame, orient=tk.HORIZONTAL)
        self.main_horizontal_pane.pack(expand=True, fill=tk.BOTH, pady=5)

        # --- Left Pane Container (Vertical split: Top=Header/Controls, Bottom=Graphs) ---
        self.left_vertical_pane_frame = ttk.Frame(self.main_horizontal_pane)
        self.main_horizontal_pane.add(self.left_vertical_pane_frame, weight=3) # Give more space to left side

        self.left_vertical_pane = ttk.PanedWindow(self.left_vertical_pane_frame, orient=tk.VERTICAL)
        self.left_vertical_pane.pack(expand=True, fill=tk.BOTH)

        # Top-left pane for header, data display, and controls
        self.top_left_pane = ttk.Frame(self.left_vertical_pane, padding="5")
        self.left_vertical_pane.add(self.top_left_pane, weight=1) # Give controls/data less vertical space initially

        # Bottom-left pane for graphs
        self.graph_pane_container = ttk.LabelFrame(self.left_vertical_pane, text="Live Data Trends", padding="5")
        self.left_vertical_pane.add(self.graph_pane_container, weight=1) # Give graphs equal vertical space initially

        # --- Right Pane (Activity Log) ---
        self.activity_log_frame = ttk.LabelFrame(self.main_horizontal_pane, text="Activity Log", padding="5")
        self.main_horizontal_pane.add(self.activity_log_frame, weight=1) # Give log less horizontal space initially

        # --- Header Elements (within top_left_pane) ---
        header_frame = ttk.Frame(self.top_left_pane)
        header_frame.pack(fill=tk.X, pady=(0, 10)) # Fill horizontally, add padding below

        # "Connected" status indicator (left side of header)
        self.connected_status_frame = ttk.Frame(header_frame)
        self.connected_status_frame.pack(side=tk.LEFT, padx=5)
        self.connected_dot_label = ttk.Label(self.connected_status_frame, text="●", font=("Arial", 12), foreground="green")
        self.connected_dot_label.pack(side=tk.LEFT)
        self.connected_text_label = ttk.Label(self.connected_status_frame, text="Connected", font=("Arial", 10))
        self.connected_text_label.pack(side=tk.LEFT, padx=(0, 5))

        # Logout button (right side of header)
        self.logout_button = ttk.Button(header_frame, text="Logout", command=self.logout, width=8)
        self.logout_button.pack(side=tk.RIGHT, padx=5)
        
        # Room selection and management (centre of header, expands)
        room_management_frame = ttk.Frame(header_frame)
        room_management_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=10)
        ttk.Label(room_management_frame, text="Room:").pack(side=tk.LEFT, padx=(0,2))
        self.room_var = tk.StringVar(value=self.current_room if self.current_room else "")
        self.room_combobox = ttk.Combobox(room_management_frame, textvariable=self.room_var, 
                                          values=self.get_room_display_names(), state="readonly", width=22)
        self.room_combobox.pack(side=tk.LEFT, padx=(0,5))
        self.room_combobox.bind("<<ComboboxSelected>>", self.on_room_selected) # Event binding
        self.add_room_button = ttk.Button(room_management_frame, text="+ Add Room", command=self.add_new_room_prompt, width=10)
        self.add_room_button.pack(side=tk.LEFT, padx=(5,0))
        
        # Dashboard Title (below header)
        self.title_label = ttk.Label(self.top_left_pane, text="Climate Control Dashboard", font=("Arial", 16, "bold"))
        self.title_label.pack(pady=(5, 10))

        # Data Display Area (using grid layout)
        data_frame = ttk.Frame(self.top_left_pane)
        data_frame.pack(pady=5, fill=tk.X, expand=True)
        self.temp_label_title = ttk.Label(data_frame, text="Temperature:", font=("Arial", 11))
        self.temp_label_title.grid(row=0, column=0, sticky="w", padx=5)
        self.temp_value_label = ttk.Label(data_frame, text="N/A", font=("Arial", 11, "bold"), width=10)
        self.temp_value_label.grid(row=0, column=1, sticky="w", padx=5)
        self.humidity_label_title = ttk.Label(data_frame, text="Humidity:", font=("Arial", 11))
        self.humidity_label_title.grid(row=1, column=0, sticky="w", padx=5)
        self.humidity_value_label = ttk.Label(data_frame, text="N/A", font=("Arial", 11, "bold"), width=10)
        self.humidity_value_label.grid(row=1, column=1, sticky="w", padx=5)
        # Status indicator for the current room and simulation state
        self.system_status_indicator = ttk.Label(data_frame, text="System Idle", font=("Arial", 11, "italic"), foreground="grey")
        self.system_status_indicator.grid(row=0, column=2, rowspan=2, sticky="ew", padx=(15,5))
        data_frame.columnconfigure(2, weight=1) # Allow status label to expand horizontally

        # Control Buttons Area (using grid layout)
        controls_frame = ttk.LabelFrame(self.top_left_pane, text="Controls", padding="10")
        controls_frame.pack(pady=10, padx=5, fill=tk.X)
        self.heat_on_button = ttk.Button(controls_frame, text="Heat ON", command=self.toggle_heat_on, width=12)
        self.heat_on_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.heat_off_button = ttk.Button(controls_frame, text="Heat OFF", command=self.toggle_heat_off, width=12, state=tk.DISABLED)
        self.heat_off_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.ac_boost_button = ttk.Button(controls_frame, text="Boost AC", command=self.activate_ac_boost, width=12)
        self.ac_boost_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        self.timed_heat_button = ttk.Button(controls_frame, text="Timed Heat", command=self.toggle_timed_heat, width=12)
        self.timed_heat_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew") # Span 2 columns
        self.schedule_event_button = ttk.Button(controls_frame, text="Schedule", command=self.schedule_event_prompt, width=12)
        self.schedule_event_button.grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        controls_frame.columnconfigure((0,1,2), weight=1) # Make columns expand equally

        # --- Graph Setup (using Matplotlib Figure and TkAgg canvas) ---
        self.fig = Figure(figsize=(5, 3.5), dpi=90) # Figure size and resolution
        self.fig.subplots_adjust(hspace=0.5, bottom=0.15) # Adjust spacing between plots and bottom margin
        # Temperature subplot
        self.ax_temp = self.fig.add_subplot(2, 1, 1) # 2 rows, 1 column, plot 1
        self.line_temp, = self.ax_temp.plot([], [], 'r-', label="Temp (°C)") # Store line reference
        self.ax_temp.set_ylabel("Temp (°C)", fontsize=9)
        self.ax_temp.tick_params(axis='y', labelsize=8); self.ax_temp.tick_params(axis='x', labelsize=8) # Set tick label sizes
        self.ax_temp.legend(loc='upper left', fontsize='x-small'); self.ax_temp.grid(True) # Add legend and grid
        # Humidity subplot
        self.ax_humidity = self.fig.add_subplot(2, 1, 2) # 2 rows, 1 column, plot 2
        self.line_humidity, = self.ax_humidity.plot([], [], 'b-', label="Humid (%RH)") # Store line reference
        self.ax_humidity.set_xlabel("Time (s)", fontsize=9); self.ax_humidity.set_ylabel("Humid (%RH)", fontsize=9)
        self.ax_humidity.tick_params(axis='y', labelsize=8); self.ax_humidity.tick_params(axis='x', labelsize=8)
        self.ax_humidity.legend(loc='upper left', fontsize='x-small'); self.ax_humidity.grid(True)
        # Embed Matplotlib figure in Tkinter window
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_pane_container)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True); self.canvas.draw()

        # --- Activity Log Setup (using ScrolledText) ---
        self.activity_text = scrolledtext.ScrolledText(self.activity_log_frame, wrap=tk.WORD, height=10, state=tk.DISABLED, font=("Arial", 9))
        self.activity_text.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)


    def get_room_display_names(self):
        """
        Generates display names for the room selection combobox.
        Appends suffixes like '(T)' for active timers or '(S)' for pending schedules.

        Returns:
            list: A list of strings representing room display names.
        """
        display_names = []
        for room_name in self.rooms:
            if room_name not in self.room_states: continue # Safety check
            state = self.room_states[room_name]
            suffix = ""
            # Check for active timers first
            if state.get('timed_heat_active', False) or state.get('ac_boost_on', False):
                suffix = " (T)" # Active Timer indicator
            # If no active timer, check for pending scheduled events
            elif state.get('scheduled_events') and any(not event.get('triggered', False) for event in state['scheduled_events']):
                suffix = " (S)" # Scheduled Event indicator
            display_names.append(f"{room_name}{suffix}")
        return display_names
    
    def update_room_combobox_display(self):
        """
        Refreshes the items displayed in the room selection combobox,
        including any status suffixes like (T) or (S).
        Attempts to maintain the selection of the currently viewed room.
        """
        if hasattr(self, 'room_combobox') and self.room_combobox.winfo_exists():
            current_selection_base = self.current_room # Base name (without suffix)
            
            new_display_values = self.get_room_display_names()
            self.room_combobox.config(values=new_display_values)

            # Re-select the current room, potentially with its new suffix
            found_current_in_new_display = False
            if current_selection_base:
                for display_name in new_display_values:
                    if display_name.startswith(current_selection_base):
                        self.room_var.set(display_name) # Set the Tkinter variable
                        found_current_in_new_display = True
                        break
            # If the current room wasn't found e.g., deleted?, select the first available room
            if not found_current_in_new_display and new_display_values: 
                self.room_var.set(new_display_values[0])
                self.current_room = new_display_values[0].split(" (")[0] # Update current_room to the new selection


    def add_activity_log(self, message: str):
        """
        Adds a timestamped message to the activity log display.
        Ensures thread safety by scheduling the widget update on the main thread.

        Args:
            message: The string message to log.
        """
        if not hasattr(self, 'activity_text') or not self.activity_text.winfo_exists(): return
        now = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{now}] {message}\n"
        self.activity_log_messages.append(full_message) # Store internally if needed
        # Schedule the Tkinter widget update to run in the main GUI thread
        self.root.after(0, self._update_activity_log_widget, full_message)
        logger.info(f"Activity Log: {message}") # Also log to file/console

    def _update_activity_log_widget(self, message_to_add):
        """Helper method to update the ScrolledText widget (called via root.after)."""
        if hasattr(self, 'activity_text') and self.activity_text.winfo_exists():
            try:
                self.activity_text.config(state=tk.NORMAL) # Enable writing
                self.activity_text.insert(tk.END, message_to_add)
                self.activity_text.see(tk.END) # Auto-scroll to the bottom
                self.activity_text.config(state=tk.DISABLED) # Disable writing
            except tk.TclError as e:
                logger.error(f"TclError updating activity log: {e}. Widget might be destroyed.")


    def _save_state_to_config(self):
        """
        Saves the current room list and the full state of all rooms
        (including timers, controls, scheduled events, and graph data history)
        to the configuration file (config.json).
        Converts non-JSON-serializable types (like deques) to lists.
        """
        # Update the config dictionary with the current room list
        self.config_data[utils.DEFAULT_ROOM_KEY] = self.rooms
        
        # Prepare room_states for JSON serialization
        serializable_room_states = {}
        for room_name, state in self.room_states.items():
            s_state = state.copy() # Shallow copy to avoid modifying original state dict
            # Convert deques to lists
            s_state['time_data'] = list(state.get('time_data', []))
            s_state['temp_data'] = list(state.get('temp_data', []))
            s_state['humidity_data'] = list(state.get('humidity_data', []))
            
            # Ensure scheduled events list is present and contains serializable data
            # (datetime objects were already converted to ISO strings when scheduled)
            s_state['scheduled_events'] = [event for event in state.get('scheduled_events', [])]

            serializable_room_states[room_name] = s_state
            
        # Update the config dictionary with the serializable states
        self.config_data[utils.ROOM_STATES_KEY] = serializable_room_states
        
        # Attempt to save the updated config dictionary to the file
        if utils.save_config(self.config_data):
            logger.info("Full room states saved to configuration.")
            # Optionally add to activity log, but can be noisy on frequent saves
            # self.add_activity_log("System configuration saved.") 
        else:
            logger.error("Failed to save full room states to configuration.")
            self.add_activity_log("Error: Failed to save system configuration.")


    def add_new_room_prompt(self):
        """
        Displays a dialog prompting the user to enter a name for a new room.
        Validates the name, adds the room to the internal state and config,
        updates the UI, and selects the newly added room.
        """
        if not self.root.winfo_exists(): return # Check if window still exists
        
        # Prompt for room name
        new_room_name = simpledialog.askstring("Add New Room", "Enter name for the new room:", parent=self.root)
        
        if new_room_name: # If user entered a name and didn't cancel
            new_room_name = new_room_name.strip() # Remove leading/trailing whitespace
            
            # Validation checks
            if not new_room_name: 
                messagebox.showwarning("Invalid Name", "Room name cannot be empty.", parent=self.root)
                return
            if len(new_room_name) > MAX_ROOM_NAME_LENGTH: 
                messagebox.showwarning("Invalid Name", f"Room name cannot exceed {MAX_ROOM_NAME_LENGTH} characters.", parent=self.root)
                return
            if new_room_name in self.rooms: 
                messagebox.showwarning("Duplicate Name", f"Room '{new_room_name}' already exists.", parent=self.root)
                return
            
            # Add room to internal state
            self.rooms.append(new_room_name)
            self.room_states[new_room_name] = self._get_default_room_state()
            
            # Save the updated room list and state to config file
            self._save_state_to_config() 
            
            # Update the combobox display and select the new room
            self.update_room_combobox_display()
            new_room_display_name = new_room_name # Find display name (usually same for new room)
            for dn in self.get_room_display_names():
                if dn.startswith(new_room_name):
                    new_room_display_name = dn
                    break
            self.room_var.set(new_room_display_name) # Set the combobox variable
            
            # Trigger UI update for the newly selected room
            self.on_room_selected() 
            
            self.add_activity_log(f"Room '{new_room_name}' added.")
            logger.info(f"Room '{new_room_name}' added by user.")
        else: 
            logger.info("Add new room cancelled by user.")


    def on_room_selected(self, event=None):
        """
        Callback function executed when a room is selected from the combobox.
        Updates the `current_room` state and refreshes the UI. Clears graph lines.
        """
        selected_display_name = self.room_var.get()
        # Extract the base room name (remove suffix like ' (T)' or ' (S)')
        base_room_name = selected_display_name.split(" (")[0]
        
        if not base_room_name: 
            logger.warning("Room selection resulted in empty base room name.")
            return
        
        # Only update if the base room name has actually changed
        if self.current_room is None or base_room_name != self.current_room:
            old_room_log_name = self.current_room if self.current_room else "None"
            logger.info(f"Current room view changed from '{old_room_log_name}' to '{base_room_name}'.")
            self.add_activity_log(f"Switched to view {base_room_name}.")
            
            # Update the currently viewed room
            self.current_room = base_room_name 
            
            # Clear graph lines before drawing new data
            if hasattr(self, 'line_temp'): self.line_temp.set_data([], [])
            if hasattr(self, 'line_humidity'): self.line_humidity.set_data([], [])
            
            # Refresh the entire UI for the new room
            self.update_all_ui_for_current_room()
            
        # If the same room is selected (e.g., after adding it), still refresh UI
        elif base_room_name == self.current_room and self.root.winfo_exists():
             self.update_all_ui_for_current_room()


    def update_all_ui_for_current_room(self):
        """
        Refreshes all relevant UI elements (labels, buttons, graph, combobox display)
        to reflect the state of the `self.current_room`.
        """
        if not self.root.winfo_exists() or not self.current_room: return # Exit if window closed or no room selected
        
        # Safety check: Ensure the current room exists in our state dictionary
        if self.current_room not in self.room_states:
            logger.error(f"Current room '{self.current_room}' not found in room_states. Resetting.")
            if self.rooms: 
                # Attempt to reset to the first room in the list
                self.current_room = self.rooms[0].split(" (")[0] 
                self.update_room_combobox_display() # This will set self.room_var
            else: 
                # No rooms left - critical state
                logger.critical("No rooms available. Cannot update UI.") 
                # Make UI reflect error state
                if self.temp_value_label.winfo_exists(): self.temp_value_label.config(text="ERR")
                if self.humidity_value_label.winfo_exists(): self.humidity_value_label.config(text="ERR")
                # Consider disabling all control buttons here
                return
        
        # Get the state dictionary for the currently selected room
        current_room_state = self.room_states[self.current_room]
        
        # Update temperature and humidity labels
        if self.temp_value_label.winfo_exists(): 
            self.temp_value_label.config(text=utils.format_temperature(current_room_state['temp']))
        if self.humidity_value_label.winfo_exists(): 
            self.humidity_value_label.config(text=utils.format_humidity(current_room_state['humidity']))
            
        # Refresh the room combobox display (to update suffixes like (T)/(S))
        self.update_room_combobox_display() 
        
        # Update button states (enabled/disabled, text) and the status indicator label
        self._update_button_states() 
        
        # Redraw the graph with data for the current room
        self._update_graph() 


    def start_simulation(self):
        """Starts the background simulation thread if not already running."""
        if not self._simulation_running:
            self._simulation_running = True
            # Create and start the simulation thread
            self.simulation_thread = threading.Thread(target=self._simulation_loop, daemon=True)
            self.simulation_thread.start()
            self.add_activity_log("Climate simulation started globally.")
            logger.info("Climate simulation thread started globally.")
            # Update status indicator immediately
            if hasattr(self, 'system_status_indicator') and self.system_status_indicator.winfo_exists():
                self.system_status_indicator.config(text="Sim: Running", foreground="green")


    def stop_simulation(self):
        """Stops the background simulation thread."""
        self._simulation_running = False # Signal the thread to stop
        if self.simulation_thread and self.simulation_thread.is_alive(): 
            logger.info("Attempting to stop simulation thread...")
            # The thread checks _simulation_running flag and exits
        else: 
            logger.info("Simulation already stopped or not started.")
        
        # Update status indicator immediately
        if hasattr(self, 'system_status_indicator') and self.system_status_indicator.winfo_exists():
            self.system_status_indicator.config(text="Sim: Stopped", foreground="orange")
        self.add_activity_log("Climate simulation stopped globally.")


    def _simulation_loop(self):
        """
        Main simulation loop running in a background thread.
        Processes timers and scheduled events for ALL rooms.
        Applies climate changes (heating, cooling, ambient drift) for ALL rooms.
        Updates graph data ONLY for the currently viewed room.
        Schedules UI updates for the main thread.
        """
        logger.debug("Global simulation loop starting.")
        while self._simulation_running:
            loop_start_time = time.time()
            now_time = datetime.now() # Get time once per tick for consistency
            
            # Flag to check if a state change occurred in the current room requiring button updates
            current_room_state_changed = False 

            # Iterate through a copy of room states for safety if rooms could be added/removed during loop
            for room_name, room_state in list(self.room_states.items()): 
                
                # --- Process Scheduled Events for this room ---
                # Iterate backwards through scheduled events for safe removal or modification
                for i in range(len(room_state.get('scheduled_events', [])) -1, -1, -1):
                    event = room_state['scheduled_events'][i]
                    # Check if event is due and not already triggered
                    if not event.get('triggered', False) and now_time >= datetime.fromisoformat(event['start_time_iso']):
                        self.execute_scheduled_event(room_name, event) # Execute the action
                        event['triggered'] = True # Mark as done
                        if room_name == self.current_room: current_room_state_changed = True
                
                # --- Process Timers (Timed Heat, AC Boost) for this room ---
                # Timed Heat
                if room_state.get('timed_heat_active', False):
                    room_state['heat_on'] = True # Ensure heat is considered ON
                    room_state['timed_heat_remaining_seconds'] -= SIMULATION_TICK_INTERVAL_SECONDS
                    if room_state['timed_heat_remaining_seconds'] <= 0:
                        # Timer expired
                        room_state['timed_heat_active'] = False
                        room_state['heat_on'] = False # Turn heat off
                        room_state['timed_heat_remaining_seconds'] = 0
                        self.add_activity_log(f"Timed heat finished in {room_name}.")
                        logger.info(f"Timed heat finished for {room_name}.")
                        if room_name == self.current_room: current_room_state_changed = True
                
                # AC Boost
                if room_state.get('ac_boost_on', False):
                    # AC Boost overrides manual heat if both were somehow active
                    if room_state.get('heat_on', False) and not room_state.get('timed_heat_active', False): 
                        room_state['heat_on'] = False
                    room_state['ac_boost_timer'] -= SIMULATION_TICK_INTERVAL_SECONDS
                    if room_state['ac_boost_timer'] <= 0:
                        # Timer expired
                        room_state['ac_boost_on'] = False
                        room_state['ac_boost_timer'] = 0
                        self.add_activity_log(f"AC Boost ended in {room_name}.")
                        logger.info(f"AC Boost finished for {room_name}.")
                        if room_name == self.current_room: current_room_state_changed = True

                # --- Apply climate changes (Temperature and Humidity) for ALL rooms ---
                temp_change = 0.0
                humidity_change = 0.0
                
                # Apply direct heating/cooling effects
                if room_state.get('heat_on', False): # Covers timed and manual heat
                    temp_change += HEAT_RATE
                elif room_state.get('ac_boost_on', False):
                    temp_change -= COOL_RATE_AC
                    humidity_change -= AC_HUMIDITY_REDUCTION_RATE
                
                # Apply ambient temperature drift
                drift_rate_temp = BACKGROUND_AMBIENT_DRIFT_RATE_TEMP if room_name != self.current_room else AMBIENT_DRIFT_RATE_TEMP
                current_temp = room_state.get('temp', INITIAL_TEMP_CELSIUS)
                if current_temp < AMBIENT_TEMP_TARGET: 
                    temp_change += drift_rate_temp * abs(AMBIENT_TEMP_TARGET - current_temp) * 0.15
                elif current_temp > AMBIENT_TEMP_TARGET: 
                    temp_change -= drift_rate_temp * abs(current_temp - AMBIENT_TEMP_TARGET) * 0.15
                
                # Apply ambient humidity drift
                drift_rate_humidity = BACKGROUND_AMBIENT_DRIFT_RATE_HUMIDITY if room_name != self.current_room else AMBIENT_DRIFT_RATE_HUMIDITY
                current_humidity = room_state.get('humidity', INITIAL_HUMIDITY_PERCENT)
                if current_humidity < AMBIENT_HUMIDITY_TARGET: 
                    humidity_change += drift_rate_humidity * abs(AMBIENT_HUMIDITY_TARGET - current_humidity) * 0.15
                elif current_humidity > AMBIENT_HUMIDITY_TARGET: 
                    humidity_change -= drift_rate_humidity * abs(current_humidity - AMBIENT_HUMIDITY_TARGET) * 0.15
                
                # Apply random fluctuations only to the currently viewed room
                if room_name == self.current_room:
                    temp_change += random.uniform(-0.03, 0.03)
                    humidity_change += random.uniform(-0.08, 0.08)
                
                # Update and clamp temperature and humidity values
                room_state['temp'] = current_temp + temp_change
                room_state['temp'] = max(5.0, min(35.0, room_state['temp'])) # Clamp within realistic bounds
                room_state['humidity'] = current_humidity + humidity_change
                room_state['humidity'] = max(10.0, min(90.0, room_state['humidity'])) # Clamp within realistic bounds

                # Update graph data history ONLY for the currently viewed room
                if room_name == self.current_room:
                    room_state['simulation_time_elapsed'] += SIMULATION_TICK_INTERVAL_SECONDS
                    room_state['time_data'].append(room_state['simulation_time_elapsed'])
                    room_state['temp_data'].append(room_state['temp'])
                    room_state['humidity_data'].append(room_state['humidity'])
            
            # --- Schedule UI Update ---
            # Ensure the root window still exists before scheduling updates
            if self.root.winfo_exists(): 
                # If a timer/event changed state for the *current* room, update buttons immediately
                if current_room_state_changed: 
                    self.root.after(0, self._update_button_states) 
                # Always schedule a general UI refresh for the current room
                self.root.after(0, self.update_all_ui_for_current_room) 
            
            # --- Loop Timing Control ---
            elapsed_time = time.time() - loop_start_time
            sleep_time = SIMULATION_TICK_INTERVAL_SECONDS - elapsed_time
            if sleep_time > 0: 
                time.sleep(sleep_time) # Wait to maintain the desired tick interval
                
        logger.debug("Global simulation loop ended.")


    def schedule_event_prompt(self):
        """
        Opens dialogs to gather information for scheduling a future 'Start Timed Heat' action.
        Validates input and adds the event to the selected room's schedule.
        """
        if not self.current_room or not self.root.winfo_exists():
            messagebox.showinfo("No Room", "Please select a room first.", parent=self.root)
            return
            
        # Use try-except for robustness against non-integer input in dialogs
        try:
            # Ask for delay
            delay_minutes = simpledialog.askinteger("Schedule Event", 
                                                    "Start Timed Heat in how many minutes (1-1440, i.e., 24h)?",
                                                    parent=self.root, minvalue=1, maxvalue=1440)
            if delay_minutes is None: return # User cancelled delay input
            
            # Ask for duration
            duration_minutes = simpledialog.askinteger("Schedule Event", 
                                                       f"Timed Heat duration in minutes (1-{MAX_TIMED_HEAT_MINUTES}):",
                                                       parent=self.root, minvalue=1, maxvalue=MAX_TIMED_HEAT_MINUTES)
            if duration_minutes is None: return # User cancelled duration input
            
        except Exception as e:
            logger.error(f"Error getting schedule input: {e}")
            messagebox.showerror("Input Error", "Invalid numerical input required.", parent=self.root)
            return

        # Calculate the absolute start time for the event
        start_time = datetime.now() + timedelta(minutes=delay_minutes)
        
        # Create the event dictionary
        event = {
            'start_time_iso': start_time.isoformat(), # Store timestamp as ISO string (JSON compatible)
            'action': 'start_timed_heat',
            'params': {'duration_minutes': duration_minutes},
            'triggered': False, # Mark as not yet triggered
            'description': f"Timed Heat for {duration_minutes}m in {delay_minutes}m" # User-friendly description
        }
        
        # Add event to the room's schedule list and save state
        self.room_states[self.current_room]['scheduled_events'].append(event)
        self._save_state_to_config() 
        
        # Log the scheduling action
        self.add_activity_log(f"Scheduled: {event['description']} for {self.current_room} at {start_time.strftime('%H:%M:%S')}.")
        logger.info(f"Scheduled event: {event} for room {self.current_room}")
        
        # Update UI (specifically combobox suffix)
        self.update_room_combobox_display() 


    def execute_scheduled_event(self, room_name, event_details):
        """
        Executes the action defined in a scheduled event dictionary for a specific room.
        Currently handles 'start_timed_heat'.

        Args:
            room_name (str): The name of the room where the event occurs.
            event_details (dict): The dictionary containing event information.
        """
        action = event_details['action']
        params = event_details.get('params', {})
        logger.info(f"Executing scheduled event '{action}' for room '{room_name}' with params: {params}")
        self.add_activity_log(f"Executing: {event_details.get('description', action)} in {room_name}.")
        
        # Get the state for the target room
        room_state = self.room_states[room_name]

        # --- Handle specific actions ---
        if action == 'start_timed_heat':
            duration = params.get('duration_minutes', 10) # Default duration if not specified
            
            # Check for conflicts (e.g., manual heat or AC already on)
            if room_state.get('heat_on', False) or room_state.get('ac_boost_on', False):
                self.add_activity_log(f"Skipped scheduled Timed Heat for {room_name} due to existing operation.")
                logger.warning(f"Skipped scheduled Timed Heat for {room_name} due to conflict.")
                return # Do not execute if conflict exists

            # Start the timed heat
            room_state['timed_heat_active'] = True
            room_state['timed_heat_remaining_seconds'] = duration * 60
            room_state['heat_on'] = True # Timed heat implies heat is on
            self.add_activity_log(f"Scheduled Timed Heat started for {duration}m in {room_name}.")
        

        # --- Update UI if the affected room is the currently viewed one ---
        if room_name == self.current_room and self.root.winfo_exists():
            self.root.after(0, self._update_button_states) # Schedule button state update
            
        # Update combobox display as the status (S)/(T) might have changed
        self.update_room_combobox_display() 


    def _update_graph(self):
        """Redraws the Matplotlib graphs with data for the currently selected room."""
        # Check if essential components exist
        if not hasattr(self, 'canvas_widget') or not self.canvas_widget.winfo_exists() or not self.current_room: return
        if self.current_room not in self.room_states: return 
        
        room_state = self.room_states[self.current_room]
        # Get data, converting deques to lists for plotting
        time_list = list(room_state.get('time_data', []))
        temp_list = list(room_state.get('temp_data', []))
        humidity_list = list(room_state.get('humidity_data', []))
        
        # Update temperature plot data and rescale axes
        self.line_temp.set_data(time_list, temp_list)
        self.ax_temp.relim(); self.ax_temp.autoscale_view(True, True, True)
        # Set Y-axis limits dynamically for better visibility, with fallback defaults
        min_temp_display = min(temp_list) - 2 if temp_list else 15
        max_temp_display = max(temp_list) + 2 if temp_list else 25
        self.ax_temp.set_ylim(min(10, min_temp_display), max(30, max_temp_display))

        # Update humidity plot data and rescale axes
        self.line_humidity.set_data(time_list, humidity_list)
        self.ax_humidity.relim(); self.ax_humidity.autoscale_view(True, True, True)
        min_hum_display = min(humidity_list) - 5 if humidity_list else 30
        max_hum_display = max(humidity_list) + 5 if humidity_list else 70
        self.ax_humidity.set_ylim(min(20, min_hum_display), max(80, max_hum_display))

        # Update X-axis limits based on time data
        if time_list:
            # Show the window of data defined by GRAPH_DATA_POINTS
            start_time = time_list[0] if len(time_list) < GRAPH_DATA_POINTS else time_list[-GRAPH_DATA_POINTS]
            end_time = time_list[-1] + SIMULATION_TICK_INTERVAL_SECONDS # Add padding
            self.ax_temp.set_xlim(start_time, end_time)
            self.ax_humidity.set_xlim(start_time, end_time)
        else:
            # Default x-axis if no data
            self.ax_temp.set_xlim(0, GRAPH_DATA_POINTS * SIMULATION_TICK_INTERVAL_SECONDS)
            self.ax_humidity.set_xlim(0, GRAPH_DATA_POINTS * SIMULATION_TICK_INTERVAL_SECONDS)
            
        # Request Tkinter to redraw the canvas when idle
        self.canvas.draw_idle()


    def _update_status_indicator(self):
        """Updates the text and colour of the system status indicator label."""
        # Check if essential components exist
        if not hasattr(self, 'system_status_indicator') or not self.system_status_indicator.winfo_exists() or not self.current_room: return
        if self.current_room not in self.room_states: return 
        
        room_state = self.room_states[self.current_room]
        status_text = f"{self.current_room}: Idle"; status_color = "grey" # Default state

        # Determine status based on active operations (priority: Timed Heat > Heat > AC Boost)
        if room_state.get('timed_heat_active', False):
            remaining_seconds = room_state.get('timed_heat_remaining_seconds', 0)
            minutes = remaining_seconds // 60; seconds = remaining_seconds % 60
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            status_text = f"{self.current_room}: Timed Heat ({time_str} left)"; status_color = "purple" 
        elif room_state.get('heat_on', False): # Manual heat
            status_text = f"{self.current_room}: Heating ON"; status_color = "orange red"
        elif room_state.get('ac_boost_on', False):
            status_text = f"{self.current_room}: AC Boost ({room_state.get('ac_boost_timer', 0)}s)"; status_color = "dodger blue"
        
        # Append global simulation status if it's not running
        if not self._simulation_running:
            sim_status_text = "Sim Offline" if not self.simulation_thread or not self.simulation_thread.is_alive() else "Sim Paused"
            sim_color = "dim gray" if sim_status_text == "Sim Offline" else "dark orange"
            # Replace 'Idle' or append the simulation status
            if status_text.endswith("Idle"): 
                status_text = f"{self.current_room}: {sim_status_text}"; status_color = sim_color
            else: 
                status_text += f" (Sim: {sim_status_text})"
                
        # Update the label widget
        self.system_status_indicator.config(text=status_text, foreground=status_color)


    def _update_button_states(self):
        """Updates the enabled/disabled state and text of control buttons based on the current room's state."""
        # Check if essential components exist
        if not hasattr(self, 'heat_on_button') or not self.heat_on_button.winfo_exists() or not self.current_room: return
        if self.current_room not in self.room_states: return 
        
        room_state = self.room_states[self.current_room]
        
        # Determine current operational states
        is_timed_heating = room_state.get('timed_heat_active', False)
        is_ac_boosting = room_state.get('ac_boost_on', False)
        is_manual_heating = room_state.get('heat_on', False) and not is_timed_heating

        # Default button states (all enabled, standard text)
        heat_on_btn_state = tk.NORMAL
        heat_off_btn_state = tk.DISABLED
        ac_boost_btn_state = tk.NORMAL
        timed_heat_btn_text = "Timed Heat"
        timed_heat_btn_state = tk.NORMAL
        schedule_btn_state = tk.NORMAL # Schedule button enabled by default

        # Adjust states based on active operations
        if is_timed_heating:
            heat_on_btn_state = tk.DISABLED; heat_off_btn_state = tk.DISABLED
            ac_boost_btn_state = tk.DISABLED; schedule_btn_state = tk.DISABLED 
            remaining_seconds = room_state.get('timed_heat_remaining_seconds', 0)
            minutes = remaining_seconds // 60; seconds = remaining_seconds % 60
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            timed_heat_btn_text = f"Cancel Timed Heat ({time_str} left)" # Change text to Cancel
        elif is_manual_heating:
            heat_on_btn_state = tk.DISABLED; heat_off_btn_state = tk.NORMAL # Enable Heat OFF
            ac_boost_btn_state = tk.DISABLED; timed_heat_btn_state = tk.DISABLED
            schedule_btn_state = tk.DISABLED 
        elif is_ac_boosting:
            heat_on_btn_state = tk.DISABLED; heat_off_btn_state = tk.DISABLED
            ac_boost_btn_state = tk.DISABLED; timed_heat_btn_state = tk.DISABLED
            schedule_btn_state = tk.DISABLED 
        
        # Set AC Boost button text
        ac_button_text = f"Boost AC ({room_state.get('ac_boost_timer', 0)}s)" if is_ac_boosting else "Boost AC"
        
        # Apply states to widgets, checking existence first
        if self.heat_on_button.winfo_exists(): self.heat_on_button.config(state=heat_on_btn_state)
        if self.heat_off_button.winfo_exists(): self.heat_off_button.config(state=heat_off_btn_state)
        if self.ac_boost_button.winfo_exists(): self.ac_boost_button.config(state=ac_boost_btn_state, text=ac_button_text)
        if self.timed_heat_button.winfo_exists(): self.timed_heat_button.config(text=timed_heat_btn_text, state=timed_heat_btn_state)
        if hasattr(self, 'schedule_event_button') and self.schedule_event_button.winfo_exists():
            self.schedule_event_button.config(state=schedule_btn_state)
        
        # Update the status indicator label as well, as it depends on these states
        self._update_status_indicator()


    def toggle_heat_on(self):
        """Handles the 'Heat ON' button click (Manual Heat)."""
        if not self.current_room or self.current_room not in self.room_states: return
        room_state = self.room_states[self.current_room]
        
        # Prevent activation if timed heat or AC boost is running
        if room_state.get('timed_heat_active', False) or room_state.get('ac_boost_on', False):
            self.add_activity_log(f"Cannot turn on manual heat in {self.current_room} while other operations are active.")
            return
            
        # Activate if not already on
        if not room_state.get('heat_on', False):
            room_state['heat_on'] = True
            self.add_activity_log(f"Manual heat turned ON in {self.current_room}.")
            logger.info(f"Manual Heat ON for {self.current_room}.")
            self._update_button_states() # Update UI


    def toggle_heat_off(self):
        """Handles the 'Heat OFF' button click (Manual Heat)."""
        if not self.current_room or self.current_room not in self.room_states: return
        room_state = self.room_states[self.current_room]
        
        # Cannot manually turn off timed heat (must use Cancel)
        if room_state.get('timed_heat_active', False): 
            self.add_activity_log(f"Cannot turn off manual heat in {self.current_room} during timed heating. Cancel timed heat instead.")
            return
            
        # Deactivate if manual heat is currently on
        if room_state.get('heat_on', False):
            room_state['heat_on'] = False
            self.add_activity_log(f"Manual heat turned OFF in {self.current_room}.")
            logger.info(f"Manual Heat OFF for {self.current_room}.")
            self._update_button_states() # Update UI


    def activate_ac_boost(self):
        """Handles the 'Boost AC' button click."""
        if not self.current_room or self.current_room not in self.room_states: return
        room_state = self.room_states[self.current_room]
        
        # Prevent activation if any heating is active
        if room_state.get('heat_on', False) or room_state.get('timed_heat_active', False):
            self.add_activity_log(f"Cannot activate AC Boost in {self.current_room} while heating is active.")
            return
            
        # Activate if not already boosting
        if not room_state.get('ac_boost_on', False):
            room_state['ac_boost_on'] = True
            room_state['ac_boost_timer'] = 30 # Set 30 second timer
            self.add_activity_log(f"AC Boost activated for 30s in {self.current_room}.")
            logger.info(f"AC Boost ON for {self.current_room}.")
            self._update_button_states() # Update UI


    def toggle_timed_heat(self):
        """Handles the 'Timed Heat' / 'Cancel Timed Heat' button click."""
        if not self.current_room or not self.root.winfo_exists() or self.current_room not in self.room_states: return
        room_state = self.room_states[self.current_room]
        
        # If timed heat is currently active, cancel it
        if room_state.get('timed_heat_active', False): 
            room_state['timed_heat_active'] = False
            room_state['heat_on'] = False # Ensure heat turns off
            room_state['timed_heat_remaining_seconds'] = 0
            self.add_activity_log(f"Timed heat cancelled for {self.current_room}.")
            logger.info(f"Timed heat cancelled for {self.current_room}.")
            
        # If trying to start timed heat, check for conflicts first
        elif room_state.get('heat_on', False) or room_state.get('ac_boost_on', False):
             self.add_activity_log(f"Cannot start timed heat in {self.current_room} while other operations are active.")
             messagebox.showwarning("Operation Conflict", "Turn off manual heat or AC boost before starting timed heat.", parent=self.root)
             return
             
        # Otherwise, prompt user for duration and start timed heat
        else: 
            try:
                duration_minutes = simpledialog.askinteger("Timed Heat Duration", 
                                                        f"Enter duration in minutes (1-{MAX_TIMED_HEAT_MINUTES}):",
                                                        parent=self.root, minvalue=1, maxvalue=MAX_TIMED_HEAT_MINUTES)
            except Exception as e:
                 logger.error(f"Error getting timed heat duration: {e}")
                 messagebox.showerror("Input Error", "Invalid numerical input required.", parent=self.root)
                 return

            if duration_minutes is not None: # User entered a value
                room_state['timed_heat_active'] = True
                room_state['timed_heat_remaining_seconds'] = duration_minutes * 60
                room_state['heat_on'] = True # Timed heat implies heat is on
                self.add_activity_log(f"Timed heat started for {duration_minutes} min in {self.current_room}.")
                logger.info(f"Timed heat for {duration_minutes} min started for {self.current_room}.")
            else: 
                logger.info("Timed heat duration input cancelled.")
                
        # Update UI regardless of action taken (start or cancel)
        self._update_button_states() 


    def logout(self):
        """Handles the logout process: saves state and calls the main app's logout handler."""
        logger.info("Logout requested by user.")
        self.add_activity_log("User logged out.")
        self._save_state_to_config() # Save current state before logging out
        self.on_logout_callback() # Trigger screen switch in main app


    def destroy(self):
        """Cleans up resources when the dashboard screen is destroyed."""
        logger.info("Destroying SystemStatusScreen.")
        self.stop_simulation() # Ensure simulation thread is stopped
        self._save_state_to_config() # Save final state on graceful shutdown
        
        # Clean up Matplotlib resources
        if hasattr(self, 'canvas_widget') and self.canvas_widget.winfo_exists(): 
            self.canvas_widget.destroy()
        if hasattr(self, 'fig'): 
            plt.close(self.fig) # Close the figure to release memory
            
        # Destroy the main Tkinter frame for this screen
        if hasattr(self, 'dashboard_frame') and self.dashboard_frame.winfo_exists(): 
            self.dashboard_frame.destroy()

# --- Main execution block for testing this module independently ---
if __name__ == '__main__':
    # Configure basic logging for testing
    logging.basicConfig(level=logging.DEBUG, 
                        handlers=[logging.StreamHandler()], 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
    
    # Create main test window
    root_test = tk.Tk()
    root_test.title("System Dashboard Test - Outstanding")
    root_test.geometry("1200x800") # Set test window size
    
    # Apply a theme
    style = ttk.Style(root_test)
    try:
        if 'clam' in style.theme_names(): style.theme_use('clam')
        elif 'alt' in style.theme_names(): style.theme_use('alt')
    except tk.TclError: 
        logger.warning("Could not apply 'clam' or 'alt' theme. Using default.")
    
    # Dummy callback function for logout action during testing
    def test_logout_callback(): 
        logger.info("Logout callback triggered (test mode).")
        dashboard.destroy() # Ensure destroy is called
        root_test.quit() # Exit the test application

    # Create instance of the dashboard screen
    dashboard = SystemStatusScreen(root_test, test_logout_callback)
    
    # Start simulation only if a room is available
    if dashboard.current_room: 
        dashboard.start_simulation()
    
    # Define behaviour for closing the test window
    def on_test_closing(): 
        logger.info("Test window closing...")
        dashboard.destroy() # Ensure destroy (which includes saving state) is called
        root_test.destroy() # Destroy the main Tk window
    
    # Bind the window close event (clicking the 'X') to our cleanup function
    root_test.protocol("WM_DELETE_WINDOW", on_test_closing)
    
    # Start the Tkinter event loop for the test window
    root_test.mainloop()
