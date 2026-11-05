// Taro 4 + React + TypeScript（webpack5 编译器）
module.exports = {
  presets: [
    [
      'taro',
      {
        framework: 'react',
        ts: true,
        compiler: 'webpack5'
      }
    ]
  ]
}
