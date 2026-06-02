# import streamlit as st
# import polars as pl
# import numpy as np
# from pathlib import Path

# from openms_insight import Table, LinePlot, StateManager

# st.set_page_config(page_title="Interactive Viewer", layout="wide")
# st.title("Interactive Data Viewer")

# # -----------------------------------------------------------------------------
# # Data setup - write to parquet for stable identity across reruns
# # -----------------------------------------------------------------------d------

# DATA_DIR = Path(__file__).parent / ".data"
# DATA_DIR.mkdir(exist_ok=True)

# # Force regenerate data if structure changed
# DATA_VERSION = 2
# VERSION_FILE = DATA_DIR / ".version"

# def should_regenerate():
#     if not VERSION_FILE.exists():
#         return True
#     try:
#         return int(VERSION_FILE.read_text().strip()) < DATA_VERSION
#     except:
#         return True

# if should_regenerate() or not (DATA_DIR / "spectra.parquet").exists():
#     np.random.seed(42)

#     # Spectra table
#     pl.DataFrame({
#         "scan_id": range(1, 11),
#         "rt": np.round(np.linspace(1.5, 15.0, 10), 2),
#         "precursor_mz": np.round(np.random.uniform(400, 1200, 10), 2),
#     }).write_parquet(DATA_DIR / "spectra.parquet")

#     # Peaks table - simulate MS2 fragmentation pattern
#     # Generate realistic-ish fragment masses for demo purposes
#     peaks = []
#     for scan_id in range(1, 11):
#         # Generate ~50-100 peaks per spectrum
#         n = np.random.randint(50, 100)

#         # Mix of fragment ions and noise
#         # Fragment-like peaks (roughly evenly spaced, higher intensity)
#         n_fragments = np.random.randint(10, 25)
#         fragment_masses = np.sort(np.random.uniform(150, 1400, n_fragments))
#         fragment_intensities = np.random.exponential(5000, n_fragments) + 1000

#         # Noise peaks (random, lower intensity)
#         n_noise = n - n_fragments
#         noise_masses = np.random.uniform(100, 1500, n_noise)
#         noise_intensities = np.random.exponential(500, n_noise)

#         # Combine and sort
#         all_masses = np.concatenate([fragment_masses, noise_masses])
#         all_intensities = np.concatenate([fragment_intensities, noise_intensities])
#         sort_idx = np.argsort(all_masses)
#         all_masses = all_masses[sort_idx]
#         all_intensities = all_intensities[sort_idx]

#         for i in range(len(all_masses)):
#             peaks.append({
#                 "peak_id": len(peaks),
#                 "scan_id": scan_id,
#                 "mass": round(all_masses[i], 4),
#                 "intensity": round(all_intensities[i], 1),
#             })

#     pl.DataFrame(peaks).write_parquet(DATA_DIR / "peaks.parquet")
#     VERSION_FILE.write_text(str(DATA_VERSION))

# # -----------------------------------------------------------------------------
# # Components
# # -----------------------------------------------------------------------------

# spectra_table = Table(
#     cache_id="spectra",
#     data=pl.scan_parquet(DATA_DIR / "spectra.parquet"),
#     interactivity={"spectrum": "scan_id"},
#     index_field="scan_id",
#     default_row=0,
#     column_definitions=[
#         {"field": "scan_id", "title": "Scan", "width": 60},
#         {"field": "rt", "title": "RT (min)", "sorter": "number"},
#         {"field": "precursor_mz", "title": "Precursor m/z", "sorter": "number"},
#     ],
#     title="Spectra",
# )

# peaks_table = Table(
#     cache_id="peaks",
#     data=pl.scan_parquet(DATA_DIR / "peaks.parquet"),
#     filters={"spectrum": "scan_id"},
#     interactivity={"peak": "peak_id"},
#     index_field="peak_id",
#     column_definitions=[
#         {"field": "mass", "title": "m/z", "sorter": "number",
#          "formatter": "money", "formatterParams": {"precision": 4, "symbol": ""}},
#         {"field": "intensity", "title": "Intensity", "sorter": "number",
#          "formatter": "money", "formatterParams": {"precision": 0, "symbol": ""}},
#     ],
#     title="Peaks",
#     initial_sort=[{"column": "intensity", "dir": "desc"}],
# )

# spectrum_plot = LinePlot(
#     cache_id="plot",
#     data=pl.scan_parquet(DATA_DIR / "peaks.parquet"),
#     filters={"spectrum": "scan_id"},
#     interactivity={"peak": "peak_id"},
#     x_column="mass",
#     y_column="intensity",
#     title="Mass Spectrum",
#     x_label="m/z",
#     y_label="Intensity",
# )

# # -----------------------------------------------------------------------------
# # Layout
# # -----------------------------------------------------------------------------

# state_manager = StateManager()

# # Top section: Spectra and Peaks tables
# col1, col2 = st.columns([1, 1])

# with col1:
#     spectra_table(key="spectra", state_manager=state_manager, height=250)

# with col2:
#     peaks_table(key="peaks", state_manager=state_manager, height=250)

# # Spectrum plot
# spectrum_plot(key="spectrum", state_manager=state_manager, height=300)
import pandas as pd
import streamlit as st

from openms_insight.analysis.parsers.expression_parser import ExpressionDataParser
from openms_insight.analysis.filter import ExpressionDataFilter
from openms_insight.analysis.imputation import ExpressionDataImputer
from openms_insight.analysis.filter import ExpressionDataFilter
from openms_insight.analysis.imputation import ExpressionDataImputer

test_params = {}
file_path = r"C:\Users\admin\Desktop\LFQ\quant_results\openms_msstats.csv"
# 1. Parsing (TMT/LFQ 규격화)
parser = ExpressionDataParser(workspace_path="./workspace", params=test_params)
# df_with_groups, group_map = parser.parse(file_path)
raw_result = parser.parse(file_path)

if raw_result is None:
    st.error("❌ 파서가 None을 반환했습니다! 아래 내용을 점검하세요.")
    
    try:
        debug_df = pd.read_csv(file_path, comment="#")
        st.warning(f"파일 읽기 성공! 감지된 컬럼명들: {list(debug_df.columns)}")
        if debug_df.empty:
            st.warning("경고: 파일이 비어있습니다.")
    except Exception as e:
        st.error(f"파일을 읽는 도중 에러 발생 (경로 오류 등): {e} ")

    st.stop()

df_with_groups, group_map = raw_result

st.dataframe(df_with_groups)
    
# 2. Filtering (품질 저하 데이터 제거)
filter_engine = ExpressionDataFilter(df_with_groups)
filtered_df = (
    filter_engine.filter_low_abundance(10.0)
    # .filter_low_repeatability(0.5)
    # .filter_low_variance(10.0)
    .get_result()
)

# 3. Imputation (결측치 처리 🎯 새롭게 추가된 단계)
imputer_engine = ExpressionDataImputer(filtered_df)

# 예시 A: MAR (Biological Group Median으로 채우기)
# imputed_df = imputer_engine.impute_mar(strategy="median").get_result()

# 예시 B: MNAR (각 행의 최솟값으로 채우기)
imputed_df = imputer_engine.impute_smallest_value(scope="row").get_result()

st.subheader("📊 Imputation Result Check")
st.dataframe(imputed_df)