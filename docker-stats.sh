#!/bin/bash

CONTAINER="website-change-monitoring-v2-webglancer-1"

NORMAL_LOG="docker_stats.log"
JSON_LOG="docker_stats.jsonl"

INTERVAL=20

# ------------------------------------------------------------
# Get container ID
# ------------------------------------------------------------

get_container_id() {
    docker inspect --format='{{.Id}}' "$CONTAINER" 2>/dev/null | cut -c1-12
}

# ------------------------------------------------------------
# Create headers for normal log
# ------------------------------------------------------------

printf "%-19s | %-12s | %-42s | %-8s | %-25s | %-8s | %-22s | %-22s | %-6s | %-10s | %-12s\n" \
"TIME" \
"CONTAINER ID" \
"NAME" \
"CPU %" \
"MEM USAGE / LIMIT" \
"MEM %" \
"NET I/O" \
"BLOCK I/O" \
"PIDS" \
"STATUS" \
"RESTARTS" > "$NORMAL_LOG"

# ------------------------------------------------------------
# Monitoring loop
# ------------------------------------------------------------

while true; do

    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    CONTAINER_ID=$(get_container_id)

    # Check whether container exists
    if [ -z "$CONTAINER_ID" ]; then

        printf "%s | ERROR: Container %s not found\n" \
            "$TIMESTAMP" "$CONTAINER" >> "$NORMAL_LOG"

        printf '{"timestamp":"%s","container":"%s","error":"container_not_found"}\n' \
            "$TIMESTAMP" "$CONTAINER" >> "$JSON_LOG"

        sleep "$INTERVAL"
        continue
    fi

    # --------------------------------------------------------
    # Docker resource statistics
    # --------------------------------------------------------

    STATS=$(docker stats --no-stream \
        --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}' \
        "$CONTAINER" 2>/dev/null)

    if [ -z "$STATS" ]; then

        printf "%s | ERROR: Unable to retrieve Docker statistics\n" \
            "$TIMESTAMP" >> "$NORMAL_LOG"

        printf '{"timestamp":"%s","container_id":"%s","container":"%s","error":"stats_unavailable"}\n' \
            "$TIMESTAMP" "$CONTAINER_ID" "$CONTAINER" >> "$JSON_LOG"

        sleep "$INTERVAL"
        continue
    fi

    # --------------------------------------------------------
    # Parse Docker statistics
    # --------------------------------------------------------

    IFS='|' read -r CPU MEM_USAGE MEM_PERCENT NET_IO BLOCK_IO PIDS <<< "$STATS"

    # --------------------------------------------------------
    # Container state information
    # --------------------------------------------------------

    STATUS=$(docker inspect \
        --format='{{.State.Status}}' \
        "$CONTAINER" 2>/dev/null)

    RESTARTS=$(docker inspect \
        --format='{{.RestartCount}}' \
        "$CONTAINER" 2>/dev/null)

    OOM_KILLED=$(docker inspect \
        --format='{{.State.OOMKilled}}' \
        "$CONTAINER" 2>/dev/null)

    # --------------------------------------------------------
    # Normal human-readable log
    # --------------------------------------------------------

    printf "%-19s | %-12s | %-42s | %-8s | %-25s | %-8s | %-22s | %-22s | %-6s | %-10s | %-12s\n" \
        "$TIMESTAMP" \
        "$CONTAINER_ID" \
        "$CONTAINER" \
        "$CPU" \
        "$MEM_USAGE" \
        "$MEM_PERCENT" \
        "$NET_IO" \
        "$BLOCK_IO" \
        "$PIDS" \
        "$STATUS" \
        "$RESTARTS" >> "$NORMAL_LOG"

    # --------------------------------------------------------
    # JSON Lines log
    # --------------------------------------------------------

    printf '{"timestamp":"%s","container_id":"%s","container_name":"%s","cpu_percent":"%s","memory_usage":"%s","memory_percent":"%s","network_io":"%s","block_io":"%s","pids":%s,"status":"%s","restart_count":%s,"oom_killed":%s}\n' \
        "$TIMESTAMP" \
        "$CONTAINER_ID" \
        "$CONTAINER" \
        "$CPU" \
        "$MEM_USAGE" \
        "$MEM_PERCENT" \
        "$NET_IO" \
        "$BLOCK_IO" \
        "$PIDS" \
        "$STATUS" \
        "$RESTARTS" \
        "$OOM_KILLED" >> "$JSON_LOG"

    sleep "$INTERVAL"

done
