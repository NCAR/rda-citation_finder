import os
import time

from .local_settings import config


def clean_cache():
    directory = f"{config['temporary-directory-path']}/citation_cache"
    if not os.path.exists(directory):
        raise FileNotFoundError(f"cache directory {directory} does not exist")

    days_to_keep = 180
    cutoff = time.time() - (days_to_keep * 86400)
    for file in os.listdir(directory):
        file_path = os.path.join(directory, file)
        mtime = os.path.getmtime(file_path)
        if mtime < cutoff:
            os.remove(file_path)
