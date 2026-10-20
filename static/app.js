/**
 * AI Data Insight Builder - 프론트엔드 제어 스크립트 (Vanilla JavaScript)
 * 규칙 준수:
 * 1. React/Vue 일절 미사용 (순수 Vanilla JS)
 * 2. 프론트엔드 표준 로그 출력: [PAGE], [UPLOAD], [INSPECT], [SUGGEST], [RUN], [CHART], [EXPLAIN], [ERROR]
 * 3. API Key, 개인정보 원문, CSV 전체 데이터는 로그에 출력하지 않음
 * 4. Chart.js 연동을 통한 동적 차트 렌더링
 */

// 전역 상태 관리 객체 (배포 환경 및 로컬 환경 자동 대응)
const API_BASE = window.location.protocol === "file:"
  ? "http://127.0.0.1:5000"
  : "";

const state = {
  selectedFile: null,
  diagnostics: null,
  suggestions: [],
  selectedSuggestion: null,
  calculationResult: null,
  currentMode: "B",
  chartInstance: null,
  currentReportMarkdown: ""
};

// DOM 로드 완료 후 초기화
document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE] 페이지 로드 완료");
  initPinLock();
  initPwaInstallPrompt();
  initServerHealth();
  setupEventListeners();
});

/**
 * 🔐 4자리 비밀번호 잠금 인증 (1234)
 */
function initPinLock() {
  const CORRECT_PIN = "1234";
  const overlay = document.getElementById("pinLockOverlay");
  const dots = document.querySelectorAll("#pinDots .pin-dot");
  const errorMsg = document.getElementById("pinErrorMsg");
  const btnLock = document.getElementById("btnLockApp");
  let enteredPin = "";

  // 세션에 이미 인증된 경우 잠금 해제 상태 유지
  if (sessionStorage.getItem("data_insight_auth") === "true") {
    if (overlay) overlay.classList.add("unlocked");
  } else {
    if (overlay) overlay.classList.remove("unlocked");
  }

  function updateDots() {
    dots.forEach((dot, idx) => {
      if (idx < enteredPin.length) {
        dot.classList.add("filled");
      } else {
        dot.classList.remove("filled");
      }
    });
  }

  function handleDigit(digit) {
    if (enteredPin.length >= 4) return;
    enteredPin += digit;
    updateDots();

    if (errorMsg) errorMsg.style.display = "none";

    if (enteredPin.length === 4) {
      if (enteredPin === CORRECT_PIN) {
        // 성공: 잠금 해제
        sessionStorage.setItem("data_insight_auth", "true");
        if (overlay) overlay.classList.add("unlocked");
        enteredPin = "";
        updateDots();
      } else {
        // 실패: 진동 및 에러 표시
        if (errorMsg) errorMsg.style.display = "block";
        const card = document.querySelector(".pin-lock-card");
        if (card) {
          card.classList.remove("shake");
          void card.offsetWidth;
          card.classList.add("shake");
        }
        setTimeout(() => {
          enteredPin = "";
          updateDots();
        }, 500);
      }
    }
  }

  function handleBackspace() {
    if (enteredPin.length > 0) {
      enteredPin = enteredPin.slice(0, -1);
      updateDots();
      if (errorMsg) errorMsg.style.display = "none";
    }
  }

  function handleClear() {
    enteredPin = "";
    updateDots();
    if (errorMsg) errorMsg.style.display = "none";
  }

  // 화면 키패드 버튼 클릭
  document.querySelectorAll(".pin-key[data-key]").forEach(keyBtn => {
    keyBtn.addEventListener("click", () => handleDigit(keyBtn.dataset.key));
  });

  const btnClear = document.getElementById("btnPinClear");
  if (btnClear) btnClear.addEventListener("click", handleClear);

  const btnBackspace = document.getElementById("btnPinBackspace");
  if (btnBackspace) btnBackspace.addEventListener("click", handleBackspace);

  // 물리 키보드 숫자 입력 지원
  window.addEventListener("keydown", (e) => {
    if (overlay && overlay.classList.contains("unlocked")) return;
    if (e.key >= "0" && e.key <= "9") {
      handleDigit(e.key);
    } else if (e.key === "Backspace") {
      handleBackspace();
    } else if (e.key === "Escape") {
      handleClear();
    }
  });

  // 상단 헤더 🔒 잠금 버튼
  if (btnLock) {
    btnLock.addEventListener("click", () => {
      sessionStorage.removeItem("data_insight_auth");
      enteredPin = "";
      updateDots();
      if (errorMsg) errorMsg.style.display = "none";
      if (overlay) overlay.classList.remove("unlocked");
    });
  }
}

/**
 * 📲 PWA 설치 유도 플로팅 배너 및 앱 설치 버튼 제어
 */
let deferredPwaPrompt = null;

function initPwaInstallPrompt() {
  const banner = document.getElementById("pwaInstallBanner");
  const btnBannerInstall = document.getElementById("btnBannerInstall");
  const btnBannerDismiss = document.getElementById("btnBannerDismiss");
  const btnBannerClose = document.getElementById("btnBannerClose");
  const btnHeaderInstall = document.getElementById("btnHeaderInstallPwa");

  // 이미 독립형 PWA 앱으로 실행 중인지 확인
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  if (isStandalone) {
    if (btnHeaderInstall) btnHeaderInstall.style.display = "none";
    if (banner) banner.style.display = "none";
    console.log("[PWA] 현재 독립형 PWA 앱 모드로 실행 중입니다.");
    return;
  }

  // 1. 브라우저의 PWA 설치 준비 이벤트 감지
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPwaPrompt = e;
    console.log("[PWA] beforeinstallprompt 이벤트 포착 완료");

    // 상단 헤더 '📲 앱 설치' 버튼 활성화
    if (btnHeaderInstall) {
      btnHeaderInstall.style.display = "inline-flex";
    }

    // 이번 세션에서 사용자가 닫은 적이 없다면 1.5초 후 하단 설치 알림 배너 팝업
    if (!sessionStorage.getItem("pwa_install_dismissed") && banner) {
      setTimeout(() => {
        banner.style.display = "block";
      }, 1500);
    }
  });

  // 2. 앱 설치 실행 트리거 공통 함수
  async function triggerInstall() {
    if (deferredPwaPrompt) {
      deferredPwaPrompt.prompt();
      const choice = await deferredPwaPrompt.userChoice;
      console.log("[PWA] 사용자 설치 선택:", choice.outcome);
      if (choice.outcome === "accepted") {
        if (banner) banner.style.display = "none";
        if (btnHeaderInstall) btnHeaderInstall.style.display = "none";
      }
      deferredPwaPrompt = null;
    } else {
      // iOS 사파리나 브라우저 자동 처리를 위한 친절한 수동 설치 안내
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
      if (isIOS) {
        alert("📲 아이폰/아이패드 설치 방법:\n하단 공유 버튼(⎋)을 누른 후 '홈 화면에 추가'를 선택하시면 앱으로 설치됩니다!");
      } else {
        alert("📲 크롬 브라우저 상단 주소창 맨 오른쪽의 설치 아이콘(⬇️ 또는 모니터 모양)을 클릭하시면 즉시 앱으로 설치됩니다!");
      }
    }
  }

  if (btnBannerInstall) btnBannerInstall.addEventListener("click", triggerInstall);
  if (btnHeaderInstall) btnHeaderInstall.addEventListener("click", triggerInstall);

  // 3. 배너 닫기 및 나중에 하기
  function dismissBanner() {
    if (banner) banner.style.display = "none";
    sessionStorage.setItem("pwa_install_dismissed", "true");
  }

  if (btnBannerDismiss) btnBannerDismiss.addEventListener("click", dismissBanner);
  if (btnBannerClose) btnBannerClose.addEventListener("click", dismissBanner);

  // 4. 앱 설치 완료 이벤트
  window.addEventListener("appinstalled", () => {
    console.log("[PWA] 앱 설치 성공적으로 완료됨");
    if (banner) banner.style.display = "none";
    if (btnHeaderInstall) btnHeaderInstall.style.display = "none";
  });
}

/**
 * 1. 서버 헬스체크 (/health)
 */
async function initServerHealth() {
  const dot = document.getElementById("statusDot");
  const text = document.getElementById("statusText");

  try {
    const res = await fetch(`${API_BASE}/health`);
    const data = await res.json();
    if (res.ok && data.status === "healthy") {
      dot.className = "status-indicator online";
      text.textContent = `온라인 (${data.model} 준비됨)`;
    } else {
      dot.className = "status-indicator error";
      text.textContent = "서버 상태 이상";
    }
  } catch (err) {
    console.error("[ERROR] 서버 헬스체크 실패:", err);
    dot.className = "status-indicator error";
    text.textContent = "서버 연결 불가";
  }
}

