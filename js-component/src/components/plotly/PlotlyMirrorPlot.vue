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

// Default styling configuration (matches PlotlyLineplot for visual consistency)
const DEFAULT_STYLING = {
  highlightColor: '#E4572E',
  selectedColor: '#F3A712',
  unhighlightedColor: 'lightblue',
}

interface SideData {
  x: number[]
  y: number[] // POSITIVE values from Python; we negate for bottom in render() (Task 12)
  highlight?: boolean[]
  annotations?: string[]
  interactivityValues?: Record<string, unknown[]>
}

interface AnnotatedPeak {
  x: number
  y: number
  label: string
  index: number
}

interface AnnotationBox {
  x: number
  y: number
  width: number
  height: number
  label: string
  visible: boolean
  inVisibleRange: boolean
  index: number
  peakY: number
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
      textMeasureCanvas: null as HTMLCanvasElement | null,
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
    /** Maximum positive y value across both sides (data values are positive). */
    yMaxData(): number {
      const topY = this.topData?.y ?? []
      const bottomY = this.bottomData?.y ?? []
      const topMax = topY.reduce((m, v) => (v > m ? v : m), 0)
      const bottomMax = bottomY.reduce((m, v) => (v > m ? v : m), 0)
      return Math.max(topMax, bottomMax, 1.0)
    },
    /** Half-height of the y-axis range. Matches PlotlyLineplot's 1.8× expansion. */
    yRangeMax(): number {
      return this.yMaxData * 1.8
    },
    /** X range covering both sides, with 2% padding (used for label fit calculations). */
    xRange(): number[] {
      const xs: number[] = []
      if (this.topData) xs.push(...this.topData.x)
      if (this.bottomData) xs.push(...this.bottomData.x)
      if (xs.length === 0) return [0, 1]
      const minX = Math.min(...xs)
      const maxX = Math.max(...xs)
      const padding = (maxX - minX) * 0.02
      return [minX - padding, maxX + padding]
    },
    /** Plot DOM width for pixel-to-data conversion. */
    actualPlotWidth(): number {
      const element = document.getElementById(this.id)
      if (element) {
        const rect = element.getBoundingClientRect()
        if (rect.width > 0) return rect.width
      }
      return 800
    },
    annotatedPeaksTop(): AnnotatedPeak[] {
      return this.collectAnnotatedPeaks(this.topData)
    },
    annotatedPeaksBottom(): AnnotatedPeak[] {
      return this.collectAnnotatedPeaks(this.bottomData)
    },
    annotationBoxDataTop(): AnnotationBox[] {
      return this.computeAnnotationBoxes(this.annotatedPeaksTop)
    },
    annotationBoxDataBottom(): AnnotationBox[] {
      return this.computeAnnotationBoxes(this.annotatedPeaksBottom)
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

    collectAnnotatedPeaks(side: SideData | undefined): AnnotatedPeak[] {
      if (!side || !side.annotations) return []
      const { x, y, annotations, highlight } = side
      const peaks: AnnotatedPeak[] = []
      for (let i = 0; i < annotations.length; i++) {
        const label = annotations[i]
        if (!label || label.length === 0) continue
        if (highlight && !highlight[i]) continue
        peaks.push({ x: x[i], y: y[i], label, index: i })
      }
      return peaks
    },

    /**
     * Greedy intensity-based overlap resolution: sort by peak intensity
     * (highest first), commit boxes that don't collide with already-committed
     * neighbors. Mirrors PlotlyLineplot's algorithm.
     */
    computeAnnotationBoxes(peaks: AnnotatedPeak[]): AnnotationBox[] {
      if (peaks.length === 0) return []
      const xRange = this.xRange
      if (xRange[1] <= xRange[0]) return []

      const yMax = this.yMaxData
      const ypos_low = yMax * 1.18
      const ypos_high = yMax * 1.32
      const boxHeight = ypos_high - ypos_low
      const textPaddingPx = 16

      const boxes: AnnotationBox[] = peaks.map((peak) => {
        const inVisibleRange = peak.x >= xRange[0] && peak.x <= xRange[1]
        const textWidthPx = this.measureTextWidth(peak.label)
        const widthDataUnits = this.pixelWidthToDataUnits(textWidthPx + textPaddingPx)
        return {
          x: peak.x,
          y: (ypos_low + ypos_high) / 2,
          width: widthDataUnits,
          height: boxHeight,
          label: peak.label,
          visible: false,
          inVisibleRange,
          index: peak.index,
          peakY: peak.y,
        }
      })

      const candidates = boxes
        .filter((b) => b.inVisibleRange)
        .sort((a, b) => {
          if (b.peakY !== a.peakY) return b.peakY - a.peakY
          return a.x - b.x
        })

      const gapDataUnits = this.pixelWidthToDataUnits(4)
      const committed: AnnotationBox[] = []
      for (const box of candidates) {
        const left = box.x - box.width / 2 - gapDataUnits
        const right = box.x + box.width / 2 + gapDataUnits
        let collides = false
        for (const c of committed) {
          const cLeft = c.x - c.width / 2
          const cRight = c.x + c.width / 2
          if (!(right < cLeft || left > cRight)) {
            collides = true
            break
          }
        }
        if (!collides) {
          box.visible = true
          committed.push(box)
        }
      }
      return boxes
    },

    /**
     * Build label background rectangles for one side. Bottom side gets y-flipped
     * (negated) since the plot mirrors data below the x axis.
     */
    buildAnnotationShapes(
      boxes: AnnotationBox[],
      side: 'top' | 'bottom',
    ): Partial<Plotly.Shape>[] {
      const yMax = this.yMaxData
      const ypos_low = yMax * 1.18
      const ypos_high = yMax * 1.32
      const interactivityCol = this.firstInteractivityColumn()
      const selectionValue = interactivityCol ? this.currentSelectionValue() : undefined
      const sourceData = side === 'top' ? this.topData : this.bottomData

      const shapes: Partial<Plotly.Shape>[] = []
      for (const box of boxes) {
        if (!box.visible) continue
        let isSelected = false
        if (interactivityCol && sourceData?.interactivityValues?.[interactivityCol]) {
          const peakValue = sourceData.interactivityValues[interactivityCol][box.index]
          isSelected = peakValue === selectionValue && selectionValue !== undefined
        }
        const color = isSelected ? this.styling.selectedColor : this.styling.highlightColor
        const y0 = side === 'top' ? ypos_low : -ypos_high
        const y1 = side === 'top' ? ypos_high : -ypos_low
        shapes.push({
          type: 'rect',
          x0: box.x - box.width / 2,
          y0,
          x1: box.x + box.width / 2,
          y1,
          fillcolor: color,
          line: { width: 0 },
        })
      }
      return shapes
    },

    /**
     * Build Plotly text annotations for one side. Bottom side y is negated.
     */
    buildPeakAnnotations(
      boxes: AnnotationBox[],
      side: 'top' | 'bottom',
    ): Partial<Plotly.Annotations>[] {
      const yMax = this.yMaxData
      const ypos = yMax * 1.25
      const annotations: Partial<Plotly.Annotations>[] = []
      for (const box of boxes) {
        if (!box.visible) continue
        annotations.push({
          x: box.x,
          y: side === 'top' ? ypos : -ypos,
          xref: 'x',
          yref: 'y',
          text: box.label,
          showarrow: false,
          font: { size: 14, color: 'white' },
        })
      }
      return annotations
    },

    measureTextWidth(text: string): number {
      if (!this.textMeasureCanvas) {
        this.textMeasureCanvas = document.createElement('canvas')
      }
      const ctx = this.textMeasureCanvas.getContext('2d')
      if (!ctx) return text.length * 8
      ctx.font = '14px Arial'
      return ctx.measureText(text).width
    },

    pixelWidthToDataUnits(pixelWidth: number): number {
      const xRange = this.xRange
      const rangeWidth = xRange[1] - xRange[0]
      const plotWidth = this.actualPlotWidth
      if (plotWidth <= 0 || rangeWidth <= 0) return 0
      return pixelWidth / (plotWidth / rangeWidth)
    },
    async render() {
      const top = this.topData
      const bottom = this.bottomData
      if (!top && !bottom) return

      const yMax = this.yMaxData
      const yRangeMax = this.yRangeMax

      const topColors = this.colorsForSide(top)
      const bottomColors = this.colorsForSide(bottom)

      const stickShapes: Partial<Plotly.Shape>[] = [
        ...this.buildStickShapes(top, topColors, 'top'),
        ...this.buildStickShapes(bottom, bottomColors, 'bottom'),
      ]

      const labelShapes = [
        ...this.buildAnnotationShapes(this.annotationBoxDataTop, 'top'),
        ...this.buildAnnotationShapes(this.annotationBoxDataBottom, 'bottom'),
      ]
      const shapes = [...stickShapes, ...labelShapes]

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
          y: (bottom?.y ?? []).map((v) => -v),
          mode: 'markers',
          type: 'scattergl',
          marker: { color: bottomColors, size: 4 },
          name: this.args.titleBottom || 'Bottom',
          customdata: (bottom?.x.map((_, i) => ({ side: 'bottom', index: i })) ?? []) as any[],
        },
      ]

