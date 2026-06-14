import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Itinerary, TripSummaryItem, PipelineSummary } from '../types'
import { listTrips, getTripDetail, saveTrip as saveTripApi, deleteTrip as deleteTripApi } from '../services/api'
import { message } from 'ant-design-vue'

export const useTripStore = defineStore('trip', () => {
  // 状态
  const currentItinerary = ref<Itinerary | null>(null)
  const pipelineSummary = ref<PipelineSummary | null>(null)
  const tripHistory = ref<TripSummaryItem[]>([])
  const isLoading = ref(false)
  const isHistoryLoading = ref(false)
  const isSaving = ref(false)
  const isDeleting = ref(false)
  const errorMessage = ref<string | null>(null)

  // 计算属性
  const hasCurrentItinerary = computed(() => currentItinerary.value !== null)
  const tripId = computed(() => currentItinerary.value?.tripId || null)
  const destination = computed(() => currentItinerary.value?.destination || '')
  const tripHistoryCount = computed(() => tripHistory.value.length)

  // Actions
  const setItinerary = (itinerary: Itinerary) => {
    currentItinerary.value = itinerary
    errorMessage.value = null
  }

  const setPipelineSummary = (summary: PipelineSummary) => {
    pipelineSummary.value = summary
  }

  const clearItinerary = () => {
    currentItinerary.value = null
    pipelineSummary.value = null
    errorMessage.value = null
  }

  const setLoading = (loading: boolean) => {
    isLoading.value = loading
  }

  const setError = (message: string) => {
    errorMessage.value = message
  }

  const clearError = () => {
    errorMessage.value = null
  }

  // 获取行程历史
  const loadTripHistory = async () => {
    isHistoryLoading.value = true
    errorMessage.value = null
    try {
      const response = await listTrips()
      tripHistory.value = response.items
      return response.items
    } catch (error) {
      errorMessage.value = '加载行程历史失败'
      message.error(errorMessage.value)
      throw error
    } finally {
      isHistoryLoading.value = false
    }
  }

  // 加载行程详情
  const loadTripDetail = async (tripId: string) => {
    isLoading.value = true
    errorMessage.value = null
    try {
      const response = await getTripDetail(tripId)
      currentItinerary.value = response.itinerary
      return response.itinerary
    } catch (error) {
      errorMessage.value = '加载行程详情失败'
      message.error(errorMessage.value)
      throw error
    } finally {
      isLoading.value = false
    }
  }

  // 保存行程
  const saveTrip = async () => {
    if (!currentItinerary.value) {
      return
    }
    isSaving.value = true
    try {
      const response = await saveTripApi(currentItinerary.value)
      message.success('行程已保存')
      return response
    } catch (error) {
      errorMessage.value = '保存行程失败'
      message.error(errorMessage.value)
      throw error
    } finally {
      isSaving.value = false
    }
  }

  // 删除行程
  const deleteTrip = async (tripId: string) => {
    isDeleting.value = true
    try {
      await deleteTripApi(tripId)
      message.success('行程已删除')
      tripHistory.value = tripHistory.value.filter(item => item.tripId !== tripId)
    } catch (error) {
      errorMessage.value = '删除行程失败'
      message.error(errorMessage.value)
      throw error
    } finally {
      isDeleting.value = false
    }
  }

  return {
    // 状态
    currentItinerary,
    pipelineSummary,
    tripHistory,
    isLoading,
    isHistoryLoading,
    isSaving,
    isDeleting,
    errorMessage,

    // 计算属性
    hasCurrentItinerary,
    tripId,
    destination,
    tripHistoryCount,

    // Actions
    setItinerary,
    setPipelineSummary,
    clearItinerary,
    setLoading,
    setError,
    clearError,
    loadTripHistory,
    loadTripDetail,
    saveTrip,
    deleteTrip,
  }
})

