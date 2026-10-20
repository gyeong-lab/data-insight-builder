import os
import io
import csv
import json
import re
import logging
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template, send_from_directory
from dotenv import load_dotenv

# 1. 환경변수 로드
load_dotenv()

# 2. 로깅 설정 (print() 대신 logging 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataInsightBuilder")

# 3. Flask 앱 생성 (Vercel Serverless 및 로컬 공통 호환을 위해 절대 경로 지정)
base_dir = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, "templates"),
    static_folder=os.path.join(base_dir, "static")
)

# 환경변수 읽기
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# 메모리 데이터 저장소 (규칙: 파일은 디스크에 영구 저장하지 않고 메모리에 1개 데이터셋만 보관)
CURRENT_DATASET = {
    "filename": None,
    "df": None,
    "inspect_result": None
}

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

logger.info(f"서버 초기화 완료: 모델={GEMINI_MODEL}, 최대업로드={MAX_UPLOAD_MB}MB")

SUPPORTED_ENCODINGS = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]

# 집계 행(Aggregates) 탐지용 키워드 목록
AGGREGATE_KEYWORDS = [
    "world", "oecd members", "euro area", "european union",
    "high income", "low income", "middle income", "upper middle income",
    "lower middle income", "income", "area", "total", "average", "aggregate",
    "countries", "ida & ibrd", "latin america", "sub-saharan africa",
    "east asia", "south asia", "north america", "middle east"
]


def detect_encoding_and_content(file_bytes: bytes):
    """
    utf-8-sig, utf-8, cp949, euc-kr 순서로 인코딩을 시도합니다.
    """
    for enc in SUPPORTED_ENCODINGS:
        try:
            text = file_bytes.decode(enc)
            logger.info(f"[ENCODING] 시도 성공: {enc}")
            return enc, text
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None


def detect_header_row(text: str, max_check_lines: int = 15):
    """
    앞쪽 여러 줄을 검사하여 유효 컬럼이 가장 많은 실제 헤더 행을 찾습니다.
    """
    lines = text.splitlines()
    if not lines:
        return 0, []

    best_skip = 0
    max_non_empty_cols = 0
    best_header = []

    reader = csv.reader(lines[:max_check_lines])
    for idx, row in enumerate(reader):
        cleaned_cells = [cell.strip() for cell in row if cell.strip()]
        if len(cleaned_cells) > max_non_empty_cols:
            max_non_empty_cols = len(cleaned_cells)
            best_skip = idx
            best_header = row

    logger.info(f"[HEADER] 감지 결과: 건너뛴 줄 수={best_skip}, 컬럼 수={len(best_header)}")
    return best_skip, best_header


def diagnose_dataframe(df: pd.DataFrame, filename: str, file_size_kb: float, encoding: str, skiprows: int):
    """
    13가지 세부 진단 항목을 수행합니다:
    1. 파일명, 파일 크기
    2. 인코딩, 건너뛴 줄 수
    3. 행 수, 열 수, 열 이름
    4. 열별 데이터 타입
    5. 숫자형, 문자형, 연도/날짜 후보 열
    6. 결측치 개수 및 비율 (열별)
    7. 중복 행 수
    8. Unnamed 열 / 빈 열 목록
    9. 연도별 데이터 충실도 (각 연도 값 개수)
    10. 권장 기준연도 (값이 가장 많이 채워진 최근 연도)
    11. 집계 행 후보 (World, OECD, income 등)
    12. 데이터 미리보기 10행
    13. 경고 목록
    """
    warnings = []
    rows_count, cols_count = df.shape
    columns = [str(c).strip() for c in df.columns]

    # 8. Unnamed 열 / 전체가 빈 열 감지
    unnamed_cols = [c for c in columns if c.lower().startswith("unnamed:") or c == ""]
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    all_empty_or_unnamed = list(set(unnamed_cols + empty_cols))

    if unnamed_cols:
        warnings.append(f"이름이 없거나 Unnamed인 열이 {len(unnamed_cols)}개 발견되었습니다.")
    if empty_cols:
        warnings.append(f"전체 값이 비어 있는 열이 {len(empty_cols)}개 있습니다.")

    # 7. 중복 행 수
    dup_rows = int(df.duplicated().sum())
    if dup_rows > 0:
        warnings.append(f"전체 데이터 중 완전히 중복된 행이 {dup_rows}개 있습니다.")

    # 4 & 5 & 6. 열별 타입, 결측치, 분류 (숫자/문자/연도)
    dtypes = {}
    missing_stats = {}
    numeric_cols = []
    text_cols = []
    year_cols = []

    # 연도 컬럼 패턴 (1900~2099년 숫자 4자리)
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")

    for col in df.columns:
        col_str = str(col).strip()
        dtype_str = str(df[col].dtype)
        dtypes[col_str] = dtype_str

        # 결측치
        null_count = int(df[col].isna().sum())
        null_ratio = round((null_count / rows_count * 100), 2) if rows_count > 0 else 0.0
        missing_stats[col_str] = {"missing_count": null_count, "missing_ratio_pct": null_ratio}

        # 연도 컬럼 판별
        if year_pattern.match(col_str):
            year_cols.append(col_str)

        # 숫자형 / 문자형 분류 (전체 값이 비어있는 열은 수치 분석 대상에서 제외)
        if pd.api.types.is_numeric_dtype(df[col]) and col_str not in all_empty_or_unnamed and null_count < rows_count:
            numeric_cols.append(col_str)
        else:
            text_cols.append(col_str)

    # 9 & 10. 연도별 데이터 충실도 및 권장 기준연도 판별
    year_coverage = {}
    recommended_year = None
    if year_cols:
        # 연도 컬럼 정렬
        sorted_years = sorted(year_cols, key=lambda y: int(y))
        year_counts = {}
        for y in sorted_years:
            val_count = int(df[y].notna().sum())
            year_counts[y] = val_count
            year_coverage[y] = {
                "valid_count": val_count,
                "coverage_pct": round((val_count / rows_count * 100), 2) if rows_count > 0 else 0
            }

        # 권장 기준연도: 값이 존재하는 최근 연도들 중 충실도가 높은 연도 선정
        candidates = [y for y in reversed(sorted_years) if year_counts[y] >= rows_count * 0.3 and year_counts[y] > 0]
        if candidates:
            recommended_year = candidates[0]
        else:
            non_empty_years = [y for y in reversed(sorted_years) if year_counts[y] > 0]
            recommended_year = non_empty_years[0] if non_empty_years else None
    else:
        # Long 포맷(SDMX / Tidy 데이터)의 시점 열(TIME_PERIOD 등) 탐색
        for col in df.columns:
            if str(col).strip().upper() in ["TIME_PERIOD", "TIME", "YEAR", "PERIOD", "DATE"]:
                s = pd.to_numeric(df[col], errors="coerce").dropna()
                y_vals = [int(v) for v in s.unique() if 1900 <= v <= 2099]
                if y_vals:
                    sorted_years = sorted(y_vals, reverse=True)
                    recommended_year = str(sorted_years[0])
                    for y in sorted_years:
                        cnt = int((df[col] == y).sum())
                        year_coverage[str(y)] = {
                            "valid_count": cnt,
                            "coverage_pct": round((cnt / rows_count * 100), 2) if rows_count > 0 else 0
                        }
                    break

    # 11. 집계 행(Aggregates) 후보 탐지
    aggregate_candidates = []
    # 첫 3개 문자열 열에서 국가명/라벨 검사
    label_cols = [c for c in text_cols if c not in unnamed_cols][:3]
    for lcol in label_cols:
        for idx, val in df[lcol].dropna().items():
            val_str = str(val).strip()
            val_lower = val_str.lower()
            if any(kw in val_lower for kw in AGGREGATE_KEYWORDS):
                aggregate_candidates.append({
                    "row_index": int(idx),
                    "column": lcol,
                    "value": val_str,
                    "reason": "국가 단위가 아닌 전세계/지역/소득그룹 집계 행으로 추정됨"
                })

    # 중복 제거 (최대 20개까지만 샘플링)
    seen_rows = set()
    unique_aggregates = []
    for agg in aggregate_candidates:
        if agg["row_index"] not in seen_rows:
            seen_rows.add(agg["row_index"])
            unique_aggregates.append(agg)
        if len(unique_aggregates) >= 20:
            break

    if unique_aggregates:
        warnings.append(f"World, OECD, 소득분류 등 집계 행으로 보이는 항목이 {len(seen_rows)}개 이상 감지되었습니다.")

    # 12. 미리보기 10행 (안전한 JSON 직렬화 변환: NaN -> None)
    preview_df = df.head(10).replace({np.nan: None})
    preview_records = preview_df.to_dict(orient="records")

    # 14. 데이터 주제/지표 힌트 추출
    topic_hints = {}
    for c in ["STRUCTURE_NAME", "Measure", "Indicator Name", "INDICATOR_NAME", "Title", "Series Name"]:
        if c in df.columns:
            vals = [str(v).strip() for v in df[c].dropna().unique()[:3] if str(v).strip()]
            if vals:
                topic_hints[c] = vals

    for c in ["Unit of measure", "UNIT_MEASURE", "Unit"]:
        if c in df.columns:
            vals = [str(v).strip() for v in df[c].dropna().unique()[:2] if str(v).strip()]
            if vals:
                topic_hints["Unit"] = vals

    for c in ["Scale", "Category", "SECTOR", "Institutional sector"]:
        if c in df.columns:
            vals = [str(v).strip() for v in df[c].dropna().unique()[:4] if str(v).strip()]
            if vals:
                topic_hints[c] = vals

    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(warnings)} aggregates={len(unique_aggregates)} year_cols={len(year_cols)} topic_hints={len(topic_hints)}")

    return {
        "filename": filename,
        "file_size_kb": file_size_kb,
        "encoding": encoding,
        "skiprows": skiprows,
        "rows": rows_count,
        "columns": cols_count,
        "column_names": columns,
        "dtypes": dtypes,
        "numeric_columns": numeric_cols,
        "text_columns": text_cols,
        "year_columns": year_cols,
        "missing_stats": missing_stats,
        "duplicate_rows": dup_rows,
        "unnamed_or_empty_columns": all_empty_or_unnamed,
        "year_coverage": year_coverage,
        "recommended_year": recommended_year,
        "aggregate_candidates": unique_aggregates,
        "preview": preview_records,
        "warnings": warnings,
        "topic_hints": topic_hints,
        "notice": "파일은 서버 디스크에 저장되지 않고 메모리에만 보관되며, 서버 재시작 시 초기화됩니다."
    }


