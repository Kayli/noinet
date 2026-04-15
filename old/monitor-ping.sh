#!/bin/bash
HOST=8.8.8.8
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$SCRIPT_DIR/internet_log.txt"
TIMEOUT=2000

while true; do
  if ping -c1 -W${TIMEOUT} $HOST >/dev/null 2>&1; then
    sleep 5
  else
    echo "$(date '+%F %T') connection lost" | tee -a "$LOGFILE"
    until ping -c1 -W${TIMEOUT} $HOST >/dev/null 2>&1; do
      sleep 1
    done
    echo "$(date '+%F %T') connection restored" | tee -a "$LOGFILE"
  fi
done
