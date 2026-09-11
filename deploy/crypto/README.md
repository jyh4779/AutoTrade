# Ubuntu 코인 전용 배포

현재 Windows 코인 실행은 사용자 요청으로 중단됐다. 자동으로 다시 시작하지 않는다. 주식 서비스는 이 패키지와 별개다.

## 패키지

저장소에서 `python deploy/crypto/build.py`를 실행하면 `dist/crypto-ubuntu.zip`을 생성한다. 허용 목록의 코인·공통 코드와 배포 도구만 포함하며 데이터·인증정보·KIS·Ollama는 포함하지 않는다. 패키지 내 manifest.json은 파일 SHA-256 목록이다.

Ubuntu 24.04/Python 3.12를 설치 대상으로 한다. 서버 접속·실제 systemd 재부팅 검증은 아직 수행하지 않았다.

```bash
sudo apt-get update
sudo apt-get install python3-venv unzip
unzip crypto-ubuntu.zip -d crypto-package
cd crypto-package
sudo bash deploy/crypto/install.sh
PYTHONPATH=. /opt/ml-crypto/venv/bin/python deploy/crypto/smoke.py
```

설치는 서비스를 자동 시작하지 않는다. 설치 도중 실패하면 실행하지 말고 오류를 해결한다. 패키지와 잠금·장부는 로컬 파일시스템에 둔다. NFS 공유 장부를 사용하지 않는다.

## 데이터 이전

1. Windows 코인 프로세스 중단을 확인한다. 구버전은 코드 위치 기준 잠금이므로 새 데이터 위치 잠금으로 잔존 여부를 대신 확인할 수 없다.
2. 저장소에서 `venv2\Scripts\python.exe -m src.runners.crypto_backup --output <새_백업_폴더>`를 실행한다.
3. 백업의 research.db, audit.db를 서버 `/var/lib/ml-crypto/data/`에 복사한다. 존재하는 장부를 자동 덮어쓰지 않는다. 데이터 디렉터리와 파일 소유자는 ml-crypto로 설정한다.
4. SQLite integrity_check와 manifest의 테이블별 건수를 대조하고, 양쪽의 positions·closed·signals 내용을 비교한다. 이전 초기 백업과 최신 이전 백업을 혼동하지 않는다.
5. DB 내부의 과거 Windows 보고서 경로는 이력이다. 복사한 옛 RUNNING 상태 파일을 새 프로세스 상태로 사용하지 않는다.
6. 준비 후 `sudo systemctl enable --now ml-crypto`로 운영을 전환한다. Windows 코인 실행기는 중단 상태를 유지한다.

주문 없는 모의 장부도 동일 데이터를 두 서버에서 독립 처리하면 갈라진다. 한쪽만 실행한다. 중단 구간은 관측 공백이며 과거 호가를 이용한 소급 청산을 만들지 않는다.

## 상태·로그·종료

```bash
systemctl status ml-crypto
journalctl -u ml-crypto -n 100 --no-pager
sudo -u ml-crypto env ML_CRYPTO_DATA=/var/lib/ml-crypto /opt/ml-crypto/venv/bin/python -m src.reporting.crypto_health
sudo systemctl stop ml-crypto
```

작업 디렉터리는 /opt/ml-crypto다. 마지막 health 명령을 다른 디렉터리에서 실행할 때는 먼저 `cd /opt/ml-crypto` 한다. 서비스 상태와 최근 감시·평가 시각을 함께 확인한다. GPU·Ollama·거래소 인증키는 필요하지 않다.

SIGTERM은 신규 평가 시작을 막고 감시 반복을 끝낸 다음 진행 평가 작업의 종료를 기다린다. systemd 대기 한도 180초 이후에는 강제 종료될 수 있다. 이 경우에도 다음 실행은 SQLite 장부를 읽으며 동일 신호를 다시 진입하지 않는다.

## 주기와 보관

평가 15분, 관측 목표 15초, 성과 전체 집계 5분이다. `paper_latest.json`은 관측 상태, `performance_latest.json`은 마지막 집계 손익이다. API 지연 중에는 관측 간격이 늘어난다.

백업은 서비스 중단 상태에서 수행한다. 자동 삭제·보관 기간 정책은 아직 적용하지 않았다. 호가가 계속 쌓이므로 디스크 크기를 점검하고 보존 기준 확정 전 자동 삭제하지 않는다. health는 1GB 미만 여유 공간을 실패로 표시한다.

의존성은 현재 사용 환경의 버전을 고정했다. Ubuntu 설치·네트워크·인증서 검증은 대상 서버에서 완료해야 한다.
# GitHub와 서버 접속

서버 주소·SSH 계정·로컬 키 위치·GitHub clone 절차는 [공통 서버 지침](../../md/09-server-deployment.md)을 따른다. Git 저장소에서 직접 전체 src를 설치하지 말고 `build.py`로 생성한 코인 패키지를 별도 폴더에 풀어 설치한다.
