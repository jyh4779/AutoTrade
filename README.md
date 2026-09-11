# AutoTrade

코스피 주식 시스템과 업비트 원화 현물 모의매매 시스템의 소스 저장소다. 공통 코드와 시장별 로직을 함께 관리하며, Ubuntu에는 코인 코드만 패키징해 설치한다.

- 공통 지침: [CLAUDE.md](CLAUDE.md) → [md/README.md](md/README.md)
- 서버 및 GitHub 배포: [md/09-server-deployment.md](md/09-server-deployment.md)
- Ubuntu 설치·장부 이전·서비스 운영: [deploy/crypto/README.md](deploy/crypto/README.md)

코인 실행은 Upbit 공개 시세 기반 모의매매이며 실주문을 제출하지 않는다. SSH 키, 거래소 인증정보, 장부와 로그는 저장소에 포함하지 않는다. Windows 주식 실행기는 별도 설정과 운영 환경을 요구하므로 Ubuntu에서 실행하지 않는다.