/**
 * 2. 이벤트 리스너 설정
 */
function setupEventListeners() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const btnInspect = document.getElementById("btnInspect");
  const btnRequestSuggest = document.getElementById("btnRequestSuggest");
  const btnGoToExplain = document.getElementById("btnGoToExplain");
  const btnTabModeA = document.getElementById("btnTabModeA");
  const btnTabModeB = document.getElementById("btnTabModeB");
  const btnRunExplain = document.getElementById("btnRunExplain");

  // 파일 선택 드롭존 이벤트
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  // 1단계: 진단 시작 버튼
  btnInspect.addEventListener("click", () => startInspect());

  // 1단계 -> 2단계 이동 버튼: 자연어 질문창으로 이동하고 2단계 표시
  btnRequestSuggest.addEventListener("click", () => {
    activateStep(2);
    document.getElementById("sectionStep2").scrollIntoView({ behavior: "smooth" });
    // AI 추천 도구 카탈로그는 백그라운드에서 조용히 로드하여 필요 시 활용
    if (!state.suggestions || state.suggestions.length === 0) {
      startSuggest();
    }
  });

  // 맞춤형 자연어 질문 제출 버튼
  const btnSubmitQuery = document.getElementById("btnSubmitQuery");
  const inputCustomQuery = document.getElementById("inputCustomQuery");
  if (btnSubmitQuery && inputCustomQuery) {
    btnSubmitQuery.addEventListener("click", () => submitCustomQuery());
    inputCustomQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submitCustomQuery();
    });
  }

  // 2단계: 질문에 맞는 차트 및 시각화 보기 버튼 클릭
  const btnViewQueryVisualization = document.getElementById("btnViewQueryVisualization");
  if (btnViewQueryVisualization) {
    btnViewQueryVisualization.addEventListener("click", () => {
      if (state.calculationResult) {
        activateStep(3);
        renderCalculationResult(state.calculationResult);
        document.getElementById("sectionStep3").scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  // 추천 질문 칩 클릭: 자동으로 실행하지 않고 입력창에 채워 넣기만 수행 (사용자가 직접 [질문하기] 클릭하도록 대기)
  document.querySelectorAll(".query-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      if (inputCustomQuery) {
        inputCustomQuery.value = chip.dataset.q;
        inputCustomQuery.focus();
      }
    });
  });

  // 4단계 이동 버튼
  btnGoToExplain.addEventListener("click", () => {
    activateStep(4);
    document.getElementById("sectionStep4").scrollIntoView({ behavior: "smooth" });
  });

  // A/B 모드 탭 전환
  btnTabModeA.addEventListener("click", () => setExplainMode("A"));
  btnTabModeB.addEventListener("click", () => setExplainMode("B"));

  // 4단계: 보고서 생성 버튼
  btnRunExplain.addEventListener("click", () => startExplain());

  // 3단계: 순위 차트 상하위 전환 버튼
  const btnChartTop = document.getElementById("btnChartTop");
  const btnChartBottom = document.getElementById("btnChartBottom");
  if (btnChartTop && btnChartBottom) {
    btnChartTop.addEventListener("click", () => {
      btnChartTop.classList.add("active");
      btnChartBottom.classList.remove("active");
      if (state.lastCalculationResult) {
        renderChart(state.lastCalculationResult, "top");
      }
    });
    btnChartBottom.addEventListener("click", () => {
      btnChartBottom.classList.add("active");
      btnChartTop.classList.remove("active");
      if (state.lastCalculationResult) {
        renderChart(state.lastCalculationResult, "bottom");
      }
    });
  }

  // 2단계: 분석 도구 직접 설정 및 실행 버튼
  const btnRunManualTool = document.getElementById("btnRunManualTool");
  if (btnRunManualTool) {
    btnRunManualTool.addEventListener("click", () => runManualTool());
  }

  // 2단계: 분석 도구 선택 변경 시 필드 표시 동적 갱신
  const manualToolSelect = document.getElementById("manualToolSelect");
  if (manualToolSelect) {
    manualToolSelect.addEventListener("change", () => updateManualToolFields());
  }

  // 3단계: 차트 이미지 PNG 다운로드 버튼
  const btnDownloadChartPng = document.getElementById("btnDownloadChartPng");
  if (btnDownloadChartPng) {
    btnDownloadChartPng.addEventListener("click", () => downloadChartPng());
  }

  // 4단계: 마크다운 파일 다운로드 버튼
  const btnDownloadMd = document.getElementById("btnDownloadMd");
  if (btnDownloadMd) {
    btnDownloadMd.addEventListener("click", () => downloadMarkdownFile());
  }

  // 4단계: 인쇄 및 PDF 저장 버튼
  const btnExportPdf = document.getElementById("btnExportPdf");
  if (btnExportPdf) {
    btnExportPdf.addEventListener("click", () => exportPdfReport());
  }

  // 4단계: 독립형 HTML 보고서 다운로드 버튼
  const btnExportHtml = document.getElementById("btnExportHtml");
  if (btnExportHtml) {
    btnExportHtml.addEventListener("click", () => exportStandaloneHtmlReport());
  }

  // 4단계: 후속 질문 칩 클릭 시 입력창 채우기 (자동 제출 안 함, 사용자 주도성 존중)
  document.querySelectorAll(".followup-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const input = document.getElementById("inputFollowupQuery");
      if (input && chip.dataset.query) {
        input.value = chip.dataset.query;
        input.focus();
      }
    });
  });

  // 4단계: 후속 질문 제출 버튼 및 Enter 키
  const btnSubmitFollowup = document.getElementById("btnSubmitFollowup");
  const inputFollowupQuery = document.getElementById("inputFollowupQuery");
  if (btnSubmitFollowup && inputFollowupQuery) {
    btnSubmitFollowup.addEventListener("click", () => submitFollowupQuery());
    inputFollowupQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submitFollowupQuery();
    });
  }
}

/**
 * 파일 선택 처리
 */
function handleFileSelected(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    alert("오류: .csv 확장자의 파일만 선택할 수 있습니다.");
    console.error("[ERROR] 확장자 불일치:", file.name);
    return;
  }

  state.selectedFile = file;
  const sizeKb = (file.size / 1024).toFixed(1);
  console.log(`[UPLOAD] 파일 선택: name=${file.name}, size=${sizeKb}KB`);

  document.getElementById("selectedFileName").textContent = file.name;
  document.getElementById("selectedFileSize").textContent = `(${sizeKb} KB)`;
  document.getElementById("selectedFileBar").style.display = "flex";
  document.getElementById("inspectResults").style.display = "none";
}

/**
 * 단계 네비게이션 활성화
 */
function activateStep(stepNum) {
  for (let i = 1; i <= 4; i++) {
    const indicator = document.getElementById(`stepIndicator${i}`);
    const section = document.getElementById(`sectionStep${i}`);
    if (i <= stepNum) {
      indicator.classList.add("active");
    } else {
      indicator.classList.remove("active");
    }
    if (section) {
      if (i <= stepNum) {
        section.style.display = "block";
      }
    }
  }
}

/**
 * STEP 1: POST /inspect 실행
 */
async function startInspect() {
  if (!state.selectedFile) {
    alert("진단할 CSV 파일을 먼저 선택해 주세요.");
    return;
  }

  const btnInspect = document.getElementById("btnInspect");
  btnInspect.disabled = true;
  btnInspect.textContent = "⏳ 진단 중...";
  console.log("[INSPECT] 진단 요청 시작");

  const formData = new FormData();
  formData.append("file", state.selectedFile);

  try {
    const res = await fetch(`${API_BASE}/inspect`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "진단 처리 중 오류가 발생했습니다.");
    }

    state.diagnostics = data.diagnostics;
    const d = state.diagnostics;
    console.log(`[INSPECT] 응답 수신: rows=${d.rows}, cols=${d.columns}, warnings=${d.warnings.length}`);

    // UI 렌더링
    renderInspectResults(d);
  } catch (err) {
    console.error("[ERROR] 진단 오류:", err);
    if (err.message && (err.message.includes("Failed to fetch") || err.name === "TypeError")) {
      alert("진단 실패: 서버와 통신할 수 없습니다.\n\n네트워크 연결 및 서버 동작 상태를 확인해 주세요.");
    } else {
      alert(`진단 실패: ${err.message}`);
    }
  } finally {
    btnInspect.disabled = false;
    btnInspect.textContent = "🔍 데이터 진단 시작";
  }
}

