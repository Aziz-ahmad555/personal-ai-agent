import { createContext, useContext } from 'react'

export interface SceneMode {
  /** '3d' draws into the shared canvas; 'fallback' shows the SVG stand-ins. */
  mode: '3d' | 'fallback'
  reduced: boolean
}

export const SceneModeContext = createContext<SceneMode>({ mode: 'fallback', reduced: false })
export const useSceneMode = () => useContext(SceneModeContext)
