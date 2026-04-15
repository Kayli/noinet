ping -W2000 google.com | while read line; do echo "$(date '+%Y-%m-%d %H:%M:%S') $line"; done