/**
 * 진단 결과 UI 렌더링
 */
function renderInspectResults(d) {
  document.getElementById("mRowsCols").textContent = `${d.rows.toLocaleString()}행 × ${d.columns}열`;
  document.getElementById("mEncodingSkip").textContent = `${d.encoding} (헤더까지 ${d.skiprows}줄 건너뜀)`;
  document.getElementById("mRecYear").textContent = d.recommended_year ? `${d.recommended_year}년` : "연도 미감지";
  document.getElementById("mAggregates").textContent = `${d.aggregate_candidates.length}개 발견`;

  // 경고 표시
  const alertBox = document.getElementById("warningAlertBox");
  const warningList = document.getElementById("warningList");
  warningList.innerHTML = "";
  if (d.warnings && d.warnings.length > 0) {
    d.warnings.forEach(w => {
      const li = document.createElement("li");
      li.textContent = w;
      warningList.appendChild(li);
    });
    alertBox.style.display = "block";
  } else {
    alertBox.style.display = "none";
  }

  // 미리보기 테이블 렌더링 (상위 10행)
  renderPreviewTable(d.preview, d.column_names);

  // 데이터 주제에 맞게 질문창 플레이스홀더 1차 갱신
  if (d.topic_hints) {
    let title = "";
    for (const k of ["STRUCTURE_NAME", "Measure", "Indicator Name", "INDICATOR_NAME", "Title"]) {
      if (d.topic_hints[k] && d.topic_hints[k][0]) {
        title = d.topic_hints[k][0].substring(0, 30);
        break;
      }
    }
    const inputCustomQuery = document.getElementById("inputCustomQuery");
    if (inputCustomQuery && title) {
      const yr = d.recommended_year ? `${d.recommended_year}년 ` : "";
      inputCustomQuery.placeholder = `예: ${yr}'${title}' 기준 상위 10개국과 한국의 위치를 알려줘`;
    }
  }

  // 2단계 직접 설정 필드 datalist 및 기본값 주입
  populateManualConfigOptions(d);

  document.getElementById("inspectResults").style.display = "block";
  document.getElementById("inspectResults").scrollIntoView({ behavior: "smooth" });
}

/**
 * 2단계: 분석 도구 직접 설정 datalist 및 기본값 채우기
 */
function populateManualConfigOptions(d) {
  if (!d) return;

  // 1) 기준 시점 datalist 채우기
  const listRef = document.getElementById("listRefPeriods");
  const inputRef = document.getElementById("manualRefPeriod");
  if (listRef) {
    listRef.innerHTML = "";
    const periods = new Set();
    if (d.recommended_year) periods.add(String(d.recommended_year));
    if (d.year_columns) d.year_columns.forEach(y => periods.add(String(y)));
    if (d.numeric_columns) d.numeric_columns.forEach(n => periods.add(String(n)));
    if (periods.size === 0) periods.add("2024");

    periods.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p;
      listRef.appendChild(opt);
    });

    if (inputRef && !inputRef.value) {
      inputRef.value = d.recommended_year || (d.year_columns && d.year_columns.length > 0 ? d.year_columns[d.year_columns.length - 1] : "2024");
    }
  }

  // 2) 비교 대상 국가/항목 datalist 채우기
  const listTarget = document.getElementById("listTargetItems");
  const inputTarget = document.getElementById("manualTargetItem");
  if (listTarget) {
    listTarget.innerHTML = "";
    const items = new Set(["Korea", "Korea, Rep.", "United States", "Japan", "Germany", "United Kingdom", "France", "Australia", "Canada", "Mexico", "China"]);

    // 미리보기 행에서 텍스트 라벨 수집
    if (d.preview && d.preview.length > 0) {
      const labelCol = d.text_columns && d.text_columns.length > 0 ? d.text_columns[0] : null;
      if (labelCol) {
        d.preview.forEach(row => {
          if (row[labelCol]) items.add(String(row[labelCol]));
        });
      }
    }

    items.forEach(it => {
      const opt = document.createElement("option");
      opt.value = it;
      listTarget.appendChild(opt);
    });

    if (inputTarget && !inputTarget.value) {
      let defaultKorea = "Korea";
      if (d.preview && d.preview.some(r => Object.values(r).some(v => String(v).includes("Korea, Rep.")))) {
        defaultKorea = "Korea, Rep.";
      }
      inputTarget.value = defaultKorea;
    }
  }

  updateManualToolFields();
}

/**
 * 선택한 분석 도구에 맞춰 필요한 입력 필드 동적 갱신
 */
function updateManualToolFields() {
  const toolSelect = document.getElementById("manualToolSelect");
  if (!toolSelect) return;
  const tool = toolSelect.value;

  const fieldTarget = document.getElementById("fieldTargetItem");
  const fieldRankN = document.getElementById("fieldRankN");
  const hintRef = document.getElementById("hintRefPeriod");

  if (tool === "compare_one_vs_all") {
    if (fieldTarget) fieldTarget.style.display = "flex";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "비교할 기준 연도 또는 수치 열을 지정하세요.";
  } else if (tool === "top_bottom_n") {
    if (fieldTarget) fieldTarget.style.display = "none";
    if (fieldRankN) fieldRankN.style.display = "flex";
    if (hintRef) hintRef.textContent = "순위를 매길 기준 연도(수치) 열을 지정하세요.";
  } else if (tool === "trend_line") {
    if (fieldTarget) fieldTarget.style.display = "flex";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "시계열 구간의 시작/기준 연도를 지정하세요 (비워두면 전체).";
  } else if (tool === "forecast_trend") {
    if (fieldTarget) fieldTarget.style.display = "flex";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "예측 대상 국가/항목을 선택하세요 (비워두면 한국 또는 첫 번째 항목).";
  } else if (tool === "correlation_matrix") {
    if (fieldTarget) fieldTarget.style.display = "none";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "수치형 지표/연도 간 상관계수가 자동으로 일괄 계산됩니다.";
  } else if (tool === "group_summary") {
    if (fieldTarget) fieldTarget.style.display = "none";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "집계할 기준 연도 또는 수치 열을 지정하세요.";
  } else {
    if (fieldTarget) fieldTarget.style.display = "none";
    if (fieldRankN) fieldRankN.style.display = "none";
    if (hintRef) hintRef.textContent = "분석에 사용할 기준 시점(연도)을 지정하세요.";
  }
}

/**
 * 2단계: 분석 도구 직접 설정 실행
 */