@app.route("/", methods=["GET"])
@app.route("/api/index", methods=["GET"])
@app.route("/api/index.py", methods=["GET"])
@app.route("/api", methods=["GET"])
def index():
    """메인 페이지 반환 (templates/index.html)"""
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """서버 상태와 API Key 설정 여부만 반환 (키 값은 반환 금지)"""
    api_key_configured = bool(GEMINI_API_KEY and len(GEMINI_API_KEY) > 10)
    logger.info(f"[RESPONSE] status=200 health_check api_key_configured={api_key_configured}")
    return jsonify({
        "status": "healthy",
        "api_key_configured": api_key_configured,
        "model": GEMINI_MODEL,
        "max_upload_mb": MAX_UPLOAD_MB
    })


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon.ico", mimetype="image/vnd.microsoft.icon")


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json", mimetype="application/json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/inspect", methods=["POST"])
def inspect():
    """
    CSV 업로드, 인코딩·헤더 자동 감지, 13개 항목 상세 진단 결과 JSON 반환
    """
    logger.info("[REQUEST] POST /inspect")

    # 1. 파일 검사
    if "file" not in request.files:
        logger.warning("[ERROR] 파일이 요청에 없음")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400

    file = request.files["file"]
    filename = file.filename or ""

    if not filename:
        logger.warning("[ERROR] 파일명이 비어있음")
        return jsonify({"error": "선택된 파일이 없습니다."}), 400

    if not filename.lower().endswith(".csv"):
        logger.warning(f"[ERROR] 허용되지 않은 확장자: {filename}")
        return jsonify({"error": "지원하지 않는 파일 형식입니다. .csv 확장자 파일만 업로드할 수 있습니다."}), 400

    file_bytes = file.read()
    file_size_bytes = len(file_bytes)
    file_size_kb = round(file_size_bytes / 1024, 2)
    logger.info(f"[FILE] name={filename} size={file_size_kb}KB")

    if file_size_bytes == 0:
        logger.warning("[ERROR] 빈 파일 업로드")
        return jsonify({"error": "업로드한 파일이 비어 있습니다 (0 byte)."}), 400

    # 2. 인코딩 순차 시도
    encoding, text = detect_encoding_and_content(file_bytes)
    if not encoding:
        logger.error("[ERROR] 모든 인코딩(utf-8-sig, utf-8, cp949, euc-kr) 디코딩 실패")
        return jsonify({"error": "파일 인코딩을 인식하지 못했습니다. 지원 인코딩: utf-8-sig, utf-8, cp949, euc-kr"}), 400

    # 3. 헤더 자동 감지
    skiprows, raw_header = detect_header_row(text)

    # 4. Pandas 파싱
    try:
        df = pd.read_csv(io.StringIO(text), skiprows=skiprows)
    except Exception as e:
        logger.error(f"[ERROR] Pandas CSV 파싱 오류: {str(e)}", exc_info=True)
        return jsonify({"error": f"CSV 파싱 중 오류가 발생했습니다: {str(e)}"}), 400

    # 5. 13가지 상세 진단 실행
    diagnostics = diagnose_dataframe(df, filename, file_size_kb, encoding, skiprows)

    # 메모리 데이터셋 갱신
    CURRENT_DATASET["filename"] = filename
    CURRENT_DATASET["df"] = df
    CURRENT_DATASET["inspect_result"] = diagnostics

    logger.info(f"[RESPONSE] status=200 inspect_complete warnings={len(diagnostics['warnings'])}")
    return jsonify({
        "status": "success",
        "message": "데이터 진단이 완료되었습니다.",
        "diagnostics": diagnostics
    })


# 12개 공식 도구 카탈로그 정의 (Gemini는 이 목록에 있는 도구만 제안 가능)
TOOL_CATALOG = [
    {
        "name": "reshape_wide_to_long",
        "description": "연도 열(1960~2024 등)을 행(Year, Value)으로 변환하여 시계열 데이터셋 구축"
    },
    {
        "name": "quality_report",
        "description": "결측치, 중복, 비어있는 열 등 전반적인 데이터 품질 정밀 진단"
    },
    {
        "name": "year_coverage",
        "description": "연도별 유효 데이터 충실도 분석 및 최적의 권장 기준연도 판별"
    },
    {
        "name": "detect_aggregates",
        "description": "World, OECD 등 국가가 아닌 대륙/지역/소득그룹 집계 행 탐지"
    },
    {
        "name": "describe_numeric",
        "description": "기준연도 수치의 기술통계(평균, 중앙값, 최소, 최대, 표준편차) 계산"
    },
    {
        "name": "trend_line",
        "description": "선택한 주요 국가들의 연도별 변화 추이 비교 (선 차트)"
    },
    {
        "name": "top_bottom_n",
        "description": "기준연도 기준 상위 N개국 및 하위 N개국 순위 분석 (수평 막대 차트)"
    },
    {
        "name": "group_summary",
        "description": "그룹/범주 열 기준 평균, 합계, 개수 집계 (막대 차트)"
    },
    {
        "name": "change_rate",
        "description": "두 시점 사이의 절대 변화량(p.p.) 및 증가율(%) 분석 (막대 차트)"
    },
    {
        "name": "distribution",
        "description": "기준연도 값의 구간별 분포 빈도수 분석 (히스토그램 차트)"
    },
    {
        "name": "correlation_scatter",
        "description": "두 시점/지표 간 피어슨 상관계수 산출 및 산점도 분석 (산점도 차트)"
    },
    {
        "name": "compare_one_vs_all",
        "description": "특정 국가(예: 한국)와 전 세계 전체 평균 및 중앙값 비교 (강조 막대 차트)"
    },
    {
        "name": "detect_outliers",
        "description": "평균에서 크게 벗어난 특이값·이상치 탐지 (표준편차 2배 이상 차이 나는 극단값 국가 식별)"
    },
    {
        "name": "forecast_trend",
        "description": "과거 시계열 데이터 회귀 분석을 통한 향후 3~5년 미래 예측치 및 95% 신뢰구간 도출 (미래 예측 선 차트)"
    },
    {
        "name": "correlation_matrix",
        "description": "전체 수치형 변수 간 피어슨 상관계수 행렬 산출 및 상관관계 히트맵 매트릭스 도출"
    }
]

