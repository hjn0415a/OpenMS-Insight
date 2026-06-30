import streamlit as st
import polars as pl
import numpy as np
import plotly.express as px
import traceback
from openms_insight.analysis.filter import filter_low_abundance, filter_low_repeatability, filter_low_variance
from openms_insight.analysis.imputation import impute_mar, impute_smallest_value
from openms_insight.analysis.normalization import transform_data, normalize_samples, scale_data
from openms_insight.analysis.statistics import calculate_statistical_tests, adjust_fdr_lazy
# Added the decoupled module import
from openms_insight.analysis.enrichment import calculate_go_enrichment

file_path = r"C:\Users\admin\Desktop\test.csv"

st.title("Proteomics Advanced Data Studio (Polars Stream Engine)")

try:
    # -------------------------------------------------------------------------
    # 📑 [Polars Optimization Layer] Metadata Mapping & File Structure Extraction
    # -------------------------------------------------------------------------
    init_df = pl.read_csv(file_path, n_rows=1)
    columns = init_df.columns
    
    id_col = columns[0] 
    sample_cols = columns[1:]
    group_values = init_df.row(0)[1:]
    
    # Core auxiliary design pattern for non-breaking streaming graph loops
    metadata = pl.DataFrame({
        "sample_id": sample_cols,
        "group": group_values
    })
    
    st.write("📊 **Extracted Metadata (Auxiliary DataFrame):**")
    st.dataframe(metadata)

    # Declare heavy body data sequence as a deferred evaluation pointer
    quantification_data = pl.scan_csv(file_path, skip_rows=2, has_header=False, new_columns=columns)
    
    # Cast target sample matrices to high precision floating numbers instantly
    quantification_data = quantification_data.with_columns([
        pl.col(col).cast(pl.Float64, strict=False) for col in sample_cols
    ])
except Exception as e:
    st.error(f"Failed to read CSV file: {e}")
    st.stop()


# -------------------------------------------------------------------------
# 🔍 Stage 1: Filtering Pipeline Execution Block
# -------------------------------------------------------------------------
filter_pipeline = (
    quantification_data
    .pipe(filter_low_abundance, metadata=metadata, group_column="group", threshold_percentile=10.0)
)

st.subheader("🔍 Stage 1: Filtered Data Table")
with st.spinner("Polars is parsing active filtering masks..."):
    filtered_df = filter_pipeline.collect(streaming=True)
st.dataframe(filtered_df)


# -------------------------------------------------------------------------
# 🎯 Stage 2: Imputation Pipeline Execution Block
# -------------------------------------------------------------------------
impute_pipeline = (
    filter_pipeline
    .pipe(impute_smallest_value, metadata=metadata, scope="row")
)

st.subheader("📊 Stage 2: Imputation Result Check")
with st.spinner("Polars is filling structural missing values..."):
    imputed_df = impute_pipeline.collect(streaming=True)
st.dataframe(imputed_df)


# -------------------------------------------------------------------------
# 🧪 Stage 3: Interactive Normalization Parameter Panel Selector
# -------------------------------------------------------------------------
st.write("---")
st.header("🧪 3. Data Normalization Step")

detected_groups = sorted(metadata.select("group").to_series().unique().to_list())
group_count = len(detected_groups)
st.info(f"💡 Detected Biological Groups in this file: {detected_groups} ({group_count} groups)")

st.markdown("### ⚙️ Choose Pipeline Configurations")
ui_col1, ui_col2, ui_col3 = st.columns(3)

with ui_col1:
    transform_opt = st.selectbox(
        "⚡ Step 1: Data Transformation",
        options=["log2", "log10", "square_root", "cube_root", "None"],
        index=0,
        help="Compresses extreme values and scales heteroscedastic data variance.",
    )

with ui_col2:
    norm_opt = st.selectbox(
        "🛡️ Step 2: Sample Normalization",
        options=["median", "sum", "pqn", "reference_feature", "quantile", "None"],
        index=0,
        help="Removes systematic loading differences across sample columns.",
    )

