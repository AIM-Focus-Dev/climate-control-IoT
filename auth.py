# auth.py
# Handles the login screen UI and authentication logic.

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog
import utils # Our utility functions
import logging

logger = logging.getLogger(__name__)

MAX_LOGIN_ATTEMPTS = 2

class LoginScreen:
    """
    Manages the login screen UI and authentication process.
    """
    def __init__(self, root, on_login_success_callback):
        """
        Initialises the LoginScreen.
        Args:
            root: The main Tkinter window (or a frame to embed into).
            on_login_success_callback: A function to call when login is successful.
        """
        self.root = root
        self.on_login_success_callback = on_login_success_callback
        self.attempts_left = MAX_LOGIN_ATTEMPTS
        logger.info("LoginScreen initialised.")

        self.config = utils.load_config() # load_config now logs its own success/failure
        self.password_hash = self.config.get("password_hash")

        if not self.password_hash:
            logger.warning("No password hash found in configuration. User will be prompted to set a new password.")
        else:
            logger.info("Password hash loaded from configuration.")

        self.login_frame = ttk.Frame(self.root, padding="20")
        self.login_frame.pack(expand=True) # Centre the frame

        # --- UI Elements ---
        self.title_label = ttk.Label(self.login_frame, text="Climate Control System Login", font=("Arial", 16, "bold"))
        self.title_label.pack(pady=(0, 20))

        self.password_label = ttk.Label(self.login_frame, text="Password:")
        self.password_label.pack(pady=(0, 5))

        self.password_entry = ttk.Entry(self.login_frame, show="*", width=30)
        self.password_entry.pack(pady=(0, 10))
        self.password_entry.focus_set() # Set focus to password entry

        self.login_button = ttk.Button(self.login_frame, text="Login", command=self.attempt_login)
        self.login_button.pack(pady=(0, 10))

        self.status_label = ttk.Label(self.login_frame, text="")
        self.status_label.pack()

        # Bind Enter key to login button
        self.root.bind('<Return>', lambda event: self.attempt_login())

        # Check if a password needs to be set (first run)
        if not self.password_hash:
            self.prompt_set_password()

    def prompt_set_password(self):
        """
        Prompts the user to set a new password on the first run or if config is missing/corrupted.
        """
        logger.info("Prompting user to set a new password.")
        self.status_label.config(text="First run: Please set a new password.", foreground="blue")
        self.login_button.config(text="Set Password", command=self.set_new_password)
        self.password_label.config(text="Enter New Password:")
        self.password_entry.delete(0, tk.END) # Clear entry
        self.password_entry.focus_set()

    def set_new_password(self):
        """
        Handles setting a new password.
        """
        new_password = self.password_entry.get()
        if not new_password:
            self.status_label.config(text="Password cannot be empty.", foreground="red")
            logger.warning("User attempted to set an empty password.")
            return

        if len(new_password) < 6: # Basic password strength check
            self.status_label.config(text="Password must be at least 6 characters.", foreground="red")
            logger.warning("User attempted to set a password shorter than 6 characters.")
            return

        # Ask for confirmation
        confirm_password = simpledialog.askstring("Confirm Password", "Re-enter new password:", parent=self.root, show='*')

        if new_password == confirm_password:
            self.password_hash = utils.hash_password(new_password)
            self.config["password_hash"] = self.password_hash
            if utils.save_config(self.config): # save_config now logs and returns status
                messagebox.showinfo("Password Set", "Password has been set successfully. Please log in.", parent=self.root)
                logger.info("New password set and configuration saved successfully.")
                # Revert UI to login mode
                self.password_label.config(text="Password:")
                self.login_button.config(text="Login", command=self.attempt_login)
                self.status_label.config(text="Password set. Please log in.", foreground="green")
                self.password_entry.delete(0, tk.END)
                self.password_entry.focus_set()
            else:
                messagebox.showerror("Error", "Could not save the new password. Please check logs.", parent=self.root)
                logger.error("Failed to save new password to configuration file.")
                self.status_label.config(text="Error saving password. Check logs.", foreground="red")

        elif confirm_password is not None: # User entered something but it didn't match
            self.status_label.config(text="Passwords do not match. Try again.", foreground="red")
            logger.warning("Password confirmation failed: passwords did not match.")
            self.password_entry.delete(0, tk.END)
        else: # User cancelled the confirmation dialog
            self.status_label.config(text="Password setting cancelled.", foreground="orange")
            logger.info("User cancelled the password setting process.")


    def attempt_login(self):
        """
        Attempts to log in the user.
        """
        if not self.password_hash:
            logger.error("Login attempt failed: No password hash configured. Forcing password set.")
            self.prompt_set_password()
            self.status_label.config(text="Error: No password set. Please set one.", foreground="red")
            return

        entered_password = self.password_entry.get()
        if not entered_password:
            self.status_label.config(text="Password cannot be empty.", foreground="red")
            logger.warning("Login attempt with empty password.")
            return

        if utils.verify_password(self.password_hash, entered_password):
            self.status_label.config(text="Login successful!", foreground="green")
            logger.info(f"User login successful.") 
            messagebox.showinfo("Login Success", "Welcome to the Climate Control System!", parent=self.root)
            self.on_login_success_callback() # Call the success callback
        else:
            self.attempts_left -= 1
            self.password_entry.delete(0, tk.END) # Clear password field
            logger.warning(f"Failed login attempt. Attempts remaining: {self.attempts_left}")
            if self.attempts_left > 0:
                self.status_label.config(
                    text=f"Incorrect password. {self.attempts_left} attempts remaining.",
                    foreground="red"
                )
            else:
                self.status_label.config(text="Max login attempts reached. Application will exit.", foreground="red")
                logger.critical("Maximum login attempts reached. Application will exit.")
                messagebox.showerror("Login Failed", "Maximum login attempts reached. The application will now close.", parent=self.root)
                self.root.quit()

    def destroy(self):
        """
        Cleans up the login screen widgets.
        """
        logger.info("Destroying LoginScreen.")
        if self.login_frame.winfo_exists():
            self.login_frame.destroy()
        # Unbind the enter key if it was bound specifically for this screen
        self.root.unbind('<Return>')


if __name__ == '__main__':
    # Basic logging configuration for testing this module directly
    logging.basicConfig(level=logging.DEBUG, handlers=[logging.StreamHandler()], format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    root_test = tk.Tk()
    root_test.title("Login Screen Test")
    root_test.geometry("400x300")

    style = ttk.Style(root_test)
    try:
        if 'clam' in style.theme_names(): style.theme_use('clam')
        elif 'alt' in style.theme_names(): style.theme_use('alt')
    except tk.TclError:
        logger.warning("Note: 'clam' or 'alt' theme not found, using default for LoginScreen test.")

    def on_success_test():
        logger.info("Login successful (test mode)! Main application would load now.")
        messagebox.showinfo("Test Success", "Login was successful!", parent=root_test)

    login_screen = LoginScreen(root_test, on_success_test)
    root_test.mainloop()
