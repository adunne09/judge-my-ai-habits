#!/usr/bin/env bash
# Build the same portable release on macOS or Linux. No third-party dependencies.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 vMAJOR.MINOR.PATCH [output-directory]" >&2
  exit 1
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 - "$root" "$1" "${2:-$root/dist/$1}" <<'PY'
import gzip
import hashlib
import io
import pathlib
import re
import sys
import tarfile

if sys.version_info < (3, 9):
    sys.exit("Python 3.9+ is required.")
root, version, output = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
    sys.exit("Version must look like v0.2.0 or v0.2.0-rc.1.")
output.mkdir(parents=True, exist_ok=True)
if any(p.name not in {"judge-my-ai-habits.tar.gz", "run.sh", "SHA256SUMS"} for p in output.iterdir()):
    sys.exit("Output directory contains other files; choose a new output directory.")
archive = output / "judge-my-ai-habits.tar.gz"
# An explicit allowlist keeps local sessions, databases, and credentials out.
files = {
    "judge-my-ai-habits": ((root / "judge-my-ai-habits").read_bytes(), 0o755),
    "dashboard.html": ((root / "dashboard.html").read_bytes(), 0o644),
    "VERSION": ((version + "\n").encode(), 0o644),
}
# Fixed metadata makes builds reproducible for the same source and version.
with archive.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
    with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo("judge-my-ai-habits/" + name)
            info.size, info.mode, info.mtime = len(data), mode, 0
            tar.addfile(info, io.BytesIO(data))
runner = output / "run.sh"
runner.write_bytes((root / "scripts/run.sh").read_bytes())
runner.chmod(0o755)
manifest = output / "SHA256SUMS"
manifest.write_text("".join(
    f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
    for p in (archive, runner)
))
for p in (archive, runner, manifest):
    print(p.resolve())
PY
