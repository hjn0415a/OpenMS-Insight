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
