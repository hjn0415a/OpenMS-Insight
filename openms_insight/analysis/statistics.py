import polars as pl
import numpy as np
import scipy.stats as stats

def calculate_statistical_tests(
    quantification_data: pl.LazyFrame,
    metadata: pl.DataFrame,
    method: str = "limma_like"
) -> pl.LazyFrame:
    """
    🔬 Pure Polars Stream Engine for Mass Spectrometry Statistics.
    - Maintains 100% Non-blocking Lazy Graphs with explicit return_dtypes.
    """
    sample_cols = metadata.select("sample_id").to_series().to_list()
    unique_groups = sorted(metadata.select("group").unique().to_series().to_list())
    group_count = len(unique_groups)
    total_samples = len(sample_cols)

    # Row-wise Stats Generation
    group_stats_exprs = []
    for g in unique_groups:
        g_samples = metadata.filter(pl.col("group") == g).select("sample_id").to_series().to_list()
        n_g = len(g_samples)
        
        group_stats_exprs.extend([
            pl.mean_horizontal(g_samples).alias(f"_mean_{g}"),
            pl.lit(n_g).alias(f"_n_{g}"),
            (pl.concat_list(g_samples).list.var().fill_null(0.0) * (n_g - 1)).alias(f"_ss_{g}")
        ])

    lazy_base = quantification_data.with_columns(group_stats_exprs)

    # Advanced Mathematical Method Routing
    if method == "limma_like":
        df_residual = total_samples - group_count
        ss_total_expr = pl.sum_horizontal([f"_ss_{g}" for g in unique_groups])
        
        lazy_limma = lazy_base.with_columns([
            (ss_total_expr / df_residual).alias("_sigma_sq")
        ]).with_columns([
            pl.col("_sigma_sq").mean().over(pl.lit(1)).alias("_s0_sq")
        ])
        
        d0 = 4.0
        lazy_eb = lazy_limma.with_columns([
            ((d0 * pl.col("_s0_sq") + df_residual * pl.col("_sigma_sq")) / (d0 + df_residual)).alias("_moderated_var"),
            pl.lit(d0 + df_residual).alias("_updated_df")
        ])

        if group_count == 2:
            g1, g2 = unique_groups[0], unique_groups[1]
            
            def compute_ebayes_t_pvalue(s: pl.Series) -> pl.Series:
                struct_df = s.struct.unnest()
                t_stats = struct_df["stat"].to_numpy()
                dfs = struct_df["_updated_df"].to_numpy()
                p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=dfs))

                return pl.Series(
                    "p-value",
                    p_vals,
                    dtype=pl.Float64
                )

            return (
                lazy_eb.with_columns([
                    (pl.col(f"_mean_{g2}") - pl.col(f"_mean_{g1}")).alias("log2FC"),
                    ((pl.col(f"_mean_{g2}") - pl.col(f"_mean_{g1}")) / 
                     (pl.col("_moderated_var") * (1.0/pl.col(f"_n_{g1}") + 1.0/pl.col(f"_n_{g2}"))).sqrt()).alias("stat")
                ])
                .with_columns([
                    pl.struct(["stat", "_updated_df"]).map_batches(compute_ebayes_t_pvalue, return_dtype=pl.Float64).alias("p-value")
                ])
                .drop(["_sigma_sq", "_s0_sq", "_moderated_var", "_updated_df"])
            )
        else:
            grand_mean_expr = pl.sum_horizontal([pl.col(f"_mean_{g}") * pl.col(f"_n_{g}") for g in unique_groups]) / total_samples
            
            def compute_ebayes_f_pvalue(s: pl.Series) -> pl.Series:
                struct_df = s.struct.unnest()
                f_stats = struct_df["stat"].to_numpy()
                df2 = struct_df["_updated_df"].to_numpy()
                df1 = group_count - 1
                p_vals = 1 - stats.f.cdf(f_stats, dfn=df1, dfd=df2)
                return pl.Series("p-value", p_vals, dtype=pl.Float64)

            return (
                lazy_eb.with_columns([grand_mean_expr.alias("_grand_mean")])
                .with_columns([
                    pl.sum_horizontal([
                        pl.col(f"_n_{g}") * ((pl.col(f"_mean_{g}") - pl.col("_grand_mean")) ** 2)
                        for g in unique_groups
                    ]).alias("_ss_between")
                ])
                .with_columns([
                    ((pl.col("_ss_between") / (group_count - 1)) / pl.col("_moderated_var")).alias("stat"),
                    (pl.col(f"_mean_{unique_groups[-1]}") - pl.col(f"_mean_{unique_groups[0]}")).abs().alias("log2FC")
                ])
                .with_columns([
                    pl.struct(["stat", "_updated_df"]).map_batches(compute_ebayes_f_pvalue, return_dtype=pl.Float64).alias("p-value")
                ])
                .drop(["_sigma_sq", "_s0_sq", "_moderated_var", "_updated_df", "_grand_mean", "_ss_between"])
            )

    elif method == "welch":
        if group_count != 2: raise ValueError("Welch test requires exactly 2 groups.")
        g1, g2 = unique_groups[0], unique_groups[1]
        g1_samples = metadata.filter(pl.col("group") == g1).select("sample_id").to_series().to_list()
        g2_samples = metadata.filter(pl.col("group") == g2).select("sample_id").to_series().to_list()
        
        def compute_welch_pvalue(s: pl.Series) -> pl.Series:
            struct_df = s.struct.unnest()
            t_stats = struct_df["stat"].to_numpy()
            v1, v2 = struct_df["_v1"].to_numpy(), struct_df["_v2"].to_numpy()
            n1, n2 = len(g1_samples), len(g2_samples)
            df_welch = ((v1 + v2) ** 2) / ((v1 ** 2) / (n1 - 1) + (v2 ** 2) / (n2 - 1) + 1e-9)
            p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=df_welch))
            return pl.Series("p-value", p_vals, dtype=pl.Float64)

        return (
            lazy_base.with_columns([
                (pl.col(f"_mean_{g2}") - pl.col(f"_mean_{g1}")).alias("log2FC"),
                (pl.concat_list(g1_samples).list.var().fill_null(1e-6) / len(g1_samples)).alias("_v1"),
                (pl.concat_list(g2_samples).list.var().fill_null(1e-6) / len(g2_samples)).alias("_v2")
            ])
            .with_columns([
                ((pl.col(f"_mean_{g2}") - pl.col(f"_mean_{g1}")) / (pl.col("_v1") + pl.col("_v2")).sqrt()).alias("stat")
            ])
            .with_columns([
                pl.struct(["stat", "_v1", "_v2"]).map_batches(compute_welch_pvalue, return_dtype=pl.Float64).alias("p-value")
            ])
            .drop(["_v1", "_v2"])
        )

    # Implementation Layer: Paired t-test (Dependent Samples) Execution Block
    elif method == "paired":
        if group_count != 2: raise ValueError("Paired t-test requires exactly 2 groups.")
        g1, g2 = unique_groups[0], unique_groups[1]
        g1_samples = metadata.filter(pl.col("group") == g1).select("sample_id").to_series().to_list()
        g2_samples = metadata.filter(pl.col("group") == g2).select("sample_id").to_series().to_list()
        
        if len(g1_samples) != len(g2_samples):
            raise ValueError("Paired t-test requires equal sample sizes in both groups.")
        
        n_pairs = len(g1_samples)
        diff_exprs = [pl.col(g2_s) - pl.col(g1_s) for g1_s, g2_s in zip(g1_samples, g2_samples)]

        # FIXED: Changed input from pl.DataFrame to pl.Series and applied .struct.unnest() to resolve the paired crash
        def compute_paired_pvalue(s: pl.Series) -> pl.Series:
            struct_df = s.struct.unnest()
            t_stats = struct_df["stat"].to_numpy()
            df_paired = n_pairs - 1
            p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=df_paired))
            return pl.Series("p-value", p_vals, dtype=pl.Float64)

        return (
            lazy_base.with_columns([
                pl.mean_horizontal(diff_exprs).alias("log2FC"),
                (pl.concat_list(diff_exprs).list.var().fill_null(1e-6).sqrt()).alias("_diff_sd")
            ])
            .with_columns([
                (pl.col("log2FC") / (pl.col("_diff_sd") / np.sqrt(n_pairs))).alias("stat")
            ])
            .with_columns([
                # FIXED: Required structural variables are mapped into pl.struct block
                pl.struct(["stat"]).map_batches(compute_paired_pvalue, return_dtype=pl.Float64).alias("p-value")
            ])
            .drop(["_diff_sd"])
        )

    elif method == "anova":
        if group_count < 3: raise ValueError("ANOVA requires 3+ groups.")
        grand_mean_expr = pl.sum_horizontal([pl.col(f"_mean_{g}") * pl.col(f"_n_{g}") for g in unique_groups]) / total_samples
        ss_within_expr = pl.sum_horizontal([f"_ss_{g}" for g in unique_groups])
        
        # FIXED: Changed input from pl.DataFrame to pl.Series and applied .struct.unnest() to prevent future potential crashes
        def compute_anova_pvalue(s: pl.Series) -> pl.Series:
            struct_df = s.struct.unnest()
            f_stats = struct_df["stat"].to_numpy()
            df1 = group_count - 1
            df2 = total_samples - group_count
            p_vals = 1 - stats.f.cdf(f_stats, dfn=df1, dfd=df2)
            return pl.Series("p-value", p_vals, dtype=pl.Float64)

        return (
            lazy_base.with_columns([
                grand_mean_expr.alias("_grand_mean"),
                ss_within_expr.alias("_ss_within")
            ])
            .with_columns([
                pl.sum_horizontal([
                    pl.col(f"_n_{g}") * ((pl.col(f"_mean_{g}") - pl.col("_grand_mean")) ** 2)
                    for g in unique_groups
                ]).alias("_ss_between")
            ])
            .with_columns([
                ((pl.col("_ss_between") / (group_count - 1)) / (pl.col("_ss_within") / (total_samples - group_count))).alias("stat"),
                (pl.col(f"_mean_{unique_groups[-1]}") - pl.col(f"_mean_{unique_groups[0]}")).abs().alias("log2FC")
            ])
            .with_columns([
                # FIXED: Required structural variables are mapped into pl.struct block
                pl.struct(["stat"]).map_batches(compute_anova_pvalue, return_dtype=pl.Float64).alias("p-value")
            ])
            .drop(["_grand_mean", "_ss_within", "_ss_between"])
        )
    else:
        raise ValueError(f"Unknown method strategy: {method}")


def adjust_fdr_lazy(quantification_data: pl.LazyFrame, strategy: str = "BH") -> pl.LazyFrame:
    """Mathematically Sound FDR Alignment Matrix inside Polars Graph Trees."""
    if strategy == "None":
        return quantification_data.with_columns(pl.col("p-value").alias("p-adj"))

    if strategy == "Bonferroni":
        return quantification_data.with_columns(
            (pl.col("p-value") * pl.col("p-value").count()).clip(0.0, 1.0).alias("p-adj")
        )

    elif strategy == "BH":
        return (
            quantification_data
            .with_row_index("_original_order")
            .sort("p-value")
            .with_columns([
                (pl.col("p-value") * pl.col("p-value").count() / (pl.int_range(1, pl.col("p-value").count() + 1))).alias("_raw_bh")
            ])
            .with_columns([
                pl.col("_raw_bh").cum_min(reverse=True).clip(0.0, 1.0).alias("p-adj")
            ])
            .sort("_original_order")
            .drop(["_original_order", "_raw_bh"])
        )
    else:
        raise ValueError(f"Unknown FDR strategy: {strategy}")