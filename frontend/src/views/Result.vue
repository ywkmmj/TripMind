<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useTripStore } from '../stores/trip'
import AmapTripMap from '../components/AmapTripMap.vue'
import BusinessCard from '../components/BusinessCard.vue'
import {
  editTrip,
  fetchWeatherForecast,
  getMarkdownExportUrl,
  getPdfExportUrl,
  saveTrip,
} from '../services/api'
import type { WeatherForecastResponse } from '../types'

const router = useRouter()
const tripStore = useTripStore()

const stageNames: Record<string, string> = {
  'trip_planning': '行程规划',
  'map_enrichment': '地图数据补充',
  'weather_check': '天气检查',
  'ticket_check': '票价检查',
  'consistency_validation': '一致性校验',
}

const stageIcons: Record<string, string> = {
  'trip_planning': '📝',
  'map_enrichment': '🗺️',
  'weather_check': '🌤️',
  'ticket_check': '🎫',
  'consistency_validation': '✅',
}

const formatDuration = (ms: number | null | undefined): string => {
  if (ms == null) return '-'
  if (ms < 1000) {
    return `${ms}ms`
  }
  return `${(ms / 1000).toFixed(1)}s`
}

const exportingPdf = ref(false)
const exportingMarkdown = ref(false)
const editing = ref(false)
const editScope = ref('day_1')
const editInstruction = ref('这一天节奏更轻松一点，减少固定安排。')
const weatherLoading = ref(false)
const weatherError = ref('')
const weather = ref<WeatherForecastResponse | null>(null)

const formatShortDate = (dateText?: string | null): string => {
  if (!dateText) {
    return '待定'
  }

  const parts = dateText.split('-')
  if (parts.length !== 3) {
    return dateText
  }

  return `${parts[1]}-${parts[2]}`
}

const formatWeatherDate = (dateText?: string | null, week?: string | null): string => {
  const weekdayMap: Record<string, string> = {
    '1': '周一',
    '2': '周二',
    '3': '周三',
    '4': '周四',
    '5': '周五',
    '6': '周六',
    '7': '周日',
  }
  const weekday = week ? weekdayMap[week] || `周${week}` : ''
  return [formatShortDate(dateText), weekday].filter(Boolean).join(' ')
}

const budgetItems = computed(() => {
  if (!tripStore.currentItinerary) {
    return []
  }

  const budget = tripStore.currentItinerary.budgetBreakdown
  const items = [
    { label: '景点门票(人均)', value: `¥${budget.tickets.toFixed(0)}` },
    { label: '酒店住宿(人均)', value: `¥${budget.hotel.toFixed(0)}` },
    { label: '餐饮费用(人均)', value: `¥${budget.meals.toFixed(0)}` },
    { label: '交通费用(人均)', value: `¥${budget.transport.toFixed(0)}` },
  ]
  // 新增杂项明细
  if (budget.insurance > 0) {
    items.push({ label: '旅行保险(人均)', value: `¥${budget.insurance.toFixed(0)}` })
  }
  if (budget.contingency > 0) {
    items.push({ label: '应急备用金(人均)', value: `¥${budget.contingency.toFixed(0)}` })
  }
  if ((budget as any).shopping_misc > 0) {
    items.push({ label: '购物/杂项(人均)', value: `¥${(budget as any).shopping_misc.toFixed(0)}` })
  }
  // 团队总预算
  if (budget.travelers > 1 && (budget as any).total_for_group > 0) {
    items.push({ label: `团队总计(${budget.travelers}人)`, value: `¥${(budget as any).total_for_group.toFixed(0)}`, highlight: true })
  }
  return items
})

