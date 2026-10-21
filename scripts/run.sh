#!/usr/bin/env bash
# Usage: curl -fsSL https://github.com/adunne09/judge-my-ai-habits/releases/latest/download/run.sh | bash
set -euo pipefail

# EXIT traps can run after function-local variables go out of scope on newer Bash.
download=""

main() {
  local version=${JMAIH_VERSION:-latest}
  local repository=https://github.com/adunne09/judge-my-ai-habits
  local base
  command -v python3 >/dev/null 2>&1 || { echo "Install Python 3.9+ first: https://www.python.org/downloads/" >&2; return 1; }
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ is required.")'
  command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; return 1; }
  if [[ "$version" != latest && ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]]; then
    echo "JMAIH_VERSION must be latest or a version such as v0.2.0." >&2
    return 1
  fi
  if [[ "$version" == latest ]]; then
    base="$repository/releases/latest/download"
  else
    base="$repository/releases/download/$version"
  fi
  # A mirror URL also allows offline/local release smoke tests.
  base=${JMAIH_DOWNLOAD_BASE_URL:-$base}
  download=$(mktemp -d "${TMPDIR:-/tmp}/judge-my-ai-habits-run.XXXXXX")
  trap 'rm -rf "$download"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  echo "Downloading judge-my-ai-habits ($version)…" >&2
  curl --fail --silent --show-error --location --retry 3 "$base/SHA256SUMS" -o "$download/SHA256SUMS"
  curl --fail --silent --show-error --location --retry 3 "$base/judge-my-ai-habits.tar.gz" -o "$download/judge-my-ai-habits.tar.gz"
  python3 - "$download" "$version" <<'PY'
import hashlib
import pathlib
import re
import sys
import tarfile

download = pathlib.Path(sys.argv[1]).resolve()
requested = sys.argv[2]
stage = download / "app"
stage.mkdir()
archive = download / "judge-my-ai-habits.tar.gz"
checksums = [line.split() for line in (download / "SHA256SUMS").read_text().splitlines()]
expected = [parts[0] for parts in checksums if len(parts) == 2 and parts[1] == archive.name]
if len(expected) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != expected[0]:
    sys.exit("Download checksum mismatch; run aborted. Please retry.")
names = {"judge-my-ai-habits": 0o755, "dashboard.html": 0o644, "VERSION": 0o644}
with tarfile.open(archive, "r:gz") as tar:
    members = tar.getmembers()
    if len(members) != len(names) or {m.name for m in members} != {"judge-my-ai-habits/" + n for n in names}:
        sys.exit("Unexpected release archive contents.")
    for member in members:
        if not member.isfile() or member.size > 10 * 1024 * 1024:
            sys.exit("Invalid release archive member.")
        name = member.name.split("/")[1]
        dest = stage / name
        dest.write_bytes(tar.extractfile(member).read())
        dest.chmod(names[name])
version = (stage / "VERSION").read_text().strip()
if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
    sys.exit("Invalid release version.")
if requested != "latest" and version != requested:
    sys.exit(f"Requested {requested}, but the archive contains {version}.")
print(f"Running judge-my-ai-habits {version}", file=sys.stderr)
PY
  # Forward every argument and preserve the tool's exit status. EXIT cleans up
  # the downloaded code; the tool writes results to its normal persistent path.
  python3 "$download/app/judge-my-ai-habits" "$@"
}

# Wrapping execution means curl | bash reads the whole runner before starting.
main "$@"
