"""Integration tests for MirrorPlot — full render pipeline with StateManager."""

from openms_insight import MirrorPlot


class TestMirrorPlotIntegration:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = {
            "cache_id": "test_integration",
            "data": data,
            "cache_path": str(temp_cache_dir),
            "filters_top": {"spectrum_top": "scan_id"},
            "filters_bottom": {"spectrum_bottom": "scan_id"},
            "interactivity": {"selected_peak": "peak_id"},
            "x_column": "mass",
            "y_column": "intensity",
        }
        defaults.update(overrides)
        return MirrorPlot(**defaults)

    def test_two_filter_selections_drive_independent_halves(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        result = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})
        assert set(result["plotDataTop"]["scan_id"]) == {1}
        assert set(result["plotDataBottom"]["scan_id"]) == {2}

        # Swap and re-render
        result2 = comp._prepare_vue_data({"spectrum_top": 2, "spectrum_bottom": 1})
        assert set(result2["plotDataTop"]["scan_id"]) == {2}
        assert set(result2["plotDataBottom"]["scan_id"]) == {1}

    def test_dynamic_annotations_per_side_independent(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)

        # Top only
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        result = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})
        assert "_dynamic_highlight" in result["plotDataTop"].columns
        assert "_dynamic_highlight" not in result["plotDataBottom"].columns

        # Add bottom too
        comp.set_bottom_dynamic_annotations(
            {40: {"highlight": True, "annotation": "y3"}}
        )
        result = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})
        assert "_dynamic_highlight" in result["plotDataTop"].columns
        assert "_dynamic_highlight" in result["plotDataBottom"].columns

        # Verify the annotation rows match (peak_id 10 in top, peak_id 40 in bottom)
        top_df = result["plotDataTop"]
        bot_df = result["plotDataBottom"]
        assert top_df.loc[top_df["peak_id"] == 10, "_dynamic_highlight"].iloc[0]
        assert bot_df.loc[bot_df["peak_id"] == 40, "_dynamic_highlight"].iloc[0]

    def test_clear_side_arg_independent(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        comp.set_bottom_dynamic_annotations(
            {40: {"highlight": True, "annotation": "y3"}}
        )

        comp.clear_dynamic_annotations(side="top")
        result = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})
        assert "_dynamic_highlight" not in result["plotDataTop"].columns
        assert "_dynamic_highlight" in result["plotDataBottom"].columns

    def test_hash_changes_when_either_side_filter_changes(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        h1 = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})["_hash"]
        h2 = comp._prepare_vue_data({"spectrum_top": 2, "spectrum_bottom": 2})["_hash"]
        h3 = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 1})["_hash"]
        assert h1 != h2
        assert h1 != h3
        assert h2 != h3

    def test_hash_changes_when_annotations_change(
        self, mock_streamlit, temp_cache_dir, sample_lineplot_data
    ):
        comp = self._make(temp_cache_dir, sample_lineplot_data)
        h_no_ann = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})[
            "_hash"
        ]
        comp.set_top_dynamic_annotations({10: {"highlight": True, "annotation": "b1"}})
        h_with_ann = comp._prepare_vue_data({"spectrum_top": 1, "spectrum_bottom": 2})[
            "_hash"
        ]
        assert h_no_ann != h_with_ann
