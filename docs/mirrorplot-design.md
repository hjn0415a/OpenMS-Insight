# MirrorPlot Component Design

**Status:** Approved (2026-05-05)
**Component:** `openms_insight.MirrorPlot`
**Vue component:** `PlotlyMirrorPlot.vue`

## 1. Overview

A mirror plot displays two mass spectra in a single figure: one above a horizontal baseline, one below (with intensities flipped). It enables side-by-side visual comparison of two spectra — for example, two PSMs of the same precursor, experimental vs. theoretical, or two replicates.

`MirrorPlot` is built directly on `BaseComponent` (not as a `LinePlot` subclass) and ships its own Vue component. It reuses the project's existing caching, state management, and bridge infrastructure unchanged.

### Design contract

- **Single shared dataset.** Top and bottom halves both pull from the same `data` LazyFrame.
- **Two independent selection states drive filtering.** `filters_top` and `filters_bottom` each map their own identifier(s) to columns. The two filter identifier-name sets must be disjoint.
- **One shared selection state captures clicks.** Clicking a peak on either half fills the same `interactivity` identifier; matching peaks on both halves are highlighted automatically.
- **Y-axis flip happens in Vue, not Python.** The cached parquet stores positive y-values for both halves; Vue negates the bottom half at render time.
- **Symmetric Y-axis range.** `Ymax = max(|top_max|, |bottom_max|)`; tick labels rendered as absolute values so both halves read positive.
- **Independent dynamic annotations per half.** Two annotation slots, two setter methods, one clear method with optional `side` argument.

## 2. Approach decision

Three approaches were considered:

| | Approach | Verdict |
|---|---|---|
| A | New `BaseComponent` subclass + new Vue component (`PlotlyMirrorPlot.vue`) | **Chosen.** Clean separation; full control over layout and Y-axis behavior; LinePlot stays untouched. |
| B | Composition over two `LinePlot` instances stacked in Streamlit containers | Rejected — cannot deliver true mirror visual (each LinePlot renders an independent Plotly figure with its own Y axis). |
| C | `LinePlot` subclass + extend `PlotlyLineplot.vue` with mirror mode | Rejected — most of LinePlot's internals assume a single `filters` dict and a single `_dynamic_annotations` slot; subclassing forces overrides that risk breaking the LinePlot path, and the Vue component grows `if (mirror)` branches throughout. |

Annotation overlay logic is duplicated from `PlotlyLineplot.vue` only if the diff stays small. If duplication grows, the overlay can be lifted into a shared composable in a follow-up — not in scope for the initial implementation.

## 3. File layout

### New files

| File | Purpose |
|---|---|
| `openms_insight/components/mirrorplot.py` | `MirrorPlot(BaseComponent)` class, registered as `@register_component("mirrorplot")` |
| `js-component/src/components/plotly/PlotlyMirrorPlot.vue` | Vue component: one Plotly figure with two traces, symmetric Y axis, per-side annotation overlays |
| `tests/test_mirrorplot_contract.py` | Contract tests |
| `tests/test_mirrorplot_validation.py` | Constructor validation tests |
| `tests/integration/test_mirrorplot.py` | Render-pipeline integration tests |

### Edited files

| File | Edit |
|---|---|
| `openms_insight/components/__init__.py` | Re-export `MirrorPlot` |
| `openms_insight/__init__.py` | Re-export `MirrorPlot` |
| `js-component/src/App.vue` | Import `PlotlyMirrorPlot`, register in `components: {...}`, add `case 'PlotlyMirrorPlot'` to `currentComponent` switch |
| `js-component/src/types/component.ts` | Add `MirrorPlotComponentArgs` type |
| `tests/conftest.py` | Add `sample_mirror_data` fixture if `sample_lineplot_data` is insufficient |

### Untouched

- `LinePlot`, `PlotlyLineplot.vue`
- `BaseComponent`, `bridge.py`, `StateManager`
- `CACHE_VERSION` (no cache structure changes for existing components)

## 4. Python API surface

### Constructor

```python
@register_component("mirrorplot")
class MirrorPlot(BaseComponent):
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
    ): ...
```

`filters_top` and `filters_bottom` are typed `Optional` to support reconstruction-from-cache mode (where the constructor is called with only `cache_id`). In creation mode (`data` or `data_path` provided), both are required and `_validate_mappings` raises if either is missing.

