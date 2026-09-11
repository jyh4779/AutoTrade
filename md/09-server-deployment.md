# Ubuntu 코인 서버와 GitHub 배포

## 접속 대상

- 서버: `smart-beauty.kr`
- SSH 사용자: `ubuntu`
- 로컬 개인키 경로: `D:\ML\ssh\salonmanager-server-01.key`
- GitHub HTTPS 원격: `https://github.com/jyh4779/AutoTrade.git`
- 배포 브랜치: `main`

키 내용·토큰·계좌 설정을 문서나 Git에 넣지 않는다. `ssh/`, `data/`, `.env`, 개인키와 런타임 산출물은 업로드에서 제외한다. 과거 Notion 인증정보가 포함된 유틸리티 5개도 제외한다. 로컬에서 이미 추적 중인 파일은 .gitignore만으로 보호되지 않으므로 배포 트리를 별도로 검사한다.

```powershell
ssh -i D:\ML\ssh\salonmanager-server-01.key ubuntu@smart-beauty.kr
```

SSH 호스트 키는 서버 관리 경로에서 확인한 지문과 대조한다. 검증을 끄지 않는다. GitHub 비공개 저장소 접근에는 서버용 읽기 전용 인증을 사용하며 개인키나 토큰을 URL에 기록하지 않는다.

## 배포 방식

원격의 기존 파일은 현재 프로젝트 소스로 교체하되 이전 커밋 이력은 복구용으로 보존한다. 강제 푸시나 과거 이력 삭제는 필요하지 않다. 주식과 공통 코드는 저장소에서 함께 관리하지만 Ubuntu 서비스에는 코인 배포 패키지만 설치한다. Windows 주식 서비스는 독립 운영한다.

서버에서 다음 순서로 코드 패키지를 준비하고 [설치·데이터 이전 절차](../deploy/crypto/README.md)를 따른다.

```bash
git clone --branch main https://github.com/jyh4779/AutoTrade.git /app/autotrade
cd /app/autotrade
git rev-parse HEAD
python3 deploy/crypto/build.py
mkdir -p /app/autotrade/dist/package
unzip dist/crypto-ubuntu.zip -d /app/autotrade/dist/package
cd /app/autotrade/dist/package
sudo bash deploy/crypto/install.sh
PYTHONPATH=. /opt/ml-crypto/venv/bin/python deploy/crypto/smoke.py
```

재배포 시에는 서비스를 중단하고 DB를 백업한 뒤 `git pull --ff-only`를 사용한다. 압축 해제 대상은 배포별 새 폴더를 사용한다. 커밋 SHA, 설치 결과, 서비스 상태, 최신 평가·감시 시각을 기록한다.

모의매매 DB는 GitHub로 전달하지 않는다. 중단 상태에서 만든 검증된 백업을 SSH/SCP로 별도 전송하고 무결성과 건수를 대조한다. Windows 코인 프로세스는 중단 상태로 유지하고 장부 복원 후 Ubuntu에서만 실행한다. 실행 중단 구간을 소급 체결로 채우지 않는다.

## 현재 상태

2026-09-12: Ubuntu 배포 코드 준비 완료. 서버 설치·DB 복원·systemd 기동은 별도 검증해야 하며, GitHub 푸시 성공만으로 서버 운영 완료로 표시하지 않는다.
