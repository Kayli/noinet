#!/bin/bash
URL="https://example.com"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$SCRIPT_DIR/internet_log.txt"
TIMEOUT=5  # timeout in seconds for each HTTP request

echo "Monitoring of internet connection started ..."

while true; do
  STATUS=$(curl -o /dev/null -s -w "%{http_code}" --max-time $TIMEOUT -L $URL)
  
  if [[ "$STATUS" =~ ^2[0-9]{2}$ ]]; then
    # HTTP 2xx is considered healthy
    sleep 5
  else
    echo "$(date '+%F %T') connection lost (HTTP $STATUS)" | tee -a "$LOGFILE"
    until [[ "$(curl -o /dev/null -s -w "%{http_code}" --max-time $TIMEOUT -L $URL)" =~ ^2[0-9]{2}$ ]]; do
      sleep 1
    done
    echo "$(date '+%F %T') connection restored" | tee -a "$LOGFILE"
  fi
done
