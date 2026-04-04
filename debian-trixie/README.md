# RaccoonOS for Debian Trixie

> This is a guide to install RaccoonOS on a Raspberry Pi 3 B+ with a touch display running Debian Trixie (Debian 13).
> The commands are designed to work on Ubuntu 24.04 LTS.
> This will most likely not work on Windows, as Windows can't access the SD card's root partition.

## Create the initial SD card

Use the Raspberry Pi Imager tool to create the initial SD card. Select **Raspberry Pi OS Lite 64-bit (Debian Trixie)**.
Configure the hostname, user and password. Set up the WiFi, locale and enable SSH.

### First time start

Now start the pi with the SD card — the first time start will take ~5 minutes with a few reboots. The display will have
scan lines — but don't worry, they'll get fixed in the next step.

### Run `setup-image.py`

To transfer all relevant files, run the `setup-image.py` script. This copies the needed files into the correct folders
automatically.

```bash
python3 setup-image.py --boot_partition <Boot Partition> --root_partition <Root Partition> --default_user <Default User>
```

Example (Linux):

```bash
python3 setup-image.py --boot_partition /media/tobias/bootfs --root_partition /media/tobias/rootfs --default_user pi
```

This copies `config.txt` to the boot partition and appends the video parameter to `cmdline.txt`.

## Setup touch display (Dev Machine)

### Clone Repositories

The Raspberry Pi Linux repository is fairly large and may take some time to download.

```bash
git clone --depth=1 https://github.com/raspberrypi/linux
```

### Build Kernel

```bash
cd linux
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- bcm2711_defconfig
sed -i 's/# CONFIG_TOUCHSCREEN_TSC2007 is not set/CONFIG_TOUCHSCREEN_TSC2007=m/' .config
```

### Copy TSC2007 overlay files

```bash
sudo cp ../assets/tsc2007-overlay.dts arch/arm64/boot/dts/overlays/tsc2007-overlay.dts
sudo cp ../assets/Makefile arch/arm64/boot/dts/overlays/Makefile
```

### Build and install

```bash
# Define mount point variables
MNT_BOOT="/media/tobias/bootfs"
MNT_ROOT="/media/tobias/rootfs"

sudo chmod 777 $MNT_ROOT/etc/modules
sudo echo 'tsc2007' >> $MNT_ROOT/etc/modules

# Build dtbs (adjust -j to your core count)
sudo make -j12 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image dtbs

# Copy device tree files
sudo cp arch/arm64/boot/dts/broadcom/*.dtb $MNT_BOOT/
sudo cp arch/arm64/boot/dts/overlays/*.dtb* $MNT_BOOT/overlays/
sudo cp arch/arm/boot/dts/overlays/README $MNT_BOOT/overlays/
```

# Start

Now you can start the pi and connect via SSH. The display should be fine now.

# On-Device Setup

## 1. Install Dependencies

```bash
sudo apt install cmake libgl1-mesa-dev libgles2-mesa-dev libegl1-mesa-dev libdrm-dev libgbm-dev \
  ttf-mscorefonts-installer fontconfig libsystemd-dev libinput-dev libudev-dev \
  libxkbcommon-dev git liblcm-dev
```

## 2. Install stm32flash

```bash
sudo apt update
sudo apt install stm32flash
```

## 3. Enable Serial Ports

```bash
sudo raspi-config
```
Interface Options -> Serial Port
- login shell accessible over serial? -> **NO**
- serial port hardware to be enabled? -> **YES**

## 4. Flash Firmware

Clone the firmware repo and run the deploy script:

```bash
git clone https://github.com/htl-stp-ecer/Firmware
cd Firmware
RPI_HOST=<pi-ip> bash deploy.sh
```

This compiles the latest firmware and flashes it to the STM32 on the device.

## 5. Install flutter-pi

Clone and build flutter-pi:

```bash
git clone https://github.com/ardera/flutter-pi.git
cd flutter-pi
mkdir -p build && cd build
cmake ..
make -j`nproc`
sudo make install
cd ~
rm -rf flutter-pi/
```

## 6. Deploy botui

On your **dev machine**, clone the botui repo and run its deploy script:

```bash
RPI_HOST=<pi-ip> bash deploy.sh
```

This builds and uploads the botui binaries to the pi.

Create the systemd service on the pi:

```bash
sudo nano /etc/systemd/system/flutter-ui.service
```

Paste:

```ini
[Unit]
Description=Flutter UI with flutter-pi
After=network.target

[Service]
ExecStart=flutter-pi --videomode 800x480 --release /home/pi/botui/
WorkingDirectory=/home/pi
User=pi
Group=pi
Restart=always
RestartSec=5
StandardOutput=tty
StandardError=tty

[Install]
WantedBy=multi-user.target
```

Enable & start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable flutter-ui.service
sudo systemctl start flutter-ui.service
```

## 7. Deploy stm32-data-reader

Clone the stm32 data reader repo and run its deploy script:

```bash
git clone git@github.com:htl-stp-ecer/stm32-data-reader.git
cd stm32-data-reader
RPI_HOST=<pi-ip> bash deploy.sh
```

## 8. Deploy Raccoon Toolchain

Clone and deploy the Raccoon toolchain to the pi.

## 9. Deploy BackendIDE

Clone and deploy the BackendIDE to the pi.

## 10. Install LCM Python Bindings

```bash
pip3 install lcm --break-system-packages
```

# Network Manager (for UI WiFi control)

> Make sure you test the UI before running this — doing so will remove the ability to SSH into the pi until you
> reconfigure the network.

```bash
sudo systemctl enable NetworkManager
sudo systemctl start NetworkManager
```

# Troubleshooting

## flutter-pi: Artifact not found

Caused by using a too-new Flutter version with no pre-built engine. Switch to `3.24.4`:

```bash
flutter version 3.24.4
```

Engine version lookup: https://github.com/ardera/flutter-engine-binaries-for-arm

## SSH connectivity issues

```bash
sudo ip link set dev wlp7s0 down
sudo ip link set dev wlp7s0 mtu 1400
sudo ip link set dev wlp7s0 up
```
