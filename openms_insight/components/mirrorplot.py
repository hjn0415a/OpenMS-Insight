"""Mirror plot component using Plotly.js — two spectra, one figure."""

import hashlib
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

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
        """
        Initialize the MirrorPlot component.

        Args:
            cache_id: Unique identifier for this component's cache (MANDATORY).
                Creates a folder {cache_path}/{cache_id}/ for cached data.
            data: Polars LazyFrame with plot data. Optional if cache exists.
            data_path: Path to parquet file (preferred for large datasets).
            filters_top: Mapping of identifier names to column names for filtering
                the top spectrum.
                Example: {'spectrum_top': 'scan_id'}
                When 'spectrum_top' selection exists, the top half shows only data
                where scan_id equals the selected value.
            filter_defaults_top: Default values for filters_top when state is None.
                Example: {'spectrum_top': -1}
                When 'spectrum_top' selection is None, filter uses -1 instead.
            filters_bottom: Mapping of identifier names to column names for
                filtering the bottom spectrum.
                Example: {'spectrum_bottom': 'scan_id'}
            filter_defaults_bottom: Default values for filters_bottom when state
                is None.
            interactivity: Mapping of identifier names to column names for clicks.
                Shared between both halves — clicking a peak in either half sets
                the same selection identifier.
                Example: {'selected_peak': 'peak_id'}
            cache_path: Base path for cache storage. Default "." (current dir).
            regenerate_cache: If True, regenerate cache even if valid cache exists.
            x_column: Column name for x-axis values (shared for both halves).
            y_column: Column name for y-axis values (positive for both halves;
                Vue flips the bottom half to negative at render time).
            highlight_column: Optional column name containing boolean/int
                              indicating which points to highlight (shared).
            annotation_column: Optional column name containing text annotations
                               to display on highlighted points (shared).
            title: Overall plot title (superseded by title_top/title_bottom if set).
            title_top: Label shown above the top spectrum.
            title_bottom: Label shown below the bottom spectrum (above the x-axis).
            x_label: X-axis label (defaults to x_column).
            y_label: Y-axis label (defaults to y_column).
            styling: Style configuration dict with keys:
                - highlightColor: Color for highlighted points (default: '#E4572E')
                - selectedColor: Color for clicked/selected peak (default: '#F3A712')
                - unhighlightedColor: Color for normal points (default: 'lightblue')
                - annotationBackground: Background color for annotations
            config: Additional Plotly config options.
            **kwargs: Additional configuration options.
        """
        # Subprocess preprocessing re-instantiates the component via
        # MirrorPlot(filters=union, filter_defaults=union, **kwargs) because
        # BaseComponent passes them as explicit kwargs. Without popping them,
        # super().__init__(filters=...) would receive `filters` twice and raise
        # TypeError.
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

        # Note: this deliberately does NOT call super()._validate_mappings(). We re-
        # implement the filter/interactivity column checks here to produce per-side
        # error messages naming filters_top/filters_bottom. If BaseComponent grows new
        # checks, mirror them here.

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
        """Always 10_000 — constructor enforces non-empty filters on both sides."""
        return 10_000

    def _get_vue_component_name(self) -> str:
        return "PlotlyMirrorPlot"

    def _get_data_key(self) -> str:
        return "plotDataTop"

    def get_state_dependencies(self) -> List[str]:
        """Both per-side filter identifiers; interactivity excluded so clicks don't invalidate cache."""
        return list(self._filters_top.keys()) + list(self._filters_bottom.keys())

    def _get_cache_config(self) -> Dict[str, Any]:
        """Configuration that affects cache validity."""
        return {
            "filters_top": self._filters_top,
            "filters_bottom": self._filters_bottom,
            "filter_defaults_top": self._filter_defaults_top,
            "filter_defaults_bottom": self._filter_defaults_bottom,
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
        self._x_column = config.get("x_column", "x")
        self._y_column = config.get("y_column", "y")
        self._highlight_column = config.get("highlight_column")
        self._annotation_column = config.get("annotation_column")
        self._title = config.get("title")
        self._title_top = config.get("title_top")
        self._title_bottom = config.get("title_bottom")
        self._x_label = config.get("x_label", self._x_column)
        self._y_label = config.get("y_label", self._y_column)
        self._styling = config.get("styling", {})
        self._plot_config = config.get("plot_config", {})
        # Dynamic state (not cached) — reset to None
        self._top_dynamic_annotations = None
        self._bottom_dynamic_annotations = None
        self._top_dynamic_title = None
        self._bottom_dynamic_title = None

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

        # Get cached data (DataFrame or LazyFrame)
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
                top_highlight_col=top_highlight_col,
                top_annotation_col=top_annotation_col,
                bot_highlight_col=bot_highlight_col,
                bot_annotation_col=bot_annotation_col,
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
        top_highlight_col: Optional[str] = None,
        top_annotation_col: Optional[str] = None,
        bot_highlight_col: Optional[str] = None,
        bot_annotation_col: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Plot config sent alongside data — Vue uses it to map columns per side.

        Called from two places:
        - `_prepare_vue_data` and `_apply_fresh_annotations` (Task 7) pass all 4
          args, allowing each side to have its own column names (e.g.
          _dynamic_highlight when annotations are active on that side).
        - `bridge.py` calls with 2 args (static highlight/annotation columns).
          Both sides default to those static columns in that case.
        """
        # Bridge 2-arg form: bottom defaults to top (= static columns)
        if bot_highlight_col is None:
            bot_highlight_col = top_highlight_col
        if bot_annotation_col is None:
            bot_annotation_col = top_annotation_col

        return {
            "xColumn": self._x_column,
            "yColumn": self._y_column,
            "topHighlightColumn": top_highlight_col,
            "topAnnotationColumn": top_annotation_col,
            "bottomHighlightColumn": bot_highlight_col,
            "bottomAnnotationColumn": bot_annotation_col,
            "interactivityColumns": {
                col: col
                for col in (
                    self._interactivity.values() if self._interactivity else []
                )
            },
        }

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
        # Inject any extra user-provided keys without overwriting explicitly set ones
        for key, val in self._config.items():
            if key not in args:
                args[key] = val
        return args

    def set_top_dynamic_annotations(
        self,
        annotations: Optional[Dict[Any, Dict[str, Any]]],
        title: Optional[str] = None,
    ) -> "MirrorPlot":
        """Apply per-render annotations to the top spectrum only.

        Args:
            annotations: Dict keyed by interactivity-column value (peak_id),
                each entry containing {'highlight': bool, 'annotation': str}.
                Pass None to clear (or use clear_dynamic_annotations(side='top')).
            title: Optional dynamic title — overrides title_top for this render.

        Not cached. Returns self for chaining.
        """
        self._top_dynamic_annotations = annotations
        self._top_dynamic_title = title
        return self

    def set_bottom_dynamic_annotations(
        self,
        annotations: Optional[Dict[Any, Dict[str, Any]]],
        title: Optional[str] = None,
    ) -> "MirrorPlot":
        """Apply per-render annotations to the bottom spectrum only.

        Args:
            annotations: Dict keyed by interactivity-column value (peak_id),
                each entry containing {'highlight': bool, 'annotation': str}.
                Pass None to clear (or use clear_dynamic_annotations(side='bottom')).
            title: Optional dynamic title — overrides title_bottom for this render.

        Not cached. Returns self for chaining.
        """
        self._bottom_dynamic_annotations = annotations
        self._bottom_dynamic_title = title
        return self

    def clear_dynamic_annotations(
        self,
        side: Optional[Literal["top", "bottom"]] = None,
    ) -> "MirrorPlot":
        """Clear dynamic annotations for one or both sides.

        Args:
            side: None (default) clears both halves. "top" clears only top.
                "bottom" clears only bottom.

        Returns self for chaining.
        """
        if side in (None, "top"):
            self._top_dynamic_annotations = None
            self._top_dynamic_title = None
        if side in (None, "bottom"):
            self._bottom_dynamic_annotations = None
            self._bottom_dynamic_title = None
        return self

    def _strip_dynamic_columns(self, vue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Drop dynamic annotation columns from both DataFrames before caching.

        Called by bridge.py when storing vue_data in the runtime cache, so
        future cache hits don't carry stale annotation state. _plotConfig is
        also dropped because it may reference dynamic column names —
        _apply_fresh_annotations rebuilds it.
        """
        import pandas as pd

        vue_data = dict(vue_data)
        dynamic_cols = ["_dynamic_highlight", "_dynamic_annotation"]

        for key in ("plotDataTop", "plotDataBottom"):
            df = vue_data.get(key)
            if df is not None and isinstance(df, pd.DataFrame):
                drop = [c for c in dynamic_cols if c in df.columns]
                if drop:
                    vue_data[key] = df.drop(columns=drop)

        vue_data.pop("_plotConfig", None)
        return vue_data

    def _apply_fresh_annotations(self, vue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Re-apply current top/bottom dynamic annotations to cached base vue_data.

        Called by bridge.py on cache hits when dynamic annotations are active.
        Builds a fresh _plotConfig that points to the dynamic columns where
        applicable.
        """
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
            top_highlight_col=top_highlight_col,
            top_annotation_col=top_annotation_col,
            bot_highlight_col=bot_highlight_col,
            bot_annotation_col=bot_annotation_col,
        )
        return vue_data


if TYPE_CHECKING:
    from ..core.state import StateManager  # noqa: F401
