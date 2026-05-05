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

// Default styling configuration
const DEFAULT_STYLING = {
  topColor: 'lightblue',
  bottomColor: 'lightcoral',
  highlightColor: '#E4572E',
  selectedColor: '#F3A712',
}

interface SideData {
  x: number[]
  y: number[] // POSITIVE values from Python; we negate for bottom in render() (Task 12)
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
    /**
     * Get plot config from Python (sent with data, may have dynamic column names).
     */
    plotConfig(): Record<string, unknown> | undefined {
      return this.streamlitDataStore.allDataForDrawing?._plotConfig as
        | Record<string, unknown>
        | undefined
    },
    topData(): SideData | undefined {
      return this.extractSide('plotDataTop', 'topHighlightColumn', 'topAnnotationColumn')
    },
    bottomData(): SideData | undefined {
      return this.extractSide(
        'plotDataBottom',
        'bottomHighlightColumn',
        'bottomAnnotationColumn',
      )
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
    'selectionStore.$state': {
      handler() {
        // Re-color only — no full redraw (Task 13)
        this.recolor()
      },
      deep: true,
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
      const highlightCol = this.plotConfig?.[highlightConfigKey] as string | null | undefined
      const annotationCol = this.plotConfig?.[annotationConfigKey] as string | null | undefined

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
    async render() {
      const top = this.topData
      const bottom = this.bottomData
      if (!top && !bottom) return

      const topY = top?.y ?? []
      const bottomY = bottom?.y ?? []
      const topMax = topY.reduce((m, v) => (v > m ? v : m), 0)
      const bottomMax = bottomY.reduce((m, v) => (v > m ? v : m), 0)
      const yMax = Math.max(topMax, bottomMax, 1.0) // 1.0 fallback for empty figure

      // Build per-peak colors (Task 13 will refine these on selection changes)
      const topColors = this.colorsForSide(top, this.styling.topColor)
      const bottomColors = this.colorsForSide(bottom, this.styling.bottomColor)

      // Build "stick" lines as Plotly shapes (one per peak)
      // Top half y > 0, bottom half y < 0 (we negate bottom values here)
      const shapes: Partial<Plotly.Shape>[] = []
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
            y1: -bottom.y[i], // FLIP HERE
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
          customdata: (top?.x.map((_, i) => ({ side: 'top', index: i })) ?? []) as any[],
        },
        {
          x: bottom?.x ?? [],
          y: (bottom?.y ?? []).map((v) => -v), // FLIP HERE
          mode: 'markers',
          type: 'scattergl',
          marker: { color: bottomColors, size: 4 },
          name: this.args.titleBottom || 'Bottom',
          customdata: (bottom?.x.map((_, i) => ({ side: 'bottom', index: i })) ?? []) as any[],
        },
      ]

      const tickValues = [-yMax, -yMax / 2, 0, yMax / 2, yMax]
      const tickText = tickValues.map((v) => Math.abs(v).toFixed(0))

      const annotations: Partial<Plotly.Annotations>[] = [
        ...(this.args.titleTop
          ? [
              {
                text: this.args.titleTop,
                xref: 'paper' as const,
                yref: 'paper' as const,
                x: 0.02,
                y: 0.98,
                showarrow: false,
                xanchor: 'left' as const,
                yanchor: 'top' as const,
              },
            ]
          : []),
        ...(this.args.titleBottom
          ? [
              {
                text: this.args.titleBottom,
                xref: 'paper' as const,
                yref: 'paper' as const,
                x: 0.02,
                y: 0.02,
                showarrow: false,
                xanchor: 'left' as const,
                yanchor: 'bottom' as const,
              },
            ]
          : []),
      ]

      const layout: Partial<Plotly.Layout> = {
        title: this.args.title ? { text: this.args.title } : undefined,
        xaxis: { title: this.args.xLabel ? { text: this.args.xLabel } : undefined },
        yaxis: {
          title: this.args.yLabel ? { text: this.args.yLabel } : undefined,
          range: [-yMax * 1.1, yMax * 1.1],
          tickvals: tickValues,
          ticktext: tickText,
          zeroline: true,
          zerolinecolor: '#888',
          zerolinewidth: 1,
        },
        shapes,
        showlegend: false,
        annotations,
      }

      const element = document.getElementById(this.id)
      if (!element) return

      await Plotly.newPlot(element, traces, layout, { responsive: true })
      this.isInitialized = true

      // Wire click handler for interactivity
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
            this.selectionStore.updateSelection(identifier, values[pt.pointIndex])
          }
        }
      })
    },

    colorsForSide(side: SideData | undefined, baseColor: string): string[] {
      if (!side) return []
      const colors: string[] = []
      const interactivityCol = this.firstInteractivityColumn()
      const selectionValue = interactivityCol ? this.currentSelectionValue() : undefined

      for (let i = 0; i < side.x.length; i++) {
        let color = baseColor
        if (side.highlight?.[i]) {
          color = this.styling.highlightColor
        }
        if (
          interactivityCol &&
          side.interactivityValues?.[interactivityCol]?.[i] === selectionValue &&
          selectionValue !== undefined
        ) {
          color = this.styling.selectedColor
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
      return this.selectionStore.$state[firstIdentifier]
    },

    recolor() {
      if (!this.isInitialized) return
      const top = this.topData
      const bottom = this.bottomData

      const topColors = this.colorsForSide(top, this.styling.topColor)
      const bottomColors = this.colorsForSide(bottom, this.styling.bottomColor)

      // Update marker colors on existing traces
      void Plotly.restyle(this.id, { 'marker.color': [topColors] }, [0])
      void Plotly.restyle(this.id, { 'marker.color': [bottomColors] }, [1])

      // Rebuild shapes with updated colors (no x/y recomputation needed)
      const shapes: Partial<Plotly.Shape>[] = []
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
  },
})
</script>

<style scoped>
.plot-container {
  width: 100%;
  height: 100%;
}
</style>
