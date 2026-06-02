import numpy as np
import pandas as pd


class ExpressionDataImputer:

    def __init__(self, df_filtered: pd.DataFrame):
        """Initializes the imputer with the filtered dataframe.

        Splits the metadata row (Group) from the actual protein measurements.
        """
        self.group_row = df_filtered.iloc[[0]].copy()
        self.data_df = df_filtered.iloc[1:].copy()

        # Find where the numeric sample columns start
        group_list = self.group_row.iloc[0].tolist()
        self.start_column_offset = (
            sum(1 for val in group_list if val == "") + 1
        )
        self.sample_cols = df_filtered.columns[
            self.start_column_offset :
        ].tolist()

    def _get_numeric_matrix(self) -> pd.DataFrame:
        """Helper method to get only the numeric expression values, treating

        zeros as NaN.
        """
        matrix = self.data_df[self.sample_cols].apply(
            pd.to_numeric, errors="coerce"
        )
        # In proteomics, 0 often means missing value (Not Detected)
        return matrix.replace(0, np.nan)

    def impute_mar(self, strategy: str = "mean"):
        """1. MAR (Missing At Random) Imputation Imputes missing values based on

        the biological group's characteristics.

        - 'mean': Imputes with the mean of the corresponding group.
        - 'median': Imputes with the median of the corresponding group.
        """
        numeric_matrix = self._get_numeric_matrix()
        groups = self.group_row[self.sample_cols].iloc[0].values
        unique_groups = set(groups) - {"", "NA"}

        # Perform group-wise imputation
        for group in unique_groups:
            group_cols = [
                col for col in self.sample_cols if self.group_row[col].iloc[0] == group
            ]
            group_data = numeric_matrix[group_cols]

            if strategy == "mean":
                group_fill_values = group_data.mean(axis=1)
            elif strategy == "median":
                group_fill_values = group_data.median(axis=1)
            else:
                raise ValueError("Strategy must be either 'mean' or 'median'")

            # Apply the calculated row-wise values to missing entries in this group
            for col in group_cols:
                numeric_matrix[col] = numeric_matrix[col].fillna(
                    group_fill_values
                )

        # Update the main dataframe
        self.data_df[self.sample_cols] = numeric_matrix
        return self

    def impute_smallest_value(self, scope: str = "row"):
        """2. Smallest Value Imputation Imputes missing values using the minimum

        detected value.

        - 'row': Imputes using the minimum value found *within each specific
        row (protein)*.
        - 'global': Imputes using the absolute minimum value found *across the
        entire dataset*.
        """
        numeric_matrix = self._get_numeric_matrix()

        if scope == "row":
            # Find the minimum value for each row (protein)
            row_min = numeric_matrix.min(axis=1)
            # Fallback for rows that are completely NaN: fill with global median or a very small number if needed
            global_min = numeric_matrix.min().min()
            row_min = row_min.fillna(global_min)

            for col in self.sample_cols:
                numeric_matrix[col] = numeric_matrix[col].fillna(row_min)

        elif scope == "global":
            # Find the minimum value across the entire matrix
            global_min = numeric_matrix.min().min()
            numeric_matrix = numeric_matrix.fillna(global_min)

        else:
            raise ValueError("Scope must be either 'row' or 'global'")

        # Update the main dataframe
        self.data_df[self.sample_cols] = numeric_matrix
        return self

    def get_result(self) -> pd.DataFrame:
        """Combines the Group header row back with the imputed dataset and

        returns it.
        """
        return pd.concat([self.group_row, self.data_df], ignore_index=True)