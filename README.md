# 📊 AI Data Insight Builder (Edu Edition)

> **교육용 데이터 정밀 분석 및 AI 인사이트 스튜디오**  
> Flask, Pandas, Google Gemini API, Chart.js 기반의 데이터 분석 웹앱 / PWA(Progressive Web App)

---

## 🌟 프로젝트 개요

**AI Data Insight Builder**는 복잡한 데이터 분석과 전처리 과정을 누구나 직관적으로 수행할 수 있도록 돕는 교육용 데이터 분석 웹 애플리케이션입니다.  
사용자가 CSV 파일을 업로드하면 **Pandas 연산 엔진**이 데이터 진단과 정밀 계산을 수행하고, **Gemini AI 모델**이 사실(Fact)에 기반한 다층적 인사이트 리포트 및 1:1 대화형 후속 질의응답(Q&A)을 제공합니다.

* **보안 접근 인증**: 4자리 비밀번호(PIN) 잠금 화면 적용
* **PWA 지원**: 스마트폰 및 PC에서 앱처럼 설치하여 전체 화면으로 실행 가능
* **모바일 최적화**: 스마트폰 환경에 맞춘 반응형 타이포그래피, 터치 친화적 UI 및 차트

---

## 🚀 주요 기능 및 4단계 분석 워크플로우

```
[1단계] CSV 업로드 & 정밀 진단 ➡️ [2단계] Gemini 맞춤 분석 제안 ➡️ [3단계] Pandas 계산 & 차트 ➡️ [4단계] 팩트 기반 AI 리포트 & Q&A
```

### 1단계: CSV 업로드 및 13개 항목 자동 진단 (`/inspect`)
* **다양한 인코딩 자동 감지**: UTF-8, CP949, EUC-KR 등 한글 인코딩 및 메타데이터 건너뛰기(`skiprows`) 자동 보정
* **13개 항목 품질 진단**:
  * 행/열 크기, 누락값(결측치) 비율, 중복 행 감지
  * 시계열 연도(Year) 및 기준 시점 자동 추천
  * 집계 지역(World, OECD, 동아시아 등) 후보군 자동 식별
* **데이터 프라이버시 보호**: 업로드된 CSV는 디스크에 저장되지 않고 **서버 메모리(RAM)에 1개 데이터셋만 임시 보관**되며 서버 재시작 시 자동 소멸

### 2단계: Gemini AI 도구 추천 및 사용자 직접 설정 (`/suggest`)
* **자료 적합성 검증 기반 제안**: 현재 데이터셋의 구조(국가 컬럼, 연도, 수치 등)에서 실제로 계산 가능한 검증된 분석 도구 카탈로그 중 최적의 3~5개 제안
* **분석 도구 카탈로그**:
  * 1개 국가 vs 전체 국가 비교 (`compare_one_vs_all`)
  * 상위/하위 N개 순위 분석 (`top_bottom_n`)
  * 시계열 추세 분석 (`trend_line`)
  * 두 시점 간 변화율/증감 분석 (`period_change`)
  * 상관관계 분석 (`correlation_scatter`)
  * 다국가 시계열 비교 (`multi_country_trend`)
* **자연어 질문 분석**: 사용자가 궁금한 점을 일상 언어로 입력하면 최적의 도구와 파라미터를 자동 매핑

### 3단계: Pandas 계산 엔진 & Chart.js 시각화 (`/run`)
* **환각(Hallucination) 없는 무결점 계산**: AI가 숫자를 상상해내지 않고 Pandas가 오차 없이 통계 수치를 직접 계산
* **집계 데이터 자동 제외**: World, Regional Total 등 전체 통계를 왜곡하는 집계 국가 자동 필터링
* **반응형 인터랙티브 차트**: 막대그래프, 선그래프, 산점도 등 도구에 최적화된 Chart.js 동적 렌더링
* **계산 메타 요약**: 사용된 행 수, 제외된 이상치/집계행 수 투명 공개

### 4단계: 사실 기반 AI 해석 리포트 & 대화형 Q&A (`/explain`, `/followup`)
* **모드 A / 모드 B 비교 학습**:
  * **모드 A (비교용)**: 원시 수치 없이 AI의 사전 지식에만 의존해 발생할 수 있는 환각 체험
  * **모드 B (정식 권장)**: Pandas가 계산한 팩트 테이블만을 근거로 작성된 신뢰도 100% 보고서
* **지표 극성 정밀 반영**: 청렴도/부패인식지수(CPI), 순위 등 지표 특성(점수가 높을수록 청렴 vs 낮을수록 부패)을 AI가 정확히 인지하여 모순 없는 해석 도출
* **1:1 대화형 후속 질문 (Q&A)**: "어느 나라가 가장 부패했어?", "한국과 일본의 차이는?" 등 추가 질문에 대한 즉각적이고 친절한 팩트 답변
* **다양한 내보내기**: 마크다운(`.md`), 인쇄용 PDF, 단독 실행형 HTML 보고서 저장

---

## 📱 PWA & 모바일 최적화 기능

