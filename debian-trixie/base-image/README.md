# Base image

`raccoon-os-base.img.xz` is the Raspberry Pi OS Lite 64-bit (Trixie) image the monthly
build starts from: kernel 6.18, touchscreen overlay, `config.txt`, flutter-pi, serial
console off, no SSH host keys, `machine-id` set to `uninitialized`.

The image itself is **not stored in git** (it is about 1 GB, GitHub rejects files over
100 MB). Only its checksum lives here; the file is an asset of the release `base-2026-11-01`.
`scripts/download-image-inputs.py` downloads it from there and refuses anything whose
SHA-256 differs from `raccoon-os-base.img.xz.sha256`.

Size of the unpacked image: 5,017,923,584 bytes. The root file system is shrunk to its content plus 256 MiB; it grows to the whole card on first boot, so the image fits the 8 GB cards Botball requires.

## Replacing the base image

1. Build and test the new image, compress it to `raccoon-os-base.img.xz`.
2. Create a release with a new tag (`base-YYYY-MM-DD`) and attach the file.
3. Put the new checksum into `raccoon-os-base.img.xz.sha256` (`sha256sum raccoon-os-base.img.xz`)
   and change `BASE_TAG` in `scripts/download-image-inputs.py`.
