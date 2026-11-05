import React from 'react'
import ReactDOM from 'react-dom/client'
import { Provider } from 'react-redux'
import { BrowserRouter } from 'react-router-dom'

// antd 5 的 reset 放在 Tailwind 之前，Tailwind 已关闭 Preflight，不会互相覆盖。
import 'antd/dist/reset.css'
import './styles/index.css'

import App from './App'
import { store } from './store'

const baseUrl = import.meta.env.BASE_URL
const basename = baseUrl && baseUrl !== '/' ? baseUrl.replace(/\/+$/, '') : '/'

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <Provider store={store}>
      <BrowserRouter basename={basename}>
        <App />
      </BrowserRouter>
    </Provider>
  </React.StrictMode>
)
