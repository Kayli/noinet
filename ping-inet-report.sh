#!/usr/bin/env bash

TARGET="${1:-8.8.8.8}"
MIN_FAILS="${2:-3}"
LOGFILE="./ping-$TARGET.log"

awk -v min_fails="$MIN_FAILS" '
  /^\[[0-9-]+ [0-9:]+\]/ {
    ts = $1" "$2
  }

  /no answer yet/ ||
  /Destination Host Unreachable/ ||
  /Network is unreachable/ ||
  /No route to host/ {
    fails++
    if (fails == 1) start = ts
  }

  /[0-9]+ bytes from/ {
    if (fails >= min_fails)
      print start " -> " ts " (" fails " packets lost)"
    fails = 0
  }

  END {
    if (fails >= min_fails)
      print start " -> (still down, " fails " packets lost)"
  }
' "$LOGFILE"
