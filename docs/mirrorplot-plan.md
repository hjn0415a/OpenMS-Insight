# MirrorPlot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MirrorPlot` component to `openms-insight` that displays two mass spectra in one figure (top + flipped bottom), driven by two independent selection states with one shared click selection and per-side dynamic annotations.

**Architecture:** A new `BaseComponent` subclass (`openms_insight.MirrorPlot`) plus a new Vue component (`PlotlyMirrorPlot.vue`). Y-axis flip happens in Vue, not Python. Caching, state management, and bridge infrastructure are reused unchanged. Spec: `docs/mirrorplot-design.md`.

**Tech Stack:** Python 3 (Polars LazyFrames, pandas at the wire boundary, pytest), TypeScript/Vue 3 (Plotly.js, Pinia stores), Streamlit component bridge.

---

## File structure

### New files

| Path | Responsibility |
|---|---|
| `openms_insight/components/mirrorplot.py` | `MirrorPlot(BaseComponent)` class, `@register_component("mirrorplot")` |
| `js-component/src/components/plotly/PlotlyMirrorPlot.vue` | Vue component: one Plotly figure, two traces, symmetric Y, per-side annotation overlay |
| `tests/test_mirrorplot_contract.py` | Contract tests: component_args shape, prepare_vue_data shape, cache config roundtrip, state dependencies |
| `tests/test_mirrorplot_validation.py` | Constructor validation tests: missing filters, overlapping identifier names, invalid columns |
| `tests/integration/test_mirrorplot.py` | Render-pipeline tests: independent halves, shared click, cache reuse, dynamic annotations |

### Modified files

| Path | Edit |
|---|---|
| `openms_insight/components/__init__.py` | Re-export `MirrorPlot` |
| `openms_insight/__init__.py` | Re-export `MirrorPlot` |
| `js-component/src/App.vue` | Import `PlotlyMirrorPlot`, register in `components: {…}`, add `case 'PlotlyMirrorPlot'` to `currentComponent` |
| `js-component/src/types/component.ts` | Add `MirrorPlotComponentArgs` interface |

### Untouched

`LinePlot`, `PlotlyLineplot.vue`, `BaseComponent`, `bridge.py`, `StateManager`, `CACHE_VERSION`.

---

## Phase 1 — Python core

### Task 1: Skeleton MirrorPlot class with constructor and validation

**Files:**
- Create: `openms_insight/components/mirrorplot.py`
- Create: `tests/test_mirrorplot_validation.py`

**Reference pattern:** `openms_insight/components/lineplot.py` (constructor at lines 47-141, `_validate_mappings` at lines 193-222).

- [ ] **Step 1: Write the failing validation tests**

Create `tests/test_mirrorplot_validation.py`:

```python
"""Constructor validation tests for MirrorPlot."""

import pytest

from openms_insight import MirrorPlot


class TestMirrorPlotValidation:
    def test_missing_filters_top_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="filters_top"):
            MirrorPlot(
                cache_id="test_missing_top",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_bottom={"spectrum_bottom": "scan_id"},
                x_column="mass",
                y_column="intensity",
            )

    def test_missing_filters_bottom_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="filters_bottom"):
            MirrorPlot(
                cache_id="test_missing_bottom",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_top={"spectrum_top": "scan_id"},
                x_column="mass",
                y_column="intensity",
            )

    def test_overlapping_identifier_names_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="disjoint"):
            MirrorPlot(
                cache_id="test_overlap",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_top={"spectrum": "scan_id"},
                filters_bottom={"spectrum": "scan_id"},
                x_column="mass",
                y_column="intensity",
            )

    def test_invalid_x_column_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="x_column"):
            MirrorPlot(
                cache_id="test_bad_x",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_top={"spectrum_top": "scan_id"},
                filters_bottom={"spectrum_bottom": "scan_id"},
                x_column="not_a_column",
                y_column="intensity",
            )

    def test_invalid_filter_column_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="not.*found"):
            MirrorPlot(
                cache_id="test_bad_filter_col",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_top={"spectrum_top": "missing_col"},
                filters_bottom={"spectrum_bottom": "scan_id"},
                x_column="mass",
                y_column="intensity",
            )

    def test_invalid_interactivity_column_raises(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        with pytest.raises(ValueError, match="not.*found"):
            MirrorPlot(
                cache_id="test_bad_interact_col",
                data=sample_lineplot_data,
                cache_path=str(temp_cache_dir),
                filters_top={"spectrum_top": "scan_id"},
                filters_bottom={"spectrum_bottom": "scan_id"},
                interactivity={"peak": "missing_col"},
                x_column="mass",
                y_column="intensity",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight
pytest tests/test_mirrorplot_validation.py -v
```

Expected: FAIL — `ImportError: cannot import name 'MirrorPlot' from 'openms_insight'`

- [ ] **Step 3: Create the MirrorPlot module with constructor and validation**

Create `openms_insight/components/mirrorplot.py`:

```python
"""Mirror plot component using Plotly.js — two spectra, one figure."""

from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

import polars as pl

from ..core.base import BaseComponent
from ..core.registry import register_component
from ..preprocessing.filtering import filter_and_collect_cached


@register_component("mirrorplot")
class MirrorPlot(BaseComponent):
    """
    Interactive mirror plot displaying two spectra in a single figure.

    Top half is rendered with positive intensities, bottom half is rendered with
    flipped (negative) intensities. The two halves are driven by independent
    selection states (filters_top and filters_bottom) but share a single click
    selection (interactivity). Annotations are independent per side.

    Y-axis flip happens in Vue at render time; the cache stores positive y-values
    for both halves. Y-axis range is symmetric around zero.

    Example:
        mirror = MirrorPlot(
            cache_id="psm_compare",
            data=peaks_df,
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        mirror(key="mirror", state_manager=state_manager)
    """

    _component_type: str = "mirrorplot"

    def __init__(
        self,
        cache_id: str,
        data: Optional[pl.LazyFrame] = None,
        data_path: Optional[str] = None,
        # Per-side selection
        filters_top: Optional[Dict[str, str]] = None,
        filter_defaults_top: Optional[Dict[str, Any]] = None,
        filters_bottom: Optional[Dict[str, str]] = None,
        filter_defaults_bottom: Optional[Dict[str, Any]] = None,
        # Shared click
        interactivity: Optional[Dict[str, str]] = None,
        # Cache
        cache_path: str = ".",
        regenerate_cache: bool = False,
        # Schema (shared)
        x_column: str = "x",
        y_column: str = "y",
        highlight_column: Optional[str] = None,
        annotation_column: Optional[str] = None,
        # Labels
        title: Optional[str] = None,
        title_top: Optional[str] = None,
        title_bottom: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        # Visuals
        styling: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        # Subprocess recreation passes the union dicts back; discard them
        # because we recompute the union from the per-side dicts below.
        kwargs.pop("filters", None)
        kwargs.pop("filter_defaults", None)

        self._filters_top = filters_top or {}
        self._filters_bottom = filters_bottom or {}
        self._filter_defaults_top = filter_defaults_top or {}
        self._filter_defaults_bottom = filter_defaults_bottom or {}

        self._x_column = x_column
        self._y_column = y_column
        self._highlight_column = highlight_column
        self._annotation_column = annotation_column
        self._title = title
        self._title_top = title_top
        self._title_bottom = title_bottom
        self._x_label = x_label or x_column
        self._y_label = y_label or y_column
        self._styling = styling or {}
        self._plot_config = config or {}

        # Dynamic state (never cached)
        self._top_dynamic_annotations: Optional[Dict[Any, Dict[str, Any]]] = None
        self._bottom_dynamic_annotations: Optional[Dict[Any, Dict[str, Any]]] = None
        self._top_dynamic_title: Optional[str] = None
        self._bottom_dynamic_title: Optional[str] = None

        # Union for parent-class invariants
        union_filters = {**self._filters_top, **self._filters_bottom}
        union_filter_defaults = {
            **self._filter_defaults_top,
            **self._filter_defaults_bottom,
        }

        super().__init__(
            cache_id=cache_id,
            data=data,
            data_path=data_path,
            filters=union_filters or None,
            filter_defaults=union_filter_defaults or None,
            interactivity=interactivity,
            cache_path=cache_path,
            regenerate_cache=regenerate_cache,
            # Pass per-side dicts for subprocess recreation
            filters_top=filters_top,
            filters_bottom=filters_bottom,
            filter_defaults_top=filter_defaults_top,
            filter_defaults_bottom=filter_defaults_bottom,
            x_column=x_column,
            y_column=y_column,
            highlight_column=highlight_column,
            annotation_column=annotation_column,
            title=title,
            title_top=title_top,
            title_bottom=title_bottom,
            x_label=x_label,
            y_label=y_label,
            styling=styling,
            config=config,
            **kwargs,
        )

    def _validate_mappings(self) -> None:
        """Validate per-side filters and shared schema columns."""
        if self._raw_data is None:
            return  # Skip validation when reconstructing from cache

        # Creation-mode: both sides required and disjoint
        if not self._filters_top:
            raise ValueError(
                "MirrorPlot requires filters_top (creation mode)"
            )
        if not self._filters_bottom:
            raise ValueError(
                "MirrorPlot requires filters_bottom (creation mode)"
            )

        overlap = set(self._filters_top.keys()) & set(self._filters_bottom.keys())
        if overlap:
            raise ValueError(
                f"filters_top and filters_bottom must use disjoint identifier "
                f"names; got overlap: {sorted(overlap)}"
            )

        # Schema validation
        schema = self._raw_data.collect_schema()
        column_names = schema.names()

        for col_name, col_label in [
            (self._x_column, "x_column"),
            (self._y_column, "y_column"),
        ]:
            if col_name not in column_names:
                raise ValueError(
                    f"{col_label} '{col_name}' not found in data. "
                    f"Available columns: {column_names}"
                )

        if self._highlight_column and self._highlight_column not in column_names:
            raise ValueError(
                f"highlight_column '{self._highlight_column}' not found in data. "
                f"Available columns: {column_names}"
            )
        if self._annotation_column and self._annotation_column not in column_names:
            raise ValueError(
                f"annotation_column '{self._annotation_column}' not found in data. "
                f"Available columns: {column_names}"
            )

        for identifier, column in self._filters_top.items():
            if column not in column_names:
                raise ValueError(
                    f"filters_top column '{column}' for identifier '{identifier}' "
                    f"not found in data. Available columns: {column_names}"
                )
        for identifier, column in self._filters_bottom.items():
            if column not in column_names:
                raise ValueError(
                    f"filters_bottom column '{column}' for identifier '{identifier}' "
                    f"not found in data. Available columns: {column_names}"
                )
        if self._interactivity:
            for identifier, column in self._interactivity.items():
                if column not in column_names:
                    raise ValueError(
                        f"interactivity column '{column}' for identifier "
                        f"'{identifier}' not found in data. "
                        f"Available columns: {column_names}"
                    )

    # The remaining abstract methods are stubs filled in by later tasks.
    def _preprocess(self) -> None:
        raise NotImplementedError("Filled in Task 2")

    def _get_vue_component_name(self) -> str:
        return "PlotlyMirrorPlot"

    def _get_data_key(self) -> str:
        return "plotDataTop"

    def _get_cache_config(self) -> Dict[str, Any]:
        raise NotImplementedError("Filled in Task 3")

    def _restore_cache_config(self, config: Dict[str, Any]) -> None:
        raise NotImplementedError("Filled in Task 3")

    def _prepare_vue_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Filled in Task 4")

    def _get_component_args(self) -> Dict[str, Any]:
        raise NotImplementedError("Filled in Task 5")


if TYPE_CHECKING:
    from ..core.state import StateManager  # noqa: F401
```

