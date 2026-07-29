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

# Installation directory
BIN_DIR="$HOME/.local/bin"

if [ "$LOCAL_INSTALL" -eq 1 ]; then
  echo "📦 Installing git-scripts locally from $(pwd)..."
  INSTALL_DIR="$(pwd)"
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
# Ensure pixi is installed
if ! command -v pixi &>/dev/null; then
  echo "⚠️ 'pixi' not found. Installing pixi..."
  curl -fsSL https://pixi.sh/install.sh | sh
  # Source the env to make pixi available in this script execution
  export PATH="$HOME/.pixi/bin:$PATH"
fi

pixi install

echo "🔗 Symlinking binaries to $BIN_DIR..."
mkdir -p "$BIN_DIR"
for script in bin/git-*; do
  script_name=$(basename "$script")
  ln -sf "$INSTALL_DIR/$script" "$BIN_DIR/$script_name"
  echo "   -> Created $script_name"
done

echo ""
echo "✅ Installation complete!"
echo "Make sure $BIN_DIR is in your PATH."
echo "You can now run commands like 'git rebase-prefix'."
echo "To update in the future, simply run: git-scripts-update"
