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
    render() {
      // Implemented in Task 12
    },
    recolor() {
      // Implemented in Task 13
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
