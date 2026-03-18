#!/usr/bin/env python3
"""Download azureauth release assets and repackage them as Python wheels."""

# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "zstandard"]
# ///

import hashlib
import io
import stat
import sys
import tarfile
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path

import requests  # type: ignore[import-untyped]
import zstandard  # type: ignore[import-untyped]

IMPORT_NAME = "azureauth_bin"
DIST_NAME = "azureauth_bin"
REPO = "AzureAD/microsoft-authentication-cli"

PLATFORMS = {
    "linux-x64": {
        "ext": ".deb",
        "tag": "manylinux_2_17_x86_64.manylinux2014_x86_64",
        "binary": "azureauth",
    },
    "linux-arm64": {
        "ext": ".deb",
        "tag": "manylinux_2_17_aarch64.manylinux2014_aarch64",
        "binary": "azureauth",
    },
    "osx-x64": {
        "ext": ".tar.gz",
        "tag": "macosx_12_0_x86_64",
        "binary": "azureauth",
    },
    "osx-arm64": {
        "ext": ".tar.gz",
        "tag": "macosx_12_0_arm64",
        "binary": "azureauth",
    },
    "win-x64": {
        "ext": ".zip",
        "tag": "win_amd64",
        "binary": "azureauth.exe",
    },
    "win-arm64": {
        "ext": ".zip",
        "tag": "win_arm64",
        "binary": "azureauth.exe",
    },
}


def sha256_digest(data: bytes) -> str:
    """Return url-safe base64 sha256 digest (no padding)."""
    return urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def download_asset(version: str, platform_key: str, ext: str) -> bytes:
    """Download a release asset."""
    asset_name = f"azureauth-{version}-{platform_key}{ext}"
    url = f"https://github.com/{REPO}/releases/download/{version}/{asset_name}"
    print(f"  Downloading {asset_name} ...")
    resp = requests.get(url, allow_redirects=True, timeout=300)
    resp.raise_for_status()
    return resp.content


def extract_deb(data: bytes, dest: Path) -> Path:
    """Extract data files from a .deb package (ar archive containing data.tar.*)."""
    dest.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(data)

    # ar archive magic
    magic = buf.read(8)
    if magic != b"!<arch>\n":
        raise ValueError("Not a valid ar archive")

    # Scan ar entries for data.tar.*
    data_tar = None
    while True:
        header = buf.read(60)
        if len(header) < 60:
            break
        name = header[0:16].decode("ascii").strip()
        size = int(header[48:58].decode("ascii").strip())
        content = buf.read(size)
        # Align to 2-byte boundary
        if size % 2 != 0:
            buf.read(1)

        if name.startswith("data.tar"):
            data_tar = (name, content)
            break

    if data_tar is None:
        raise ValueError("No data.tar.* found in .deb archive")

    tar_name, tar_data = data_tar
    if tar_name.endswith(".zst"):
        dctx = zstandard.ZstdDecompressor()
        tar_data = dctx.decompress(tar_data, max_output_size=512 * 1024 * 1024)
        mode = "r:"
    elif tar_name.endswith(".xz"):
        mode = "r:xz"
    elif tar_name.endswith(".gz"):
        mode = "r:gz"
    else:
        mode = "r:*"

    with tarfile.open(fileobj=io.BytesIO(tar_data), mode=mode) as tf:
        # Skip symlinks (the .deb uses symlinks like /usr/bin/azureauth -> /usr/lib/azureauth/azureauth)
        members = [m for m in tf.getmembers() if not m.issym()]
        tf.extractall(dest, members=members, filter="data")

    return dest


def extract_archive(data: bytes, ext: str, dest: Path) -> Path:
    """Extract archive and return the directory containing the files."""
    if ext == ".deb":
        return extract_deb(data, dest)
    elif ext == ".tar.gz":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            tf.extractall(dest, filter="data")
    elif ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(dest)

    # If archive has a single top-level directory, use that
    items = list(dest.iterdir())
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return dest


def _find_binary(source_dir: Path, binary_name: str) -> Path | None:
    """Find the binary in the extracted directory tree."""
    for fpath in source_dir.rglob(binary_name):
        if fpath.is_file():
            return fpath
    return None


def _is_executable(path: Path, binary_name: str) -> bool:
    """Check if a file should be marked executable in the wheel."""
    name = path.name
    if name == binary_name:
        return True
    # Shared libraries and executables without extensions
    if name.endswith((".so", ".dylib")) or "." not in name:
        return True
    return False


