/**
 * Store for Streamlit render data.
 *
 * Handles receiving data from Python, parsing Arrow tables, and storing
 * component configuration and data.
 */

import { defineStore } from 'pinia'
import type { RenderData, Theme } from 'streamlit-component-lib'
import { ArrowTable } from 'streamlit-component-lib'
import { Vector } from 'apache-arrow'
import { useSelectionStore } from '@/stores/selection'
import type { ComponentLayout, StreamlitData } from '@/types/component'

export const useStreamlitDataStore = defineStore('streamlit-data', {
  state: () => ({
    renderData: null as RenderData | null,
    dataForDrawing: {} as Record<string, unknown>,
    hash: '' as string,
    // Annotations set by components like SequenceView to share with Python
    // These are sent back to Python alongside selection state
    annotations: null as { peak_id: number[]; highlight_color: string[]; annotation: string[] } | null,
    // Flag to request data from Python when cache is empty after page navigation
    requestData: false,
  }),

  getters: {
    args: (state): StreamlitData | undefined => state.renderData?.args,

    components(): ComponentLayout[][] | undefined {
      return this.args?.components
    },

    allDataForDrawing: (state) => state.dataForDrawing,

    theme: (state): Theme | undefined => state.renderData?.theme,
  },

  actions: {
    updateRenderData(newData: RenderData) {
      const selectionStore = useSelectionStore()

      // Extract selection store data before processing
      const pythonState = newData.args.selection_store as Record<string, unknown> | undefined
      const newHash = newData.args.hash as string | undefined
      const dataChanged = newData.args.dataChanged as boolean | undefined

      // Clean up before re-assignment
      delete newData.args.selection_store
      delete newData.args.hash
      delete newData.args.dataChanged

      console.log('[StreamlitDataStore] ===== updateRenderData START =====', {
        timestamp: Date.now(),
        dataChanged,
        oldHash: this.hash?.substring(0, 8),
        newHash: newHash?.substring(0, 8),
        hasPagination: !!(newData.args as any)._pagination,
        paginationPage: ((newData.args as any)._pagination as any)?.page,
        hasTableData: !!(newData.args as any).tableData,
        pythonStateCounter: pythonState?.counter,
        pythonSelectionCounter: pythonState?.selection_counter,
        pythonPaginationCounter: pythonState?.pagination_counter,
        pythonStateKeys: pythonState ? Object.keys(pythonState) : [],
      })

      // IMPORTANT: Update selection store FIRST, before hash update
      // This ensures that when the hash change triggers watchers (which call sendStateToStreamlit),
      // all components see the correct counter value from Python. This prevents race conditions
      // where components with stale counters trigger spurious reruns that lose pagination state.
      if (pythonState) {
        // Support both new separate counters and legacy single counter
        const pythonSelectionCounter = (pythonState.selection_counter as number) ?? (pythonState.counter as number) ?? 0
        const pythonPaginationCounter = (pythonState.pagination_counter as number) ?? (pythonState.counter as number) ?? 0
        const vueSelectionCounter = (selectionStore.$state.selection_counter as number) ?? (selectionStore.$state.counter as number) ?? 0
        const vuePaginationCounter = (selectionStore.$state.pagination_counter as number) ?? (selectionStore.$state.counter as number) ?? 0

        selectionStore.$patch((state) => {
          // Clear state if different session
          if (pythonState.id !== state.id) {
            for (const key in state) {
              (state as Record<string, unknown>)[key] = undefined
            }
            Object.assign(state, pythonState)
          } else {
            // Per-key conflict resolution using appropriate counter
            for (const key in pythonState) {
              const isPagination = key.endsWith('_page')
              const pythonCounter = isPagination ? pythonPaginationCounter : pythonSelectionCounter
              const vueCounter = isPagination ? vuePaginationCounter : vueSelectionCounter

              // Accept if:
              // 1. New key or undefined value
              // 2. Python has equal/newer counter for this type
              // Counter-based resolution ensures Vue's rapid page clicks aren't overwritten
              // by stale Python state that hasn't caught up yet.
              const shouldAccept =
                !(key in state) ||
                state[key] === undefined ||
                pythonCounter >= vueCounter

              console.log(`[StreamlitDataStore] State key "${key}":`, {
                isPagination,
                pythonCounter,
                vueCounter,
                dataChanged,
                keyInState: key in state,
                currentValue: state[key],
                pythonValue: pythonState[key],
                shouldAccept,
              })

              if (shouldAccept) {
                (state as Record<string, unknown>)[key] = pythonState[key]
              }
            }
          }
        })
      }

      // Only process data if Python says it changed (optimization to avoid re-parsing same data)
      if (dataChanged && newHash) {
        // Store render data
        this.renderData = newData

        // Parse Arrow tables to native JS objects BEFORE updating hash
        // This ensures watchers see the new data when they fire on hash change
        // IMPORTANT: Merge new data instead of replacing, so multiple components
        // can each contribute their data (tableData, heatmapData, plotData, etc.)
        const data = newData.args as StreamlitData
        Object.entries(data).forEach(([key, value]) => {
          if (value instanceof ArrowTable) {
            // Use column-based parsing for plot data (LinePlot's `plotData`,
            // MirrorPlot's `plotDataTop`/`plotDataBottom`) — more efficient for plotting.
            // Use row-based parsing for tableData (needed for Tabulator) and
            // other ArrowTable payloads.
            if (key.startsWith('plotData')) {
              const parsed = this.parseArrowTableToColumns(value)
              console.log(`[StreamlitDataStore] Parsed ${key} to columns:`, {
                columns: Object.keys(parsed),
                rowCount: Object.values(parsed)[0]?.length ?? 0,
              })
              this.dataForDrawing[key] = parsed
            } else {
              const parsed = this.parseArrowTable(value)
              console.log(`[StreamlitDataStore] Parsed ${key}:`, { rowCount: parsed.length })
              this.dataForDrawing[key] = parsed
            }
          } else {
            this.dataForDrawing[key] = value
          }
        })

        // Explicitly copy pagination metadata for streaming tables
        // These are sent alongside tableData for server-side pagination
        if (data._pagination !== undefined) {
          console.log('[StreamlitDataStore] Updating _pagination:', {
            oldPage: (this.dataForDrawing._pagination as any)?.page,
            newPage: (data._pagination as any)?.page,
            newPagination: data._pagination,
          })
          this.dataForDrawing._pagination = data._pagination
        }
        if (data._navigate_to_page !== undefined) {
          console.log('[StreamlitDataStore] Updating _navigate_to_page:', data._navigate_to_page)
          this.dataForDrawing._navigate_to_page = data._navigate_to_page
        }
        if (data._target_row_index !== undefined) {
          console.log('[StreamlitDataStore] Updating _target_row_index:', data._target_row_index)
          this.dataForDrawing._target_row_index = data._target_row_index
        }

        // Update hash AFTER data is parsed - this triggers watchers that depend on hash
        this.hash = newHash
      } else if (!dataChanged) {
        // Data unchanged - Python only sent hash and state, keep cached data
        // But first check if we actually have cached data (may be empty after page navigation)
        const hasCache = Object.keys(this.dataForDrawing).length > 0

        console.log('[StreamlitDataStore] Using cached data branch:', {
          timestamp: Date.now(),
          hasCache,
          incomingPagination: (newData.args as any)._pagination,
          cachedPagination: this.dataForDrawing._pagination,
        })

        if (hasCache) {
          console.log('[StreamlitDataStore] Data unchanged, using cached data')
          // Update components config without changing data
          if (newData.args.components) {
            if (!this.renderData) {
              this.renderData = newData
            } else {
              this.renderData.args.components = newData.args.components
            }
          }
          // Update _plotConfig if sent (for dynamic annotation column changes)
          // This ensures LinePlot clears annotations when SequenceView tolerance changes
          // result in no matching fragment ions
          if ((newData.args as any)._plotConfig !== undefined) {
            this.dataForDrawing._plotConfig = (newData.args as any)._plotConfig
          }
        } else {
          // Cache is empty (e.g., after page navigation) - request data from Python
          console.warn('[StreamlitDataStore] Cache miss - requesting data from Python')
          this.requestData = true
          // Don't update renderData - wait for Python to resend with actual data
          return
        }
      }
    },

    /**
     * Parse Arrow table to array of row objects.
     * Used for table data where row-based access is needed.
     *
     * Optimized to use bulk column extraction via toArray() instead of
     * row-by-row random access. This is significantly faster for large tables.
     */
    parseArrowTable(arrowTable: ArrowTable): Record<string, unknown>[] {
      const numRows = arrowTable.table.numRows
      const columnNames = arrowTable.table.schema.fields.map((field) => field.name)

      // Step 1: Bulk extract all columns using toArray() - O(columns) not O(rows × columns)
      const columns: Map<string, unknown[]> = new Map()
      columnNames.forEach((columnName, colIndex) => {
        const column = arrowTable.table.getChildAt(colIndex)
        if (column) {
          // toArray() does vectorized conversion - much faster than row-by-row .get()
          const rawArray = column.toArray()
          // Convert typed array to regular array and handle BigInt
          const values: unknown[] = new Array(rawArray.length)
          for (let i = 0; i < rawArray.length; i++) {
            values[i] = this.parseArrowValue(rawArray[i])
          }
          columns.set(columnName, values)
        }
      })

      // Step 2: Transform to row format (required for Tabulator)
      const rows: Record<string, unknown>[] = new Array(numRows)
      for (let i = 0; i < numRows; i++) {
        const row: Record<string, unknown> = {}
        columnNames.forEach((columnName) => {
          const colData = columns.get(columnName)
          if (colData) {
            row[columnName] = colData[i]
          }
        })
        rows[i] = row
      }

      return rows
    },

    /**
     * Parse Arrow table to column arrays.
     * More efficient for plotting where column-based access is needed.
     * Returns: { columnName: [values...], ... }
     *
     * Optimized to use bulk toArray() extraction instead of row-by-row access.
     */
    parseArrowTableToColumns(arrowTable: ArrowTable): Record<string, unknown[]> {
      const columns: Record<string, unknown[]> = {}
      const columnNames = arrowTable.table.schema.fields.map((field) => field.name)

      columnNames.forEach((columnName, colIndex) => {
        const column = arrowTable.table.getChildAt(colIndex)

        if (column) {
          // toArray() does vectorized conversion - much faster than row-by-row .get()
          const rawArray = column.toArray()
          // Convert typed array to regular array and handle BigInt
          const values: unknown[] = new Array(rawArray.length)
          for (let i = 0; i < rawArray.length; i++) {
            values[i] = this.parseArrowValue(rawArray[i])
          }
          columns[columnName] = values
        } else {
          columns[columnName] = []
        }
      })

      return columns
    },

    /**
     * Convert Arrow value to native JS type.
     */
    parseArrowValue(value: unknown): unknown {
      // Arrow stores integers as bigint
      if (typeof value === 'bigint') {
        return Number(value)
      }
      // Arrays are stored as vectors
      if (value instanceof Vector) {
        const result: unknown[] = []
        for (let i = 0; i < value.length; i++) {
          result.push(this.parseArrowValue(value.get(i)))
        }
        return result
      }
      return value
    },

    /**
     * Set annotations from a component (e.g., SequenceView).
     * These are sent back to Python to enable cross-component annotation sharing.
     */
    setAnnotations(annotations: { peak_id: number[]; highlight_color: string[]; annotation: string[] } | null) {
      this.annotations = annotations
    },

    /**
     * Clear the requestData flag after it has been sent to Python.
     */
    clearRequestData() {
      this.requestData = false
    },
  },
})
