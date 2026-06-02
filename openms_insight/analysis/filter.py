import numpy as np
import pandas as pd

class ExpressionDataFilter:

    def __init__(self, df_with_groups: pd.DataFrame):
        """Initializes the filter with the adapted dataframe (df_with_groups).

        Splits the metadata row (Group) from the actual protein measurements.
        """
        self.group_row = df_with_groups.iloc[[0]].copy()
        self.data_df = df_with_groups.iloc[1:].copy()

        # Find where the numeric sample columns start
        # The first column is usually 'Protein ID', and columns with empty string in group row are ID columns.
        group_list = self.group_row.iloc[0].tolist()
        self.start_column_offset = (
            sum(1 for val in group_list if val == "") + 1
        )
        self.sample_cols = df_with_groups.columns[
            self.start_column_offset :
        ].tolist()

    def _get_numeric_matrix(self) -> pd.DataFrame:
        """Helper method to get only the numeric expression values."""
        return self.data_df[self.sample_cols].apply(
            pd.to_numeric, errors="coerce"
        )

    def filter_low_abundance(self, threshold_percentile: float = 10.0):
        """1. Low-Abundance Filtering Removes proteins whose median expression

        across all samples falls below a specific percentile threshold.
        """
        numeric_matrix = self._get_numeric_matrix()
        medians = numeric_matrix.median(axis=1)

        # Calculate cutoff value based on the specified percentile
        cutoff = np.nanpercentile(medians.dropna(), threshold_percentile)

        # Keep rows above the cutoff or rows that are completely NaN
        mask = (medians >= cutoff) | (medians.isna())
        self.data_df = self.data_df[mask]
        return self

    def filter_low_repeatability(self, max_missing_ratio: float = 0.5):
        """2. Low-Repeatability Filtering Removes proteins that have too many

        missing values (NaN or zero) within each group.
        """
        numeric_matrix = self._get_numeric_matrix()
        groups = self.group_row[self.sample_cols].iloc[0].values

        unique_groups = set(groups) - {"", "NA"}
        keep_mask = pd.Series(True, index=self.data_df.index)

        # Check missing value ratio for each biological group
        for group in unique_groups:
            group_cols = [
                col for col in self.sample_cols if self.group_row[col].iloc[0] == group
            ]
            group_data = numeric_matrix[group_cols]

            # Consider both NaN and 0 as missing values
            missing_count = (group_data.isna()) | (group_data == 0)
            missing_ratio = missing_count.sum(axis=1) / len(group_cols)

            # Keep the row only if it satisfies the criteria in all groups
            keep_mask = keep_mask & (missing_ratio <= max_missing_ratio)

        self.data_df = self.data_df[keep_mask]
        return self

    def filter_low_variance(self, threshold_percentile: float = 10.0):
        """3. Low-Variance Filtering Removes proteins with static expression

        profiles across samples using Interquartile Range (IQR).
        """
        numeric_matrix = self._get_numeric_matrix()

        # Calculate Interquartile Range (IQR) for each protein
        q3 = numeric_matrix.quantile(0.75, axis=1)
        q1 = numeric_matrix.quantile(0.25, axis=1)
        iqr = q3 - q1

        # Calculate variance cutoff
        cutoff = np.nanpercentile(iqr.dropna(), threshold_percentile)

        mask = (iqr >= cutoff) | (iqr.isna())
        self.data_df = self.data_df[mask]
        return self

    def get_result(self) -> pd.DataFrame:
        """Combines the Group header row back with the filtered dataset and

        returns it.
        """
        return pd.concat([self.group_row, self.data_df], ignore_index=True)