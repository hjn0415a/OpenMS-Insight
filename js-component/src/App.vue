<template>
  <div v-if="componentArgs !== undefined">
    <component
      :is="currentComponent"
      :args="componentArgs"
      :index="0"
    />
  </div>
  <div v-else class="d-flex w-100" style="height: 200px">
    <v-alert
      class="h-50 ma-8"
      icon="mdi-application-variable-outline"
      title="Loading..."
      type="info"
      density="compact"
    >
      <v-progress-linear indeterminate></v-progress-linear>
    </v-alert>
  </div>
</template>

<script lang="ts">
import { defineComponent, watch, toRaw, type Component } from 'vue'
import { useStreamlitDataStore } from './stores/streamlit-data'
import { useSelectionStore } from '@/stores/selection'
import { Streamlit, type RenderData } from 'streamlit-component-lib'
import type { ComponentArgs, ComponentLayout } from './types/component'
import TabulatorTable from './components/tabulator/TabulatorTable.vue'
import PlotlyLineplot from './components/plotly/PlotlyLineplot.vue'
import PlotlyHeatmap from './components/plotly/PlotlyHeatmap.vue'
import PlotlyMirrorPlot from './components/plotly/PlotlyMirrorPlot.vue'
import PlotlyVolcano from './components/plotly/PlotlyVolcano.vue'
import SequenceView from './components/sequence/SequenceView.vue'