### Argument reference

| Group | Argument | Type | Default | Notes |
|---|---|---|---|---|
| Identity | `cache_id` | `str` | — | Required |
| Data (shared) | `data` | `pl.LazyFrame?` | `None` | Same dataset feeds both halves |
| | `data_path` | `str?` | `None` | Preferred for large datasets (subprocess preprocess) |
| Top selection | `filters_top` | `Dict[str,str]?` | `None` | Required in creation mode |
| | `filter_defaults_top` | `Dict[str,Any]?` | `None` | Fallback when top identifier's selection is `None` |
| Bottom selection | `filters_bottom` | `Dict[str,str]?` | `None` | Required in creation mode |
| | `filter_defaults_bottom` | `Dict[str,Any]?` | `None` | Fallback for bottom |
| Click (shared) | `interactivity` | `Dict[str,str]?` | `None` | Single selection state across both halves |
| Cache | `cache_path` | `str` | `"."` | |
| | `regenerate_cache` | `bool` | `False` | |
| Schema (shared) | `x_column` | `str` | `"x"` | |
| | `y_column` | `str` | `"y"` | User supplies positive values; component negates internally for bottom |
| | `highlight_column` | `str?` | `None` | Shared bool/int column for highlighting |
| | `annotation_column` | `str?` | `None` | Shared text column for peak labels |
| Labels | `title` | `str?` | `None` | Overall figure title |
| | `title_top` | `str?` | `None` | Label inside top half |
| | `title_bottom` | `str?` | `None` | Label inside bottom half |
| | `x_label` | `str?` | `x_column` | |
| | `y_label` | `str?` | `y_column` | Tick labels rendered as absolute values; both halves read positive |
| Visuals | `styling` | `Dict[str,Any]?` | `None` | Recognized keys: `topColor`, `bottomColor`, `highlightColor`, `selectedColor`, `annotationColors{...}` |
| | `config` | `Dict[str,Any]?` | `None` | Plotly config passthrough |

### Lifecycle methods

| Method | Behavior |
|---|---|
| `_validate_mappings()` | Calls `super()`, then asserts: (a) creation mode requires both `filters_top` and `filters_bottom` non-empty, (b) `set(filters_top.keys()) & set(filters_bottom.keys()) == ∅`, (c) all referenced columns (`x`, `y`, `highlight`, `annotation`, filter columns, interactivity columns) exist in schema |
| `_preprocess()` | Sorts shared LazyFrame by the union of top + bottom filter columns for predicate pushdown on either side. Stores as `self._preprocessed_data["data"]` (kept lazy) |
| `_get_vue_component_name()` | Returns `"PlotlyMirrorPlot"` |
| `_get_data_key()` | Returns `"plotDataTop"` (primary; the dict also carries `plotDataBottom`) |
| `_get_row_group_size()` | `10_000` (always — both filter sets are required in creation mode) |
| `_get_cache_config()` | Returns dict containing every constructor arg that affects preprocessing or rendering: `filters_top`, `filters_bottom`, `filter_defaults_top`, `filter_defaults_bottom`, `interactivity`, `x_column`, `y_column`, `highlight_column`, `annotation_column`, `title`, `title_top`, `title_bottom`, `x_label`, `y_label`, `styling`, `plot_config` |
| `_restore_cache_config(config)` | Restores each field; resets `_top_dynamic_annotations`, `_bottom_dynamic_annotations`, `_top_dynamic_title`, `_bottom_dynamic_title` to `None` (dynamic state is never cached) |
| `get_state_dependencies()` | Returns `list(filters_top.keys()) + list(filters_bottom.keys())`. Interactivity identifiers deliberately excluded — clicks should not invalidate the data cache |
| `_prepare_vue_data(state)` | See §6 (data flow) |
| `_get_component_args()` | Returns `componentType`, `title`, `titleTop`, `titleBottom`, `xLabel`, `yLabel`, `xColumn`, `yColumn`, `highlightColumn`, `annotationColumn`, `interactivity`, merged `styling` (with mirror-specific defaults: `topColor`, `bottomColor`), and `config` |

### Parent-class state population

