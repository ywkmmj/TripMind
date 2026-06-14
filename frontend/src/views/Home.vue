<script setup lang="ts">
import { computed, reactive, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { message } from 'ant-design-vue'
import { useTripStore } from '../stores/trip'
import { generateTripWithPipeline } from '../services/api'
import type { TripRequestPayload, PipelineResponse, StageResult } from '../types'

const router = useRouter()
const tripStore = useTripStore()

const STORAGE_KEY = 'trip-planner-form-state'

interface SavedFormState {
  destination: string
  startDate: string
  endDate: string
  travelers: string
  budget: string
  hotelLevel: string
  pace: string
  preferences: string[]
  dietaryPreferences: string[]
  notes: string
  generationMode: 'fast' | 'full'
}

const preferenceOptions = [
  '自然风景',
  '拍照',
  '美食',
  '古镇',
  '休闲',
]

const dietaryOptions = [
  '少辣',
  '不吃香菜',
  '不吃葱',
]

const formatDate = (date: Date): string => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const today = new Date()
const todayPlus2 = new Date(today)
todayPlus2.setDate(todayPlus2.getDate() + 2)

const getDefaultFormState = (): SavedFormState => ({
  destination: '',
  startDate: formatDate(today),
  endDate: formatDate(todayPlus2),
  travelers: '',
  budget: '',
  hotelLevel: '舒适型',
  pace: '轻松',
  preferences: [],
  dietaryPreferences: [],
  notes: '',
  generationMode: 'fast' as const,
})

const loadFormState = (): SavedFormState => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      return { ...getDefaultFormState(), ...JSON.parse(saved) }
    }
  } catch (e) {
    console.error('Failed to load form state', e)
  }
  return getDefaultFormState()
}

const saveFormState = () => {
  try {
    const state: SavedFormState = {
      destination: formState.destination,
      startDate: formState.startDate,
      endDate: formState.endDate,
      travelers: formState.travelers,
      budget: formState.budget,
      hotelLevel: formState.hotelLevel,
      pace: formState.pace,
      preferences: [...formState.preferences],
      dietaryPreferences: [...formState.dietaryPreferences],
      notes: formState.notes,
      generationMode: generationMode.value,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch (e) {
    console.error('Failed to save form state', e)
  }
}

const clearFormState = () => {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    console.error('Failed to clear form state', e)
  }
}

const savedState = loadFormState()

const formState = reactive({
  destination: savedState.destination,
  startDate: savedState.startDate,
  endDate: savedState.endDate,
  travelers: savedState.travelers,
  budget: savedState.budget,
  hotelLevel: savedState.hotelLevel,
  pace: savedState.pace,
  preferences: savedState.preferences,
  dietaryPreferences: savedState.dietaryPreferences,
  notes: savedState.notes,
})

const generationMode = ref<'fast' | 'full'>(savedState.generationMode)

const dayCount = computed(() => {
  const start = new Date(formState.startDate)
  const end = new Date(formState.endDate)
  const diff = end.getTime() - start.getTime()
  return Number.isNaN(diff) ? 0 : Math.max(Math.floor(diff / 86400000) + 1, 0)
})

const startTime = ref<number | null>(null)
const elapsedTime = ref(0)
let timerInterval: number | null = null

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

const completedStages = ref<StageResult[]>([])
const currentStage = ref<string | null>(null)
const pipelineSummary = ref<any>(null)

const formatDuration = (ms: number): string => {
  if (ms < 1000) {
    return `${ms}ms`
  }
  return `${(ms / 1000).toFixed(1)}s`
}

const formatElapsedTime = (ms: number): string => {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) {
    return `${minutes}分${remainingSeconds}秒`
  }
  return `${remainingSeconds}秒`
}

const startTimer = () => {
  startTime.value = Date.now()
  elapsedTime.value = 0
  completedStages.value = []
  currentStage.value = null
  pipelineSummary.value = null

  timerInterval = window.setInterval(() => {
    if (startTime.value !== null) {
      elapsedTime.value = Date.now() - startTime.value
    }
  }, 100)
}

