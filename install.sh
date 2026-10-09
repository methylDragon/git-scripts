#!/usr/bin/env bash
set -e

if [[ $OSTYPE != "linux-gnu"* ]]; then
  echo "⚠️ Warning: This installation script has only been tested on Linux."
  echo "Proceeding anyway, but you may encounter issues."
fi

LOCAL_INSTALL=0
if [[ $1 == "--local" ]]; then
  LOCAL_INSTALL=1
fi

# Installation directories
BIN_DIR="$HOME/.local/bin"
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
COMPLETION_SRC_REL="share/bash-completion/completions/git-scripts"

if [ "$LOCAL_INSTALL" -eq 1 ]; then
  INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$INSTALL_DIR"
  echo "📦 Installing git-scripts locally from $(pwd)..."
else
  echo "📦 Installing git-scripts..."
  INSTALL_DIR="$HOME/.local/share/git-scripts"

  if [ -d "$INSTALL_DIR" ]; then
    echo "🔄 Repository already exists. Pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
  else
    echo "⬇️ Cloning repository..."
    git clone https://github.com/methylDragon/git-scripts "$INSTALL_DIR"
    cd "$INSTALL_DIR"
  fi
fi

echo "🏗️ Setting up pixi environment..."
export PATH="$HOME/.pixi/bin:$PATH"
if ! command -v pixi &>/dev/null; then
  echo "⚠️ 'pixi' not found. Installing pixi..."
  curl -fsSL https://pixi.sh/install.sh | sh
  export PATH="$HOME/.pixi/bin:$PATH"
fi

pixi install

echo "🔗 Symlinking binaries to $BIN_DIR and completions to $COMPLETION_DIR..."
mkdir -p "$BIN_DIR" "$COMPLETION_DIR"
COMPLETION_SRC="$INSTALL_DIR/$COMPLETION_SRC_REL"
for script in bin/git-*; do
  script_name=$(basename "$script")
  chmod +x "$INSTALL_DIR/$script"
  ln -sf "$INSTALL_DIR/$script" "$BIN_DIR/$script_name"
  rm -f "$HOME/.local/share/man/man1/$script_name.1"
  echo "   -> Created $script_name"
  if [ "$script_name" != "git-scripts-update" ] && [ -f "$COMPLETION_SRC" ]; then
    ln -sf "$COMPLETION_SRC" "$COMPLETION_DIR/$script_name"
  fi
done

# Ensure ~/.bash_completion sources git-scripts completion and --help wrapper eagerly
BASH_COMPLETION_USER="${BASH_COMPLETION_USER_FILE:-$HOME/.bash_completion}"
SOURCE_LINE="[ -f \"$COMPLETION_SRC\" ] && . \"$COMPLETION_SRC\""
if [ ! -f "$BASH_COMPLETION_USER" ] || ! grep -Fq "$COMPLETION_SRC" "$BASH_COMPLETION_USER"; then
  printf '\n# git-scripts completions and Rich --help wrapper\n%s\n' "$SOURCE_LINE" >>"$BASH_COMPLETION_USER"
fi

# Configure Git's man.viewer fallback so `git <cmd> --help` renders Rich/Typer help
# even in non-interactive shells while falling back to `man` for built-in Git commands.
git config --global --replace-all man.viewer git-scripts
git config --global --add man.viewer man
git config --global man.git-scripts.cmd 'sh -c '\''case "$1" in git-stack|git-prefix|git-cleanup|git-gh|git-gk|git-gk-optimize|git-evolve|git-rebase-stack|git-rebase-prefix|git-push-stack|git-push-prefix|git-prune-local|git-prune-remote-prefix|git-gh-align-pr-bases-and-sync-stacks) exec "$1" -h ;; *) exit 1 ;; esac'\'' --'

echo ""
echo "✅ Installation complete!"
echo "Make sure $BIN_DIR is in your PATH."
echo "You can now run commands like 'git stack', 'git prefix', 'git cleanup', 'git gh', and 'git gk'."
echo "To update in the future, simply run: git-scripts-update"
