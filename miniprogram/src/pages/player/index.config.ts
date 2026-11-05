export default definePageConfig({
  navigationBarTitleText: '课程播放',
  navigationBarBackgroundColor: '#0b0a08',
  navigationBarTextStyle: 'white',
  // 自定义导航栏：全屏横屏时连同导航栏一起隐藏，视频铺满视口。
  // 右上角胶囊是微信系统控件，任何配置都无法隐藏。
  navigationStyle: 'custom',
  disableScroll: false,
  backgroundColor: '#0b0a08',
  backgroundTextStyle: 'light',
  // 全屏播放依赖 PageMeta 动态切换 pageOrientation（横屏）。
  enablePageMeta: true
})
