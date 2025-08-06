import logging
import os
import sys
import threading

from PySide6.QtCore import (
    QFile,
    QObject,
    QRegularExpression,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
    QRegion,
    QRegularExpressionValidator,
)
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .apng import APNGProcessor, get_directories_with_files
from .constants import PACKAGE
from .settings import (
    discover_settings,
    get_settings,
    remove_settings,
    save_settings,
    validate_settings,
)

# LOGGING
LOGGER = logging.getLogger(__name__)


class DropWidget(QWidget):
    directory_deleted = Signal(bool)
    stage_empty = Signal(bool)

    def __init__(self):
        super().__init__()

        self.setAcceptDrops(True)

        self.directories = []

        self.layout = QVBoxLayout()
        self.label = None
        self.setLayout(self.layout)

        self.create_label()

    def create_label(self):
        if self.label:
            return

        self.label = QLabel("Drag and drop folders here")
        self.label.setObjectName("dd_LBL")
        self.label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label)
        self.layout.setAlignment(Qt.AlignCenter)

        self.stage_empty.emit(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            for url in urls:
                folder_path = url.toLocalFile()
                subfolders = get_directories_with_files(folder_path)
                for subfolder in subfolders:
                    dir_wig = self.create_dir_wig(subfolder)
                    self.layout.addWidget(dir_wig)

                    # REMOVE THE LABLE ON FIRST DROP
                    if self.label:
                        self.label.deleteLater()
                        self.label = None
                        self.layout.setAlignment(Qt.AlignTop)

                        self.stage_empty.emit(False)
        else:
            event.ignore()

    def create_dir_wig(self, path):
        wig = load_ui("directory")
        wig.folder_LED.setText(path)
        wig.del_BTN.clicked.connect(lambda: self.delete_dir_wig(wig))
        self.directories.append(wig)

        set_icon(wig.del_BTN, "close")

        return wig

    def delete_dir_wig(self, wig):
        self.directory_deleted.emit(True)
        wig.deleteLater()
        self.directories.remove(wig)

        if self.layout.count() == 1:
            self.create_label()

    def clear(self):
        all_dirs = self.directories.copy()
        num_dirs = len(all_dirs)
        for directory in all_dirs:
            self.delete_dir_wig(directory)

        if num_dirs > 0:
            self.create_label()


class ApngConverter(QMainWindow):
    failed_directory = Signal(QWidget)

    def __init__(self):
        super().__init__()

        self.setWindowTitle("APNG Converter")
        self.setGeometry(100, 100, 800, 600)

        self.settings_data = {}
        self.total_progress = 0

        # Initialize sound effect
        self.sound_effect = QSoundEffect()

        # LOAD UI
        self.ui = load_ui("main")
        self.setCentralWidget(self.ui)

        self.drop_widget = DropWidget()
        self.ui.dd_SCR.setWidget(self.drop_widget)

        # STORE CTL THAT WILL TOGGLE ENABLE\DISABLE STATES WHEN PROCESSING
        self.toggle_ctls = [
            self.ui.clear_BTN,
            self.ui.settings_CBX,
            self.ui.convert_BTN,
            self.ui.framerate_SPB,
            self.ui.hold_SPB,
            self.ui.height_SPB,
            self.ui.width_SPB,
            self.ui.browse_BTN,
            self.ui.output_LED,
            self.ui.loops_SPB,
            self.ui.opt_CHB,
            self.ui.settingsAdd_BTN,
            self.ui.settingsRem_BTN,
            self.ui.key_LED,
        ]

        self.add_icons()
        self.create_connections()
        self.populate_settings()
        self.disable_convert(True)

        load_stylesheet(self)

    def add_icons(self):
        set_icon(self.ui.settingsAdd_BTN, "add", 5, 5)
        set_icon(self.ui.settingsRem_BTN, "remove", 5, 5)
        set_icon(self.ui.browse_BTN, "folder", 10, 10)

    def create_connections(self):
        self.ui.settings_CBX.currentIndexChanged.connect(self.load_settings)
        self.ui.convert_BTN.clicked.connect(self.convert)
        self.ui.browse_BTN.clicked.connect(self.browse_folder)
        self.ui.clear_BTN.clicked.connect(self.drop_widget.clear)
        self.drop_widget.directory_deleted.connect(self.reset_progress)
        self.ui.opt_CHB.stateChanged.connect(self.toggle_tinify_key)
        self.ui.settingsAdd_BTN.clicked.connect(self.show_settings_input)
        self.ui.settingsRem_BTN.clicked.connect(self.confirm_remove_settings)
        self.drop_widget.stage_empty.connect(self.disable_convert)
        self.failed_directory.connect(self.update_failed_directory)

    def disable_convert(self, disabled):
        self.ui.convert_BTN.setDisabled(disabled)

    def toggle_tinify_key(self, state):
        if state == 2:
            self.ui.key_LED.setDisabled(False)
        else:
            self.ui.key_LED.setDisabled(True)

    def load_settings(self):
        """Loads the settings into the UI"""
        self.settings_name = self.ui.settings_CBX.currentText()
        self.settings = self.settings_data[self.settings_name]

        self.ui.width_SPB.setValue(self.settings.get("width"))
        self.ui.height_SPB.setValue(self.settings.get("height"))
        self.ui.framerate_SPB.setValue(self.settings.get("framerate"))
        self.ui.opt_CHB.setChecked(self.settings.get("optimize"))
        self.ui.key_LED.setText(self.settings.get("tinify_key"))
        self.ui.loops_SPB.setValue(self.settings.get("loops"))
        self.ui.hold_SPB.setValue(self.settings.get("hold"))
        self.ui.output_LED.setText(self.settings.get("output_path"))

    def populate_settings(self):
        """Populates the settings combo box with the available settings"""
        settings = discover_settings()
        self.settings_data = {}
        self.ui.settings_CBX.clear()

        for setting in sorted(settings):
            setting_name = os.path.basename(setting).split(".")[0]
            setting_data = get_settings(setting)
            self.settings_data[setting_name] = setting_data

            self.ui.settings_CBX.addItem(setting_name)

    def save_settings(self):
        """Saves the current settings from the UI to the settings file"""
        self.settings = self.get_current_settings()

        self.settings_data[self.settings_name] = self.settings.copy()
        save_settings(self.settings, self.settings_name)

    def enable_ui(self, enable):
        for ctl in self.toggle_ctls:
            # Don't re-enable tinify key if not optimizing
            if (
                enable
                and not self.ui.opt_CHB.isChecked()
                and ctl == self.ui.key_LED
            ):
                continue

            ctl.setEnabled(enable)

    def get_current_settings(self):
        return {
            "width": self.ui.width_SPB.value(),
            "height": self.ui.height_SPB.value(),
            "framerate": self.ui.framerate_SPB.value(),
            "optimize": self.ui.opt_CHB.isChecked(),
            "tinify_key": self.ui.key_LED.text(),
            "loops": self.ui.loops_SPB.value(),
            "hold": self.ui.hold_SPB.value(),
            "output_path": self.ui.output_LED.text(),
        }

    def convert(self):
        # RESET PROGRESS
        self.reset_progress()

        # CAPTURE LATEST SETTINGS FROM UI FIRST
        current_settings = self.get_current_settings()

        # SAVE SETTINGS (using the captured settings)
        if self.ui.savesettings_CHB.isChecked():
            self.settings = current_settings
            self.settings_data[self.settings_name] = self.settings.copy()
            save_settings(self.settings, self.settings_name)

        # USE THE CAPTURED SETTINGS FOR PROCESSING
        self.settings = current_settings

        # VALIDATE SETTINGS
        errors = validate_settings(self.settings)
        if errors:
            self.show_error_dialog(errors)
            return

        # DISABLE UI
        self.enable_ui(False)

        # PROCESS
        threads = []
        self.weight = len(self.drop_widget.directories)
        for directory_wig in self.drop_widget.directories:
            thread = threading.Thread(
                target=self.process_directory,
                args=(
                    directory_wig,
                    current_settings,
                ),  # Pass settings directly
            )
            threads.append(thread)
            thread.start()

            # SET FOCUS (ON MAC NO PROGRESS IS UPDATED WITHOUT THIS)
            directory_wig.folder_LED.setFocus()

    def _play_sound(self, sound_path):
        """Play a sound file using PySide6 QSoundEffect."""
        try:
            # Convert to absolute path
            abs_path = os.path.abspath(sound_path)

            # Set the sound source
            self.sound_effect.setSource(QUrl.fromLocalFile(abs_path))

            # Set volume (optional)
            self.sound_effect.setVolume(0.5)

            # Play the sound
            self.sound_effect.play()

            LOGGER.debug(f"Playing sound: {abs_path}")

        except Exception as e:
            LOGGER.warning(f"Failed to play sound with QSoundEffect: {e}")
            # Fallback: try to log more details about the error
            LOGGER.debug(f"Sound file exists: {os.path.exists(sound_path)}")
            LOGGER.debug(f"Sound file path: {sound_path}")

    def reset_progress(self):
        self.total_progress = 0
        self.ui.progress_PBR.setValue(0)
        for directory_wig in self.drop_widget.directories:
            directory_wig.progress_PBR.setValue(0)
            directory_wig.progress_PBR.setProperty("error", 0)
            load_stylesheet(directory_wig.progress_PBR)

    def update_progress(self, progress):
        self.total_progress += progress / self.weight
        self.ui.progress_PBR.setValue(self.total_progress)

        if self.total_progress >= 100:
            self.enable_ui(True)
            # Play completion sound
            try:
                complete_path = os.path.join(
                    os.path.dirname(__file__), "audio", "complete.wav"
                )
                self._play_sound(complete_path)
            except Exception as e:
                LOGGER.warning(f"Failed to play completion sound: {e}")

    def update_directory_progress(self, progress, directory_wig):
        directory_wig.progress_PBR.setValue(progress)

    def process_directory(self, directory_wig, settings):
        processor = APNGProcessor(
            seq_dir=directory_wig.folder_LED.text(),
            settings=settings,
        )
        processor.progress_changed.connect(
            lambda progress: self.update_progress(progress)
        )
        processor.absolute_progress_changed.connect(
            lambda progress: self.update_directory_progress(
                progress, directory_wig
            )
        )
        try:
            processor.process()
        except Exception as e:
            LOGGER.error(e)
            self.failed_directory.emit(directory_wig)

    def update_failed_directory(self, wig):
        """Updates a failed directory with a full red progress bar"""
        current_progress = wig.progress_PBR.value()
        wig.progress_PBR.setValue(100)
        wig.progress_PBR.setProperty("error", 1)
        load_stylesheet(wig.progress_PBR)
        wig.progress_PBR.update()  # don't know the call to rerender the widget
        remaining_progress = 100 - current_progress
        self.update_progress(remaining_progress)

    def browse_folder(self):
        """Browses for the output folder"""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder", "/"
        )
        if folder_path:
            self.ui.output_LED.setText(folder_path)

    def show_error_dialog(self, errors):
        """Displays an error dialog to the user"""
        error_dialog = ErrorDialog(errors)
        error_dialog.show_errors()

    def show_settings_input(self):
        """Shows an input dialog for creating a preset"""
        settings_dialog = NewSettingsDialog()

        load_stylesheet(settings_dialog)
        result = settings_dialog.get_settings_name()

        if result is not None:
            self.add_new_setting(result)

        settings_dialog.close()

    def add_new_setting(self, setting_name):
        """Adds a new setting to the UI and saves the settings file"""
        # Use current UI state instead of old self.settings
        current_settings = self.get_current_settings()
        save_settings(current_settings, setting_name)
        self.settings_data[setting_name] = current_settings.copy()
        self.ui.settings_CBX.addItem(setting_name)
        index = self.ui.settings_CBX.findText(setting_name)
        self.ui.settings_CBX.setCurrentIndex(index)

    def confirm_remove_settings(self):
        """Confirms that the user wants to remove the selected settings"""
        setting = self.ui.settings_CBX.currentText()

        message = 'Do you really want to remove the "{}" settings?'.format(
            setting
        )

        confirm_dialog = ConfirmDeleteSettingsDialog(message)
        confirm = confirm_dialog.confirm()

        if confirm:
            self.remove_settings(setting)

        confirm_dialog.close()

    def remove_settings(self, setting):
        """Removes a setting from the UI and file system"""
        remove_settings(setting)
        self.settings_data.pop(setting)
        self.ui.settings_CBX.removeItem(self.ui.settings_CBX.findText(setting))


