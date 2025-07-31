import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import tinify
from PySide6.QtCore import QObject, Signal

from .constants import APNGASM_PATH, FFMPEG_PATH

# LOGGING
LOGGER = logging.getLogger(__name__)


def get_image_size(image_path):
    ffprobe_exe = os.path.join(FFMPEG_PATH, "ffprobe.exe")
    if os.name != "nt":  # macOS or Linux
        ffprobe_exe = ffprobe_exe.split(".exe")[0]

    ffprobe_cmd = [
        ffprobe_exe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        image_path,
    ]

    try:
        result = subprocess.check_output(ffprobe_cmd)
        data = json.loads(result)
        width = data["streams"][0]["width"]
        height = data["streams"][0]["height"]
        return int(width), int(height)
    except subprocess.CalledProcessError as e:
        LOGGER.error(e.output)
        return None
    except Exception as e:
        LOGGER.error(e)
        return None


def get_image_sequence(seq):
    """Gets all of the files in an image sequence.

    Args:
        seq (str): an image sequence name where the frame number is
            represented by a regular expression (ex. %04d)
    Returns:
        image_files (lst): a list of files making up the image sequence
    """
    frame_pattern = r"%\d+d"
    match = re.search(frame_pattern, seq)
    if match:
        frame_number_pattern = match.group(0)
    else:
        frame_number_pattern = ""

    pattern = seq.replace(frame_number_pattern, "*")

    image_files = glob.glob(pattern)
    image_files.sort()
    return image_files


def get_first_frame(file_path, number=False):
    """Returns the first frame or first frame number of a sequence.

    Assumes that there aren't multiple sequences in a directory.

    Args:
        file_path (str): a path to one of the files in a sequence.
        number (bool): whether or not to return just the frame number.
            True: returns only the number
            False: returns the entire file name
    Returns:
        first_frame_number or first_frame_file
    """
    directory, file_name = os.path.split(file_path)
    ext = file_name.split(".")[-1]

    files = sorted(glob.glob(os.path.join(directory, "*." + ext)))
    if files:
        first_frame_file = files[0]
        match = re.search(r"(\d+)(?=\.\w+$)", first_frame_file)

        if match:
            first_frame_number = int(match.group(1))
        else:
            first_frame_number = 1

        if number:
            return first_frame_number
        else:
            return first_frame_file

    else:
        return None


def resize(seq, start_frame, width, height):
    """Resizes all of the files in an image sequence.

    Args:
        seq (str): a string representing a frame of an image sequence.
        start_frame (int): the first frame of the image sequence.
        width (int): the width to resize the sequence to
        height (int): the height to resize the sequence to

    Returns:
        out (str): a string representing the resulting image sequence.
    """
    LOGGER.info(f"Resizing {seq} to {width}x{height}")
    temp_dir = tempfile.gettempdir()
    name = os.path.basename(seq).split("%")[0][:-1]
    out_dir = os.path.join(temp_dir, "apng", name)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    out = os.path.join(out_dir, os.path.basename(seq))

    ffmpeg_exe = os.path.join(FFMPEG_PATH, "ffmpeg.exe")
    if os.name != "nt":  # macOS or Linux
        ffmpeg_exe = ffmpeg_exe.split(".exe")[0]

    ffmpeg_cmd = '"{ffmpeg_exe}" -y -start_number {start_frame} -i "{seq}" -vf "scale={width}:{height}:flags=lanczos" "{out}"'.format(
        ffmpeg_exe=ffmpeg_exe,
        start_frame=start_frame,
        seq=seq,
        width=width,
        height=height,
        out=out,
    )
    LOGGER.debug(f'FFMPEG Resizing Command: "{ffmpeg_cmd}"')
    subprocess.call(ffmpeg_cmd, shell=True)

    return out


def tinify_apng(src_apng, key, overwrite=True):
    """Uses TINIFY to optimize an APNG

    Args:
        src_apng (str): a string representing the path to an APNG
    Returns:
        None
    """
    LOGGER.info(f"Optimizing {src_apng} with tinify")

    tinify.key = key

    if overwrite:
        dst_apng = src_apng
    else:
        dst_apng = src_apng.replace(".apng", "_opt.apng")

    tinify.from_file(src_apng).to_file(dst_apng)


def assemble_apng(out_filename, in_filename, framerate, loops):
    """Uses APNGASM to assemble a sequence into an APNG

    Args:
        out_filename (str): the filename of the resulting image sequence.
        in_filename (str): the name of the sequence to assemble.
        framerate (int): the frame rate of the resulting APNG
    Returns:
        None
    """
    LOGGER.info(f"Using APNGASM to assemble {in_filename} into {out_filename}")
    apngasm_exe = os.path.join(APNGASM_PATH, "apngasm64.exe")
    if os.name != "nt":  # macOS or Linux
        apngasm_exe = apngasm_exe.split("64.exe")[0]

    apngasm_cmd = '"{apngasm_exe}" "{out_filename}" "{in_filename}" 1 {framerate} -l{loops}'.format(
        apngasm_exe=apngasm_exe,
        out_filename=out_filename,
        in_filename=in_filename,
        framerate=framerate,
        loops=loops,
    )
    LOGGER.debug(f"APNGASM Command: {apngasm_cmd}")
    subprocess.call(apngasm_cmd, shell=True)


