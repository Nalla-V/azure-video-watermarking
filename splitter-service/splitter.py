import os
import subprocess
import logging

logger = logging.getLogger("SplitterLogic")

def split_video_into_chunks(input_path: str, output_dir: str, chunk_duration: int = 30):
    """
    Splits the input video into chunks of specified duration (in seconds).
    
    Args:
        input_path (str): Path to the input video file.
        output_dir (str): Directory where the output chunks will be saved.
        chunk_duration (int): Duration of each chunk in seconds.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found at {input_path}")

    os.makedirs(output_dir, exist_ok=True)
    output_pattern = os.path.join(output_dir, "chunk_%03d.mp4")

    command = [
    "ffmpeg",
    "-i", input_path,
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "23",
    "-c:a", "aac",
    "-b:a", "128k",
    "-f", "segment",
    "-segment_time", "15",
    "-reset_timestamps", "1",
    output_pattern
]

    logger.info("Running ffmpeg command: %s", " ".join(command))
    
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0:
        logger.error("ffmpeg failed:\n%s", result.stderr.decode())
        raise RuntimeError(f"ffmpeg failed with code {result.returncode}")
    
    logger.info("Video split successfully into chunks at %s", output_dir)
