#!/bin/bash
cd /opt/workdev/apps/web && pnpm build && systemctl restart workdev-api && echo "✅ Deploy concluído: https://workdev.bpfconsult.com.br"
