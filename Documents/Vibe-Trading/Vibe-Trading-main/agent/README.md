# Vibe-Trading-main-kr-ver

KIS VTS 기반 한국 주식 자동매매 봇입니다.

## Home MacBook Docker 실행

```bash
docker compose -f deploy/home-macbook/docker-compose.yml up -d --build
```

대시보드:

```text
http://127.0.0.1:8765
```

종료:

```bash
./deploy/home-macbook/stop.sh
```

외부 접속은 Tailscale Serve를 사용합니다.

```bash
./deploy/home-macbook/tailscale_serve_dashboard.sh
```

## GitHub Actions 배포

`.github/workflows/deploy-home-macbook.yml`는 집 맥북에 설치한 GitHub self-hosted runner에서만 동작합니다.

필요한 GitHub Secret:

```text
PAPER_ENV_FILE
```

`PAPER_ENV_FILE`에는 로컬 `.env.paper` 파일 내용을 그대로 넣습니다. API 키와 계좌 정보는 저장소에 커밋하지 않습니다.
