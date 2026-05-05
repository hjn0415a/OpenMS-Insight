# OpenMS-Insight

[![PyPI version](https://badge.fury.io/py/openms-insight.svg)](https://badge.fury.io/py/openms-insight)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/t0mdavid-m/OpenMS-Insight/actions/workflows/tests.yml/badge.svg)](https://github.com/t0mdavid-m/OpenMS-Insight/actions/workflows/tests.yml)

Interactive visualization components for mass spectrometry data in Streamlit, backed by Vue.js.

## Features

- **Cross-component selection linking** via shared identifiers
- **Memory-efficient preprocessing** via subprocess isolation
- **Automatic disk caching** with config-based invalidation
- **Cache reconstruction** - components can be restored from cache without re-specifying configuration
- **Table component** (Tabulator.js) with server-side pagination, filtering, sorting, go-to, CSV export
- **Line plot component** (Plotly.js) with highlighting, annotations, zoom
- **Mirror plot component** for paired-spectrum comparison with independent per-side filtering and shared click selection
- **Heatmap component** (Plotly scattergl) with multi-resolution downsampling for millions of points
- **Volcano plot component** for differential expression visualization with significance thresholds
- **Sequence view component** for peptide visualization with fragment ion matching and auto-zoom

## Installation

```bash
pip install openms-insight
```

## Quick Start

```python
import streamlit as st
from openms_insight import Table, LinePlot, Heatmap, VolcanoPlot, StateManager

# Create state manager for cross-component linking
state_manager = StateManager()

# Create a table - clicking a row sets the 'item' selection
table = Table(
    cache_id="items_table",
    data_path="items.parquet",
    interactivity={'item': 'item_id'},
    column_definitions=[
        {'field': 'item_id', 'title': 'ID', 'sorter': 'number'},
        {'field': 'name', 'title': 'Name'},
    ],
)
table(state_manager=state_manager)

# Create a linked plot - filters by the selected 'item'
plot = LinePlot(
    cache_id="values_plot",
    data_path="values.parquet",
    filters={'item': 'item_id'},
    x_column='x',
    y_column='y',
)
plot(state_manager=state_manager)
```

## Cross-Component Linking

Components communicate through **identifiers** using three mechanisms:

- **`filters`**: INPUT - filter this component's data by the selection
- **`filter_defaults`**: INPUT - default value when selection is None
- **`interactivity`**: OUTPUT - set a selection when user clicks

```python
# Master table: no filters, sets 'spectrum' on click
master = Table(
    cache_id="spectra",
    data_path="spectra.parquet",
    interactivity={'spectrum': 'scan_id'},  # Click -> sets spectrum=scan_id
)

# Detail table: filters by 'spectrum', sets 'peak' on click
detail = Table(
    cache_id="peaks",
    data_path="peaks.parquet",
    filters={'spectrum': 'scan_id'},        # Filters where scan_id = selected spectrum
    interactivity={'peak': 'peak_id'},      # Click -> sets peak=peak_id
)

# Plot: filters by 'spectrum', highlights selected 'peak'
plot = LinePlot(
    cache_id="plot",
    data_path="peaks.parquet",
    filters={'spectrum': 'scan_id'},
    interactivity={'peak': 'peak_id'},
    x_column='mass',
    y_column='intensity',
)

# Table with filter defaults - shows unannotated data when no identification selected
annotations = Table(
    cache_id="annotations",
    data_path="annotations.parquet",
    filters={'identification': 'id_idx'},
    filter_defaults={'identification': -1},  # Use -1 when identification is None
)
```

---

## Components

### Table

Interactive table using Tabulator.js with filtering dialogs, sorting, pagination, and CSV export.

```python
Table(
    cache_id="spectra_table",
    data_path="spectra.parquet",
    interactivity={'spectrum': 'scan_id'},
    column_definitions=[
        {'field': 'scan_id', 'title': 'Scan', 'sorter': 'number'},
        {'field': 'rt', 'title': 'RT (min)', 'sorter': 'number', 'hozAlign': 'right',
         'formatter': 'money', 'formatterParams': {'precision': 2, 'symbol': ''}},
        {'field': 'precursor_mz', 'title': 'm/z', 'sorter': 'number'},
    ],
    index_field='scan_id',
    go_to_fields=['scan_id'],
    initial_sort=[{'column': 'scan_id', 'dir': 'asc'}],
    default_row=0,
    pagination=True,
    page_size=100,
)
```

**Key parameters:**
- `column_definitions`: List of Tabulator column configs (field, title, sorter, formatter, etc.)
- `index_field`: Column used as unique row identifier (default: 'id')
- `go_to_fields`: Columns available in "Go to" navigation
- `initial_sort`: Default sort configuration
- `pagination`: Enable server-side pagination (default: True). Only the current page of data is sent to the browser, dramatically reducing memory usage for large datasets.
- `page_size`: Rows per page (default: 100)

**Custom formatters:**
In addition to Tabulator's built-in formatters, these custom formatters are available:
- `scientific`: Exponential notation (e.g., "1.23e-05") - use `formatterParams: {precision: 3}`
- `signed`: Explicit +/- prefix (e.g., "+1.234") - use `formatterParams: {precision: 3, showPositive: true}`
- `badge`: Colored pill/badge for categorical values - use `formatterParams: {colorMap: {"Up": "#FF0000"}, defaultColor: "#888"}`

```python
column_definitions=[
    {'field': 'pvalue', 'title': 'P-value', 'formatter': 'scientific', 'formatterParams': {'precision': 2}},
    {'field': 'log2fc', 'title': 'Log2 FC', 'formatter': 'signed', 'formatterParams': {'precision': 3}},
    {'field': 'regulation', 'title': 'Status', 'formatter': 'badge',
     'formatterParams': {'colorMap': {'Up': '#d62728', 'Down': '#1f77b4', 'NS': '#888888'}}},
]
```

### LinePlot

Stick-style line plot using Plotly.js for mass spectra visualization.

```python
LinePlot(
    cache_id="spectrum_plot",
    data_path="peaks.parquet",
    filters={'spectrum': 'scan_id'},
    interactivity={'peak': 'peak_id'},
    x_column='mass',
    y_column='intensity',
    highlight_column='is_annotated',
    annotation_column='ion_label',
    title="MS/MS Spectrum",
    x_label="m/z",
    y_label="Intensity",
    styling={
        'highlightColor': '#E4572E',
        'selectedColor': '#F3A712',
        'unhighlightedColor': 'lightblue',
    },
)
```

**Key parameters:**
- `x_column`, `y_column`: Column names for x/y values
- `highlight_column`: Boolean/int column indicating which points to highlight
- `annotation_column`: Text column for labels on highlighted points
- `styling`: Color configuration dict

### MirrorPlot

Two stick-style spectra rendered against a shared x-axis with the bottom half flipped, used for comparing paired spectra (experimental vs. theoretical, sample vs. reference, MS1 vs. MS2 fragments). Each half is filtered independently, while clicks on either half feed into one shared selection.

```python
from openms_insight import MirrorPlot

mirror = MirrorPlot(
    cache_id="mirror",
    data_path="peaks.parquet",
    filters_top={'spectrum_a': 'scan_id'},      # top half follows spectrum_a
    filters_bottom={'spectrum_b': 'scan_id'},   # bottom half follows spectrum_b
    interactivity={'selected_peak': 'peak_id'}, # click in either half -> shared
    x_column='mass',
    y_column='intensity',                       # positive for both halves
    highlight_column='is_annotated',
    annotation_column='ion_label',
    title_top="Experimental",
    title_bottom="Reference",
    x_label="m/z",
    y_label="Intensity",
)
mirror(state_manager=state_manager, height=600)
```

**Key parameters:**
- `filters_top` / `filters_bottom`: Per-side filter mappings (independent selections drive each half)
- `filter_defaults_top` / `filter_defaults_bottom`: Per-side default values when the corresponding selection is `None`
- `interactivity`: Shared across both halves — a click in either half writes the same identifier
- `x_column`, `y_column`: Shared schema. Provide y values as positive numbers; the bottom half is flipped at render time
- `highlight_column`, `annotation_column`: Shared schema for highlights and label text
- `title_top`, `title_bottom`: In-figure labels for each half (rendered inside the plot, not above it)
- `styling`: Color dict with `highlightColor`, `selectedColor`, `unhighlightedColor` (same defaults as LinePlot)

**Behavior:**
- The y-axis auto-rescales to the maximum visible peak when zooming, and overlapping annotation labels are re-evaluated at the new pixel/data ratio so previously hidden labels reappear when there is room (matches LinePlot's zoom behavior)
- Tick labels show absolute intensity on both sides — the bottom half is flipped only for layout, not for the displayed values
- Marker traces are kept in addition to stick shapes so Plotly fires `plotly_click` events; the click handler picks the side via `curveNumber` and routes the row's interactivity column value to the shared selection
- `set_top_dynamic_annotations(...)` / `set_bottom_dynamic_annotations(...)` allow another component (e.g. a `SequenceView`) to push fragment-ion annotations into one half without invalidating the cache

### Heatmap

2D scatter heatmap using Plotly scattergl with multi-resolution downsampling for large datasets (millions of points).

```python
Heatmap(
    cache_id="peaks_heatmap",
    data_path="all_peaks.parquet",
    x_column='retention_time',
    y_column='mass',
    intensity_column='intensity',
    interactivity={'spectrum': 'scan_id', 'peak': 'peak_id'},
    min_points=30000,
    x_bins=400,
    y_bins=50,
    title="Peak Map",
    x_label="Retention Time (min)",
    y_label="m/z",
    colorscale='Portland',
)
```

**Key parameters:**
- `x_column`, `y_column`, `intensity_column`: Column names for axes and color
- `min_points`: Target size for downsampling (default: 20000)
- `x_bins`, `y_bins`: Grid resolution for spatial binning
- `colorscale`: Plotly colorscale name (default: 'Portland')
- `reversescale`: Invert colorscale direction (default: False)
- `log_scale`: Use log10 color mapping (default: True). Set to False for linear.
- `low_values_on_top`: Prioritize low values during downsampling and display them on top (default: False). Use for scores where lower = better (e.g., e-values, PEP, q-values).
- `intensity_label`: Custom colorbar label (default: 'Intensity')

**Linear scale example:**
```python
Heatmap(
    cache_id="psm_scores",
    data_path="psm_data.parquet",
    x_column='rt',
    y_column='mz',
    intensity_column='score',
    log_scale=False,              # Linear color mapping
    intensity_label='Score',      # Custom colorbar label
    colorscale='Blues',
)
```

**Low values on top (PSM scores):**
For identification results where lower scores indicate better matches (e.g., e-values, PEP, q-values), use `low_values_on_top=True` to preserve low-scoring points during downsampling and display them on top of high-scoring points:

```python
Heatmap(
    cache_id="psm_evalue",
    data_path="psm_data.parquet",
    x_column='rt',
    y_column='mz',
    intensity_column='e_value',
    log_scale=True,               # Log scale for e-values
    low_values_on_top=True,       # Keep/show low e-values (best hits)
    reversescale=True,            # Bright color = low value = best
    intensity_label='E-value',
    colorscale='Portland',
)
```

**Categorical mode:**
Use `category_column` for discrete coloring by category instead of continuous intensity colorscale:

```python
Heatmap(
    cache_id="samples_heatmap",
    data_path="samples.parquet",
    x_column='retention_time',
    y_column='mass',
    intensity_column='intensity',
    category_column='sample_group',  # Color by category instead of intensity
    category_colors={                 # Optional custom colors
        'Control': '#1f77b4',
        'Treatment_A': '#ff7f0e',
        'Treatment_B': '#2ca02c',
    },
)
```

### VolcanoPlot

Interactive volcano plot for differential expression analysis with significance thresholds.

```python
from openms_insight import VolcanoPlot

VolcanoPlot(
    cache_id="de_volcano",
    data_path="differential_expression.parquet",
    log2fc_column='log2FC',
    pvalue_column='pvalue',
    label_column='protein_name',       # Optional: labels for significant points
    filters={'comparison': 'comparison_id'},
    interactivity={'protein': 'protein_id'},
    title="Differential Expression",
    x_label="Log2 Fold Change",
    y_label="-log10(p-value)",
    up_color='#d62728',               # Color for up-regulated
    down_color='#1f77b4',             # Color for down-regulated
    ns_color='#888888',               # Color for not significant
)(
    state_manager=state_manager,
    fc_threshold=1.0,                  # Fold change threshold (render-time)
    p_threshold=0.05,                  # P-value threshold (render-time)
    max_labels=20,                     # Max labels to show
)
```

**Key parameters:**
- `log2fc_column`: Column with log2 fold change values
- `pvalue_column`: Column with p-values (automatically converted to -log10)
- `label_column`: Optional column for point labels
- `up_color`, `down_color`, `ns_color`: Colors for significance categories
- `fc_threshold`, `p_threshold`: Significance thresholds (passed at render time, not cached)
- `max_labels`: Maximum number of labels to display on significant points

**Render-time thresholds:** The `fc_threshold` and `p_threshold` are passed via `__call__()`, not `__init__()`. This allows instant threshold adjustment without cache invalidation.

### SequenceView

Peptide sequence visualization with fragment ion matching. Supports both dynamic (filtered by selection) and static sequences.

```python
# Dynamic: sequence from DataFrame filtered by selection
SequenceView(
    cache_id="peptide_view",
    sequence_data_path="sequences.parquet",  # columns: scan_id, sequence, precursor_charge
    peaks_data_path="peaks.parquet",         # columns: scan_id, peak_id, mass, intensity
    filters={'spectrum': 'scan_id'},
    interactivity={'peak': 'peak_id'},
    deconvolved=False,  # peaks are m/z values, consider charge states
    title="Fragment Coverage",
)

# Static: single sequence with optional peaks
SequenceView(
    cache_id="static_peptide",
    sequence_data=("PEPTIDEK", 2),  # (sequence, charge) tuple
    peaks_data=peaks_df,            # Optional: LazyFrame with mass, intensity columns
    deconvolved=True,               # peaks are neutral masses
)

# Simplest: just a sequence string
SequenceView(
    cache_id="simple_seq",
    sequence_data="PEPTIDEK",  # charge defaults to 1
)
```

**Key parameters:**
- `sequence_data`: LazyFrame, (sequence, charge) tuple, or sequence string
- `sequence_data_path`: Path to parquet with sequence data
- `peaks_data` / `peaks_data_path`: Optional peak data for fragment matching
- `deconvolved`: If False (default), peaks are m/z and matching considers charge states
- `annotation_config`: Dict with ion_types, tolerance, neutral_losses settings

**Features:**
- Automatic fragment ion matching (a/b/c/x/y/z ions)
- Configurable mass tolerance (ppm or Da)
- Neutral loss support (-H2O, -NH3)
- Auto-zoom for short sequences (≤20 amino acids)
- Fragment coverage statistics
- Click-to-select peaks with cross-component linking

---

## Shared Component Arguments

All components accept these common arguments:

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `cache_id` | `str` | **Required** | Unique identifier for disk cache |
| `data_path` | `str` | `None` | Path to parquet file (preferred for memory efficiency) |
| `data` | `pl.LazyFrame` | `None` | Polars LazyFrame (alternative to data_path) |
| `filters` | `Dict[str, str]` | `None` | Map identifier -> column for filtering |
| `filter_defaults` | `Dict[str, Any]` | `None` | Default values when selection is None |
| `interactivity` | `Dict[str, str]` | `None` | Map identifier -> column for click actions |
| `cache_path` | `str` | `"."` | Base directory for cache storage |
| `regenerate_cache` | `bool` | `False` | Force cache regeneration |
| `height` | `int` | `400` | Component height in pixels (render-time parameter) |

## Memory-Efficient Preprocessing

When working with large datasets (especially heatmaps with millions of points), use `data_path` instead of `data` to enable subprocess preprocessing:

```python
# Subprocess preprocessing (recommended for large datasets)
# Memory is fully released after cache creation
heatmap = Heatmap(
    data_path="large_peaks.parquet",  # triggers subprocess
    cache_id="peaks_heatmap",
    ...
)

# In-process preprocessing (for smaller datasets or debugging)
# Memory may be retained by allocator after preprocessing
heatmap = Heatmap(
    data=pl.scan_parquet("large_peaks.parquet"),  # runs in main process
    cache_id="peaks_heatmap",
    ...
)
```

**Why this matters:** Memory allocators like mimalloc (used by Polars) retain freed memory for performance. For large datasets, this can cause memory usage to stay high even after preprocessing completes. Running preprocessing in a subprocess guarantees all memory is returned to the OS when the subprocess exits.

## Cache Reconstruction

Components can be reconstructed from cache using only `cache_id` and `cache_path`. All configuration is restored from the cached manifest:

```python
# First run: create component with data and config
table = Table(
    cache_id="my_table",
    data_path="data.parquet",
    filters={'spectrum': 'scan_id'},
    column_definitions=[...],
    cache_path="./cache",
)

# Subsequent runs: reconstruct from cache only
table = Table(
    cache_id="my_table",
    cache_path="./cache",
)
# All config (filters, column_definitions, etc.) restored from cache
```

## Rendering

All components are callable. Pass a `StateManager` to enable cross-component linking:

```python
from openms_insight import StateManager

state_manager = StateManager()

table(state_manager=state_manager, height=300)
plot(state_manager=state_manager, height=400)
```

---

## Development

For a comprehensive guide to the internal architecture, conventions, and pitfalls, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Building the Vue Component

```bash
cd js-component
npm install
npm run build
```

### Development Mode (Hot Reload)

```bash
# Terminal 1: Vue dev server
cd js-component
npm run dev

# Terminal 2: Streamlit with dev mode
SVC_DEV_MODE=true SVC_DEV_URL=http://localhost:5173 streamlit run app.py
```

### Debug Mode

Enable hash tracking logs to debug data synchronization issues:

```bash
SVC_DEBUG_HASH=true streamlit run app.py
```

### Running Tests

```bash
# Python tests
pip install -e ".[dev]"
pytest tests/ -v

# TypeScript type checking
cd js-component
npm run type-check
```

### Linting and Formatting

```bash
# Python
ruff check .
ruff format .

# JavaScript/TypeScript
cd js-component
npm run lint
npm run format
```
