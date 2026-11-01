# RaccoonOS Image Creator

This repo helps you understand how you can modify a base raspberry pi image into one used for the botball competition.

# Getting started

The only supported base is Debian Trixie (see `debian-trixie/`). Older Debian versions (Bookworm, Bullseye)
were removed because there is no base image for them anymore; they are still in the git history.

The base image the automated build starts from is described in
[debian-trixie/base-image](debian-trixie/base-image/README.md).

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

The **Build updated image** GitHub Action runs on the first of every month at 00:00 UTC
and publishes a new image only if the base image or the release of `raccoon-lib`,
`raccoon-cli`, `stm32-data-reader` or `botui` differs from the last published image
(`scripts/image-inputs-changed.py` compares them with that release's `manifest.json`);
otherwise the run ends without building. Changes to Debian packages alone do not trigger
a new image. A manual run always builds. Download `raccoon-os.img.xz` and `SHA256SUMS` from the
[image releases](https://github.com/htl-stp-ecer/raccoon-image/releases), verify the
checksum, then select **Use custom** in Raspberry Pi Imager to flash the compressed
image.

Every build starts from the **base image** described in
[debian-trixie/base-image](debian-trixie/base-image/README.md), never from an earlier
monthly build. The base image is not stored in git (about 1 GB); its SHA-256 is, and
`scripts/download-image-inputs.py` downloads it from the matching release and refuses
anything else. [HOW-IT-WAS-BUILT.md](debian-trixie/base-image/HOW-IT-WAS-BUILT.md)
documents exactly how it was made.

On top of the base image the build upgrades the OS packages and installs the latest
released `raccoon-lib` (`raccoon_library` and `raccoon_sim`), `raccoon-cli`,
`stm32-data-reader` and `botui`. It resolves the component versions once per build and
verifies GitHub's asset digests. Missing or ambiguous assets fail the build.
`manifest.json`, `packages.txt` and `python-packages.txt` record the inputs and the
installed dependencies; the image also contains them in `/etc/raccoon-image`.
Newly released component combinations are not guaranteed to have been tested together.
The mutable `bundles/dev.json` is not required.

Wired networking uses DHCP. Saved network profiles are removed, so configure Wi-Fi
after boot. SSH host keys and the machine identity are created on the first boot. The
upstream server setup runs once on first boot, which also expands the root partition and
reboots once to use the full SD card.
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

To change the base image, follow "Replacing the base image" in
[debian-trixie/base-image/README.md](debian-trixie/base-image/README.md).

To build locally on an ARM64 Linux machine with root/loop-device access, install
`gh`, Python 3.9+, `e2fsprogs`, `fdisk`, `parted`, and `xz-utils`, then run:

```bash
python3 scripts/download-image-inputs.py /tmp/raccoon-inputs
mkdir -p /tmp/raccoon-output
sudo bash scripts/build-image.sh /tmp/raccoon-inputs /tmp/raccoon-output
```

Allow enough disk space for the decompressed base image (about 5 GB), 2 GiB of update
headroom, and the compressed output. The build shrinks the final image with 512 MiB of
free filesystem space. GitHub-hosted `ubuntu-24.04-arm` runners build natively.
