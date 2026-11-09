#!/bin/bash
set -u
stage=/home/opc/update_condo_20261108
deploy() {
  local service="$1" dir="$2" target="$3" source="$4" mode="$5"
  local backup="$stage/${service}.original.py" log="$stage/${service}.baseline.log"
  if ! sudo -n systemctl stop "$service"; then echo "$service STOP_FAILED"; return 1; fi
  if ! cp "$dir/$target" "$backup" || ! cp "$stage/$source" "$dir/$target"; then
    echo "$service INSTALL_FAILED"; sudo -n systemctl start "$service"; return 1
  fi
  if [ "$mode" = universal ]; then
    if [ "$service" = monitor-chaves ]; then
      MONITOR_SITE=chaves MONITOR_ONCE=1 MONITOR_REBASE=1 bash "$dir/start_monitor.sh" >"$log" 2>&1
    else
      MONITOR_SITES=rhema,multiverso,roda,proprietario MONITOR_ONCE=1 MONITOR_REBASE=1 bash "$dir/start_monitor.sh" >"$log" 2>&1
    fi
  else
    MONITOR_BASELINE_ONLY=1 bash "$dir/start_monitor.sh" >"$log" 2>&1
  fi
  local result=$?
  if [ "$result" -ne 0 ]; then
    cp "$backup" "$dir/$target"
    sudo -n systemctl start "$service"
    echo "$service BASELINE_FAILED_RESTORED"
    return 1
  fi
  if sudo -n systemctl start "$service"; then echo "$service UPDATED"; else echo "$service START_FAILED"; return 1; fi
}
deploy monitor-invista /home/opc/monitor_invista monitor_final.py monitor_invista.py normal &
deploy monitor-r3-comprar /home/opc/monitor_r3_comprar monitor.py monitor_r3.py normal &
deploy monitor-vivareal-comprar /home/opc/monitor_vivareal_comprar monitor.py monitor_vivareal.py normal &
deploy monitor-zapimoveis-ocr /home/opc/monitor_zapimoveis_ocr monitor.py monitor_zap.py normal &
deploy monitor-rhema-multiverso /home/opc/monitor_rhema_multiverso monitor_universal.py monitor_universal.py universal &
deploy monitor-chaves /home/opc/monitor_chaves monitor_universal.py monitor_universal.py universal &
wait
