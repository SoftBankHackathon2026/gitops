#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
project=ghost-aws-placement-test
compose=(docker compose -p "$project" -f compose.yaml)
# Dedicated disposable volume only; mirror Kubernetes fsGroup ownership.
"${compose[@]}" create kafka
volume=$(docker inspect "$("${compose[@]}" ps -aq kafka)" --format '{{range .Mounts}}{{if eq .Destination "/tmp/aws-test-data"}}{{.Name}}{{end}}{{end}}')
test -n "$volume"
docker run --rm --user 0 --entrypoint sh -v "$volume:/data" apache/kafka:3.9.1 -c 'chown 1000:1000 /data'
trap '"${compose[@]}" down -v' EXIT
"${compose[@]}" up -d --wait --wait-timeout 360
"${compose[@]}" exec -T connect sh -c 'curl -fsS http://localhost:8083/connector-plugins'
"${compose[@]}" exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic aws_cloud_offsets
"${compose[@]}" exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic aws-placement-proof --partitions 1 --replication-factor 1
printf 'aws-placement-proof\n' | "${compose[@]}" exec -T kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic aws-placement-proof
"${compose[@]}" down
"${compose[@]}" up -d --wait --wait-timeout 360
"${compose[@]}" exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic aws-placement-proof --from-beginning --max-messages 1 --timeout-ms 30000