      const tickValues = [-yMax, -yMax / 2, 0, yMax / 2, yMax]
      const tickText = tickValues.map((v) => Math.abs(v).toFixed(0))

      const titleAnnotations: Partial<Plotly.Annotations>[] = [
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

      const annotations: Partial<Plotly.Annotations>[] = [
        ...titleAnnotations,
        ...this.buildPeakAnnotations(this.annotationBoxDataTop, 'top'),
        ...this.buildPeakAnnotations(this.annotationBoxDataBottom, 'bottom'),
      ]

      const layout: Partial<Plotly.Layout> = {
        title: this.args.title ? { text: `<b>${this.args.title}</b>` } : undefined,
        showlegend: false,
        height: this.args.height || 400,
        xaxis: {
          title: this.args.xLabel ? { text: this.args.xLabel } : undefined,
          showgrid: false,
          showline: true,
          linecolor: 'grey',
          linewidth: 1,
          range: this.xRange,
        },
        yaxis: {
          title: this.args.yLabel ? { text: this.args.yLabel } : undefined,
          showgrid: true,
          gridcolor: this.theme?.secondaryBackgroundColor || '#f0f0f0',
          showline: true,
          linecolor: 'grey',
          linewidth: 1,
          range: [-yRangeMax, yRangeMax],
          tickvals: tickValues,
          ticktext: tickText,
          zeroline: true,
          zerolinecolor: 'grey',
          zerolinewidth: 1,
        },
        paper_bgcolor: this.theme?.backgroundColor || 'white',
        plot_bgcolor: this.theme?.backgroundColor || 'white',
        font: {
          color: this.theme?.textColor || 'black',
          family: this.theme?.font || 'Arial',
        },
        margin: {
          l: 60,
          r: 20,
          t: this.args.title ? 50 : 20,
          b: 50,
        },
        shapes,
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

    colorsForSide(side: SideData | undefined): string[] {
      if (!side) return []
      const colors: string[] = []
      const interactivityCol = this.firstInteractivityColumn()
      const selectionValue = interactivityCol ? this.currentSelectionValue() : undefined

      for (let i = 0; i < side.x.length; i++) {
        let color = this.styling.unhighlightedColor
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

    /**
     * Build stick line shapes for one side. Bottom side y is negated to mirror.
     * Selected peaks get width 3 (matches PlotlyLineplot); others use Plotly default.
     */
    buildStickShapes(
      side: SideData | undefined,
      colors: string[],
      sideKey: 'top' | 'bottom',
    ): Partial<Plotly.Shape>[] {
      if (!side) return []
      const sign = sideKey === 'top' ? 1 : -1
      const shapes: Partial<Plotly.Shape>[] = []
      for (let i = 0; i < side.x.length; i++) {
        const isSelected = colors[i] === this.styling.selectedColor
        shapes.push({
          type: 'line',
          x0: side.x[i],
          x1: side.x[i],
          y0: 0,
          y1: sign * side.y[i],
          line: { color: colors[i], width: isSelected ? 3 : 1.5 },
        })
      }
      return shapes
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

      const topColors = this.colorsForSide(top)
      const bottomColors = this.colorsForSide(bottom)

      // Update marker colors on existing traces
      void Plotly.restyle(this.id, { 'marker.color': [topColors] }, [0])
      void Plotly.restyle(this.id, { 'marker.color': [bottomColors] }, [1])

      const stickShapes: Partial<Plotly.Shape>[] = [
        ...this.buildStickShapes(top, topColors, 'top'),
        ...this.buildStickShapes(bottom, bottomColors, 'bottom'),
      ]

      // Rebuild label backgrounds + text — selection state may have changed
      // which annotation rect should be shown in selectedColor.
      const labelShapes = [
        ...this.buildAnnotationShapes(this.annotationBoxDataTop, 'top'),
        ...this.buildAnnotationShapes(this.annotationBoxDataBottom, 'bottom'),
      ]
      const shapes = [...stickShapes, ...labelShapes]

      const titleAnnotations: Partial<Plotly.Annotations>[] = [
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
      const annotations: Partial<Plotly.Annotations>[] = [
        ...titleAnnotations,
        ...this.buildPeakAnnotations(this.annotationBoxDataTop, 'top'),
        ...this.buildPeakAnnotations(this.annotationBoxDataBottom, 'bottom'),
      ]

      void Plotly.relayout(this.id, { shapes, annotations })
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