VALID_TOOL_NAMES = {t["name"] for t in TOOL_CATALOG}


def get_feasible_tool_catalog(df: pd.DataFrame, diag: dict) -> list[dict]:
    """
    현재 업로드된 데이터셋의 구조(Wide/Long, 시계열 연도 수, 범주형 열, 집계행 유무 등)를 정밀 분석하여,
    이 자료에서 실제로 계산 및 시각화가 가능한 도구들만 엄선하여 반환합니다.
    """
    year_cols = diag.get("year_columns", [])
    has_aggregates = len(diag.get("aggregate_candidates", [])) > 0

    # 시계열 연도가 2개 이상 존재하는지 확인 (Wide 또는 Long)
    has_multi_periods = len(year_cols) >= 2
    if not has_multi_periods:
        for tc in ["TIME_PERIOD", "Time period", "Year", "YEAR", "Period"]:
            if tc in df.columns:
                uniq_y = df[tc].dropna().astype(str).unique()
                valid_y = [y for y in uniq_y if re.match(r"^(19\d\d|20\d\d)$", y.strip())]
                if len(valid_y) >= 2:
                    has_multi_periods = True
                    break

    # 유의미한 그룹핑(범주형) 열이 존재하는지 확인 (고유값 2~50개)
    group_candidates = [
        c for c in df.columns 
        if not pd.api.types.is_numeric_dtype(df[c]) and 2 <= df[c].nunique() <= 50
    ]
    has_group_col = len(group_candidates) > 0

    # 복수 수치 비교가 가능한지 확인
    numeric_cols = diag.get("numeric_columns", [])
    has_multi_numeric = len(numeric_cols) >= 2 or has_multi_periods

    feasible = []
    for tool in TOOL_CATALOG:
        name = tool["name"]
        
        # 1. 집계 행 탐지: 실제로 집계 행 후보가 있을 때만 추천
        if name == "detect_aggregates":
            if not has_aggregates:
                continue
                
        # 2. 시계열 선 차트 & 변화율: 시점이 2개 이상일 때만 추천
        elif name in ["trend_line", "change_rate"]:
            if not has_multi_periods:
                continue
                
        # 3. 그룹별 요약: 유의미한 그룹 열이 있을 때만 추천
        elif name == "group_summary":
            if not has_group_col:
                continue
                
        # 4. 상관분석: 2개 이상의 수치나 시점이 비교 가능할 때만 추천
        elif name in ["correlation_scatter", "correlation_matrix"]:
            if not has_multi_numeric:
                continue
                
        # 5. 미래 예측: 시계열 연도가 3개 이상일 때 추천
        elif name == "forecast_trend":
            if not has_multi_periods:
                continue
                
        feasible.append(tool)

    return feasible


