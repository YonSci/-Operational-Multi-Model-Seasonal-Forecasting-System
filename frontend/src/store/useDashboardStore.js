import { create } from 'zustand'

/**
 * Global dashboard state -- shared between MapPanel, ChartsPanel, SitePanel.
 *
 * selectedSite  : { site_name, lat, lon } | null
 * activeModels  : Set of model name strings currently enabled
 * activeLayer   : which map layer is displayed
 * activeVariable: which forecast variable is shown
 */

const ALL_LAYERS = [
  { id: 'onset_anom',   label: 'Onset anomaly',    variable: 'onset',     layer: 'anomaly'  },
  { id: 'onset_spread', label: 'Onset spread',      variable: 'onset',     layer: 'spread'   },
  { id: 'prob_bn',      label: 'P(below normal)',   variable: 'onset',     layer: 'prob_bn'  },
  { id: 'prob_an',      label: 'P(above normal)',   variable: 'onset',     layer: 'prob_an'  },
  { id: 'lgp_anom',     label: 'LGP anomaly',       variable: 'lgp',       layer: 'anomaly'  },
  { id: 'lgp_spread',   label: 'LGP spread',        variable: 'lgp',       layer: 'spread'   },
  { id: 'failure',      label: 'Season failure P',  variable: 'onset',     layer: 'failure'  },
]

const useDashboardStore = create((set, get) => ({
  // -- Site selection -------------------------------------------------------
  selectedSite: { site_name: "Kapiti Research Station Farm", lat: -1.632, lon: 37.148 },
  setSelectedSite: (site) => set({ selectedSite: site }),

  // -- Model toggles --------------------------------------------------------
  activeModels: new Set(),   // populated once /models loads
  setActiveModels: (models) => set({ activeModels: new Set(models) }),
  toggleModel: (name) => set((s) => {
    const next = new Set(s.activeModels)
    next.has(name) ? next.delete(name) : next.add(name)
    return { activeModels: next }
  }),

  // -- Map layer ------------------------------------------------------------
  activeLayerId: 'onset_anom',
  setActiveLayer: (id) => set({ activeLayerId: id }),
  getActiveLayer: () => ALL_LAYERS.find(l => l.id === get().activeLayerId) ?? ALL_LAYERS[0],
  allLayers: ALL_LAYERS,

  // -- Chart tab ------------------------------------------------------------
  activeTab: 'plume',   // 'plume' | 'taylor' | 'risk'
  setActiveTab: (tab) => set({ activeTab: tab }),

  // -- OP year -------------------------------------------------------------
  opYear: 2026,
}))

export default useDashboardStore
