#!/bin/zsh
set -euo pipefail
panel_url='http://127.0.0.1:6190/'
monitor_host="${P1_MONITOR_HOST:-p1admin@192.168.1.100}"
monitor_alias="${P1_MONITOR_HOSTKEY_ALIAS:-}"
panel_health=$(/usr/bin/curl -fsS --max-time 2 "${panel_url}health" 2>/dev/null || true)
if [[ "$panel_health" != *'"service": "p1-resource-panel"'* ]]; then
  args=(-fN -o ControlMaster=no -o ControlPath=none -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:6190:127.0.0.1:6190)
  if [[ -n "$monitor_alias" ]]; then args+=(-o "HostKeyAlias=$monitor_alias"); fi
  /usr/bin/ssh "${args[@]}" "$monitor_host"
fi
for monitor_attempt in {1..15}; do
  panel_health=$(/usr/bin/curl -fsS --max-time 2 "${panel_url}health" 2>/dev/null || true)
  if [[ "$panel_health" == *'"service": "p1-resource-panel"'* ]]; then /usr/bin/open "$panel_url"; exit 0; fi
  /bin/sleep 1
done
print '连接尚未就绪。请检查 P1 地址、SSH 登录和资源面板服务；没有更改服务器配置。'
read -r '?按回车关闭窗口'
exit 1
