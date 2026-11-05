import path from 'node:path'

import { defineConfig, type UserConfigExport } from '@tarojs/cli'

import devConfig from './dev'
import prodConfig from './prod'

const isProd = process.env.NODE_ENV === 'production'
const apiBaseUrl =
  process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

export default defineConfig<'webpack5'>(async (merge) => {
  const baseConfig: UserConfigExport<'webpack5'> = {
    projectName: 'huahuo-spark',
    date: '2026-10-27',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      828: 1.81 / 2
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: [],
    defineConstants: {
      'process.env.TARO_APP_API_BASE_URL': JSON.stringify(apiBaseUrl)
    },
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
      // 生产环境把模拟登录整体替换为无凭据的空实现，避免 mock 用户信息进入包体。
      '@mock-login': path.resolve(
        __dirname,
        '..',
        isProd ? 'src/dev/mockLogin.stub.ts' : 'src/dev/mockLogin.ts'
      )
    },
    copy: {
      patterns: [],
      options: {}
    },
    framework: 'react',
    compiler: 'webpack5',
    cache: {
      enable: false
    },
    mini: {
      postcss: {
        pxtransform: {
          enable: true,
          config: {}
        },
        url: {
          enable: true,
          config: {
            limit: 1024
          }
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]'
          }
        }
      }
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      miniCssExtractPluginOption: {
        ignoreOrder: true
      },
      postcss: {
        autoprefixer: {
          enable: true,
          config: {}
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]'
          }
        }
      }
    }
  }

  if (!isProd) {
    return merge({}, baseConfig, devConfig)
  }
  return merge({}, baseConfig, prodConfig)
})
