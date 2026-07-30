#!/usr/bin/env bash
# macOS only, and only for double-clicking: Finder opens a .command file in
# Terminal, while a .sh opens in a text editor. Everything real is in launch.sh,
# which is what Linux users and anyone in a terminal should run.
cd "$(dirname "$0")" || exit 1
./launch.sh
status=$?
if [ $status -ne 0 ]; then
  printf '\nЗакройте это окно.\n'
  read -r _
fi
exit $status
