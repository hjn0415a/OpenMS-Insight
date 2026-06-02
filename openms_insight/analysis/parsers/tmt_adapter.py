import re
import pandas as pd
from .base_adapter import BaseAdapter


class TMTAdapter(BaseAdapter):

    def can_parse(self, df: pd.DataFrame) -> bool:
        return "protein" in df.columns and any(
            col.startswith("abundance_sample") for col in df.columns
        )

    def parse(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict] | None:
        start_column_offset = 4

        # 1. Remove columns containing 'ratio'
        df = df.loc[:, ~df.columns.str.contains("ratio", case=False)]

        # 2. Define group_map and drop list for all sample columns based on hardcoded rules
        # Target sample range: abundance_sample1[unknown] ~ abundance_sample11[unknown]
        group_map = {}
        cols_to_drop = []

        # Actual sample columns start from the 5th column (index 4).
        for col in df.columns[start_column_offset:]:
            # Extract number from column name (e.g., abundance_sample5[unknown] -> 5)
            match = re.search(r"abundance_sample(\d+)", col)
            if match:
                sample_num = int(match.group(1))

                if 1 <= sample_num <= 3:
                    # Add samples 1~3 to the drop list
                    cols_to_drop.append(col)
                elif 4 <= sample_num <= 7:
                    # Samples 4~7 are mapped to 'one' 
                    # (Note: keys are mapped as sample_num - 1 for 0-based index correction)
                    group_map[sample_num - 1] = "one"
                elif 8 <= sample_num <= 11:
                    # Samples 8~11 are mapped to 'ten'
                    group_map[sample_num - 1] = "ten"

        # 3. Drop sample columns 1~3
        df_cleaned = df.drop(columns=cols_to_drop)

        # 4. Create Group row and inject at the very top
        new_row = [""] * len(df_cleaned.columns)
        new_row[0] = "Group"

        current_cols = df_cleaned.columns.tolist()
        original_cols = df.columns.tolist()

        for col_name in current_cols[start_column_offset:]:
            # Calculate the relative index offset based on the original data (0, 1, 2...)
            original_idx = original_cols.index(col_name) - start_column_offset
            col_pos = current_cols.index(col_name)
            
            # Match the group name ('one' or 'ten') from the pre-defined group_map
            new_row[col_pos] = group_map.get(original_idx, "NA")

        group_df = pd.DataFrame([new_row], columns=df_cleaned.columns)
        df_with_groups = pd.concat([group_df, df_cleaned], ignore_index=True)

        return df_with_groups, group_map