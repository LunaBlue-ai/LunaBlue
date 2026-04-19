#!/usr/bin/env bash
# install.sh
# Cross-platform installation script for LunaBlue

set -e

echo "=================================================="
echo "LunaBlue Installation Script"
echo "=================================================="
echo ""

# Detect OS
OS_TYPE="$(uname -s)"
case "$OS_TYPE" in
    Linux*)     OS="Linux";;
    Darwin*)    OS="macOS";;
    MINGW*)     OS="Windows";;
    *)          OS="Unknown";;
esac

echo "Detected OS: $OS"
echo ""

# Check Node.js
echo "Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo "✗ Node.js not found. Please install from https://nodejs.org/"
    exit 1
fi
NODE_VERSION=$(node -v)
echo "✓ Node.js: $NODE_VERSION"
echo ""

# Install dependencies
echo "Installing Node.js dependencies..."
npm install
echo "✓ Dependencies installed"
echo ""

# Run setup
echo "Running setup..."
npm run setup
echo ""

echo "=================================================="
echo "✓ Installation completed successfully!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Download models: npm run setup:models"
echo "2. Build: npm run build"
echo "3. Start: npm start"
echo ""