const stopTimer = () => {
  if (timerInterval !== null) {
    clearInterval(timerInterval)
    timerInterval = null
  }
}

const handleReset = () => {
  const defaultState = getDefaultFormState()
  formState.destination = defaultState.destination
  formState.startDate = defaultState.startDate
  formState.endDate = defaultState.endDate
  formState.travelers = defaultState.travelers
  formState.budget = defaultState.budget
  formState.hotelLevel = defaultState.hotelLevel
  formState.pace = defaultState.pace
  formState.preferences = defaultState.preferences
  formState.dietaryPreferences = defaultState.dietaryPreferences
  formState.notes = defaultState.notes
  generationMode.value = defaultState.generationMode
  clearFormState()
  message.success('表单已重置')
}

const handleSubmit = async () => {
  if (!formState.destination) {
    message.error('请输入目的地城市')
    return
  }
  const travelersNum = Number(formState.travelers)
  if (!formState.travelers || isNaN(travelersNum) || travelersNum <= 0) {
    message.error('请输入有效的人数')
    return
  }

  // 构造完全纯净的对象，避免 Vue 响应式系统添加的内部属性
  const payload: TripRequestPayload = {
    destination: String(formState.destination || ''),
    startDate: String(formState.startDate || ''),
    endDate: String(formState.endDate || ''),
    days: Number(dayCount.value),
    travelers: Number(formState.travelers),
    budget: formState.budget ? Number(formState.budget) : 0,
    preferences: Array.isArray(formState.preferences) ? [...formState.preferences] : [],
    pace: formState.pace ? String(formState.pace) : null,
    dietaryPreferences: Array.isArray(formState.dietaryPreferences) ? [...formState.dietaryPreferences] : [],
    hotelLevel: formState.hotelLevel ? String(formState.hotelLevel) : null,
    specialNotes: formState.notes ? String(formState.notes) : null,
  }

  tripStore.setLoading(true)
  startTimer()

  try {
    const response: PipelineResponse = await generateTripWithPipeline(payload, generationMode.value)
    
    if (response.success && response.itinerary) {
      pipelineSummary.value = response.summary
      tripStore.setPipelineSummary(response.summary)
      tripStore.setItinerary(response.itinerary)
      message.success('行程生成成功')
      router.push({ name: 'result' })
    } else {
      message.error(response.finalError || '行程生成失败')
    }
  } catch (error) {
    tripStore.setError("行程生成失败")
    if (axios.isAxiosError(error)) {
      if (error.code === 'ECONNABORTED') {
        message.error('行程生成超时，请稍后再试')
      } else if (error.response) {
        message.error(`行程生成失败：后端返回 ${error.response.status}`)
      } else {
        message.error('行程生成失败，请检查前端到后端的连接')
      }
    } else {
      message.error('行程生成失败，请检查后端地址或服务状态')
    }
  } finally {
    stopTimer()
    tripStore.setLoading(false)
  }
}

// Watch form state changes and save automatically
watch(
  () => [
    formState.destination,
    formState.startDate,
    formState.endDate,
    formState.travelers,
    formState.budget,
    formState.hotelLevel,
    formState.pace,
    formState.preferences,
    formState.dietaryPreferences,
    formState.notes,
    generationMode.value,
  ],
  () => {
    saveFormState()
  },
  { deep: true }
)

// Save on unmount as a fallback
onUnmounted(() => {
  stopTimer()
  saveFormState()
})
</script>

