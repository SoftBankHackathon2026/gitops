# migration-cdc

Debezium 기반 Kafka Connect 워커 1개. PostgreSQL Source(`pgoutput`)와 JDBC Sink 플러그인이 이미지(`ghcr.io/softbankhackathon2026/migration-connect`)에 들어 있다. 온프렘 k3s `hackathon` 네임스페이스 전용이며 Argo CD Application 은 [argocd/onprem/migration-cdc.yaml](../../argocd/onprem/migration-cdc.yaml).

```
configmap.yaml    connect-distributed 설정 (환경변수). 내부 토픽·converter·config provider
deployment.yaml   Connect 워커 Deployment (replicas 1, Recreate). 비밀번호는 Secret 에서 env 로
service.yaml      REST 8083 (ClusterIP)
```

커넥터(`forward_001` Source/Sink) 등록은 매니페스트에 없다. 도구 `migration.cdc` 가 REST 로 등록하며, 설정은 Kafka 토픽 `migration-connect-configs` 에 남아 파드 재시작 후에도 이어진다.

## 선행 조건

1. Secret `migration-db-credentials` 의 `cdc_password`, `sink_password` — 만드는 법은 [migration-db-init/README.md](../migration-db-init/README.md).
2. `migration-db-init` 이 역할을 만들어 둔 상태. 워커는 DB 없이도 뜨지만 커넥터 등록은 실패한다.
3. 데이터 토픽 `forward_001.public.migration_demo` 는 파티션 1개로 미리 만든다 — [scripts/create-migration-topic.sh](../../scripts/create-migration-topic.sh) (`KAFKA_BOOTSTRAP=kafka:9092 TOPIC_PREFIX=forward_001 REPLICATION_FACTOR=2`).

## 커넥터 설정에서 비밀번호를 쓰는 법

워커에 `config.providers=env` 가 켜져 있다. 커넥터 JSON 에 값을 직접 적지 말고 환경변수를 참조한다.

```json
"database.password": "${env:MIGRATION_CDC_PASSWORD}"
"connection.password": "${env:MIGRATION_SINK_PASSWORD}"
```

허용 패턴은 `^MIGRATION_.*` 이라 다른 환경변수는 읽히지 않는다. 워커 로그와 `GET /connectors/<name>/config` 응답에는 치환 전 문자열이 그대로 남는다.

## 확인

```bash
kubectl -n hackathon get pod -l app.kubernetes.io/name=migration-connect
kubectl -n hackathon exec deploy/migration-connect -- curl -s localhost:8083/connectors
kubectl -n hackathon exec deploy/migration-connect -- curl -s localhost:8083/connector-plugins | grep -o '"class":"[^"]*"'
```

마지막 명령에 `io.debezium.connector.postgresql.PostgresConnector` 와 `io.debezium.connector.jdbc.JdbcSinkConnector` 가 보여야 한다.

## 리소스

요청 100m/768Mi, 상한 1 CPU/1.5Gi, JVM `-Xms512m -Xmx1g`. 네임스페이스 LimitRange 기본 상한(500m)보다 크므로 명시해 뒀다. 파드가 OOMKilled 되면 힙보다 상한을 먼저 의심한다 — 힙 1g 에 메타스페이스·스레드 스택이 더해진다.