with ui_col3:
    scale_opt = st.selectbox(
        "📊 Step 3: Data Scaling",
        options=["mean_centering", "auto_scaling", "pareto_scaling", "range_scaling", "None"],
        index=0,
        help="Standardizes variance limits across row-wise proteins.",
    )

# -------------------------------------------------------------------------
# 🎯 Extract Entire Protein List from Dataset and Bind to Selectbox
# -------------------------------------------------------------------------
protein_list = imputed_df.select(id_col).to_series().unique(maintain_order=True).to_list()

normalization_ref_protein = None

if norm_opt == "reference_feature":
    normalization_ref_protein = st.selectbox(
        "🧬 Please select the REFERENCE PROTEIN from the list",
        options=protein_list,
        index=0,
        help="This protein will be used as the scaling factor (denominator) for normalization."
    )


# -------------------------------------------------------------------------
# ⛓️ Dynamic Workflow Processor Block (Polars Graph Forking)
# -------------------------------------------------------------------------
lazy_imputed = imputed_df.lazy()

try:
    df_step1_lazy = lazy_imputed.pipe(transform_data, metadata=metadata, strategy=transform_opt)
    
    df_step2_lazy = df_step1_lazy.pipe(
        normalize_samples, 
        metadata=metadata, 
        strategy=norm_opt, 
        id_col=id_col, 
        reference_feature=normalization_ref_protein
    )
    
    df_step3_lazy = df_step2_lazy.pipe(scale_data, metadata=metadata, strategy=scale_opt)

    with st.spinner("Recalculating downstream normalization matrices..."):
        df_step1 = df_step1_lazy.collect(streaming=True)
        df_step2 = df_step2_lazy.collect(streaming=True)
        df_step3 = df_step3_lazy.collect(streaming=True)

except Exception as e:
    st.error(f"❌ Pipeline Execution Failed during processing: {e}")
    st.code(traceback.format_exc())
    st.stop()


# -------------------------------------------------------------------------
# 📈 Relocate the Target Protein Selectbox for Visualization
# -------------------------------------------------------------------------
if norm_opt == "reference_feature":
    viz_target_protein = normalization_ref_protein
else:
    st.write("---")
    viz_target_protein = st.selectbox(
        "📈 Select Protein to Visualize (Monitor profile transitions in the chart below)",
        options=protein_list,
        index=0,
        help="Select any protein ID from the table to see how its values change through each step."
    )


# -------------------------------------------------------------------------
# ✅ Data Integrity & Normalization QA Dynamic Checker (Debugging Panel)
# -------------------------------------------------------------------------
protein_exists = (df_step3.select(id_col).to_series() == viz_target_protein).any()

if not protein_exists:
    st.warning(f"⚠️ The protein '{viz_target_protein}' could not be found in the dataset.")
    sample_list = df_step3.select(id_col).to_series().slice(0, 5).to_list()
    st.info(f"💡 Example input: {', '.join(sample_list)}")
    
    st.subheader("📋 Preprocessed Expression Table (Current Configuration)")
    st.dataframe(df_step3)