<template>
  <section class="home-page">
    <div class="planner-card">
      <div class="section-title">
        <span class="section-title__icon">📍</span>
        <span>目的地与日期</span>
      </div>

      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :md="8">
          <label class="field-label">目的地城市</label>
          <a-input v-model:value="formState.destination" placeholder="请输入目的地" />
        </a-col>
        <a-col :xs="24" :md="5">
          <label class="field-label">开始日期</label>
          <a-input v-model:value="formState.startDate" />
        </a-col>
        <a-col :xs="24" :md="5">
          <label class="field-label">结束日期</label>
          <a-input v-model:value="formState.endDate" />
        </a-col>
        <a-col :xs="12" :md="3">
          <label class="field-label">人数</label>
          <a-input-number v-model:value="formState.travelers" :min="1" style="width: 100%" />
        </a-col>
        <a-col :xs="12" :md="3">
          <label class="field-label">旅行天数</label>
          <div class="pill-box">{{ dayCount }} 天</div>
        </a-col>
      </a-row>
    </div>

    <div class="planner-card">
      <div class="section-title">
        <span class="section-title__icon">⚙️</span>
        <span>偏好设置</span>
      </div>

      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :md="8">
          <label class="field-label">节奏偏好</label>
          <a-select
            v-model:value="formState.pace"
            :options="[
              { label: '轻松', value: '轻松' },
              { label: '适中', value: '适中' },
              { label: '紧凑', value: '紧凑' }
            ]"
          />
        </a-col>
        <a-col :xs="24" :md="8">
          <label class="field-label">住宿偏好</label>
          <a-select
            v-model:value="formState.hotelLevel"
            :options="[
              { label: '舒适型', value: '舒适型' },
              { label: '高档型', value: '高档型' },
              { label: '经济型', value: '经济型' }
            ]"
          />
        </a-col>
        <a-col :xs="24" :md="8">
          <label class="field-label">预算</label>
          <a-input-number v-model:value="formState.budget" :min="0" style="width: 100%" />
        </a-col>
      </a-row>

      <div class="checkbox-area">
        <label class="field-label">旅行偏好</label>
        <a-checkbox-group v-model:value="formState.preferences" :options="preferenceOptions" />
      </div>

      <div class="checkbox-area">
        <label class="field-label">饮食偏好</label>
        <a-checkbox-group
          v-model:value="formState.dietaryPreferences"
          :options="dietaryOptions"
        />
      </div>
    </div>

    <div class="planner-card">
      <div class="section-title">
        <span class="section-title__icon">💬</span>
        <span>生成模式</span>
      </div>
      <a-radio-group v-model:value="generationMode">
        <a-radio value="fast">🚀 快速模式（仅行程规划）</a-radio>
        <a-radio value="full">✨ 完整模式（含地图/天气/票价）</a-radio>
      </a-radio-group>
    </div>

    <div class="planner-card">
      <div class="section-title">
        <span class="section-title__icon">💬</span>
        <span>额外要求</span>
      </div>
      <a-textarea
        v-model:value="formState.notes"
        :rows="4"
        placeholder="输入想要保留的偏好、节奏和备注"
      />
    </div>

    <div class="submit-panel">
      <div class="submit-buttons">
        <button
          class="submit-panel__button submit-panel__button--secondary"
          :disabled="tripStore.isLoading"
          @click="handleReset"
        >
          重置表单
        </button>
        <button
          class="submit-panel__button"
          :disabled="tripStore.isLoading"
          @click="handleSubmit"
        >
          <span v-if="!tripStore.isLoading">开始规划</span>
          <span v-else class="loading-text">
            <span class="pulse-dot"></span>
            <span class="pulse-dot"></span>
            <span class="pulse-dot"></span>
            正在生成中...
          </span>
        </button>
      </div>

      <div v-if="tripStore.isLoading" class="timer-display">
        <div class="timer-text">
          <span class="timer-icon">⏱️</span>
          已耗时：{{ formatElapsedTime(elapsedTime) }}
        </div>
      </div>

      <div v-if="tripStore.isLoading" class="stages-display">
        <div
          v-for="(stage, stageType) in (generationMode === 'full' ? ['trip_planning', 'map_enrichment', 'weather_check', 'ticket_check', 'consistency_validation'] : ['trip_planning'])"
          :key="stageType"
          class="stage-item"
        >
          <span class="stage-icon">{{ stageIcons[stageType] || '📋' }}</span>
          <span class="stage-name">{{ stageNames[stageType] || stageType }}</span>
          <span class="stage-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </span>
        </div>
      </div>

      <div v-if="pipelineSummary && !tripStore.isLoading" class="summary-display">
        <div class="summary-title">✅ 生成完成！耗时：{{ formatDuration(pipelineSummary.totalDurationMs || 0) }}</div>
        <div class="summary-stages">
          <div
            v-for="(stageResult, stageType) in pipelineSummary.stageResults"
            :key="stageType"
            class="summary-stage"
          >
            <span class="stage-icon">{{ stageIcons[stageType] || '📋' }}</span>
            <span class="stage-name">{{ stageNames[stageType] || stageType }}</span>
            <span :class="['stage-status', stageResult.status.toLowerCase()]">
              {{ stageResult.status === 'COMPLETED' ? '✅' : stageResult.status === 'SKIPPED' ? '⚠️' : '❌' }}
            </span>
            <span class="stage-duration">{{ formatDuration(stageResult.durationMs || 0) }}</span>
          </div>
        </div>
      </div>

      <div class="submit-panel__status">
        当前已接上 /trip/generate-multi-stage，生成成功后会直接展示真实 itinerary。
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-page {
  display: grid;
  gap: 18px;
}

