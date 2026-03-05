# 🚀 README.md (최종 완성본)

# On-device LLM Inference Test Automation

> **Project Status:** PoC Stage (S25 GPU 추론 검증 완료 ✅)

이 프로젝트는 Android 기기 내에서 구동되는 LLM(MediaPipe 기반)의 추론 성능 및 결과 품질을 자동으로 벤치마킹하기 위한 파이프라인입니다.

## 1. Prerequisites

* **Python 3.10+**
* **ADB (Android Debug Bridge)** 설치 및 시스템 경로(Path) 등록
* [Platform-Tools 다운로드](https://developer.android.com/studio/releases/platform-tools) 후 환경 변수 등록 필수
* **안드로이드 기기 설정**: S25 등 최신 기기 권장
* 개발자 옵션 활성화 및 **USB 디버깅** 허용


## 2. Installation & Setup

### 2.1 가상환경 생성 및 활성화

```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
source .venv/bin/activate # Mac/Linux

```

### 2.2 Dependency 및 초기 환경 설치

```bash
# 라이브러리 설치
pip install -r requirements.txt

# 필수 폴더 구조(models, results, logs 등) 생성
python scripts/setup.py

```

## 3. Project Structure

On-device-LLM-Test-Automation/  (Root)
├── .venv/                      # 파이썬 가상환경
├── android/                    # 안드로이드 프로젝트 (com.tecace.llmtester)
├── scripts/
│   ├── setup.py                # 초기 폴더 구조 및 환경 세팅
│   ├── shuttle.py              # 모델 파일을 기기로 전송
│   └── runner.py               # ADB를 통한 추론 실행 및 모니터링
├── models/                     # 테스트용 모델 보관 (.task)
├── results/                    # 수집된 결과 데이터 보관
└── .env                        # 환경 변수 설정

---

## 4. Troubleshooting

### 🚨 GPU 백엔드 설정

GPU를 돌리려면 `LlmRunner.kt`에서 아래 설정이 필수입니다.
* **설정**: `.setPreferredBackend(LlmInference.Backend.GPU)`

### 📂 결과 확인 (Internal Storage 접근)

안드로이드 15 보안 정책에 따라 `cat` 대신 `run-as`를 사용해야 합니다.

```bash
# 결과 확인 (앱 전용 샌드박스 내부)
adb shell "run-as com.tecace.llmtester cat files/results/last_result.json"

```

* **`ModuleNotFoundError: No module named 'dotenv'`**: 가상환경(`.venv`)이 활성화된 상태인지 확인 후 `pip install python-dotenv`를 실행하세요.
* **`adb: command not found`**: ADB가 설치되지 않았거나 시스템 환경 변수(Path)에 등록되지 않은 상태입니다.
* **기기 인식 불가**: 폰을 연결한 후 터미널에서 `adb devices`를 입력하여 연결 상태와 디버깅 승인 여부를 확인하세요.

---

## 5. Execution Step

### Step 1: 모델 동기화

```bash
python scripts/shuttle.py

```

### Step 2: 추론 실행

**Windows PowerShell 사용자:**
```powershell
adb shell am start -n com.tecace.llmtester/.MainActivity `
  --es model_path "/data/local/tmp/llm_test/models/gemma3-1b-it-int4.task" `
  --es input_prompt "'Hello, tell me a joke.'"

### Step 3: 데이터 수집

```bash
# PC로 결과 가져오기
adb shell "run-as com.tecace.llmtester cp files/results/last_result.json /sdcard/"
adb pull /sdcard/last_result.json ./results/

```

---
