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
    printf '\n[!] Git не установлен, поэтому эта копия не будет обновляться.\n'
    case "$os" in
      macos) printf '    Выполните: xcode-select --install\n' ;;
      linux) printf '    Установите git через пакетный менеджер, например: apt install git\n' ;;
      *)     printf '    Установите git с https://git-scm.com\n' ;;
    esac
    printf '\n'
  elif [ ! -d .git ]; then
    printf '\n[!] Эта папка не является клоном Git, обновления приходить не будут.\n'
    printf '    Замените папку на клон:\n'
    printf '        git clone https://github.com/ydap1/fns-viewer.git\n'
    printf '    и перенесите в неё data.xml.\n\n'
  else
    echo 'Проверка обновлений...'
    if ! git pull --ff-only; then
      printf '\n[!] Обновиться не удалось — запускается версия, которая уже на диске.\n'
      printf '    Обычно причина в локальных правках или разошедшейся ветке,\n    точную покажет команда git status.\n\n'
    fi
  fi

  if [ ! -f data.xml ]; then
    printf '\n[!] Файл data.xml не найден в %s\n' "$PWD"
    printf '    База в репозиторий не входит — положите её в эту папку.\n\n'
    exit 1
  fi

  python=$(command -v python3 || command -v python) || {
    printf '\n[!] Python 3 не найден.\n'
    case "$os" in
      macos) printf '    Установите его с https://python.org или командой: brew install python\n' ;;
      linux) printf '    Установите его через пакетный менеджер, например: apt install python3\n' ;;
      *)     printf '    Установите Python 3 и запустите файл заново.\n' ;;
    esac
    printf '\n'
    exit 1
  }
  exec "$python" viewer.py --open-browser
}

main "$@"
