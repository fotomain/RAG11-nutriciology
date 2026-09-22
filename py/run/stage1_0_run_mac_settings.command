#!/bin/zsh
# =========================================================================
# RAG11 Nutrition — Stage 1.0: system-wide Mac file-limit fix
#
# Fixes "[Errno 35] Resource temporarily unavailable" for EVERY app on this
# Mac -- Terminal, PyCharm, Jupyter, anything -- not just processes this
# script happens to launch. It does that by permanently raising the
# system-wide open-file ceiling via a LaunchDaemon, the standard macOS
# mechanism for this. That's a system setting, so it needs admin: this
# script re-launches itself with sudo and you'll be asked for your Mac
# password.
#
# Run it once (double-click in Finder, or from Terminal:
# ./stage1_0_run_mac_settings.command). Safe to re-run -- it just
# reinstalls the same LaunchDaemon. Independent of everything else in this
# project: it doesn't touch the venv, .env, or launch Jupyter -- it only
# changes this Mac's system-wide file-descriptor limit, once, for good.
#
# What changes, system-wide, for every process, permanently (survives
# reboots): the open-file ceiling goes from macOS's default (often 256 per
# process) to 65536 (soft) / 200000 (hard).
# =========================================================================

set -e

PLIST_LABEL="limit.maxfiles"
PLIST_PATH="/Library/LaunchDaemons/${PLIST_LABEL}.plist"
SOFT_LIMIT=65536
HARD_LIMIT=200000

# Re-exec with sudo if not already root -- writing to /Library/LaunchDaemons
# and loading it into the system launchd domain both require admin.
if [ "$EUID" -ne 0 ]; then
    echo "This changes a system-wide setting, so it needs admin access."
    echo "You'll be asked for your Mac password next."
    exec sudo "$0" "$@"
fi

echo "== RAG11: installing system-wide open-file limit for all apps =="

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>launchctl</string>
        <string>limit</string>
        <string>maxfiles</string>
        <string>${SOFT_LIMIT}</string>
        <string>${HARD_LIMIT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST

chown root:wheel "$PLIST_PATH"
chmod 644 "$PLIST_PATH"
echo "Wrote ${PLIST_PATH}"

# Load it now so it applies immediately, without waiting for a reboot.
# Unload first (ignoring errors) in case this is a re-run.
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"

# Also raise the ceiling for the current login session immediately, since
# the LaunchDaemon's own effect is guaranteed from the next boot onward.
launchctl limit maxfiles "$SOFT_LIMIT" "$HARD_LIMIT" 2>/dev/null || true

echo ""
echo "Done. System-wide open-file limit is now:"
launchctl limit maxfiles
echo ""
echo "This applies to every NEW process from now on -- all apps, every"
echo "login, every reboot. If Terminal, PyCharm, or Jupyter were already"
echo "running, restart them so they pick up the new limit."
