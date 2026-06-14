<template>
  <div class="business-card">
    <div v-if="imageUrl" class="business-card__image">
      <img :src="imageUrl" :alt="name" />
      <div v-if="images && images.length > 1" class="business-card__image-count">
        {{ images.length }} 张
      </div>
    </div>
    <div class="business-card__content">
      <div class="business-card__header">
        <h3 class="business-card__name">{{ name }}</h3>
        <div v-if="rating !== null && rating !== undefined" class="business-card__rating">
          <span class="business-card__stars">
            <span v-for="i in 5" :key="i" class="business-card__star">
              {{ i <= Math.round(rating) ? '★' : '☆' }}
            </span>
          </span>
          <span class="business-card__rating-value">{{ rating.toFixed(1) }}</span>
        </div>
      </div>

      <div v-if="tags && tags.length > 0" class="business-card__tags">
        <span v-for="(tag, index) in tags.slice(0, 4)" :key="index" class="business-card__tag">
          {{ tag }}
        </span>
      </div>

      <div v-if="address" class="business-card__info-row">
        <span class="business-card__info-icon">📍</span>
        <span class="business-card__info-text">{{ address }}</span>
      </div>

      <div v-if="openingHours" class="business-card__info-row">
        <span class="business-card__info-icon">🕐</span>
        <span class="business-card__info-text">{{ openingHours }}</span>
      </div>

      <div v-if="phone" class="business-card__info-row">
        <span class="business-card__info-icon">📞</span>
        <span class="business-card__info-text">{{ phone }}</span>
      </div>

      <div v-if="pricePerPerson !== null && pricePerPerson !== undefined" class="business-card__info-row">
        <span class="business-card__info-icon">💰</span>
        <span class="business-card__info-text">人均 ¥{{ pricePerPerson }}</span>
      </div>

      <div v-if="pricePerNight !== null && pricePerNight !== undefined" class="business-card__info-row">
        <span class="business-card__info-icon">💵</span>
        <span class="business-card__info-text">¥{{ pricePerNight }}/晚</span>
      </div>

      <div v-if="priceLevel" class="business-card__info-row">
        <span class="business-card__info-icon">💴</span>
        <span class="business-card__info-text">{{ priceLevel }}</span>
      </div>

      <div v-if="cuisine && cuisine.length > 0" class="business-card__info-row">
        <span class="business-card__info-icon">🍽️</span>
        <span class="business-card__info-text">{{ cuisine.join('、') }}</span>
      </div>

      <div v-if="facilities && facilities.length > 0" class="business-card__info-row">
        <span class="business-card__info-icon">🏨</span>
        <span class="business-card__info-text">{{ facilities.join('、') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { PhotoItem } from '../types';

interface Props {
  name: string;
  imageUrl?: string | null;
  images?: PhotoItem[];
  address?: string | null;
  rating?: number | null;
  openingHours?: string | null;
  phone?: string | null;
  website?: string | null;
  tags?: string[];
  priceLevel?: string | null;
  pricePerPerson?: number | null;
  pricePerNight?: number | null;
  cuisine?: string[];
  facilities?: string[];
}

const props = withDefaults(defineProps<Props>(), {
  images: () => [],
  tags: () => [],
  cuisine: () => [],
  facilities: () => [],
});

const imageUrl = computed(() => {
  if (props.imageUrl) return props.imageUrl;
  if (props.images && props.images.length > 0) return props.images[0].url;
  return null;
});
</script>

<style scoped>
.business-card {
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.business-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
}

.business-card__image {
  position: relative;
  width: 100%;
  height: 260px;
  overflow: hidden;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.business-card__image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.business-card__image-count {
  position: absolute;
  bottom: 12px;
  right: 12px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
}

.business-card__content {
  padding: 18px;
}

.business-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.business-card__name {
  font-size: 20px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
  flex: 1;
  line-height: 1.4;
}

.business-card__rating {
  display: flex;
  align-items: center;
  gap: 5px;
  background: linear-gradient(135deg, #ffd700 0%, #ffaa00 100%);
  padding: 6px 12px;
  border-radius: 16px;
  white-space: nowrap;
}

.business-card__stars {
  color: #fff;
  font-size: 13px;
  letter-spacing: -1px;
}

.business-card__star {
  display: inline-block;
}

.business-card__rating-value {
  color: #fff;
  font-weight: 600;
  font-size: 14px;
}

.business-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.business-card__tag {
  background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
  color: #667eea;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  white-space: nowrap;
}

.business-card__info-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 14px;
  color: #555;
}

.business-card__info-icon {
  font-size: 16px;
  margin-top: 1px;
  flex-shrink: 0;
}

.business-card__info-text {
  flex: 1;
  line-height: 1.6;
  word-break: break-word;
}
</style>
