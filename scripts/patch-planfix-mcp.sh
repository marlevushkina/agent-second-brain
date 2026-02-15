#!/bin/bash
# Patch @popstas/planfix-mcp-server
# Fixes: .planfix.com → .planfix.ru for Russian Planfix accounts
#
# Run on VPS:  bash scripts/patch-planfix-mcp.sh
# Revert:      npm install -g @popstas/planfix-mcp-server

set -euo pipefail

MCP_DIR=$(dirname "$(readlink -f "$(which planfix-mcp-server)")")/..
DIST="$MCP_DIR/dist"

if [ ! -f "$DIST/config.js" ]; then
    echo "ERROR: MCP package not found. Install first:"
    echo "  npm install -g @popstas/planfix-mcp-server"
    exit 1
fi

echo "Patching Planfix MCP at: $DIST"
echo "Version: $(node -e "console.log(require('$MCP_DIR/package.json').version)")"

# Backup original
if [ ! -f "$DIST/config.js.orig" ]; then
    cp "$DIST/config.js" "$DIST/config.js.orig"
    echo "  Backed up config.js -> config.js.orig"
fi

# Patch: .planfix.com → .planfix.ru
sed -i 's/\.planfix\.com/\.planfix\.ru/g' "$DIST/config.js"
echo "  Patched config.js: .planfix.com → .planfix.ru"

# Verify
if grep -q 'planfix.ru' "$DIST/config.js"; then
    echo ""
    echo "Done! Restart the MCP server or bot to apply changes."
    echo "  systemctl restart d-brain"
else
    echo "ERROR: Patch verification failed!"
    exit 1
fi
