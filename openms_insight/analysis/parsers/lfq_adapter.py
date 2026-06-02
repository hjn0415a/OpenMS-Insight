import streamlit as st
import pandas as pd
from .base_adapter import BaseAdapter

class LFQAdapter(BaseAdapter):
    def can_parse(self, df: pd.DataFrame) -> bool:
        return "Reference" in df.columns and "Intensity" in df.columns

    def parse(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict] | None:
        df = df.copy()

        df["Sample"] = df["Reference"].str.replace(".mzML", "", regex=False)

        unique_samples = df["Sample"].unique()
        st.write(f"🔍 LFQAdapter: Detected unique samples - {unique_samples}")
        group_map = {}
        for sample in unique_samples:
            if sample.startswith("01"):
                group_map[sample] = "one"
            elif sample.startswith("10"):
                group_map[sample] = "ten"
            else:
                group_map[sample] = "NA"
        st.write(f"🔍 LFQAdapter: Generated group mapping - {group_map}")

        df["Group"] = df["Sample"].map(group_map)
        df = df.dropna(subset=["Group"])
        df = df[~df["Group"].str.lower().isin(["skip", "na"])]

        st.write("df after filtering:\n", df.head(15))

        sample_order = sorted(df["Sample"].drop_duplicates())

        meta_cols = [
            "ProteinName",
            "PeptideSequence",
            "PrecursorCharge",
            "FragmentIon",
            "ProductCharge",
            "IsotopeLabelType",
            "Condition",
            "BioReplicate",
            "Run",
        ]

        meta_df = (
            df[meta_cols]
            .drop_duplicates(subset=["ProteinName"])
        )

        intensity_df = (
            df.pivot_table(
                index="ProteinName",
                columns="Sample",
                values="Intensity",
                aggfunc="first"
            )
            .reindex(columns=sample_order)
            .reset_index()
        )

        result_df = meta_df.merge(
            intensity_df,
            on="ProteinName",
            how="left"
        )

        st.write(result_df.head())

        return result_df, group_map


        # id_cols = [
        #     col
        #     for col in df.columns
        #     if col not in ["Reference", "Intensity", "Sample", "Group"]
        # ]

        # st.write("id_cols:", id_cols)
        # start_column_offset = len(id_cols)
        # st.write("start_column_offset:", start_column_offset)

        # df_pivot = df.pivot_table(
        #     index=id_cols, columns="Sample", values="Intensity", aggfunc="median"
        # ).reset_index()

        # st.write("df after pivoting:\n", df_pivot.head())

        # sample_cols = df_pivot.columns[start_column_offset:].tolist()
        # st.write("sample_cols:", sample_cols)

        # new_row = [""] * len(df_pivot.columns)
        # new_row[0] = "Group"

        # for col_name in sample_cols:
        #     col_pos = df_pivot.columns.get_loc(col_name)
        #     new_row[col_pos] = group_map.get(col_name, "NA")

        # group_df = pd.DataFrame([new_row], columns=df_pivot.columns)
        # df_with_groups = pd.concat([group_df, df_pivot], ignore_index=True)

        # return df_with_groups, group_map