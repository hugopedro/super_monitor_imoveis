#!/bin/bash
set -e
cd /home/opc/monitor_rhema_multiverso
set -a
. /home/opc/monitor_invista/.env
set +a
exec /home/opc/monitor_r3_comprar/venv/bin/python monitor_universal.py
