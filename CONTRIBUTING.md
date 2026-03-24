# Contributing to OpenMS-Insight

This guide is for developers adding **new visualization components** to OpenMS-Insight. It covers the setup, the abstractions you need to understand, a detailed walkthrough of building a component, caching, and testing.

Technologies used are Python, TypeScript, Streamlit, and Vue 3.

---

## Table of Contents

- [Getting Started](#getting-started)
- [How Components Work](#how-components-work)
- [Adding a New Component](#adding-a-new-component)
- [Caching](#caching)
- [Testing](#testing)

---

## Getting Started

### Prerequisites

- Python 3.9+
- Node.js (for building/developing the Vue frontend)
- A working Streamlit installation

### Install for Development

```bash
# Python package with dev dependencies
pip install -e ".[dev]"

# Vue frontend
cd js-component
npm install
```

### Development Workflow (Hot Reload)

Run two terminals side by side:

```bash
# Terminal 1: Vite dev server (port 5173)
cd js-component && npm run dev

# Terminal 2: Streamlit with dev mode
cd ../example_app
SVC_DEV_MODE=true SVC_DEV_URL=http://localhost:5173 streamlit run app.py
```

Changes to Vue files trigger instant hot reload. Python changes require a Streamlit rerun.

### Debug Modes

```bash
SVC_DEBUG_HASH=true streamlit run app.py    # Hash tracking: debug data sync issues
SVC_DEBUG_STATE=true streamlit run app.py   # State tracking: debug selection/pagination
```

### Linting, Formatting, and Type Checking

```bash
# Python
ruff check .               # Lint
ruff format .              # Format
mypy openms_insight        # Type check

# Vue/TypeScript
cd js-component
npm run type-check         # vue-tsc
npm run lint               # ESLint with auto-fix
npm run format             # Prettier
```

### Running Tests

```bash
pytest                                # All tests (coverage enabled by default)
pytest tests/test_foo.py::test_bar    # Single test
pytest -k "heatmap"                   # Tests matching pattern
```

### Production Build

```bash
cd js-component && npm run build && cd ..
mkdir -p openms_insight/js-component
cp -r js-component/dist openms_insight/js-component/
python -m build
```

---

## How Components Work

OpenMS-Insight components have a Python side that preprocesses data and a Vue side that renders it. Components communicate with each other through **shared identifiers** managed by a `StateManager`.

### Filters (Input)

A dict mapping `{identifier: column}`. When `StateManager` has a selection for that identifier, the component filters its data where `column` equals the selected value.

```python
# This component shows only rows where scan_id matches the selected "spectrum"
LinePlot(filters={"spectrum": "scan_id"}, ...)
```

A component can have multiple filters from different identifiers — each one narrows the data further.

### Interactivity (Output + Highlighting)

A dict mapping `{identifier: column}`. Interactivity serves **two purposes**:

1. **Setting selections on click (output)**: When the user clicks a row or point, the component sets `identifier` in `StateManager` to the clicked item's `column` value.
2. **Receiving and highlighting the current selection (input)**: The component reads the current value of `identifier` from `StateManager` and visually highlights the matching item. This happens even when a *different* component set that selection.

```python
# Clicking a row in this table sets "spectrum" to that row's scan_id.
# If another component already set "spectrum", this table highlights the matching row.
Table(interactivity={"spectrum": "scan_id"}, ...)
```

How highlighting works in each component:

| Component | Click behavior | Highlight behavior |
|-----------|---------------|-------------------|
| **LinePlot** | Finds nearest peak to click position, sets selection to that peak's interactivity column value | Draws the selected peak in a separate Plotly trace with `selectedColor` (gold by default), rendered on top. If the peak has an annotation box, the box also turns gold. Auto-zooms if the selected annotation is hidden. |
| **Table** | `onRowClick()` immediately selects the row visually, then updates the selection store | `syncSelectionFromStore()` reads the selection, finds the matching row by interactivity column value, calls `row.select()` and `row.scrollTo()`. For paginated tables, navigates to the correct page first. |
| **Heatmap** | Uses `usePlotlyScatter` composable: finds the clicked point by `pointIndex` in the data array, sets selection for each interactivity mapping | No per-point highlighting (scatter plots with thousands of points don't highlight individual selections). |
| **VolcanoPlot** | Same as Heatmap (uses `usePlotlyScatter` composable) | No per-point highlighting. |

**Bidirectional linking**: A component can have the *same* identifier in both `filters` and `interactivity`. In this case, the identifier filters the component's data AND the component can set/highlight that selection. This is less common than having separate identifiers for each role.

### filter_defaults

A dict mapping `{identifier: default_value}`. Fallback values when no selection exists yet. **Without this, components with filters render empty on first load** (before any selection is made).

```python
# Show rows where id_idx == -1 when no identification is selected
Table(
    filters={"identification": "id_idx"},
    filter_defaults={"identification": -1},
    ...
)
```

### Cross-Component Linking

This is the core pattern. One component's click output becomes another component's filter input, with `StateManager` as the broker:

```
┌────────────────────────────┐   ┌─────────────────────────────┐
│  Table                     │   │  LinePlot                   │
│                            │   │                             │
│  interactivity={           │   │  filters={                  │
│    "spectrum": "scan_id"   │   │    "spectrum": "scan_id"    │
│  }                         │   │  }                          │
│                            │   │                             │
│  OUTPUT: on click, sets    │   │  INPUT: filters data where  │
│  "spectrum" to clicked     │   │  scan_id == selected value  │
│  row's scan_id value       │   │                             │
└──────────┬─────────────────┘   └──────────────▲──────────────┘
           │                                    │
           │  1. User clicks row                │  3. LinePlot sees
           │     where scan_id=42               │     spectrum=42,
           │                                    │     filters peaks
           ▼                                    │
┌───────────────────────────────────────────────┴──────────────┐
│                       StateManager                           │
│                                                              │
│   selections: { "spectrum": 42 }                             │
│                                                              │
│   2. Table click ──► set_selection("spectrum", 42)           │
│      ──► st.rerun() ──► All components re-render             │
└──────────────────────────────────────────────────────────────┘
```

`LinePlot` participates in the same linking flow in both directions. `filters={"spectrum": "scan_id"}` decides which spectrum is shown, while `interactivity` controls how peak-level state is shared. Clicking a peak selects the nearest x-position, writes the mapped interactivity value into `selectionStore`, and Vue reads that same identifier back to find the matching row through `interactivity_<column>` and render it as the selected peak, even if another component set it first.

In linked spectrum views, the component highlights peaks whose IDs appear in the current annotation set for the active context by matching those IDs against the plot's interactivity column, and then renders the currently selected matching peak on top.

### cache_id

A mandatory unique string identifier for on-disk caching. Creates a folder at `{cache_path}/{cache_id}/`. Must be stable across reruns but unique per logical component instance.

### data_path vs data

Two ways to provide input data:

- **`data_path`** (string path to parquet): Runs preprocessing in a **spawned subprocess** so memory is fully released after caching. **Preferred for large datasets** (e.g., heatmaps with millions of points).
- **`data`** (Polars LazyFrame): Runs preprocessing **in-process**. Simpler but memory allocators may retain freed memory.

### StateManager

The centralized broker for cross-component selection state. It holds a flat dict of `{identifier: value}` selections in Streamlit's `session_state`.

As a component author, you interact with `StateManager` indirectly:

- Your `filters` dict tells the framework which selections to read
- Your `interactivity` dict tells the framework which selections to write on user clicks
- In `_prepare_vue_data(state)`, you receive the current state dict and use it to filter your data
- On the Vue side, you call `selectionStore.updateSelection(identifier, value)` when the user clicks

You do not need to manage counters, conflict resolution, or session IDs — the framework handles all of that.

---

## Adding a New Component

This is the main task when contributing. A component has two halves: a Python class that preprocesses data and prepares it for rendering, and a Vue component that displays it in the browser.

### Step 1: Create the Python Class

Create a new file in `openms_insight/components/`, for example `mycomponent.py`:

```python
"""My visualization component."""

from typing import Any, Dict, Optional
import polars as pl

from ..core.base import BaseComponent
from ..core.registry import register_component
from ..preprocessing.filtering import filter_and_collect_cached


@register_component("mycomponent")
class MyComponent(BaseComponent):
    _component_type: str = "mycomponent"

    def __init__(
        self,
        cache_id: str,
        data: Optional[pl.LazyFrame] = None,
        data_path: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
        filter_defaults: Optional[Dict[str, Any]] = None,
        interactivity: Optional[Dict[str, str]] = None,
        cache_path: str = ".",
        regenerate_cache: bool = False,
        # Component-specific parameters:
        x_column: str = "x",
        y_column: str = "y",
        title: Optional[str] = None,
        **kwargs,
    ):
        # Set component attributes BEFORE calling super().__init__()
        # because super().__init__() triggers _preprocess()
        self._x_column = x_column
        self._y_column = y_column
        self._title = title

        super().__init__(
            cache_id=cache_id,
            data=data,
            data_path=data_path,
            filters=filters,
            filter_defaults=filter_defaults,
            interactivity=interactivity,
            cache_path=cache_path,
            regenerate_cache=regenerate_cache,
            # Pass component-specific params for subprocess recreation
            x_column=x_column,
            y_column=y_column,
            title=title,
            **kwargs,
        )
```

**Important**: Set all component-specific attributes before `super().__init__()`. The base class calls `_preprocess()` during init, so your attributes must already exist.

### Step 2: Implement the 7 Required Abstract Methods

Every component must implement these methods:

#### `_preprocess()`

Populate `self._preprocessed_data` with data ready to be saved as parquet. This runs once and the result is cached to disk.

```python
def _preprocess(self) -> None:
    data = self._raw_data

    # Sort by filter columns for efficient predicate pushdown
    if self._filters:
        sort_columns = list(self._filters.values())
        data = data.sort(sort_columns)

    # Store as LazyFrame — base class uses sink_parquet() to stream to disk
    self._preprocessed_data["data"] = data
```

Key points:
- `self._raw_data` contains the user's input LazyFrame
- Store results in `self._preprocessed_data` dict (keys become parquet filenames)
- LazyFrames are streamed to disk via `sink_parquet()`, DataFrames via `write_parquet()`
- JSON-serializable values (strings, numbers, dicts) are stored in the manifest
- Sorting by filter columns enables predicate pushdown (Polars can skip row groups)

#### `_get_vue_component_name()`

Return the string name of the Vue component to render. This must match exactly what you register in `App.vue`.

```python
def _get_vue_component_name(self) -> str:
    return "MyComponent"
```

#### `_get_data_key()`

Return the key name for the primary data in the Vue payload. Vue receives data as a dict — this is the key it looks for.

```python
def _get_data_key(self) -> str:
    return "myData"
```

#### `_prepare_vue_data(state)`

This is the most important method. It runs on every Streamlit rerender, filters your cached data by the current selection state, and returns a dict for Vue.

```python
def _prepare_vue_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
    # Get cached data (LazyFrame from disk)
    data = self._preprocessed_data.get("data")
    if isinstance(data, pl.DataFrame):
        data = data.lazy()

    # Build list of columns to send to Vue
    columns = [self._x_column, self._y_column]
    if self._interactivity:
        for col in self._interactivity.values():
            if col not in columns:
                columns.append(col)
    if self._filters:
        for col in self._filters.values():
            if col not in columns:
                columns.append(col)

    # Filter by selection state and convert to pandas for Arrow serialization
    df_pandas, data_hash = filter_and_collect_cached(
        data,
        self._filters,
        state,
        columns=columns,
        filter_defaults=self._filter_defaults,
    )

    return {
        "myData": df_pandas,    # Key must match _get_data_key()
        "_hash": data_hash,      # REQUIRED: used for change detection
    }
```

Key points:
- `state` is a dict of `{identifier: value}` from `StateManager`
- Use `filter_and_collect_cached()` from `preprocessing/filtering.py` to filter and convert data — it handles selection matching, column projection, and hash computation
- Always include `"_hash"` in the return value — it's used for change detection to avoid resending identical data
- Return pandas DataFrames for Arrow serialization to Vue
- Only select the columns Vue actually needs (projection pushdown)
- **Include interactivity columns** in the projection. Vue needs these columns to (a) look up the value to set on click, and (b) find the currently selected item for highlighting. Without them, click-to-select and highlighting both break.

#### `_get_component_args()`

Return a config dict that is sent to Vue alongside the data. This includes styling, column names, labels, and other UI configuration. It must include `"componentType"`.

```python
def _get_component_args(self) -> Dict[str, Any]:
    return {
        "componentType": self._get_vue_component_name(),
        "title": self._title or "",
        "xColumn": self._x_column,
        "yColumn": self._y_column,
        "interactivity": self._interactivity or {},
    }
```

Key points:
- `"componentType"` is required — it's how `App.vue` routes to the correct Vue component
- Include everything the Vue side needs for rendering (column mappings, styling, labels)
- This runs every rerender but is cheap since it's just building a dict

#### `_get_cache_config()`

Return a dict of configuration that affects the preprocessed data. Changes to any value here invalidate the cache.

```python
def _get_cache_config(self) -> Dict[str, Any]:
    return {
        "x_column": self._x_column,
        "y_column": self._y_column,
    }
```

**Include**: Anything that changes what data is stored in parquet — column selections, sort orders, data transformations, downsampling parameters.

**Exclude**: Styling, colors, UI labels, or anything only used at render time. Including these causes unnecessary cache rebuilds. For example, `title` and `styling` dicts should generally be excluded unless they affect preprocessing.

> **Note**: Looking at existing components, some (like LinePlot) include title/styling in cache config for simplicity even though they don't strictly affect preprocessing. This works but means changing a title forces a cache rebuild. For components with expensive preprocessing, keep cache config minimal.

#### `_restore_cache_config(config)`

Restore your component attributes from a cached config dict. Called when a component is loaded from an existing cache (reconstruction mode).

```python
def _restore_cache_config(self, config: Dict[str, Any]) -> None:
    self._x_column = config.get("x_column", "x")
    self._y_column = config.get("y_column", "y")
```

Key points:
- Every key you put in `_get_cache_config()` must be restored here
- Provide sensible defaults for `.get()` calls (backward compatibility if keys were added later)
- Also initialize any non-cached attributes (e.g., `self._dynamic_annotations = None`)

### Step 3: Optional Overrides

These base class methods have default behavior but can be overridden:

| Method | Default | Override when |
|--------|---------|---------------|
| `get_initial_selection(state)` | Returns `None` | Your component should pre-select a row/point on first load (e.g., Table selects the first row) |
| `get_state_dependencies()` | Returns filter identifiers | Your component has state dependencies beyond filters (e.g., pagination, zoom state) |
| `_get_row_group_size()` | Returns 50,000 | You need different parquet row group sizes for predicate pushdown tuning |
| `_validate_mappings()` | Validates filter/interactivity columns exist | You have additional required columns to validate (call `super()` first) |

### Step 4: Export the Component

Add your component to `openms_insight/__init__.py`:

```python
from .components.mycomponent import MyComponent

__all__ = [
    ...
    "MyComponent",
]
```

### Step 5: Create the Vue Component

Create a new file in `js-component/src/components/`, for example `my/MyComponent.vue`.

Your Vue component receives data and config via these stores and props. It needs to handle **both directions** of interactivity: setting selections on click, and highlighting the current selection (which may have been set by another component).

```vue
<template>
  <div ref="container">
    <!-- Your visualization here -->
  </div>
</template>

<script lang="ts">
import { defineComponent, watch, computed, ref } from 'vue'
import { useStreamlitDataStore } from '@/stores/streamlit-data'
import { useSelectionStore } from '@/stores/selection'

export default defineComponent({
  name: 'MyComponent',
  props: {
    args: { type: Object, required: true },
    index: { type: Number, required: true },
  },
  setup(props) {
    const streamlitDataStore = useStreamlitDataStore()
    const selectionStore = useSelectionStore()

    // Access component config from props.args (from _get_component_args())
    const title = computed(() => props.args.title || '')
    const xColumn = computed(() => props.args.xColumn || 'x')
    const yColumn = computed(() => props.args.yColumn || 'y')

    // Access data from the streamlit data store
    // The key matches what _get_data_key() returns
    const data = computed(() => {
      const allData = streamlitDataStore.allDataForDrawing
      return allData?.myData || null
    })

    // --- HIGHLIGHTING: Read the current selection from the store ---
    // Look up the interactivity column values to find which item is selected.
    // This computed property re-evaluates when the selection store changes,
    // so highlighting updates even when a different component set the selection.
    const selectedItemIndex = computed(() => {
      const interactivity = props.args.interactivity || {}
      if (!data.value) return undefined

      for (const [identifier, column] of Object.entries(interactivity)) {
        const selectedValue = selectionStore.$state[identifier]
        if (selectedValue == null) continue

        // Find the item with the matching value in the interactivity column
        const columnValues = data.value[column as string] as unknown[]
        if (columnValues) {
          const idx = columnValues.indexOf(selectedValue)
          if (idx >= 0) return idx
        }
      }
      return undefined
    })

    // Watch for data changes and render
    watch(data, (newData) => {
      if (newData) renderVisualization(newData)
    }, { immediate: true })

    // Re-render when selection changes (to update highlighting)
    watch(() => selectionStore.$state, () => {
      if (data.value) renderVisualization(data.value)
    }, { deep: true })

    // --- CLICK: Set selection on user interaction ---
    function onItemClicked(itemIndex: number) {
      const interactivity = props.args.interactivity || {}
      if (!data.value) return

      for (const [identifier, column] of Object.entries(interactivity)) {
        const value = data.value[column as string]?.[itemIndex]
        if (value !== undefined) {
          selectionStore.updateSelection(identifier, value)
        }
      }
    }

    function renderVisualization(rawData: unknown) {
      // Parse Arrow data and render your visualization.
      // Use selectedItemIndex.value to apply highlight styling
      // (e.g., different color, border, or separate trace for the selected item).
    }

    return { title, data, selectedItemIndex, onItemClicked }
  },
})
</script>

<style scoped>
/* Component-specific styles */
</style>
```

Key points:
- Data arrives via `useStreamlitDataStore()` — access it with the key from `_get_data_key()`
- Config arrives via `props.args` — the dict from `_get_component_args()`
- **Click-to-select**: Call `selectionStore.updateSelection(identifier, value)` when the user clicks an item
- **Highlighting**: Read from `selectionStore.$state[identifier]` to find the current selection, match it against the interactivity column in your data, and apply visual emphasis (separate trace, row highlight, etc.). Watch `selectionStore.$state` to re-render when the selection changes.
- The `interactivity` dict from `props.args` tells you both what to write on click (identifier + column) and what to read for highlighting (same identifier + column)
- Deep clone state before `Streamlit.setComponentValue()` (App.vue handles this for selections, but if you send custom state, use `JSON.parse(JSON.stringify(...))`)
- Echo the data hash back to Python (App.vue handles this automatically via the `streamlit-data` store)

**Highlighting patterns in existing components** (study these for reference):

- **LinePlot** (`PlotlyLineplot.vue`): Computes `selectedPeakIndex` from the selection store, splits data into three Plotly traces (unhighlighted, highlighted, selected), and draws the selected peak in a gold trace on top. Annotation boxes for the selected peak also get gold coloring. Re-renders on `selectionStore.$state` changes.
- **Table** (`TabulatorTable.vue`): `syncSelectionFromStore()` reads the selection, finds the matching row via interactivity column, and calls Tabulator's `row.select()` + `row.scrollTo()`. For server-side pagination, navigates to the correct page before selecting.
- **Heatmap/VolcanoPlot**: Use the `usePlotlyScatter` composable for click handling only; no per-point highlighting (impractical for large scatter plots).

### Step 6: Define TypeScript Interfaces

Add your component's type definition in `js-component/src/types/component.ts`:

```typescript
export interface MyComponentArgs extends BaseComponentArgs {
  componentType: 'MyComponent'
  title?: string
  xColumn: string
  yColumn: string
  interactivity?: InteractivityMapping
  height?: number
}
```

Then add it to the `ComponentArgs` union type at the bottom of the file.

### Step 7: Register in App.vue

Import your component and add it to the `currentComponent` computed switch in `js-component/src/App.vue`:

```typescript
import MyComponent from './components/my/MyComponent.vue'

// In the components object:
components: {
  ...,
  MyComponent,
},

// In the currentComponent computed:
case 'MyComponent':
  return MyComponent
```

### Registration Flow

This diagram shows how Python's component name connects to the Vue component:

```
 PYTHON SIDE                         VUE SIDE

 @register_component("mycomponent")  App.vue:
 class MyComponent(BaseComponent):   switch(componentType) {
     ...                               case "MyComponent":
                                          return MyComponent
 _get_vue_component_name()             ...
   → "MyComponent"                   }

 BRIDGE: render_component()
 ┌────────────────────┐    ┌──────────────────┐    ┌──────────┐
 │ component.         │    │ componentArgs =  │    │ App.vue  │
 │ _get_vue_component │───►│ { componentType: │───►│ switch   │
 │ _name()            │    │   "MyComponent"  │    │ routes   │
 │                    │    │   ...             │    │ to Vue   │
 │ Returns string     │    │ }                │    │ component│
 └────────────────────┘    └──────────────────┘    └──────────┘
```

### Vue Conventions

- **Arrow data parsing**: Column-wise for plots (`{x_values: [...], y_values: [...]}`), row-wise for tables (`[{id: 1, ...}, ...]`)
- **UI framework**: Vuetify 3 for menus, buttons, dialogs; MDI icons (`mdi-filter`, `mdi-download`, etc.)
- **Theming**: Read theme from `streamlitDataStore.theme` and apply to Plotly layouts (`paper_bgcolor`, `plot_bgcolor`, `font.color`)
- **Scoped CSS**: Use `<style scoped>` for component isolation
- **Types**: Define component-specific interfaces in `js-component/src/types/component.ts`

### Quick Reference: Existing Components

Study these to understand common patterns:

| Component | Python file | Vue file | Good example of |
|-----------|------------|----------|-----------------|
| **LinePlot** | `components/lineplot.py` | `components/plotly/PlotlyLineplot.vue` | Simple Plotly component, filter + interactivity, dynamic annotations |
| **VolcanoPlot** | `components/volcanoplot.py` | `components/plotly/PlotlyVolcano.vue` | Render-time parameters (thresholds via `__call__`), computed columns in preprocessing |
| **Table** | `components/table.py` | `components/tabulator/TabulatorTable.vue` | Server-side pagination, `get_initial_selection()`, `get_state_dependencies()` |
| **Heatmap** | `components/heatmap.py` | `components/plotly/PlotlyHeatmap.vue` | Multi-resolution downsampling, large dataset handling |
| **SequenceView** | `components/sequenceview.py` | `components/sequence/SequenceView.vue` | Multi-data-key component (sequences + peaks), linked annotations |

### Key Files Reference

| File | What it does |
|------|-------------|
| `core/base.py` | `BaseComponent` ABC — your class inherits from this |
| `core/registry.py` | `@register_component()` decorator |
| `core/state.py` | `StateManager` (you rarely interact with it directly) |
| `preprocessing/filtering.py` | `filter_and_collect_cached()`, `compute_dataframe_hash()`, type optimization |
| `preprocessing/compression.py` | 2D downsampling for scatter/heatmap components |
| `rendering/bridge.py` | `render_component()` — the bridge between Python and Vue |
| `js-component/src/App.vue` | Component router — register new Vue components here |
| `js-component/src/stores/streamlit-data.ts` | Arrow data reception in Vue |
| `js-component/src/stores/selection.ts` | Selection state store (Pinia) |
| `js-component/src/types/component.ts` | TypeScript interfaces for component args |

---

## Caching

### What Component Authors Need to Know

Components preprocess data once and cache the result to Parquet on disk. Subsequent loads read from cache. As a component author, you control cache behavior through two methods:

#### `_get_cache_config()` — What Invalidates the Cache

Return a dict of parameters that affect the preprocessed data. The base class hashes this dict (along with `filters` and `interactivity`) to compute a config hash. If the hash changes, the cache is rebuilt.

```python
def _get_cache_config(self) -> Dict[str, Any]:
    return {
        "x_column": self._x_column,       # YES: changes which columns are stored
        "downsample_n": self._downsample,  # YES: changes data content
        # "title": self._title,            # NO: only affects rendering
        # "styling": self._styling,        # NO: only affects rendering
    }
```

#### `_restore_cache_config(config)` — Restoring from Cache

When a component is reconstructed from cache (no data provided), this method restores your attributes from the saved config. Every key in `_get_cache_config()` must be restored here.

```python
def _restore_cache_config(self, config: Dict[str, Any]) -> None:
    self._x_column = config.get("x_column", "x")
    self._downsample = config.get("downsample_n", 10000)
```

### Two Initialization Modes

Components support creation mode (data provided, builds cache) and reconstruction mode (no data, loads from existing cache):

```python
# Creation mode
comp = MyComponent(cache_id="c1", data_path="data.parquet", filters={...})

# Reconstruction mode — only cache_id and cache_path needed
comp = MyComponent(cache_id="c1", cache_path=".")
# All config (filters, interactivity, component-specific) is restored from manifest
# Any config parameters passed here are IGNORED
```

### When to Increment CACHE_VERSION

The global `CACHE_VERSION` in `core/base.py` (currently 3) invalidates **all** existing caches when incremented. Increment it when:
- The manifest structure changes (new required fields)
- The parquet schema changes (different columns, types)
- Type optimization logic changes (e.g., how Float64/Int64 downcasting works)

This is a project-wide change, not something you do for a single component.

### Type Optimization

At cache save time, the base class automatically downcasts types to reduce Arrow transfer overhead:
- **Float64 to Float32**: Always applied (sufficient precision for visualization)
- **Int64 to Int32**: Applied when values fit (avoids JavaScript BigInt overhead)

You do not need to handle this yourself — it happens automatically in `_save_to_cache()`.

### Parquet Details

- **Compression**: zstd (reduces disk I/O)
- **Row groups**: 50k rows by default (override `_get_row_group_size()` if needed)
- **Predicate pushdown**: Sorting by filter columns during `_preprocess()` clusters filter values together, enabling Polars to skip irrelevant row groups during filtered reads

---

## Testing

### Organization

```
tests/
├── conftest.py                        # Shared fixtures
├── test_*_contract.py                 # Python ↔ Vue interface contracts
├── test_cache_*.py                    # Caching and reconstruction
├── test_streamlit_construction.py     # Component construction
├── test_<component>.py                # Component-specific behavior
└── integration/
    ├── test_cross_component_*.py      # Multi-component selection flows
    ├── test_tabulator_*.py            # Table pagination/filtering/sorting
    └── test_heatmap_*.py              # Heatmap rendering
```

### Key Fixtures (conftest.py)

- **`mock_streamlit`** — patches `st.session_state` so components work without a running Streamlit server
- **`temp_cache_dir`** / **`tmp_path`** — isolated cache directories per test
- **Sample data fixtures** — pre-built LazyFrames for each component type (`sample_table_data`, `sample_heatmap_data`, etc.)

### Writing Tests for a New Component

1. **Add a sample data fixture** to `conftest.py`:

```python
@pytest.fixture
def sample_mycomponent_data() -> pl.LazyFrame:
    return pl.LazyFrame({
        "x": [1.0, 2.0, 3.0],
        "y": [10.0, 20.0, 30.0],
        "group_id": [1, 1, 2],
    })
```

2. **Create contract tests** in `test_mycomponent_contract.py` verifying the Python-Vue interface:

```python
class TestMyComponentContract:
    def test_component_args_keys(self, mock_streamlit, sample_mycomponent_data, tmp_path):
        comp = MyComponent(
            cache_id="test", data=sample_mycomponent_data,
            cache_path=str(tmp_path), x_column="x", y_column="y",
        )
        args = comp._get_component_args()
        assert "componentType" in args
        assert args["componentType"] == "MyComponent"
        assert "xColumn" in args

    def test_prepare_vue_data_structure(self, mock_streamlit, sample_mycomponent_data, tmp_path):
        comp = MyComponent(
            cache_id="test", data=sample_mycomponent_data,
            cache_path=str(tmp_path), x_column="x", y_column="y",
        )
        vue_data = comp._prepare_vue_data({})
        assert "myData" in vue_data
        assert "_hash" in vue_data

    def test_cache_config_round_trips(self, mock_streamlit, sample_mycomponent_data, tmp_path):
        comp = MyComponent(
            cache_id="test", data=sample_mycomponent_data,
            cache_path=str(tmp_path), x_column="custom_x", y_column="custom_y",
        )
        config = comp._get_cache_config()
        assert config["x_column"] == "custom_x"

        # Verify round-trip
        comp2 = MyComponent(cache_id="test", cache_path=str(tmp_path))
        assert comp2._x_column == "custom_x"
```

3. **Test cache reconstruction**: Verify the component can be rebuilt from cache alone:

```python
def test_reconstruction(self, mock_streamlit, sample_mycomponent_data, tmp_path):
    # Create and cache
    MyComponent(
        cache_id="test", data=sample_mycomponent_data,
        cache_path=str(tmp_path), x_column="x", y_column="y",
        filters={"group": "group_id"},
    )

    # Reconstruct from cache only
    comp = MyComponent(cache_id="test", cache_path=str(tmp_path))
    assert comp._filters == {"group": "group_id"}
    assert comp._x_column == "x"
```

4. **Run Vue type checking** after any changes to Vue components or TypeScript interfaces:

```bash
cd js-component && npm run type-check
```

---