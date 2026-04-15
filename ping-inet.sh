#!/usr/bin/env bash

TARGET="${1:-8.8.8.8}"
LOGFILE="./ping-$TARGET.log"

stdbuf -oL ping -O -i 1 -n "$TARGET" | while IFS= read -r line; do
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line"
done | tee -a "$LOGFILE"