`BaseComponent.__init__` populates `self._filters` and `self._filter_defaults` from its `filters=` and `filter_defaults=` kwargs. To keep parent machinery working without forking it, MirrorPlot stores its per-side dicts as `self._filters_top` / `self._filters_bottom` (and the analogous `_filter_defaults_*`) **before** calling `super().__init__()`, then passes the union — `filters={**filters_top, **filters_bottom}` and `filter_defaults={**(filter_defaults_top or {}), **(filter_defaults_bottom or {})}` — to super. The disjoint-identifier-name validation guarantees the union is collision-free. After init, MirrorPlot reads from `self._filters_top` / `self._filters_bottom` exclusively; `self._filters` exists only to satisfy parent invariants.

### Runtime methods

```python
def set_top_dynamic_annotations(
    self,
    annotations: Optional[Dict[Any, Dict[str, Any]]],
    title: Optional[str] = None,
) -> "MirrorPlot":
    """
    Apply per-render annotations to the top spectrum only. Replaces any existing
    top dynamic annotations; bottom is untouched. `annotations` is keyed by the
    value of the interactivity column (peak_id), each entry containing
    {'highlight': bool, 'annotation': str}. `title` (optional) overrides
    `title_top` for this render. Not cached.
    """

def set_bottom_dynamic_annotations(
    self,
    annotations: Optional[Dict[Any, Dict[str, Any]]],
    title: Optional[str] = None,
) -> "MirrorPlot":
    """Same contract, applied to bottom half. `title` overrides `title_bottom`."""

def clear_dynamic_annotations(
    self,
    side: Optional[Literal["top", "bottom"]] = None,
) -> "MirrorPlot":
    """
    side=None  → clears both halves and both dynamic titles
    side="top" → clears only top
    side="bottom" → clears only bottom
    """
```

`from_sequence_views` is **not** provided. Users wire SequenceViews via `__call__` instead.