Update `openms_insight/components/__init__.py` to re-export — find the existing `__all__` list and add `MirrorPlot`:

```python
# At the top of the file, alongside other component imports:
from .mirrorplot import MirrorPlot

# In __all__:
__all__ = [
    # ... existing entries ...
    "MirrorPlot",
]
```

Update `openms_insight/__init__.py` similarly — add `from .components.mirrorplot import MirrorPlot` and append `"MirrorPlot"` to the existing `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight
pytest tests/test_mirrorplot_validation.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Add the reconstruction-from-cache test (and verify it fails)**

Append to `tests/test_mirrorplot_validation.py`:

```python
    def test_reconstruct_from_cache_only(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        """After full creation, instantiate with just cache_id — succeeds."""
        # First, create with full args to populate cache
        MirrorPlot(
            cache_id="test_reconstruct",
            data=sample_lineplot_data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
            title_top="Top",
            title_bottom="Bottom",
        )
        # Then reconstruct with only cache_id + cache_path
        restored = MirrorPlot(
            cache_id="test_reconstruct",
            cache_path=str(temp_cache_dir),
        )
        assert restored._title_top == "Top"
        assert restored._title_bottom == "Bottom"
        assert restored._filters_top == {"spectrum_top": "scan_id"}
        assert restored._filters_bottom == {"spectrum_bottom": "scan_id"}
```

```bash
pytest tests/test_mirrorplot_validation.py::TestMirrorPlotValidation::test_reconstruct_from_cache_only -v
```

Expected: FAIL — `_preprocess` raises `NotImplementedError`. This test is unblocked by Task 2 and gets re-run there.

- [ ] **Step 6: Commit**

```bash
git add openms_insight/components/mirrorplot.py \
        openms_insight/components/__init__.py \
        openms_insight/__init__.py \
        tests/test_mirrorplot_validation.py
git commit -m "feat(mirrorplot): add MirrorPlot constructor and validation"
```

---

### Task 2: Implement `_preprocess` and reach a working cache cycle

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Modify: `tests/test_mirrorplot_validation.py` (re-run reconstruction test)

**Reference pattern:** `openms_insight/components/lineplot.py:_preprocess` (lines 224-251) and `_get_row_group_size` (lines 177-191).

- [ ] **Step 1: Replace the `_preprocess` stub with implementation**

In `openms_insight/components/mirrorplot.py`, replace the `_preprocess` stub:

```python
    def _preprocess(self) -> None:
        """
        Preprocess shared data for both halves.

        Sorts by the union of top and bottom filter columns to enable
        Polars predicate pushdown when filtering by either selection state.
        Stores the LazyFrame; the base class streams to parquet via sink_parquet.
        """
        data = self._raw_data

        # Union of top + bottom filter columns, deduped, preserving order
        sort_columns = []
        for col in list(self._filters_top.values()) + list(
            self._filters_bottom.values()
        ):
            if col not in sort_columns:
                sort_columns.append(col)

        if sort_columns:
            data = data.sort(sort_columns)

        # Store configuration in preprocessed data for serialization
        self._preprocessed_data["plot_config"] = {
            "x_column": self._x_column,
            "y_column": self._y_column,
            "highlight_column": self._highlight_column,
            "annotation_column": self._annotation_column,
        }

        # Keep lazy — base class streams to parquet
        self._preprocessed_data["data"] = data

    def _get_row_group_size(self) -> int:
        """Smaller row groups for filtered components (better predicate pushdown)."""
        return 10_000
```

- [ ] **Step 2: Add `get_state_dependencies` override**

Append (after `_get_data_key`):

```python
    def get_state_dependencies(self) -> list:
        """Both per-side filter identifiers; interactivity excluded so clicks don't invalidate cache."""
        return list(self._filters_top.keys()) + list(self._filters_bottom.keys())
```

- [ ] **Step 3: Run reconstruction test to verify cache cycle works**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight
pytest tests/test_mirrorplot_validation.py::TestMirrorPlotValidation::test_reconstruct_from_cache_only -v
```

Expected: FAIL — `_get_cache_config` and `_restore_cache_config` are still stubs; the cache write path will hit `NotImplementedError`. Confirms preprocessing is the next blocker. Move to Task 3.

- [ ] **Step 4: Commit (partial — preprocess works, cache config not yet)**

```bash
git add openms_insight/components/mirrorplot.py
git commit -m "feat(mirrorplot): implement _preprocess and get_state_dependencies"
```

---

### Task 3: Implement cache config (`_get_cache_config` / `_restore_cache_config`)

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Create: `tests/test_mirrorplot_contract.py`

**Reference pattern:** `openms_insight/components/lineplot.py:_get_cache_config` (lines 143-160) and `_restore_cache_config` (lines 162-175).

- [ ] **Step 1: Write the failing cache config roundtrip test**

Create `tests/test_mirrorplot_contract.py`:

```python
"""Contract tests for MirrorPlot."""

import pytest

from openms_insight import MirrorPlot


class TestMirrorPlotContract:
    def test_cache_config_roundtrip(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        """_get_cache_config / _restore_cache_config preserves every field."""
        original = MirrorPlot(
            cache_id="test_roundtrip",
            data=sample_lineplot_data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filter_defaults_top={"spectrum_top": 1},
            filters_bottom={"spectrum_bottom": "scan_id"},
            filter_defaults_bottom={"spectrum_bottom": 2},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
            highlight_column="annotation",
            annotation_column="annotation",
            title="Compare",
            title_top="PSM A",
            title_bottom="PSM B",
            x_label="m/z",
            y_label="Intensity",
            styling={"topColor": "#1f77b4", "bottomColor": "#d62728"},
            config={"displayModeBar": True},
        )
        config = original._get_cache_config()

        # Every constructor field that affects rendering must round-trip
        assert config["filters_top"] == {"spectrum_top": "scan_id"}
        assert config["filters_bottom"] == {"spectrum_bottom": "scan_id"}
        assert config["filter_defaults_top"] == {"spectrum_top": 1}
        assert config["filter_defaults_bottom"] == {"spectrum_bottom": 2}
        assert config["interactivity"] == {"selected_peak": "peak_id"}
        assert config["x_column"] == "mass"
        assert config["y_column"] == "intensity"
        assert config["highlight_column"] == "annotation"
        assert config["annotation_column"] == "annotation"
        assert config["title"] == "Compare"
        assert config["title_top"] == "PSM A"
        assert config["title_bottom"] == "PSM B"
        assert config["x_label"] == "m/z"
        assert config["y_label"] == "Intensity"
        assert config["styling"] == {"topColor": "#1f77b4", "bottomColor": "#d62728"}
        assert config["plot_config"] == {"displayModeBar": True}

        # Restore on a fresh instance
        restored = MirrorPlot(
            cache_id="test_roundtrip_target",
            data=sample_lineplot_data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            x_column="mass",
            y_column="intensity",
        )
        restored._restore_cache_config(config)

        assert restored._filters_top == {"spectrum_top": "scan_id"}
        assert restored._filters_bottom == {"spectrum_bottom": "scan_id"}
        assert restored._filter_defaults_top == {"spectrum_top": 1}
        assert restored._filter_defaults_bottom == {"spectrum_bottom": 2}
        assert restored._title_top == "PSM A"
        assert restored._title_bottom == "PSM B"
        assert restored._top_dynamic_annotations is None
        assert restored._bottom_dynamic_annotations is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotContract::test_cache_config_roundtrip -v
```

Expected: FAIL — `_get_cache_config` raises `NotImplementedError`.

- [ ] **Step 3: Implement cache config methods**

In `openms_insight/components/mirrorplot.py`, replace the two stubs:

```python
    def _get_cache_config(self) -> Dict[str, Any]:
        """Configuration that affects cache validity."""
        return {
            "filters_top": self._filters_top,
            "filters_bottom": self._filters_bottom,
            "filter_defaults_top": self._filter_defaults_top,
            "filter_defaults_bottom": self._filter_defaults_bottom,
            "interactivity": self._interactivity,
            "x_column": self._x_column,
            "y_column": self._y_column,
            "highlight_column": self._highlight_column,
            "annotation_column": self._annotation_column,
            "title": self._title,
            "title_top": self._title_top,
            "title_bottom": self._title_bottom,
            "x_label": self._x_label,
            "y_label": self._y_label,
            "styling": self._styling,
            "plot_config": self._plot_config,
        }

    def _restore_cache_config(self, config: Dict[str, Any]) -> None:
        """Restore component-specific configuration from cached config."""
        self._filters_top = config.get("filters_top") or {}
        self._filters_bottom = config.get("filters_bottom") or {}
        self._filter_defaults_top = config.get("filter_defaults_top") or {}
        self._filter_defaults_bottom = config.get("filter_defaults_bottom") or {}
        self._interactivity = config.get("interactivity") or {}
        self._x_column = config.get("x_column", "x")
        self._y_column = config.get("y_column", "y")
        self._highlight_column = config.get("highlight_column")
        self._annotation_column = config.get("annotation_column")
        self._title = config.get("title")
        self._title_top = config.get("title_top")
        self._title_bottom = config.get("title_bottom")
        self._x_label = config.get("x_label", self._x_column)
        self._y_label = config.get("y_label", self._y_column)
        self._styling = config.get("styling") or {}
        self._plot_config = config.get("plot_config") or {}
        # Dynamic state (not cached) — reset to None
        self._top_dynamic_annotations = None
        self._bottom_dynamic_annotations = None
        self._top_dynamic_title = None
        self._bottom_dynamic_title = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotContract::test_cache_config_roundtrip -v
pytest tests/test_mirrorplot_validation.py -v
```

Expected: cache config roundtrip PASS, all 7 validation tests PASS (including reconstruction).

- [ ] **Step 5: Commit**

```bash
git add openms_insight/components/mirrorplot.py tests/test_mirrorplot_contract.py
git commit -m "feat(mirrorplot): implement cache config roundtrip"
```

---

### Task 4: Implement `_prepare_vue_data` (the double-filter algorithm)

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Modify: `tests/test_mirrorplot_contract.py`

**Reference pattern:** `openms_insight/components/lineplot.py:_prepare_vue_data` (lines 261-367), particularly the column projection, `filter_and_collect_cached` call, dynamic annotation lookup loop, and `_build_plot_config`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mirrorplot_contract.py`:

```python
import pandas as pd


class TestMirrorPlotPrepareVueData:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = dict(
            cache_id="test_prepare",
            data=data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_returns_dict_with_hash(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert isinstance(result, dict)
        assert "_hash" in result
        assert isinstance(result["_hash"], str)

    def test_returns_both_dataframes(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert "plotDataTop" in result
        assert "plotDataBottom" in result
        assert isinstance(result["plotDataTop"], pd.DataFrame)
        assert isinstance(result["plotDataBottom"], pd.DataFrame)

    def test_filters_independently(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        """Top selection (scan 1) and bottom selection (scan 2) produce disjoint rows."""
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        df_top = result["plotDataTop"]
        df_bot = result["plotDataBottom"]
        # sample_lineplot_data has scan_id [1,1,1,2,2]: scan 1 has 3 rows, scan 2 has 2
        assert len(df_top) == 3
        assert len(df_bot) == 2
        assert set(df_top["scan_id"]) == {1}
        assert set(df_bot["scan_id"]) == {2}

    def test_keeps_y_positive_on_bottom(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        """Vue does the y-flip; Python emits positive intensities for both halves."""
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert (result["plotDataTop"]["intensity"] >= 0).all()
        assert (result["plotDataBottom"]["intensity"] >= 0).all()

    def test_get_data_key_returns_plotDataTop(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        assert comp._get_data_key() == "plotDataTop"

    def test_state_dependencies_includes_both_sides(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        deps = comp.get_state_dependencies()
        assert "spectrum_top" in deps
        assert "spectrum_bottom" in deps

    def test_state_dependencies_excludes_interactivity(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        assert "selected_peak" not in comp.get_state_dependencies()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotPrepareVueData -v
```

Expected: 5 FAIL with `NotImplementedError` (the data key / state deps tests already pass).

- [ ] **Step 3: Implement `_prepare_vue_data` and helpers**

In `openms_insight/components/mirrorplot.py`, add a hashlib import at the top:

```python
import hashlib
```

Replace the `_prepare_vue_data` stub with:

```python
    def _prepare_vue_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Filter shared data twice — once per side — and apply per-side annotations."""
        # Build column projection (deduped, preserving order)
        projection: list[str] = [self._x_column, self._y_column]
        if self._highlight_column:
            projection.append(self._highlight_column)
        if self._annotation_column:
            projection.append(self._annotation_column)
        if self._interactivity:
            for col in self._interactivity.values():
                if col not in projection:
                    projection.append(col)
        for col in list(self._filters_top.values()) + list(
            self._filters_bottom.values()
        ):
            if col not in projection:
                projection.append(col)

        # Get cached data
        data = self._preprocessed_data.get("data")
        if data is None:
            data = self._raw_data
        if isinstance(data, pl.DataFrame):
            data = data.lazy()

        # Filter twice — once per side
        df_top, hash_top = filter_and_collect_cached(
            data,
            self._filters_top,
            state,
            columns=projection,
            filter_defaults=self._filter_defaults_top,
        )
        df_bottom, hash_bottom = filter_and_collect_cached(
            data,
            self._filters_bottom,
            state,
            columns=projection,
            filter_defaults=self._filter_defaults_bottom,
        )

        # Apply dynamic annotations per side
        top_highlight_col = self._highlight_column
        top_annotation_col = self._annotation_column
        bot_highlight_col = self._highlight_column
        bot_annotation_col = self._annotation_column

        if self._top_dynamic_annotations and len(df_top) > 0:
            df_top = self._apply_annotations_to_df(
                df_top, self._top_dynamic_annotations
            )
            top_highlight_col = "_dynamic_highlight"
            top_annotation_col = "_dynamic_annotation"
        if self._bottom_dynamic_annotations and len(df_bottom) > 0:
            df_bottom = self._apply_annotations_to_df(
                df_bottom, self._bottom_dynamic_annotations
            )
            bot_highlight_col = "_dynamic_highlight"
            bot_annotation_col = "_dynamic_annotation"

        # Build combined hash; include annotation state if any
        data_hash = f"{hash_top}_{hash_bottom}"
        if self._top_dynamic_annotations or self._bottom_dynamic_annotations:
            ann_payload = (
                sorted((self._top_dynamic_annotations or {}).keys()),
                sorted((self._bottom_dynamic_annotations or {}).keys()),
            )
            ann_hash = hashlib.md5(str(ann_payload).encode()).hexdigest()[:8]
            data_hash = f"{data_hash}_{ann_hash}"

        return {
            "plotDataTop": df_top,
            "plotDataBottom": df_bottom,
            "_hash": data_hash,
            "_plotConfig": self._build_plot_config(
                top_highlight_col, top_annotation_col,
                bot_highlight_col, bot_annotation_col,
            ),
        }

    def _apply_annotations_to_df(
        self,
        df_pandas,
        annotations: Dict[Any, Dict[str, Any]],
    ):
        """Apply dynamic annotations to a pandas DataFrame (per-side helper)."""
        df_pandas = df_pandas.copy()
        num_rows = len(df_pandas)
        highlights = [False] * num_rows
        labels = [""] * num_rows

        # Use first interactivity column for peak_id lookup
        id_column = None
        if self._interactivity:
            id_column = list(self._interactivity.values())[0]

        if id_column and id_column in df_pandas.columns:
            for row_idx, peak_id in enumerate(df_pandas[id_column].tolist()):
                if peak_id in annotations:
                    entry = annotations[peak_id]
                    highlights[row_idx] = entry.get("highlight", False)
                    labels[row_idx] = entry.get("annotation", "")
        else:
            # Legacy fallback — index-keyed
            for idx, entry in annotations.items():
                if isinstance(idx, int) and 0 <= idx < num_rows:
                    highlights[idx] = entry.get("highlight", False)
                    labels[idx] = entry.get("annotation", "")

        df_pandas["_dynamic_highlight"] = highlights
        df_pandas["_dynamic_annotation"] = labels
        return df_pandas

    def _build_plot_config(
        self,
        top_highlight_col: Optional[str],
        top_annotation_col: Optional[str],
        bot_highlight_col: Optional[str],
        bot_annotation_col: Optional[str],
    ) -> Dict[str, Any]:
        """Plot config sent alongside data — Vue uses it to map columns per side."""
        return {
            "xColumn": self._x_column,
            "yColumn": self._y_column,
            "topHighlightColumn": top_highlight_col,
            "topAnnotationColumn": top_annotation_col,
            "bottomHighlightColumn": bot_highlight_col,
            "bottomAnnotationColumn": bot_annotation_col,
            "interactivityColumns": {
                col: col
                for col in (self._interactivity.values() if self._interactivity else [])
            },
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mirrorplot_contract.py -v
pytest tests/test_mirrorplot_validation.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add openms_insight/components/mirrorplot.py tests/test_mirrorplot_contract.py
git commit -m "feat(mirrorplot): implement _prepare_vue_data with per-side filtering"
```

---

### Task 5: Implement `_get_component_args`

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Modify: `tests/test_mirrorplot_contract.py`

**Reference pattern:** `openms_insight/components/lineplot.py:_get_component_args` (lines 369-422).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mirrorplot_contract.py`:

```python
class TestMirrorPlotComponentArgs:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = dict(
            cache_id="test_args",
            data=data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_includes_componentType(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        args = comp._get_component_args()
        assert args["componentType"] == "PlotlyMirrorPlot"

    def test_carries_per_side_titles_and_columns(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(
            temp_cache_dir,
            sample_lineplot_data,
            title="Compare",
            title_top="A",
            title_bottom="B",
            x_label="m/z",
            y_label="Intensity",
        )
        args = comp._get_component_args()
        assert args["title"] == "Compare"
        assert args["titleTop"] == "A"
        assert args["titleBottom"] == "B"
        assert args["xLabel"] == "m/z"
        assert args["yLabel"] == "Intensity"
        assert args["xColumn"] == "mass"
        assert args["yColumn"] == "intensity"
        assert args["interactivity"] == {"selected_peak": "peak_id"}

    def test_styling_merged_with_defaults(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(
            temp_cache_dir,
            sample_lineplot_data,
            styling={"topColor": "#1f77b4"},
        )
        args = comp._get_component_args()
        # Override applied
        assert args["styling"]["topColor"] == "#1f77b4"
        # Defaults preserved for unspecified keys
        assert "bottomColor" in args["styling"]
        assert "highlightColor" in args["styling"]
        assert "selectedColor" in args["styling"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotComponentArgs -v
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `_get_component_args`**

Replace the stub:

```python
    def _get_component_args(self) -> Dict[str, Any]:
        default_styling = {
            "topColor": "lightblue",
            "bottomColor": "lightcoral",
            "highlightColor": "#E4572E",
            "selectedColor": "#F3A712",
            "annotationColors": {
                "massButton": "#E4572E",
                "selectedMassButton": "#F3A712",
                "background": "#f0f0f0",
                "buttonHover": "#e0e0e0",
            },
        }

        styling = {**default_styling, **self._styling}
        if "annotationColors" in self._styling:
            styling["annotationColors"] = {
                **default_styling["annotationColors"],
                **self._styling["annotationColors"],
            }

        # Use dynamic titles if set
        title_top = (
            self._top_dynamic_title
            if self._top_dynamic_title is not None
            else (self._title_top or "")
        )
        title_bottom = (
            self._bottom_dynamic_title
            if self._bottom_dynamic_title is not None
            else (self._title_bottom or "")
        )

        args: Dict[str, Any] = {
            "componentType": self._get_vue_component_name(),
            "title": self._title or "",
            "titleTop": title_top,
            "titleBottom": title_bottom,
            "xLabel": self._x_label,
            "yLabel": self._y_label,
            "xColumn": self._x_column,
            "yColumn": self._y_column,
            "highlightColumn": self._highlight_column,
            "annotationColumn": self._annotation_column,
            "interactivity": self._interactivity,
            "styling": styling,
            "config": self._plot_config,
        }
        args.update(self._config)
        return args
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mirrorplot_contract.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add openms_insight/components/mirrorplot.py tests/test_mirrorplot_contract.py
git commit -m "feat(mirrorplot): implement _get_component_args"
```

---

### Task 6: Dynamic annotation methods (set/clear top/bottom)

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Modify: `tests/test_mirrorplot_contract.py`

**Reference pattern:** `openms_insight/components/lineplot.py:set_dynamic_annotations` (lines 480-526).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mirrorplot_contract.py`:

```python
class TestMirrorPlotDynamicAnnotations:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = dict(
            cache_id="test_dyn",
            data=data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_set_top_only_affects_top(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_top_dynamic_annotations(
            {10: {"highlight": True, "annotation": "b1"}},
            title="Top!",
        )
        assert comp._top_dynamic_annotations == {
            10: {"highlight": True, "annotation": "b1"}
        }
        assert comp._top_dynamic_title == "Top!"
        assert comp._bottom_dynamic_annotations is None
        assert comp._bottom_dynamic_title is None

    def test_set_bottom_only_affects_bottom(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_bottom_dynamic_annotations(
            {40: {"highlight": True, "annotation": "y3"}}, title="Bot"
        )
        assert comp._bottom_dynamic_annotations == {
            40: {"highlight": True, "annotation": "y3"}
        }
        assert comp._bottom_dynamic_title == "Bot"
        assert comp._top_dynamic_annotations is None

    def test_clear_top_only(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        comp.set_bottom_dynamic_annotations({40: {"highlight": True, "annotation": "y3"}})
        comp.clear_dynamic_annotations(side="top")
        assert comp._top_dynamic_annotations is None
        assert comp._top_dynamic_title is None
        # Bottom untouched
        assert comp._bottom_dynamic_annotations == {
            40: {"highlight": True, "annotation": "y3"}
        }

    def test_clear_both(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        comp.set_bottom_dynamic_annotations({40: {"highlight": True, "annotation": "y3"}})
        comp.clear_dynamic_annotations()  # side=None default
        assert comp._top_dynamic_annotations is None
        assert comp._bottom_dynamic_annotations is None
        assert comp._top_dynamic_title is None
        assert comp._bottom_dynamic_title is None

    def test_setters_return_self_for_chaining(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        assert comp.set_top_dynamic_annotations({}) is comp
        assert comp.set_bottom_dynamic_annotations({}) is comp
        assert comp.clear_dynamic_annotations() is comp
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotDynamicAnnotations -v
```

Expected: FAIL — `AttributeError: 'MirrorPlot' object has no attribute 'set_top_dynamic_annotations'`.

- [ ] **Step 3: Implement the dynamic annotation methods**

Append to `openms_insight/components/mirrorplot.py` (anywhere after `_get_component_args`):

```python
    def set_top_dynamic_annotations(
        self,
        annotations: Optional[Dict[Any, Dict[str, Any]]],
        title: Optional[str] = None,
    ) -> "MirrorPlot":
        """Apply per-render annotations to the top spectrum only."""
        self._top_dynamic_annotations = annotations
        self._top_dynamic_title = title
        return self

    def set_bottom_dynamic_annotations(
        self,
        annotations: Optional[Dict[Any, Dict[str, Any]]],
        title: Optional[str] = None,
    ) -> "MirrorPlot":
        """Apply per-render annotations to the bottom spectrum only."""
        self._bottom_dynamic_annotations = annotations
        self._bottom_dynamic_title = title
        return self

    def clear_dynamic_annotations(
        self,
        side: Optional[Literal["top", "bottom"]] = None,
    ) -> "MirrorPlot":
        """Clear dynamic annotations for one or both sides."""
        if side in (None, "top"):
            self._top_dynamic_annotations = None
            self._top_dynamic_title = None
        if side in (None, "bottom"):
            self._bottom_dynamic_annotations = None
            self._bottom_dynamic_title = None
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotDynamicAnnotations -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add openms_insight/components/mirrorplot.py tests/test_mirrorplot_contract.py
git commit -m "feat(mirrorplot): add per-side dynamic annotation setters and clear"
```

---

### Task 7: Bridge integration (`_apply_fresh_annotations` and `_strip_dynamic_columns`)

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`
- Modify: `tests/test_mirrorplot_contract.py`

**Reference pattern:** `openms_insight/components/lineplot.py:_apply_fresh_annotations` (lines 582-645) and `_strip_dynamic_columns` (lines 554-580).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mirrorplot_contract.py`:

```python
class TestMirrorPlotBridgeIntegration:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = dict(
            cache_id="test_bridge",
            data=data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_strip_drops_dynamic_columns_from_both(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        # Build vue_data containing dynamic cols on both sides
        comp.set_top_dynamic_annotations(
            {10: {"highlight": True, "annotation": "b1"}}
        )
        comp.set_bottom_dynamic_annotations(
            {40: {"highlight": True, "annotation": "y3"}}
        )
        vue_data = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert "_dynamic_highlight" in vue_data["plotDataTop"].columns
        assert "_dynamic_highlight" in vue_data["plotDataBottom"].columns

        stripped = comp._strip_dynamic_columns(vue_data)
        assert "_dynamic_highlight" not in stripped["plotDataTop"].columns
        assert "_dynamic_annotation" not in stripped["plotDataTop"].columns
        assert "_dynamic_highlight" not in stripped["plotDataBottom"].columns
        assert "_dynamic_annotation" not in stripped["plotDataBottom"].columns
        # _plotConfig also removed (may reference dynamic column names)
        assert "_plotConfig" not in stripped

    def test_apply_fresh_annotations_top_only(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        # Build cached vue_data with no annotations
        cached = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        cached_clean = comp._strip_dynamic_columns(cached)

        # Set top annotations only
        comp.set_top_dynamic_annotations(
            {10: {"highlight": True, "annotation": "b1"}}
        )
        refreshed = comp._apply_fresh_annotations(cached_clean)

        assert "_dynamic_highlight" in refreshed["plotDataTop"].columns
        # Bottom must NOT have dynamic columns since no bottom annotations set
        assert "_dynamic_highlight" not in refreshed["plotDataBottom"].columns
        # _plotConfig rebuilt
        assert "_plotConfig" in refreshed
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mirrorplot_contract.py::TestMirrorPlotBridgeIntegration -v
```

Expected: FAIL — methods do not exist yet.

- [ ] **Step 3: Implement the bridge integration methods**

Append to `openms_insight/components/mirrorplot.py`:

```python
    def _strip_dynamic_columns(self, vue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Drop dynamic annotation columns from both DataFrames before caching."""
        import pandas as pd

        vue_data = dict(vue_data)
        dynamic_cols = ["_dynamic_highlight", "_dynamic_annotation"]

        for key in ("plotDataTop", "plotDataBottom"):
            df = vue_data.get(key)
            if df is not None and isinstance(df, pd.DataFrame):
                drop = [c for c in dynamic_cols if c in df.columns]
                if drop:
                    vue_data[key] = df.drop(columns=drop)

        # _plotConfig may reference dynamic column names — drop and let
        # _apply_fresh_annotations rebuild it.
        vue_data.pop("_plotConfig", None)
        return vue_data

    def _apply_fresh_annotations(self, vue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Re-apply current top/bottom dynamic annotations to cached base vue_data."""
        import pandas as pd

        vue_data = dict(vue_data)
        df_top = vue_data.get("plotDataTop")
        df_bottom = vue_data.get("plotDataBottom")
        if df_top is None or df_bottom is None:
            return vue_data
        if not isinstance(df_top, pd.DataFrame) or not isinstance(df_bottom, pd.DataFrame):
            return vue_data

        top_highlight_col = self._highlight_column
        top_annotation_col = self._annotation_column
        bot_highlight_col = self._highlight_column
        bot_annotation_col = self._annotation_column

        if self._top_dynamic_annotations and len(df_top) > 0:
            df_top = self._apply_annotations_to_df(df_top, self._top_dynamic_annotations)
            top_highlight_col = "_dynamic_highlight"
            top_annotation_col = "_dynamic_annotation"
        if self._bottom_dynamic_annotations and len(df_bottom) > 0:
            df_bottom = self._apply_annotations_to_df(
                df_bottom, self._bottom_dynamic_annotations
            )
            bot_highlight_col = "_dynamic_highlight"
            bot_annotation_col = "_dynamic_annotation"

        # Rebuild combined hash with annotation state
        existing_hash = vue_data.get("_hash", "")
        if self._top_dynamic_annotations or self._bottom_dynamic_annotations:
            ann_payload = (
                sorted((self._top_dynamic_annotations or {}).keys()),
                sorted((self._bottom_dynamic_annotations or {}).keys()),
            )
            ann_hash = hashlib.md5(str(ann_payload).encode()).hexdigest()[:8]
            existing_hash = f"{existing_hash}_{ann_hash}"

        vue_data["plotDataTop"] = df_top
        vue_data["plotDataBottom"] = df_bottom
        vue_data["_hash"] = existing_hash
        vue_data["_plotConfig"] = self._build_plot_config(
            top_highlight_col, top_annotation_col,
            bot_highlight_col, bot_annotation_col,
        )
        return vue_data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mirrorplot_contract.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add openms_insight/components/mirrorplot.py tests/test_mirrorplot_contract.py
git commit -m "feat(mirrorplot): implement bridge cache hit/store hooks"
```

---

### Task 8: Implement `__call__` with optional SequenceView annotation linking

**Files:**
- Modify: `openms_insight/components/mirrorplot.py`

**Reference pattern:** `openms_insight/components/lineplot.py:__call__` (lines 746-795).

- [ ] **Step 1: Implement `__call__`**

Append to `openms_insight/components/mirrorplot.py`:

```python
    def __call__(
        self,
        key: Optional[str] = None,
        state_manager: Optional["StateManager"] = None,
        height: Optional[int] = None,
        sequence_view_top_key: Optional[str] = None,
        sequence_view_bottom_key: Optional[str] = None,
    ) -> Any:
        """
        Render the component.

        If sequence_view_top_key is provided, fetches annotations from that
        SequenceView via get_component_annotations and applies them as top
        dynamic annotations. Same for sequence_view_bottom_key. Sides independent.
        """
        from ..core.state import get_default_state_manager
        from ..rendering.bridge import get_component_annotations, render_component

        if state_manager is None:
            state_manager = get_default_state_manager()

        def _annotations_from_sv(sv_key: str) -> Optional[Dict[Any, Dict[str, Any]]]:
            df = get_component_annotations(sv_key)
            if df is None or df.height == 0:
                return None
            result: Dict[Any, Dict[str, Any]] = {}
            for row in df.iter_rows(named=True):
                peak_id = row.get("peak_id")
                if peak_id is not None:
                    result[peak_id] = {
                        "highlight": True,
                        "annotation": row.get("annotation", ""),
                        "color": row.get("highlight_color", "#E4572E"),
                    }
            return result

        if sequence_view_top_key:
            anns = _annotations_from_sv(sequence_view_top_key)
            if anns:
                self.set_top_dynamic_annotations(anns)
            else:
                self.clear_dynamic_annotations(side="top")

        if sequence_view_bottom_key:
            anns = _annotations_from_sv(sequence_view_bottom_key)
            if anns:
                self.set_bottom_dynamic_annotations(anns)
            else:
                self.clear_dynamic_annotations(side="bottom")

        return render_component(
            component=self, state_manager=state_manager, key=key, height=height
        )
```

- [ ] **Step 2: Smoke-test the existing test suite**

```bash
pytest tests/test_mirrorplot_contract.py tests/test_mirrorplot_validation.py -v
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add openms_insight/components/mirrorplot.py
git commit -m "feat(mirrorplot): implement __call__ with optional SequenceView linking"
```

---

### Task 9: Integration tests (Python render pipeline)

**Files:**
- Create: `tests/integration/test_mirrorplot.py`

**Reference pattern:** `tests/integration/test_tabulator.py` for render-pipeline patterns; `tests/integration/test_cross_component_selection.py` for state-driven flows.

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_mirrorplot.py`:

```python
"""Integration tests for MirrorPlot — full render pipeline with StateManager."""

import pytest

from openms_insight import MirrorPlot
from openms_insight.core.state import StateManager


class TestMirrorPlotIntegration:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = dict(
            cache_id="test_integration",
            data=data,
            cache_path=str(temp_cache_dir),
            filters_top={"spectrum_top": "scan_id"},
            filters_bottom={"spectrum_bottom": "scan_id"},
            interactivity={"selected_peak": "peak_id"},
            x_column="mass",
            y_column="intensity",
        )
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_two_filter_selections_drive_independent_halves(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert set(result["plotDataTop"]["scan_id"]) == {1}
        assert set(result["plotDataBottom"]["scan_id"]) == {2}

        # Swap and re-render
        result2 = comp._prepare_vue_data(
            {"spectrum_top": 2, "spectrum_bottom": 1}
        )
        assert set(result2["plotDataTop"]["scan_id"]) == {2}
        assert set(result2["plotDataBottom"]["scan_id"]) == {1}

    def test_dynamic_annotations_per_side_independent(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)

        # Top only
        comp.set_top_dynamic_annotations(
            {10: {"highlight": True, "annotation": "b1"}}
        )
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert "_dynamic_highlight" in result["plotDataTop"].columns
        assert "_dynamic_highlight" not in result["plotDataBottom"].columns

        # Add bottom too
        comp.set_bottom_dynamic_annotations(
            {40: {"highlight": True, "annotation": "y3"}}
        )
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert "_dynamic_highlight" in result["plotDataTop"].columns
        assert "_dynamic_highlight" in result["plotDataBottom"].columns

        # Verify the annotation rows match (peak_id 10 in top, peak_id 40 in bottom)
        top_df = result["plotDataTop"]
        bot_df = result["plotDataBottom"]
        assert top_df.loc[top_df["peak_id"] == 10, "_dynamic_highlight"].iloc[0] == True
        assert bot_df.loc[bot_df["peak_id"] == 40, "_dynamic_highlight"].iloc[0] == True

    def test_clear_side_arg_independent(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        comp.set_bottom_dynamic_annotations({40: {"highlight": True, "annotation": "y3"}})

        comp.clear_dynamic_annotations(side="top")
        result = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )
        assert "_dynamic_highlight" not in result["plotDataTop"].columns
        assert "_dynamic_highlight" in result["plotDataBottom"].columns

    def test_hash_changes_when_either_side_filter_changes(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        h1 = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )["_hash"]
        h2 = comp._prepare_vue_data(
            {"spectrum_top": 2, "spectrum_bottom": 2}
        )["_hash"]
        h3 = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 1}
        )["_hash"]
        assert h1 != h2
        assert h1 != h3
        assert h2 != h3

    def test_hash_changes_when_annotations_change(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        h_no_ann = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )["_hash"]
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        h_with_ann = comp._prepare_vue_data(
            {"spectrum_top": 1, "spectrum_bottom": 2}
        )["_hash"]
        assert h_no_ann != h_with_ann
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
pytest tests/integration/test_mirrorplot.py -v
```

Expected: all PASS.

- [ ] **Step 3: Run the full Python test suite to catch regressions**

```bash
pytest tests/ -v
```

Expected: all existing tests still PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mirrorplot.py
git commit -m "test(mirrorplot): add integration tests for render pipeline"
```

---

## Phase 2 — Vue frontend

### Task 10: Add `MirrorPlotComponentArgs` type

**Files:**
- Modify: `js-component/src/types/component.ts`

- [ ] **Step 1: Locate the existing component-args interfaces**

```bash
grep -n "ComponentArgs\|LinePlotComponentArgs" /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component/src/types/component.ts | head -20
```

This file already declares the discriminated union for component args (e.g. `LinePlotComponentArgs`). The new `MirrorPlotComponentArgs` follows the same shape.

- [ ] **Step 2: Add the new interface**

In `js-component/src/types/component.ts`, append:

```typescript
export interface MirrorPlotComponentArgs {
  componentType: 'PlotlyMirrorPlot'
  xColumn: string
  yColumn: string
  highlightColumn?: string | null
  annotationColumn?: string | null
  title?: string
  titleTop?: string
  titleBottom?: string
  xLabel?: string
  yLabel?: string
  interactivity?: Record<string, string>
  styling?: {
    topColor?: string
    bottomColor?: string
    highlightColor?: string
    selectedColor?: string
    annotationColors?: Record<string, string>
  }
  config?: Record<string, unknown>
}
```

If the file declares a top-level `ComponentArgs` discriminated union, add `MirrorPlotComponentArgs` to it. Otherwise the new type stands alone.

- [ ] **Step 3: Type-check**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npx vue-tsc --build --force
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add js-component/src/types/component.ts
git commit -m "feat(mirrorplot): add MirrorPlotComponentArgs Vue type"
```

---

### Task 11: Create `PlotlyMirrorPlot.vue` skeleton

**Files:**
- Create: `js-component/src/components/plotly/PlotlyMirrorPlot.vue`

**Reference pattern:** `js-component/src/components/plotly/PlotlyLineplot.vue` — entire file. The mirror version reuses its structure (props, stores, computed, watchers) with the changes described below.

- [ ] **Step 1: Create the component skeleton**

Create `js-component/src/components/plotly/PlotlyMirrorPlot.vue`:

```vue
<template>
  <div :id="id" class="plot-container" :style="cssCustomProperties"></div>
</template>

<script lang="ts">
import { defineComponent, type PropType } from 'vue'
import Plotly from 'plotly.js-dist-min'
import { type Theme } from 'streamlit-component-lib'
import { useStreamlitDataStore } from '@/stores/streamlit-data'
import { useSelectionStore } from '@/stores/selection'
import type { MirrorPlotComponentArgs } from '@/types/component'

const DEFAULT_STYLING = {
  topColor: 'lightblue',
  bottomColor: 'lightcoral',
  highlightColor: '#E4572E',
  selectedColor: '#F3A712',
}

interface SideData {
  x: number[]
  y: number[]   // POSITIVE values from Python; we negate for bottom in render()
  highlight?: boolean[]
  annotations?: string[]
  interactivityValues?: Record<string, unknown[]>
}

export default defineComponent({
  name: 'PlotlyMirrorPlot',
  props: {
    args: {
      type: Object as PropType<MirrorPlotComponentArgs>,
      required: true,
    },
    index: {
      type: Number,
      required: true,
    },
  },
  setup() {
    const streamlitDataStore = useStreamlitDataStore()
    const selectionStore = useSelectionStore()
    return { streamlitDataStore, selectionStore }
  },
  data() {
    return {
      isInitialized: false as boolean,
    }
  },
  computed: {
    id(): string {
      return `mirror-plot-${this.index}`
    },
    theme(): Theme | undefined {
      return this.streamlitDataStore.theme
    },
    styling() {
      return { ...DEFAULT_STYLING, ...this.args.styling }
    },
    cssCustomProperties(): Record<string, string> {
      return {}
    },
    plotConfig(): Record<string, unknown> | undefined {
      return this.streamlitDataStore.allDataForDrawing?._plotConfig as
        | Record<string, unknown>
        | undefined
    },
    topData(): SideData | undefined {
      return this.extractSide('plotDataTop', 'topHighlightColumn', 'topAnnotationColumn')
    },
    bottomData(): SideData | undefined {
      return this.extractSide('plotDataBottom', 'bottomHighlightColumn', 'bottomAnnotationColumn')
    },
  },
  watch: {
    topData: {
      handler() {
        this.render()
      },
      deep: true,
    },
    bottomData: {
      handler() {
        this.render()
      },
      deep: true,
    },
    'selectionStore.counter'() {
      // Re-color only — no full redraw
      this.recolor()
    },
  },
  mounted() {
    this.render()
  },
  methods: {
    extractSide(
      dataKey: 'plotDataTop' | 'plotDataBottom',
      highlightConfigKey: 'topHighlightColumn' | 'bottomHighlightColumn',
      annotationConfigKey: 'topAnnotationColumn' | 'bottomAnnotationColumn',
    ): SideData | undefined {
      const raw = this.streamlitDataStore.allDataForDrawing?.[dataKey] as
        | Record<string, unknown[]>
        | undefined
      if (!raw) return undefined

      const xCol = (this.plotConfig?.xColumn as string) || this.args.xColumn
      const yCol = (this.plotConfig?.yColumn as string) || this.args.yColumn
      const highlightCol = this.plotConfig?.[highlightConfigKey] as string | null
      const annotationCol = this.plotConfig?.[annotationConfigKey] as string | null

      const interactivityValues: Record<string, unknown[]> = {}
      if (this.args.interactivity) {
        for (const column of Object.values(this.args.interactivity)) {
          if (raw[column]) {
            interactivityValues[column] = raw[column]
          }
        }
      }

      return {
        x: (raw[xCol] as number[]) || [],
        y: (raw[yCol] as number[]) || [],
        highlight: highlightCol ? (raw[highlightCol] as boolean[]) : undefined,
        annotations: annotationCol ? (raw[annotationCol] as string[]) : undefined,
        interactivityValues,
      }
    },
    render() {
      // Implemented in Task 12
    },
    recolor() {
      // Implemented in Task 13
    },
  },
})
</script>

<style scoped>
.plot-container {
  width: 100%;
  height: 100%;
}
</style>
```

- [ ] **Step 2: Type-check**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npx vue-tsc --build --force
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add js-component/src/components/plotly/PlotlyMirrorPlot.vue
git commit -m "feat(mirrorplot): add PlotlyMirrorPlot.vue skeleton"
```

---

### Task 12: Render two traces with symmetric Y axis

**Files:**
- Modify: `js-component/src/components/plotly/PlotlyMirrorPlot.vue`

**Reference pattern:** `js-component/src/components/plotly/PlotlyLineplot.vue:render` (search for the `Plotly.newPlot` call). Mirror the trace setup but produce two traces with the bottom y values negated.

- [ ] **Step 1: Implement the render method**

Replace the `render()` placeholder in `PlotlyMirrorPlot.vue`:

```ts
    render() {
      const top = this.topData
      const bottom = this.bottomData
      if (!top && !bottom) return

      const topY = top?.y ?? []
      const bottomY = bottom?.y ?? []
      const topMax = topY.length > 0 ? Math.max(...topY) : 0
      const bottomMax = bottomY.length > 0 ? Math.max(...bottomY) : 0
      const yMax = Math.max(topMax, bottomMax, 1.0) // 1.0 fallback for empty figure

      // Build per-peak colors (Task 13 will refine these)
      const topColors = this.colorsForSide(top, this.styling.topColor)
      const bottomColors = this.colorsForSide(bottom, this.styling.bottomColor)

      // Build "stick" lines as Plotly shapes (one per peak), top half positive, bottom negated
      const shapes: Plotly.Shape[] = []
      if (top) {
        for (let i = 0; i < top.x.length; i++) {
          shapes.push({
            type: 'line',
            x0: top.x[i],
            x1: top.x[i],
            y0: 0,
            y1: top.y[i],
            line: { color: topColors[i], width: 1.5 },
          })
        }
      }
      if (bottom) {
        for (let i = 0; i < bottom.x.length; i++) {
          shapes.push({
            type: 'line',
            x0: bottom.x[i],
            x1: bottom.x[i],
            y0: 0,
            y1: -bottom.y[i],  // FLIP HERE
            line: { color: bottomColors[i], width: 1.5 },
          })
        }
      }

      // Marker traces give us click events (the shapes alone don't)
      const traces: Partial<Plotly.PlotData>[] = [
        {
          x: top?.x ?? [],
          y: top?.y ?? [],
          mode: 'markers',
          type: 'scattergl',
          marker: { color: topColors, size: 4 },
          name: this.args.titleTop || 'Top',
          customdata: top?.x.map((_, i) => ({ side: 'top', index: i })) ?? [],
        },
        {
          x: bottom?.x ?? [],
          y: (bottom?.y ?? []).map((v) => -v),  // FLIP HERE
          mode: 'markers',
          type: 'scattergl',
          marker: { color: bottomColors, size: 4 },
          name: this.args.titleBottom || 'Bottom',
          customdata: bottom?.x.map((_, i) => ({ side: 'bottom', index: i })) ?? [],
        },
      ]

      const tickValues = [-yMax, -yMax / 2, 0, yMax / 2, yMax]
      const tickText = tickValues.map((v) => Math.abs(v).toFixed(0))

      const layout: Partial<Plotly.Layout> = {
        title: this.args.title,
        xaxis: { title: this.args.xLabel },
        yaxis: {
          title: this.args.yLabel,
          range: [-yMax * 1.1, yMax * 1.1],
          tickvals: tickValues,
          ticktext: tickText,
          zeroline: true,
          zerolinecolor: '#888',
          zerolinewidth: 1,
        },
        shapes,
        showlegend: false,
        annotations: [
          ...(this.args.titleTop
            ? [
                {
                  text: this.args.titleTop,
                  xref: 'paper',
                  yref: 'paper',
                  x: 0.02,
                  y: 0.98,
                  showarrow: false,
                  xanchor: 'left',
                  yanchor: 'top',
                } as Plotly.Annotations,
              ]
            : []),
          ...(this.args.titleBottom
            ? [
                {
                  text: this.args.titleBottom,
                  xref: 'paper',
                  yref: 'paper',
                  x: 0.02,
                  y: 0.02,
                  showarrow: false,
                  xanchor: 'left',
                  yanchor: 'bottom',
                } as Plotly.Annotations,
              ]
            : []),
        ],
      }

      const element = document.getElementById(this.id)
      if (!element) return

      void Plotly.newPlot(element, traces, layout, { responsive: true })
      this.isInitialized = true
    },

    colorsForSide(side: SideData | undefined, baseColor: string): string[] {
      if (!side) return []
      const colors: string[] = []
      const interactivityCol = this.firstInteractivityColumn()
      const selectionValue = interactivityCol
        ? this.currentSelectionValue()
        : undefined

      for (let i = 0; i < side.x.length; i++) {
        let color = baseColor
        if (side.highlight?.[i]) {
          color = this.styling.highlightColor!
        }
        if (
          interactivityCol &&
          side.interactivityValues?.[interactivityCol]?.[i] === selectionValue &&
          selectionValue !== undefined
        ) {
          color = this.styling.selectedColor!
        }
        colors.push(color)
      }
      return colors
    },

    firstInteractivityColumn(): string | undefined {
      const map = this.args.interactivity
      if (!map) return undefined
      const keys = Object.keys(map)
      return keys.length ? map[keys[0]] : undefined
    },

    currentSelectionValue(): unknown {
      const map = this.args.interactivity
      if (!map) return undefined
      const firstIdentifier = Object.keys(map)[0]
      if (!firstIdentifier) return undefined
      return this.selectionStore.getSelection(firstIdentifier)
    },
```

- [ ] **Step 2: Type-check**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npx vue-tsc --build --force
```

Expected: no errors. (If `Plotly.Shape` or `Plotly.Annotations` types are not exposed by `plotly.js-dist-min`, fall back to `any` for the shape/annotation arrays — same approach `PlotlyLineplot.vue` uses.)

- [ ] **Step 3: Commit**

```bash
git add js-component/src/components/plotly/PlotlyMirrorPlot.vue
git commit -m "feat(mirrorplot): render two traces with symmetric Y axis"
```

---

### Task 13: Click handler with shared interactivity + recolor on selection change

**Files:**
- Modify: `js-component/src/components/plotly/PlotlyMirrorPlot.vue`

- [ ] **Step 1: Wire the Plotly click event**

In `PlotlyMirrorPlot.vue`'s `render()` method, after the `Plotly.newPlot` call, attach a click listener:

```ts
      const plotEl = element as Plotly.PlotlyHTMLElement
      plotEl.removeAllListeners?.('plotly_click')
      plotEl.on('plotly_click', (event: Plotly.PlotMouseEvent) => {
        const pt = event.points?.[0]
        if (!pt) return
        const traceIdx = pt.curveNumber
        const sourceData = traceIdx === 0 ? this.topData : this.bottomData
        if (!sourceData) return

        const interactivity = this.args.interactivity
        if (!interactivity) return

        for (const [identifier, column] of Object.entries(interactivity)) {
          const values = sourceData.interactivityValues?.[column]
          if (values && pt.pointIndex !== undefined) {
            this.selectionStore.setSelection(identifier, values[pt.pointIndex])
          }
        }
      })
```

- [ ] **Step 2: Implement `recolor` (selection counter watcher)**

Replace the `recolor()` placeholder:

```ts
    recolor() {
      if (!this.isInitialized) return
      const top = this.topData
      const bottom = this.bottomData

      const topColors = this.colorsForSide(top, this.styling.topColor)
      const bottomColors = this.colorsForSide(bottom, this.styling.bottomColor)

      // Update marker colors on existing traces
      void Plotly.restyle(this.id, { 'marker.color': [topColors] }, [0])
      void Plotly.restyle(this.id, { 'marker.color': [bottomColors] }, [1])

      // Update shape colors (rebuild shapes with new colors)
      const shapes: Plotly.Shape[] = []
      if (top) {
        for (let i = 0; i < top.x.length; i++) {
          shapes.push({
            type: 'line',
            x0: top.x[i],
            x1: top.x[i],
            y0: 0,
            y1: top.y[i],
            line: { color: topColors[i], width: 1.5 },
          })
        }
      }
      if (bottom) {
        for (let i = 0; i < bottom.x.length; i++) {
          shapes.push({
            type: 'line',
            x0: bottom.x[i],
            x1: bottom.x[i],
            y0: 0,
            y1: -bottom.y[i],
            line: { color: bottomColors[i], width: 1.5 },
          })
        }
      }
      void Plotly.relayout(this.id, { shapes })
    },
```

- [ ] **Step 3: Type-check**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npx vue-tsc --build --force
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add js-component/src/components/plotly/PlotlyMirrorPlot.vue
git commit -m "feat(mirrorplot): wire click handler and selection recolor"
```

---

### Task 14: Register `PlotlyMirrorPlot` in App.vue

**Files:**
- Modify: `js-component/src/App.vue`

- [ ] **Step 1: Locate the existing component switch**

```bash
grep -n "currentComponent\|PlotlyLineplot" /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component/src/App.vue | head -20
```

Identify (a) the existing imports of Plotly Vue components, (b) the `components: { ... }` registration, and (c) the `currentComponent` computed switch.

- [ ] **Step 2: Add import + registration + switch case**

In `js-component/src/App.vue`:

1. Top of `<script>`, alongside other imports, add:

```ts
import PlotlyMirrorPlot from './components/plotly/PlotlyMirrorPlot.vue'
```

2. In the `components: { ... }` block, append:

```ts
  PlotlyMirrorPlot,
```

3. In the `currentComponent` computed switch, add a new case before the `default`:

```ts
case 'PlotlyMirrorPlot':
  return PlotlyMirrorPlot
```

- [ ] **Step 3: Type-check**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npx vue-tsc --build --force
```

Expected: no errors.

- [ ] **Step 4: Build the bundle**

```bash
npm run build
```

Expected: clean build, output in `dist/`.

- [ ] **Step 5: Commit**

```bash
git add js-component/src/App.vue
git commit -m "feat(mirrorplot): register PlotlyMirrorPlot in App.vue routing"
```

---

## Phase 3 — End-to-end verification

### Task 15: Manual smoke test in example_app

**Files:** none modified. This is a verification task.

- [ ] **Step 1: Build and link the Vue bundle**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight/js-component
npm run build
cd ..
mkdir -p openms_insight/js-component
rm -rf openms_insight/js-component/dist
cp -r js-component/dist openms_insight/js-component/
```

- [ ] **Step 2: Create a temporary smoke-test app**

Create `/tmp/mirrorplot_smoke.py`:

```python
"""Manual smoke test for MirrorPlot."""

import polars as pl
import streamlit as st

from openms_insight import MirrorPlot, StateManager

st.set_page_config(layout="wide")

data = pl.LazyFrame(
    {
        "scan_id": [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
        "mass": [100.0, 200.0, 300.0, 400.0, 500.0, 100.0, 250.0, 300.0, 450.0, 500.0],
        "intensity": [1000, 2000, 1500, 3000, 500, 800, 1700, 1200, 2800, 900],
        "peak_id": list(range(10)),
    }
)

state_manager = StateManager()

# Two simple selectors driving the per-side filters
col_a, col_b = st.columns(2)
with col_a:
    top_scan = st.selectbox("Top spectrum", [1, 2], key="ui_top")
    state_manager.set_selection("spectrum_top", top_scan)
with col_b:
    bottom_scan = st.selectbox("Bottom spectrum", [1, 2], index=1, key="ui_bot")
    state_manager.set_selection("spectrum_bottom", bottom_scan)

mirror = MirrorPlot(
    cache_id="smoke_mirror",
    data=data,
    cache_path="/tmp/mirror_cache",
    filters_top={"spectrum_top": "scan_id"},
    filters_bottom={"spectrum_bottom": "scan_id"},
    interactivity={"selected_peak": "peak_id"},
    x_column="mass",
    y_column="intensity",
    title="Mirror smoke test",
    title_top=f"Scan {top_scan}",
    title_bottom=f"Scan {bottom_scan}",
)
mirror(key="mirror", state_manager=state_manager, height=600)

st.write("Selected peak:", state_manager.get_selection("selected_peak"))
```

- [ ] **Step 3: Run it**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight
streamlit run /tmp/mirrorplot_smoke.py
```

- [ ] **Step 4: Verify in the browser**

Check that:
- Top half shows one spectrum, bottom half another, mirrored across y=0.
- Y-axis tick labels read as positive numbers on both halves.
- Switching `Top spectrum` updates the top half only; switching `Bottom spectrum` updates the bottom half only.
- Setting both selectors to the same value produces a vertically symmetric plot (same peaks above and below).
- Clicking a peak on either half updates the "Selected peak" line to that peak's `peak_id`.
- If a peak with the same m/z exists on both halves, both highlight when clicked.

Stop streamlit (`Ctrl-C`).

- [ ] **Step 5: No commit**

This task only verifies behavior; nothing to commit. Report any failures and address them by amending the relevant earlier task.

---

### Task 16: Final pass — full test suite, lint, type-check

**Files:** none modified. Final verification.

- [ ] **Step 1: Run all Python tests**

```bash
cd /home/tom-mueller/kohlbacherlab/viz_package/openms-insight
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 2: Lint Python**

```bash
ruff check openms_insight/components/mirrorplot.py tests/test_mirrorplot_*.py tests/integration/test_mirrorplot.py
ruff format openms_insight/components/mirrorplot.py tests/test_mirrorplot_*.py tests/integration/test_mirrorplot.py
```

Expected: clean (or auto-fixed).

- [ ] **Step 3: Type-check Vue**

```bash
cd js-component
npx vue-tsc --build --force
```

Expected: no errors.

- [ ] **Step 4: Lint Vue**

```bash
npm run lint
```

Expected: clean.

- [ ] **Step 5: Production Vue build (final)**

```bash
npm run build
cd ..
rm -rf openms_insight/js-component/dist
mkdir -p openms_insight/js-component
cp -r js-component/dist openms_insight/js-component/
```

- [ ] **Step 6: Final commit if any formatting changes were made**

```bash
git status
# If anything is modified by ruff format or eslint:
git add -A
git commit -m "style: apply ruff/eslint formatting"
```

---

## Self-review

### Spec coverage

- §1 Overview / Design contract — Tasks 1, 2, 4, 6 cover the contract bullets (single dataset, per-side filters, shared click, Vue-side flip, symmetric Y, per-side dynamic annotations).
- §2 Approach decision — implementation follows Approach A (new BaseComponent + new Vue component).
- §3 File layout — Tasks 1, 10, 11, 14 cover all new and modified files. The `tests/conftest.py` "potentially add `sample_mirror_data`" line was resolved during planning by reusing existing `sample_lineplot_data`.
- §4 Constructor + argument reference — Task 1.
- §4 Lifecycle methods (`_validate_mappings`, `_preprocess`, `_get_vue_component_name`, `_get_data_key`, `_get_row_group_size`, `_get_cache_config`, `_restore_cache_config`, `get_state_dependencies`, `_prepare_vue_data`, `_get_component_args`) — Tasks 1-5.
- §4 Parent-class state population — Task 1 (kwargs.pop pattern).
- §4 Runtime methods — Task 6.
- §4 `__call__` — Task 8.
- §4 Bridge integration — Task 7.
- §5 Vue component contract — Tasks 10-14.
- §6 Data flow — Tasks 4, 7.
- §7 Validation — Task 1.
- §7 Reconstruction-from-cache mode — Task 1 (test_reconstruct_from_cache_only re-run after Task 3).
- §8 Testing strategy — Tasks 1, 3-7, 9.

### Placeholder scan

- No "TBD" / "TODO" / "implement later" anywhere in the plan body.
- Steps that say "Implemented in Task N" are scoped placeholders inside Task 11's skeleton — Tasks 12 and 13 fill them with full code, not vague descriptions.

### Type / signature consistency

- `_prepare_vue_data` returns dict with `plotDataTop`, `plotDataBottom`, `_hash`, `_plotConfig` — used consistently across Tasks 4, 7, 9, 12.
- Vue side reads `_plotConfig.topHighlightColumn`, `_plotConfig.bottomHighlightColumn` — Task 4 emits exactly these keys, Task 11 reads them via the same names.
- `set_top_dynamic_annotations` / `set_bottom_dynamic_annotations` / `clear_dynamic_annotations` — Task 6 defines these names; Tasks 8 and 9 use them with the same names.
- `_filters_top`, `_filters_bottom`, `_filter_defaults_top`, `_filter_defaults_bottom`, `_top_dynamic_annotations`, `_bottom_dynamic_annotations`, `_top_dynamic_title`, `_bottom_dynamic_title` — Task 1 defines, Tasks 3-9 use consistently.