@app.route("/suggest", methods=["POST"])
def suggest():
    """
    진단 결과를 Gemini에 전달하고, 현재 데이터에서 실제로 실행 가능한 검증된 도구 카탈로그 중에서만
    데이터에 가장 적합한 3~5개 분석 제안을 JSON으로 수신합니다.
    절대 규칙:
    - Gemini에게 CSV 원본을 보내지 않고 진단 요약만 전달
    - 현재 자료에서 실제 계산 가능한 도구만 제안 허용 (자료 적합성 엄격 검증)
    - JSON 응답 강제
    """
    logger.info("[REQUEST] POST /suggest")

    # 1. 업로드된 데이터셋 존재 여부 확인
    if CURRENT_DATASET["df"] is None or CURRENT_DATASET["inspect_result"] is None:
        logger.warning("[ERROR] 진단된 데이터셋 없음")
        return jsonify({"error": "먼저 CSV 파일을 업로드하고 진단을 완료해 주세요."}), 400

    if not GEMINI_API_KEY:
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 500

    df = CURRENT_DATASET["df"]
    diag = CURRENT_DATASET["inspect_result"]

    # 2. 현재 데이터에서 실제로 실행 가능한 도구 카탈로그만 엄선 필터링
    feasible_catalog = get_feasible_tool_catalog(df, diag)
    feasible_tool_names = {t["name"] for t in feasible_catalog}
    logger.info(f"[SUGGEST] 실행 가능한 도구 목록 ({len(feasible_catalog)}개): {list(feasible_tool_names)}")

    # 3. Gemini에게 보낼 진단 요약문 작성 (CSV 원본 전송 금지 규칙 준수)
    diag_summary = {
        "filename": diag["filename"],
        "rows": diag["rows"],
        "columns_count": diag["columns"],
        "recommended_year": diag.get("recommended_year"),
        "year_columns_sample": diag.get("year_columns", [])[-5:] if diag.get("year_columns") else [],
        "numeric_columns_sample": diag.get("numeric_columns", [])[:5],
        "text_columns": diag.get("text_columns", [])[:5],
        "topic_hints": diag.get("topic_hints", {}),
        "detected_aggregates_count": len(diag.get("aggregate_candidates", [])),
        "warnings": diag.get("warnings", [])
    }

    # 4. Gemini 프롬프트 구성 (실행 가능한 도구 카탈로그만 전달)
    prompt = f"""
당신은 데이터 분석 전문가입니다.
사용자가 업로드한 데이터의 진단 요약(실제 지표명, 주제, 단위 등)과 [이 데이터에서 실제로 실행 가능한 도구 카탈로그]를 확인하고,
1) 오직 아래 제공된 [실행 가능한 도구 카탈로그] 안에서만 가장 유의미한 분석 도구 3~5개('suggestions')와
2) 사용자가 2단계 자연어 질의응답 창에서 바로 클릭하여 질문할 수 있는 이 데이터셋의 실제 주제(지표 내용, 국가/항목, 기준연도)에 부합하는 맞춤형 추천 질문 4개('recommended_questions')를 생성하세요.

[진단 요약]
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

[이 데이터에서 실제로 실행 가능한 검증된 도구 카탈로그]
{json.dumps(feasible_catalog, ensure_ascii=False, indent=2)}

[절대 규칙 - 자료 적합성 보장]
1. 반드시 위에 제공된 [실행 가능한 도구 카탈로그]에 있는 tool 이름만 사용하세요. 목록에 없는 도구나 자료 특성상 불가능한 분석은 절대로 제안하지 마세요.
2. 데이터에 실제로 존재하는 열 이름만 params에 사용하세요. (기준연도/수치로는 권장연도 '{diag.get("recommended_year")}' 또는 적합한 수치열 사용)
3. 7~13번 도구를 제안할 때는 params 안에 반드시 "reference_period"를 포함하세요.
4. 'recommended_questions'는 데이터의 실제 주제(지표명, 측정 내용)와 기준연도를 명확히 반영해야 합니다. 업로드된 파일과 무관한 엉뚱한 분야의 질문을 절대 만들지 마세요.
5. 출력은 오직 아래 JSON 형식만 반환하세요. 마크다운 따옴표나 기타 텍스트를 포함하지 마세요.

{{
  "suggestions": [
    {{
      "tool": "top_bottom_n",
      "params": {{
        "reference_period": "{diag.get("recommended_year") or '2024'}",
        "n": 10,
        "exclude_aggregates": true
      }},
      "reference_period": "{diag.get("recommended_year") or '2024'}",
      "why": "이 분석이 이 데이터에서 의미 있는 이유",
      "caution": "해석할 때 주의할 점"
    }}
  ],
  "recommended_questions": [
    {{
      "label": "상위 10개국 & 한국 순위",
      "query": "{diag.get('recommended_year') or ''}년 기준 상위 10개 국가와 한국의 위치를 알려줘"
    }},
    {{
      "label": "한국 vs 전체 평균",
      "query": "한국의 수치는 전 세계 전체 평균 및 중앙값과 비교해 어떤가요?"
    }},
    {{
      "label": "그룹별 평균 비교",
      "query": "주요 범주/그룹별 평균 및 분포 현황을 비교해줘"
    }},
    {{
      "label": "이상치 탐지",
      "query": "평균에서 크게 벗어난 특이값이나 이상치 국가를 찾아줘"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={GEMINI_MODEL})")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        ai_raw_text = response.text or "{}"
        logger.info("[AI] suggest 응답 수신 완료")

        # JSON 파싱
        clean_text = ai_raw_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        parsed = json.loads(clean_text)
        suggestions = parsed.get("suggestions", [])
        rec_questions = parsed.get("recommended_questions", [])

        # 도구 유효성 검증 필터링 (현재 데이터에서 실제 실행 가능한 도구만 엄격 허용)
        valid_suggestions = []
        for s in suggestions:
            tool_name = s.get("tool")
            if tool_name in feasible_tool_names:
                valid_suggestions.append(s)
            else:
                logger.warning(f"[AI] 현재 자료에서 실행 불가능하거나 목록에 없는 도구 제안 제외됨: {tool_name}")

        if not valid_suggestions:
            # 방어적 기본 제안 (실행 가능한 도구들 중에서만 엄선)
            rec_y = diag.get("recommended_year") or "2024"
            fallback_candidates = [
                {
                    "tool": "top_bottom_n",
                    "params": {"reference_period": rec_y, "n": 10, "exclude_aggregates": True},
                    "reference_period": rec_y,
                    "why": f"{rec_y}년 기준 국가별 최상위 및 최하위 분포를 파악하기 위함",
                    "caution": "결측치가 있는 국가는 순위 집계에서 제외됩니다."
                },
                {
                    "tool": "compare_one_vs_all",
                    "params": {"reference_period": rec_y, "target_item": "Korea, Rep."},
                    "reference_period": rec_y,
                    "why": "우리나라와 전체 국가 평균 및 중앙값 비교",
                    "caution": "전체 데이터의 분포 형태를 함께 고려해야 합니다."
                },
                {
                    "tool": "group_summary",
                    "params": {"reference_period": rec_y},
                    "reference_period": rec_y,
                    "why": "주요 범주 및 그룹별 평균 통계 비교",
                    "caution": "그룹별 표본 크기 편차를 유의해야 합니다."
                },
                {
                    "tool": "trend_line",
                    "params": {},
                    "reference_period": rec_y,
                    "why": "주요 국가들의 시계열 변화 추이 비교",
                    "caution": "중간 연도 결측치는 선이 끊어질 수 있습니다."
                },
                {
                    "tool": "distribution",
                    "params": {"reference_period": rec_y, "bins": 10, "exclude_aggregates": True},
                    "reference_period": rec_y,
                    "why": f"{rec_y}년 전 세계 국가들의 지표 분포 구조 확인",
                    "caution": "집계 행을 제외하지 않으면 특정 그룹에 편향될 수 있습니다."
                },
                {
                    "tool": "describe_numeric",
                    "params": {"reference_period": rec_y},
                    "reference_period": rec_y,
                    "why": "기초 기술통계치(평균, 중앙값, 왜도 등) 요약",
                    "caution": "이상치 유무에 따라 평균이 왜곡될 수 있습니다."
                }
            ]
            valid_suggestions = [fc for fc in fallback_candidates if fc["tool"] in feasible_tool_names][:4]

        # 추천 질문 보정 (만약 Gemini가 누락한 경우 topic_hints 기반 똑똑한 자동 생성)
        if not rec_questions:
            topic_h = diag.get("topic_hints", {})
            title_sample = ""
            for k in ["STRUCTURE_NAME", "Measure", "Indicator Name", "INDICATOR_NAME", "Title"]:
                if k in topic_h and topic_h[k]:
                    title_sample = str(topic_h[k][0])[:35]
                    break
            y_prefix = f"{diag.get('recommended_year')}년 기준 " if diag.get('recommended_year') else ""
            subj = f"'{title_sample}' " if title_sample else ""
            rec_questions = [
                {
                    "label": "상위 10개국 & 한국 순위",
                    "query": f"{y_prefix}{subj}상위 10개 국가와 한국의 위치를 알려줘."
                },
                {
                    "label": "한국 vs 전체 평균",
                    "query": f"{y_prefix}한국의 {subj}수치는 전체 평균 및 중앙값과 비교해 어떤가요?"
                },
                {
                    "label": "이상치 국가 탐지",
                    "query": f"{y_prefix}평균에서 크게 벗어난 특이값이나 이상치 국가를 찾아줘."
                },
                {
                    "label": "전체 평균 및 중앙값",
                    "query": f"{y_prefix}전체 대상의 {subj}평균과 중앙값은 얼마인가요?"
                }
            ]

        logger.info(f"[AI] 제안 파싱 성공: {len(valid_suggestions)}개 제안, {len(rec_questions)}개 추천 질문")
        return jsonify({
            "status": "success",
            "model": GEMINI_MODEL,
            "suggestions": valid_suggestions,
            "recommended_questions": rec_questions
        })

    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] AI 응답 JSON 파싱 실패: {str(je)}", exc_info=True)
        return jsonify({"error": "AI 제안 응답을 JSON으로 변환하는 데 실패했습니다."}), 500
    except Exception as e:
        logger.error(f"[ERROR] Gemini API 호출 오류: {str(e)}", exc_info=True)
        return jsonify({"error": f"Gemini API 호출 중 오류가 발생했습니다: {str(e)}"}), 500


def get_dataset_topic_title(diag: dict) -> str:
    """
    topic_hints 및 진단 정보로부터 데이터셋의 핵심 지표명과 주제를 사람이 명확히 알 수 있는 텍스트로 추출합니다.
    """
    topic_hints = diag.get("topic_hints", {})
    for k in ["STRUCTURE_NAME", "Measure", "Indicator Name", "INDICATOR_NAME", "Series Name", "Title"]:
        if k in topic_hints and topic_hints[k]:
            title = str(topic_hints[k][0]).strip()
            if "perception of public sector integrity" in title.lower() or "public sector integrity" in title.lower():
                return f"OECD 공공부문 청렴 신뢰도 지표 ({title})"
            elif "individuals using the internet" in title.lower() or "internet" in title.lower():
                return f"인구 대비 인터넷 이용자 비율 지표 ({title})"
            return title

    filename = str(diag.get("filename", "")).lower()
    if "gov_int" in filename or "integrity" in filename:
        return "OECD 공공부문 청렴 신뢰도 지표 (공무원의 뇌물 거절 신뢰율)"
    elif "it.net.user" in filename or "internet" in filename:
        return "인구 대비 인터넷 이용자 비율 (World Bank Data)"

    return "글로벌 공공 통계 데이터셋"


def get_metric_polarity_guidance(diag: dict) -> str:
    """
    지표의 방향성(높을수록 좋은지 vs 낮을수록 좋은지)을 사전에 명확히 고정하여,
    보고서 1~5번 목차 및 후속 Q&A 전체에서 위아래 모순이 생기지 않도록 단일화된 가이드를 반환합니다.
    """
    title = get_dataset_topic_title(diag).lower()
    filename = str(diag.get("filename", "")).lower()

    # 명백히 낮을수록 좋은 부정 지표 목록
    negative_keywords = [
        "crime", "범죄", "homicide", "살인", "unemployment", "실업", 
        "poverty", "빈곤", "mortality", "사망", "inflation", "인플레이션", 
        "pollution", "오염", "co2 emissions", "탄소 배출"
    ]
    is_lower_better = any(kw in title or kw in filename for kw in negative_keywords)

    if is_lower_better:
        return """[★ 점수 방향성 절대 불변 원칙 ★]:
- 본 지표는 수치가 **낮을수록 좋은 긍정적 상태(예: 범죄/실업/사망률이 낮음)**이며, 수치가 **높을수록 심각한 부정적 상태**입니다.
- 보고서 요약, 본문 비교, 후속 Q&A 전체에서 무조건 '점수 낮음 = 우수', '점수 높음 = 취약/심각'으로 100% 일관되게 서술하세요."""
    else:
        return """[★ 점수 방향성 절대 불변 원칙 (보고서 위아래 통일) ★]:
- 본 지표는 **점수가 높을수록(100%에 가까울수록) 긍정적이고 우수한 상태(예: 공직사회 청렴도가 높고 뇌물 거절 신뢰가 큼)**입니다!
- 반대로 **점수가 낮을수록(0%에 가까울수록) 부정적이고 취약한 상태(예: 부패 위험이 크고 공직사회 불신이 높음)**입니다!
- 1위(최고점) 국가는 '가장 청렴하고 신뢰받는 우수국'이며, 최하위(최저점) 국가는 '가장 부패 위험이 높은 취약국'입니다.
- [경고]: 위 요약에서는 점수가 높으면 청렴하다고 해놓고, 아래 분석이나 질문 답변에서는 '점수가 낮아야 청렴하다'라거나 '점수가 높으면 부패하다'처럼 앞뒤가 뒤바뀌는 모순을 절대로 범하지 마세요! 처음부터 끝까지 무조건 '점수 높음 = 청렴 우수', '점수 낮음 = 부패 취약'으로 일관되게 작성하세요."""


COUNTRY_ALIAS_MAP = {
    "한국": ["Korea, Rep.", "Korea", "South Korea", "Republic of Korea", "대한민국", "남한"],
    "대한민국": ["Korea, Rep.", "Korea", "South Korea", "Republic of Korea"],
    "미국": ["United States", "USA", "U.S.", "United States of America"],
    "일본": ["Japan"],
    "중국": ["China"],
    "독일": ["Germany"],
    "영국": ["United Kingdom", "UK", "Great Britain"],
    "프랑스": ["France"],
    "호주": ["Australia"],
    "캐나다": ["Canada"],
    "멕시코": ["Mexico"],
    "이탈리아": ["Italy"],
    "스페인": ["Spain"],
    "네덜란드": ["Netherlands"],
    "스위스": ["Switzerland"],
    "스웨덴": ["Sweden"],
    "노르웨이": ["Norway"],
    "덴마크": ["Denmark"],
    "핀란드": ["Finland"],
    "뉴질랜드": ["New Zealand"],
    "그리스": ["Greece"],
    "포르투갈": ["Portugal"],
    "칠레": ["Chile"],
    "콜롬비아": ["Colombia"],
    "코스타리카": ["Costa Rica"],
    "체코": ["Czechia", "Czech Republic"],
    "에스토니아": ["Estonia"],
    "아이슬란드": ["Iceland"],
    "아일랜드": ["Ireland"],
    "라트비아": ["Latvia"],
    "룩셈부르크": ["Luxembourg"],
    "슬로바키아": ["Slovak Republic", "Slovakia"],
    "슬로베니아": ["Slovenia"],
    "오스트리아": ["Austria"]
}


def detect_target_country_from_query(query: str, available_labels: list[str]):
    """
    질문 텍스트에서 국가명을 감지하고, 현재 데이터셋의 실제 라벨 목록(available_labels)에서
    매칭되는 고유 국가명을 찾아 (매칭된 국가명, 사용자 언급 국가명) 형태로 반환합니다.
    데이터에 없는 경우 (None, 사용자 언급 국가명)을 반환합니다.
    """
    query_lower = query.lower()
    for kr_name, aliases in COUNTRY_ALIAS_MAP.items():
        if kr_name in query or any(a.lower() in query_lower for a in aliases):
            for a in aliases:
                for lbl in available_labels:
                    if lbl.lower() == a.lower():
                        return lbl, kr_name
            for a in aliases:
                for lbl in available_labels:
                    if a.lower() in lbl.lower():
                        return lbl, kr_name
            return None, kr_name

    for lbl in available_labels:
        if lbl.lower() in query_lower and len(lbl) >= 3:
            return lbl, lbl

    return None, None


@app.route("/query", methods=["POST"])
def natural_language_query():
    """
    사용자의 자연어 질문을 받아
    1) 현재 데이터셋의 실제 지표(주제) 맥락을 강력하게 앵커링하여 최적의 도구와 파라미터 선정
    2) 질문에 언급된 국가를 정밀 탐색 (없는 국가일 경우 명확히 안내)
    3) Pandas로 도구를 직접 실행하여 오차 없는 데이터 및 순위 계산
    4) 계산된 결과만을 바탕으로 질문에 대한 명확한 답변 및 해석 반환
    """
    logger.info("[REQUEST] POST /query")

    if CURRENT_DATASET["df"] is None or CURRENT_DATASET["inspect_result"] is None:
        logger.warning("[ERROR] 데이터셋 미업로드")
        return jsonify({"error": "먼저 CSV 파일을 업로드하고 진단을 완료해 주세요."}), 400

    payload = request.get_json(silent=True) or {}
    user_query = payload.get("query", "").strip()

    if not user_query:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    if not GEMINI_API_KEY:
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다."}), 500

    diag = CURRENT_DATASET["inspect_result"]
    df = CURRENT_DATASET["df"]
    indicator_title = get_dataset_topic_title(diag)
    topic_hints = diag.get("topic_hints", {})

    import tools
    label_col = tools.resolve_label_column(df, {})
    available_labels = df[label_col].dropna().astype(str).unique().tolist()

    # 1. 사용자가 질문에 언급한 국가 정밀 감지
    matched_country, requested_country = detect_target_country_from_query(user_query, available_labels)
    logger.info(f"[QUERY] 질문 분석: query='{user_query}', requested_country='{requested_country}', matched='{matched_country}'")

    # 2. Gemini에게 질문을 최적의 도구 호출 계획으로 변환하도록 요청
    plan_prompt = f"""
당신은 데이터 분석 파이프라인 설계자입니다.
현재 사용자가 분석 중인 데이터는 **'{indicator_title}'** 데이터셋입니다.
사용자의 질문을 분석하여, 제공된 12개 도구 카탈로그 중 질문에 답하기 위해 실행해야 할 최적의 도구 1개와 파라미터(params)를 JSON으로 결정하세요.

[현재 분석 데이터셋 지표/주제]
- 핵심 지표명: {indicator_title}
- 파일명: {diag.get('filename')}
- 기준 연도/수치 열: {diag.get('recommended_year')}
- 국가/라벨 열: {label_col}

[사용자 질문]
"{user_query}"

[도구 카탈로그]
{json.dumps(TOOL_CATALOG, ensure_ascii=False, indent=2)}

[절대 주의 및 규칙]
1. 본 데이터셋의 주제는 **'{indicator_title}'**입니다. 과거의 다른 지표(인터넷 보급률 등)를 절대 언급하거나 혼동하지 마세요.
2. 7~13번 도구는 reference_period가 필수입니다. 질문에 연도가 언급되어 있으면 해당 연도를 쓰고, 없으면 권장 시점 '{diag.get('recommended_year')}'를 params에 넣으세요.
3. [도구 선정 우선순위]:
   - 질문에 **'순위', '1~10등', '상위', '하위', '랭킹', 'top', '몇 위'** 등이 포함된 경우: 반드시 **'top_bottom_n'** 도구를 선택하고, 질문의 개수(예: 1~10등이면 n=10)를 params에 넣으세요. 만약 질문에 한국이나 특정 국가가 함께 비교 대상으로 언급되었다면 params.target_item에 해당 국가명('{matched_country or requested_country or "Korea"}')을 넣으세요.
   - 특정 국가 1개와 전체 평균/중앙값의 대조가 주 목적인 경우: **'compare_one_vs_all'**을 선택하세요.
   - 연도별 시계열 변화, 과거 추세가 주 목적인 경우: **'trend_line'**을 선택하세요.
   - 향후 전망, 미래 예측, 앞으로의 변화 추정이 목적인 경우: **'forecast_trend'**를 선택하고 params.target_item에 해당 국가명('{matched_country or requested_country or "Korea"}')을 넣으세요.
   - 모든 변수/연도 간 종합 상관관계 또는 히트맵 매트릭스가 목적인 경우: **'correlation_matrix'**를 선택하세요.
   - 이상치, 특이값 탐지가 목적인 경우: **'detect_outliers'**를 선택하세요.
