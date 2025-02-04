import os
import sys


def configure(settings_file):
    print("Creating 'local_settings.py' ...")
    with open(settfiles_file, "r") as f:
        lines = f.read().splitlines()

    for line in lines:
        if line[0] != '#':
            parts = [x.strip() for x in line.split("=")]
            if parts[0] == "temporary_directory_path":
                temp_dir = parts[1]
            elif parts[0] == "default_asset_type":
                def_asset = parts[1]

    with open(os.path.join(os.path.dirname(__file__), "local_settings.py"), "w") as f:
        f.write("temp_dir = \"" + temp_dir + "\"\n")
        f.write("default_asset_type = \"" + def_asset + "\"\n")

    print("... done.")
    sys.exit(0)