const dayBudgetItems = computed(() => {
  if (!tripStore.currentItinerary) {
    return []
  }

  return tripStore.currentItinerary.days.map((day) => {
    const tickets = day.spots.reduce((sum, spot) => sum + (spot.estimatedCost ?? 0), 0)
    const meals = day.meals.reduce((sum, meal) => sum + (meal.estimatedCost ?? 0), 0)
    const transport = day.transport.reduce((sum, item) => sum + (item.estimatedCost ?? 0), 0)
    const hotel = day.hotel?.estimatedCost ?? 0
    const total = tickets + meals + transport + hotel

    return {
      key: day.dayIndex,
      title: `第${day.dayIndex}天`,
      subtitle: day.theme || '未命名主题',
      tickets,
      meals,
      transport,
      hotel,
      total,
    }
  })
})

const mapPoints = computed(() => {
  if (!tripStore.currentItinerary) {
    return []
  }

  return tripStore.currentItinerary.days.flatMap((day) =>
    day.spots.map((spot) => ({
      key: `${day.dayIndex}-${spot.name}`,
      dayIndex: day.dayIndex,
      date: day.date || '待定',
      theme: day.theme || '未命名主题',
      name: spot.name,
      address: spot.address || spot.location || '待补充',
      latitude: spot.latitude,
      longitude: spot.longitude,
      poiId: spot.poiId,
      imageUrl: spot.imageUrl,
      description: spot.description || '暂无说明',
    }))
  )
})

const technicalTipKeywords = [
  'LLM',
  'RAG',
  'LangChain',
  'Chroma',
  '演示',
  '测试',
  '规则',
  '模型',
  '源码',
]

const rainWeatherKeywords = ['雨', '阵雨', '雷阵雨', '小雨', '中雨', '大雨']
const sunnyTipKeywords = ['防晒', '太阳', '日照', '晒']

const weatherText = computed(() => {
  if (!weather.value) {
    return ''
  }

  return weather.value.days
    .map((day) => `${day.dayWeather || ''}${day.nightWeather || ''}`)
    .join(' ')
})

const hasRainyWeather = computed(() => {
  return rainWeatherKeywords.some((keyword) => weatherText.value.includes(keyword))
})

const displayTips = computed(() => {
  if (!tripStore.currentItinerary) {
    return []
  }

  const tips = tripStore.currentItinerary.tips
    .map((tip) => tip.trim())
    .filter(Boolean)
    .filter((tip) => !technicalTipKeywords.some((keyword) => tip.includes(keyword)))

  const weatherAwareTips = hasRainyWeather.value
    ? tips.filter((tip) => !sunnyTipKeywords.some((keyword) => tip.includes(keyword)))
    : tips

  if (hasRainyWeather.value) {
    weatherAwareTips.push('天气可能有雨，建议随身带伞或轻便雨衣。')
    weatherAwareTips.push('阴雨天路面湿滑，建议穿防滑鞋。')
  }

  const uniqueTips = Array.from(new Set(weatherAwareTips))
  if (uniqueTips.length) {
    return uniqueTips
  }

  return [
    `建议根据${tripStore.currentItinerary.destination}当天实时天气准备雨具或薄外套。`,
  ]
})

const buildVisibleItinerary = () => {
  if (!tripStore.currentItinerary) {
    return null
  }

  return {
    ...tripStore.currentItinerary,
    tips: displayTips.value,
  }
}

const loadWeather = async () => {
  if (!tripStore.currentItinerary?.destination) {
    weather.value = null
    return
  }

  weatherLoading.value = true
  weatherError.value = ''
  try {
    weather.value = await fetchWeatherForecast(tripStore.currentItinerary.destination)
  } catch (error) {
    weather.value = null
    weatherError.value = '天气信息加载失败。'
  } finally {
    weatherLoading.value = false
  }
}

watch(
  () => tripStore.currentItinerary?.destination,
  () => {
    void loadWeather()
  },
  { immediate: true }
)

watch(
  () => tripStore.currentItinerary?.tripId,
  () => {
    const firstDay = tripStore.currentItinerary?.days[0]
    editScope.value = firstDay ? `day_${firstDay.dayIndex}` : 'day_1'
  },
  { immediate: true }
)

