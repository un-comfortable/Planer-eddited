# TonkatsuBot(바이브 코딩 프로젝트)

계획을 세우고 인증하는 디스코드 봇입니다. 인증을 빼먹거나 제한 횟수를 넘기면 벌금이 쌓입니다.

- 매일 / 주간 / 월간 / 요일 / N일 간격 / 마감일 목표 계획
- "몬스터 주 2회 이하" 같은 **제한 계획** (넘기면 벌금)
- 사진 인증 필수 설정
- 매일 12시 자동 정산, 각자 정한 시간에 인증 알림
- 월 1회 휴식권, 참가자 투표로 정하는 면책

## 명령어

### 계획

| 명령어 | 설명 |
|---|---|
| `/계획 등록` | 매일·주간·월간 계획을 등록합니다. `제한: O`로 등록하면 "N회 이하로 참기" 계획이 됩니다. |
| `/계획 요일` | 특정 요일에만 하는 계획 (예: `요일: 월수금`) |
| `/계획 n일` | N일마다 하는 계획 (예: `간격: 3`) |
| `/계획 목표` | 마감일까지 한 번 하면 되는 목표. 달성하면 목록에서 자동으로 빠집니다. |
| `/계획 수정` | 계획의 이름·사진 필수 여부·횟수·요일·간격·마감일을 바꿉니다. 조건을 바꾸면 알림 채널에 공개됩니다. 계획 종류와 제한 기간은 못 바꿉니다. |
| `/계획 삭제` | 계획 하나를 삭제합니다. |
| `/계획표` | 내 계획과 이번 주·이번 달 진행 상황을 봅니다. |

`/계획 등록` 예시:

| 하고 싶은 것 | 입력 |
|---|---|
| 매일 운동 | `주기:매일 내용:운동` |
| 주 3회 코딩 (사진 필수) | `주기:주간 내용:코딩 횟수:3 사진인증:O` |
| 월 4회 등산 | `주기:월간 내용:등산 횟수:4` |
| 몬스터 주 2회 이하 | `주기:주간 내용:몬스터 횟수:2 제한:O` |
| 커피 하루 1잔 이하 | `주기:매일 내용:커피 횟수:1 제한:O` |
| 담배 한 번도 안 피우기 | `주기:월간 내용:담배 횟수:0 제한:O` |

- 계획 이름은 80자까지 쓸 수 있습니다. 같은 이름은 중복 등록할 수 없습니다.
- 주간 목표는 1~7회, 월간 목표는 1~31회, 제한 횟수는 0~50회까지 정할 수 있습니다.

### 인증

| 명령어 | 설명 |
|---|---|
| `/인증` | 계획을 인증합니다. 깜빡한 어제 인증은 `날짜: 어제`로 합니다. 사진 필수 계획은 `사진`을 첨부해야 합니다. |
| `/인증취소` | 잘못 누른 인증을 한 번 되돌립니다. 제한 계획은 기록 1회만 지워지고, 달성한 목표는 목록으로 돌아옵니다. |

- 제한 계획은 할 때마다 `/인증`으로 기록합니다. 같은 날 여러 번 기록할 수 있습니다.
- 자동완성 목록에 아직 인증하지 않은 계획만 나옵니다. 제한 계획은 항상 나오고 현재 횟수가 같이 보입니다.

### 휴식 · 면책

| 명령어 | 설명 |
|---|---|
| `/휴식` | 한 달에 한 번, 오늘을 휴식일로 씁니다. `동작: 취소하기`로 되돌릴 수 있습니다. |
| `/면책` | 사정이 있을 때 벌금 면제를 요청합니다. 날짜를 비우면 오늘 하루, `시작일`·`종료일`을 넣으면 최대 30일까지 기간 면책입니다. |
| `/현황` | 이번 달 멤버들의 휴식·면책 사용 내역을 봅니다. |

**면책 투표 규칙**
- 서버 멤버 중 **계획을 하나라도 등록한 참가자**만 투표할 수 있습니다. 요청자 본인은 투표할 수 없습니다.
- 요청자를 뺀 참가자의 **과반수**가 찬성하면 통과합니다. 남은 사람이 다 찬성해도 과반수가 안 되면 바로 거절됩니다.
- 투표할 다른 참가자가 없으면 면책을 요청할 수 없습니다.

### 기타

