import polars as pl

def filter_low_abundance(
    quantification_data: pl.LazyFrame,
    metadata: pl.DataFrame,
    group_column: str = "group",
    threshold_percentile: float = 10.0
) -> pl.LazyFrame:
    """Filter low-abundance rows based on per-group median. 
    Keeps rows where AT LEAST ONE biological group's median is above the threshold percentile cutoff.
    """
    # 1. Extract unique group names from metadata
    unique_groups = metadata.select(group_column).to_series().unique().drop_nulls().to_list()
    unique_groups = [g for g in unique_groups if g not in ["", "NA"]]
    
    if not unique_groups:
        return quantification_data

    group_median_cols = []
    
    # 2. Compute horizontal median for each group dynamically using subsetted sample columns
    for group in unique_groups:
        group_samples = metadata.filter(pl.col(group_column) == group).select("sample_id").to_series().to_list()
        if not group_samples:
            continue
        
        median_col_name = f"_median_{group}"
        group_median_cols.append(median_col_name)
        
        quantification_data = quantification_data.with_columns([
            pl.concat_list(group_samples).list.median().alias(median_col_name)
        ])

    # 3. Define cutoff expressions using lazy quantiles to preserve pipeline optimization
    filter_conditions = [
        pl.col(g_med) >= pl.col(g_med).quantile(threshold_percentile / 100.0)
        for g_med in group_median_cols
    ]
    
    # 4. Retain rows that meet the criteria in at least one group (OR logic execution)
    return (
        quantification_data
        .filter(pl.any_horizontal(filter_conditions))
        .drop(group_median_cols)
    )


def filter_low_repeatability(
    quantification_data: pl.LazyFrame,
    metadata: pl.DataFrame,
    group_column: str = "group",
    max_missing_ratio: float = 0.5
) -> pl.LazyFrame:
    """Filter rows based on missing-value ratio per group.
    Keeps rows where AT LEAST ONE biological group satisfies the repeatability threshold.
    """
    # 1. Extract unique group names from metadata
    unique_groups = metadata.select(group_column).to_series().unique().drop_nulls().to_list()
    unique_groups = [g for g in unique_groups if g not in ["", "NA"]]
    
    if not unique_groups:
        return quantification_data

    group_status_cols = []
    
    # 2. Iterate through groups to evaluate missing value profiles
    for group in unique_groups:
        group_samples = metadata.filter(pl.col(group_column) == group).select("sample_id").to_series().to_list()
        if not group_samples:
            continue
            
        status_col_name = f"_keep_{group}"
        group_status_cols.append(status_col_name)
        
        # Count missing values, treating both 0 and explicitly defined Nulls as missing data
        null_count_expr = pl.sum_horizontal([
            pl.col(col).is_null() | (pl.col(col) == 0) for col in group_samples
        ])
        
        # Assign a boolean flag based on whether the ratio is within the allowed threshold
        quantification_data = quantification_data.with_columns([
            (null_count_expr / len(group_samples) <= max_missing_ratio).alias(status_col_name)
        ])

    # 3. Keep rows that satisfy repeatability requirements in at least one group
    return (
        quantification_data
        .filter(pl.any_horizontal(group_status_cols))
        .drop(group_status_cols)
    )


def filter_low_variance(
    quantification_data: pl.LazyFrame,
    metadata: pl.DataFrame,
    group_column: str = "group",
    threshold_percentile: float = 10.0
) -> pl.LazyFrame:
    """Filter rows based on per-group variance to avoid discarding group-specific variable features."""
    # 1. Extract unique group names from metadata
    unique_groups = metadata.select(group_column).to_series().unique().drop_nulls().to_list()
    unique_groups = [g for g in unique_groups if g not in ["", "NA"]]
    
    if not unique_groups:
        return quantification_data

    group_var_cols = []
    
    # 2. Compute horizontal variance for each biological group dynamically
    for group in unique_groups:
        group_samples = metadata.filter(pl.col(group_column) == group).select("sample_id").to_series().to_list()
        if not group_samples:
            continue
            
        var_col_name = f"_var_{group}"
        group_var_cols.append(var_col_name)
        
        quantification_data = quantification_data.with_columns([
            pl.concat_list(group_samples).list.var().alias(var_col_name)
        ])

    # 3. Formulate filtering cutoff conditions based on lower-bound variance percentiles
    filter_conditions = [
        pl.col(g_var) >= pl.col(g_var).quantile(threshold_percentile / 100.0)
        for g_var in group_var_cols
    ]

    # 4. Filter the lazy graph and remove temporary structural tracking columns
    return (
        quantification_data
        .filter(pl.any_horizontal(filter_conditions))
        .drop(group_var_cols)
    )