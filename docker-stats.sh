#!/bin/bash

CONTAINER="website-change-monitoring-v2-webglancer-1"
LOG_FILE="docker_stats.log"

echo "TIME | CONTAINER ID   NAME                                      CPU %     MEM USAGE / LIMIT     MEM %     NET I/O        BLOCK I/O      PIDS" > "$LOG_FILE"

while true; do
    docker stats --no-stream \
        --format "$(date '+%Y-%m-%d %H:%M:%S') | {{.Container}}   {{.Name}}   {{.CPUPerc}}   {{.MemUsage}}   {{.MemPerc}}   {{.NetIO}}   {{.BlockIO}}   {{.PIDs}}" \
        "$CONTAINER" >> "$LOG_FILE"

    sleep 2
done