| 명령어 | 설명 |
|---|---|
| `/알림시간` | 인증 알림을 받을 시각을 정합니다 (0~23시, 기본 2시). |
| `/연동` | Planer 앱과 연동합니다. 앱 ⚙ 설정 → 디스코드 연동에서 받은 코드를 `코드`에 넣습니다. 비우면 연동 상태 확인, `동작: 연동 해제`로 해제 |
| `/칭찬` | 무작위 칭찬 한마디 |
| `/벌금수정` | **[관리자]** 벌금을 3,000원 더하거나 뺍니다 (벌금을 냈을 때 차감). 0원 아래로는 내려가지 않습니다. |

## 정산 규칙

매일 **12시**에 봇이 어제 기록을 확인해서 벌금을 매기고, 알림 채널에 결과와 벌금 순위를 올립니다.

| 언제 | 무엇을 검사 |
|---|---|
| 매일 | 어제 일일·요일 계획을 했는지, 어제가 마감인 목표를 달성했는지, 하루 제한을 넘겼는지 |
| 월요일 | 지난주 주간 목표를 채웠는지, 주간 제한을 넘겼는지 |
| 매달 1일 | 지난달 월간 목표를 채웠는지, 월간 제한을 넘겼는지 |

- 벌금은 **하루 3,000원 고정**입니다. 여러 개를 놓쳐도 그날은 3,000원입니다.
- **휴식·면책 날**에는 못 한 계획으로 벌금을 매기지 않습니다. 단, **제한 초과는 봐주지 않습니다**.
- 휴식·면책을 쓴 날 수만큼 그 주·그 달의 **주간·월간 목표 횟수가 줄어듭니다**. 예: 주 3회 목표에 휴식 1일 → 주 2회
- 새로 등록한 계획은 등록 전 기간은 검사하지 않습니다. 주·달 중간에 만든 주간·월간 계획은 첫 주·첫 달 검사에서 빠집니다.
- **새벽 0~4시는 전날로 취급**합니다 (하루 기준 새벽 5시, Planer 앱과 같음). 새벽 2시에 인증하면 전날 인증이 됩니다.
- **N일 계획**은 알림만 보내고 벌금은 매기지 않습니다.
- 봇이 12시에 꺼져 있었다면 같은 날 다시 켜진 뒤 첫 정각에 정산합니다. 같은 날 두 번 정산하지는 않습니다.

## 인증 알림

각자 `/알림시간`으로 정한 시각에 아직 안 한 계획을 알림 채널에서 멘션합니다. 휴식·면책 날에는 보내지 않습니다.

| 계획 | 알림을 보내는 때 |
|---|---|
| 일일 · 요일 | 그날 아직 안 했을 때 |
| 주간 | 금·토·일요일에, 이번 주 목표를 아직 못 채웠을 때 |
| 월간 | 20일·25일·말일에, 이번 달 목표를 아직 못 채웠을 때 |
| N일 | 간격이 다 찼을 때 |
| 목표 | 마감 3일 전부터 |
| 제한 | 알림 없음 |

## 설치와 실행

