import polars as pl
import pandas as pd
import numpy as np
import plotly.express as px
import mygene
from scipy.stats import fisher_exact
from collections import defaultdict

def get_clean_uniprot(name):
    """Cleans FASTA-style UniProt headers to extract the core accession ID."""
    parts = str(name).split("|")
    return parts[1] if len(parts) >= 2 else parts[0]

def extract_go_terms(go_data, go_type):
    """Parses nested dictionary schema from MyGene.info API response."""
    if not isinstance(go_data, dict) or go_type not in go_data:
        return []
    terms = go_data[go_type]
    if isinstance(terms, dict):
        terms = [terms]
    return list({t.get("term") for t in terms if "term" in t})

def run_go_category(res_go, fg_set, bg_set, go_type):
    """Calculates hypergeometric enrichment for a specific GO category (BP, CC, MF)."""
    go2fg = defaultdict(set)
    go2bg = defaultdict(set)

    for _, row in res_go.iterrows():
        uid = str(row["query"])
        for term in row[f"{go_type}_terms"]:
            go2bg[term].add(uid)
            if uid in fg_set:
                go2fg[term].add(uid)

    records = []
    N_fg = len(fg_set)
    N_bg = len(bg_set)

    for term, fg_genes in go2fg.items():
        a = len(fg_genes)
        if a == 0:
            continue
        b = N_fg - a
        c = len(go2bg[term]) - a
        d = N_bg - (a + b + c)

        # Hypergeometric test via Fisher's Exact Test
        _, p = fisher_exact([[a, b], [c, d]], alternative="greater")
        records.append({
            "GO_Term": term,
            "Count": a,
            "GeneRatio": f"{a}/{N_fg}",
            "p_value": p,
        })

    df = pd.DataFrame(records)
    if df.empty:
        return None, None

    df["-log10(p)"] = -np.log10(df["p_value"].replace(0, 1e-10))
    df = df.sort_values("p_value").head(20)

    # Generate dynamic Plotly bar figure
    fig = px.bar(
        df,
        x="-log10(p)",
        y="GO_Term",
        orientation="h",
        title=f"GO Enrichment: {go_type}",
        color="-log10(p)",
        color_continuous_scale="Viridis"
    )
    fig.update_layout(
        yaxis=dict(autorange="reversed"),
        height=500,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig, df

def calculate_go_enrichment(final_report: pl.DataFrame, id_col: str, target_p_col: str, p_cutoff: float = 0.05, fc_cutoff: float = 1.0):
    """
    Main orchestration function for GO enrichment pipeline.
    Filters profiles, queries MyGene.info, and executes Fisher's exact tests.
    """
    # 1. Filter non-null entries via Polars
    analysis_ready = final_report.filter(
        pl.col(target_p_col).is_not_null() & pl.col("log2FC").is_not_null()
    )

    if analysis_ready.is_empty():
        return "empty_data", None

    # 2. Extract clean UniProt accessions using Polars element mapping
    analysis_ready = analysis_ready.with_columns(
        pl.col(id_col).map_elements(get_clean_uniprot, return_dtype=pl.String).alias("UniProt")
    )

    bg_ids = analysis_ready.select("UniProt").drop_nulls().unique().to_series().to_list()
    fg_ids = (
        analysis_ready
        .filter((pl.col(target_p_col) < p_cutoff) & (pl.col("log2FC").abs() >= fc_cutoff))
        .select("UniProt")
        .drop_nulls()
        .unique()
        .to_series()
        .to_list()
    )

    if len(fg_ids) < 3:
        return "insufficient_proteins", len(fg_ids)

    # 3. Fetch data from MyGene.info
    mg = mygene.MyGeneInfo()
    res_list = mg.querymany(bg_ids, scopes="uniprot", fields="go", as_dataframe=False)
    res_go = pd.DataFrame(res_list)
    
    if "notfound" in res_go.columns:
        res_go = res_go[res_go["notfound"] != True]

    # 4. Map GO annotations
    for go_type in ["BP", "CC", "MF"]:
        res_go[f"{go_type}_terms"] = res_go["go"].apply(lambda x: extract_go_terms(x, go_type))

    annotated_ids = set(res_go["query"].astype(str))
    fg_set = annotated_ids.intersection(fg_ids)
    bg_set = annotated_ids

    # 5. Run statistical tests across all categories
    results = {}
    for go_type in ["BP", "CC", "MF"]:
        fig, df_go = run_go_category(res_go, fg_set, bg_set, go_type)
        results[go_type] = {"fig": fig, "df": df_go}

    return "success", {
        "bg_count": len(bg_ids),
        "fg_count": len(fg_ids),
        "categories": results
    }