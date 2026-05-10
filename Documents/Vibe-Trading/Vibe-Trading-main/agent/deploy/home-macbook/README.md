# Home MacBook Paper Trading Runtime

집 맥북에서 자동매매 봇을 계속 띄워두는 운영 구조입니다.

구성:

- macOS host: Tailscale, Docker Desktop, tmux
- Docker Ubuntu container: `run_paper.py`, `log_dashboard.py`
- tmux: 운영 콘솔, 로그, 상태 감시
- Tailscale Serve: 외부 접속은 tailnet 내부로만 제한

## 1. 최초 준비

```bash
brew install tmux
brew install --cask docker tailscale
```

Docker Desktop과 Tailscale에 로그인합니다.

`.env.paper`는 저장소 루트에 둡니다. 이 파일은 Docker 이미지에 복사되지 않고 `docker compose`의 `env_file`로만 주입됩니다.

## 2. 실행

```bash
cd /path/to/agent
chmod +x deploy/home-macbook/*.sh
./deploy/home-macbook/start_tmux.sh
```

tmux 창:

- `bot-log`: 모의투자 봇 로그
- `dashboard-log`: 대시보드 로그
- `status`: 컨테이너 상태와 최근 로그
- `shell`: 운영 쉘

tmux 분리:

```text
Ctrl-b d
```

다시 붙기:

```bash
tmux attach -t vibe-trading
```

## 3. 대시보드

로컬:

```text
http://127.0.0.1:8765
```

Tailscale 외부 접속:

```bash
./deploy/home-macbook/tailscale_serve_dashboard.sh
```

이후 `tailscale serve status`에 표시되는 HTTPS URL로 접속합니다.

주의:

- `tailscale serve`만 사용합니다.
- `tailscale funnel`은 인터넷 공개이므로 사용하지 않습니다.
- compose는 대시보드를 `127.0.0.1:8765`에만 바인딩합니다.

## 4. 중지

```bash
./deploy/home-macbook/stop.sh
```

## 5. 운영 체크리스트

장 시작 전:

```bash
docker compose -f deploy/home-macbook/docker-compose.yml ps
tail -80 paper_trading.log
```

확인할 로그:

- `[READY→RUNNING]`
- `env=demo`
- `positions=0` 또는 복구된 포지션 수
- `[Account] deposit=...`
- `[StrategySchedule]`

장중 위험 징후:

- `CRITICAL [running→STOPPING]`
- 연속 `balance query failed`
- `WS stale`
- `Order failed`
- `STATE_SYNC_FAIL`

## 6. 설계 원칙

- 매매 봇과 대시보드는 컨테이너를 분리합니다.
- 로그 파일과 `data/`는 호스트에 보존합니다.
- `.env.paper`와 API 키는 이미지에 굽지 않습니다.
- 대시보드는 로컬 포트만 열고, 외부 접속은 Tailscale Serve로 제한합니다.
- 봇은 `restart: unless-stopped`로 재부팅 후 자동 복구됩니다.

