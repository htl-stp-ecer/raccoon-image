# RaccoonOS Image Creator

This repo helps you understand how you can modify a base raspberry pi image into one used for the botball competition.

# Getting started

There are multiple base versions available here. Right now, these do exist:

- Debian Trixie (latest, recommended)
- Debian Bookworm
- Debian Bullseye (deprecated)

The latest and therefore recommended version is the Debian Trixie version.
The Bookworm version is still supported but will not receive new features.
The Bullseye version is deprecated and will not be updated anymore.

# Disclaimers

These steps and guides are heavily focused on you working on a Linux machine.
From my current understanding, you can't even do this on windows yet, don't know about macOS.

All steps shown here might be outdated or not functional 100%, so please be careful. If things are outdated, you can
always look at [kipr/wombat-os](https://github.com/kipr/wombat-os/tree/main). This is the repo containing the
instructions and files for the original wombat image.

# Author

Tobias Madlberger - Creator of RaccoonOS

## License

Copyright (C) 2026 Tobias Madlberger  
Licensed under the GNU General Public License v3.0 — see [COPYING](COPYING) for details.

# Automated images

The **Build updated image** GitHub Action refreshes the Trixie image on the first
of every month at 04:23 UTC. Download `raccoon-os.img.xz` and `SHA256SUMS` from the
[image releases](https://github.com/htl-stp-ecer/raccoon-image/releases), verify the
checksum, then select **Use custom** in Raspberry Pi Imager to flash the compressed
image. These are SD-card disk images (`.img.xz`), rather than bootable PC ISOs.
Automated releases do not replace the maintainer-selected **Latest** release.

The build starts from the SHA-256-pinned `v2.0.0` image, preserving the Pi kernel
configuration, touchscreen support, flutter-pi, and other device setup. It upgrades
OS packages and installs the latest published `raccoon-lib`, `raccoon-cli`,
`stm32-data-reader`, and `botui` releases. It resolves component versions once per
build and verifies GitHub's asset digests. Missing or ambiguous assets fail the
build. `manifest.json`, `packages.txt`, and `python-packages.txt` record the inputs
and installed dependencies; the image also contains these in `/etc/raccoon-image`.
The mutable `bundles/dev.json` is not required.

Wired networking uses DHCP. Saved network profiles are removed, so configure Wi-Fi
after boot. The seed's `pi` account/password are retained; SSH host keys and machine
identity are regenerated. The upstream server setup runs once on first boot, which also expands the root
partition and reboots once to use the full SD card.
Matching STM32 firmware is included in `/home/pi/flashFiles`, but CI cannot flash
the physical coprocessor. When needed, run `sudo bash flash_wombat.sh` from that
directory on the bot. Hardware boot, touchscreen, Ethernet, and firmware testing
remain necessary before competition use.

Maintainers can run **Actions → Build updated image → Run workflow** at any time.
The default builds an artifact only; enable **publish** on `main` to create a
release. Scheduled builds publish automatically only in the upstream repository.
Artifacts are retained for seven days, and published releases remain available.
A failed build never publishes an image, and uploads finish in a draft before the
release is made public. No personal access token or physical runner is required.
Pull requests touching the build run validation and an ARM64 image build without
release permissions (external contributions may require GitHub's workflow approval).

To change the hardware-tested seed, update `BASE_TAG`, `BASE_ASSET`, and
`BASE_SHA256` in `scripts/download-image-inputs.py` together. The seed must be a
64-bit Trixie image with the Raspberry Pi OS boot partition followed by an ext4
root partition and the existing `pi` user/device setup. Each refresh starts from
that seed, not a previous monthly build. Newly released component combinations
are not guaranteed to have been tested together.

To build locally on an ARM64 Linux machine with root/loop-device access, install
`gh`, Python 3.9+, `e2fsprogs`, `fdisk`, `parted`, and `xz-utils`, then run:

```bash
python3 scripts/download-image-inputs.py /tmp/raccoon-inputs
mkdir -p /tmp/raccoon-output
sudo bash scripts/build-image.sh /tmp/raccoon-inputs /tmp/raccoon-output
```

Allow enough disk space for the decompressed seed, 2 GiB of update headroom, and
the compressed output. The build shrinks the final image with 512 MiB of free
filesystem space. GitHub-hosted `ubuntu-24.04-arm` runners build natively.