4. 출력은 오직 아래 JSON 형식만 반환하세요:
{{
  "tool": "top_bottom_n",
  "params": {{
    "reference_period": "{diag.get('recommended_year') or '2024'}",
    "n": 10,
    "target_item": "{matched_country or requested_country or 'Korea'}",
    "label_column": "{label_col}",
    "exclude_aggregates": true
  }}
}}
"""

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=plan_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        plan_text = resp.text.strip()
        if plan_text.startswith("```json"):
            plan_text = plan_text[7:]
        if plan_text.startswith("```"):
            plan_text = plan_text[3:]
        if plan_text.endswith("```"):
            plan_text = plan_text[:-3]

        plan = json.loads(plan_text.strip())
        tool_name = plan.get("tool")
        tool_params = plan.get("params", {}) or {}

        if tool_name not in VALID_TOOL_NAMES:
            tool_name = "top_bottom_n" if ("순위" in user_query or "등" in user_query or "top" in user_query.lower()) else ("compare_one_vs_all" if requested_country else "top_bottom_n")
            tool_params = {"reference_period": diag.get("recommended_year") or "2024"}

        tool_params["label_column"] = label_col

        # 기준 시점(reference_period) 보정
        try:
            resolved_ref = tools.resolve_reference_period(df, tool_params)
            tool_params["reference_period"] = resolved_ref
        except Exception:
            resolved_ref = diag.get("recommended_year") or "2024"
            tool_params["reference_period"] = resolved_ref

        target_not_found = False
        calc_result = None
        extra_target_info = None

        # 3. 국가 검색 결과 분기 처리
        if requested_country and not matched_country:
            # 사용자가 특정 국가를 물어보았으나 본 데이터셋에 없는 경우 (예: 미국)
            target_not_found = True
            work_df, _, _ = tools.filter_aggregate_rows(df, label_col)
            series = pd.to_numeric(work_df[resolved_ref], errors="coerce").dropna()
            
            # 엔티티별 평균
            if work_df[label_col].nunique() < len(work_df):
                entity_s = work_df.groupby(label_col)[resolved_ref].mean()
            else:
                entity_s = series

            overall_m = round(float(entity_s.mean()), 2)
            overall_med = round(float(entity_s.median()), 2)

            calc_result = {
                "tool": "compare_one_vs_all",
                "reference_period": resolved_ref,
                "used_rows": len(work_df),
                "excluded_rows": 0,
                "exclusion_reason": "없음",
                "unit": "지표 기준 단위",
                "data": {
                    "requested_item": requested_country,
                    "target_not_found": True,
                    "overall_mean": overall_m,
                    "overall_median": overall_med,
                    "total_available_countries": len(available_labels),
                    "available_countries_sample": available_labels[:12]
                }
            }
        else:
            # 정상적인 도구 실행
            if matched_country:
                tool_params["target_item"] = matched_country

            tool_func = getattr(tools, tool_name)
            calc_result = tool_func(df, tool_params)

            # 타겟 국가의 전체 순위 및 위치 계산 (한국 또는 사용자가 물어본 국가)
            active_target = matched_country or calc_result.get("data", {}).get("target_item")
            if active_target:
                work_df, _, _ = tools.filter_aggregate_rows(df, label_col)
                series = pd.to_numeric(work_df[resolved_ref], errors="coerce")
                valid_w = work_df[series.notna()].copy()
                valid_w["_val"] = series[series.notna()]

                if not valid_w.empty:
                    # 복수 행인 경우 고유 국가별 평균 기준 정렬
                    if valid_w[label_col].nunique() < len(valid_w):
                        grouped_all = valid_w.groupby(label_col, as_index=False)["_val"].mean()
                    else:
                        grouped_all = valid_w[[label_col, "_val"]].copy()

                    sorted_all = grouped_all.sort_values(by="_val", ascending=False).reset_index(drop=True)
                    sorted_all["rank"] = sorted_all.index + 1

                    match_rows = sorted_all[sorted_all[label_col].astype(str) == str(active_target)]
                    if not match_rows.empty:
                        m_row = match_rows.iloc[0]
                        extra_target_info = {
                            "country": str(m_row[label_col]),
                            "rank": int(m_row["rank"]),
                            "total_countries": len(sorted_all),
                            "value": round(float(m_row["_val"]), 2),
                            "year": str(resolved_ref)
                        }

        CURRENT_DATASET["last_run_result"] = calc_result
        CURRENT_DATASET["last_query"] = user_query

        # 4. 답변 프롬프트 작성 (친절한 데이터 멘토, 지표 정체성 절대 엄수)
        answer_prompt = f"""
당신은 중학생이나 일반 대중도 쉽게 이해할 수 있도록 데이터를 명쾌하고 친절하게 설명해주는 데이터 멘토입니다.
현재 사용자가 업로드하여 분석 중인 데이터는 **[{indicator_title}]** 데이터셋입니다.

[🚨 절대 엄수 - 지표 정체성 및 팩트 준수 규칙]
1. 본 분석은 100% **'{indicator_title}'**에 대한 분석입니다!
   - 이전 대화나 타 데이터셋의 '인터넷 보급률'이나 무관한 지표를 절대로 언급하지 마세요.
   - 질문에 지표명이 생략되어 있거나 국가명만 있더라도, 오직 현재 데이터의 지표인 **'{indicator_title}'**의 맥락에서만 답변하세요.
2. 사용자가 질문한 국가에 대한 정직한 사실 안내:
   - 만약 사용자가 질문한 국가('{requested_country}')가 본 데이터셋에 없는 경우 ('target_not_found': True):
     "요청하신 '{requested_country}'는 본 [{indicator_title}] 데이터셋(총 {len(available_labels)}개 참여국)에 포함되어 있지 않습니다."라고 사실을 정직하게 밝히세요.
     절대로 다른 나라의 수치를 미국이나 질문한 국가인 것처럼 거짓으로 꾸며대지 마세요.
     현재 데이터셋에 포함된 주요 국가들({', '.join(available_labels[:8])} 등)과 전체 평균치를 대신 안내하세요.
   - 질문한 국가('{matched_country}')가 데이터셋에 있는 경우:
     해당 국가의 실제 수치와 순위, 전체 평균을 정확하게 인용하여 비교 설명하세요.
3. 숫자는 반드시 아래 [Pandas 계산 결과]에 명시된 숫자만 인용하세요.
4. 어려운 통계 전문 용어 대신 일상적인 쉬운 표현과 명쾌한 비유를 사용하세요.

[사용자 질문]
"{user_query}"

[데이터셋 주제 및 지표 정보]
- 핵심 지표명: {indicator_title}
- 세부 메타데이터: {json.dumps(topic_hints, ensure_ascii=False)}

[Pandas가 계산한 실제 통계 결과]
{json.dumps(calc_result, ensure_ascii=False, indent=2)}

[요청 국가 상세 순위 및 위치 계산 결과]
{json.dumps(extra_target_info, ensure_ascii=False, indent=2) if extra_target_info else "해당 없음"}

