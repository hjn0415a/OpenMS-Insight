"""Contract tests for MirrorPlot."""

import pandas as pd

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
        assert restored._top_dynamic_title is None
        assert restored._bottom_dynamic_title is None
        assert restored._x_column == "mass"
        assert restored._y_column == "intensity"
        assert restored._highlight_column == "annotation"
        assert restored._annotation_column == "annotation"
        assert restored._title == "Compare"
        assert restored._x_label == "m/z"
        assert restored._y_label == "Intensity"
        assert restored._styling == {"topColor": "#1f77b4", "bottomColor": "#d62728"}
        assert restored._plot_config == {"displayModeBar": True}


class TestMirrorPlotPrepareVueData:
    def _make(self, temp_cache_dir, data, **overrides):
        defaults = {
            "cache_id": "test_prepare",
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
