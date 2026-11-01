# How the base image was built

This is the exact procedure behind `raccoon-os-base.img.xz` (2026-11-01). Follow it to
rebuild the base from scratch. Everything here is done **by hand once**; the monthly
build (`scripts/`) only adds the Raccoon components and updates on top.

What is in the base: Raspberry Pi OS Lite 64-bit (Debian Trixie), kernel 6.18, working
800x480 HDMI display and `tsc2007` touchscreen, the UART free for the STM32, build
dependencies and `flutter-pi`. What is **not** in it: any Raccoon component, any
credentials, any SSH host key, any machine identity.

Target hardware: Raspberry Pi 3 B+ in the Wombat with the 800x480 touch display.

## 1. Flash the card

Raspberry Pi Imager, **Raspberry Pi OS Lite (64-bit)**, Trixie. Use an 8 GB card, the size
Botball allows (the base was made on one). In the Imager customisation set:

- host name, user `pi`, and a password that you are willing to hand out to everybody
  (the base keeps this account),
- SSH with a public key,
- a Wi-Fi network that is **not** your home network.

Everything entered here is written to the card (`user-data`, `network-config`, cloud-init
state) and would end up in the image. Step 9 removes it again; do not enter anything you
could not publish.

## 2. First boot and update

The first start takes about five minutes with a few reboots, the display shows scan lines
meanwhile. Then, over SSH:

```
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

The kernel was `6.18.50+rpt-rpi-v8`.

## 3. Touch driver: no kernel build needed

Trixie ships `tsc2007` as an in-tree module, compressed:

```
find /lib/modules -name 'tsc2007.ko*'
# /lib/modules/6.18.50+rpt-rpi-v8/kernel/drivers/input/touchscreen/tsc2007.ko.xz
```

(Searching for `tsc2007.ko` without the `*` finds nothing because of the `.xz`.) The module
depends only on `industrialio`. A kernel build is therefore not needed. It is still checked
on every image build (`update-image-root.sh` fails if the module or the overlay is missing).

## 4. Touch overlay

The overlay source is `../assets/tsc2007-overlay.dts` (I2C address 0x48, interrupt on GPIO
25, plate resistance 300 ohm). It uses three kernel headers. Compile on any machine:

```
mkdir -p inc/dt-bindings/{interrupt-controller,gpio,pinctrl}
R=https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.12.y
curl -fL $R/include/dt-bindings/interrupt-controller/irq.h -o inc/dt-bindings/interrupt-controller/irq.h
curl -fL $R/include/dt-bindings/gpio/gpio.h               -o inc/dt-bindings/gpio/gpio.h
curl -fL $R/include/dt-bindings/pinctrl/bcm2835.h         -o inc/dt-bindings/pinctrl/bcm2835.h
cpp -nostdinc -I inc -undef -x assembler-with-cpp tsc2007-overlay.dts -o tsc2007.pp.dts
dtc -@ -I dts -O dtb -o tsc2007.dtbo tsc2007.pp.dts      # package device-tree-compiler
```

Copy `tsc2007.dtbo` to `/boot/firmware/overlays/` on the Pi. (The build used `dtc` in a
`debian:trixie-slim` container; the headers come from the 6.12 branch, which is fine
because the bindings used here are stable.) The built file had SHA-256
`807340dd...` and was verified against the one on the card.

The module must also load at boot: `/etc/modules-load.d/tsc2007.conf` exists on the card,
and `tsc2007` is listed in `/etc/modules`.

## 5. Display configuration

- `/boot/firmware/config.txt`: replaced with `../assets/config.txt` (800x480 custom HDMI
  timing, I2C and SPI on, `enable_uart=1`, `dtoverlay=pi3-disable-bt`, the `tsc2007`
  overlay, `vc4-kms-v3d`, `arm_64bit=1`). Keep a backup of the original while testing.
- `/boot/firmware/cmdline.txt` must stay **one line**. Append ` video=HDMI-A-1:800x480M@60D`
  (`../setup-image.py` does the same on a mounted card).

Reboot. The scan lines are gone and the touch works. Check with
`dmesg | grep -i tsc2007` and `sudo evtest` (touch events).

## 6. Serial port for the STM32

The STM32 hangs on the Pi's UART, so no login shell may use it:

- `enable_uart=1` and `dtoverlay=pi3-disable-bt` are in `config.txt` (step 5),
- `cmdline.txt` must **not** contain `console=serial0,115200` (remove it by hand or with
  `raspi-config` -> Interface Options -> Serial Port -> login shell: No, hardware: Yes).

## 7. Packages and `flutter-pi`

```
sudo apt install -y cmake libgl1-mesa-dev libgles2-mesa-dev libegl1-mesa-dev libdrm-dev \
  libgbm-dev fontconfig libsystemd-dev libinput-dev libudev-dev libxkbcommon-dev git \
  liblcm-dev stm32flash python3-pip evtest network-manager