### `__call__`

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

    If sequence_view_top_key is given, fetches annotations via
    get_component_annotations(sequence_view_top_key) and applies them via
    set_top_dynamic_annotations. Same for bottom. Each side independent.
    """
```

### Bridge integration

`bridge.py` calls `_apply_fresh_annotations` and `_strip_dynamic_columns` on cache hits. MirrorPlot implements both for the pair:

- **`_apply_fresh_annotations(vue_data)`** — Applies current top annotations to `vue_data["plotDataTop"]` and current bottom annotations to `vue_data["plotDataBottom"]`. Returns updated dict with refreshed `_hash` and `_plotConfig`.
- **`_strip_dynamic_columns(vue_data)`** — Drops `_dynamic_highlight` and `_dynamic_annotation` columns from both DataFrames before storing in the runtime cache.

## 5. Vue component contract: `PlotlyMirrorPlot.vue`

### Props

```ts
props: {
  args: { type: Object as PropType<MirrorPlotComponentArgs>, required: true },
  index: { type: Number, required: true },
}
```

### Stores

```ts
const streamlitDataStore = useStreamlitDataStore()
const selectionStore = useSelectionStore()
```

### Data keys consumed from `streamlitDataStore.allDataForDrawing`

| Key | Shape | Notes |
|---|---|---|
| `plotDataTop` | `{ [columnName]: any[] }` | Top spectrum's filtered, optionally annotated rows |
| `plotDataBottom` | `{ [columnName]: any[] }` | Bottom spectrum's filtered, optionally annotated rows. **Y-values are still positive at this boundary; Vue negates them.** |
| `_plotConfig` | `{ xColumn, yColumn, highlightColumn, annotationColumn, interactivityColumns }` | Same shape LinePlot uses; one config drives both halves |

### Plotly figure structure

One figure, two traces, no subplots:

```
trace 0  (top):     x = plotDataTop[xCol],     y =  plotDataTop[yCol]
trace 1  (bottom):  x = plotDataBottom[xCol],  y = -plotDataBottom[yCol]
```

**Layout:**
- `yaxis.range = [-Ymax, +Ymax]` where `Ymax = max(max(|top y|), max(|bottom y|))`
- `yaxis.tickvals` placed at `[-Ymax, -Ymax/2, 0, +Ymax/2, +Ymax]` with `ticktext` showing absolute values
- Horizontal zero-line shape at `y=0` separating the two halves
- Plotly annotations pinned to top-half (paper coords near `y=0.98`) and bottom-half (near `y=0.02`) for `args.titleTop` / `args.titleBottom`. Dynamic titles (set via `set_*_dynamic_annotations(title=…)`) override

### Stick rendering

Vertical line shapes (or scattergl line segments) from `(x, 0)` to `(x, y)`. Per-peak color resolution order (highest precedence first):
1. `selectedColor` if peak's `interactivityColumn` value matches current selection
2. `highlightColor` if peak's `highlightColumn` value is true
3. `topColor` (top trace) or `bottomColor` (bottom trace)

### Click handling — single shared selection

```ts
function onClick(event) {
  const pt = event.points[0]
  const traceIdx = pt.curveNumber
  const sourceData = traceIdx === 0 ? plotDataTop : plotDataBottom
  for (const [identifier, column] of Object.entries(args.interactivity ?? {})) {
    selectionStore.setSelection(identifier, sourceData[column][pt.pointIndex])
  }
}
```

Both traces fill the **same** `interactivity` identifier. Both halves then re-color any peak whose `interactivityColumn` value matches — producing automatic cross-side highlight when the same value appears in both spectra.

### Annotations overlay

Per-peak labels positioned via Plotly pixel coordinates:
- Top half: label above peak tip
- Bottom half: label below peak tip (peak tips at negative y)

Two passes (one per trace) with vertical anchor flipped. Implementation may share helpers with `PlotlyLineplot.vue` only if duplication crosses a meaningful threshold; otherwise inline.

### Re-render triggers

Watch:
- `plotDataTop` (deep) → redraw both traces
- `plotDataBottom` (deep) → redraw both traces
- `selectionStore.counter` → recolor highlighted peak (no full redraw)
- `theme` → restyle background/foreground

### Component args type

Add to `js-component/src/types/component.ts`:

```ts
interface MirrorPlotComponentArgs extends ComponentArgs {
  componentType: 'PlotlyMirrorPlot'
  xColumn: string
  yColumn: string
  highlightColumn?: string
  annotationColumn?: string
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

## 6. Data flow

### Selection state shape

`StateManager.session_state` holds three independent identifiers (example):

```python
{
  "spectrum_top":    "scan_42",     # filters_top    = {"spectrum_top":    "scan_id"}
  "spectrum_bottom": "scan_99",     # filters_bottom = {"spectrum_bottom": "scan_id"}
  "selected_peak":   500.234,       # interactivity  = {"selected_peak":   "mass"}
}
```

The disjoint-name validation guarantees `spectrum_top` ≠ `spectrum_bottom`, so updates to one side never overwrite the other.

### `_prepare_vue_data(state)` algorithm

```
1. Build column projection (shared between both filters):
   [x_column, y_column, highlight_column?, annotation_column?,
    *interactivity column values, *filters_top column values,
    *filters_bottom column values]
   deduped.

2. df_top, hash_top = filter_and_collect_cached(
       data, filters_top, state, columns=projection,
       filter_defaults=filter_defaults_top,
   )

3. df_bottom, hash_bottom = filter_and_collect_cached(
       data, filters_bottom, state, columns=projection,
       filter_defaults=filter_defaults_bottom,
   )

4. If self._top_dynamic_annotations:
       apply to df_top using interactivity column for peak_id lookup
       (sets _dynamic_highlight, _dynamic_annotation columns;
        same algorithm as LinePlot._prepare_vue_data)

5. If self._bottom_dynamic_annotations:
       apply to df_bottom (same algorithm)

6. data_hash = f"{hash_top}_{hash_bottom}"
   if any dynamic annotations active:
       data_hash += "_" + md5(sorted(top_keys) + sorted(bottom_keys))[:8]

7. Build _plotConfig dict; switch column names to "_dynamic_highlight" /
   "_dynamic_annotation" per side independently if dynamic annotations active.

8. return {
       "plotDataTop":    df_top,    # pandas, y still positive
       "plotDataBottom": df_bottom, # pandas, y still positive (Vue negates)
       "_hash":          data_hash,
       "_plotConfig":    plot_config,
   }
```

The Y-negation deliberately doesn't happen here. The cache stores positive values for both halves; reuse on a future render with different dynamic titles or annotations remains valid.

### Cache-hit path (`_apply_fresh_annotations`)

When the bridge detects same filter state but different annotation hash:

```
df_top    = cached_vue_data["plotDataTop"].copy()    # base, no _dynamic_* cols
df_bottom = cached_vue_data["plotDataBottom"].copy()

if self._top_dynamic_annotations:    apply to df_top
if self._bottom_dynamic_annotations: apply to df_bottom

return {
    "plotDataTop":    df_top,
    "plotDataBottom": df_bottom,
    "_hash":          combined_hash_with_annotation_state,
    "_plotConfig":    rebuilt_plot_config,
}
```

### Cache-store path (`_strip_dynamic_columns`)

Inverse — drops `_dynamic_highlight` and `_dynamic_annotation` from both DataFrames before storing in the runtime cache, ensuring future cache hits don't carry stale annotation state.

### Render payload to Vue

```
{
  "components": [
    { "type": "PlotlyMirrorPlot", "args": {...component_args...}, "index": 0 }
  ],
  "selection_store": {
    "spectrum_top":    "scan_42",
    "spectrum_bottom": "scan_99",
    "selected_peak":   500.234,
  },
  "hash": "<combined>",
  "plotDataTop":    <Arrow table>,
  "plotDataBottom": <Arrow table>,
  "_plotConfig":    {...},
}
```

The bridge code already iterates over all keys in `vue_data`; two Arrow tables coexist in one payload without framework changes.

### Why a click does not trigger a Phase 4 redraw

Click → `selectionStore.setSelection("selected_peak", 500.234)` → debounced send to Python → Phase 3 applies it to state → Phase 4: `get_state_dependencies` returns only `["spectrum_top", "spectrum_bottom"]`, so cached `(plotDataTop, plotDataBottom)` matches → cache hit → Phase 5 returns cached data → Vue receives the same hash, doesn't redraw the figure, only re-colors via the `selectionStore.counter` watcher. Same hot-path optimization LinePlot uses.

## 7. Validation & error handling

### Constructor-time (`_validate_mappings`)

| Check | Failure mode |
|---|---|
| Creation mode requires `filters_top` non-empty | `ValueError: "MirrorPlot requires filters_top (creation mode)"` |
| Creation mode requires `filters_bottom` non-empty | `ValueError: "MirrorPlot requires filters_bottom (creation mode)"` |
| `set(filters_top.keys()) & set(filters_bottom.keys()) == ∅` | `ValueError: "filters_top and filters_bottom must use disjoint identifier names; got overlap: {names}"` |
| `x_column`, `y_column` exist in shared schema | Standard schema-validation error (matches LinePlot format) |
| `highlight_column` exists if set | Standard |
| `annotation_column` exists if set | Standard |
| Each filter column (top + bottom) exists | Standard. (Same column referenced from both sides is fine; only identifier *names* must be disjoint.) |
| Each `interactivity` column exists | Standard |

### Runtime soft cases (no error, degraded render)

| Situation | Behavior |
|---|---|
| `state["spectrum_top"]` is `None` and no matching `filter_defaults_top` | Top side renders empty trace; bottom unaffected |
| Same for bottom | Bottom side renders empty trace; top unaffected |
| Filter value resolves to row count of 0 | Empty DataFrame from `filter_and_collect_cached`, empty trace, no warning |
| Both sides empty | Empty mirror figure with axes only; `Ymax` falls back to `1.0` so the figure still draws |
| `set_*_dynamic_annotations` called with peak IDs absent from current data | Silently ignored (matches LinePlot) |
| `filter_defaults_top` keyed by an identifier not in `filters_top` | Silently ignored (matches LinePlot) |

### Reconstruction-from-cache mode

`MirrorPlot(cache_id="x", cache_path=".")` with no `data` and no `filters_*`. `_validate_mappings` skips the per-side filter checks because `self._raw_data is None`. The cached `manifest.json` provides everything via `_restore_cache_config`.

### Deliberately not validated

- Whether the same scan_id is selected on both sides (mirror would just show identical spectra — fine).
- Whether dynamic annotations dicts are well-formed (trust caller, matches LinePlot).
- Whether `topColor` and `bottomColor` are visually distinguishable (cosmetic).

## 8. Testing strategy

### `tests/test_mirrorplot_contract.py`

| Test | What it verifies |
|---|---|
| `test_component_args_includes_componentType` | Returns `"PlotlyMirrorPlot"` |
| `test_component_args_carries_per_side_titles_and_columns` | `titleTop`, `titleBottom`, `xColumn`, `yColumn`, `interactivity`, merged styling |
| `test_get_data_key_returns_plotDataTop` | Primary key contract |
| `test_prepare_vue_data_returns_dict_with_hash` | `_hash` present and is `str` |
| `test_prepare_vue_data_returns_both_dataframes` | Both `plotDataTop` and `plotDataBottom` present, both pandas |
| `test_prepare_vue_data_keeps_y_positive_on_bottom` | Bottom-half y-values are not negated at the Python boundary |
| `test_prepare_vue_data_filters_independently` | Disjoint state values for top/bottom produce disjoint row sets; sentinel test for cross-talk |
| `test_state_dependencies_includes_both_sides` | Returns union of `filters_top.keys()` and `filters_bottom.keys()` |
| `test_state_dependencies_excludes_interactivity` | Interactivity identifiers absent |
| `test_cache_config_roundtrip` | `_get_cache_config` → `_restore_cache_config` preserves every field |

### `tests/test_mirrorplot_validation.py`

| Test | Failure path |
|---|---|
| `test_missing_filters_top_raises` | Creation mode without `filters_top` → `ValueError` |
| `test_missing_filters_bottom_raises` | Same for bottom |
| `test_overlapping_identifier_names_raises` | Top and bottom share an identifier name → `ValueError` mentioning the overlap |
| `test_invalid_x_column_raises` | Same error format LinePlot uses |
| `test_invalid_filter_column_raises` | Filter references non-existent column |
| `test_invalid_interactivity_column_raises` | Interactivity references non-existent column |
| `test_reconstruct_from_cache_only` | After full creation, instantiate with just `cache_id` — succeeds, fields restored |

### `tests/integration/test_mirrorplot.py`

| Test | What it covers |
|---|---|
| `test_two_filter_selections_drive_independent_halves` | Set both selections, render, assert per-side row counts and content |
| `test_shared_click_fills_one_selection_id` | Simulated Vue response with click on top trace → only `interactivity` identifier updated |
| `test_dynamic_annotations_per_side_independent` | `set_top_dynamic_annotations` adds `_dynamic_*` cols to top df only; bottom df untouched, and vice versa |
| `test_clear_dynamic_annotations_side_arg` | `clear(side="top")` leaves bottom intact; `clear()` (no arg) clears both |
| `test_cache_hit_reuses_data_and_reapplies_annotations` | Two renders with same filter state but different annotations: second hits cache, `_apply_fresh_annotations` produces fresh `_dynamic_*` columns on the right side |
| `test_click_does_not_invalidate_data_cache` | Render, click, render — second render is a cache hit |
| `test_subprocess_preprocessing_via_data_path` | `data_path=` exercises spawn-based preprocess; reconstruction afterward works |

### Fixtures

Reuse `sample_lineplot_data` if it carries `scan_id`, `mass`, `intensity`, `peak_id` with ≥ 2 distinct scans. Otherwise add `sample_mirror_data` to `tests/conftest.py` with `scan_id ∈ {"A", "B"}`, distinct mass/intensity per scan, and unique `peak_id` per row.

### Test patterns

- Validation tests use `pytest.raises(ValueError, match=…)` to assert the *shape* of the error, not exact wording.
- Integration tests construct components inline (no module-level fixtures) so each test gets a fresh cache dir from `temp_cache_dir`.
- Contract tests parametrize over `(filters_top, filters_bottom, expected_*)` where it tightens repetition.

## 9. Out of scope

The following are intentionally not in scope for this design and may be addressed in follow-ups:

- A `MirrorPlot.from_sequence_views` classmethod (users wire SequenceViews through `__call__` arguments instead).
- Independent (non-symmetric) Y-axis scaling per half.
- Click semantics that pair-match peaks across spectra by m/z tolerance (current behavior: exact value match only, which is the natural outcome of a single shared `interactivity` identifier).
- Diff-highlighting of peaks present on one side but absent on the other.
- Lifting `PlotlyLineplot.vue`'s annotation overlay into a shared composable (acceptable inline duplication for v1).
