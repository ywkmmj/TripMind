<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useTripStore } from './stores/trip'

const router = useRouter()
const route = useRoute()
const tripStore = useTripStore()

// 计算当前选中的标签
const activeTab = computed(() => route.name)

// 标签切换
const switchTab = (tab: string) => {
  if (tab === 'result' && !tripStore.hasCurrentItinerary) {
    return
  }
  router.push({ name: tab })
}
</script>

<template>
  <div class="app-shell">
    <header class="hero">
      <div class="hero__badge">Trip Planner Demo</div>
      <h1 class="hero__title">智能旅行助手</h1>

      <div class="hero__tabs">
        <button
          :class="['hero__tab', { 'hero__tab--active': activeTab === 'home' }]"
          @click="switchTab('home')"
        >
          规划页
        </button>
        <button
          :class="['hero__tab', { 'hero__tab--active': activeTab === 'result' }, { 'hero__tab--disabled': !tripStore.hasCurrentItinerary }]"
          :disabled="!tripStore.hasCurrentItinerary"
          @click="switchTab('result')"
        >
          结果页
        </button>
        <button
          :class="['hero__tab', { 'hero__tab--active': activeTab === 'history' }]"
          @click="switchTab('history')"
        >
          历史列表
        </button>
      </div>
    </header>

    <main class="page-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  min-width: 320px;
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  background: #f4f6f8;
  color: #1f2937;
}

:global(*) {
  box-sizing: border-box;
}

.app-shell {
  position: relative;
  min-height: 100vh;
  padding: 40px 24px 64px;
}

.hero {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  margin: 0 auto 28px;
  text-align: center;
}

.hero__badge {
  display: inline-flex;
  align-items: center;
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
  color: #0d9488;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.04em;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.hero__title {
  margin: 18px 0 0;
  color: #1e293b;
  font-size: 48px;
  line-height: 1.1;
}

.hero::before {
  content: "";
  position: absolute;
  inset: -24px 0 auto;
  height: 220px;
  z-index: -1;
  border-radius: 36px;
  background: #0d9488;
  box-shadow: 0 8px 24px rgba(13, 148, 136, 0.2);
}

.hero__tabs {
  display: inline-flex;
  gap: 10px;
  margin-top: 24px;
  padding: 8px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.18);
}

.hero__tab {
  border: none;
  border-radius: 14px;
  padding: 10px 18px;
  background: transparent;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
}

.hero__tab--active {
  background: #ffffff;
  color: #0d9488;
}

.hero__tab--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-content {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  margin: 0 auto;
}

@media (max-width: 768px) {
  .app-shell {
    padding: 24px 16px 40px;
  }

  .hero__title {
    font-size: 34px;
  }

  .hero::before {
    inset: -20px 0 auto;
    height: 230px;
  }
}
</style>

