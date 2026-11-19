# Auto-Deploy World Monitor (ohne PC)

Stand 19.11.2026. Ziel: Updates gelangen auf den Server, ohne dass der PC laufen muss.

## Ablauf im Betrieb
| Schritt | Wer | Wo |
| --- | --- | --- |
| 1. Änderung als Pull Request (PR) | Claude | GitHub, Branch `claude/...` |
| 2. Freigabe = PR mergen | Maximilian | GitHub-App iPhone: PR öffnen › «Merge pull request» |
| 3. Server prüft alle 5 Min. `main` | Server (systemd-Timer) | `wm-autodeploy.timer` |
| 4. Syntaxprüfung, Backup, Einspielen, Neustart | Server | `/opt/wm-deploy/wm-autodeploy.sh` |
| 5. Gesundheitsprüfung (Dienst aktiv, API antwortet, kein Traceback) | Server | 45 s nach Neustart |
| 6. Meldung aufs iPhone (ntfy) | Server | Erfolg (leise) / Fehler (hoch) |

Bei Fehler: automatischer Rollback auf das Backup, derselbe Commit wird nicht erneut versucht. Ein neuer Commit auf `main` wird wieder normal geprüft.

## Was eingespielt wird
- Nur Dateien `*.py`, `*.js`, `*.json` direkt in `50_Code/world-monitor-erweiterung/`, und davon nur jene, die in den neu gemergten Commits geändert wurden. Server-Anpassungen in unberührten Dateien bleiben so erhalten.
- Nie angefasst: `server.py`, `index.html`, `config.json`, Datenordner, Schlüssel.
- Dateien, die im Repo gelöscht werden, bleiben auf dem Server (bewusst, sicherer).
- Änderungen an `server.py` oder `index.html` brauchen weiterhin einen manuellen Einbau (PC), solange diese Dateien nicht im Repo liegen.

## Einmalige Einrichtung (über den PC, Remote Control)
1. Ordner `50_Code/auto-deploy/` auf den Server kopieren, z.B. nach `/root/auto-deploy/`.
2. `bash install.sh schluessel` → öffentlichen Schlüssel als **Read-only Deploy Key** im Repo eintragen (`gh repo deploy-key add key.pub --repo 6nr2wh6bf5-oss/ki-os --title wm-server`).
3. `/etc/wm-autodeploy.conf` anpassen: Dienstname (`systemctl list-units | grep -i world`), Port der Health-URLs.
4. `bash install.sh einrichten`
5. `GIT_SSH_COMMAND="ssh -i /opt/wm-deploy/deploy_key" /opt/wm-deploy/wm-autodeploy.sh --pruefen` → Unterschiede Server vs. `main` prüfen. Hat der Server Anpassungen, die im Repo fehlen: zuerst ins Repo übernehmen.
6. `bash install.sh starten --basis`: aktueller `main` gilt als eingespielt; ab dem nächsten Merge werden nur die darin geänderten Dateien übernommen. (Ohne `--basis` spielt der erste Lauf alle Abweichungen ein, nur verwenden, wenn `main` neuer ist als der Server.)
7. Test: `systemctl start wm-autodeploy.service; journalctl -u wm-autodeploy -n 30`.

## Bedienung
| Zweck | Befehl (Server) |
| --- | --- |
| Status / letzte Läufe | `journalctl -u wm-autodeploy -n 50` |
| Was weicht ab? | `/opt/wm-deploy/wm-autodeploy.sh --pruefen` |
| Letztes Update zurücknehmen | `/opt/wm-deploy/wm-autodeploy.sh --rollback` |
| Auto-Deploy pausieren | `systemctl disable --now wm-autodeploy.timer` |
| Backups | `/opt/world-monitor/_autodeploy_backup/` (letzte 15) |

Rollback ohne PC: Den Merge in GitHub rückgängig machen («Revert» im PR) und den Revert-PR mergen. Der Server spielt den alten Stand dann automatisch ein.

## Sicherheit
- Deploy Key nur lesend und nur für dieses Repo; liegt nur auf dem Server (`/opt/wm-deploy/deploy_key`).
- Server bleibt nur via Tailscale erreichbar; keine eingehende Verbindung nötig (Server holt selbst).
- Freigabe bleibt beim Nutzer: Nur was auf `main` gemergt ist, wird eingespielt. Claude pusht nie direkt auf `main`.