[답변 작성 형식 가이드]
- **💡 1. 3초 쉬운 결론**: 질문에 대한 가장 핵심적인 답을 1~2문장으로 명쾌하게 제시
- **🔍 2. 이 지표의 의미**: 점수가 높을수록 좋은 건지 낮을수록 좋은 건지 먼저 안내
- **📊 3. 구체적인 순위와 비교**: 1~10위 국가들과 질문 국가(예: 한국)의 점수 및 순위 차이를 보기 쉽게 정리
- **🌟 4. 현실적 의미**: 이 순위와 점수가 뜻하는 현실적인 의미를 친절하게 해설
"""

        answer_resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=answer_prompt
        )
        answer_text = answer_resp.text or ""

        logger.info(f"[RESPONSE] status=200 query_complete (tool={tool_name})")
        return jsonify({
            "status": "success",
            "query": user_query,
            "tool_used": tool_name,
            "tool_params": tool_params,
            "calculation_result": calc_result,
            "extra_target_info": extra_target_info,
            "answer": answer_text
        })

    except Exception as e:
        logger.error(f"[ERROR] /query 처리 중 예외 발생: {str(e)}", exc_info=True)
        return jsonify({"error": f"질문 처리 중 오류가 발생했습니다: {str(e)}"}), 500


@app.route("/run", methods=["POST"])
def run_tool():
    """
    선택된 도구를 Pandas로 직접 실행합니다.
    절대 규칙:
    - 숫자 계산은 반드시 Pandas가 수행하며 Gemini에게 계산을 시키지 않음
    - 7~12번 도구는 기준 시점(reference_period) 필수
    - 결과에 기준 시점, 사용한 행 수, 제외한 행 수와 이유 반드시 포함
    - Chart.js 렌더링에 필요한 차트 데이터 구조 반환
    """
    logger.info("[REQUEST] POST /run")

    # 1. 메모리 데이터셋 로드 여부 검사
    if CURRENT_DATASET["df"] is None:
        logger.warning("[ERROR] 데이터셋 미업로드")
        return jsonify({"error": "업로드된 데이터셋이 없습니다. 먼저 CSV를 진단해 주세요."}), 400

    payload = request.get_json(silent=True) or {}
    tool_name = payload.get("tool")
    params = payload.get("params", {})

    if not tool_name:
        logger.warning("[ERROR] 도구명 미입력")
        return jsonify({"error": "실행할 도구명을 지정해야 합니다."}), 400

    if tool_name not in VALID_TOOL_NAMES:
        logger.warning(f"[ERROR] 등록되지 않은 도구: {tool_name}")
        return jsonify({"error": f"도구 카탈로그에 없는 도구입니다: '{tool_name}'"}), 400

    # 2. 7~12번 도구의 기준 시점(reference_period) 필수 검증
    tools_requiring_reference = {
        "top_bottom_n", "group_summary", "change_rate",
        "distribution", "correlation_scatter", "compare_one_vs_all",
        "detect_outliers"
    }

    df = CURRENT_DATASET["df"]

    # 2. 기준 시점(reference_period) 자동 보정
    import tools
    if tool_name in tools_requiring_reference:
        try:
            resolved_ref = tools.resolve_reference_period(df, params)
            if resolved_ref:
                params["reference_period"] = str(resolved_ref)
        except Exception as e:
            logger.warning(f"[WARN] reference_period 자동 탐색 실패: {e}")

    ref_period = params.get("reference_period") or params.get("year")
    if tool_name in tools_requiring_reference and not ref_period:
        logger.warning(f"[ERROR] {tool_name} 기준 시점 미지정")
        return jsonify({
            "error": f"도구 '{tool_name}'는 기준 시점(reference_period, 예: 2024) 입력이 필수입니다."
        }), 400

    # 3. tools.py 모듈 함수 매핑 및 안전한 실행
    try:
        import tools
        tool_func = getattr(tools, tool_name, None)
        if not tool_func:
            return jsonify({"error": f"도구 함수 '{tool_name}'를 찾을 수 없습니다."}), 500

        result = tool_func(df, params)

        # 백엔드 표준 규격 로깅
        logger.info(
            f"[TOOL] 도구={result.get('tool')}, 기준시점={result.get('reference_period')}, "
            f"사용한행수={result.get('used_rows')}, 제외행수={result.get('excluded_rows')}"
        )

        # 최근 실행 결과를 메모리에 보관 (/explain 단계에서 사용)
        CURRENT_DATASET["last_run_result"] = result

        logger.info(f"[RESPONSE] status=200 run_{tool_name}_success")
        return jsonify({
            "status": "success",
            "result": result
        })

    except ValueError as ve:
        logger.warning(f"[ERROR] {tool_name} 실행 값 오류: {str(ve)}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] {tool_name} 실행 중 예외 발생: {str(e)}", exc_info=True)
        return jsonify({"error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500


@app.route("/explain", methods=["POST"])
def explain_results():
    """
    계산 결과에 대한 Gemini AI 해석을 생성합니다.
    모드 A (비교용, 의도적으로 허술하게):
      진단 요약만 전달하고 계산 결과 없이 보고서 작성 요청.
    모드 B (정식):
      Pandas가 계산한 결과(표, 기준시점, 제외 행 수)만 전달하고
      엄격한 8개 규칙과 정해진 마크다운 목차 형식 준수 강제.
    """
    logger.info("[REQUEST] POST /explain")

    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "B").upper()

    if not GEMINI_API_KEY:
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 500

    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)

    # ==========================================
    # 모드 A (비교용, 의도적으로 허술하게)
    # ==========================================
    if mode == "A":
        logger.info("[AI] explain 요청 시작 (모드 A: 단순 진단 요약 기반)")
        diag = CURRENT_DATASET.get("inspect_result") or {}
        diag_summary = {
            "filename": diag.get("filename", "데이터 파일"),
            "rows": diag.get("rows", 0),
            "columns": diag.get("columns", 0),
            "warning_count": len(diag.get("warnings", []))
        }

        prompt_a = f"""
당신은 일반 AI 어시스턴트입니다.
아래의 데이터 기본 정보만 보고, 이 데이터를 자유롭게 상상하여 분석 보고서를 그럴듯하게 작성해 주세요.
어떤 계산 결과도 제공되지 않았으므로 일반적인 상식과 추정에 기반해 작성하세요.

[데이터 요약]
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}
"""
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_a
            )
            explanation = resp.text or ""
            logger.info(f"[RESPONSE] status=200 explain_mode_A_complete (len={len(explanation)})")
            return jsonify({
                "status": "success",
                "mode": "A",
                "model": GEMINI_MODEL,
                "explanation": explanation
            })
        except Exception as e:
            logger.error(f"[ERROR] 모드 A 생성 중 오류: {str(e)}", exc_info=True)
            return jsonify({"error": f"해석 생성 중 오류가 발생했습니다: {str(e)}"}), 500

    # ==========================================
    # 모드 B (정식: Pandas 계산 결과 기반 엄격한 해석)
    # ==========================================
    else:
        logger.info("[AI] explain 요청 시작 (모드 B: Pandas 계산 결과 기반 정식)")

        run_result = payload.get("calculation_result") or CURRENT_DATASET.get("last_run_result")
        if not run_result:
            logger.warning("[ERROR] 계산 결과 없음")
            return jsonify({"error": "먼저 /run 도구를 실행하여 계산 결과를 생성해 주세요."}), 400

        diag = CURRENT_DATASET.get("inspect_result") or {}
        topic_hints = diag.get("topic_hints", {})
        filename = diag.get("filename", "데이터 파일")

        # 계산 데이터 요약
        tool_name = run_result.get("tool", "")
        ref_period = run_result.get("reference_period", "")
        used_rows = run_result.get("used_rows", 0)
        excluded_rows = run_result.get("excluded_rows", 0)
        exclusion_reason = run_result.get("exclusion_reason", "없음")
        unit = run_result.get("unit", "")
        caution = run_result.get("caution", "")
        calc_data = run_result.get("data", {})

        # 분석 질문 및 지표 주제 정의
        user_query = payload.get("query") or CURRENT_DATASET.get("last_query") or f"{tool_name} 통계 분석"
        topic = get_dataset_topic_title(diag)
        metric = topic_hints.get("metric", topic)
        polarity_guidance = get_metric_polarity_guidance(diag)

        prompt_b = f"""당신은 누구나 이해하기 쉽게 데이터를 설명해주는 친절한 데이터 멘토입니다.
중학생이나 일반 대중도 막힘없이 단번에 이해할 수 있도록, 어려운 통계/학술 전문 용어는 피하고 일상적인 언어와 명쾌한 비유를 사용해 설명해 주세요.

[분석 질문]
{user_query}

[데이터셋 기본 정보]
- 파일명: {filename}
- 주제(Topic): {topic}
- 핵심 지표(Metric): {metric}
- 단위: {unit}
- 분석 기본 주의사항: {caution}

{polarity_guidance}

[Pandas가 계산한 실제 통계 결과]
{json.dumps(calc_data, ensure_ascii=False, indent=2)}

[해설 작성 핵심 원칙]
1. [친절하고 쉬운 설명]: '왜도', '비대칭성', '표본 편향' 같은 딱딱한 전문 용어를 지양하고, "평균보다 높다/낮다", "격차가 크다", "~점 차이가 난다"처럼 일상적인 쉬운 표현으로 풀어쓰세요.
2. [점수 방향성 일관성 준수]: 반드시 위 [점수 방향성 절대 불변 원칙]을 100% 준수하여, 지표의 의미를 위아래 모순 없이 명확히 짚어주세요.
3. [구체적인 숫자 인용]: Pandas가 계산한 수치(1등 점수, 꼴찌 점수, 평균, 한국의 순위 및 점수 등)를 직접 짚어주며 알기 쉽게 비교해 주세요.
4. [체감할 수 있는 현실적 의미]: 이 숫자가 우리 일상과 사회에 어떤 영향을 주는지 공감할 수 있는 설명으로 마무리하세요.
5. 아래 5가지 Markdown 목차를 반드시 사용하여 가독성 높고 이해하기 쉬운 리포트로 구성하세요:

## 💡 1. 3초 쉬운 요약 (한 줄 결론)
- 이 데이터가 말하고자 하는 가장 핵심적인 결론 2~3가지를 굵은 글씨로 알기 쉽게 정리합니다.

## 🔍 2. 이 데이터는 무엇을 잰 건가요? (지표 쉬운 설명)
- 어떤 지표(측정 항목, 출처, 기준 시점)를 잰 것인지 일상 언어로 설명합니다.
- **이 점수가 높을수록 좋은 건지, 낮을수록 좋은 건지**를 위 원칙에 따라 명확히 짚어주세요.
- 분석 대상 국가/데이터는 총 몇 개({used_rows}개)인지 밝힙니다.

## 📊 3. 핵심 숫자와 비교 (누가 앞서고 있고 한국은 어디쯤일까요?)
- 1등과 꼴찌의 점수 차이, 전체 평균 점수를 알기 쉽게 비교합니다.
- 데이터에 한국(Korea)이 있다면, 한국의 점수와 순위, 그리고 평균보다 높은지/낮은지를 칭찬 또는 보완점으로 설명합니다.

