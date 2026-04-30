import { create } from "zustand";

interface AppState {
  currentTicker: string;
  recentSearches: string[];
  sidebarOpen: boolean;
  setCurrentTicker: (t: string) => void;
  addRecentSearch: (t: string) => void;
  setSidebarOpen: (open: boolean) => void;
}

export const useStore = create<AppState>((set) => ({
  currentTicker: "",
  recentSearches: [],
  sidebarOpen: true,
  setCurrentTicker: (t) => set({ currentTicker: t.toUpperCase() }),
  addRecentSearch: (t) =>
    set((s) => {
      const upper = t.toUpperCase();
      const filtered = s.recentSearches.filter((x) => x !== upper);
      return { recentSearches: [upper, ...filtered].slice(0, 10) };
    }),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}));
