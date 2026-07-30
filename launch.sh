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

  case "$(uname -s)" in
    Darwin) os=macos ;;
    Linux)  os=linux ;;
    *)      os=other ;;
  esac

  if ! command -v git >/dev/null 2>&1; then
    printf '\n[!] Git is not installed, so this copy cannot receive updates.\n'
    case "$os" in
      macos) printf '    Run: xcode-select --install\n' ;;
      linux) printf '    Install git with your package manager, e.g. apt install git\n' ;;
      *)     printf '    Install git from https://git-scm.com\n' ;;
    esac
    printf '\n'
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
    printf '\n[!] Python 3 not found.\n'
    case "$os" in
      macos) printf '    Install it from https://python.org or with: brew install python\n' ;;
      linux) printf '    Install it with your package manager, e.g. apt install python3\n' ;;
      *)     printf '    Install Python 3 and run this file again.\n' ;;
    esac
    printf '\n'
    exit 1
  }
  exec "$python" viewer.py --open-browser
}

main "$@"