const openPdfExport = async () => {
  const itineraryToExport = buildVisibleItinerary()
  if (!itineraryToExport) {
    return
  }

  const exportWindow = window.open('about:blank', '_blank')
  exportingPdf.value = true
  try {
    await saveTrip(itineraryToExport)
    const exportUrl = getPdfExportUrl(itineraryToExport.tripId)
    if (exportWindow) {
      exportWindow.location.href = exportUrl
    } else {
      window.location.href = exportUrl
    }
  } catch (error) {
    exportWindow?.close()
    message.error('导出 PDF 前同步当前行程失败。')
  } finally {
    exportingPdf.value = false
  }
}

const openMarkdownExport = async () => {
  const itineraryToExport = buildVisibleItinerary()
  if (!itineraryToExport) {
    return
  }

  const exportWindow = window.open('about:blank', '_blank')
  exportingMarkdown.value = true
  try {
    await saveTrip(itineraryToExport)
    const exportUrl = getMarkdownExportUrl(itineraryToExport.tripId)
    if (exportWindow) {
      exportWindow.location.href = exportUrl
    } else {
      window.location.href = exportUrl
    }
  } catch (error) {
    exportWindow?.close()
    message.error('导出 Markdown 前同步当前行程失败。')
  } finally {
    exportingMarkdown.value = false
  }
}

const handleSave = async () => {
  const itineraryToSave = buildVisibleItinerary()
  if (!itineraryToSave) {
    return
  }

  try {
    await tripStore.saveTrip()
    message.success('行程已保存')
  } catch (error) {
  }
}

const handleEdit = async () => {
  if (!tripStore.currentItinerary) {
    return
  }

  const instruction = editInstruction.value.trim()
  if (!instruction) {
    message.warning('请先输入想要调整行程的内容。')
    return
  }

  editing.value = true
  try {
    const updatedItinerary = await editTrip({
      tripId: tripStore.currentItinerary.tripId,
      currentItinerary: tripStore.currentItinerary,
      userInstruction: instruction,
      editScope: editScope.value,
      preserveConstraints: ['保留预算结构', '保留目的地和旅行日期'],
    })
    tripStore.setItinerary(updatedItinerary)
    message.success('行程已智能调整')
  } catch (error) {
    message.error('智能调整失败，请稍后再试')
  } finally {
    editing.value = false
  }
}
</script>

