#!/bin/bash
set -euo pipefail
TS=$(date +%Y%m%d_%H%M%S)
DIR=/opt/backups/postgres
docker exec postgres pg_dump -U evolution -Fc workdev > "$DIR/workdev_$TS.dump"
docker exec postgres pg_dump -U evolution -Fc evolution > "$DIR/evolution_$TS.dump"
find "$DIR" -name "*.dump" -mtime +7 -delete
echo "$(date -Is) backup OK: workdev_$TS.dump + evolution_$TS.dump" >> /var/log/pg_backup.log

# --- Fase 2: replica para VPS2 ---
REMOTE="workdev@2.25.201.90"
RDIR="/home/workdev/backups/vps1-postgres"
KEY="/root/.ssh/backup_vps2"
if rsync -az -e "ssh -i $KEY -o ConnectTimeout=15" \
    "$DIR/workdev_$TS.dump" "$DIR/evolution_$TS.dump" \
    "$REMOTE:$RDIR/"; then
  ssh -i "$KEY" "$REMOTE" \
    "find $RDIR -name '*.dump' -mtime +14 -delete" || true
  echo "$(date -Is) replica VPS2 OK" >> /var/log/pg_backup.log
else
  echo "$(date -Is) ERRO replica VPS2 (backup local intacto)" >> /var/log/pg_backup.log
fi
