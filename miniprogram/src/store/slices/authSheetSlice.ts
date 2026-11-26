import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

export interface AuthSheetState {
  visible: boolean
  reason: string
}

const initialState: AuthSheetState = {
  visible: false,
  reason: ''
}

const authSheetSlice = createSlice({
  name: 'authSheet',
  initialState,
  reducers: {
    showAuthSheet(state, action: PayloadAction<{ reason?: string } | undefined>) {
      state.visible = true
      state.reason = action.payload?.reason?.trim() || ''
    },
    hideAuthSheet(state) {
      state.visible = false
      state.reason = ''
    }
  }
})

export const { hideAuthSheet, showAuthSheet } = authSheetSlice.actions

export default authSheetSlice.reducer
