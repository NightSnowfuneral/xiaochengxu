import { useSyncExternalStore } from 'react'

export interface LoginModalState {
  visible: boolean
  reason: string
}

let state: LoginModalState = {
  visible: false,
  reason: ''
}

const listeners = new Set<() => void>()

function emit(nextState: LoginModalState): void {
  state = nextState
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): LoginModalState {
  return state
}

export function openLoginModal(reason = ''): void {
  emit({ visible: true, reason })
}

export function closeLoginModal(): void {
  if (!state.visible) {
    return
  }
  emit({ ...state, visible: false })
}

export function useLoginModalState(): LoginModalState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}
