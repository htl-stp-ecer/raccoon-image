import os
import argparse
import logging
import shutil

mount_point: str = ""
root_mount_point: str = ""
default_user: str = ""


def copy_assets_to_sd_card(asset: str, destination: str):
    source_path = os.path.join("assets", asset)
    destination_path = os.path.join(mount_point, destination)
    logging.info(f"Copying {os.path.abspath(source_path)} to {os.path.abspath(destination_path)}")
    if not os.path.exists(source_path):
        logging.error(f"Asset {source_path} does not exist.")
        raise FileNotFoundError(f"Asset {source_path} not found.")
    shutil.copy2(source_path, destination_path)


def append_to_cmdline_txt():
    cmdline_path = os.path.join(mount_point, "cmdline.txt")
    logging.info(f"Checking {cmdline_path} for video parameter")
    if not os.path.exists(cmdline_path):
        logging.error(f"{cmdline_path} does not exist.")
        raise FileNotFoundError(f"{cmdline_path} not found.")
    with open(cmdline_path, "r") as cmdline_file:
        content = cmdline_file.read()
    if "video=HDMI-A-1" not in content:
        logging.info("Appending 'video=HDMI-A-1:800x480M@60D' to cmdline.txt")
        with open(cmdline_path, "a") as cmdline_file:
            cmdline_file.write(" video=HDMI-A-1:800x480M@60D")
    else:
        logging.info("video parameter already present in cmdline.txt, skipping")


def receive_partitions(boot_partition, root_partition, user):
    global mount_point, root_mount_point, default_user
    if not os.path.ismount(boot_partition):
        raise ValueError(f"{boot_partition} is not a valid mount point.")
    if not os.path.ismount(root_partition):
        raise ValueError(f"{root_partition} is not a valid mount point.")
    logging.info(f"Boot partition: {boot_partition}")
    logging.info(f"Root partition: {root_partition}")
    mount_point = boot_partition
    root_mount_point = root_partition
    default_user = user


def copy_resources_to_sd_card():
    logging.info("Copying resources to the SD card.")
    copy_assets_to_sd_card("config.txt", "config.txt")
    append_to_cmdline_txt()


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    parser = argparse.ArgumentParser(description="CLI Tool for setting up the SD card.")
    parser.add_argument('--boot_partition', type=str, required=True, help='Mount point for the boot partition')
    parser.add_argument('--root_partition', type=str, required=True, help='Mount point for the root partition')
    parser.add_argument('--default_user', type=str, required=True, help='Default user name')

    args = parser.parse_args()
    receive_partitions(args.boot_partition, args.root_partition, args.default_user)
    logging.info("Setting up the SD card.")

    copy_resources_to_sd_card()

    logging.info("Setup complete.")


if __name__ == "__main__":
    main()