else:
    st.write("---")
    st.subheader("✅ Data Integrity & Normalization QA Check")

    qa_col1, qa_col2, qa_col3 = st.columns(3)

    with qa_col1:
        st.markdown(f"**Step 1: Transformation ({transform_opt})**")
        if transform_opt != "None":
            mat_step1 = df_step1.select(sample_cols).to_numpy()
            max_val = np.nanmax(mat_step1)
            min_val = np.nanmin(mat_step1)
            st.metric("Max Transformed Value", f"{max_val:.2f}")
            st.metric("Min Transformed Value", f"{min_val:.2f}")
        else:
            st.info("Skipped (Raw values applied)")

    with qa_col2:
        st.markdown(f"**Step 2: Normalization ({norm_opt})**")
        mat_step2 = df_step2.select(sample_cols)
        
        if norm_opt == "median":
            medians = [mat_step2.select(col).median().item() for col in sample_cols]
            median_deviation = max(medians) - min(medians)
            if median_deviation < 1e-9:
                st.success("⭕ Medians Perfectly Aligned!")
            else:
                st.error(f"❌ Alignment Shift (Dev: {median_deviation:.4f})")
            st.metric("Common Sample Median", f"{medians[0]:.4f}")
            
        elif norm_opt == "sum":
            sums = [mat_step2.select(col).sum().item() for col in sample_cols]
            sum_deviation = max(sums) - min(sums)
            if sum_deviation < 1e-4:
                st.success("⭕ Grand Total Sums Aligned!")
            else:
                st.error(f"❌ Sums Varied (Dev: {sum_deviation:.2f})")
            st.metric("Total Column Sum", f"{sums[0]:.2f}")
            
        elif norm_opt == "quantile":
            col1_sorted = np.sort(mat_step2.select(sample_cols[0]).to_numpy().flatten())
            col2_sorted = np.sort(mat_step2.select(sample_cols[1]).to_numpy().flatten())
            quant_dev = np.max(np.abs(col1_sorted - col2_sorted))
            if quant_dev < 1e-9:
                st.success("⭕ Identical Profiles Forged!")
            else:
                st.error("❌ Profile Distribution Mismatch")
                
        elif norm_opt == "reference_feature":
            ref_row_step2 = df_step2.filter(pl.col(id_col) == viz_target_protein).select(sample_cols)
            if len(ref_row_step2) > 0:
                ref_values = [ref_row_step2.select(col).item() for col in sample_cols]
                if all(abs(val - 1.0) < 1e-5 for val in ref_values if val is not None):
                    st.success("⭕ Reference Protein Scale Flattened to 1.0!")
                else:
                    st.warning("⚠️ Reference Values deviated from 1.0. Check for multiple rows or zeros.")
                st.metric("Ref Feature Value (Sample 1)", f"{ref_values[0]:.2f}")
            else:
                st.error("❌ Ref protein missing in step 2.")
                
        elif norm_opt == "None":
            st.info("Skipped")
        else:
            st.info(f"⭕ Applied: {norm_opt}")

    with qa_col3:
        st.markdown(f"**Step 3: Scaling ({scale_opt})**")
        mat_step3 = df_step3.select(sample_cols)
            
        if scale_opt == "mean_centering":
            row_means = df_step3.select([pl.mean_horizontal(sample_cols)]).to_series().to_numpy()
            meta_mean = np.nanmean(row_means)
            if abs(meta_mean) < 1e-5:
                st.success("⭕ Centers Fixed at 0")
            else:
                st.error("❌ Offset Center")
            st.metric("Avg Row Means", f"{meta_mean:.4f}")
        elif scale_opt == "auto_scaling":
            row_means = df_step3.select([pl.mean_horizontal(sample_cols)]).to_series().to_numpy()
            row_stds = df_step3.select([pl.concat_list(sample_cols).list.var().sqrt()]).to_series().to_numpy()
            meta_mean = np.nanmean(row_means)
            meta_std = np.nanmean(row_stds)
            if abs(meta_mean) < 1e-5 and abs(meta_std - 1.0) < 1e-3:
                st.success("⭕ Mean at 0 & Std Dev at 1!")
            else:
                st.warning("⚠️ Auto scaling bounds slightly offset (check for constants/zeros).")
            st.metric("Avg Mean / Std Dev", f"{meta_mean:.2f} / {meta_std:.2f}")
        elif scale_opt == "None":
            st.info("Skipped")
        else:
            st.info(f"⭕ Applied: {scale_opt}")
            
    st.write("---")

    # -------------------------------------------------------------------------
    # 📈 Protein Profiling Line Plot Section (Dynamic Plotly Processing)
    # -------------------------------------------------------------------------
    def get_protein_series_polars(df, label):
        row_data = df.filter(pl.col(id_col) == viz_target_protein).select(sample_cols).row(0)
        return pl.DataFrame({
            "Sample": sample_cols,
            "Intensity": list(row_data),
            "Step": [label] * len(sample_cols)
        })

    viz_df_polars = pl.concat([
        get_protein_series_polars(imputed_df, "1. Raw Data"),
        get_protein_series_polars(df_step1, f"2. {transform_opt}"),
        get_protein_series_polars(df_step2, f"3. {norm_opt}"),
        get_protein_series_polars(df_step3, f"4. {scale_opt}")
    ])
    
    st.subheader("📋 Preprocessed Expression Table (Current Configuration)")
    st.dataframe(df_step3)

    csv_buffer_prep = df_step3.write_csv().encode("utf-8")
    st.download_button(
        label="📥 Download Preprocessed Expression Table (CSV)",
        data=csv_buffer_prep,
        file_name="openms_insight_preprocessed_data.csv",
        mime="text/csv",
        key="download_prep"
    )

    st.subheader(f"📈 Normalization Graph for: {viz_target_protein}")
    
    fig = px.line(
        viz_df_polars.to_pandas(), 
        x="Sample",
        y="Intensity",
        color="Step",
        facet_col="Step",
        facet_col_wrap=2,
        markers=True,
        title=f"Pipeline Transformation Profile [{viz_target_protein}]",
        labels={"Intensity": "Value Level"},
    )
    fig.update_yaxes(matches=None, showgrid=True)
    fig.update_layout(showlegend=False, height=500)
    st.plotly_chart(fig, use_container_width=True)