_EXEC_ATTR = (
    stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
) << 16
_FILE_ATTR = (stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH) << 16


def build_wheel(version: str, platform_key: str, info: dict[str, str], dist_dir: Path) -> Path:
    """Build a single platform wheel."""
    ext = info["ext"]
    platform_tag = info["tag"]
    binary_name = info["binary"]

    data = download_asset(version, platform_key, ext)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Extract archive
        source_dir = extract_archive(data, ext, tmpdir / "extracted")

        # For .deb packages, find the directory containing the binary
        # and use that as the base for collecting files
        binary_path = _find_binary(source_dir, binary_name)
        if binary_path is None:
            raise FileNotFoundError(
                f"Binary {binary_name} not found in extracted archive"
            )
        # Use the binary's parent directory as the source for files
        files_dir = binary_path.parent

        # Collect wheel entries: (arcname, data_bytes, is_executable)
        entries: list[tuple[str, bytes, bool]] = []

        # Add __init__.py
        init_py = Path(__file__).resolve().parent.parent / "python" / IMPORT_NAME / "__init__.py"
        entries.append(
            (f"{IMPORT_NAME}/__init__.py", init_py.read_bytes(), False)
        )

        # Add all files from the directory containing the binary
        for fpath in sorted(files_dir.rglob("*")):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(files_dir).as_posix()
            arcname = f"{IMPORT_NAME}/{rel}"
            executable = _is_executable(fpath, binary_name)
            entries.append((arcname, fpath.read_bytes(), executable))

        # dist-info directory
        dist_info_dir = f"{DIST_NAME}-{version}.dist-info"

        readme_path = Path(__file__).resolve().parent.parent / "README.md"
        readme_text = readme_path.read_text(encoding="utf-8")

        metadata = (
            f"Metadata-Version: 2.4\n"
            f"Name: azureauth-bin\n"
            f"Version: {version}\n"
            f"Summary: Microsoft Authentication CLI repackaged as Python wheels\n"
            f"Home-page: https://github.com/AzureAD/microsoft-authentication-cli\n"
            f"License: MIT\n"
            f"Requires-Python: >=3.9\n"
            f"Description-Content-Type: text/markdown\n"
            f"\n"
            f"{readme_text}"
        )
        entries.append((f"{dist_info_dir}/METADATA", metadata.encode(), False))

        wheel_meta = (
            f"Wheel-Version: 1.0\n"
            f"Generator: build_wheels.py\n"
            f"Root-Is-Purelib: false\n"
            f"Tag: py3-none-{platform_tag}\n"
        )
        entries.append((f"{dist_info_dir}/WHEEL", wheel_meta.encode(), False))

        entry_points = f"[console_scripts]\nazureauth = {IMPORT_NAME}:main\n"
        entries.append(
            (f"{dist_info_dir}/entry_points.txt", entry_points.encode(), False)
        )

        # Build RECORD
        records: list[str] = []
        for arcname, file_data, _ in entries:
            digest = sha256_digest(file_data)
            records.append(f"{arcname},sha256={digest},{len(file_data)}")
        records.append(f"{dist_info_dir}/RECORD,,")
        record_data = ("\n".join(records) + "\n").encode()
        entries.append((f"{dist_info_dir}/RECORD", record_data, False))

        # Write wheel zip
        wheel_name = f"{DIST_NAME}-{version}-py3-none-{platform_tag}.whl"
        wheel_path = dist_dir / wheel_name
        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as whl:
            for arcname, file_data, executable in entries:
                zi = zipfile.ZipInfo(arcname)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = _EXEC_ATTR if executable else _FILE_ATTR
                whl.writestr(zi, file_data)

        print(f"  Built {wheel_name} ({wheel_path.stat().st_size / 1024 / 1024:.1f} MB)")
        return wheel_path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>")
        print(f"Example: {sys.argv[0]} 0.9.5")
        sys.exit(1)

    version = sys.argv[1]
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)

    print(f"Building wheels for azureauth v{version}\n")

    wheels: list[Path] = []
    for platform_key, info in PLATFORMS.items():
        print(f"[{platform_key}]")
        wheel = build_wheel(version, platform_key, info, dist_dir)
        wheels.append(wheel)
        print()

    print(f"Done! {len(wheels)} wheels in {dist_dir}/")
    for w in wheels:
        print(f"  {w.name}")


if __name__ == "__main__":
    main()
