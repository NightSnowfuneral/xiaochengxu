/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // 关闭 Preflight：antd 5 自带 reset，避免 Tailwind 基础样式覆盖 antd 组件。
  corePlugins: {
    preflight: false
  },
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#fbf7ef',
          100: '#f4e9d4',
          200: '#e8d4ab',
          300: '#dbbd7d',
          400: '#cba55c',
          500: '#b98b45',
          600: '#a47436',
          700: '#875b2e',
          800: '#6f4a2a',
          900: '#5c3e26'
        },
        ink: {
          900: '#0d1526',
          800: '#131e33',
          700: '#1b2942'
        }
      },
      fontFamily: {
        sans: [
          'PingFang SC',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'sans-serif'
        ]
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.04), 0 12px 32px -20px rgba(15, 23, 42, 0.25)'
      }
    }
  },
  plugins: []
}
