#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
PYTHON="${INSTALL_DIR}/.venv/bin/python"
PIP="${INSTALL_DIR}/.venv/bin/pip"

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root: sudo bash scripts/deploy_ai_defense.sh" >&2; exit 1; }
[[ -x "$PYTHON" ]] || { echo "XFI Guard venv not found: $PYTHON" >&2; exit 1; }

cd "$INSTALL_DIR"

echo "=== XFI Guard: update source ==="
git fetch origin main --prune
git reset --hard origin/main

"$PIP" install --upgrade .

# Remove stale bytecode so the running interpreter cannot retain an older AI module.
find "$INSTALL_DIR/xfi_guard" -type f -name '*.pyc' -delete
find "$INSTALL_DIR/xfi_guard" -type d -name '__pycache__' -empty -delete || true

# Install the repository-owned Fail2Ban integration. The jail is deliberately
# fixed to seven days; XFI Guard submits bans through fail2ban-client.
install -d -m 0755 /etc/fail2ban/filter.d /etc/fail2ban/jail.d /var/log/xfi-guard /var/lib/xfi-guard
install -m 0644 config/fail2ban/filter.d/xfi-guard.conf /etc/fail2ban/filter.d/xfi-guard.conf
install -m 0644 config/fail2ban/jail.d/xfi-guard.conf /etc/fail2ban/jail.d/xfi-guard.conf
touch /var/log/xfi-guard/fail2ban-sync.log
chmod 0640 /var/log/xfi-guard/fail2ban-sync.log

systemctl enable --now fail2ban
fail2ban-client reload
fail2ban-client status xfi-guard

systemctl restart xfi-guard.service
systemctl restart xfi-guard-bot.service 2>/dev/null || true
sleep 2

"$PYTHON" -B - <<'PY'
from xfi_guard.ai import AIAnalyzer
from xfi_guard.routerai import RouterAIAdapter

ai = AIAnalyzer()
print("=== AI RUNTIME ===")
print("module:", __import__('xfi_guard.ai', fromlist=['']).__file__)
print("providers:", ai.available_providers())
print("routerai_enabled:", ai.routerai_enabled)
print("routerai_allow_paid:", ai.routerai_allow_paid)
print("routerai_models:", len(ai._models_for("routerai")))

if ai.routerai_key:
    adapter = RouterAIAdapter(ai.routerai_key, timeout=ai.request_timeout)
    all_models = adapter.models(force=True)
    free_models = adapter.free_models(all_models, force=True)
    ordered = adapter.ordered_models(all_models, allow_paid=ai.routerai_allow_paid)
    print("routerai_catalogue:", len(all_models))
    print("routerai_free:", len(free_models))
    print("routerai_ordered:", len(ordered))
    print("routerai_first_model:", ordered[0] if ordered else "")

print("=== AI STATUS ===")
print(ai.status())
PY

echo "=== SERVICES ==="
systemctl --no-pager --full status xfi-guard.service | head -20
systemctl --no-pager --full status xfi-guard-bot.service | head -20 || true

echo "=== DONE ==="
echo "RouterAI: free models first; paid models are fallback when routerai_allow_paid=true."
echo "Auto defense: Fail2Ban xfi-guard, bantime=7d."
