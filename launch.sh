#!/usr/bin/env bash
# Update from git, then start the viewer. Linux and macOS.
#
# The whole script is one function called on the last line: the shell parses a
# function completely before running it, so `git pull` replacing this file
# mid-run cannot make it resume at a stale byte offset. `$0` rather than
# BASH_SOURCE, and no `pipefail`, so it still behaves if run as `sh launch.sh`.
set -u

main() {
  cd "$(dirname "$0")" || exit 1

  if ! command -v git >/dev/null 2>&1; then
    printf '\n[!] Git is not installed, so this copy cannot receive updates.\n'
    printf '    Linux: install git with your package manager.\n'
    printf '    macOS: run `xcode-select --install`, or install from https://git-scm.com\n\n'
  elif [ ! -d .git ]; then
    printf '\n[!] This folder is not a Git clone, so it will never update.\n'
    printf '    Replace it with:\n'
    printf '        git clone https://github.com/ydap1/fns-viewer.git\n'
    printf '    then move data.xml into the new folder.\n\n'
  else
    echo 'Checking for updates...'
    if ! git pull --ff-only; then
      printf '\n[!] Update failed - starting the version already on disk.\n'
      printf '    Usually local edits or a diverged branch; `git status` says which.\n\n'
    fi
  fi

  if [ ! -f data.xml ]; then
    printf '\n[!] data.xml not found in %s\n' "$PWD"
    printf '    The database is not part of the repository; put it here first.\n\n'
    exit 1
  fi

  python=$(command -v python3 || command -v python) || {
    printf '\n[!] Python 3 not found. Install it and run this file again.\n\n'
    exit 1
  }
  exec "$python" viewer.py --open-browser
}

main "$@"
