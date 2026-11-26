import { type PropsWithChildren } from 'react'
import { Provider } from 'react-redux'
import { useDidShow, useLaunch } from '@tarojs/taro'

import './app.scss'
import { store } from './store'
import { fetchConfigs } from './store/slices/configSlice'
import {
  bootstrapAuth,
  configureAuthRuntime,
  revalidateAuthOnShow
} from './utils/auth'
import { cancelAuthSheetIfStale } from './utils/authGate'
import { setupPrivacyAuthorization } from './utils/privacy'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // useLaunch 只在冷启动执行：等待持久化恢复并校验本地 Token。
    // 先注册 401 处理，再发起冷启动校验。
    configureAuthRuntime()
    // 注册微信隐私授权监听：未同意《用户隐私保护指引》时，
    // getPhoneNumber 会先走这里，而不是直接失败返回空 code。
    setupPrivacyAuthorization()
    void bootstrapAuth()
    void store.dispatch(fetchConfigs())
  })

  useDidShow(() => {
    // 热启动（后台切回 / 右上角重新进入 / 下拉唤起）每次都会触发。
    // 这里只做本地 Token 校验，不重复登录、不拉起手机号授权。
    cancelAuthSheetIfStale()
    void revalidateAuthOnShow()
  })

  return <Provider store={store}>{children}</Provider>
}

export default App