class ErrorDialog(QDialog):
    def __init__(self, errors):
        super().__init__()
        self.ui = load_ui("errors")
        self.setWindowTitle("Errors Have Ocurred")

        self.ui.errors_TED.setPlainText("\n".join(errors))
        self.ui.dismiss_BTN.clicked.connect(self.reject)
        set_icon(self.ui.error_LBL, "error", 30, 30)

        layout = QVBoxLayout()
        layout.addWidget(self.ui)
        self.setLayout(layout)

        load_stylesheet(self)

    def show_errors(self):
        result = self.exec_()
        return result


class ConfirmDeleteSettingsDialog(QDialog):
    def __init__(self, message):
        super().__init__()
        self.ui = load_ui("delete_settings")
        self.setWindowTitle("Confirm Remove Settings")

        self.ui.confirmation_LBL.setText(message)
        self.ui.dismiss_BTN.clicked.connect(self.reject)
        self.ui.confirm_BTN.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(self.ui)
        self.setLayout(layout)

        load_stylesheet(self)

    def confirm(self):
        result = self.exec_()

        if result == QDialog.Accepted:
            return True
        else:
            return None


class NewSettingsDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.ui = load_ui("settings")

        # VALIDATE INPUT
        validator = QRegularExpressionValidator(
            QRegularExpression("^[a-zA-Z0-9]{0,50}$")
        )
        self.ui.name_LED.setValidator(validator)

        layout = QVBoxLayout()
        layout.addWidget(self.ui)
        self.setLayout(layout)

        self.setWindowTitle("New Settings")

        # Connect signals to slots
        self.ui.ok_BTN.clicked.connect(self.accept)
        self.ui.cancel_BTN.clicked.connect(self.reject)

    def get_settings_name(self):
        result = self.exec_()

        if result == QDialog.Accepted:
            return self.ui.name_LED.text()
        else:
            return None


