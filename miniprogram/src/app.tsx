import { type PropsWithChildren } from 'react'
import { Provider } from 'react-redux'
import { useLaunch } from '@tarojs/taro'

import './app.scss'
import { store } from './store'
import { fetchConfigs } from './store/slices/configSlice'
import { bootstrapAuth, configureAuthRuntime } from './utils/auth'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // 先注册 401 处理，再等待持久化恢复并执行静默登录。
    configureAuthRuntime()
    void bootstrapAuth()
    void store.dispatch(fetchConfigs())
  })

  return <Provider store={store}>{children}</Provider>
}

export default App
