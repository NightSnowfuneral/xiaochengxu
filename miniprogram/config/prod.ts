import type { UserConfigExport } from '@tarojs/cli'

export default {
  logger: {
    quiet: true,
    stats: false
  },
  mini: {
    webpackChain(chain) {
      chain.merge({
        optimization: {
          minimize: true
        }
      })
    }
  },
  h5: {}
} satisfies UserConfigExport<'webpack5'>