async function runManualTool() {
  const toolSelect = document.getElementById("manualToolSelect");
  const inputRef = document.getElementById("manualRefPeriod");
  const inputTarget = document.getElementById("manualTargetItem");
  const inputRankN = document.getElementById("manualRankN");
  const checkExcludeAgg = document.getElementById("manualExcludeAgg");
  const btn = document.getElementById("btnRunManualTool");

  if (!toolSelect) return;
  const tool = toolSelect.value;
  const refPeriod = inputRef ? inputRef.value.trim() : "";
  const targetItem = inputTarget ? inputTarget.value.trim() : "";
  const rankN = inputRankN ? parseInt(inputRankN.value) || 10 : 10;
  const excludeAgg = checkExcludeAgg ? checkExcludeAgg.checked : true;

  const params = {
    exclude_aggregates: excludeAgg
  };

  if (refPeriod) {
    params.reference_period = refPeriod;
  }
  if (targetItem && (tool === "compare_one_vs_all" || tool === "trend_line" || tool === "forecast_trend")) {
    params.target_item = targetItem;
    if (tool === "trend_line") {
      params.items = [targetItem];
    }
  }
  if (tool === "top_bottom_n") {
    params.n = rankN;
  }

  // 3단계 섹션 활성화 및 스크롤
  activateStep(3);
  const sectionStep3 = document.getElementById("sectionStep3");
  if (sectionStep3) {
    sectionStep3.scrollIntoView({ behavior: "smooth" });
  }

  btn.disabled = true;
  btn.textContent = "⏳ 정밀 계산 실행 중...";
  console.log(`[MANUAL_RUN] 도구 직접 실행: tool=${tool}`, params);

  try {
    const res = await fetch(`${API_BASE}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, params })
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "분석 도구 실행에 실패했습니다.");
    }

    renderCalculationResult(data.result);
  } catch (err) {
    console.error("[ERROR] 도구 직접 실행 실패:", err);
    alert(`도구 실행 오류: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ 직접 설정한 도구로 분석 실행하기";
  }
}

function renderPreviewTable(records, columns) {
  const thead = document.getElementById("previewTableHead");
  const tbody = document.getElementById("previewTableBody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!records || records.length === 0) return;

  // 테이블 헤더 (최대 12개 열 우선 표시)
  const displayCols = columns.slice(0, 12);
  displayCols.forEach(col => {
    const th = document.createElement("th");
    th.textContent = col;
    thead.appendChild(th);
  });
  if (columns.length > 12) {
    const thMore = document.createElement("th");
    thMore.textContent = `... 외 ${columns.length - 12}개 열`;
    thead.appendChild(thMore);
  }

  // 테이블 행
  records.forEach(row => {
    const tr = document.createElement("tr");
    displayCols.forEach(col => {
      const td = document.createElement("td");
      const val = row[col];
      td.textContent = (val !== null && val !== undefined) ? String(val) : "-";
      tr.appendChild(td);
    });
    if (columns.length > 12) {
      const tdMore = document.createElement("td");
      tdMore.textContent = "...";
      tr.appendChild(tdMore);
    }
    tbody.appendChild(tr);
  });
}

/**
 * STEP 2: POST /suggest 실행
 */
async function startSuggest() {
  activateStep(2);
  const loading = document.getElementById("suggestLoading");
  const container = document.getElementById("suggestionsContainer");
  const btnSuggest = document.getElementById("btnRequestSuggest");

  loading.style.display = "block";
  container.innerHTML = "";
  btnSuggest.disabled = true;
  document.getElementById("sectionStep2").scrollIntoView({ behavior: "smooth" });

  console.log("[SUGGEST] 제안 요청 시작");

  try {
    const res = await fetch(`${API_BASE}/suggest`, { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "분석 제안 수신 실패");
    }

    state.suggestions = data.suggestions || [];
    state.recommendedQuestions = data.recommended_questions || [];
    console.log(`[SUGGEST] 응답 수신: 제안 개수=${state.suggestions.length}, 추천질문=${state.recommendedQuestions.length}`);
    renderSuggestions(state.suggestions);

    if (state.recommendedQuestions && state.recommendedQuestions.length > 0) {
      renderRecommendedQuestions(state.recommendedQuestions);
    }
  } catch (err) {
    console.error("[ERROR] 제안 요청 오류:", err);
    alert(`제안 수신 실패: ${err.message}`);
  } finally {
    loading.style.display = "none";
    btnSuggest.disabled = false;
  }
}

/**
 * 도구 제안 카드 렌더링
 */
function renderSuggestions(suggestions) {
  const container = document.getElementById("suggestionsContainer");
  container.innerHTML = "";

  if (suggestions.length === 0) {
    container.innerHTML = "<p>제안된 분석 도구가 없습니다.</p>";
    return;
  }

  suggestions.forEach((sug, idx) => {
    const card = document.createElement("div");
    card.className = "suggestion-card";

    const periodBadge = sug.reference_period ? `<span class="sugg-period-badge">기준: ${sug.reference_period}</span>` : "";

    card.innerHTML = `
      <div class="card-top">
        ${periodBadge}
        <h3 class="sugg-tool-name">${idx + 1}. ${formatToolName(sug.tool)}</h3>
        <p class="sugg-why"><strong>💡 제안 이유:</strong> ${sug.why || "-"}</p>
        <p class="sugg-caution"><strong>⚠️ 해석 시 주의:</strong> ${sug.caution || "-"}</p>
      </div>
      <button class="btn btn-primary" onclick="executeToolByIndex(${idx})">
        ▶ 이 분석 실행하기
      </button>
    `;
    container.appendChild(card);
  });
}

function formatToolName(tool) {
  const map = {
    "reshape_wide_to_long": "시계열 변환 (가로 연도 열을 세로 데이터로 접기)",
    "quality_report": "데이터 품질 성적표 (빈칸·중복·비어있는 열 검사)",
    "year_coverage": "연도별 데이터 충실도 & 가장 추천하는 기준연도",
    "detect_aggregates": "가짜 국가 걸러내기 (World·OECD 등 묶음 통계 행 탐지)",
    "describe_numeric": "기초 통계 요약 (평균 · 중앙값 · 1등과 꼴찌 점수)",
    "trend_line": "주요 국가 연도별 성장 추이 (꺾은선 그래프)",
    "top_bottom_n": "상위 · 하위 순위 TOP 비교 (가로 막대 그래프)",
    "group_summary": "그룹별 평균 및 합계 비교 (막대 그래프)",
    "change_rate": "두 시점 사이 성장률 & 변화량 비교",
    "distribution": "점수대별 국가 분포 현황 (히스토그램)",
    "correlation_scatter": "두 지표 간의 관련성 탐색 (산점도 그래프)",
    "compare_one_vs_all": "우리나라(한국) vs 전 세계 전체 평균 비교",
    "detect_outliers": "이상치 탐지 (평균에서 크게 벗어난 특이값 국가)",
    "forecast_trend": "시계열 미래 추세 예측 (향후 3~5년 전망 및 신뢰구간)",
    "correlation_matrix": "전체 상관관계 히트맵 매트릭스 (지표/연도 간 관련성)"
  };
  return map[tool] || tool;
}

/**
 * 추천 질문 칩 동적 렌더링 (데이터셋 주제 기반 맞춤 생성)
 */
function renderRecommendedQuestions(questions) {
  const container = document.getElementById("queryChipsContainer");
  const inputCustomQuery = document.getElementById("inputCustomQuery");
  if (!container || !questions || questions.length === 0) return;

  container.innerHTML = '<span class="chip-label">추천 질문:</span>';
  questions.forEach(qItem => {
    const btn = document.createElement("button");
    btn.className = "query-chip";
    btn.dataset.q = qItem.query;
    btn.textContent = qItem.label || qItem.query;
    btn.addEventListener("click", () => {
      if (inputCustomQuery) {
        inputCustomQuery.value = qItem.query;
        inputCustomQuery.focus();
      }
    });
    container.appendChild(btn);
  });

  if (inputCustomQuery && questions[0] && questions[0].query) {
    inputCustomQuery.placeholder = `예: ${questions[0].query}`;
  }
}

/**
 * STEP 3: POST /run 실행 (인덱스로 호출)
 */
window.executeToolByIndex = async function(idx) {
  const suggestion = state.suggestions[idx];
  if (!suggestion) return;

  state.selectedSuggestion = suggestion;
  activateStep(3);

  const sectionStep3 = document.getElementById("sectionStep3");
  sectionStep3.scrollIntoView({ behavior: "smooth" });

  console.log(`[RUN] 도구 실행 시작: tool=${suggestion.tool}, period=${suggestion.reference_period}`);

  try {
    const res = await fetch(`${API_BASE}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool: suggestion.tool,
        params: suggestion.params || {}
      })
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "도구 실행 실패");
    }

    state.calculationResult = data.result;
    console.log(`[RUN] 결과 수신: tool=${data.result.tool}, used=${data.result.used_rows}, excluded=${data.result.excluded_rows}`);

    // UI 렌더링 및 차트 생성
    renderCalculationResult(data.result);
  } catch (err) {
    console.error("[ERROR] 도구 실행 오류:", err);
    alert(`도구 실행 오류: ${err.message}`);
  }
};

/**
 * 계산 결과 및 Chart.js 렌더링
 */
function renderCalculationResult(result) {
  state.lastCalculationResult = result;

  document.getElementById("resToolName").textContent = formatToolName(result.tool);
  document.getElementById("resRefPeriod").textContent = result.reference_period || "전체";
  document.getElementById("resUsedRows").textContent = `${result.used_rows.toLocaleString()}개`;
  document.getElementById("resExcludedRows").textContent = `${result.excluded_rows.toLocaleString()}개`;
  document.getElementById("resExclusionReason").textContent = result.exclusion_reason || "없음";

  // 상세 계산 수치 요약 텍스트
  const box = document.getElementById("calcDataContent");
  if (result.tool === "forecast_trend" && result.data && result.data.metrics) {
    const m = result.data.metrics;
    const tableRows = (result.data.forecast_table || []).map(f => `
      <tr>
        <td style="padding:0.6rem; font-weight:700; color:#4338ca; border:1px solid #cbd5e1;">${f.year}년</td>
        <td style="padding:0.6rem; font-weight:800; color:#1e293b; border:1px solid #cbd5e1;">${f.predicted}</td>
        <td style="padding:0.6rem; color:#64748b; border:1px solid #cbd5e1;">${f.lower_95}</td>
        <td style="padding:0.6rem; color:#64748b; border:1px solid #cbd5e1;">${f.upper_95}</td>
      </tr>
    `).join("");

    box.innerHTML = `
      <div class="forecast-summary-grid">
        <div class="forecast-card">
          <span class="forecast-label">🎯 대상 항목</span>
          <span class="forecast-val" style="font-size:1.05rem;">${escapeHtml(result.data.target_item)}</span>
        </div>
        <div class="forecast-card">
          <span class="forecast-label">🔮 미래 추세 방향</span>
          <span class="forecast-val" style="color:#2563eb; font-size:1.05rem;">${escapeHtml(m.trend_description)}</span>
        </div>
        <div class="forecast-card">
          <span class="forecast-label">📈 연평균 성장률(CAGR)</span>
          <span class="forecast-val" style="color:${m.cagr_percent >= 0 ? '#10b981' : '#ef4444'};">${m.cagr_percent}%</span>
        </div>
        <div class="forecast-card">
          <span class="forecast-label">📐 모델 신뢰도 (R²)</span>
          <span class="forecast-val" style="color:#7c3aed;">${m.r_squared} <small style="font-size:0.75rem; color:#64748b;">(${escapeHtml(m.confidence_level)})</small></span>
        </div>
      </div>
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:1rem; margin-top:0.75rem;">
        <h4 style="font-size:0.9rem; font-weight:700; color:#1e293b; margin:0 0 0.5rem 0;">📅 미래 시점별 세부 예측치 및 95% 신뢰구간</h4>
        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse; font-size:0.85rem; text-align:center;">
            <thead>
              <tr style="background:#f8fafc; border-bottom:1.5px solid #cbd5e1;">
                <th style="padding:0.6rem; border:1px solid #cbd5e1;">예측 연도</th>
                <th style="padding:0.6rem; border:1px solid #cbd5e1;">미래 추정치</th>
                <th style="padding:0.6rem; border:1px solid #cbd5e1;">95% 신뢰구간 하한</th>
                <th style="padding:0.6rem; border:1px solid #cbd5e1;">95% 신뢰구간 상한</th>
              </tr>
            </thead>
            <tbody>${tableRows}</tbody>
          </table>
        </div>
      </div>
    `;
  } else if (result.tool === "correlation_matrix" && result.data && result.data.matrix) {
    const cols = result.data.columns || [];
    const mat = result.data.matrix || [];

    const topPosHtml = (result.data.top_positive_pairs || []).map(p => `
      <div style="background:#ecfdf5; border:1px solid #a7f3d0; border-radius:6px; padding:0.5rem 0.75rem; font-size:0.82rem;">
        <strong style="color:#065f46;">${escapeHtml(p.pair_name)}</strong>
        <span style="float:right; font-weight:800; color:#047857;">r = +${p.correlation}</span>
        <div style="color:#047857; font-size:0.75rem; margin-top:2px;">${escapeHtml(p.interpretation)}</div>
      </div>
    `).join("");

    const topNegHtml = (result.data.top_negative_pairs || []).map(p => `
      <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:0.5rem 0.75rem; font-size:0.82rem;">
        <strong style="color:#991b1b;">${escapeHtml(p.pair_name)}</strong>
        <span style="float:right; font-weight:800; color:#b91c1c;">r = ${p.correlation}</span>
        <div style="color:#b91c1c; font-size:0.75rem; margin-top:2px;">${escapeHtml(p.interpretation)}</div>
      </div>
    `).join("");

    let thHeaders = `<th class="heatmap-th">변수 \\ 지표</th>`;
    cols.forEach(c => {
      thHeaders += `<th class="heatmap-th">${escapeHtml(c)}</th>`;
    });

    let trRows = "";
    mat.forEach((rowVals, rIdx) => {
      let tdCells = `<th class="heatmap-th-row">${escapeHtml(cols[rIdx])}</th>`;
      rowVals.forEach((val, cIdx) => {
        let bg = "#f8fafc";
        let color = "#1e293b";
        if (rIdx === cIdx) {
          bg = "#e2e8f0";
          color = "#475569";
        } else if (val > 0) {
          const alpha = Math.min(0.9, Math.abs(val) * 0.75 + 0.15);
          bg = `rgba(16, 185, 129, ${alpha})`;
          if (alpha > 0.5) color = "#ffffff";
        } else if (val < 0) {
          const alpha = Math.min(0.9, Math.abs(val) * 0.75 + 0.15);
          bg = `rgba(239, 68, 68, ${alpha})`;
          if (alpha > 0.5) color = "#ffffff";
        }
        tdCells += `<td class="heatmap-cell" style="background:${bg}; color:${color};" title="${cols[rIdx]} ↔ ${cols[cIdx]}: r = ${val}">${val.toFixed(2)}</td>`;
      });
      trRows += `<tr>${tdCells}</tr>`;
    });

    box.innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:0.75rem; margin-bottom:1rem;">
        <div style="display:flex; flex-direction:column; gap:0.4rem;">
          <h5 style="margin:0; font-size:0.85rem; font-weight:700; color:#065f46;">🟢 가장 밀접한 양의 상관관계 TOP 3</h5>
          ${topPosHtml || "<p style='font-size:0.8rem; color:#94a3b8;'>해당 없음</p>"}
        </div>
        <div style="display:flex; flex-direction:column; gap:0.4rem;">
          <h5 style="margin:0; font-size:0.85rem; font-weight:700; color:#991b1b;">🔴 가장 뚜렷한 반비례(음의 상관) TOP 3</h5>
          ${topNegHtml || "<p style='font-size:0.8rem; color:#94a3b8;'>해당 없음</p>"}
        </div>
      </div>
      <div class="heatmap-container">
        <table class="heatmap-table">
          <thead><tr>${thHeaders}</tr></thead>
          <tbody>${trRows}</tbody>
        </table>
      </div>
      <div class="heatmap-legend">
        <span class="legend-chip"><span class="legend-color-box" style="background:#10b981;"></span> 강한 양의 상관 (함께 증가)</span>
        <span class="legend-chip"><span class="legend-color-box" style="background:#e2e8f0;"></span> 무상관 (0 근처)</span>
        <span class="legend-chip"><span class="legend-color-box" style="background:#ef4444;"></span> 강한 음의 상관 (반비례)</span>
      </div>
    `;
  } else if (result.tool === "compare_one_vs_all" && result.data) {
    const d = result.data;
    const diffSign = d.diff_from_mean >= 0 ? "+" : "";
    const diffColor = d.diff_from_mean >= 0 ? "#10b981" : "#ef4444";
    const rankText = d.target_rank ? `전체 ${d.total_entities_count || ""}개국 중 <strong>${d.target_rank}위</strong>` : "-";

    box.innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:0.6rem; margin-bottom:0.6rem;">
        <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:0.65rem; text-align:center;">
          <span style="font-size:0.75rem; font-weight:600; color:#1e40af;">🎯 ${escapeHtml(d.target_item)}</span>
          <span style="font-size:1.25rem; font-weight:800; color:#1d4ed8; display:block; margin-top:0.2rem;">${d.target_value}점</span>
          <span style="font-size:0.75rem; color:#475569; display:block; margin-top:0.15rem;">${rankText}</span>
        </div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:0.65rem; text-align:center;">
          <span style="font-size:0.75rem; font-weight:600; color:#64748b;">📊 전체 평균 vs 중앙값</span>
          <span style="font-size:1.1rem; font-weight:700; color:#334155; display:block; margin-top:0.2rem;">평균 ${d.overall_mean}점</span>
          <span style="font-size:0.75rem; color:${diffColor}; font-weight:700; display:block; margin-top:0.15rem;">(평균 대비 ${diffSign}${d.diff_from_mean}점)</span>
        </div>
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:0.65rem; text-align:center;">
          <span style="font-size:0.75rem; font-weight:600; color:#166534;">🥇 1위 (최고 청렴국)</span>
          <span style="font-size:1.05rem; font-weight:700; color:#15803d; display:block; margin-top:0.2rem;">${d.highest_country ? escapeHtml(d.highest_country.name) : "-"}</span>
          <span style="font-size:0.75rem; color:#166534; display:block; margin-top:0.15rem;">${d.highest_country ? d.highest_country.value + "점" : ""}</span>
        </div>
        <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:0.65rem; text-align:center;">
          <span style="font-size:0.75rem; font-weight:600; color:#991b1b;">⚠️ 최하위 (최저점/부패위험)</span>
          <span style="font-size:1.05rem; font-weight:700; color:#b91c1c; display:block; margin-top:0.2rem;">${d.lowest_country ? escapeHtml(d.lowest_country.name) : "-"}</span>
          <span style="font-size:0.75rem; color:#991b1b; display:block; margin-top:0.15rem;">${d.lowest_country ? d.lowest_country.value + "점" : ""}</span>
        </div>
      </div>
      <details style="font-size:0.78rem; color:#64748b; margin-top:0.35rem; cursor:pointer;">
        <summary style="font-weight:600;">🔍 원본 수치 JSON 데이터 보기</summary>
        <pre style="font-size:0.75rem; background:#fff; padding:0.6rem; border-radius:6px; border:1px solid #e2e8f0; margin-top:0.3rem; max-height:160px; overflow-y:auto;">${JSON.stringify(result.data, null, 2)}</pre>
      </details>
    `;
  } else {
    box.innerHTML = `
      <details open style="font-size:0.82rem;">
        <summary style="font-weight:600; margin-bottom:0.35rem; cursor:pointer;">📊 통계 계산 수치 요약</summary>
        <pre style="font-size:0.8rem; background:#fff; padding:0.6rem 0.8rem; border-radius:6px; border:1px solid #e2e8f0; max-height:180px; overflow-y:auto;">${JSON.stringify(result.data, null, 2)}</pre>
      </details>
    `;
  }

  // 순위 차트 컨트롤 토글 (top_bottom_n일 때만 노출)
  const chartControls = document.getElementById("chartControls");
  const btnChartTop = document.getElementById("btnChartTop");
  const btnChartBottom = document.getElementById("btnChartBottom");
  if (chartControls) {
    if (result.data && result.data.chart_top && result.data.chart_bottom) {
      chartControls.style.display = "block";
      if (btnChartTop) btnChartTop.classList.add("active");
      if (btnChartBottom) btnChartBottom.classList.remove("active");
    } else {
      chartControls.style.display = "none";
    }
  }

  // Chart.js 렌더링 (기본 상위)
  renderChart(result, "top");
}

function renderChart(result, subView = "top") {
  const canvas = document.getElementById("chartCanvas");
  const ctx = canvas.getContext("2d");

  // 이전 차트 인스턴스 파기
  if (state.chartInstance) {
    state.chartInstance.destroy();
    state.chartInstance = null;
  }

  if (!result || !result.data) {
    canvas.style.display = "none";
    return;
  }

  let chartData = null;
  if (subView === "bottom" && result.data.chart_bottom) {
    chartData = result.data.chart_bottom;
  } else if (result.data.chart_top) {
    chartData = result.data.chart_top;
  } else {
    chartData = result.data.chart;
  }

  if (!chartData) {
    console.log("[CHART] 이 도구는 별도 차트 데이터가 없으므로 표 형태로 표시합니다.");
    canvas.style.display = "none";
    return;
  }

  canvas.style.display = "block";
  const chartType = chartData.type || "bar";
  const indexAxis = chartData.indexAxis || "x";
  const isHorizontal = indexAxis === "y";

  // 기본 색상 팔레트
  const defaultColors = [
    "#2563eb", "#7c3aed", "#10b981", "#f59e0b", "#ef4444",
    "#06b6d4", "#ec4899", "#8b5cf6", "#14b8a6", "#f97316"
  ];

  // 데이터셋 스타일 보정
  const datasets = (chartData.datasets || []).map((ds, idx) => {
    let bg = ds.backgroundColor;
    let border = ds.borderColor;

    if (!bg) {
      if (chartType === "line") {
        bg = "rgba(37,99,235,0.1)";
        border = "#2563eb";
      } else if (chartData.labels && chartData.labels.length > 1 && (!ds.data || ds.data.length > 1)) {
        // 막대가 여러 개이고 단일 데이터셋인 경우 막대마다 고유 색상 부여
        bg = chartData.labels.map((_, i) => defaultColors[i % defaultColors.length]);
        border = bg;
      } else {
        bg = defaultColors[idx % defaultColors.length];
        border = bg;
      }
    }

    return {
      ...ds,
      backgroundColor: bg,
      borderColor: border || bg,
      borderWidth: ds.borderWidth || (chartType === "line" ? 2 : 1),
      tension: 0.2
    };
  });

  // 축 스케일링 설정 (수평/수직 막대 정밀 구분 및 0점 왜곡 방지)
  const isPercent = (result.unit && (result.unit.includes("%") || result.unit.includes("비율"))) ||
                    (result.data && (result.data.is_percentage || (result.data.max && result.data.max <= 100)));

  let scalesConfig = {};
  if (chartType === "scatter") {
    scalesConfig = {
      x: { type: "linear", position: "bottom", grid: { color: "#f1f5f9" } },
      y: { type: "linear", grid: { color: "#f1f5f9" } }
    };
  } else if (isHorizontal) {
    // 수평 막대: x축이 수치, y축이 카테고리
    scalesConfig = {
      x: {
        beginAtZero: true,
        ...(isPercent ? { suggestedMax: 100 } : {}),
        grid: { color: "#f1f5f9" }
      },
      y: {
        grid: { display: false }
      }
    };
  } else {
    // 수직 막대 및 라인: y축이 수치, x축이 카테고리
    scalesConfig = {
      y: {
        beginAtZero: chartType === "bar",
        ...(isPercent ? { suggestedMax: 100 } : {}),
        grid: { color: "#f1f5f9" }
      },
      x: {
        grid: { display: false }
      }
    };
  }

  state.chartInstance = new Chart(ctx, {
    type: chartType,
    data: {
      labels: chartData.labels || [],
      datasets: datasets
    },
    options: {
      indexAxis: indexAxis,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: datasets.length > 1 || chartType === "line" },
        tooltip: {
          enabled: true,
          callbacks: {
            label: function(context) {
              const val = context.raw;
              const unitStr = result.unit ? ` (${result.unit})` : "";
              return ` ${context.dataset.label || ""}: ${val !== null && val !== undefined ? val : "N/A"}${unitStr}`;
            }
          }
        }
      },
      scales: scalesConfig
    }
  });

  console.log(`[CHART] 차트 렌더 완료 (종류: ${chartType}, subView: ${subView})`);
}

/**
 * A/B 모드 전환
 */
function setExplainMode(mode) {
  state.currentMode = mode;
  const btnA = document.getElementById("btnTabModeA");
  const btnB = document.getElementById("btnTabModeB");
  const descText = document.getElementById("modeDescText");

  if (mode === "A") {
    btnA.classList.add("active");
    btnB.classList.remove("active");
    descText.innerHTML = "<strong>모드 A (비교용 모드):</strong> 계산 결과를 일절 주지 않고 진단 요약만 준 채 보고서를 작성하게 합니다. AI가 숫자를 어떻게 추정하거나 지어내는지(환각) 관찰해 보세요.";
  } else {
    btnB.classList.add("active");
    btnA.classList.remove("active");
    descText.innerHTML = "<strong>모드 B (정식 모드):</strong> Pandas가 계산한 결과만을 제공하며, 계산 결과에 없는 숫자는 언급하지 못하도록 8대 엄격 규칙을 강제합니다.";
  }
}

/**
 * STEP 4: POST /explain 실행
 */
async function startExplain() {
  const loading = document.getElementById("explainLoading");
  const reportBox = document.getElementById("reportBox");
  const reportContent = document.getElementById("reportContent");
  const btnRun = document.getElementById("btnRunExplain");

  loading.style.display = "block";
  reportBox.style.display = "none";
  btnRun.disabled = true;

  console.log(`[EXPLAIN] 해석 요청 시작 (모드: ${state.currentMode})`);

  try {
    const res = await fetch(`${API_BASE}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: state.currentMode,
        calculation_result: state.calculationResult,
        query: state.lastQuery || ""
      })
    });

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      console.error("[ERROR] JSON 파싱 불가 응답:", text.substring(0, 300));
      throw new Error(`서버 응답 오류 (HTTP ${res.status}): JSON 형식이 아닙니다.`);
    }

    if (!res.ok) {
      throw new Error(data.error || "해석 생성 실패");
    }

    console.log(`[EXPLAIN] 해석 응답 수신 완료 (길이: ${data.explanation.length})`);
    renderMarkdownReport(data.explanation, data.mode, data.model);
  } catch (err) {
    console.error("[ERROR] 해석 요청 오류:", err);
    alert(`해석 생성 실패: ${err.message}`);
  } finally {
    loading.style.display = "none";
    btnRun.disabled = false;
  }
}

