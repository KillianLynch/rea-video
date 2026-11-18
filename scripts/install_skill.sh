#!/usr/bin/env bash
# Install the CLI in this checkout; register one agent only when selected.
# PYTHON_BIN=python3.12 bash scripts/install_skill.sh   # 指定解释器
set -euo pipefail
export ORT_DISABLE_TELEMETRY=1
agent=""
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != "--agent" ]; then
    echo "Usage: bash scripts/install_skill.sh [--agent codex|claude|agents]" >&2
    exit 2
  fi
  agent="$2"
  case "$agent" in codex|claude|agents) ;; *) echo "Unknown agent: $agent" >&2; exit 2 ;; esac
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---- ffmpeg ----
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "⚠ 没找到 ffmpeg / ffprobe，rea-video 跑不起来。安装：macOS 'brew install ffmpeg'，Ubuntu/Debian 'sudo apt install ffmpeg'" >&2
fi

# ---- Python >= 3.10 ----
# 依赖 onnxruntime 只给已发布的 Python 版本出预编译包；太新的解释器（如刚发布的 3.15）装不上。
# 自动选择时优先 3.10–3.14，没有才退回更新的版本。
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
py_known() { "$1" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 14)))' 2>/dev/null; }
CANDIDATES="python3 python3.14 python3.13 python3.12 python3.11 python3.10"
PY="${PYTHON_BIN:-}"
if [ -z "$PY" ]; then
  for c in $CANDIDATES; do
    if command -v "$c" >/dev/null 2>&1 && py_known "$c"; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ]; then
  for c in $CANDIDATES; do
    if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then
      PY="$c"
      echo "⚠ 只找到 $("$c" --version 2>&1)，依赖 onnxruntime 可能还没有这个版本的安装包。装不上的话装一个 3.12，再 PYTHON_BIN=python3.12 bash $0" >&2
      break
    fi
  done
fi
if [ -z "$PY" ] || ! py_ok "$PY"; then
  echo "✗ 需要 Python ≥ 3.10（当前 ${PY:-python3}: $("${PY:-python3}" --version 2>&1 || echo 未安装)）。" >&2
  echo "  macOS: brew install python@3.12；Ubuntu: sudo apt install python3.12 python3.12-venv；然后 PYTHON_BIN=python3.12 bash $0" >&2
  exit 1
fi
echo "Using $PY ($("$PY" --version 2>&1))"
install_failed() {
  echo "✗ 安装失败，见上面的输出。" >&2
  if ! py_known "$PY"; then
    echo "  $("$PY" --version 2>&1) 太新，onnxruntime 等依赖可能还没有对应的安装包。换一个 3.10–3.14 的解释器：PYTHON_BIN=python3.12 bash $0" >&2
  else
    echo "  可以换个解释器重试：PYTHON_BIN=python3.12 bash $0" >&2
  fi
  exit 1
}

# Python ≤ 3.12 上的 OCR 依赖 rapidocr-onnxruntime 会带上 opencv-python，和 rea-video 的 opencv-python-headless
# 共用 cv2 目录，后装的覆盖先装的（3.13 及以上用的 rapidocr 3 不带，下面自然跳过）。
# 只留 headless 一套：删掉 opencv-python 后强制重装 headless（删除会带走共用文件）。
dedupe_cv() {  # 参数：能跑 pip 的命令，如 python -m pip / pipx runpip rea-video
  if "$@" show opencv-python >/dev/null 2>&1; then
    "$@" uninstall -y opencv-python >/dev/null
    "$@" install --force-reinstall --no-deps "opencv-python-headless>=4.8,<5" >/dev/null
    echo "已去掉重复的 opencv-python，只保留 opencv-python-headless"
  fi
}

# Install only into this checkout's isolated environment. No global command links.
"$PY" -m venv "$ROOT/.venv" || install_failed
VENV_PY="$ROOT/.venv/bin/python"
"$VENV_PY" -m pip install -e "$ROOT[ocr]" || install_failed
dedupe_cv "$VENV_PY" -m pip

# Agent registration is opt-in and limited to one explicitly selected agent.
if [ -n "$agent" ]; then
  dir="$HOME/.$agent/skills"
  dest="$dir/rea-video"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$ROOT/skills/rea-video" ]; then
      echo "Skill already linked: $dest"
    else
      echo "Keeping existing skill at $dest; no link created." >&2
    fi
  else
    mkdir -p "$dir"
    ln -s "$ROOT/skills/rea-video" "$dest"
    echo "Linked $dest"
  fi
fi
printf 'CLI installed in %s/.venv. Activate with: source "%s/.venv/bin/activate"\n' "$ROOT" "$ROOT"
