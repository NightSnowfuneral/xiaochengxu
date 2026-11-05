export default defineAppConfig({
  pages: [
    'pages/home/index',
    'pages/academy/index',
    'pages/course-list/index',
    'pages/course-detail/index',
    'pages/payment-success/index',
    'pages/player/index',
    'pages/profile/index'
  ],
  window: {
    backgroundTextStyle: 'dark',
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: '禾下美学院',
    navigationBarTextStyle: 'black',
    backgroundColor: '#f6f2e9'
  },
  tabBar: {
    color: '#8a8177',
    selectedColor: '#a37632',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      {
        pagePath: 'pages/home/index',
        text: '首页'
      },
      {
        pagePath: 'pages/academy/index',
        text: '课程'
      }
    ]
  },
  lazyCodeLoading: 'requiredComponents'
})
