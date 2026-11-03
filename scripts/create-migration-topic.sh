#!/usr/bin/env bash
# Run once for each migration job. Does not change shared broker defaults.
set -euo pipefail
: "${KAFKA_BOOTSTRAP:?Set the reachable broker list}"
: "${TOPIC_PREFIX:?Set a unique connector topic.prefix for this migration job}"
: "${REPLICATION_FACTOR:?Set the replication factor supported by the chosen broker cluster}"
[[ "$TOPIC_PREFIX" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid TOPIC_PREFIX' >&2; exit 1; }
[[ "$REPLICATION_FACTOR" =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid REPLICATION_FACTOR' >&2; exit 1; }
topic="${TOPIC_PREFIX}.public.migration_demo"
args=(--bootstrap-server "$KAFKA_BOOTSTRAP")
if [[ -n "${KAFKA_COMMAND_CONFIG:-}" ]]; then
  args+=(--command-config "$KAFKA_COMMAND_CONFIG")
fi
kafka-topics.sh "${args[@]}" --create --if-not-exists --topic "$topic" \
  --partitions 1 --replication-factor "$REPLICATION_FACTOR"
description=$(kafka-topics.sh "${args[@]}" --describe --topic "$topic")
partitions=$(awk '/PartitionCount:/ { for (i=1;i<=NF;i++) if ($i=="PartitionCount:") print $(i+1) }' <<< "$description")
if [[ "$partitions" != 1 ]]; then
  echo "Refusing migration: $topic has PartitionCount=$partitions; expected 1. Use a fresh topic prefix." >&2
  exit 1
fi
printf '%s\n' "$description"
