#!/usr/bin/env sh
set -euo pipefail

# Simple helper to build and run the development container.
# Usage: container_run.sh run|report

CONTAINER_CMD="$(command -v docker || command -v podman || true)"
IMAGE="noinet-dev:latest"
DOCKERFILE="Dockerfile.app"
PWD="$(pwd)"

if [ -z "$CONTAINER_CMD" ]; then
  echo "Please install docker or podman to build/run the container." >&2
  exit 1
fi

printf "Using %s to build container\n" "$CONTAINER_CMD"
"$CONTAINER_CMD" build -f "$DOCKERFILE" -t "$IMAGE" .

# Decide mount options and workdir (keep it simple)
MOUNT_OPTS=""
CONTAINER_WORKDIR="/app"
CMD_BASENAME="$(basename "$CONTAINER_CMD")"
if [ "$CMD_BASENAME" = "docker" ]; then
  MOUNT_OPTS="-v \"$PWD\":/workspaces/noinet"
  CONTAINER_WORKDIR="/workspaces/noinet"
elif [ "$CMD_BASENAME" = "podman" ]; then
  # On macOS podman, host filesystem mounts often require a podman machine.
  # Avoid mounting by default on Darwin to keep behavior reliable.
  if [ "$(uname -s)" = "Darwin" ]; then
    MOUNT_OPTS=""
    CONTAINER_WORKDIR="/app"
  else
    MOUNT_OPTS="--mount type=bind,source=\"$PWD\",target=/workspaces/noinet"
    CONTAINER_WORKDIR="/workspaces/noinet"
  fi
fi

run_cmd() {
  printf "Using %s to run container\n" "$CONTAINER_CMD"
  # Use sh -c to allow quoted mount options to expand cleanly
  sh -c "$CONTAINER_CMD run --rm -it --cap-add=NET_RAW $MOUNT_OPTS -w $CONTAINER_WORKDIR $IMAGE python3 -m noinet.ping_inet"
}

report_cmd() {
  printf "Using %s to run report in container\n" "$CONTAINER_CMD"
  sh -c "$CONTAINER_CMD run --rm -it $MOUNT_OPTS -w $CONTAINER_WORKDIR $IMAGE python3 -m noinet.ping_inet_report --coarse day"
}

case "${1-}" in
  run)
    run_cmd
    ;;
  report)
    report_cmd
    ;;
  *)
    echo "Usage: $0 {run|report}" >&2
    exit 2
    ;;
esac
