#!/bin/bash
# Refresh a release image on an ARM64 Linux host. Requires root and loop devices.
set -euo pipefail
[[ $EUID -eq 0 && "$(uname -m)" == aarch64 ]] || { echo 'Run as root on ARM64 Linux' >&2; exit 1; }
inputs=$(realpath "${1:?input directory}")
output=$(realpath "${2:?output directory}")
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
loop=''
cleanup() {
    local status=$?
    trap - EXIT
    if mountpoint -q "$work/root"; then
        umount -R "$work/root" || status=1
    fi
    if [[ -n "$loop" ]]; then losetup -d "$loop" || status=1; fi
    rmdir "$work/root" "$work" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT
image="$output/raccoon-os.img"
xz -dc "$inputs"/base/*.img.xz > "$image"
# Add room for updates without assuming the original partition size.
truncate -s +2G "$image"
loop=$(losetup --find --show --partscan "$image")
parted -s "$loop" resizepart 2 100%
partprobe "$loop"
udevadm settle
check_fs() {
    local status=0
    e2fsck -fy "${loop}p2" || status=$?
    [[ $status -le 1 ]]
}
check_fs
resize2fs "${loop}p2"
mkdir "$work/root"
mount "${loop}p2" "$work/root"
root="$work/root"
mount "${loop}p1" "$root/boot/firmware"
mount --bind /dev "$root/dev"
mount -t proc proc "$root/proc"
mount -t sysfs sysfs "$root/sys"
# Preserve the seed's DNS configuration and policy while configuring packages.
cp -a "$root/etc/resolv.conf" "$work/resolv.conf"
rm "$root/etc/resolv.conf"
cp /etc/resolv.conf "$root/etc/resolv.conf"
if [[ -e "$root/usr/sbin/policy-rc.d" ]]; then cp -a "$root/usr/sbin/policy-rc.d" "$work/policy-rc.d"; fi
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod +x "$root/usr/sbin/policy-rc.d"
mkdir -p "$root/tmp/image-inputs"
# Do not copy the multi-gigabyte base image into itself.
for component in raccoon-lib raccoon-cli stm32-data-reader botui manifest.json; do
    cp -a "$inputs/$component" "$root/tmp/image-inputs/"
done
cp "$script_dir/update-image-root.sh" "$root/tmp/update-image-root.sh"
chroot "$root" /bin/bash /tmp/update-image-root.sh
cp "$root/etc/raccoon-image/"*.txt "$output/"
rm "$root/etc/resolv.conf" "$root/usr/sbin/policy-rc.d"
cp -a "$work/resolv.conf" "$root/etc/resolv.conf"
if [[ -e "$work/policy-rc.d" ]]; then cp -a "$work/policy-rc.d" "$root/usr/sbin/policy-rc.d"; fi
rm -rf "$root/tmp/image-inputs" "$root/tmp/update-image-root.sh"
sync
umount -R "$root"
check_fs
# Shrink the filesystem and final partition, leaving 512 MiB for first boot.
resize2fs -M "${loop}p2"
blocks=$(dumpe2fs -h "${loop}p2" 2>/dev/null | awk '/^Block count:/ {print $3}')
block_size=$(dumpe2fs -h "${loop}p2" 2>/dev/null | awk '/^Block size:/ {print $3}')
start=$(parted -ms "$loop" unit s print | awk -F: '$1 == 2 {sub(/s$/, "", $2); print $2}')
sectors=$(( (blocks * block_size + 536870912 + 511) / 512 ))
end=$((start + sectors - 1))
# parted asks for confirmation on shrink even with -s; sfdisk is noninteractive.
printf 'start=%s, size=%s\n' "$start" "$sectors" | sfdisk --force -N 2 "$loop"
partprobe "$loop"
udevadm settle
resize2fs "${loop}p2"
check_fs
losetup -d "$loop"
loop=''
truncate -s "$(( (end + 1) * 512 ))" "$image"
xz -T2 -6 "$image"
cp "$inputs/manifest.json" "$output/manifest.json"
(cd "$output" && sha256sum raccoon-os.img.xz manifest.json packages.txt python-packages.txt > SHA256SUMS)
rm -f "$work/resolv.conf" "$work/policy-rc.d"
