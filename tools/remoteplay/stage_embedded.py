"""Stage the isolated embedded Python control plane and native crypto dependency."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

p = argparse.ArgumentParser()
p.add_argument("destination", type=Path)
a = p.parse_args()
repo = Path(__file__).resolve().parents[2]
source = repo / "tools/remoteplay"
root = a.destination.resolve()
rp = root / "remoteplay"
home = rp / "python"
home.mkdir(parents=True, exist_ok=True)
base = Path(sys.base_prefix)
for name in ("python313.dll", "python3.dll"):
    shutil.copy2(base / name, root / name)
for path in base.glob("vcruntime*.dll"):
    shutil.copy2(path, root / path.name)
shutil.copytree(base / "DLLs", home / "DLLs", dirs_exist_ok=True)
with zipfile.ZipFile(home / "python313.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for path in (base / "Lib").rglob("*"):
        relative = path.relative_to(base / "Lib")
        if any(
            part
            in (
                "site-packages",
                "__pycache__",
                "test",
                "tests",
                "idlelib",
                "tkinter",
                "ensurepip",
                "turtledemo",
            )
            for part in relative.parts
        ):
            continue
        if path.is_file():
            z.write(path, relative.as_posix())
site = home / "Lib/site-packages"
site.mkdir(parents=True, exist_ok=True)
venv = Path(sys.prefix) / "Lib/site-packages"
for name in ("cryptography", "google", "cffi", "pycparser"):
    if (venv / name).exists():
        shutil.copytree(
            venv / name,
            site / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "tests"),
        )
for path in venv.glob("_cffi_backend*.pyd"):
    shutil.copy2(path, site / path.name)
for pattern in (
    "cryptography-*.dist-info",
    "protobuf-*.dist-info",
    "cffi-*.dist-info",
    "pycparser-*.dist-info",
):
    for path in venv.glob(pattern):
        shutil.copytree(path, site / path.name, dirs_exist_ok=True)
modules = (
    "embedded_host",
    "installed_runtime",
    "direct_source",
    "host",
    "session",
    "takion",
    "crypto",
    "private_files",
    "native",
    "network",
    "input",
    "fec",
    "media",
    "controller_mapping",
)
for module in modules:
    shutil.copy2(source / (module + ".py"), rp / (module + ".py"))
build = rp / "build"
build.mkdir(exist_ok=True)
shutil.copy2(source / "build/takion_pb2.py", build / "takion_pb2.py")
# Recursively resolve MinGW DLL imports, never copy credentials or build outputs wholesale.
prefix = Path("C:/msys64/ucrt64/bin")
pending = [source / "build/rpcrypt.dll", prefix / "libopus-0.dll"]
seen = set()
while pending:
    path = pending.pop()
    if path.name.lower() in seen:
        continue
    seen.add(path.name.lower())
    shutil.copy2(path, build / path.name)
    output = subprocess.check_output(
        [str(prefix / "objdump.exe"), "-p", str(path)], text=True
    )
    for name in re.findall(r"DLL Name: (\S+)", output):
        if (prefix / name).is_file():
            pending.append(prefix / name)
shutil.copy2(repo / "LICENSE", rp / "LICENSE-Apollo.txt")
shutil.copy2(base / "LICENSE.txt", home / "LICENSE.txt")
print(json.dumps({"runtime": str(rp), "dlls": sorted(seen)}))

licenses = rp / "licenses"
licenses.mkdir(exist_ok=True)
chiaki = repo.parent / "chiaki-ng"
shutil.copy2(chiaki / "COPYING", licenses / "Chiaki-AGPL-3.0.txt")
shutil.copy2(
    chiaki / "LICENSES/AGPL-3.0-only-OpenSSL.txt",
    licenses / "Chiaki-OpenSSL-exception.txt",
)
for name in ("openssl", "opus"):
    path = prefix.parent / "share/licenses" / name
    if path.exists():
        shutil.copytree(path, licenses / name, dirs_exist_ok=True)
