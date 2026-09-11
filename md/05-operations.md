# 운영 안내

## 현재 서비스

작업 디렉터리 `D:\ML`, 실행 환경 `venv2\Scripts\python.exe`. NSSM 서비스 `AutoTrade_Guardian`이 `src/main_scheduler.py`를 실행한다.

`src/main_scheduler.py`는 `src.runners.stocks`로 연결하는 호환 진입점이다. 기존 서비스와 명령은 계속 사용할 수 있다. 새 구현은 `python -m src.runners.<모듈>` 방식으로 실행한다. 주식 주문·감시 실행기는 도움말 제공 여부를 확인하지 않은 채 실행하지 말고 기존 운영 절차를 따른다.

| 시각·주기(KST) | 작업 |
|---|---|
| 00:01 | 예정 작업 등록 |
| 08:45 | 사전 분석 |
| 09:15 | 오전 평가·매수 판단 |
| 15:10 | 청산 및 사후 분석 |
| 18:00 | 야간 뉴스 수집 |
| 1분 | 데몬 관리 |
| 5분 | 자체 점검 |
| 1시간 | 스케줄러 활동 기록 |

현재 감시는 약 30초 주기다. 실제 거래일·시간 조건은 스케줄러와 개별 실행기의 검사를 함께 확인한다. 예정 시각이 지났다는 사실만으로 작업 성공을 판정하지 않는다.

## 실행 모드

- `ML_EXECUTION_MODE=shadow`: 실제 자료를 읽는 주문 없는 검증. API 조회·뉴스 분석·로그·캐시 쓰기는 발생할 수 있다.
- `ML_EXECUTION_MODE=paper`: 명시적 모의 실행. 현재 별도 `data/paper_portfolio.db` 사용. 실거래 체결 품질을 입증하는 백테스트가 아니다.
- KIS 연결의 REAL/VIRTUAL은 현재 `kis_auth.py`의 `server_type` 해석을 확인한다. 과거 `virtual` 불리언 설명에 의존하지 않는다. 미지정 시 REAL 경로이므로 설정 확인 없이 매매 실행기를 실행하지 않는다.
- 인증정보는 `data/config.json`을 사용하지만 문서나 로그에 내용을 복사하지 않는다.

## 점검 명령

PowerShell, 저장소 루트에서 실행한다. 아래 명령은 매매 실행기를 호출하지 않는다.

```powershell
venv2\Scripts\python.exe -m unittest discover -s tests -q
venv2\Scripts\python.exe -m src.audit.run_daily --date 2026-09-11 --broker
venv2\Scripts\python.exe -m src.research.replay --date 2026-09-11
```

날짜는 점검 대상일로 바꾼다. `--broker`는 당일 계좌 대조에만 사용한다. 감사 종료 코드 0은 PASS/WARN, 2는 FAIL, 3은 UNKNOWN이다.

서비스 상태 확인 및 이미 승인된 재시작은 다음 스크립트를 사용한다. 재시작은 관리자 권한이 필요할 수 있다. 서비스 실행 중 스케줄러나 감시 프로세스를 중복 수동 실행하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass -File D:\ML\src\utils\register_service.ps1 -Action status
powershell -ExecutionPolicy Bypass -File D:\ML\src\utils\register_service.ps1 -Action restart
```

현재 로그: `log/guardian_service.log`, `log/guardian_service_err.log`, `log/jobs/`, `log/events/`. 감사 보고서: `docs/audit/`.

## 변경 적용 확인

감시·스케줄러에는 프로젝트/역할별 Windows 단일 실행 잠금이 있다. 종료 코드 75는 중복 잠금이다. 스케줄러는 기존 계측 감시가 남아 있으면 추가 실행하지 않으며, 정상 종료 시 소유 자식 트리를 정리한다. 감사 OP-04는 중복 수, OP-05는 최근 활동, OP-06은 현재 감시 버전을 확인한다. 기존 구버전 잔존 정리 및 실제 서비스 적용은 [수정 기록](../docs/PROCESS_LIFECYCLE_20260911.md)을 참조한다.

새 작업 프로세스와 상주 프로세스를 구분한다. 파일 저장·서비스 재시작·코드 적용·정상 판단은 서로 다른 상태다. 시작 버전과 최근 활동, 예약 작업 결과를 함께 확인한다. 과거에 종료된 작업의 버전 경고를 현재 상주 프로세스 실패로 설명하지 않는다.

실주문 여부·부분 체결·취소·미해결 상태를 확인한 후 운영 조치를 결정한다. 응답 유실을 이유로 임의 재주문하지 않는다. 코인 실행기 도입 후에도 이 원칙을 유지하고 시장별 중단·재시작을 지원한다.
