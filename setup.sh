#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PLIST_SRC="$SCRIPT_DIR/com.watchhunter.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.watchhunter.agent.plist"

echo ""
echo "=============================="
echo "  WatchHunter Setup"
echo "=============================="
echo ""

# ── Step 1: Check config ───────────────────────────────────────────────────────
echo "[1/5] Checking config.json..."
CONFIG="$SCRIPT_DIR/config.json"
if [ ! -f "$CONFIG" ]; then
    echo "ERROR: config.json not found at $CONFIG"
    exit 1
fi

TOKEN=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('telegram_token',''))" 2>/dev/null || echo "")
CHAT_ID=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('telegram_chat_id',''))" 2>/dev/null || echo "")

if [[ "$TOKEN" == YOUR* ]] || [[ -z "$TOKEN" ]]; then
    echo ""
    echo "  ⚠️  You need to set your Telegram bot token first!"
    echo ""
    echo "  How to get one:"
    echo "  1. Open Telegram and search for @BotFather"
    echo "  2. Send: /newbot"
    echo "  3. Follow the prompts — you'll get a token like: 123456789:ABCdef..."
    echo "  4. Open $CONFIG and paste your token into \"telegram_token\""
    echo ""
    echo "  How to get your chat_id:"
    echo "  1. Send any message to your new bot"
    echo "  2. Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
    echo "  3. Find: \"chat\":{\"id\":XXXXXXXXX}  — that number is your chat_id"
    echo "  4. Paste it into \"telegram_chat_id\" in config.json"
    echo ""
    echo "  Then re-run: bash setup.sh"
    exit 1
fi

echo "  config.json OK (token set, chat_id: $CHAT_ID)"

# ── Step 2: Create venv ────────────────────────────────────────────────────────
echo "[2/5] Creating Python virtual environment..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    echo "  Created .venv"
else
    echo "  .venv already exists, skipping"
fi

# ── Step 3: Install dependencies ───────────────────────────────────────────────
echo "[3/5] Installing dependencies..."
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
echo "  Done (requests, beautifulsoup4, flask, feedparser)"

# ── Step 4: Install LaunchAgent ────────────────────────────────────────────────
echo "[4/5] Installing macOS LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|WATCHHUNTER_DIR|$SCRIPT_DIR|g; s|HOME_DIR|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
echo "  Installed: $PLIST_DEST"

# ── Step 5: Load LaunchAgent ───────────────────────────────────────────────────
echo "[5/5] Starting WatchHunter (launchctl)..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"
echo "  Started."

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "=============================="
echo "  Setup Complete!"
echo "=============================="
echo ""
echo "  Dashboard:  http://localhost:5000"
echo "  Logs:       $HOME/Library/Logs/watchhunter.stdout.log"
echo "  Database:   $SCRIPT_DIR/watchhunter.db"
echo ""
echo "  Useful commands:"
echo "    Stop:    launchctl unload $PLIST_DEST"
echo "    Start:   launchctl load $PLIST_DEST"
echo "    Status:  launchctl list | grep watchhunter"
echo "    Logs:    tail -f ~/Library/Logs/watchhunter.stdout.log"
echo "    Check:   cd '$SCRIPT_DIR' && .venv/bin/python3 main.py --check-now"
echo ""
echo "  Sleep note: Keep your Mac PLUGGED IN to monitor overnight."
echo "  If the lid is closed on battery, the Mac will sleep and miss listings."
echo "  Plugged in + lid open = full 24/7 coverage."
echo ""

# Open dashboard after a brief delay to let Flask start up
sleep 3
open http://localhost:5000 2>/dev/null || true
