# 정책 포함 왕복 검증기

사용자 승인 실제 왕복 시험을 위해 기존 live-db-cutover와 별도 이름으로 최신 이미지의 idle runner를 둔다. 배포만으로 전환하지 않는다. 기존 Secret과 워커 원장 PVC를 참조하며 비밀값은 Git에 넣지 않는다. 새 job ID policy_forward_20261107 / policy_return_20261107로 과거 완료 checkpoint를 재사용하지 않는다.

snapshot 이후/전환 후 추가 쓰기 확인은 각10건이다. 예전100건의 고정 대기를 줄이며 전체 행·필드 비교, 최종 CDC drain·쓰기 차단 검증은 그대로다. 이 수치 변경 자체가 5분 시연 성공을 뜻하지 않는다.

POLICY_OPA_URL은 운영 서비스다. CUTOVER_POLICY_EVIDENCE는 실행할 때 job별 파일로 명시한다. Mac에서 실제 AWS/API/Kubernetes 관측을 갱신해 비밀값 없는 증거만 전달하는 외부 파일 모드를 사용한다. AWS 사용자 자격증명을 runner로 복사하지 않는다. 양방향 증거·앱·DB·큐 및 동시실행 여부를 확인하기 전 run을 실행하지 않는다. 자동 큐 제어 변경은 다른 세션 개발 중이므로 이번 시험의 pause/target/resume은 기존 제어 API를 사용하고 증거에 수동 조율임을 표시한다.

원본 쓰기 차단 전 문제면 승인하지 않는다. 차단 후 문제는 실제 writer/커넥터/큐 상태를 확인해 abort 또는 복구하고 요청을 다른 DB로 이중 전달하지 않는다. 시험 후 이 runner의 replicas를 GitOps로0으로 내린다. 온프렘 기존 자원·데이터 일괄정리와 무관하다.
