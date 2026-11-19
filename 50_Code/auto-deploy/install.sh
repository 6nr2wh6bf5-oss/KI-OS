#!/usr/bin/env bash
# Einmalige Einrichtung des Auto-Deploy auf dem World-Monitor-Server (als root).
# Schritt 1:  bash install.sh schluessel   -> erzeugt Deploy-Key, zeigt den oeffentlichen Teil
#             (diesen in GitHub als Read-only Deploy Key eintragen, z.B. gh repo deploy-key add)
# Schritt 2:  bash install.sh einrichten   -> klont Repo, installiert Skript und Timer (Timer noch AUS)
# Schritt 3:  /opt/wm-deploy/wm-autodeploy.sh --pruefen   -> Abweichungen Server vs. main ansehen
# Schritt 4:  bash install.sh starten      -> aktuellen Stand als Basis setzen und Timer einschalten
set -euo pipefail
HIER=$(cd "$(dirname "$0")" && pwd)
D=/opt/wm-deploy
export GIT_SSH_COMMAND="ssh -i $D/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

case "${1:-}" in
  schluessel)
    mkdir -p "$D"; chmod 700 "$D"
    [ -f "$D/deploy_key" ] || ssh-keygen -t ed25519 -N "" -C "wm-autodeploy@$(hostname)" -f "$D/deploy_key"
    cat "$D/deploy_key.pub" ;;
  einrichten)
    [ -f /etc/wm-autodeploy.conf ] || { cp "$HIER/autodeploy.conf.example" /etc/wm-autodeploy.conf; echo "Bitte /etc/wm-autodeploy.conf pruefen (Dienstname, Port)"; }
    # shellcheck source=/dev/null
    source /etc/wm-autodeploy.conf
    if [ ! -d "$REPO_DIR/.git" ]; then
      git clone --quiet --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR"
      git -C "$REPO_DIR" sparse-checkout set "$SUBDIR"
      git -C "$REPO_DIR" checkout --quiet "$BRANCH"
    fi
    install -m 0755 "$HIER/wm-autodeploy.sh" "$D/wm-autodeploy.sh"
    install -m 0644 "$HIER/wm-autodeploy.service" /etc/systemd/system/
    install -m 0644 "$HIER/wm-autodeploy.timer" /etc/systemd/system/
    systemctl daemon-reload
    echo "Eingerichtet. Timer noch aus." ;;
  starten)
    source /etc/wm-autodeploy.conf
    git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
    mkdir -p /var/lib/wm-autodeploy
    if [ "${2:-}" = "--basis" ]; then
      # Server-Stand gilt als identisch mit main (nach Pruefung), kein Einspielen beim ersten Lauf
      git -C "$REPO_DIR" rev-parse "origin/$BRANCH" > /var/lib/wm-autodeploy/deployed
    fi
    systemctl enable --now wm-autodeploy.timer
    systemctl list-timers wm-autodeploy.timer --no-pager ;;
  *) echo "Aufruf: install.sh schluessel|einrichten|starten [--basis]"; exit 1 ;;
esac