<template>
  <section v-if="tripStore.currentItinerary" class="result-page">
    <aside class="sidebar-card">
      <div class="sidebar-card__title">行程导航</div>
      <ul class="sidebar-list">
        <li>行程概览</li>
        <li>预算明细</li>
        <li>按天花费</li>
        <li>智能调整</li>
        <li>景点地图</li>
        <li>天气信息</li>
        <li>点位明细</li>
        <li>每日行程</li>
      </ul>

      <div class="sidebar-actions">
        <button class="back-button" @click="router.push({ name: 'home' })">返回规划页</button>
        <button class="save-button" :disabled="tripStore.isSaving" @click="handleSave">
          {{ tripStore.isSaving ? '保存中...' : '保存行程' }}
        </button>
        <button class="history-button" @click="router.push({ name: 'history' })">历史列表</button>
        <button class="export-button" :disabled="exportingPdf" @click="openPdfExport">
          {{ exportingPdf ? '准备 PDF...' : '导出 PDF' }}
        </button>
        <button
          class="export-button export-button--light"
          :disabled="exportingMarkdown"
          @click="openMarkdownExport"
        >
          {{ exportingMarkdown ? '准备中...' : '导出 Markdown' }}
        </button>
      </div>
    </aside>

    <div class="result-grid">
      <section class="result-card">
        <div class="result-card__title">{{ tripStore.currentItinerary.destination }}旅行计划</div>
        <div class="info-row"><strong>行程 ID：</strong>{{ tripStore.currentItinerary.tripId }}</div>
        <div class="info-row">
          <strong>日期：</strong>
          {{ tripStore.currentItinerary.days[0]?.date || '待定' }} 至
          {{ tripStore.currentItinerary.days[tripStore.currentItinerary.days.length - 1]?.date || '待定' }}
        </div>
        <div class="info-row"><strong>地点：</strong>{{ tripStore.currentItinerary.destination }}</div>
        <div class="info-row summary-text">{{ tripStore.currentItinerary.summary }}</div>
        <div v-if="displayTips.length" class="overview-tips">
          <div class="overview-tips__title">旅行提示</div>
          <ul>
            <li v-for="tip in displayTips" :key="tip">{{ tip }}</li>
          </ul>
        </div>
      </section>

      <section v-if="tripStore.pipelineSummary" class="result-card">
        <div class="result-card__title">⚡ 生成耗时</div>
        <div class="gen-time-total">
          <span class="gen-time-label">总耗时</span>
          <span class="gen-time-value">{{ formatDuration(tripStore.pipelineSummary.totalDurationMs) }}</span>
        </div>
        <div class="gen-time-stages">
          <div
            v-for="(stageResult, stageType) in tripStore.pipelineSummary.stageResults"
            :key="stageType"
            class="gen-time-stage"
          >
            <span class="gen-stage-icon">{{ stageIcons[stageType] || '📋' }}</span>
            <span class="gen-stage-name">{{ stageNames[stageType] || stageType }}</span>
            <span :class="['gen-stage-status', stageResult.status.toLowerCase()]">
              {{ stageResult.status === 'COMPLETED' ? '✅' : stageResult.status === 'SKIPPED' ? '⚠️' : '❌' }}
            </span>
            <span class="gen-stage-duration">{{ formatDuration(stageResult.durationMs) }}</span>
          </div>
        </div>
      </section>

      <section class="result-card">
        <div class="result-card__title">预算明细</div>
        <div class="budget-grid">
          <div v-for="item in budgetItems" :key="item.label"
             :class="['budget-box', { 'budget-box--highlight': item.highlight }]">
            <div class="budget-box__label">{{ item.label }}</div>
            <div class="budget-box__value">{{ item.value }}</div>
          </div>
        </div>
        <div v-if="tripStore.currentItinerary?.budgetBreakdown?.budget_alert"
             class="budget-alert">
          {{ (tripStore.currentItinerary.budgetBreakdown as any).budget_alert }}
        </div>
        <div class="budget-total">
          <span>预估总费用（人均）</span>
          <strong>¥{{ tripStore.currentItinerary.estimatedBudget.toFixed(0) }}</strong>
        </div>
      </section>

      <section class="result-card result-card--map">
        <div class="result-card__title">景点地图</div>
        <AmapTripMap :points="mapPoints" />
      </section>

      <section class="result-card result-card--weather">
        <div class="result-card__title">天气信息</div>

        <div v-if="weatherLoading" class="weather-state">正在加载天气信息...</div>
        <div v-else-if="weatherError" class="weather-state">{{ weatherError }}</div>
        <div v-else-if="weather" class="weather-grid">
          <article
            v-for="day in weather.days"
            :key="`${day.date}-${day.week}`"
            class="weather-card"
          >
            <div class="weather-card__date">
              {{ formatWeatherDate(day.date, day.week) }}
            </div>
            <div class="weather-card__temp">
              {{ day.dayTemp || '-' }}° / {{ day.nightTemp || '-' }}°
            </div>
            <div class="weather-card__desc">白天：{{ day.dayWeather || '未知' }}</div>
            <div class="weather-card__desc">夜间：{{ day.nightWeather || '未知' }}</div>
          </article>
        </div>
        <div v-else class="weather-state">暂无天气信息。</div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title">智能调整行程</div>
        <div class="edit-panel">
          <div class="edit-panel__controls">
            <label class="edit-field">
              <span>调整范围</span>
              <select v-model="editScope">
                <option
                  v-for="day in tripStore.currentItinerary.days"
                  :key="day.dayIndex"
                  :value="`day_${day.dayIndex}`"
                >
                  第{{ day.dayIndex }}天 · {{ day.theme || '未命名主题' }}
                </option>
              </select>
            </label>
            <button
              class="edit-submit-button"
              :disabled="editing"
              @click="handleEdit"
            >
              {{ editing ? '调整中...' : '智能调整' }}
            </button>
          </div>
          <textarea
            v-model="editInstruction"
            class="edit-textarea"
            :rows="3"
            placeholder="例如：第二天轻松一点，不要安排太满；第三天想换成适合看日落的地点。"
          ></textarea>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title">按天花费</div>
        <div class="day-budget-grid">
          <article
            v-for="item in dayBudgetItems"
            :key="item.key"
            class="day-budget-card"
          >
            <div class="day-budget-card__header">
              <span>{{ item.title }}</span>
              <span>{{ item.subtitle }}</span>
            </div>
            <div class="day-budget-card__body">
              <div class="day-budget-row">
                <span>门票</span>
                <strong>¥{{ item.tickets.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>餐饮</span>
                <strong>¥{{ item.meals.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>交通</span>
                <strong>¥{{ item.transport.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row">
                <span>住宿</span>
                <strong>¥{{ item.hotel.toFixed(0) }}</strong>
              </div>
              <div class="day-budget-row day-budget-row--total">
                <span>当日合计</span>
                <strong>¥{{ item.total.toFixed(0) }}</strong>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title">地图点位明细</div>
        <div class="point-grid">
          <article v-for="point in mapPoints" :key="point.key" class="point-card">
            <div class="point-card__header">
              <span>第{{ point.dayIndex }}天 · {{ point.name }}</span>
              <span>{{ formatShortDate(point.date) }}</span>
            </div>

            <div class="point-card__body">
              <div
                v-if="point.imageUrl"
                class="point-card__image"
                :style="{ backgroundImage: `url(${point.imageUrl})` }"
              ></div>
              <div v-else class="point-card__image point-card__image--empty">
                暂无景点图片
              </div>
              <div class="point-card__line">
                <strong>主题：</strong>
                <span>{{ point.theme }}</span>
              </div>
              <div class="point-card__line">
                <strong>地址：</strong>
                <span>{{ point.address }}</span>
              </div>
              <div class="point-card__desc">{{ point.description }}</div>
            </div>
          </article>
        </div>
      </section>

      <section class="result-card result-card--full">
        <div class="result-card__title">每日行程</div>
        <div class="day-list">
          <details
            v-for="day in tripStore.currentItinerary.days"
            :key="day.dayIndex"
            class="day-card"
            :open="day.dayIndex === 1"
          >
            <summary class="day-card__header">
              <span>第{{ day.dayIndex }}天 · {{ day.theme || '未命名主题' }}</span>
              <span class="day-card__meta">{{ formatShortDate(day.date) }}</span>
            </summary>

            <div class="day-card__body">
              <div v-if="day.spots && day.spots.length > 0" class="day-section">
                <div class="day-section__title">📍 景点安排</div>
                <div class="business-card-grid">
                  <BusinessCard
                    v-for="spot in day.spots"
                    :key="spot.name"
                    :name="spot.name"
                    :image-url="spot.imageUrl"
                    :images="spot.images"
                    :address="spot.address"
                    :rating="spot.rating"
                    :opening-hours="spot.openingHours"
                    :phone="spot.phone"
                    :website="spot.website"
                    :tags="spot.tags"
                    :price-level="spot.priceLevel"
                  />
                </div>
              </div>

              <div v-if="day.meals && day.meals.length > 0" class="day-section">
                <div class="day-section__title">🍽️ 餐饮安排</div>
                <div class="business-card-grid">
                  <BusinessCard
                    v-for="meal in day.meals"
                    :key="meal.name"
                    :name="meal.name"
                    :image-url="meal.imageUrl"
                    :images="meal.images"
                    :address="meal.address"
                    :rating="meal.rating"
                    :opening-hours="meal.openingHours"
                    :phone="meal.phone"
                    :website="meal.website"
                    :tags="meal.tags"
                    :price-per-person="meal.pricePerPerson"
                    :cuisine="meal.cuisine"
                  />
                </div>
              </div>

              <div v-if="day.hotel" class="day-section">
                <div class="day-section__title">🏨 住宿安排</div>
                <div class="business-card-grid">
                  <BusinessCard
                    :name="day.hotel.name"
                    :image-url="day.hotel.imageUrl"
                    :images="day.hotel.images"
                    :address="day.hotel.address"
                    :rating="day.hotel.rating"
                    :opening-hours="day.hotel.openingHours"
                    :phone="day.hotel.phone"
                    :website="day.hotel.website"
                    :tags="day.hotel.tags"
                    :price-per-night="day.hotel.pricePerNight"
                    :facilities="day.hotel.facilities"
                  />
                </div>
              </div>

              <div v-if="day.transport.length > 0" class="day-section">
                <div class="day-section__title">🚗 交通信息</div>
                <div class="day-card__transport-list">
                  <div
                    v-for="(transport, index) in day.transport"
                    :key="index"
                    class="day-card__transport-item"
                  >
                    <div class="transport-icon">{{ transport.mode.includes('步行') ? '🚶' : transport.mode.includes('公交') ? '🚌' : transport.mode.includes('地铁') ? '🚇' : '🚗' }}</div>
                    <div class="transport-content">
                      <div class="transport-mode">{{ transport.mode }}</div>
                      <div class="transport-details">
                        <span v-if="transport.fromPlace || transport.toPlace">
                          {{ transport.fromPlace || '起点' }} → {{ transport.toPlace || '终点' }}
                        </span>
                        <span v-if="transport.distanceKm != null">
                          · {{ transport.distanceKm.toFixed(2) }} km
                        </span>
                        <span v-if="transport.estimatedMinutes != null">
                          · {{ transport.estimatedMinutes }} 分钟
                        </span>
                        <span v-if="transport.estimatedCost != null && transport.estimatedCost > 0">
                          · ¥{{ transport.estimatedCost.toFixed(0) }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="day.notes.length > 0" class="day-section">
                <div class="day-section__title">📝 备注</div>
                <ul class="day-notes">
                  <li v-for="(note, index) in day.notes" :key="index">{{ note }}</li>
                </ul>
              </div>
            </div>
          </details>
        </div>
      </section>
    </div>
  </section>

  <section v-else class="empty-state">
    <div class="empty-state__card">
      <h2>还没有生成结果</h2>
      <p>先回到规划页生成一条 itinerary，结果页就会开始展示真实数据。</p>
      <button class="back-button" @click="router.push({ name: 'home' })">返回规划页</button>
    </div>
  </section>
</template>

<style scoped>
.result-page {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 22px;
}

.sidebar-card,
.result-card,
.empty-state__card {
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 22px 55px rgba(98, 116, 164, 0.12);
  backdrop-filter: blur(14px);
}

.sidebar-card {
  align-self: start;
  padding: 18px;
}

.sidebar-card__title,
.result-card__title {
  margin-bottom: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #0d9488;
  color: #ffffff;
  font-size: 15px;
  font-weight: 800;
}

.sidebar-list {
  display: grid;
  gap: 12px;
  padding: 0;
  margin: 0 0 18px;
  list-style: none;
  color: #475467;
  font-size: 14px;
}

.sidebar-actions {
  display: grid;
  gap: 10px;
}

.back-button,
.save-button,
.history-button,
.export-button {
  width: 100%;
  border: none;
  border-radius: 14px;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
}

.back-button {
  background: rgba(13, 148, 136, 0.08);
  color: #0d9488;
}

.save-button {
  background: #0d9488;
  color: #ffffff;
}

.save-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.export-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.history-button {
  background: rgba(13, 148, 136, 0.08);
  color: #0d9488;
}

.export-button {
  background: rgba(59, 130, 246, 0.12);
  color: #3568d4;
}

.export-button--light {
  background: rgba(16, 185, 129, 0.12);
  color: #0f8c63;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.result-card {
  padding: 18px;
}

.result-card--map,
.result-card--weather {
  min-height: 330px;
}

.result-card--full {
  grid-column: 1 / -1;
}

.info-row {
  margin-bottom: 10px;
  color: #475467;
  line-height: 1.7;
}

.summary-text {
  margin-top: 14px;
}

.overview-tips {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(13, 148, 136, 0.05);
  border: 1px solid rgba(13, 148, 136, 0.1);
}

.overview-tips__title {
  margin-bottom: 8px;
  color: #465467;
  font-weight: 800;
}

.overview-tips ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
  color: #5d6675;
  line-height: 1.7;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.budget-box {
  padding: 16px;
  border-radius: 16px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.budget-box__label {
  color: #667085;
  font-size: 13px;
}

.budget-box__value {
  margin-top: 10px;
  color: #3b82f6;
  font-size: 22px;
  font-weight: 800;
}

.budget-box--highlight {
  background: rgba(13, 148, 136, 0.06);
  border-color: rgba(13, 148, 136, 0.2);
}

.budget-box--highlight .budget-box__value {
  color: #0d9488;
}

.budget-alert {
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: 12px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  font-size: 13px;
  line-height: 1.6;
}

.budget-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding: 16px 18px;
  border-radius: 18px;
  background: #0d9488;
  color: #ffffff;
}

.budget-total strong {
  font-size: 28px;
}

.gen-time-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding: 16px 18px;
  border-radius: 18px;
  background: rgba(13, 148, 136, 0.05);
  border: 1px solid rgba(13, 148, 136, 0.1);
}

.gen-time-label {
  color: #465467;
  font-weight: 800;
  font-size: 14px;
}

.gen-time-value {
  font-family: monospace;
  font-size: 24px;
  font-weight: 800;
  color: #0d9488;
}

.gen-time-stages {
  display: grid;
  gap: 10px;
}

.gen-time-stage {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.gen-stage-icon {
  font-size: 20px;
}

.gen-stage-name {
  flex: 1;
  font-weight: 600;
  font-size: 13px;
  color: #475467;
}

.gen-stage-duration {
  font-family: monospace;
  font-size: 13px;
  color: #0d9488;
  font-weight: 800;
}

.weather-state {
  color: #667085;
  line-height: 1.8;
}

.weather-grid {
  display: grid;
  gap: 12px;
}

.weather-card {
  padding: 14px;
  border-radius: 16px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.weather-card__date {
  color: #465467;
  font-weight: 800;
}

.weather-card__temp {
  margin: 8px 0;
  color: #3b82f6;
  font-size: 24px;
  font-weight: 800;
}

.weather-card__desc {
  color: #667085;
  line-height: 1.7;
}

.edit-panel {
  display: grid;
  gap: 14px;
}

.edit-panel__controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 12px;
  align-items: end;
}

.edit-field {
  display: grid;
  gap: 8px;
  color: #465467;
  font-weight: 800;
}

.edit-field select,
.edit-textarea {
  width: 100%;
  border: 1px solid rgba(98, 116, 164, 0.18);
  border-radius: 14px;
  background: #fbfcff;
  color: #334155;
  font: inherit;
  outline: none;
}

.edit-field select {
  min-height: 44px;
  padding: 0 14px;
}

.edit-textarea {
  resize: vertical;
  min-height: 92px;
  padding: 12px 14px;
  line-height: 1.7;
}

.edit-field select:focus,
.edit-textarea:focus {
  border-color: rgba(13, 148, 136, 0.5);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.1);
}

.edit-submit-button {
  min-height: 44px;
  border: none;
  border-radius: 14px;
  background: #0d9488;
  color: #ffffff;
  font-weight: 800;
  cursor: pointer;
}

.edit-submit-button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.day-budget-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.day-budget-card {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
}

.day-budget-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(13, 148, 136, 0.06);
  color: #334155;
  font-weight: 800;
}

.day-budget-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.day-budget-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #475467;
}

.day-budget-row--total {
  padding-top: 10px;
  border-top: 1px solid rgba(98, 116, 164, 0.08);
  color: #0d9488;
}

.point-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.point-card {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
}

.point-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(13, 148, 136, 0.06);
  color: #334155;
  font-weight: 800;
}

.point-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.point-card__image {
  min-height: 150px;
  border-radius: 14px;
  background-position: center;
  background-size: cover;
  background-color: #f0fdfa;
}

.point-card__image--empty {
  display: grid;
  place-items: center;
  color: #94a3b8;
  font-weight: 800;
  background: #f0fdfa;
}

.point-card__line {
  color: #475467;
  line-height: 1.7;
}

.point-card__desc {
  padding-top: 10px;
  border-top: 1px solid rgba(98, 116, 164, 0.08);
  color: #667085;
  line-height: 1.7;
}

.day-list {
  display: grid;
  gap: 12px;
}

.day-card {
  border-radius: 18px;
  border: 1px solid rgba(98, 116, 164, 0.08);
  background: #fbfcff;
  overflow: hidden;
}

.day-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(13, 148, 136, 0.06);
  color: #334155;
  font-weight: 800;
  cursor: pointer;
  list-style: none;
}

.day-card__header::-webkit-details-marker {
  display: none;
}

.day-card__header::after {
  content: '展开';
  flex: 0 0 auto;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(13, 148, 136, 0.1);
  color: #0d9488;
  font-size: 12px;
}

.day-card[open] .day-card__header::after {
  content: '收起';
}

.day-card__meta {
  margin-left: auto;
  color: #667085;
  font-size: 13px;
}

.day-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.day-card__section {
  color: #475467;
  line-height: 1.7;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 360px;
}

.empty-state__card {
  max-width: 560px;
  padding: 36px;
  text-align: center;
}

.empty-state__card h2 {
  margin: 0 0 12px;
}

.empty-state__card p {
  margin: 0 0 18px;
  color: #667085;
  line-height: 1.7;
}

.day-section {
  margin-bottom: 20px;
}

.day-section:last-child {
  margin-bottom: 0;
}

.day-section__title {
  font-size: 14px;
  font-weight: 800;
  color: #465467;
  margin-bottom: 12px;
  padding-left: 4px;
}

.business-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}

.day-card__transport-list {
  display: grid;
  gap: 10px;
}

.day-card__transport-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8faff;
  border: 1px solid rgba(98, 116, 164, 0.08);
}

.transport-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.transport-content {
  flex: 1;
}

.transport-mode {
  font-weight: 800;
  color: #465467;
  font-size: 14px;
  margin-bottom: 4px;
}

.transport-details {
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.day-notes {
  margin: 0;
  padding-left: 20px;
  display: grid;
  gap: 8px;
  color: #5d6675;
  line-height: 1.7;
}

@media (max-width: 960px) {
  .result-page {
    grid-template-columns: 1fr;
  }

  .result-grid {
    grid-template-columns: 1fr;
  }

  .edit-panel__controls {
    grid-template-columns: 1fr;
  }

  .business-card-grid {
    grid-template-columns: 1fr;
  }
}
</style>

