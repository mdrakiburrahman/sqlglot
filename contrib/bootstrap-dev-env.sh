#!/bin/bash
#
#
#       Sets up a dev env with all pre-reqs. This script is idempotent, it will
#       only attempt to install dependencies, if not exists.   
#
# ---------------------------------------------------------------------------------------
#

set -e
set -m

echo ""
echo "┌────────────────────────────────────┐"
echo "│ Checking for language dependencies │"
echo "└────────────────────────────────────┘"
echo ""

missing_pkgs=()

if ! command -v python &> /dev/null; then
    missing_pkgs+=(python3 python3-pip python3-dev python3-venv build-essential)
fi

if ! command -v make &> /dev/null; then
    missing_pkgs+=(make)
fi

if [ ${#missing_pkgs[@]} -ne 0 ]; then
    echo "Installing missing packages: ${missing_pkgs[*]}"
    sudo apt update
    sudo apt upgrade -y
    sudo apt install -y "${missing_pkgs[@]}"
fi

if ! command -v rustc &> /dev/null; then
    echo "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    . "$HOME/.cargo/env"
fi

echo ""
echo "┌───────────────────────────────┐"
echo "│ Installing VS Code extensions │"
echo "└───────────────────────────────┘"
echo ""

code --install-extension github.copilot
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension rust-lang.rust-analyzer
code --install-extension vadimcn.vscode-lldb

echo ""
echo "┌──────────┐"
echo "│ Versions │"
echo "└──────────┘"
echo ""

echo "Python: $(python3 --version)"
echo "Rust: $(rustc --version)"
echo "Cargo: $(cargo --version)"