while true; do    
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $(curl -o /dev/null -s -w "%{http_code} in %{time_total}s" -L https://example.com)"
  sleep 1
done