봇은 [Planer-eddited](https://github.com/un-comfortable/Planer-eddited) 저장소의 `bot/` 폴더에 있고, 데이터는 Planer 앱과 같은 **Firestore**(`planer-f8cb7`)에 저장합니다. 자세한 구조는 [`docs/tonkatsu-integration.md`](../docs/tonkatsu-integration.md)를 참고하세요.

### 1. 준비물

- Python 3.10 이상
- 디스코드 봇 토큰 ([Discord Developer Portal](https://discord.com/developers/applications)에서 봇 생성)
- 개발자 포털 → Bot 탭에서 **Server Members Intent** 켜기 (꺼져 있으면 봇이 시작되지 않습니다)
- Firebase **서비스 계정 키** (아래 4번)

### 2. 설치

```bash
git clone https://github.com/un-comfortable/Planer-eddited.git
cd Planer-eddited/bot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. `.env` 설정

```bash
cp .env.example .env
```

| 항목 | 내용 |
|---|---|
| `TOKEN` | 디스코드 봇 토큰 |
| `ALERT_CHANNEL` | 정산 결과와 인증 알림을 올릴 채널 ID |
| `WELCOME_CHANNEL` | 새 멤버 환영 메시지를 올릴 채널 ID |
| `FIREBASE_CREDENTIALS` | 서비스 계정 키 파일 경로 (예: `/home/ubuntu/secrets/planer-bot.json`) |
| `FIREBASE_PROJECT_ID` | 비우면 `planer-f8cb7` |

채널 ID는 디스코드 설정 → 고급 → **개발자 모드**를 켠 뒤, 채널을 우클릭 → "채널 ID 복사"로 얻을 수 있습니다.

### 4. 서비스 계정 키

1. [Google Cloud 콘솔](https://console.cloud.google.com/iam-admin/serviceaccounts?project=planer-f8cb7) → IAM 및 관리자 → 서비스 계정 → **서비스 계정 만들기** (이름 예: `tonkatsu-bot`)
2. 역할은 **Cloud Datastore 사용자**(`roles/datastore.user`) 하나만 줍니다.
3. 만든 계정 → 키 → 키 추가 → JSON. 내려받은 파일을 서버로 옮깁니다.
4. 서버에서 저장소 **밖**에 두고 권한을 잠급니다.
   ```bash
   mkdir -p ~/secrets && mv planer-*.json ~/secrets/planer-bot.json && chmod 600 ~/secrets/planer-bot.json
   ```
5. `.env`의 `FIREBASE_CREDENTIALS`에 이 경로를 적습니다.

**키 파일은 절대 GitHub나 채팅에 올리지 마세요.** 이 저장소는 공개 저장소입니다. 유출됐다면 콘솔에서 키를 삭제하고 새로 만드세요.

### 5. 실행

```bash
venv/bin/python main.py
```

`🔥 Firestore 연결 완료`와 `로그인 성공!`이 출력되면 정상입니다.

### 기존 JSON 데이터 옮기기 (한 번만)

예전 봇의 `study_plans.json` 등을 Firestore로 옮깁니다. JSON 파일은 바뀌지 않습니다.

```bash
sudo systemctl stop tonkatsubot                     # 1. 기존 봇 끄기
cp -r ~/TonkatsuBot ~/TonkatsuBot-backup            # 2. 백업
cd ~/Planer-eddited/bot
venv/bin/python tools/migrate_json_to_firestore.py --data-dir ~/TonkatsuBot --dry-run   # 3. 개수 확인
venv/bin/python tools/migrate_json_to_firestore.py --data-dir ~/TonkatsuBot             # 4. 옮기기
```

- 문서 ID가 고정 규칙이라 여러 번 실행해도 중복되지 않습니다.
- **되돌리기:** 새 봇을 끄고, 예전 폴더의 봇을 다시 켜면 됩니다.

### 서버에서 계속 켜두기 (systemd)

`/etc/systemd/system/tonkatsubot.service` (경로와 사용자 이름은 환경에 맞게):

```ini
[Unit]
Description=TonkatsuBot Discord bot
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/Planer-eddited/bot
ExecStart=/home/ubuntu/Planer-eddited/bot/venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tonkatsubot   # 켜기 + 재부팅 시 자동 시작
journalctl -u tonkatsubot -f              # 로그 보기
```

### 업데이트

```bash
cd ~/Planer-eddited && git pull && sudo systemctl restart tonkatsubot
```

봇을 두 개 동시에 켜지 마세요.

### 테스트

저장소 루트에서 Firestore 에뮬레이터로 실행합니다 (Java 21 이상 필요, 실제 데이터에 접근하지 않음).

```bash
pip install -r bot/requirements-dev.txt
npm run test:bot
```

## 데이터

계획·인증·휴식·면책·벌금·투표는 Firestore에 저장되고, 봇은 실시간으로 받아서 메모리에 들고 있습니다. Planer 앱에서 인증하면 봇에도 바로 반영됩니다.

| 위치 | 내용 |
|---|---|
| Firestore `plans`, `checkIns`, `offDays`, `fineEvents`, `members`, `votes` | 공용 데이터 |

- **자동 백업:** 하루 한 번 `backups/날짜/firestore.json`에 공용 데이터 전체를 내려받고, 최근 14일치를 보관합니다.
- 벌금은 건마다 `fineEvents`에 "언제, 왜, 얼마"가 남습니다.

## 설정 바꾸기

| 값 | 위치 | 기본값 | 의미 |
|---|---|---|---|
| `SETTLEMENT_HOUR` | `main.py` | `12` | 정산 시각 |
| `FINE_AMOUNT` | `main.py` | `3000` | 하루 벌금, `/벌금수정` 금액 |
| `BACKUP_KEEP_DAYS` | `main.py` | `14` | 백업 보관 일수 |
| `DAY_START_HOUR` | `core.py` | `5` | 하루 기준 시각 (앱과 맞춰야 함) |