# =========================================================================
# 📊 Stage 4: Advanced Statistical Analysis Step (Polars Powered)
# =========================================================================
st.write("---")
st.header("🧪 4. Statistical Analysis Step")

st.markdown("### ⚙️ Select Statistical Parameters")
stat_col1, stat_col2 = st.columns(2)

with stat_col1:
    if group_count == 2:
        stat_method_opt = st.selectbox(
            "🎯 Select Statistical Test Method",
            options=["limma_like", "welch", "paired"],
            format_func=lambda x: {
                "limma_like": "Limma-like (Empirical Bayes moderated t-test)",
                "welch": "Welch's t-test (Independent)",
                "paired": "Paired t-test (Dependent)"
            }[x]
        )
    else:
        stat_method_opt = st.selectbox(
            "🎯 Select Statistical Test Method",
            options=["limma_like", "anova"],
            format_func=lambda x: {
                "limma_like": "Limma-like (Empirical Bayes moderated F-test)",
                "anova": "One-way ANOVA (Standard)"
            }[x]
        )

with stat_col2:
    fdr_strategy_opt = st.selectbox(
        "🛡️ Select Multiple Testing Correction",
        options=["BH", "Bonferroni"],
        format_func=lambda x: {
            "BH": "Benjamini-Hochberg (FDR Control)",
            "Bonferroni": "Bonferroni (Strict FWER Control)"
        }[x]
    )

# Scope final_statistics_report to handle downstream pipeline validation safely
final_statistics_report = None

try:
    with st.spinner("Executing non-breaking lazy statistical matrix calculations..."):
        stat_lazy_pipeline = (
            df_step3.lazy()
            .pipe(calculate_statistical_tests, metadata=metadata, method=stat_method_opt)
            .pipe(adjust_fdr_lazy, strategy=fdr_strategy_opt)
        )
        
        final_statistics_report = stat_lazy_pipeline.collect(streaming=True)

    display_name = {
        "limma_like": "Limma-like (Empirical Bayes)",
        "welch": "Welch's t-test",
        "paired": "Paired t-test",
        "anova": "One-way ANOVA"
    }[stat_method_opt]

    st.success(f"⭕ Statistical pipeline successfully executed using **{display_name}**!")
    st.info(
        f"• **Experimental Groups:** {detected_groups} ({group_count} groups detected)\n"
        f"• **Applied Adjustment:** {fdr_strategy_opt} procedure"
    )

    st.subheader("📋 Final Statistical Analysis Report Table")
    st.dataframe(final_statistics_report)

    csv_buffer_stat = final_statistics_report.write_csv().encode("utf-8")
    st.download_button(
        label="📥 Download Full Statistics Report (CSV)",
        data=csv_buffer_stat,
        file_name="openms_insight_statistics_report.csv",
        mime="text/csv",
        key="download_stat"
    )

