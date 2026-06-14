import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Result from '../views/Result.vue'
import History from '../views/History.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: Home,
      meta: { title: '智能旅行助手 - 规划' },
    },
    {
      path: '/result',
      name: 'result',
      component: Result,
      meta: { title: '智能旅行助手 - 结果' },
    },
    {
      path: '/history',
      name: 'history',
      component: History,
      meta: { title: '智能旅行助手 - 历史' },
    },
  ],
})

// 设置页面标题
router.beforeEach((to) => {
  if (to.meta.title) {
    document.title = String(to.meta.title)
  }
})

export default router

