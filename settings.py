import json
import logging
import os
import shutil

import tinify

from .constants import PACKAGE

# LOGGING
LOGGER = logging.getLogger(__name__)


def get_local_settings_path():
    """Returns the local settings path"""
    if os.name == "posix":  # Unix-like systems
        return os.path.expanduser("~/.apngc/settings")
    elif os.name == "nt":  # Windows
        return os.path.join(os.getenv("APPDATA"), "apngc", "settings")
    else:
        raise RuntimeError("Unsupported platform")


def discover_settings():
    """Returns all settings files"""
    global_settings_dir = os.path.join(PACKAGE, "settings")
    local_settings_dir = get_local_settings_path()
    LOGGER.debug(f"Global settings: {global_settings_dir}")
    LOGGER.debug(f"Local settings: {local_settings_dir}")

    settings = []
    if not os.path.exists(local_settings_dir):
        shutil.copytree(global_settings_dir, local_settings_dir)
        LOGGER.info(f"Created local settings: {local_settings_dir}")

    settings = [
        os.path.join(local_settings_dir, f)
        for f in os.listdir(local_settings_dir)
        if f.endswith(".json")
    ]

    return settings


def get_settings(settings_file):
    """Returns the settings from a settings file"""
    settings = {}
    if not os.path.isfile(settings_file):
        return settings

    with open(settings_file, "r") as f:
        settings = json.load(f)

    return settings


def remove_settings(settings_name):
    """Removes a settings file"""
    settings_file = os.path.join(
        get_local_settings_path(), settings_name + ".json"
    )
    if os.path.isfile(settings_file):
        os.remove(settings_file)


def save_settings(settings, settings_name):
    """Writes a settings dictionary to a json settings file"""
    settings_file = os.path.join(
        get_local_settings_path(), settings_name + ".json"
    )
    with open(settings_file, "w") as json_file:
        json.dump(settings, json_file, indent=4)


def validate_settings(settings):
    """Validate settings"""
    errors = []

    # THESE JUST NEED SOME VALUE (but output_path can be empty)
    required_settings = ["width", "height", "framerate"]
    for setting in required_settings:
        if not settings.get(setting):
            errors.append(f"Must specify {setting}.")

    # VALIDATE THE TINIFY KEY
    if settings.get("optimize"):
        if not settings.get("tinify_key"):
            errors.append("Must specify 'TINIFY KEY' if optimizing.")
        # else:
        #     try:
        #         tinify.key = settings.get("tinify_key")
        #         tinify.validate()
        #     except tinify.Error as e:
        #         errors.append(
        #             f"Invalid TINIFY KEY: {settings.get('tinify_key')}."
        #         )
        #         errors.append(f"{e}")

    # Only validate output_path if it's not empty
    if settings.get("output_path") and settings.get("output_path").strip():
        if not os.path.isdir(settings.get("output_path")):
            errors.append(
                f"Output path does not exist: '{settings.get('output_path')}'."
            )

    return errors