## 🌟 4. 우리 삶에 왜 중요하고 무엇을 뜻하나요? (현실 속 의미)
- 이 수치가 왜 우리에게 중요한지, 실생활이나 국가의 미래에 어떤 영향을 주는지 알기 쉽게 설명합니다.

## 📌 5. 데이터를 볼 때 참고할 점 (쉬운 주의사항)
- 이 데이터를 볼 때 오해하지 말아야 할 점이나 참고할 한계점을 1~2문장으로 친절하게 알려줍니다.
"""

        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_b
            )
            explanation = resp.text or ""
            logger.info(f"[RESPONSE] status=200 explain_mode_B_complete (len={len(explanation)})")
            return jsonify({
                "status": "success",
                "mode": "B",
                "model": GEMINI_MODEL,
                "explanation": explanation
            })
        except Exception as e:
            logger.error(f"[ERROR] 모드 B 생성 중 오류: {str(e)}", exc_info=True)
            return jsonify({"error": f"해석 생성 중 오류가 발생했습니다: {str(e)}"}), 500


@app.route("/followup", methods=["POST"])
def followup():
    """보고서 및 분석 결과에 대한 후속 질문 Q&A 처리"""
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    report_text = data.get("report_text", "").strip()
    calculation_result = data.get("calculation_result") or {}
    meta = data.get("meta") or {}

    logger.info(f"[REQUEST] POST /followup query='{query}'")

    if not query:
        return jsonify({"error": "질문 내용을 입력해주세요."}), 400

    if not GEMINI_API_KEY:
        return jsonify({
            "status": "fallback",
            "reply": f"'{query}'에 대한 답변입니다. 현재 Gemini API 키가 설정되지 않아 상세 답변을 생성할 수 없습니다."
        })

    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)

    topic = meta.get("topic", "데이터 분석")
    metric = meta.get("metric", "지표")
    unit = meta.get("unit", "")
    calc_data = calculation_result.get("data") if calculation_result else {}

    # 실제 데이터셋 기반 전체 순위 및 최고/최하위 국가 통계 산출
    df = CURRENT_DATASET.get("df")
    diag = CURRENT_DATASET.get("inspect_result") or {}
    polarity_guidance = get_metric_polarity_guidance(diag)
    rankings_summary = ""
    ref_col = calculation_result.get("reference_period") or diag.get("recommended_year")

    if df is not None and not df.empty:
        try:
            import tools
            label_col = tools.resolve_label_column(df, {})
            if not ref_col or str(ref_col) not in df.columns:
                try:
                    ref_col = tools.resolve_reference_period(df, {})
                except Exception:
                    ref_col = None

            if ref_col and str(ref_col) in df.columns:
                work_df, _, _ = tools.filter_aggregate_rows(df, label_col)
                work_df, _ = tools.filter_survey_dimensions(work_df, {}, str(ref_col))
                s = pd.to_numeric(work_df[str(ref_col)], errors="coerce")
                valid_mask = s.notna()
                valid_sub = work_df[valid_mask].copy()
                valid_sub["_val"] = s[valid_mask]

                if not valid_sub.empty:
                    if valid_sub[label_col].nunique() < len(valid_sub):
                        agg_series = valid_sub.groupby(label_col)["_val"].mean().sort_values(ascending=False)
                    else:
                        agg_series = valid_sub.set_index(label_col)["_val"].sort_values(ascending=False)

                    total_n = len(agg_series)
                    top_5 = [f"{i+1}위: {k} ({round(float(v), 2)}점)" for i, (k, v) in enumerate(agg_series.head(5).items())]
                    bottom_5 = [f"{total_n - len(agg_series.tail(5)) + i + 1}위: {k} ({round(float(v), 2)}점)" for i, (k, v) in enumerate(agg_series.tail(5).items())]

                    korea_info = ""
                    for k in agg_series.index:
                        if any(alias in str(k).lower() for alias in ["korea", "한국"]):
                            r = int(agg_series.index.get_loc(k)) + 1
                            korea_info = f"- 한국({k}): 전체 {total_n}개국 중 {r}위 ({round(float(agg_series.loc[k]), 2)}점)\n"
                            break

                    rankings_summary = f"""
- 기준 시점: {ref_col}
- 전체 평가 대상 국가 수: 총 {total_n}개국
{korea_info}- 최상위 국가 TOP 5 (점수 가장 높음): {', '.join(top_5)}
- 최하위 국가 BOTTOM 5 (점수 가장 낮음): {', '.join(bottom_5)}
- 최하위 꼴찌(최저점) 국가: {agg_series.index[-1]} ({round(float(agg_series.iloc[-1]), 2)}점)
- 최상위 1위(최고점) 국가: {agg_series.index[0]} ({round(float(agg_series.iloc[0]), 2)}점)
"""
        except Exception as e:
            logger.warning(f"[WARN] followup 순위 계산 중 예외 발생: {e}")

    prompt = f"""당신은 방금 작성된 데이터 분석 보고서에 대해 사용자의 궁금증을 1:1로 친절하게 풀어주는 전문 데이터 멘토입니다.
중학생이나 일반 대중도 단번에 이해할 수 있도록 쉬운 일상 언어와 비유를 사용하여 명쾌하고 친절하게 답변해 주세요.

[현재 분석 중인 데이터 정보]
- 주제: {topic}
- 핵심 지표: {metric}
- 단위: {unit}

{polarity_guidance}

[데이터셋 실제 국가별 순위 및 최고/최하위 통계]
{rankings_summary if rankings_summary else "순위 상세 정보 없음"}

[Pandas 실제 계산 통계 요약]
{json.dumps(calc_data, ensure_ascii=False, indent=2) if calc_data else "계산 결과 없음"}

[기존에 생성된 보고서 내용 요약]
{report_text[:1500] if report_text else "보고서 내용 없음"}

[사용자의 후속 질문]
"{query}"

[답변 작성 핵심 가이드 (반드시 준수)]:
1. [🚨 구체적인 실명(국가 이름) 언급 필수]:
   - 사용자가 "어디 나라가 제일 부패했는지", "가장 점수가 낮은/높은 나라는 어디인지", "1등이나 꼴찌 국가는 어디인지", 특정 국가의 순위를 물어볼 때는,
     절대로 "점수가 가장 낮은 곳이 부패한 곳입니다"라는 식의 원론적인 설명이나 일반론만 말하고 끝내지 마세요!
   - 반드시 위 [데이터셋 실제 국가별 순위 및 최고/최하위 통계]를 직접 확인하여,
     **실제 데이터에 등장하는 구체적인 국가 이름(예: 멕시코, 콜롬비아, 덴마크 등)과 점수, 순위를 명확하게 실명으로 밝혀서** 직접 답변하세요!
     (예: "현재 데이터({ref_col or '기준시점'} 기준)에서 점수가 가장 낮아 부패 위험이 가장 높은(청렴도가 가장 낮은) 최하위 국가는 **[최하위 국가명]**([점수]점)입니다. 반대로 가장 청렴도가 높은 1위 국가는 **[1위 국가명]**([점수]점)입니다.")
2. [점수 방향성 일치 필수]:
   - 반드시 위 [점수 방향성 절대 불변 원칙]을 엄격히 준수하세요. 본 지표는 점수가 높을수록 청렴하고 낮을수록 부패한 지표이므로, 절대로 '점수가 낮아야 청렴하다'라거나 '점수가 높으면 부패하다'고 반대로 서술해서는 안 됩니다!
3. [명쾌한 두괄식 답변]:
   - 사용자의 질문에 대해 직관적이고 군더더기 없는 명쾌한 결론부터 먼저 말해주세요.
4. [친절한 경어체]:
   - 2~4개 문단 또는 불릿포인트를 활용해 읽기 편하게 작성하고, 친절하고 신뢰감 있는 경어체(~해요, ~합니다)를 사용하세요.
"""

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        reply = resp.text or ""
        logger.info(f"[RESPONSE] status=200 followup_complete (len={len(reply)})")
        return jsonify({
            "status": "success",
            "reply": reply
        })
    except Exception as e:
        logger.error(f"[ERROR] 후속 질문 답변 생성 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500


if __name__ == "__main__":
    flask_debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    port = int(os.getenv("PORT", 5000))
    logger.info(f"서버 실행: http://127.0.0.1:{port} (debug={flask_debug})")
    app.run(host="127.0.0.1", port=port, debug=flask_debug)
