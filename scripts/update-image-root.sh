#!/bin/bash
# Runs inside the mounted ARM64 image. Never start services in the build host.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PIP_BREAK_SYSTEM_PACKAGES=1
export PIP_ROOT_USER_ACTION=ignore
export PYTHONNOUSERSITE=1
# shellcheck disable=SC1091
. /etc/os-release
[[ "$VERSION_CODENAME" == trixie ]]
[[ "$(dpkg --print-architecture)" == arm64 ]]
id pi
apt-get update
apt-get -y -o Dpkg::Options::=--force-confold full-upgrade
# The refreshed kernel must still provide the bot's touchscreen support.
test -s /boot/firmware/overlays/tsc2007.dtbo
find /lib/modules -name 'tsc2007.ko*' -print -quit | grep -q .
apt-get install -y python3-pip network-manager
python3 -m pip install --upgrade uv
mkdir -p /tmp/raccoon-server /tmp/raccoon-reader
tar -xzf /tmp/image-inputs/raccoon-cli/*.tar.gz -C /tmp/raccoon-server
tar -xzf /tmp/image-inputs/stm32-data-reader/*.tar.gz -C /tmp/raccoon-reader
python3 -m pip install --upgrade /tmp/raccoon-server/*.whl /tmp/image-inputs/raccoon-lib/*.whl
apt-get install -y /tmp/image-inputs/botui/*.deb
install -Dm755 /tmp/raccoon-reader/stm32_data_reader /home/pi/stm32_data_reader/stm32_data_reader
install -m644 /tmp/raccoon-reader/*.service /etc/systemd/system/
# Stage the matching firmware; flashing requires the physical coprocessor.
mkdir -p /home/pi/flashFiles
for file in wombat.bin flash_wombat.sh reset_coprocessor.sh init_gpio.sh; do
    if [[ -f "/tmp/raccoon-reader/$file" ]]; then
        install -m755 "/tmp/raccoon-reader/$file" "/home/pi/flashFiles/$file"
    fi
done
chown -R pi:pi /home/pi/stm32_data_reader /home/pi/flashFiles /home/pi/stp-velox
rm -f /etc/systemd/system/iox2-janitor.service
systemctl disable iox2-janitor.service 2>/dev/null || true
mkdir -p /var/lib/systemd/linger
touch /var/lib/systemd/linger/pi
python3 - <<'PY'
from pathlib import Path
import shutil
import raccoon_cli
units = Path(raccoon_cli.__file__).parent / 'systemd'
for unit in units.glob('*.service'):
    shutil.copy2(unit, '/etc/systemd/system')
PY
systemctl enable raccoon.service flutter-ui.service stm32_data_reader.service lcm-loopback-multicast.service NetworkManager.service
# Run the upstream setup on first boot, where systemd is available.
cat > /etc/systemd/system/raccoon-image-setup.service <<'UNIT'
[Unit]
Description=Complete Raccoon image setup on first boot
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/raccoon-image-configured

[Service]
Type=oneshot
ExecStart=/usr/bin/raspi-config --expand-rootfs
ExecStart=/usr/bin/python3 -m raccoon_cli.server.cli post-install
ExecStart=/usr/bin/touch /var/lib/raccoon-image-configured
ExecStart=/usr/bin/systemctl --no-block reboot

[Install]
WantedBy=multi-user.target
UNIT
systemctl enable raccoon-image-setup.service
rm -f /var/lib/raccoon-image-configured
# A generic wired DHCP profile avoids inheriting a captured bot's MAC/IP binding.
rm -f /etc/NetworkManager/system-connections/*
cat > /etc/NetworkManager/system-connections/ethernet.nmconnection <<'PROFILE'
[connection]
id=Ethernet
uuid=f6d6b836-1543-4a31-b380-75a6223bce97
type=ethernet
autoconnect=true
[ethernet]
[ipv4]
method=auto
[ipv6]
method=auto
PROFILE
chmod 600 /etc/NetworkManager/system-connections/ethernet.nmconnection
python3 - <<'PY'
import raccoon_cli
import raccoon
import raccoon_transport
PY
ldd /home/pi/stm32_data_reader/stm32_data_reader > /tmp/reader-libraries.txt
if grep -q 'not found' /tmp/reader-libraries.txt; then
    cat /tmp/reader-libraries.txt >&2
    exit 1
fi
apt-get clean
rm -rf /var/lib/apt/lists/* /root/.cache /home/pi/.cache
# Remove machine identity and captured credentials from the public seed.
rm -f /etc/ssh/ssh_host_* /var/lib/systemd/random-seed /var/lib/dbus/machine-id
truncate -s 0 /etc/machine-id
ln -s /etc/machine-id /var/lib/dbus/machine-id
rm -rf /root/.ssh /home/pi/.ssh
rm -f /root/.*history /home/pi/.*history
find /var/log -type f -exec truncate -s 0 {} +
# Raspberry Pi OS regenerates host keys with this service on first boot.
systemctl enable regenerate_ssh_host_keys.service
mkdir -p /etc/raccoon-image
cp /tmp/image-inputs/manifest.json /etc/raccoon-image/manifest.json
dpkg-query -W > /etc/raccoon-image/packages.txt
python3 -m pip freeze > /etc/raccoon-image/python-packages.txt
rm -rf /tmp/raccoon-server /tmp/raccoon-reader /tmp/reader-libraries.txt
