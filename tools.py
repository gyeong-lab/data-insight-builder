import math
import re
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

# 집계 행 감지 키워드 목록
AGGREGATE_KEYWORDS = [
    "world", "oecd members", "euro area", "european union",
    "high income", "low income", "middle income", "upper middle income",
    "lower middle income", "income", "area", "total", "average", "aggregate",
    "countries", "ida & ibrd", "latin america", "sub-saharan africa",
    "east asia", "south asia", "north america", "middle east"
]


def sanitize_for_json(obj: Any) -> Any:
    """
    NaN, Infinity, -Infinity 값을 JSON 직렬화가 가능한 None 또는 표준 형태로 변환합니다.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 4)
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return round(float(obj), 4)
    return obj


def filter_aggregate_rows(df: pd.DataFrame, label_col: Optional[str] = None) -> tuple[pd.DataFrame, int, list]:
    """
    집계 행(World, OECD 등)을 식별하고 필터링합니다.
    (필터링된 DF, 제외된 행 수, 제외 이유 목록) 반환
    """
    if label_col is None or label_col not in df.columns:
        # 텍스트 열 중 첫 번째를 기본 레이블 컬럼으로 사용
        text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        label_col = text_cols[0] if text_cols else None

    if not label_col:
        return df, 0, []

    is_agg = df[label_col].astype(str).str.lower().apply(
        lambda val: any(kw in val for kw in AGGREGATE_KEYWORDS)
    )
    excluded_count = int(is_agg.sum())
    filtered_df = df[~is_agg].copy()
    reasons = [f"집계 행(대륙, 소득그룹, 총계 등) {excluded_count}개 제외"] if excluded_count > 0 else []

    return filtered_df, excluded_count, reasons


def resolve_label_column(df: pd.DataFrame, params: Dict[str, Any]) -> str:
    """
    params에서 라벨/국가명 열을 추출하고, 없으면 데이터프레임 내 가장 적합한 엔티티 열을 자동 탐색합니다.
    """
    col = params.get("label_column") or params.get("label_col") or params.get("item_column")
    if col and col in df.columns:
        return str(col)

    # 표준적인 국가/엔티티 라벨 컬럼명 우선 탐색
    priority_label_cols = [
        "Country Name", "Reference area", "Country", "Country/Territory",
        "REF_AREA", "Country Code", "Entity", "Item", "Name", "TableName"
    ]
    for pcol in priority_label_cols:
        if pcol in df.columns:
            return pcol

    # 텍스트 열 중 적절한 열 선택 (Unnamed/빈 열 제외)
    text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    if text_cols:
        good_text_cols = [c for c in text_cols if not str(c).lower().startswith("unnamed") and df[c].nunique() > 2]
        if good_text_cols:
            return str(good_text_cols[0])
        return str(text_cols[0])

    return str(df.columns[0])


def resolve_reference_period(df: pd.DataFrame, params: Dict[str, Any], default: Optional[str] = None) -> str:
    """
    params에서 기준 시점(연도 또는 열 이름)을 추출하고,
    누락되거나 비어있는 경우 데이터프레임 내 유효한 최신 연도 컬럼 또는 실제 수치 열로 자동 보정합니다.
    (모든 값이 NaN인 빈 열은 절대 반환하지 않음)
    """
    def is_valid_numeric_col(col_name: str) -> bool:
        if not col_name or col_name not in df.columns:
            return False
        s = pd.to_numeric(df[col_name], errors="coerce")
        return int(s.notna().sum()) > 0

    candidates = [
        params.get("reference_period"),
        params.get("year"),
        params.get("period"),
        params.get("period_to"),
        params.get("column"),
        default
    ]
    for cand in candidates:
        if cand:
            c_str = str(cand).strip()
            # 1. 컬럼으로 존재하고 실제 유효한 숫자가 있는 경우
            if is_valid_numeric_col(c_str):
                return c_str
            # 2. "2024년", "2024 (최신)" 등에서 4자리 연도 추출 시도
            m = re.search(r"\b(19\d\d|20\d\d)\b", c_str)
            if m and is_valid_numeric_col(m.group(1)):
                return m.group(1)

    # 3. Wide 포맷 연도 컬럼 탐색 (컬럼명이 1900~2099년 숫자 4자리인 경우)
    year_cols = [str(c) for c in df.columns if re.match(r"^(19\d\d|20\d\d)$", str(c).strip()) and is_valid_numeric_col(str(c))]
    if year_cols:
        sorted_years = sorted(year_cols, key=lambda y: int(y), reverse=True)
        min_threshold = max(1, int(len(df) * 0.3))
        good_coverage = [y for y in sorted_years if df[y].notna().sum() >= min_threshold]
        if good_coverage:
            return good_coverage[0]
        return sorted_years[0]

    # 4. Long 포맷(SDMX / Tidy 데이터) 표준 수치 열 탐색 (OBS_VALUE, Value 등)
    standard_value_cols = ["OBS_VALUE", "obs_value", "Value", "value", "VAL", "val", "Observation value"]
    for vcol in standard_value_cols:
        if is_valid_numeric_col(vcol):
            return vcol

    # 5. 그 외 유효한 숫자가 있는 열 중 고유값이 다양하고 가장 적합한 수치 열 탐색
    numeric_candidates = []
    for c in df.columns:
        if is_valid_numeric_col(str(c)):
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            # ID성 열(모두 고유)이나 상수 열(고유값 1개) 제외 우선순위 부여
            if s.nunique() > 1:
                numeric_candidates.append((str(c), s.nunique()))

    if numeric_candidates:
        numeric_candidates.sort(key=lambda x: x[1], reverse=True)
        return numeric_candidates[0][0]

    # 최후의 수단: 유효한 숫자가 1개라도 있는 아무 열
    for c in df.columns:
        if is_valid_numeric_col(str(c)):
            return str(c)

    if len(df.columns) > 0:
        return str(df.columns[0])

    raise ValueError("데이터프레임에 유효한 수치 열이 존재하지 않습니다.")


# ==========================================
# 도구 1: reshape_wide_to_long (Wide -> Long 변환)
# ==========================================
def reshape_wide_to_long(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    1960, 1961... 처럼 가로로 길게 늘어선 연도 열들을 'Year'와 'Value' 두 열로 세로로 접습니다 (melt).
    """
    id_vars = params.get("id_vars", [])
    if not id_vars:
        # 숫자가 아닌 열들을 기본 id_vars로 지정
        id_vars = [c for c in df.columns if not re.match(r"^(19\d\d|20\d\d)$", str(c))]

    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    value_vars = [str(c) for c in df.columns if year_pattern.match(str(c))]

    if not value_vars:
        raise ValueError("변환할 연도 형식의 열(1900~2099)을 찾을 수 없습니다.")

    melted = pd.melt(
        df,
        id_vars=id_vars,
        value_vars=value_vars,
        var_name="Year",
        value_name="Value"
    )

    # 결측치 정돈
    total_before = len(melted)
    melted_clean = melted.dropna(subset=["Value"]).copy()
    excluded = total_before - len(melted_clean)

    preview = melted_clean.head(10).replace({np.nan: None}).to_dict(orient="records")

    result = {
        "tool": "reshape_wide_to_long",
        "reference_period": "전체 연도",
        "used_rows": len(melted_clean),
        "excluded_rows": excluded,
        "exclusion_reason": f"Value 열이 결측치(NaN)인 행 {excluded}개 제외",
        "used_columns": id_vars + ["Year", "Value"],
        "unit": "행 (Long Format)",
        "caution": "연도 열을 세로로 변환한 결과로, 행 수가 원본보다 크게 증가합니다.",
        "data": {
            "total_rows": len(melted_clean),
            "preview": preview,
            "id_vars": id_vars,
            "year_range": f"{min(value_vars)} ~ {max(value_vars)}"
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 2: quality_report (데이터 품질 진단 리포트)
# ==========================================
def quality_report(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    결측치, 중복, 데이터 타입, 비어있거나 불완전한 열을 정밀 집계합니다.
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    missing_by_col = {}
    for col in df.columns:
        m_cnt = int(df[col].isna().sum())
        missing_by_col[str(col)] = {
            "count": m_cnt,
            "ratio_pct": round(m_cnt / total_rows * 100, 2) if total_rows > 0 else 0
        }

    duplicate_rows = int(df.duplicated().sum())
    unnamed_cols = [str(c) for c in df.columns if str(c).lower().startswith("unnamed:") or str(c) == ""]
    empty_cols = [str(c) for c in df.columns if df[c].isna().all()]

    result = {
        "tool": "quality_report",
        "reference_period": "전체 데이터셋",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "없음 (품질 검사를 위해 전체 행 사용)",
        "used_columns": [str(c) for c in df.columns],
        "unit": "건 / 비율(%)",
        "caution": "결측치가 80% 이상인 열은 개별 분석 시 신뢰성이 떨어지므로 주의해야 합니다.",
        "data": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "duplicate_rows": duplicate_rows,
            "empty_columns": empty_cols,
            "unnamed_columns": unnamed_cols,
            "missing_summary": missing_by_col
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 3: year_coverage (연도별 충실도 & 권장연도)
# ==========================================
def year_coverage(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    연도 열들의 유효 데이터 개수와 충실도(%)를 계산하고 최적의 권장 기준연도를 제안합니다.
    """
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c))]

    if not year_cols:
        raise ValueError("분석할 연도 열(1900~2099)이 존재하지 않습니다.")

    sorted_years = sorted(year_cols, key=lambda y: int(y))
    total_rows = len(df)

    coverage_data = []
    best_year = None
    best_count = 0

    # 차트용 데이터 형식 준비
    labels = []
    counts = []

    for y in sorted_years:
        valid_cnt = int(df[y].notna().sum())
        ratio = round(valid_cnt / total_rows * 100, 2) if total_rows > 0 else 0
        labels.append(y)
        counts.append(valid_cnt)
        coverage_data.append({
            "year": y,
            "valid_count": valid_cnt,
            "coverage_pct": ratio
        })

    # 권장연도 판별: 최근 연도 중 유효 개수가 행 수의 30% 이상인 최신 연도
    for y in reversed(sorted_years):
        v = int(df[y].notna().sum())
        if v >= total_rows * 0.3 and v > 0:
            best_year = y
            best_count = v
            break

    if not best_year:
        best_year = sorted_years[-1]

    result = {
        "tool": "year_coverage",
        "reference_period": f"{sorted_years[0]} ~ {sorted_years[-1]} (권장: {best_year})",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "없음 (전체 연도 충실도 비교를 위해 전체 행 사용)",
        "used_columns": sorted_years,
        "unit": "개 (유효 데이터 수)",
        "caution": "연도별로 데이터를 보고한 국가 수가 다르므로 시계열 비교 시 표본 수 변화에 유의하세요.",
        "data": {
            "recommended_year": best_year,
            "recommended_year_count": best_count,
            "chart": {
                "type": "bar",
                "labels": labels,
                "datasets": [{
                    "label": "연도별 유효 데이터 국가 수",
                    "data": counts
                }]
            },
            "coverage_list": coverage_data
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 4: detect_aggregates (집계 행 후보 탐지)
# ==========================================
def detect_aggregates(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    World, OECD members, High income 등 국가 단위가 아닌 대륙/경제권/소득 집계 행을 분리 탐지합니다.
    """
    label_col = params.get("label_column")
    if not label_col or label_col not in df.columns:
        text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        label_col = text_cols[0] if text_cols else None

    if not label_col:
        raise ValueError("집계 행을 탐지할 라벨(국가명 등) 열을 지정해야 합니다.")

    agg_rows = []
    for idx, val in df[label_col].dropna().items():
        v_str = str(val).strip()
        v_lower = v_str.lower()
        matched = [kw for kw in AGGREGATE_KEYWORDS if kw in v_lower]
        if matched:
            agg_rows.append({
                "row_index": int(idx),
                "name": v_str,
                "matched_keyword": matched[0],
                "reason": f"집계 키워드 '{matched[0]}' 포함"
            })

    total_rows = len(df)
    agg_count = len(agg_rows)

    result = {
        "tool": "detect_aggregates",
        "reference_period": "전체 데이터셋",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "없음 (집계 행 탐지 목적이므로 전체 행 분석)",
        "used_columns": [label_col],
        "unit": "개 (집계 행 후보 수)",
        "caution": "국가 간 순위나 통계를 계산할 때 이 집계 행들을 제외하지 않으면 왜곡된 결과가 나옵니다.",
        "data": {
            "label_column": label_col,
            "total_aggregates_detected": agg_count,
            "aggregates_ratio_pct": round(agg_count / total_rows * 100, 2) if total_rows > 0 else 0,
            "candidates": agg_rows
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 5: describe_numeric (기술통계)
# ==========================================
def describe_numeric(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    선택한 열(또는 기준연도 열)의 개수, 평균, 중앙값, 최소, 최대, 표준편차를 계산합니다.
    """
    col = params.get("column") or params.get("reference_period")
    if not col or col not in df.columns:
        # 숫자형 열 중 첫 번째 또는 권장연도 사용
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        col = num_cols[-1] if num_cols else None

    if not col:
        raise ValueError("기술통계를 계산할 숫자형 열을 찾을 수 없습니다.")

    exclude_agg = params.get("exclude_aggregates", True)
    label_col = params.get("label_column")

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    series = pd.to_numeric(work_df[col], errors="coerce")
    valid_series = series.dropna()

    null_count = len(series) - len(valid_series)
    total_excluded = excluded_agg_count + null_count
    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"결측치 {null_count}개 제외")

    if len(valid_series) == 0:
        raise ValueError(f"열 '{col}'에 유효한 숫자 데이터가 없습니다.")

    stats = {
        "count": int(valid_series.count()),
        "mean": float(valid_series.mean()),
        "median": float(valid_series.median()),
        "std": float(valid_series.std()) if len(valid_series) > 1 else 0.0,
        "min": float(valid_series.min()),
        "max": float(valid_series.max()),
        "q25": float(valid_series.quantile(0.25)),
        "q75": float(valid_series.quantile(0.75))
    }

    result = {
        "tool": "describe_numeric",
        "reference_period": str(col),
        "used_rows": len(valid_series),
        "excluded_rows": total_excluded,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [str(col)],
        "unit": "수치 단위 (원본 지표 기준)",
        "caution": "평균은 극단값(이상치)의 영향을 크게 받을 수 있으므로 중앙값과 함께 비교하세요.",
        "data": {
            "column": str(col),
            "stats": stats,
            "chart": {
                "type": "bar",
                "labels": ["평균", "중앙값", "최소값", "최대값"],
                "datasets": [{
                    "label": f"{col} 기술통계치",
                    "data": [stats["mean"], stats["median"], stats["min"], stats["max"]]
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 6: trend_line (연도별 추이 선 차트)
# ==========================================
def trend_line(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    선택한 항목(국가 등)들의 연도별 시계열 변화 추이를 선 차트로 생성합니다.
    Wide 포맷(연도 열) 및 Long 포맷(TIME_PERIOD/Year 열) 모두 지원합니다.
    """
    label_col = resolve_label_column(df, params)

    selected_items = params.get("items", [])
    if isinstance(selected_items, str):
        selected_items = [s.strip() for s in selected_items.split(",") if s.strip()]

    # 연도 컬럼 추출 (Wide 포맷)
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c))]
    sorted_years = sorted(year_cols, key=lambda y: int(y)) if year_cols else []

    is_long_format = False
    time_col = None
    val_col = None

    if not sorted_years:
        # Long 포맷 시계열 탐색 (TIME_PERIOD, Time period, Year 등)
        for tc in ["TIME_PERIOD", "Time period", "Year", "YEAR", "Period"]:
            if tc in df.columns:
                time_col = tc
                break
        if time_col:
            val_col = resolve_reference_period(df, params)
            unique_years = df[time_col].dropna().astype(str).unique()
            # 4자리 연도만 추출
            valid_years = [y for y in unique_years if re.match(r"^(19\d\d|20\d\d)$", y.strip())]
            if valid_years:
                sorted_years = sorted(valid_years, key=lambda y: int(y))
                is_long_format = True

    if not sorted_years:
        raise ValueError("시계열 추이를 그릴 연도 열 또는 시계열 데이터(TIME_PERIOD)를 찾을 수 없습니다.")

    # 특정 항목 미지정 시 한국 및 대표 4개국 자동 선택
    available_names = df[label_col].dropna().astype(str).unique().tolist()
    if not selected_items:
        preferred = ["Korea, Rep.", "Korea", "South Korea", "United States", "Japan", "Germany", "United Kingdom"]
        selected_items = [name for name in preferred if name in available_names]
        if not selected_items:
            # 한국 부분 일치 시도
            for name in available_names:
                if any(k in name.lower() for k in ["korea", "한국"]):
                    selected_items.append(name)
                    break
        if not selected_items:
            selected_items = available_names[:5]

    datasets = []
    total_data_points = 0
    missing_points = 0

    if is_long_format and time_col and val_col:
        # Long 포맷 피벗 집계
        for item in selected_items:
            item_df = df[df[label_col].astype(str) == str(item)]
            vals = []
            for y in sorted_years:
                matched = item_df[item_df[time_col].astype(str) == str(y)]
                if not matched.empty:
                    num_series = pd.to_numeric(matched[val_col], errors="coerce").dropna()
                    if not num_series.empty:
                        vals.append(round(float(num_series.mean()), 2))
                    else:
                        vals.append(None)
                        missing_points += 1
                else:
                    vals.append(None)
                    missing_points += 1
                total_data_points += 1

            datasets.append({
                "label": str(item),
                "data": vals,
                "fill": False
            })
    else:
        # Wide 포맷
        for item in selected_items:
            row_match = df[df[label_col].astype(str) == str(item)]
            if row_match.empty:
                continue
            row = row_match.iloc[0]
            vals = []
            for y in sorted_years:
                val = row.get(y)
                try:
                    f_val = float(val)
                    if math.isnan(f_val):
                        vals.append(None)
                        missing_points += 1
                    else:
                        vals.append(round(f_val, 2))
                except (ValueError, TypeError):
                    vals.append(None)
                    missing_points += 1
                total_data_points += 1

            datasets.append({
                "label": str(item),
                "data": vals,
                "fill": False
            })

    result = {
        "tool": "trend_line",
        "reference_period": f"{sorted_years[0]} ~ {sorted_years[-1]}",
        "used_rows": len(selected_items),
        "excluded_rows": 0,
        "exclusion_reason": f"데이터 포인트 결측치 {missing_points}개는 선 연결에서 제외" if missing_points else "없음",
        "used_columns": [label_col] + ([time_col, val_col] if is_long_format else sorted_years),
        "unit": "수치 단위 (연도별 변화)",
        "caution": "시계열 구간 중 중간 연도 데이터가 비어 있을 수 있으며, 이는 선이 끊기거나 결측으로 처리됩니다.",
        "data": {
            "label_column": label_col,
            "selected_items": selected_items,
            "year_range": f"{sorted_years[0]} ~ {sorted_years[-1]}",
            "chart": {
                "type": "line",
                "labels": sorted_years,
                "datasets": datasets
            }
        }
    }
    return sanitize_for_json(result)


def filter_survey_dimensions(df: pd.DataFrame, params: Dict[str, Any], ref_col: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Long 포맷 설문 지표 데이터셋에서 연도(TIME_PERIOD)와 설문 척도(Scale/SCALE) 등
    다차원 혼합으로 인해 국가별 평균이 25% 등으로 균일화되는 왜곡을 방지하기 위해 스마트 필터링을 수행합니다.
    """
    work_df = df.copy()
    reasons = []

    # 1. TIME_PERIOD / Time period (연도) 필터링
    time_col = None
    for c in ["TIME_PERIOD", "Time period", "Year", "YEAR", "Period"]:
        if c in work_df.columns:
            time_col = c
            break

    if time_col and time_col != ref_col:
        # 질문이나 params에 특정 연도가 있는지 확인
        req_year = None
        for cand in [params.get("reference_period"), params.get("year")]:
            if cand:
                m = re.search(r"\b(19\d\d|20\d\d)\b", str(cand))
                if m:
                    req_year = int(m.group(1))
                    break

        available_years = pd.to_numeric(work_df[time_col], errors="coerce").dropna().unique()
        if len(available_years) > 1:
            target_year = None
            if req_year and req_year in available_years:
                target_year = req_year
            else:
                target_year = int(max(available_years))

            before_count = len(work_df)
            work_df = work_df[pd.to_numeric(work_df[time_col], errors="coerce") == target_year].copy()
            reasons.append(f"최신 조사 연도({target_year}년) 데이터만 선별 ({before_count - len(work_df)}개 행 제외)")

    # 2. Scale / SCALE / Answer (설문 척도) 필터링
    scale_col = None
    for c in ["Scale", "SCALE", "Answer", "Response"]:
        if c in work_df.columns:
            scale_col = c
            break

    if scale_col and scale_col != ref_col:
        unique_scales = work_df[scale_col].dropna().astype(str).unique()
        if len(unique_scales) > 1:
            target_scale = None
            for s in unique_scales:
                s_lower = s.lower().strip()
                if any(kw in s_lower for kw in ["likely", "lik", "agree", "yes", "high", "positive"]):
                    target_scale = s
                    break

            if target_scale:
                before_count = len(work_df)
                work_df = work_df[work_df[scale_col].astype(str) == target_scale].copy()
                reasons.append(f"청렴도 대표 긍정 척도('{target_scale}')만 선별하여 왜곡 방지 ({before_count - len(work_df)}개 중립/부정 행 제외)")

    return work_df, reasons


# ==========================================
# 도구 7: top_bottom_n (기준연도 상위·하위 N 수평 막대)
# ==========================================
def top_bottom_n(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    기준연도(reference_period)를 기준으로 상위 N개, 하위 N개 항목을 계산합니다 (수평 막대).
    기준 시점 필수!
    """
    ref_col = resolve_reference_period(df, params)
    n = int(params.get("n", 10))
    label_col = resolve_label_column(df, params)

    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    reasons = []

    # 1. 집계 행(World, OECD 등) 제외
    if exclude_agg:
        work_df, excluded_agg_count, agg_reasons = filter_aggregate_rows(work_df, label_col)
        reasons.extend(agg_reasons)

    # 2. Long 포맷 설문 다차원(연도 및 Likely 척도) 스마트 선별
    work_df, dim_reasons = filter_survey_dimensions(work_df, params, ref_col)
    reasons.extend(dim_reasons)

    # 3. 기준 시점에 값이 없는 행 필터링
    series = pd.to_numeric(work_df[ref_col], errors="coerce")
    valid_mask = series.notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()
    valid_df["_val"] = series[valid_mask]

    if null_count > 0:
        reasons.append(f"기준 시점({ref_col}) 결측치 행 {null_count}개 제외")

    if valid_df.empty:
        raise ValueError(f"기준 시점({ref_col})에 유효한 데이터가 전혀 없습니다.")

    # 4. 동일 엔티티(국가) 복수 측정값 집계
    is_multi_row_entity = valid_df[label_col].nunique() < len(valid_df)
    if is_multi_row_entity:
        reasons.append(f"동일 항목({label_col}) 내 다중 세부지표가 감지되어 고유 항목별 평균값 기준으로 순위를 정렬했습니다.")
        calc_df = valid_df.groupby(label_col, as_index=False)["_val"].mean()
    else:
        calc_df = valid_df[[label_col, "_val"]].copy()

    # 정렬
    sorted_df = calc_df.sort_values(by="_val", ascending=False).reset_index(drop=True)
    actual_n = min(n, len(sorted_df))
    top_n = sorted_df.head(actual_n)
    bottom_n = sorted_df.tail(actual_n).iloc[::-1]  # 가장 낮은 것부터

    top_labels = top_n[label_col].astype(str).tolist()
    top_values = top_n["_val"].round(2).tolist()

    bottom_labels = bottom_n[label_col].astype(str).tolist()
    bottom_values = bottom_n["_val"].round(2).tolist()

    # 특정 비교 대상(target_item, 예: Korea, 한국)이 지정된 경우 하이라이트 및 추가 비교
    target_item = params.get("target_item")
    top_bg_colors = ["#2563eb"] * len(top_labels)
    top_border_colors = ["#1d4ed8"] * len(top_labels)
    top_list_data = [{"rank": i+1, "label": l, "value": v} for i, (l, v) in enumerate(zip(top_labels, top_values))]

    if target_item:
        target_str = str(target_item).strip().lower()
        match_idx = None
        for idx, row in sorted_df.iterrows():
            if str(row[label_col]).strip().lower() == target_str:
                match_idx = idx
                break

        if match_idx is not None:
            target_rank = int(match_idx) + 1
            target_val = round(float(sorted_df.iloc[match_idx]["_val"]), 2)
            target_real_label = str(sorted_df.iloc[match_idx][label_col])

            # 상위 N에 이미 포함되어 있는 경우 색상 하이라이트
            in_top_idx = None
            for i, l in enumerate(top_labels):
                if l.lower() == target_str or l.lower() == target_real_label.lower():
                    in_top_idx = i
                    break

            if in_top_idx is not None:
                top_bg_colors[in_top_idx] = "#f59e0b"
                top_border_colors[in_top_idx] = "#d97706"
                top_list_data[in_top_idx]["is_target"] = True
            else:
                # 상위 N에 없는 경우 (예: 한국이 25위 등), 차트 및 목록 끝에 별도 비교 항목으로 추가
                compare_label = f"{target_real_label} ({target_rank}위)"
                top_labels.append(compare_label)
                top_values.append(target_val)
                top_bg_colors.append("#f59e0b")
                top_border_colors.append("#d97706")
                top_list_data.append({
                    "rank": target_rank,
                    "label": compare_label,
                    "value": target_val,
                    "is_target": True
                })

    chart_top = {
        "type": "bar",
        "indexAxis": "y",
        "labels": top_labels,
        "datasets": [{
            "label": f"상위 {actual_n}위 {'및 ' + str(target_item) if target_item else ''} ({ref_col} {'평균' if is_multi_row_entity else ''})",
            "data": top_values,
            "backgroundColor": top_bg_colors if target_item else "#2563eb",
            "borderColor": top_border_colors if target_item else "#1d4ed8",
            "borderWidth": 1
        }]
    }

    chart_bottom = {
        "type": "bar",
        "indexAxis": "y",
        "labels": bottom_labels,
        "datasets": [{
            "label": f"하위 {actual_n}위 ({ref_col} {'평균' if is_multi_row_entity else ''})",
            "data": bottom_values,
            "backgroundColor": "#ef4444",
            "borderColor": "#b91c1c",
            "borderWidth": 1
        }]
    }

    result = {
        "tool": "top_bottom_n",
        "reference_period": ref_col,
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [label_col, ref_col],
        "unit": "수치 (상하위 순위)",
        "caution": f"기준 시점({ref_col})에 결측치인 항목은 제외되었으며, 1개 항목당 여러 측정값이 있을 경우 고유 항목별 평균 기준으로 순위가 산출되었습니다.",
        "data": {
            "n": actual_n,
            "top_n": top_list_data,
            "bottom_n": [{"rank": i+1, "label": l, "value": v} for i, (l, v) in enumerate(zip(bottom_labels, bottom_values))],
            "chart": chart_top,
            "chart_top": chart_top,
            "chart_bottom": chart_bottom
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 8: group_summary (그룹별 평균·합계·개수)
# ==========================================
def group_summary(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    기준 시점의 값을 특정 범주형 그룹 열 기준으로 평균, 합계, 개수를 집계합니다.
    기준 시점 필수!
    """
    ref_col = resolve_reference_period(df, params)
    group_col = params.get("group_column")

    # group_col 미지정 시 선호 그룹 열 및 고유값 2~30개 텍스트 열 탐색
    if not group_col or group_col not in df.columns:
        preferred_groups = ["Scale", "IncomeGroup", "Region", "Category", "Measure", "Sector"]
        for pg in preferred_groups:
            if pg in df.columns and 2 <= df[pg].nunique() <= 30:
                group_col = pg
                break

    if not group_col or group_col not in df.columns:
        for c in df.columns:
            if not pd.api.types.is_numeric_dtype(df[c]) and 2 <= df[c].nunique() <= 30:
                group_col = c
                break

    if not group_col or group_col not in df.columns:
        group_col = "Indicator Name" if "Indicator Name" in df.columns else df.columns[1]

    exclude_agg = params.get("exclude_aggregates", True)
    label_col = resolve_label_column(df, params)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    series = pd.to_numeric(work_df[ref_col], errors="coerce")
    valid_mask = series.notna() & work_df[group_col].notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()
    valid_df["_val"] = series[valid_mask]

    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"기준 시점 또는 그룹 열 결측치 {null_count}개 제외")

    if valid_df.empty:
        raise ValueError(f"기준 시점({ref_col}) 및 그룹 열({group_col})에 유효한 데이터가 없습니다.")

    grouped = valid_df.groupby(group_col)["_val"].agg(
        count="count",
        mean="mean",
        sum="sum",
        median="median"
    ).reset_index()

    labels = grouped[group_col].astype(str).tolist()
    means = grouped["mean"].round(2).tolist()
    counts = grouped["count"].astype(int).tolist()

    result = {
        "tool": "group_summary",
        "reference_period": ref_col,
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [group_col, ref_col],
        "unit": "수치 (그룹별 평균)",
        "caution": "그룹 간 표본 크기(데이터 수) 차이가 클 경우 단순 평균 비교 시 편향이 발생할 수 있습니다.",
        "data": {
            "group_column": group_col,
            "groups": grouped.to_dict(orient="records"),
            "chart": {
                "type": "bar",
                "labels": labels,
                "datasets": [{
                    "label": f"그룹별 평균 ({ref_col}년)",
                    "data": means
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 9: change_rate (두 시점 사이 변화량·변화율)
# ==========================================
def change_rate(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    기준 시점(period_to)과 이전 시점(period_from) 사이의 절대 변화량 및 변화율(%)을 계산합니다.
    기준 시점 필수!
    """
    period_to = resolve_reference_period(df, params)
    period_from = params.get("period_from")

    # period_from 미지정 시 10년 전 또는 5년 전 또는 이전 연도 자동 선정
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c))]
    sorted_years = sorted(year_cols, key=lambda y: int(y))

    if not period_from:
        if period_to in sorted_years:
            idx = sorted_years.index(period_to)
            period_from = sorted_years[max(0, idx - 10)] if idx >= 10 else sorted_years[0]
        else:
            raise ValueError("비교할 시작 시점(period_from)을 지정해야 합니다.")

    period_from = str(period_from)
    if period_from not in df.columns:
        raise ValueError(f"시작 시점 열 '{period_from}'을 찾을 수 없습니다.")

    n = int(params.get("n", 10))
    label_col = params.get("label_column") or "Country Name"
    if label_col not in df.columns:
        text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        label_col = text_cols[0] if text_cols else df.columns[0]

    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    s_from = pd.to_numeric(work_df[period_from], errors="coerce")
    s_to = pd.to_numeric(work_df[period_to], errors="coerce")

    # 두 시점 모두 데이터가 있는 행만 추출
    valid_mask = s_from.notna() & s_to.notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()

    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"두 시점 중 하나라도 결측치인 행 {null_count}개 제외")

    if valid_df.empty:
        raise ValueError(f"두 시점({period_from} -> {period_to}) 모두 유효한 데이터가 없습니다.")

    v_from = s_from[valid_mask]
    v_to = s_to[valid_mask]

    diff = v_to - v_from
    pct_change = np.where(v_from != 0, (diff / v_from.abs()) * 100, np.nan)

    valid_df["_from"] = v_from
    valid_df["_to"] = v_to
    valid_df["_diff"] = diff
    valid_df["_pct"] = pct_change

    # 변화량 기준 상위 N개국
    sorted_diff = valid_df.sort_values(by="_diff", ascending=False)
    top_diff = sorted_diff.head(n)

    labels = top_diff[label_col].astype(str).tolist()
    diff_values = top_diff["_diff"].round(2).tolist()
    pct_values = top_diff["_pct"].round(2).tolist()

    result = {
        "tool": "change_rate",
        "reference_period": f"{period_from} -> {period_to}",
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [label_col, period_from, period_to],
        "unit": "수치 변화량 (p.p. 또는 %)",
        "caution": "시작 시점의 기초 수치가 매우 작은 경우 변화율(%)이 비정상적으로 과장될 수 있으므로 절대 변화량과 함께 비교하세요.",
        "data": {
            "period_from": period_from,
            "period_to": period_to,
            "top_increasers": [
                {"label": l, "from": f, "to": t, "diff": d, "pct": p}
                for l, f, t, d, p in zip(
                    labels,
                    top_diff["_from"].round(2),
                    top_diff["_to"].round(2),
                    diff_values,
                    pct_values
                )
            ],
            "chart": {
                "type": "bar",
                "labels": labels,
                "datasets": [{
                    "label": f"절대 증가량 ({period_from} 대비 {period_to})",
                    "data": diff_values
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 10: distribution (구간별 분포 히스토그램)
# ==========================================
def distribution(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    기준 시점(reference_period) 데이터의 값 구간별 분포(히스토그램) 빈도수를 계산합니다.
    기준 시점 필수!
    """
    ref_col = resolve_reference_period(df, params)
    bins_count = int(params.get("bins", 10))
    label_col = params.get("label_column") or "Country Name"

    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    series = pd.to_numeric(work_df[ref_col], errors="coerce")
    valid_series = series.dropna()
    null_count = len(series) - len(valid_series)

    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"결측치 {null_count}개 제외")

    if len(valid_series) == 0:
        raise ValueError(f"열 '{ref_col}'에 유효한 숫자 데이터가 없습니다.")

    # 히스토그램 빈(구간) 계산
    counts, bin_edges = np.histogram(valid_series, bins=bins_count)
    labels = [f"{round(bin_edges[i], 1)} ~ {round(bin_edges[i+1], 1)}" for i in range(len(counts))]
    counts_list = [int(c) for c in counts]

    result = {
        "tool": "distribution",
        "reference_period": ref_col,
        "used_rows": len(valid_series),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [ref_col],
        "unit": "개국 (빈도수)",
        "caution": "특정 구간에 빈도가 극단적으로 치우친 경우 데이터의 편향이나 불평등 구조를 시사합니다.",
        "data": {
            "column": ref_col,
            "bins": bins_count,
            "histogram": [{"range": l, "count": c} for l, c in zip(labels, counts_list)],
            "chart": {
                "type": "bar",
                "labels": labels,
                "datasets": [{
                    "label": f"{ref_col}년 분포 빈도수",
                    "data": counts_list
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 11: correlation_scatter (두 숫자 열 상관계수 및 산점도)
# ==========================================
def correlation_scatter(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    두 숫자 열 사이의 피어슨 상관계수를 계산하고 산점도(Scatter) 데이터를 생성합니다.
    기준 시점 필수! (또는 비교할 두 숫자 열)
    절대 규칙: '상관관계는 인과관계가 아니다' 필수 명시!
    """
    col_x = params.get("col_x") or params.get("reference_period")
    col_y = params.get("col_y")

    # 만약 col_y가 없으면 다른 연도 또는 다른 숫자 열 자동 탐색
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c))]

    if not col_x or str(col_x) not in df.columns:
        col_x = year_cols[-1] if year_cols else None

    if not col_x:
        raise ValueError("11번 도구(correlation_scatter)는 'reference_period'(기준 열)가 필수입니다.")

    col_x = str(col_x)

    if not col_y or str(col_y) not in df.columns:
        # col_x와 다른 이전 연도를 비교 열로 선정 (예: 2024 vs 2014)
        if col_x in year_cols:
            idx = year_cols.index(col_x)
            col_y = year_cols[max(0, idx - 10)] if idx >= 10 else year_cols[0]
        else:
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != col_x]
            col_y = num_cols[0] if num_cols else None

    if not col_y or col_y == col_x:
        raise ValueError("비교할 유효한 두 번째 숫자 열(col_y)을 찾을 수 없습니다.")

    col_y = str(col_y)
    label_col = params.get("label_column") or "Country Name"

    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    sx = pd.to_numeric(work_df[col_x], errors="coerce")
    sy = pd.to_numeric(work_df[col_y], errors="coerce")

    valid_mask = sx.notna() & sy.notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()

    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"두 변수 중 결측치 행 {null_count}개 제외")

    if len(valid_df) < 2:
        raise ValueError("상관계수를 계산하기 위한 유효 행 수가 2개 미만입니다.")

    vx = sx[valid_mask]
    vy = sy[valid_mask]

    corr = float(vx.corr(vy))
    labels_list = valid_df[label_col].astype(str).tolist() if label_col in valid_df.columns else []

    # 산점도 포인트 구조: [{x: ..., y: ..., label: ...}]
    scatter_points = []
    for i, (x_val, y_val) in enumerate(zip(vx, vy)):
        lbl = labels_list[i] if i < len(labels_list) else f"Row {i+1}"
        scatter_points.append({
            "x": round(float(x_val), 2),
            "y": round(float(y_val), 2),
            "label": lbl
        })

    result = {
        "tool": "correlation_scatter",
        "reference_period": f"{col_x} vs {col_y}",
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [col_x, col_y],
        "unit": "상관계수 (-1.0 ~ +1.0)",
        "caution": "상관관계는 인과관계가 아닙니다. 두 변수 사이의 통계적 상관성이 원인과 결과를 직접 증명하지 않습니다.",
        "data": {
            "col_x": col_x,
            "col_y": col_y,
            "correlation_coefficient": round(corr, 4),
            "interpretation": "강한 양의 상관관계" if corr > 0.7 else ("양의 상관관계" if corr > 0.3 else ("상관관계 약함" if corr > -0.3 else "음의 상관관계")),
            "chart": {
                "type": "scatter",
                "datasets": [{
                    "label": f"{col_x} vs {col_y} 산점도",
                    "data": scatter_points
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값)
# ==========================================
def compare_one_vs_all(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    특정 1개 항목(예: Korea, Rep.)의 수치를 전체 평균 및 중앙값과 비교합니다 (강조 막대 차트).
    기준 시점 필수!
    """
    ref_col = resolve_reference_period(df, params)
    target_item = params.get("target_item") or params.get("item") or "Korea, Rep."
    label_col = resolve_label_column(df, params)

    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    reasons = []
    if exclude_agg:
        work_df, excluded_agg_count, agg_reasons = filter_aggregate_rows(work_df, label_col)
        reasons.extend(agg_reasons)

    work_df, dim_reasons = filter_survey_dimensions(work_df, params, ref_col)
    reasons.extend(dim_reasons)

    series = pd.to_numeric(work_df[ref_col], errors="coerce")
    valid_mask = series.notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()
    valid_df["_val"] = series[valid_mask]

    if null_count > 0:
        reasons.append(f"기준 시점({ref_col}) 결측치 행 {null_count}개 제외")

    if valid_df.empty:
        raise ValueError(f"기준 시점({ref_col})에 유효한 데이터가 없습니다.")

    # 엔티티당 복수 행이 존재하는 Long 포맷인지 확인
    is_multi_row = valid_df[label_col].nunique() < len(valid_df)
    if is_multi_row:
        entity_series = valid_df.groupby(label_col)["_val"].mean()
        overall_mean = float(entity_series.mean())
        overall_median = float(entity_series.median())
    else:
        overall_mean = float(valid_df["_val"].mean())
        overall_median = float(valid_df["_val"].median())

    # 타겟 항목 조회 및 별칭(Alias) 지원
    target_item_str = str(target_item).strip()
    korean_aliases = [
        "Korea, Rep.", "Korea", "South Korea", "Republic of Korea", 
        "Korea, Republic of", "대한민국", "한국"
    ]
    is_korea_query = target_item_str.lower() in [
        "korea", "korea, rep.", "south korea", "republic of korea", 
        "korea, republic of", "한국", "대한민국", "남한"
    ]

    available_labels = valid_df[label_col].dropna().astype(str).unique().tolist()
    target_rows = pd.DataFrame()

    if is_korea_query:
        # 데이터셋에 실제로 존재하는 한국 명칭 후보 우선 탐색
        for alias in korean_aliases:
            found = [lbl for lbl in available_labels if lbl.lower() == alias.lower()]
            if found:
                target_rows = valid_df[valid_df[label_col].astype(str) == found[0]]
                target_item = found[0]
                break
        if target_rows.empty:
            for lbl in available_labels:
                if any(k in lbl.lower() for k in ["korea", "한국"]):
                    target_rows = valid_df[valid_df[label_col].astype(str) == lbl]
                    target_item = lbl
                    break
    else:
        other_aliases = {
            "미국": "United States", "usa": "United States",
            "일본": "Japan", "중국": "China",
            "독일": "Germany", "영국": "United Kingdom", "uk": "United Kingdom",
            "프랑스": "France"
        }
        search_kw = other_aliases.get(target_item_str.lower(), target_item_str)
        matched_lbls = [lbl for lbl in available_labels if lbl.lower() == search_kw.lower()]
        if matched_lbls:
            target_rows = valid_df[valid_df[label_col].astype(str) == matched_lbls[0]]
            target_item = matched_lbls[0]
        else:
            partial_lbls = [lbl for lbl in available_labels if search_kw.lower() in lbl.lower()]
            if partial_lbls:
                target_rows = valid_df[valid_df[label_col].astype(str) == partial_lbls[0]]
                target_item = partial_lbls[0]

    if target_rows.empty:
        target_item = str(valid_df.iloc[0][label_col])
        target_rows = valid_df[valid_df[label_col].astype(str) == target_item]

    # 복수 행일 경우 타겟 항목의 평균값 사용
    target_val = float(target_rows["_val"].mean())
    diff_from_mean = target_val - overall_mean
    diff_from_median = target_val - overall_median

    # 전체 엔티티 순위 분석 (최고점 1위, 최하위 꼴찌, 타겟 국가 순위 도출)
    if is_multi_row:
        ranked_series = valid_df.groupby(label_col)["_val"].mean().sort_values(ascending=False)
    else:
        ranked_series = valid_df.set_index(label_col)["_val"].sort_values(ascending=False)

    total_entities_count = len(ranked_series)
    top_entity_name = str(ranked_series.index[0])
    top_entity_val = float(ranked_series.iloc[0])
    bottom_entity_name = str(ranked_series.index[-1])
    bottom_entity_val = float(ranked_series.iloc[-1])

    target_rank = None
    if target_item in ranked_series.index:
        target_rank = int(ranked_series.index.get_loc(target_item)) + 1

    top_3_list = [
        {"rank": i + 1, "name": str(k), "value": round(float(v), 2)}
        for i, (k, v) in enumerate(ranked_series.head(3).items())
    ]
    bottom_3_list = [
        {"rank": total_entities_count - len(ranked_series.tail(3)) + i + 1, "name": str(k), "value": round(float(v), 2)}
        for i, (k, v) in enumerate(ranked_series.tail(3).items())
    ]

    result = {
        "tool": "compare_one_vs_all",
        "reference_period": ref_col,
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [label_col, ref_col],
        "unit": "수치 (지표 기준값)",
        "caution": "특정 단일 항목과 전체 통계를 비교할 때 전체 집단의 정규분포 여부를 확인해야 왜곡을 피할 수 있습니다.",
        "data": {
            "target_item": target_item,
            "target_value": round(target_val, 2),
            "target_rank": target_rank,
            "total_entities_count": total_entities_count,
            "overall_mean": round(overall_mean, 2),
            "overall_median": round(overall_median, 2),
            "diff_from_mean": round(diff_from_mean, 2),
            "diff_from_median": round(diff_from_median, 2),
            "highest_country": {"name": top_entity_name, "value": round(top_entity_val, 2)},
            "lowest_country": {"name": bottom_entity_name, "value": round(bottom_entity_val, 2)},
            "top_3_ranking": top_3_list,
            "bottom_3_ranking": bottom_3_list,
            "is_entity_averaged": is_multi_row,
            "chart": {
                "type": "bar",
                "labels": [f"{target_item} (선택 항목)", "전체 평균", "전체 중앙값"],
                "datasets": [{
                    "label": f"{ref_col} 비교",
                    "data": [round(target_val, 2), round(overall_mean, 2), round(overall_median, 2)],
                    "backgroundColor": ["#2563eb", "#64748b", "#0d9488"],
                    "borderColor": ["#1d4ed8", "#475569", "#0f766e"],
                    "borderWidth": 1.5
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 13: detect_outliers (이상치 탐지: 평균에서 크게 벗어난 항목)
# ==========================================
def detect_outliers(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    기준 시점(reference_period) 데이터에서 평균으로부터 크게 벗어난 이상치(Outliers)를 탐지합니다.
    - Z-Score 방식 (|Z| >= 2.0 또는 사용자 지정 임계값)
    - IQR 방식 (Q1 - 1.5*IQR 이하 또는 Q3 + 1.5*IQR 이상)
    기준 시점 필수!
    """
    ref_col = resolve_reference_period(df, params)
    label_col = params.get("label_column") or "Country Name"
    if label_col not in df.columns:
        text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        label_col = text_cols[0] if text_cols else df.columns[0]

    threshold_z = float(params.get("threshold_z", 2.0))
    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    series = pd.to_numeric(work_df[ref_col], errors="coerce")
    valid_mask = series.notna()
    null_count = int((~valid_mask).sum())
    valid_df = work_df[valid_mask].copy()
    valid_vals = series[valid_mask]
    valid_df["_val"] = valid_vals

    reasons = []
    if excluded_agg_count > 0:
        reasons.append(f"집계 행 {excluded_agg_count}개 제외")
    if null_count > 0:
        reasons.append(f"기준 시점({ref_col}) 결측치 행 {null_count}개 제외")

    if len(valid_df) < 3:
        raise ValueError(f"열 '{ref_col}'에 이상치를 판별할 유효 데이터가 충분하지 않습니다 (최소 3개 필요).")

    mean_val = float(valid_vals.mean())
    std_val = float(valid_vals.std()) if len(valid_vals) > 1 else 1.0

    # Z-Score 계산
    z_scores = (valid_vals - mean_val) / std_val if std_val > 0 else (valid_vals * 0)
    valid_df["_z_score"] = z_scores

    # IQR 계산
    q25 = float(valid_vals.quantile(0.25))
    q75 = float(valid_vals.quantile(0.75))
    iqr = q75 - q25
    lower_bound_iqr = q25 - 1.5 * iqr
    upper_bound_iqr = q75 + 1.5 * iqr

    # 이상치 판별 (Z-score 절대값 >= threshold_z)
    outlier_mask = valid_df["_z_score"].abs() >= threshold_z
    outlier_df = valid_df[outlier_mask].sort_values(by="_z_score", key=abs, ascending=False)

    outliers_list = []
    for _, row in outlier_df.iterrows():
        val = float(row["_val"])
        z = float(row["_z_score"])
        is_high = val > mean_val
        outliers_list.append({
            "label": str(row[label_col]),
            "value": round(val, 2),
            "mean": round(mean_val, 2),
            "diff_from_mean": round(val - mean_val, 2),
            "z_score": round(z, 2),
            "type": "상위 극단값(매우 높음)" if is_high else "하위 극단값(매우 낮음)",
            "description": f"평균({round(mean_val, 1)})보다 표준편차의 {round(abs(z), 1)}배만큼 {'높음' if is_high else '낮음'}"
        })

    # 시각화 데이터 (이상치 상위 10개 및 전체 평균 비교)
    chart_labels = ["전체 평균"] + [o["label"] for o in outliers_list[:10]]
    chart_data = [round(mean_val, 2)] + [o["value"] for o in outliers_list[:10]]
    chart_colors = ["#94a3b8"] + ["#ef4444" if o["value"] < mean_val else "#10b981" for o in outliers_list[:10]]

    result = {
        "tool": "detect_outliers",
        "reference_period": ref_col,
        "used_rows": len(valid_df),
        "excluded_rows": excluded_agg_count + null_count,
        "exclusion_reason": ", ".join(reasons) if reasons else "없음",
        "used_columns": [label_col, ref_col],
        "unit": "수치 (Z-Score 및 원본 단위)",
        "caution": "이상치(극단값)는 단순한 오류 데이터일 수도 있고, 특별한 정책적 성과나 특수 환경을 반영한 중요한 발견일 수도 있으므로 원인을 면밀히 검토해야 합니다.",
        "data": {
            "mean": round(mean_val, 2),
            "std": round(std_val, 2),
            "threshold_z": threshold_z,
            "total_outliers_count": len(outliers_list),
            "iqr_bounds": {"lower": round(lower_bound_iqr, 2), "upper": round(upper_bound_iqr, 2)},
            "outliers": outliers_list,
            "chart": {
                "type": "bar",
                "labels": chart_labels,
                "datasets": [{
                    "label": f"평균 vs 주요 이상치 ({ref_col}년)",
                    "data": chart_data,
                    "backgroundColor": chart_colors
                }]
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 14: forecast_trend (시계열 회귀 및 미래 추세 예측)
# ==========================================
def forecast_trend(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    선택한 국가/항목(또는 전체 평균)의 시계열 과거 실적을 바탕으로 선형 회귀 추세 및
    연평균 성장률(CAGR)을 분석하고, 향후 3~5개 시점(연도)의 미래 예측치와 95% 신뢰구간을 도출합니다.
    """
    label_col = resolve_label_column(df, params)

    # 1. 시계열 연도 열 파악 (Wide 포맷 또는 Long 포맷)
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c))]
    sorted_years = sorted(year_cols, key=lambda y: int(y)) if year_cols else []

    is_long_format = False
    time_col = None
    val_col = None

    if not sorted_years:
        for tc in ["TIME_PERIOD", "Time period", "Year", "YEAR", "Period"]:
            if tc in df.columns:
                time_col = tc
                break
        if time_col:
            val_col = resolve_reference_period(df, params)
            unique_years = df[time_col].dropna().astype(str).unique()
            valid_years = [y for y in unique_years if re.match(r"^(19\d\d|20\d\d)$", y.strip())]
            if valid_years:
                sorted_years = sorted(valid_years, key=lambda y: int(y))
                is_long_format = True

    if len(sorted_years) < 3:
        raise ValueError("시계열 미래 예측을 수행하려면 최소 3개 이상의 연도 데이터가 필요합니다.")

    # 2. 대상 항목 (국가/라벨) 결정
    target_item = params.get("target_item") or params.get("country") or params.get("item")
    available_names = df[label_col].dropna().astype(str).unique().tolist()

    if not target_item or target_item not in available_names:
        # 한국 우선 탐색, 없으면 첫 번째 유효 항목
        preferred = ["Korea, Rep.", "Korea", "South Korea", "대한민국", "한국"]
        for p in preferred:
            if p in available_names:
                target_item = p
                break
        if not target_item:
            for name in available_names:
                if any(k in name.lower() for k in ["korea", "한국"]):
                    target_item = name
                    break
        if not target_item:
            target_item = available_names[0] if available_names else "전체 평균"

    # 3. 과거 시계열 데이터 추출
    hist_x = []
    hist_y = []
    missing_points = 0

    if is_long_format:
        sub_df = df[df[label_col].astype(str) == str(target_item)]
        sub_map = dict(zip(sub_df[time_col].astype(str), pd.to_numeric(sub_df[val_col], errors="coerce")))
        for y in sorted_years:
            val = sub_map.get(y)
            if val is not None and not math.isnan(val):
                hist_x.append(int(y))
                hist_y.append(float(val))
            else:
                missing_points += 1
    else:
        row_match = df[df[label_col].astype(str) == str(target_item)]
        if not row_match.empty:
            row = row_match.iloc[0]
            for y in sorted_years:
                try:
                    f_val = float(row.get(y))
                    if not math.isnan(f_val):
                        hist_x.append(int(y))
                        hist_y.append(f_val)
                    else:
                        missing_points += 1
                except (ValueError, TypeError):
                    missing_points += 1

    if len(hist_x) < 3:
        raise ValueError(f"'{target_item}'의 유효 시계열 데이터가 3개 미만이어서 신뢰할 수 있는 예측이 불가능합니다.")

    # 4. 회귀 분석 및 예측 통계량 산출 (Numpy)
    arr_x = np.array(hist_x, dtype=float)
    arr_y = np.array(hist_y, dtype=float)
    n = len(arr_x)

    # 1차 선형 회귀: y = m*x + b
    slope, intercept = np.polyfit(arr_x, arr_y, 1)
    fitted_y = slope * arr_x + intercept

    ss_tot = float(np.sum((arr_y - np.mean(arr_y)) ** 2))
    ss_res = float(np.sum((arr_y - fitted_y) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))

    # 잔차 표준 오차 (Residual Standard Error)
    df_resid = max(1, n - 2)
    s_err = math.sqrt(ss_res / df_resid)
    x_mean = float(np.mean(arr_x))
    sum_sq_x = float(np.sum((arr_x - x_mean) ** 2))

    # 연평균 성장률 (CAGR)
    cagr = 0.0
    if len(hist_y) >= 2 and hist_y[0] > 0 and hist_y[-1] > 0:
        cagr = (hist_y[-1] / hist_y[0]) ** (1.0 / max(1, hist_x[-1] - hist_x[0])) - 1.0

    # 5. 미래 시점 예측 (기본 향후 4개 연도)
    periods_ahead = int(params.get("periods_ahead", 4))
    periods_ahead = max(2, min(10, periods_ahead))
    last_year = hist_x[-1]

    future_years = [last_year + i for i in range(1, periods_ahead + 1)]
    forecast_points = []

    for fut_y in future_years:
        pred_val = slope * fut_y + intercept
        # 95% 예측 신뢰구간 (Prediction Interval)
        leverage = 1.0 + (1.0 / n) + (((fut_y - x_mean) ** 2) / sum_sq_x) if sum_sq_x > 0 else 1.0
        margin = 1.96 * s_err * math.sqrt(leverage)
        lower_bound = pred_val - margin
        upper_bound = pred_val + margin

        forecast_points.append({
            "year": str(fut_y),
            "predicted": round(pred_val, 2),
            "lower_95": round(lower_bound, 2),
            "upper_95": round(upper_bound, 2)
        })

    # 6. Chart.js 시각화 데이터셋 구성
    all_label_years = [str(y) for y in sorted_years] + [str(y) for y in future_years]

    # 과거 실적 데이터 배열 (미래 구간은 null)
    hist_chart_data = []
    hist_dict = dict(zip([str(x) for x in hist_x], hist_y))
    for y_str in all_label_years:
        if y_str in hist_dict:
            hist_chart_data.append(round(hist_dict[y_str], 2))
        else:
            hist_chart_data.append(None)

    # 미래 예측치 데이터 배열 (과거 마지막 점부터 매끄럽게 연결)
    pred_chart_data = [None] * len(all_label_years)
    upper_chart_data = [None] * len(all_label_years)
    lower_chart_data = [None] * len(all_label_years)

    last_idx = all_label_years.index(str(last_year))
    pred_chart_data[last_idx] = round(hist_dict.get(str(last_year), arr_y[-1]), 2)
    upper_chart_data[last_idx] = pred_chart_data[last_idx]
    lower_chart_data[last_idx] = pred_chart_data[last_idx]

    for fp in forecast_points:
        idx = all_label_years.index(fp["year"])
        pred_chart_data[idx] = fp["predicted"]
        upper_chart_data[idx] = fp["upper_95"]
        lower_chart_data[idx] = fp["lower_95"]

    datasets = [
        {
            "label": f"{target_item} (실제 관측치)",
            "data": hist_chart_data,
            "borderColor": "#2563eb",
            "backgroundColor": "rgba(37,99,235,0.1)",
            "fill": False,
            "borderWidth": 2.5,
            "pointRadius": 4,
            "tension": 0.1
        },
        {
            "label": f"{target_item} (미래 예측 추세선)",
            "data": pred_chart_data,
            "borderColor": "#7c3aed",
            "backgroundColor": "rgba(124,58,237,0.1)",
            "borderDash": [6, 6],
            "borderWidth": 2.5,
            "pointRadius": 4,
            "fill": False,
            "tension": 0.1
        },
        {
            "label": "95% 예측 신뢰구간 (상한)",
            "data": upper_chart_data,
            "borderColor": "#94a3b8",
            "borderDash": [2, 4],
            "borderWidth": 1.5,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.1
        },
        {
            "label": "95% 예측 신뢰구간 (하한)",
            "data": lower_chart_data,
            "borderColor": "#94a3b8",
            "borderDash": [2, 4],
            "borderWidth": 1.5,
            "pointRadius": 0,
            "fill": False,
            "tension": 0.1
        }
    ]

    # 추세 해석 문구
    if slope > 0.05:
        trend_desc = "지속적인 우상향 상승세"
    elif slope > 0.005:
        trend_desc = "완만한 증가 추세"
    elif slope < -0.05:
        trend_desc = "지속적인 하락세"
    elif slope < -0.005:
        trend_desc = "완만한 감소 추세"
    else:
        trend_desc = "큰 변동 없는 정체/보합 상태"

    result = {
        "tool": "forecast_trend",
        "reference_period": f"{hist_x[0]}~{hist_x[-1]} (예측: {future_years[0]}~{future_years[-1]})",
        "used_rows": 1,
        "excluded_rows": 0,
        "exclusion_reason": f"과거 결측치 {missing_points}개는 추세 계산에서 제외" if missing_points else "없음",
        "used_columns": [label_col] + sorted_years,
        "unit": "수치 (회귀 추세 및 미래 예측)",
        "caution": "미래 예측치는 과거 데이터의 추세(선형 회귀)가 앞으로도 동일하게 유지된다는 가정하에 계산된 통계적 추정치이며, 급격한 대외 정책 변화나 외생 변수에 의해 실제 결과와 다를 수 있습니다.",
        "data": {
            "target_item": target_item,
            "historical_period": f"{hist_x[0]}~{hist_x[-1]}",
            "forecast_period": f"{future_years[0]}~{future_years[-1]}",
            "metrics": {
                "r_squared": round(r_squared, 4),
                "annual_change_slope": round(slope, 3),
                "cagr_percent": round(cagr * 100, 2),
                "trend_description": trend_desc,
                "confidence_level": "높음 (R² >= 0.8)" if r_squared >= 0.8 else ("보통 (0.5 <= R² < 0.8)" if r_squared >= 0.5 else "낮음 (변동성 큼)"),
                "sample_points_count": n
            },
            "forecast_table": forecast_points,
            "chart": {
                "type": "line",
                "labels": all_label_years,
                "datasets": datasets
            }
        }
    }
    return sanitize_for_json(result)


# ==========================================
# 도구 15: correlation_matrix (전체 수치형 변수 상관관계 매트릭스)
# ==========================================
def correlation_matrix(df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    데이터셋 내의 모든 수치형 열(또는 대표 시계열 연도들) 간의 피어슨 상관계수를 산출하여,
    전체 상관관계 히트맵 매트릭스 및 가장 밀접한 상관관계/반비례 변수 쌍을 도출합니다.
    """
    label_col = resolve_label_column(df, params)
    exclude_agg = params.get("exclude_aggregates", True)

    work_df = df.copy()
    excluded_agg_count = 0
    if exclude_agg:
        work_df, excluded_agg_count, _ = filter_aggregate_rows(work_df, label_col)

    # 1. 수치형 열 후보군 추출
    year_pattern = re.compile(r"^(19\d\d|20\d\d)$")
    year_cols = [str(c) for c in work_df.columns if year_pattern.match(str(c))]

    selected_cols = []
    if len(year_cols) >= 4:
        # 연도 열이 많을 경우 대표 연도 6~8개 엄선 (최근 연도 및 5년 주기)
        sorted_y = sorted(year_cols, key=lambda y: int(y))
        if len(sorted_y) <= 8:
            selected_cols = sorted_y
        else:
            # 최근 4개 연도 + 5년 단위 과거 4개 연도
            recent_4 = sorted_y[-4:]
            sampled_past = [sorted_y[i] for i in range(0, len(sorted_y) - 4, max(1, (len(sorted_y) - 4) // 4))][:4]
            selected_cols = sorted(list(set(sampled_past + recent_4)), key=lambda y: int(y))
    else:
        # 일반 수치형 열 전체 탐색
        for col in work_df.columns:
            if col == label_col:
                continue
            numeric_s = pd.to_numeric(work_df[col], errors="coerce")
            if numeric_s.notna().sum() >= 5:
                selected_cols.append(col)

    if len(selected_cols) < 2:
        raise ValueError("상관관계 매트릭스를 계산할 수치형 열이 최소 2개 이상 필요합니다.")

    # 최대 10개 열로 제한하여 시각적 명확성 확보
    if len(selected_cols) > 10:
        selected_cols = selected_cols[-10:]

    # 2. 결측치 정제 및 상관계수 행렬 계산
    num_df = work_df[selected_cols].apply(pd.to_numeric, errors="coerce")
    corr_df = num_df.corr(method="pearson")

    # 3. 변수 쌍 상관도 순위 추출 (자기 자신 대각선 제외)
    pairs = []
    cols = list(corr_df.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c1 = cols[i]
            c2 = cols[j]
            r = corr_df.loc[c1, c2]
            if not math.isnan(r):
                pairs.append({
                    "var1": str(c1),
                    "var2": str(c2),
                    "pair_name": f"{c1} ↔ {c2}",
                    "correlation": round(float(r), 4),
                    "abs_corr": round(abs(float(r)), 4),
                    "interpretation": "강한 양의 상관관계" if r >= 0.7 else ("양의 상관관계" if r >= 0.3 else ("상관관계 없음" if r >= -0.3 else ("음의 상관관계" if r >= -0.7 else "강한 음의 상관관계")))
                })

    pairs.sort(key=lambda p: p["correlation"], reverse=True)
    top_positive = pairs[:3] if pairs else []
    top_negative = sorted(pairs, key=lambda p: p["correlation"])[:3] if pairs else []

    # 4. 2차원 매트릭스 배열 구조화
    matrix_data = []
    for c1 in cols:
        row_vals = []
        for c2 in cols:
            val = corr_df.loc[c1, c2]
            row_vals.append(round(float(val), 3) if not math.isnan(val) else 0.0)
        matrix_data.append(row_vals)

    # 5. 상위 상관관계 비교 차트 데이터 (수평 막대 차트)
    top_chart_pairs = (top_positive + [p for p in top_negative if p["correlation"] < 0])[:8]
    chart_labels = [p["pair_name"] for p in top_chart_pairs]
    chart_values = [p["correlation"] for p in top_chart_pairs]
    chart_colors = ["#10b981" if v >= 0 else "#ef4444" for v in chart_values]

    result = {
        "tool": "correlation_matrix",
        "reference_period": f"{cols[0]} ~ {cols[-1]} (전체 {len(cols)}개 지표/연도)",
        "used_rows": len(work_df),
        "excluded_rows": excluded_agg_count,
        "exclusion_reason": f"집계 행 {excluded_agg_count}개 제외" if excluded_agg_count else "없음",
        "used_columns": cols,
        "unit": "피어슨 상관계수 r (-1.0 ~ +1.0)",
        "caution": "상관관계는 인과관계가 아닙니다. 두 지표의 상관계수가 높더라도 하나의 변화가 다른 하나의 직접적인 원인임을 보장하지 않습니다.",
        "data": {
            "columns": cols,
            "matrix": matrix_data,
            "top_positive_pairs": top_positive,
            "top_negative_pairs": top_negative,
            "chart": {
                "type": "bar",
                "indexAxis": "y",
                "labels": chart_labels,
                "datasets": [{
                    "label": "변수 쌍 피어슨 상관계수 (r)",
                    "data": chart_values,
                    "backgroundColor": chart_colors
                }]
            }
        }
    }
    return sanitize_for_json(result)

