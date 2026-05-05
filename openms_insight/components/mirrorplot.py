"""Mirror plot component using Plotly.js — two spectra, one figure."""

from typing import TYPE_CHECKING, Any, Dict, Optional

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
