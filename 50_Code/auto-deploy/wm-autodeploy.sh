#!/usr/bin/env bash
# World Monitor: Pull-basierter Auto-Deploy
# Prueft GitHub (Branch main). Bei neuem Commit: Dateien pruefen, Backup, einspielen,
# Dienst neu starten, Gesundheitspruefung, bei Fehler Rollback. Meldung per ntfy.
#
# Aufruf:  wm-autodeploy.sh            (normaler Lauf, vom systemd-Timer)
#          wm-autodeploy.sh --pruefen  (nur zeigen, was abweicht; nichts aendern)
#          wm-autodeploy.sh --rollback (letztes Backup zurueckspielen)
set -uo pipefail

CONF=${WM_AUTODEPLOY_CONF:-/etc/wm-autodeploy.conf}
# shellcheck source=/dev/null
source "$CONF"
STATE_DIR=${WM_STATE_DIR:-/var/lib/wm-autodeploy}
BACKUP_ROOT="$WM_DIR/_autodeploy_backup"
LOCK=${WM_LOCK:-/run/wm-autodeploy.lock}
MODUS=${1:-lauf}
mkdir -p "$STATE_DIR"

log() { echo "[$(date '+%F %T')] $*"; }

ntfy() {  # ntfy <titel> <text> <prioritaet>
  python3 - "$WM_CONFIG" "$1" "$2" "${3:-default}" <<'PY' || true
import json, sys, urllib.request
cfg, titel, text, prio = sys.argv[1:5]
try:
    p = json.load(open(cfg, encoding="utf-8")).get("push", {})
    topic = p.get("ntfy_topic")
    if not topic:
        sys.exit(0)
    srv = p.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(f"{srv}/{topic}", data=text.encode("utf-8"),
        headers={"Title": titel.encode("utf-8").decode("latin-1", "ignore"),
                 "Priority": prio, "Tags": "gear"})
    urllib.request.urlopen(req, timeout=15)
except Exception as e:
    print("ntfy-Fehler:", e, file=sys.stderr)
PY
}

exec 9>"$LOCK"
flock -n 9 || { log "Laeuft bereits"; exit 0; }

# ---- Kandidatendateien bestimmen ---------------------------------------------
kandidaten() {  # gibt Dateinamen (ohne Pfad) im SUBDIR aus, die eingespielt werden duerfen
  local src="$REPO_DIR/$SUBDIR" f name ext
  for f in "$src"/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f"); ext="${name##*.}"
    [[ " $ENDUNGEN " == *" $ext "* ]] || continue
    [[ " $GESCHUETZT " == *" $name "* ]] && continue
    echo "$name"
  done
}

geaendert() {  # Kandidaten, die sich vom Server unterscheiden
  local n
  for n in $(kandidaten); do
    cmp -s "$REPO_DIR/$SUBDIR/$n" "$WM_DIR/$n" || echo "$n"
  done
}

pruefe_dateien() {  # Syntaxpruefung im Repo-Stand
  local n f ok=0
  for n in "$@"; do
    f="$REPO_DIR/$SUBDIR/$n"
    case "$n" in
      *.py)   python3 -m py_compile "$f" 2>&1 || { log "Syntaxfehler: $n"; ok=1; } ;;
      *.json) python3 -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$f" 2>&1 || { log "JSON-Fehler: $n"; ok=1; } ;;
      *.js)   if command -v node >/dev/null; then node --check "$f" 2>&1 || { log "JS-Fehler: $n"; ok=1; }; fi ;;
    esac
  done
  find "$REPO_DIR/$SUBDIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  return $ok
}

gesund() {
  local u since="$1"
  sleep "$HEALTH_WARTEN"
  systemctl is-active --quiet "$WM_SERVICE" || { log "Dienst nicht aktiv"; return 1; }
  for u in $HEALTH_URLS; do
    curl -fsS -m 20 -o /dev/null "$u" || { log "Pruefung fehlgeschlagen: $u"; return 1; }
  done
  if journalctl -u "$WM_SERVICE" --since "$since" --no-pager 2>/dev/null | grep -q "Traceback"; then
    log "Traceback im Log seit Neustart"; return 1
  fi
  return 0
}

zurueckspielen() {  # zurueckspielen <backupordner>
  local b="$1" n
  [ -d "$b" ] || { log "Kein Backup $b"; return 1; }
  for n in $(cat "$b/.dateien"); do
    if [ -f "$b/$n" ]; then cp -p "$b/$n" "$WM_DIR/$n"; else rm -f "$WM_DIR/$n"; fi
  done
  systemctl restart "$WM_SERVICE"
}

