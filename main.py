# main.py
# Entry point for the Smart Home Climate Control Simulation application.
# Initialises the main Tkinter window, manages screen switching between

import tkinter as tk
from tkinter import ttk
import auth         # Module for the login screen and authentication logic
import sys_status   # Module for the main dashboard screen and simulation logic
import utils        # Module for shared utilities (config, hashing, formatting)
import logging
import logging.handlers # Required for RotatingFileHandler

# --- Logging Configuration Constants ---
LOG_FILENAME = "climate_control_app.log"  # Name of the log file
MAX_LOG_SIZE_BYTES = 1024 * 1024 * 5      # 5 MB maximum log file size
LOG_BACKUP_COUNT = 3                      # Number of backup log files to keep

def setup_logging():
    """
    Configures the global logging settings for the entire application.
    Sets up logging to both the console and a rotating file.
    """
    # Get the root logger instance
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) # Log messages of DEBUG level and above

    # Define the log message format
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )

    # Configure console logging handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO) # Show INFO level and above on console by default
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Configure rotating file logging handler
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILENAME,
            maxBytes=MAX_LOG_SIZE_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8' # Specify UTF-8 encoding for the log file
        )
        file_handler.setLevel(logging.DEBUG) # Log DEBUG level and above to the file
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Log an error if file logging setup fails (e.g., permissions issue)
        root_logger.error(f"Failed to set up file logging to {LOG_FILENAME}: {e}", exc_info=True)

    logging.info("Logging initialised. Application starting.")


class ClimateControlApp:
    """
    The main application class.
    Manages the Tkinter root window and orchestrates the switching
    between the LoginScreen and SystemStatusScreen.
    """
    def __init__(self, root_window):
        """
        Initialises the main application window and sets up styling.

        Args:
            root_window: The main Tkinter root window (tk.Tk instance).
        """
        self.root = root_window
        self.root.title("Smart Home Climate Control (Outstanding Edition)")
        # Set initial size suitable for dashboard; login screen will resize smaller
        self.root.geometry("1200x800") 

        # Apply a modern theme if available (e.g., 'clam', 'alt', 'vista')
        self.style = ttk.Style(self.root)
        available_themes = self.style.theme_names()
        logging.debug(f"Available ttk themes: {available_themes}")
        if 'clam' in available_themes: self.style.theme_use('clam')
        elif 'alt' in available_themes: self.style.theme_use('alt')
        elif 'vista' in available_themes: self.style.theme_use('vista') # fallback on Windows
        else: logging.info(f"Using default ttk theme: {self.style.theme_use()}")

        # Reference to the currently displayed screen object (LoginScreen or SystemStatusScreen)
        self.current_screen = None
        
        # Initialise by showing the login screen
        self.show_login_screen() 
        logging.info("ClimateControlApp initialised.")

    def show_login_screen(self):
        """
        Destroys the current screen (if any) and displays the LoginScreen.
        Handles saving state if switching away from the dashboard.
        """
        logging.info("Attempting to display Login Screen.")
        if self.current_screen:
            # If switching from the dashboard, save its state first
            if isinstance(self.current_screen, sys_status.SystemStatusScreen):
                logging.debug("Saving full state before switching from dashboard to login.")
                self.current_screen._save_state_to_config() 
            
            # Destroy the widgets of the previous screen
            logging.debug(f"Destroying current screen: {type(self.current_screen).__name__}")
            self.current_screen.destroy()
            self.current_screen = None # Clear the reference

        # Resize window for the login screen dimensions
        self.root.geometry("450x350") 
        self.center_window(450, 350) # Centre the smaller window
        
        # Create and display the LoginScreen instance
        self.current_screen = auth.LoginScreen(self.root, self.on_login_successful)
        logging.info("Login Screen displayed.")
        self.root.deiconify() # Ensure the window is visible

    def on_login_successful(self):
        """
        Callback function executed after successful authentication.
        Destroys the login screen and displays the SystemStatusScreen (dashboard).
        """
        logging.info("Login successful. Switching to Dashboard Screen.")
        if self.current_screen:
            # Destroy the login screen widgets
            logging.debug(f"Destroying current screen: {type(self.current_screen).__name__}")
            self.current_screen.destroy()
            self.current_screen = None

        # Resize window for the dashboard dimensions
        self.root.geometry("1200x800") 
        self.center_window(1200, 800) # Centre the larger window
        
        # Create and display the SystemStatusScreen instance
        self.current_screen = sys_status.SystemStatusScreen(self.root, self.on_logout)
        
        # Start the background simulation only if a room is configured
        if self.current_screen.current_room: 
            self.current_screen.start_simulation()
        logging.info("Dashboard Screen displayed and simulation potentially started.")

    def on_logout(self):
        """
        Callback function executed when the user logs out from the dashboard.
        Saves the dashboard state, destroys the dashboard screen, and displays the login screen.
        """
        logging.info("User logged out. Attempting to switch to Login Screen.")
        if self.current_screen: 
            # If the current screen is the dashboard, save its state
            if isinstance(self.current_screen, sys_status.SystemStatusScreen):
                logging.debug("Saving full state on logout.")
                self.current_screen._save_state_to_config() 

            # Destroy the dashboard screen widgets
            logging.debug(f"Destroying current screen before logout: {type(self.current_screen).__name__}")
            self.current_screen.destroy() 
            self.current_screen = None
            
        # Display the login screen again
        self.show_login_screen() 

    def center_window(self, width, height):
        """
        Centres the main application window on the screen.

        Args:
            width (int): The desired width of the window.
            height (int): The desired height of the window.
        """
        # Ensure the root window still exists before proceeding
        if not self.root.winfo_exists():
            logging.warning("Root window does not exist, cannot center.")
            return
            
        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Calculate position for top-left corner
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        
        # Set the window's geometry (size and position)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        logging.debug(f"Window centered to {width}x{height} at ({x},{y})")

    def run(self):
        """Starts the Tkinter main event loop, making the application interactive."""
        logging.info("Starting Tkinter main event loop.")
        self.root.mainloop()
        # This line is reached after the main window is closed
        logging.info("Tkinter main event loop finished.")

# --- Main Execution Block ---
# This code runs only when the script is executed directly (not imported as a module).
if __name__ == "__main__":
    # Set up logging as the first step
    setup_logging() 

    # Create the main Tkinter window
    app_root = tk.Tk()
    
    # Create an instance of the main application class
    app = ClimateControlApp(app_root)

    # Define the function to handle graceful shutdown when the window is closed
    def on_app_close():
        """Handles the event when the user closes the main window."""
        logging.info("Application close requested via window manager (WM_DELETE_WINDOW).")
        if app.current_screen:
            # If the dashboard is open, save its state before closing
            if isinstance(app.current_screen, sys_status.SystemStatusScreen):
                logging.info("Saving full state before application exit.")
                app.current_screen._save_state_to_config() 
            
            # Destroy the current screen's widgets
            logging.debug(f"Destroying current screen before app close: {type(app.current_screen).__name__}")
            app.current_screen.destroy() 
            app.current_screen = None
        
        # Destroy the main application window itself
        if app_root.winfo_exists():
            app_root.destroy()
        logging.info("Application shutdown complete.")

    # Bind the window close ('X' button) event to the on_app_close function
    app_root.protocol("WM_DELETE_WINDOW", on_app_close)
    
    # Start the application's main event loop
    app.run()
