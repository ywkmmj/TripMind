<script setup lang="ts">
import { message } from "ant-design-vue";
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import { useTripStore } from "../stores/trip";

const router = useRouter();
const tripStore = useTripStore();

async function loadTrips() {
  await tripStore.loadTripHistory();
}

async function openTrip(tripId: string) {
  try {
    await tripStore.loadTripDetail(tripId);
    message.success("已加载已保存行程。");
    router.push({ name: "result" });
  } catch (error) {
    message.error("读取行程详情失败。");
  }
}

async function removeTrip(tripId: string) {
  const confirmed = window.confirm("确定要删除这条已保存行程吗？删除后无法恢复。");
  if (!confirmed) {
    return;
  }

  try {
    await tripStore.deleteTrip(tripId);
    message.success("行程已删除。");
  } catch (error) {
    message.error("删除行程失败。");
  }
}

onMounted(() => {
  void loadTrips();
});
</script>

<template>
  <section class="history-page">
    <div class="history-header">
      <div>
        <h2>历史行程</h2>
        <p>这里会展示已经保存到后端数据库里的 itinerary 摘要。</p>
      </div>
      <button class="refresh-button" @click="loadTrips">刷新列表</button>
    </div>

    <div v-if="tripStore.isHistoryLoading" class="history-state">正在加载历史列表...</div>
    <div v-else-if="tripStore.tripHistory.length === 0" class="history-state">还没有已保存的行程。</div>

    <div v-else class="history-grid">
      <article
        v-for="item in tripStore.tripHistory"
        :key="item.tripId"
        class="history-card"
      >
        <div class="history-card__destination">{{ item.destination }}</div>
        <div class="history-card__trip-id">{{ item.tripId }}</div>
        <p class="history-card__summary">{{ item.summary }}</p>
        <div class="history-card__time">
          更新时间：{{ item.updatedAt || "未记录" }}
        </div>
        <div class="history-card__actions">
          <button class="history-card__button" @click="openTrip(item.tripId)">
            查看详情
          </button>
          <button
            class="history-card__button history-card__button--danger"
            :disabled="tripStore.isDeleting"
            @click="removeTrip(item.tripId)"
          >
            {{ tripStore.isDeleting ? "删除中..." : "删除行程" }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.history-page {
  display: grid;
  gap: 18px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 16px;
  padding: 24px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 22px 55px rgba(98, 116, 164, 0.12);
}

.history-header h2 {
  margin: 0 0 8px;
  font-size: 28px;
  color: #31456a;
}

.history-header p {
  margin: 0;
  color: #667085;
}

.refresh-button,
.history-card__button {
  border: none;
  border-radius: 14px;
  padding: 12px 16px;
  background: #0d9488;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
}

.history-card__actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.history-card__button--danger {
  background: rgba(239, 68, 68, 0.12);
  color: #c2410c;
}

.history-card__button:disabled {
  opacity: 0.65;
  cursor: wait;
}

.history-state {
  padding: 28px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 22px 55px rgba(98, 116, 164, 0.12);
  color: #667085;
  text-align: center;
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
}

.history-card {
  display: grid;
  gap: 12px;
  padding: 22px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 22px 55px rgba(98, 116, 164, 0.12);
}

.history-card__destination {
  font-size: 28px;
  font-weight: 800;
  color: #0f766e;
}

.history-card__trip-id {
  color: #8a94a6;
  font-size: 13px;
  word-break: break-all;
}

.history-card__summary {
  margin: 0;
  color: #475467;
  line-height: 1.7;
}

.history-card__time {
  color: #667085;
  font-size: 13px;
}
</style>