* **설치형 웹앱(PWA)**:
  * 브라우저 주소창 없는 전체 화면(Standalone) 앱 경험
  * 안드로이드 크롬 / 삼성인터넷: 원클릭 네이티브 앱 설치 대화상자 지원
  * 아이폰 / 아이패드 사파리: 홈 화면 추가 3단계 비주얼 가이드 지원
* **모바일 사용자 경험 강화**:
  * 한국어 가독성을 위한 단어 단위 줄바꿈 (`word-break: keep-all;`)
  * 15px 기본 폰트 및 1.8 행간 적용으로 모바일 눈 피로도 최소화
  * 터치 시 화면 확대 방지 (`font-size: 16px` 및 44px 터치 타겟)
  * 데이터 표(Table) 가로 스와이프 스크롤 지원

---

## 🔒 보안 및 인증

* **접근 보안 PIN 잠금**:
  * 사이트 최초 접속 시 4자리 비밀번호 인증 필수
  * 인증 성공 시 세션 스토리지에 안전하게 상태 유지 (화면 상단 `🔒 잠금` 버튼으로 즉시 재잠금 가능)
* **API Key 및 원문 보호**:
  * Gemini API Key는 프론트엔드나 콘솔 로그에 절대 노출되지 않음
  * CSV 원본 데이터 전문은 외부 AI API로 전송되지 않음

---

## 🛠️ 기술 스택

| 영역 | 기술 스택 | 설명 |
|---|---|---|
| **Backend** | Python 3.10+, Flask, Pandas, NumPy | RESTful API, 데이터 전처리 및 통계 연산 엔진 |
| **AI Model** | Google Gemini API (`gemini-3.5-flash-lite`) | 도구 추천, 팩트 기반 해석 보고서, 후속 질의응답 |
| **Frontend** | Vanilla JavaScript (ES6+), HTML5, CSS3 | 프레임워크 없는 순수 경량 웹 프론트엔드 |
| **Visualization** | Chart.js 4.x | 반응형 인터랙티브 차트 렌더링 |
| **Mobile / PWA** | Web App Manifest, Service Worker | 오프라인 정적 캐싱, 홈 화면 앱 설치 |
| **Deployment** | Vercel Serverless Functions | WSGI Wrapper 기반 파이썬 서버리스 배포 |

---

## 💻 로컬 개발 및 실행 방법

### 1. 레포지토리 클론
```bash
git clone https://github.com/gyeong-lab/datainsghtbuilder.git
cd datainsghtbuilder
```

### 2. 파이썬 가상환경 생성 및 활성화
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# Mac / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 필수 패키지 설치
```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정 (`.env`)
프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 아래 내용을 입력합니다:
```ini
GEMINI_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
FLASK_DEBUG=true
PORT=5000
```

### 5. 서버 실행
```bash
python app.py
```
* **PC 브라우저 접속**: `http://127.0.0.1:5000`
* **동일 Wi-Fi 스마트폰 접속**: `http://[컴퓨터_IP]:5000` (예: `http://10.20.32.184:5000`)

---

## ☁️ Vercel 서버리스 배포

본 프로젝트는 Vercel Serverless Functions 환경에 최적화된 WSGI 미들웨어([`api/index.py`](api/index.py)) 및 라우팅 설정([`vercel.json`](vercel.json))을 포함하고 있습니다.

1. **GitHub 연동**: GitHub 저장소 푸시 시 Vercel에서 자동 빌드 및 배포
2. **Vercel 환경 변수 설정**:
   * Vercel Dashboard → Project Settings → **Environment Variables**
   * Key: `GEMINI_API_KEY`, Value: `본인의_Gemini_API_키` 등록
3. **배포 보안 설정 (중요)**:
   * 외부 사용자 및 스마트폰에서 로그인 없이 사이트에 접근할 수 있도록 Vercel Dashboard → **Settings** → **Deployment Protection** → **Vercel Authentication**을 **`Disabled`**로 설정합니다. (자체 4자리 PIN으로 안전하게 보호됩니다.)

---

## 📁 디렉토리 구조

```
data-insight-builder/
├── api/
│   └── index.py            # Vercel Serverless WSGI 진입점
├── static/
│   ├── app.js              # 프론트엔드 비즈니스 로직 및 PWA 제어
│   ├── style.css           # 모바일 반응형 UI/UX 스타일시트
│   ├── sw.js               # PWA 서비스 워커 (캐시 및 업데이트 관리)
│   ├── manifest.json       # PWA 매니페스트 메타데이터
│   ├── icon-192.png        # 192x192 앱 아이콘
│   ├── icon-512.png        # 512x512 앱 아이콘
│   └── favicon.ico         # 파비콘
├── templates/
│   └── index.html          # 메인 UI 템플릿
├── app.py                  # Flask 메인 애플리케이션 및 라우트
├── requirements.txt        # 파이썬 의존성 목록
├── vercel.json             # Vercel 배포 및 라우팅 설정
└── README.md               # 프로젝트 안내 문서
```

---

## 📄 라이선스
AI Data Insight Builder &copy; 2026. Educational Data Analysis Web App powered by Flask, Pandas, and Gemini API.