```

`flutter-pi` is C code that has to be compiled; the monthly build does **not** build it
(the botui package only brings the app, not the engine), so it must be in the base:

```
cd ~ && git clone https://github.com/ardera/flutter-pi
cd flutter-pi && mkdir -p build && cd build
cmake .. && make -j2 && sudo make install      # -j2: -j4 can run a Pi 3 out of memory
cd ~ && rm -rf flutter-pi
which flutter-pi                                 # /usr/local/bin/flutter-pi
```

Reboot and test: display, touch (`sudo evtest`), `ls -l /dev/serial0`.

## 8. Passwordless sudo

`/etc/sudoers.d/pi` with the single line `pi ALL=(ALL) NOPASSWD: ALL` (mode 0440, owned by
root). The Imager's `sudo: null` setting does not create such a rule, and the CLI installer
needs it. Check the syntax with `sudo visudo -c`.

## 9. Clean up, **then do not boot the card again**

Test everything that needs the network first. After this step the card has no network
profile any more. Every boot after it refills the files below, so remove them last and
take the image right away.

```
sudo rm -f /etc/NetworkManager/system-connections/*          # Wi-Fi profiles
sudo rm -rf /var/lib/cloud/instances/* /var/lib/cloud/instance
sudo rm -f /boot/firmware/{user-data,network-config,meta-data,config.txt.orig}
sudo sed -i 's/ ds=nocloud;i=[^ ]*//' /boot/firmware/cmdline.txt   # cloud-init seed
rm -f ~/.bash_history ~/.sudo_as_admin_successful
sudo rm -f /var/cache/apt/archives/*.deb
sudo rm -f /var/lib/systemd/random-seed
sudo rm -f /var/lib/NetworkManager/{secret_key,seen-bssids,timestamps}
sudo sh -c 'rm -f /var/lib/NetworkManager/*.lease'
sudo find /var/log -type f -exec truncate -s 0 {} +
sudo rm -rf /var/log/journal/*
sudo mkdir -p -m 755 /etc/NetworkManager/system-connections    # keep the folder itself
printf 'uninitialized\n' | sudo tee /etc/machine-id
sudo sh -c 'rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub'
sudo poweroff
```

Two details that cost time:

- **`/etc/machine-id` must contain `uninitialized`**, not be empty. systemd treats a boot as
  the first boot only if the file is missing or says `uninitialized` ("If it exists and is
  empty, a boot is *not* considered the first boot"). `regenerate_ssh_host_keys.service` and
  `sshd-keygen.service` have `ConditionFirstBoot=yes`, so with an empty file they never run.
  An image with deleted host keys and a filled or empty `machine-id` then has no working
  `sshd` (this is what the October image had).
- In zsh a `rm` with a pattern that matches nothing aborts the whole command line. Wrap the
  pattern in `sh -c '...'` as above.

The systemd preset policy of the image has no `disable *`, so the services of the Raccoon
stack stay enabled across the preset run of the first boot.

## 10. Take the image

Put the card in a PC, **do not mount it writable and do not boot it**. Image the whole
drive (GNOME Disks "Create disk image" worked), compress and check:

```
xz -T0 -6 -k -v raccoon_os_base.img
xz -t raccoon_os_base.img.xz
sha256sum raccoon_os_base.img raccoon_os_base.img.xz
```

The result is the size of the whole card (7,948,206,080 bytes), because the root partition
spans the card.

## 11. Shrink it

Most of the root partition is free space. Shrinking the file system and the partition
makes the build faster and needs less disk on the runner. Work on a **copy** (unpacked
with `xz -dc`):

```
L=$(sudo losetup --find --show --partscan base.img)
sudo e2fsck -fy ${L}p2
sudo resize2fs -M ${L}p2                           # file system to its minimum
sudo dumpe2fs -h ${L}p2 | grep -E '^(Block count|Block size)'
sfdisk -d base.img                                 # note the start of partition 2
```

New partition size in sectors = blocks x block size / 512 + 524288 (256 MiB reserve).
For the 2026-11-01 base: 1,026,423 blocks of 4096 bytes -> 8,211,384 sectors + 524,288 =
8,735,672 sectors; partition 2 starts at sector 1,064,960.

```
echo 'start=1064960, size=8735672' | sudo sfdisk --force -N 2 $L
sudo partprobe $L
sudo resize2fs ${L}p2                              # grow the file system into the partition
sudo e2fsck -fn ${L}p2                             # must be clean
sudo losetup -d $L
truncate -s $(( (1064960 + 8735672) * 512 )) base.img     # 5,017,923,584 bytes
xz -T0 -6 -c base.img > raccoon-os-base.img.xz
sha256sum raccoon-os-base.img.xz > raccoon-os-base.img.xz.sha256
```

Before this step the file system on the card was 875,989 of 1,807,360 blocks used (3.6 of
6.9 GB). The compressed file stays about the same size (1.06 GB), the free space compresses
to almost nothing; the gain is the unpacked size.

## 12. Publish

See "Replacing the base image" in [README.md](README.md). The released asset is named
`raccoon-os-base.img.xz`; its SHA-256 goes into `raccoon-os-base.img.xz.sha256` in this
folder.

## What was and was not tested

Tested on the card before imaging: display, touch, UART free, `flutter-pi` installed, SSH
and passwordless sudo, and (on a Wombat running the base) installation of CLI, botui,
stm32 reader and the library.

**Not yet verified on the final, shrunk image:** that the first boot creates new SSH host
keys and a new `machine-id` (compare the key fingerprint with the old one), and that the
root partition grows on a card larger than the image (the monthly build covers this with
`raspi-config --expand-rootfs`, the bare base does not). Do both on a fresh card before
publishing a new base.