def set_icon(widget, name, width=None, height=None):
    """
    Set the icon for the provided widget with optional width and height
    """
    icon_path = os.path.join(
        PACKAGE,
        "ui",
        "icons",
        name + ".png",
    )
    icon = QIcon(icon_path)
    if width is not None and height is not None:
        icon = icon.pixmap(width, height)
    if isinstance(widget, QPushButton):
        widget.setIcon(icon)
    elif isinstance(widget, QLabel):
        pixmap = QPixmap(icon_path)
        if width is not None and height is not None:
            pixmap = pixmap.scaled(width, height)
        widget.setPixmap(pixmap)


def load_ui(ui):
    """
    Loads the provided UI file from the package's resources dir
    """
    ui_path = os.path.join(PACKAGE, "ui", ui + ".ui")

    if os.path.isfile(ui_path):
        ui_file = QFile(ui_path)
        ui_file.open(QFile.ReadOnly)

        loader = QUiLoader()
        widget = loader.load(ui_file)
        ui_file.close()

        return widget
    else:
        raise FileNotFoundError("UI file not found: {}".format(ui_path))


def load_stylesheet(widget):
    """
    Load the stylesheet.

    Returns:
        None
    """
    ui_path = os.path.join(PACKAGE, "ui")
    stylesheet_file_path = os.path.join(ui_path, "style.qss")
    with open(stylesheet_file_path, "r") as file:
        stylesheet = file.read()

    icons_path = os.path.join(ui_path, "icons").replace("\\", "/")
    stylesheet = stylesheet.replace("{icons_path}", icons_path)

    widget.setStyleSheet(stylesheet)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ApngConverter()
    window.show()
    sys.exit(app.exec())
