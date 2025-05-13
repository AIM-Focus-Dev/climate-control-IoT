# utils.py
# Contains shared utility functions for hashing, configuration management, and formatting.

import hashlib
import json
import os
import logging

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
DEFAULT_ROOM_KEY = "default_rooms" # Key for storing the list of rooms
ROOM_STATES_KEY = "room_states" # Key for storing states of rooms 

def hash_password(password: str) -> str:
    """
    Hashes a given password using SHA-256.
    Args:
        password: The password string to hash.
    Returns:
        The hexadecimal string representation of the hashed password.
    """
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash: str, provided_password: str) -> bool:
    """
    Verifies a provided password against a stored hash.
    Args:
        stored_hash: The hash stored in the configuration.
        provided_password: The password provided by the user.
    Returns:
        True if the passwords match, False otherwise.
    """
    return stored_hash == hash_password(provided_password)

def load_config() -> dict:
    """
    Loads the configuration from config.json.
    Now includes loading room lists.
    If the file doesn't exist or is corrupted, it returns an empty dictionary
    and logs an appropriate message.
    Returns:
        A dictionary containing the configuration. Expected keys include
        'password_hash' and potentially 'rooms'.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Configuration loaded successfully from {CONFIG_FILE}.")
                return config
        except json.JSONDecodeError:
            logger.error(f"Error: {CONFIG_FILE} is corrupted or not valid JSON. A new one may be created.", exc_info=True)
            return {} 
        except IOError as e:
            logger.error(f"IOError reading {CONFIG_FILE}: {e}", exc_info=True)
            return {}
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading {CONFIG_FILE}: {e}", exc_info=True)
            return {}
    else:
        logger.info(f"{CONFIG_FILE} not found. A new one may be created on first password set or room config save.")
        return {}

def save_config(config_data: dict) -> bool:
    """
    Saves the provided configuration dictionary to config.json.
    Args:
        config_data: The dictionary containing the configuration to save.
                     This should include 'password_hash' and 'rooms' list.
    Returns:
        True if saving was successful, False otherwise.
    """
    try:
        with open(CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        logger.info(f"Configuration saved successfully to {CONFIG_FILE}.")
        return True
    except IOError as e:
        logger.error(f"IOError: Could not write configuration to {CONFIG_FILE}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while saving {CONFIG_FILE}: {e}", exc_info=True)
        return False

def format_temperature(temp_celsius: float) -> str:
    """
    Formats the temperature for display (e.g., "23.5 °C").
    Args:
        temp_celsius: The temperature in Celsius.
    Returns:
        A string representation of the formatted temperature.
    """
    return f"{temp_celsius:.1f} °C"

def format_humidity(humidity_percent: float) -> str:
    """
    Formats the humidity for display (e.g., "45.0 %RH").
    Args:
        humidity_percent: The humidity in percentage.
    Returns:
        A string representation of the formatted humidity.
    """
    return f"{humidity_percent:.1f} %RH"

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Testing utils.py...")

    test_password = "securepassword123"
    hashed = hash_password(test_password)
    
    # Test saving and loading rooms
    initial_config = {
        "password_hash": hashed,
        DEFAULT_ROOM_KEY: ["Test Room 1", "Test Room 2"]
    }
    if save_config(initial_config):
        logger.info(f"Saved initial config with rooms: {initial_config[DEFAULT_ROOM_KEY]}")

    loaded_conf = load_config()
    logger.info(f"Loaded config: {loaded_conf}")
    
    loaded_rooms = loaded_conf.get(DEFAULT_ROOM_KEY)
    if loaded_rooms:
        logger.info(f"Rooms loaded from config: {loaded_rooms}")
    else:
        logger.warning(f"No rooms found under key '{DEFAULT_ROOM_KEY}' in loaded config.")

    # Clean up
    # if os.path.exists(CONFIG_FILE):
    #     os.remove(CONFIG_FILE)
    #     logger.info(f"Cleaned up {CONFIG_FILE}")