export default defineComponent({
  name: 'App',
  components: {
    TabulatorTable,
    PlotlyLineplot,
    PlotlyHeatmap,
    PlotlyMirrorPlot,
    PlotlyVolcano,
    SequenceView,
  },
  setup() {
    const streamlitDataStore = useStreamlitDataStore()
    const selectionStore = useSelectionStore()

    // Watch selection store counter and send state back to Python
    // We watch counter (a primitive) instead of deep-watching the entire state.
    // This avoids creating a spread object on every reactivity check.
    // Counter increments on every selection change, so this captures all updates.
    let lastSentCounter: number | undefined = undefined
    let lastSentHash: string | undefined = undefined
    let lastSentAnnotationsHash: string | undefined = undefined

    // Debounce utility for selection state updates
    // This prevents rapid clicks from overwhelming Streamlit with reruns
    let sendStateTimeout: ReturnType<typeof setTimeout> | null = null
    const DEBOUNCE_MS = 100 // 100ms debounce window

    const sendStateToStreamlit = () => {
      const currentCounter = selectionStore.$state.counter
      const currentHash = streamlitDataStore.hash || null
      const currentAnnotations = streamlitDataStore.annotations
      // Hash annotations to detect changes (use peak_id array as proxy for full content)
      const annotationsHash = currentAnnotations
        ? JSON.stringify(currentAnnotations.peak_id)
        : undefined

      // Avoid duplicate sends for same counter+hash+annotations combination
      if (currentCounter === lastSentCounter && currentHash === lastSentHash && annotationsHash === lastSentAnnotationsHash) {
        console.log('[App] sendStateToStreamlit: SKIPPED (duplicate)', {
          timestamp: Date.now(),
          counter: currentCounter,
        })
        return
      }
      lastSentCounter = currentCounter
      lastSentHash = currentHash ?? undefined
      lastSentAnnotationsHash = annotationsHash

      // Deep clone to remove Vue reactivity proxies before sending to Streamlit
      // This prevents "Proxy object could not be cloned" errors
      const plainState = JSON.parse(JSON.stringify(selectionStore.$state))

      // Find pagination identifier and value for logging
      const paginationIdentifier = Object.keys(plainState).find(k =>
        typeof plainState[k] === 'object' && plainState[k]?.page !== undefined
      )
      const paginationValue = paginationIdentifier ? plainState[paginationIdentifier] : undefined

      console.log('[App] ===== sendStateToStreamlit =====', {
        timestamp: Date.now(),
        counter: currentCounter,
        hash: currentHash?.substring(0, 8),
        paginationIdentifier,
        paginationValue,
        requestData: streamlitDataStore.requestData,
      })

      // Echo back Vue's current data hash so Python knows if Vue has the data
      // This enables bidirectional hash confirmation for cache optimization
      plainState._vueDataHash = currentHash
      // Include annotations from components like SequenceView
      if (currentAnnotations) {
        plainState._annotations = JSON.parse(JSON.stringify(currentAnnotations))
      }
      // Signal Python if we need data (cache miss after page navigation)
      if (streamlitDataStore.requestData) {
        plainState._requestData = true
        streamlitDataStore.clearRequestData()
      }
      Streamlit.setComponentValue(plainState)
      console.log('[App] setComponentValue CALLED')
    }

    // Debounced version for selection changes - batches rapid clicks
    const debouncedSendState = () => {
      if (sendStateTimeout) {
        clearTimeout(sendStateTimeout)
      }
      sendStateTimeout = setTimeout(() => {
        sendStateToStreamlit()
        sendStateTimeout = null
      }, DEBOUNCE_MS)
    }

    // Flush any pending debounced state (used before immediate sends)
    const flushPendingState = () => {
      if (sendStateTimeout) {
        clearTimeout(sendStateTimeout)
        sendStateTimeout = null
      }
    }

    // Watch counter, hash, annotations, and requestData to ensure Python always knows Vue's state
    // Counter changes (selection updates) are debounced to prevent rapid click cascades
    watch(() => selectionStore.$state.counter, (newVal, oldVal) => {
      // On first load (immediate: true), send immediately
      if (oldVal === undefined) {
        sendStateToStreamlit()
      } else {
        // Debounce subsequent selection changes to batch rapid clicks
        debouncedSendState()
      }
    }, { immediate: true })
    // Hash and annotation changes are sent immediately (data sync, not user interaction)
    watch(() => streamlitDataStore.hash, () => sendStateToStreamlit())
    watch(() => streamlitDataStore.annotations, () => sendStateToStreamlit(), { deep: true })
    // RequestData needs immediate response - flush any pending debounced state first
    watch(() => streamlitDataStore.requestData, (newVal) => {
      if (newVal) {
        flushPendingState()
        sendStateToStreamlit()
      }
    })

    // Watch for height changes and update frame height
    watch(
      () => streamlitDataStore.allDataForDrawing?.height,
      (newHeight) => {
        if (newHeight && typeof newHeight === 'number') {
          Streamlit.setFrameHeight(newHeight)
        }
      },
      { immediate: true }
    )

    return { streamlitDataStore, selectionStore }
  },
  data() {
    return {
      resizeObserver: undefined as ResizeObserver | undefined,
    }
  },
  computed: {
    /**
     * Get the component args from the first (and only) component in the layout.
     * Python sends: components: [[{componentArgs: {...}}]]
     */
    componentArgs(): ComponentArgs | undefined {
      const components = this.streamlitDataStore.args?.components
      if (components && components.length > 0 && components[0].length > 0) {
        return components[0][0].componentArgs
      }
      return undefined
    },

    /**
     * Get the Vue component based on componentType.
     */
    currentComponent(): Component | null {
      const componentType = this.componentArgs?.componentType
      switch (componentType) {
        case 'TabulatorTable':
          return TabulatorTable
        case 'PlotlyLineplotUnified':
        case 'PlotlyLineplot':
          return PlotlyLineplot
        case 'PlotlyHeatmap':
          return PlotlyHeatmap
        case 'PlotlyMirrorPlot':
          return PlotlyMirrorPlot
        case 'PlotlyVolcano':
          return PlotlyVolcano
        case 'SequenceView':
          return SequenceView
        default:
          console.warn(`Unknown component type: ${componentType}`)
          return null
      }
    },
  },
  created() {
    Streamlit.setComponentReady()
    // Set initial frame height - will be updated when data arrives
    Streamlit.setFrameHeight(400)
    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, this.updateStreamlitData)
  },
  mounted() {
    // Use ResizeObserver to update frame height only when size actually changes
    // This replaces polling (setInterval every 500ms) with event-driven updates
    this.resizeObserver = new ResizeObserver(() => {
      Streamlit.setFrameHeight()
    })
    this.resizeObserver.observe(this.$el as HTMLElement)
  },
  unmounted() {
    Streamlit.events.removeEventListener(Streamlit.RENDER_EVENT, this.updateStreamlitData)
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
    }
  },
  // Removed: updated() hook that called Streamlit.setFrameHeight()
  // This was redundant - height is now set explicitly by components
  // and via the watch on allDataForDrawing.height
  methods: {
    async updateStreamlitData(event: Event): Promise<void> {
      this.streamlitDataStore.updateRenderData((event as CustomEvent<RenderData>).detail)
    },
  },
})
</script>

<style>
body {
  margin: 0;
  font-family: 'Source Sans Pro', sans-serif;
}

.tabulator-tooltip {
  background: #fff;
  color: #000;
}
</style>
