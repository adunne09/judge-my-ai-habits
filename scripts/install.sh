#!/usr/bin/env bash
# Usage: curl -fsSL https://github.com/adunne09/judge-my-ai-habits/releases/latest/download/install.sh | bash
set -euo pipefail

main() {
  local version=${JMAIH_VERSION:-latest}
  local repository=https://github.com/adunne09/judge-my-ai-habits
  local base bin_dir app_dir download stage
  command -v python3 >/dev/null 2>&1 || { echo "Install Python 3.9+ first: https://www.python.org/downloads/" >&2; return 1; }
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ is required.")'
  command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; return 1; }
  if [[ "$version" != latest && ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]]; then
    echo "JMAIH_VERSION must be latest or a version such as v0.1.0." >&2
    return 1
  fi
  if [[ "$version" == latest ]]; then
    base="$repository/releases/latest/download"
  else
    base="$repository/releases/download/$version"
  fi
  # A mirror URL also allows offline/local release smoke tests.
  base=${JMAIH_DOWNLOAD_BASE_URL:-$base}
  bin_dir=${JMAIH_BIN_DIR:-$HOME/.local/bin}
  app_dir=${JMAIH_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/judge-my-ai-habits/app}
  mkdir -p "$bin_dir" "$app_dir/releases"
  bin_dir=$(cd "$bin_dir" && pwd)
  app_dir=$(cd "$app_dir" && pwd)
  download=$(mktemp -d "${TMPDIR:-/tmp}/judge-my-ai-habits-download.XXXXXX")
  stage=""
  trap 'rm -rf "$download"; if [[ -n "$stage" ]]; then rm -rf "$stage"; fi' EXIT
  echo "Downloading judge-my-ai-habits ($version)…"
  curl --fail --silent --show-error --location --retry 3 "$base/SHA256SUMS" -o "$download/SHA256SUMS"
  curl --fail --silent --show-error --location --retry 3 "$base/judge-my-ai-habits.tar.gz" -o "$download/judge-my-ai-habits.tar.gz"
  stage=$(mktemp -d "$app_dir/releases/release.XXXXXX")
  python3 - "$download" "$stage" "$bin_dir" "$app_dir" "$version" <<'PY'
import hashlib
import os
import pathlib
import re
import sys
import tarfile
import tempfile

download, stage, bin_dir, app_dir = (pathlib.Path(p).resolve() for p in sys.argv[1:5])
requested = sys.argv[5]
archive = download / "judge-my-ai-habits.tar.gz"
checksums = [line.split() for line in (download / "SHA256SUMS").read_text().splitlines()]
expected = [parts[0] for parts in checksums if len(parts) == 2 and parts[1] == archive.name]
if len(expected) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != expected[0]:
    sys.exit("Download checksum mismatch; installation aborted. Please retry.")
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
command = bin_dir / "judge-my-ai-habits"
if os.path.lexists(command):
    if not command.is_symlink() or not command.resolve().is_relative_to(app_dir / "releases"):
        sys.exit(f"{command} already exists outside this installation. Choose another JMAIH_BIN_DIR.")
# Atomically switch the command only after verifying and unpacking the release.
with tempfile.TemporaryDirectory(prefix=".judge-my-ai-habits-", dir=bin_dir) as temporary:
    link = pathlib.Path(temporary) / "command-link"
    link.symlink_to(stage / "judge-my-ai-habits")
    os.replace(link, command)
print(f"Installed judge-my-ai-habits {version} at {command}")
PY
  # Keep this release; earlier installs and the analytics database remain available.
  stage=""
  rm -rf "$download"
  trap - EXIT
  echo
  echo "Set your TypeSafe API key, then run:"
  printf '  "%s/judge-my-ai-habits"\n' "$bin_dir"
  printf '  "%s/judge-my-ai-habits" dashboard --open\n' "$bin_dir"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf '\nFor a shorter command, add this directory to PATH in your shell profile:\n  %s\n' "$bin_dir" ;;
  esac
}

# Wrapping execution means curl | bash reads the whole installer before starting.
main "$@"
