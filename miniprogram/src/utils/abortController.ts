/**
 * 微信小程序基础库（含 3.x）没有实现 AbortController，
 * 而 axios 1.x 在派发请求时会无条件 new AbortController 用于超时/取消，
 * 缺失时所有请求在 dispatch 阶段直接抛 ReferenceError，页面拿不到任何接口数据。
 * 这里补一个最小可用实现，仅在宿主缺失时挂载，浏览器/Node 环境不受影响。
 */
type AbortListener = (event: { type: string }) => void

interface AbortListenerOptions {
  once?: boolean
}

interface AbortListenerEntry {
  listener: AbortListener
  once: boolean
}

class MiniAbortSignal {
  aborted = false
  reason: unknown = undefined
  private entries: AbortListenerEntry[] = []

  addEventListener(
    type: string,
    listener: AbortListener,
    options?: AbortListenerOptions
  ): void {
    if (type !== 'abort') {
      return
    }
    this.entries.push({ listener, once: Boolean(options?.once) })
  }

  removeEventListener(type: string, listener: AbortListener): void {
    if (type !== 'abort') {
      return
    }
    this.entries = this.entries.filter((entry) => entry.listener !== listener)
  }

  throwIfAborted(): void {
    if (this.aborted) {
      throw this.reason
    }
  }

  /** 仅由 MiniAbortController 调用。 */
  markAborted(reason: unknown): void {
    if (this.aborted) {
      return
    }
    this.aborted = true
    this.reason = reason
    const entries = this.entries
    this.entries = []
    entries.forEach((entry) => entry.listener({ type: 'abort' }))
  }
}

class MiniAbortController {
  readonly signal = new MiniAbortSignal()

  abort(reason?: unknown): void {
    this.signal.markAborted(reason)
  }
}

// TS 的 DOM lib 把 AbortController/AbortSignal 声明为完整实现，
// 这里只需向宿主挂载最小实现，故先与 DOM 类型解耦再赋值。
const runtime = globalThis as unknown as {
  AbortController?: unknown
  AbortSignal?: unknown
}

if (typeof runtime.AbortController === 'undefined') {
  runtime.AbortController = MiniAbortController
}

if (typeof runtime.AbortSignal === 'undefined') {
  runtime.AbortSignal = MiniAbortSignal
}

export {}