/**
 * 마크다운 보고서 렌더링
 */
function renderMarkdownReport(rawMarkdown, mode, model) {
  const reportBox = document.getElementById("reportBox");
  const reportContent = document.getElementById("reportContent");
  const reportTitle = document.getElementById("reportTitle");
  const reportModelBadge = document.getElementById("reportModelBadge");

  state.currentReportMarkdown = rawMarkdown;

  reportTitle.textContent = mode === "A" ? "모드 A: 추정 기반 일반 보고서 (비교용)" : "모드 B: Pandas 계산 기반 정밀 팩트 보고서";
  reportModelBadge.textContent = `${model} (${mode === "A" ? "자유 모드" : "8대 엄격 모드"})`;

  // 간단한 마크다운 파서 (헤더, 볼드, 불릿 리스트, 줄바꿈)
  let html = rawMarkdown
    .replace(/^## (.*$)/gim, "<h2>$1</h2>")
    .replace(/^### (.*$)/gim, "<h3>$1</h3>")
    .replace(/\*\*(.*?)\*\*/gim, "<strong>$1</strong>")
    .replace(/^\* (.*$)/gim, "<li>$1</li>")
    .replace(/^- (.*$)/gim, "<li>$1</li>")
    .replace(/\n\n/gim, "<br><br>");

  // <li> 태그 묶기
  html = html.replace(/(<li>.*<\/li>)/gis, "<ul>$1</ul>");

  reportContent.innerHTML = html;
  reportBox.style.display = "block";
  reportBox.scrollIntoView({ behavior: "smooth" });
}

/**
 * 보고서 마크다운(.md) 파일로 다운로드
 */
function downloadMarkdownFile() {
  if (!state.currentReportMarkdown) {
    alert("다운로드할 분석 보고서 내용이 없습니다. 먼저 보고서를 생성해 주세요.");
    return;
  }

  const mode = state.currentMode === "A" ? "ModeA_Free" : "ModeB_FactBased";
  const toolName = state.calculationResult ? state.calculationResult.tool : "analysis";
  const dateStr = new Date().toISOString().slice(0, 10);
  const filename = `AI_Data_Insight_${toolName}_${mode}_${dateStr}.md`;

  // 메타데이터 헤더를 포함한 마크다운 문서 구성
  const header = `---
title: AI Data Insight Builder 분석 보고서
date: ${new Date().toLocaleString()}
mode: ${state.currentMode}
file: ${state.selectedFile ? state.selectedFile.name : "unknown"}
tool: ${toolName}
---

`;

  const fullContent = header + state.currentReportMarkdown;

  // Blob 객체 생성 및 가상 링크를 통한 다운로드 트리거
  const blob = new Blob([fullContent], { type: "text/markdown;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);

  console.log(`[DOWNLOAD] 마크다운 파일 다운로드 완료: ${filename}`);
}

/**
 * 차트 캔버스 이미지를 PNG 파일로 다운로드
 */
function downloadChartPng() {
  const canvas = document.getElementById("chartCanvas");
  if (!canvas || canvas.style.display === "none") {
    alert("저장할 차트가 화면에 표시되어 있지 않습니다.");
    return;
  }

  try {
    // 배경이 투명할 경우 뷰어에 따라 검게 보이는 현상 방지를 위해 흰 배경 합성
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    const tempCtx = tempCanvas.getContext("2d");
    tempCtx.fillStyle = "#ffffff";
    tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
    tempCtx.drawImage(canvas, 0, 0);

    const dataUrl = tempCanvas.toDataURL("image/png");
    const link = document.createElement("a");
    const toolName = state.lastCalculationResult ? state.lastCalculationResult.tool : "chart";
    link.download = `Data_Insight_Chart_${toolName}_${new Date().toISOString().slice(0, 10)}.png`;
    link.href = dataUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    console.log("[EXPORT] 차트 PNG 다운로드 완료");
  } catch (err) {
    console.error("[ERROR] 차트 이미지 다운로드 실패:", err);
    alert(`차트 이미지 저장 실패: ${err.message}`);
  }
}

/**
 * 인쇄 및 PDF 저장 (window.print() + 전용 인쇄 CSS)
 */
function exportPdfReport() {
  const reportBox = document.getElementById("reportBox");
  if (!reportBox || reportBox.style.display === "none") {
    alert("먼저 '4단계: 보고서 생성하기'를 실행하여 리포트를 작성해 주세요.");
    return;
  }
  window.print();
}

/**
 * 독립형 인터랙티브 HTML 보고서 파일 다운로드
 */
function exportStandaloneHtmlReport() {
  const reportBox = document.getElementById("reportBox");
  if (!reportBox || reportBox.style.display === "none") {
    alert("먼저 '4단계: 보고서 생성하기'를 실행하여 리포트를 작성해 주세요.");
    return;
  }

  // 1. 차트 캔버스를 Base64 이미지로 캡처
  const canvas = document.getElementById("chartCanvas");
  let chartImgTag = "";
  if (canvas && canvas.style.display !== "none") {
    try {
      const tempCanvas = document.createElement("canvas");
      tempCanvas.width = canvas.width;
      tempCanvas.height = canvas.height;
      const tempCtx = tempCanvas.getContext("2d");
      tempCtx.fillStyle = "#ffffff";
      tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
      tempCtx.drawImage(canvas, 0, 0);
      const chartDataUrl = tempCanvas.toDataURL("image/png");
      chartImgTag = `
        <div style="text-align:center; margin: 1.5rem 0; padding:1.25rem; background:#fff; border:1px solid #e2e8f0; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
          <img src="${chartDataUrl}" style="max-width:100%; height:auto; border-radius:6px;" alt="데이터 시각화 차트" />
        </div>
      `;
    } catch (e) {
      console.warn("[EXPORT] 차트 캡처 실패:", e);
    }
  }

  const tool = state.lastCalculationResult?.tool || "analysis";
  const toolNameKo = formatToolName(tool);
  const refPeriod = state.lastCalculationResult?.reference_period || "-";
  const fileName = state.selectedFile?.name || "데이터셋";
  const reportHtml = document.getElementById("reportContent")?.innerHTML || "";
  const calcDataHtml = document.getElementById("calcDataContent")?.innerHTML || "";
  const followupHtml = document.getElementById("followupChatList")?.innerHTML || "";

  const standaloneHtml = `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Data Insight 종합 분석 보고서 - ${escapeHtml(fileName)}</title>
  <style>
    :root {
      --primary: #2563eb;
      --primary-dark: #1e40af;
      --text: #0f172a;
      --text-muted: #64748b;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --border: #e2e8f0;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
      line-height: 1.65;
      color: var(--text);
      background-color: var(--bg);
      padding: 2.5rem 1rem;
      margin: 0;
    }
    .report-container {
      max-width: 920px;
      margin: 0 auto;
      background: var(--card-bg);
      padding: 3rem;
      border-radius: 14px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.06);
      border: 1px solid var(--border);
    }
    .header-section {
      border-bottom: 2px solid var(--primary);
      padding-bottom: 1.5rem;
      margin-bottom: 2rem;
    }
    .report-badge-top {
      display: inline-block;
      font-size: 0.78rem;
      font-weight: 700;
      color: #fff;
      background: linear-gradient(135deg, #2563eb, #7c3aed);
      padding: 0.3rem 0.8rem;
      border-radius: 20px;
      margin-bottom: 0.75rem;
    }
    h1 {
      font-size: 1.85rem;
      font-weight: 800;
      color: #0f172a;
      margin: 0 0 0.75rem 0;
      line-height: 1.3;
    }
    .meta-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      margin-top: 1rem;
    }
    .meta-tag {
      font-size: 0.82rem;
      font-weight: 600;
      padding: 0.35rem 0.8rem;
      border-radius: 6px;
      background: #eff6ff;
      color: #1e40af;
      border: 1px solid #bfdbfe;
    }
    h2 {
      font-size: 1.3rem;
      font-weight: 800;
      color: #1e3a8a;
      border-left: 4px solid var(--primary);
      padding-left: 0.75rem;
      margin-top: 2.5rem;
      margin-bottom: 1.25rem;
    }
    h3 {
      font-size: 1.1rem;
      font-weight: 700;
      color: #334155;
      margin-top: 1.5rem;
    }
    .content-card {
      background: #fdfdfd;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      font-size: 0.85rem;
    }
    th, td {
      border: 1px solid #cbd5e1;
      padding: 0.65rem 0.5rem;
      text-align: center;
    }
    th {
      background: #f1f5f9;
      font-weight: 700;
      color: #1e293b;
    }
    .forecast-summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .forecast-card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 0.75rem;
      text-align: center;
    }
    .forecast-label { font-size: 0.78rem; font-weight: 600; color: #64748b; }
    .forecast-val { font-size: 1.2rem; font-weight: 800; color: #4338ca; display: block; margin-top: 0.25rem; }
    .heatmap-container { overflow-x: auto; margin-top: 1rem; }
    .heatmap-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    .heatmap-th { background: #f8fafc; padding: 0.6rem; border: 1px solid #cbd5e1; font-weight: 700; }
    .heatmap-th-row { background: #f8fafc; padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1; text-align: left; }
    .heatmap-cell { padding: 0.6rem; border: 1px solid #e2e8f0; font-family: monospace; font-weight: 700; }
    .qa-card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 1rem 1.25rem;
      margin-bottom: 1rem;
    }
    .qa-card-user { font-weight: 700; color: #1e293b; margin-bottom: 0.5rem; }
    .qa-card-ai { color: #334155; font-size: 0.92rem; }
    footer {
      text-align: center;
      margin-top: 3.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
      font-size: 0.82rem;
      color: var(--text-muted);
    }
    @media print {
      body { background: #fff !important; padding: 0 !important; }
      .report-container { box-shadow: none !important; border: none !important; padding: 0 !important; max-width: 100% !important; }
    }
  </style>
</head>
<body>
  <div class="report-container">
    <div class="header-section">
      <span class="report-badge-top">AI Data Insight 종합 분석 보고서</span>
      <h1>${escapeHtml(fileName)} 데이터 통계 분석 리포트</h1>
      <div class="meta-tags">
        <span class="meta-tag">📁 파일명: ${escapeHtml(fileName)}</span>
        <span class="meta-tag">🛠️ 분석 도구: ${escapeHtml(toolNameKo)}</span>
        <span class="meta-tag">📅 기준 시점: ${escapeHtml(refPeriod)}</span>
        <span class="meta-tag">⏰ 리포트 생성일: ${new Date().toLocaleString()}</span>
      </div>
    </div>

    <h2>1. 데이터 시각화 차트</h2>
    ${chartImgTag}

    <h2>2. Pandas 통계 정밀 계산 데이터</h2>
    <div class="content-card">
      ${calcDataHtml}
    </div>

    <h2>3. AI 심층 인사이트 해설</h2>
    <div class="content-card">
      ${reportHtml}
    </div>

    ${followupHtml.trim() ? `
      <h2>4. 1:1 데이터 멘토 Q&A 답변 기록</h2>
      <div class="content-card">
        ${followupHtml}
      </div>
    ` : ""}

    <footer>
      본 보고서는 AI Data Insight Builder에 의해 자동 생성된 종합 분석 문서입니다.<br>
      Powered by Flask, Pandas and Google Gemini API &copy; 2026.
    </footer>
  </div>
</body>
</html>`;

  const blob = new Blob([standaloneHtml], { type: "text/html;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `Data_Insight_Report_${tool}_${new Date().toISOString().slice(0, 10)}.html`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  console.log("[EXPORT] 독립형 HTML 보고서 다운로드 완료");
}

/**
 * 사용자 맞춤형 자연어 질문 처리 (/query)
 */
async function submitCustomQuery() {
  const input = document.getElementById("inputCustomQuery");
  const btn = document.getElementById("btnSubmitQuery");
  const loading = document.getElementById("queryLoading");
  const answerCard = document.getElementById("queryAnswerCard");
  const answerContent = document.getElementById("queryAnswerContent");
  const qaQueryEcho = document.getElementById("qaQueryEcho");
  const qaToolBadge = document.getElementById("qaToolBadge");
  const query = input.value.trim();

  if (!query) {
    alert("질문 내용을 입력해 주세요.");
    input.focus();
    return;
  }

  btn.disabled = true;
  btn.textContent = "분석 중...";
  if (loading) loading.style.display = "block";
  if (answerCard) answerCard.style.display = "none";

  console.log(`[QUERY] 맞춤형 질문 요청: "${query}"`);

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query })
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "질문 처리에 실패했습니다.");
    }

    console.log(`[QUERY] 질문 처리 성공: 도구=${data.tool_used}`);

    // 계산 결과 및 상태 업데이트 (즉시 3/4단계로 점프하지 않고 보관)
    state.calculationResult = data.calculation_result;
    state.lastQuery = query;
    state.currentMode = "B";

    // 자연어 답변 카드 렌더링
    if (qaQueryEcho) qaQueryEcho.textContent = `🙋‍♂️ "${query}"`;
    if (qaToolBadge) {
      const refPeriod = data.calculation_result?.reference_period || "기준 시점";
      qaToolBadge.textContent = `도구: ${data.tool_used} | 기준: ${refPeriod}`;
    }

    // 간단한 마크다운/줄바꿈 서식 변환
    let answerHtml = (data.answer || "")
      .replace(/^## (.*$)/gim, "<h3 style='color:var(--primary-color); margin-top:0.9rem; margin-bottom:0.4rem;'>$1</h3>")
      .replace(/^### (.*$)/gim, "<strong style='color:var(--text-main); display:block; margin:0.4rem 0;'>$1</strong>")
      .replace(/\*\*(.*?)\*\*/gim, "<strong>$1</strong>")
      .replace(/^\* (.*$)/gim, "<li style='margin-left:1.2rem;'>$1</li>")
      .replace(/^- (.*$)/gim, "<li style='margin-left:1.2rem;'>$1</li>")
      .replace(/\n\n/gim, "<br><br>")
      .replace(/\n/gim, "<br>");
    answerHtml = answerHtml.replace(/(<li>.*<\/li>)/gis, "<ul>$1</ul>");

    if (answerContent) answerContent.innerHTML = answerHtml;
    if (answerCard) {
      answerCard.style.display = "block";
      answerCard.scrollIntoView({ behavior: "smooth" });
    }
  } catch (err) {
    console.error("[ERROR] 맞춤형 질문 오류:", err);
    alert(`질문 처리 실패: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "질문하기";
    if (loading) loading.style.display = "none";
  }
}

/**
 * 4단계 보고서 후속 질문 처리 (/followup)
 */
async function submitFollowupQuery() {
  const input = document.getElementById("inputFollowupQuery");
  const btn = document.getElementById("btnSubmitFollowup");
  const loading = document.getElementById("followupLoading");
  const chatList = document.getElementById("followupChatList");
  const query = input.value.trim();

  if (!query) {
    alert("궁금한 질문 내용을 입력해 주세요.");
    input.focus();
    return;
  }

  btn.disabled = true;
  loading.style.display = "block";
  console.log(`[FOLLOWUP] 후속 질문 요청: "${query}"`);

  try {
    const meta = state.diagnostics ? {
      topic: state.diagnostics.topic_hints?.topic || "",
      metric: state.diagnostics.topic_hints?.metric || "",
      unit: state.diagnostics.topic_hints?.unit || ""
    } : {};

    const res = await fetch(`${API_BASE}/followup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        report_text: state.currentReportMarkdown || "",
        calculation_result: state.calculationResult || {},
        meta: meta
      })
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "답변 생성에 실패했습니다.");
    }

    // 간단한 마크다운/줄바꿈 서식 변환
    let replyHtml = (data.reply || "")
      .replace(/^### (.*$)/gim, "<strong style='color:var(--text-main); font-size:0.95rem; display:block; margin:0.4rem 0;'>$1</strong>")
      .replace(/\*\*(.*?)\*\*/gim, "<strong>$1</strong>")
      .replace(/^\* (.*$)/gim, "<li style='margin-left:1.2rem;'>$1</li>")
      .replace(/^- (.*$)/gim, "<li style='margin-left:1.2rem;'>$1</li>")
      .replace(/\n\n/gim, "<br><br>")
      .replace(/\n/gim, "<br>");

    // Q&A 대화 카드 생성 및 추가
    const card = document.createElement("div");
    card.className = "qa-card";
    card.innerHTML = `
      <div class="qa-card-user">
        <span style="font-size:1.1rem;">🙋‍♂️</span>
        <span>${escapeHtml(query)}</span>
      </div>
      <div class="qa-card-ai">
        <div style="font-weight: 700; color: var(--primary-color); margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.4rem;">
          <span>🤖 데이터 멘토의 알기 쉬운 해설:</span>
        </div>
        <div>${replyHtml}</div>
      </div>
    `;

    chatList.appendChild(card);
    input.value = "";
    card.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    console.error("[ERROR] 후속 질문 실패:", err);
    alert(`후속 질문 처리 실패: ${err.message}`);
  } finally {
    btn.disabled = false;
    loading.style.display = "none";
  }
}

/**
 * XSS 방지를 위한 HTML 이스케이프 유틸
 */
function escapeHtml(text) {
  if (!text) return "";
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
