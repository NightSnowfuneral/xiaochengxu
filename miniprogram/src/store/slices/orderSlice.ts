import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

import type {
  OrderCreatedBase,
  OrderResponse,
  OrderStatus
} from '../../types'

export interface OrderState {
  /** 只保存订单公共字段，不保存虚拟支付调起参数。 */
  currentOrder: OrderCreatedBase | null
  status: OrderStatus | null
  paying: boolean
  paid: boolean
  error: string | null
}

const initialState: OrderState = {
  currentOrder: null,
  status: null,
  paying: false,
  paid: false,
  error: null
}

const orderSlice = createSlice({
  name: 'order',
  initialState,
  reducers: {
    startPayment(state) {
      state.paying = true
      state.paid = false
      state.error = null
      state.status = null
    },
    orderCreated(state, action: PayloadAction<OrderCreatedBase>) {
      state.currentOrder = action.payload
      state.status = action.payload.status
      state.error = null
    },
    orderStatusUpdated(state, action: PayloadAction<OrderResponse>) {
      state.status = action.payload.status
      state.paid = action.payload.status === 'paid'
      state.error = null
    },
    paymentSucceeded(state) {
      state.paying = false
      state.paid = true
      state.status = 'paid'
      state.error = null
    },
    paymentFailed(state, action: PayloadAction<string>) {
      state.paying = false
      state.paid = false
      state.error = action.payload
    },
    clearOrder(state) {
      state.currentOrder = null
      state.status = null
      state.paying = false
      state.paid = false
      state.error = null
    }
  }
})

export const {
  clearOrder,
  orderCreated,
  orderStatusUpdated,
  paymentFailed,
  paymentSucceeded,
  startPayment
} = orderSlice.actions

export const selectOrderState = (state: { order: OrderState }): OrderState =>
  state.order

export default orderSlice.reducer