class APNGProcessor(QObject):
    progress_changed = Signal(int)  # THIS RETURNS INCREMENTAL PROGRESS
    absolute_progress_changed = Signal(int)  # THIS RETURNS AN ABSOLUTE 0-100

    def __init__(self, seq_dir, settings):
        super().__init__()

        self.seq_dir = seq_dir
        self.settings = settings
        self.temp_resized_seq = None
        self.files = []
        self.absolute_progress = 0
        self.temp_hold_file = None

    def update_progress(self, progress):
        self.absolute_progress += progress
        self.absolute_progress_changed.emit(self.absolute_progress)
        self.progress_changed.emit(progress)

    def process(self):
        self.update_progress(0)

        self.files = self._get_image_files()
        if len(self.files) < 2:
            LOGGER.error(
                f"Less than 2 files detected in {self.seq_dir}, skipping..."
            )
            raise Exception("No sequence!")
            # print(
            #     "No sequence detected in {}, skipping...".format(self.seq_dir)
            # )
            # self.update_progress(100)
            # return

        start_frame = self._get_start_frame(self.files[0])
        basename = self._get_basename(start_frame)
        self.seq = self._determine_sequence(basename, self.files)
        self.update_progress(20)

        if self.settings.get("hold"):
            LOGGER.debug(f"Applying hold of {self.settings.get('hold')} ms")
            self._hold()
        self.update_progress(20)

        out_filename = self._assemble_apng(self.seq, basename)
        self.update_progress(20)

        if self.settings.get("optimize"):
            self._optimize_apng(out_filename)
        self.update_progress(20)

        self._cleanup_temp_files()
        self.update_progress(20)
        LOGGER.info(f"Finished processing {self.seq_dir}")

    def _hold(self, index=-1):
        # handle last delay
        # apngasm looks for files with the same name as the image but with .txt extension
        # and delay string within them
        files = get_image_sequence(self.seq)
        delay_str = f"delay={self.settings.get('hold')}/1000"
        delay_file = files[index].replace(".png", ".txt")
        with open(delay_file, "w") as file:
            file.write(delay_str)
        self.temp_hold_file = delay_file

    def _get_image_files(self):
        extensions = ["png"]
        return sorted(
            [
                fn
                for fn in os.listdir(self.seq_dir)
                if any(fn.endswith(ext) for ext in extensions)
            ]
        )

    def _get_start_frame(self, filename):
        if filename.count(".") > 1:
            return filename.split(".")[-2]
        else:
            return filename.split(".")[0].split("_")[-1]

    def _get_basename(self, start_frame):
        pad = len(start_frame)
        return replace_last_occurrence(
            self.files[0], start_frame, "%0{}d".format(pad)
        )

    def _determine_sequence(self, basename, files):
        dimensions = get_image_size(os.path.join(self.seq_dir, files[0]))
        if not dimensions or (
            dimensions[0] != self.settings.get("width")
            or dimensions[1] != self.settings.get("height")
        ):
            self.temp_resized_seq = resize(
                os.path.join(self.seq_dir, basename),
                get_first_frame(os.path.join(self.seq_dir, basename), 1),
                self.settings.get("width"),
                self.settings.get("height"),
            )
            return self.temp_resized_seq
        else:
            return os.path.join(self.seq_dir, basename)

    def _assemble_apng(self, seq, basename):
        out_dir = self.settings.get("output_path")

        # If output_path is blank or empty, use the parent directory of the input sequence
        if not out_dir or out_dir.strip() == "":
            out_dir = os.path.dirname(self.seq_dir)

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        out_filename = os.path.normpath(
            os.path.join(out_dir, basename.split("%")[0][:-1] + ".png")
        )

        assemble_apng(
            out_filename,
            get_first_frame(seq),
            self.settings.get("framerate"),
            self.settings.get("loops"),
        )

        return out_filename

    def _optimize_apng(self, out_filename):
        tinify_apng(out_filename, self.settings.get("tinify_key"))

    def _cleanup_temp_files(self):
        if self.temp_hold_file:
            os.remove(self.temp_hold_file)
        if self.temp_resized_seq:
            shutil.rmtree(os.path.dirname(self.temp_resized_seq))


def get_directories_with_files(directory):
    directories = []
    for root, dirs, files in os.walk(directory):
        if files and len(files) > 1:
            directories.append(root)
    return directories


def replace_last_occurrence(input_string, old_substring, new_substring):
    parts = input_string.rsplit(old_substring, 1)
    return new_substring.join(parts)