except Exception as e:
    st.error(f"❌ Statistical pipeline execution failed: {str(e)}")
    st.code(traceback.format_exc())


# =========================================================================
# 🧬 Stage 5: GO Enrichment Analysis Step (Decoupled Module Layer)
# =========================================================================
# Placed out of Stage 4 scope to preserve structured procedural stream pipeline maps
if final_statistics_report is not None:
    st.write("---")
    st.header("🧬 5. Gene Ontology (GO) Enrichment Analysis")

    # ⚙️ Dynamic Cutoff Configuration UI Panel
    st.markdown("### ⚙️ Adjust Enrichment Thresholds")
    ui_go_col1, ui_go_col2 = st.columns(2)
    
    # Identify whether we are using adjusted p-value or raw p-value for the label
    target_p_col = "p-adj" if fdr_strategy_opt in ["BH", "Bonferroni"] else "p-value"
    p_label = "Adjusted P-value (padj) Cutoff" if target_p_col == "padj" else "Raw P-value (p-value) Cutoff"

    with ui_go_col1:
        p_cutoff = st.number_input(
            f"🔬 {p_label}", 
            min_value=0.0001, 
            max_value=1.0, 
            value=0.05, 
            step=0.01,
            format="%.4f",
            help="Proteins with values below this threshold will be selected for the foreground group."
        )
        
    with ui_go_col2:
        fc_cutoff = st.number_input(
            "📈 Absolute Difference Cutoff (|log2FC|)", 
            min_value=0.0, 
            max_value=10.0, 
            value=1.0, 
            step=0.1,
            format="%.2f",
            help="Proteins with absolute log2 fold change greater than or equal to this threshold will be selected."
        )

    # Trigger analysis using user-defined variable parameters
    if st.button("🚀 Run GO Enrichment Analysis", key="run_go_analysis"):

        with st.spinner("Processing GO enrichment pipeline (API querying & stats calculation)..."):
            status, output = calculate_go_enrichment(
                final_statistics_report, 
                id_col=id_col, 
                target_p_col=target_p_col, 
                p_cutoff=p_cutoff,     # Overwritten with UI variable values
                fc_cutoff=fc_cutoff     # Overwritten with UI variable values
            )

        if status == "empty_data":
            st.error("No valid statistical data found for GO enrichment.")
            
        elif status == "insufficient_proteins":
            st.warning(
                f"⚠️ Not enough significant proteins found to run enrichment analysis. "
                f"(Criteria: {target_p_col} < {p_cutoff:.4f}, |log2FC| ≥ {fc_cutoff:.2f}). "
                f"Found significant proteins: {output}"
            )
            st.info("💡 Try weakening the thresholds (e.g., increase p-value or decrease log2FC) to capture more proteins.")
            
        elif status == "success":
            st.info(f"🧬 Total Background Proteins: {output['bg_count']} | Significant Foreground Proteins: {output['fg_count']}")
            
            tabs = st.tabs(["🧬 Biological Process (BP)", "🔬 Cellular Component (CC)", "🧪 Molecular Function (MF)"])
            categories_data = output["categories"]

            for idx, go_type in enumerate(["BP", "CC", "MF"]):
                with tabs[idx]:
                    fig = categories_data[go_type]["fig"]
                    df_go = categories_data[go_type]["df"]

                    if fig is not None and df_go is not None:
                        st.plotly_chart(fig, use_container_width=True)
                        st.subheader(f"📊 {go_type} Results Table")
                        st.dataframe(df_go)
                    else:
                        st.info(f"No enriched terms found for Category: {go_type}")

            st.success("⭕ GO Enrichment Analysis completed successfully!")