# ---- Repo aktualisieren -------------------------------------------------------
git -C "$REPO_DIR" fetch --quiet origin "$BRANCH" || { log "git fetch fehlgeschlagen"; exit 1; }
NEU=$(git -C "$REPO_DIR" rev-parse "origin/$BRANCH")
git -C "$REPO_DIR" checkout --quiet --force --detach "$NEU"
ALT=$(cat "$STATE_DIR/deployed" 2>/dev/null || echo "")
FEHL=$(cat "$STATE_DIR/fehlgeschlagen" 2>/dev/null || echo "")

if [ "$MODUS" = "--pruefen" ]; then
  log "Repo-Stand $NEU, zuletzt eingespielt: ${ALT:-keiner}"
  for n in $(geaendert); do
    echo "=== $n ==="; diff -u "$WM_DIR/$n" "$REPO_DIR/$SUBDIR/$n" | head -40
  done
  exit 0
fi

if [ "$MODUS" = "--rollback" ]; then
  LETZT=$(ls -1d "$BACKUP_ROOT"/2* 2>/dev/null | tail -1)
  zurueckspielen "$LETZT" && log "Rollback auf $LETZT" && ntfy "World Monitor: Rollback" "Manueller Rollback auf $(basename "$LETZT")" default
  # aktuellen Stand sperren, sonst spielt der naechste Timer-Lauf ihn sofort wieder ein
  echo "$NEU" > "$STATE_DIR/fehlgeschlagen"
  exit 0
fi

[ "$NEU" = "$ALT" ] && exit 0
[ "$NEU" = "$FEHL" ] && exit 0   # derselbe fehlerhafte Stand wird nicht erneut versucht

MSG=$(git -C "$REPO_DIR" log -1 --format=%s "$NEU" | cut -c1-120)
KURZ=${NEU:0:7}
mapfile -t DATEIEN < <(geaendert)

if [ ${#DATEIEN[@]} -eq 0 ]; then
  log "Neuer Commit $KURZ ohne Aenderung am World Monitor"
  echo "$NEU" > "$STATE_DIR/deployed"; exit 0
fi
log "Neuer Stand $KURZ: ${DATEIEN[*]}"

if ! pruefe_dateien "${DATEIEN[@]}"; then
  echo "$NEU" > "$STATE_DIR/fehlgeschlagen"
  ntfy "World Monitor: Update abgelehnt" "Commit $KURZ ($MSG) hat Syntaxfehler. Nichts eingespielt, Server unveraendert." high
  exit 1
fi

# ---- Backup -----------------------------------------------------------------
TS=$(date '+%Y-%m-%d_%H%M%S')
B="$BACKUP_ROOT/${TS}_$KURZ"
mkdir -p "$B"
printf '%s\n' "${DATEIEN[@]}" > "$B/.dateien"
echo "${ALT:-unbekannt}" > "$B/.commit_vorher"
for n in "${DATEIEN[@]}"; do [ -f "$WM_DIR/$n" ] && cp -p "$WM_DIR/$n" "$B/$n"; done
ls -1d "$BACKUP_ROOT"/2* 2>/dev/null | head -n -"$BACKUPS_BEHALTEN" | xargs -r rm -rf

# ---- Einspielen + Neustart ------------------------------------------------------
for n in "${DATEIEN[@]}"; do
  install -m 0644 "$REPO_DIR/$SUBDIR/$n" "$WM_DIR/$n.neu" && mv -f "$WM_DIR/$n.neu" "$WM_DIR/$n"
done
SEIT=$(date '+%F %T')
systemctl restart "$WM_SERVICE"

if gesund "$SEIT"; then
  echo "$NEU" > "$STATE_DIR/deployed"; rm -f "$STATE_DIR/fehlgeschlagen"
  log "Eingespielt: $KURZ"
  ntfy "World Monitor: Update eingespielt" "$MSG ($KURZ). Dateien: ${DATEIEN[*]}" low
else
  log "Gesundheitspruefung fehlgeschlagen, Rollback"
  zurueckspielen "$B"
  echo "$NEU" > "$STATE_DIR/fehlgeschlagen"
  sleep 20
  if systemctl is-active --quiet "$WM_SERVICE"; then
    ntfy "World Monitor: Update fehlgeschlagen" "$MSG ($KURZ) lief nicht sauber. Alter Stand automatisch wiederhergestellt, Dienst laeuft." high
  else
    ntfy "World Monitor: STOERUNG" "$MSG ($KURZ) fehlgeschlagen, Rollback eingespielt, Dienst laeuft trotzdem nicht. Bitte pruefen." urgent
  fi
  exit 1
fi