.planner-card {
  padding: 24px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 22px 55px rgba(98, 116, 164, 0.12);
  backdrop-filter: blur(14px);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(13, 148, 136, 0.15);
  color: #334155;
  font-size: 16px;
  font-weight: 800;
}

.section-title__icon {
  font-size: 18px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  color: #667085;
  font-size: 13px;
  font-weight: 800;
}

.pill-box {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  border-radius: 12px;
  background: #0d9488;
  color: #ffffff;
  font-weight: 800;
}

.checkbox-area {
  margin-top: 18px;
}

.submit-panel {
  padding: 12px 8px 0;
  text-align: center;
}

.submit-buttons {
  display: flex;
  gap: 12px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
}

.submit-panel__button {
  min-width: 180px;
  border: none;
  border-radius: 999px;
  padding: 14px 28px;
  background: #0d9488;
  color: #ffffff;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.3);
  transition: all 0.2s ease;
}

.submit-panel__button.submit-panel__button--secondary {
  background: rgba(13, 148, 136, 0.08);
  color: #0d9488;
  box-shadow: none;
  border: 1.5px solid rgba(13, 148, 136, 0.25);
}

.submit-panel__button.submit-panel__button--secondary:hover {
  background: rgba(13, 148, 136, 0.15);
  border-color: rgba(13, 148, 136, 0.4);
}

.submit-panel__button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.loading-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: white;
  animation: pulse 1.4s infinite ease-in-out;
}

.pulse-dot:nth-child(1) {
  animation-delay: 0s;
}

.pulse-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.pulse-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes pulse {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.timer-display {
  margin-top: 16px;
  padding: 12px;
  background: rgba(13, 148, 136, 0.06);
  border-radius: 12px;
}

.timer-text {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #0d9488;
  font-weight: 600;
  font-size: 14px;
}

.timer-icon {
  font-size: 18px;
}

.stages-display {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.stage-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 8px;
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
}

.stage-icon {
  font-size: 20px;
}

.stage-name {
  flex: 1;
  text-align: left;
  color: #394867;
  font-weight: 600;
  font-size: 13px;
}

.stage-dots {
  display: flex;
  gap: 4px;
}

.stage-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0d9488;
  animation: dotPulse 1s infinite ease-in-out;
}

.stage-dots .dot:nth-child(1) {
  animation-delay: 0s;
}

.stage-dots .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.stage-dots .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dotPulse {
  0%, 80%, 100% {
    opacity: 0.3;
  }
  40% {
    opacity: 1;
  }
}

.summary-display {
  margin-top: 16px;
  padding: 16px;
  background: rgba(76, 175, 80, 0.1);
  border-radius: 12px;
  text-align: left;
}

.summary-title {
  color: #4CAF50;
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 12px;
}

.summary-stages {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-stage {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 8px;
}

.summary-stage .stage-icon {
  font-size: 18px;
}

.summary-stage .stage-name {
  flex: 1;
  font-size: 13px;
}

.summary-stage .stage-status {
  font-size: 14px;
}

.summary-stage .stage-duration {
  font-family: monospace;
  font-size: 13px;
  color: #0d9488;
  font-weight: 600;
}

.submit-panel__status {
  margin-top: 12px;
  color: #6b7280;
  font-size: 13px;
}
</style>
