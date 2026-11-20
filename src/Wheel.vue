<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Play, LoaderCircle } from 'lucide-vue-next'

const props = defineProps({
  items: { type: Array, default: () => [] },
  rotation: { type: Number, default: 0 },
  spinning: Boolean,
  disabled: Boolean,
  preview: Boolean,
})
defineEmits(['draw'])

const canvas = ref(null)
const palette = ['#6752ec', '#a78afa', '#f6bcb4', '#f9d989', '#a9e4db', '#7284f5', '#e69ad7', '#c5b6fc']
const samples = ['幸运大奖', '再试一次', '惊喜礼品', '积分奖励', '专属好礼', '神秘奖励', '特别奖', '幸运加倍']
const values = computed(() => props.preview ? samples : props.items.map(item => item.text))
let observer

function render() {
  const element = canvas.value
  if (!element) return
  const size = element.clientWidth
  if (!size) return
  const density = window.devicePixelRatio || 1
  element.width = Math.round(size * density)
  element.height = element.width
  const ctx = element.getContext('2d')
  const radius = size / 2
  ctx.scale(element.width / size, element.width / size)
  ctx.translate(radius, radius)
  const count = values.value.length || 8
  const slice = Math.PI * 2 / count

  for (let index = 0; index < count; index++) {
    const angle = -Math.PI / 2 + index * slice
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.arc(0, 0, radius, angle - slice / 2, angle + slice / 2)
    ctx.closePath()
    ctx.fillStyle = values.value.length ? palette[index % palette.length] : (index % 2 ? '#e7e3fc' : '#efedfa')
    ctx.fill()
    ctx.strokeStyle = '#ffffffa0'
    ctx.lineWidth = count > 80 ? 0.45 : 1.5
    if (count > 1) ctx.stroke()

    const label = values.value[index]
    if (!label || count > 44) continue
    ctx.save()
    ctx.rotate(angle)
    ctx.translate(radius * .72, 0)
    if (Math.cos(angle) < -0.001) ctx.rotate(Math.PI)
    ctx.fillStyle = [0, 5].includes(index % palette.length) ? '#fff' : '#25204a'
    const fontSize = Math.max(9, Math.min(17, size * .043, radius * slice * .44))
    ctx.font = `700 ${fontSize}px system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    let display = label
    const max = radius * .47
    if (ctx.measureText(label).width > max) {
      const chars = Array.from(label)
      while (chars.length && ctx.measureText(chars.join('') + '…').width > max) chars.pop()
      display = chars.join('') + '…'
    }
    ctx.fillText(display, 0, 0)
    ctx.restore()
  }
}

watch(values, () => nextTick(render))
onMounted(() => {
  observer = new ResizeObserver(render)
  observer.observe(canvas.value)
  render()
})
onUnmounted(() => observer?.disconnect())
</script>

<template>
  <div class="wheel-wrap" :class="{ 'preview-wheel': preview }">
    <div class="pointer" aria-hidden="true"></div>
    <div class="wheel-rim">
      <canvas ref="canvas" aria-hidden="true" :class="{ animated: spinning }" :style="{ transform: `rotate(${rotation}deg)` }"></canvas>
    </div>
    <div v-if="preview" class="wheel-center preview-center" aria-hidden="true"><Play :size="27" fill="currentColor" /></div>
    <button v-else class="wheel-center" type="button" :disabled="disabled || spinning" @click="$emit('draw')">
      <LoaderCircle v-if="spinning" class="loader" :size="23" />
      <Play v-else :size="23" fill="currentColor" />
      <span>{{ spinning ? '抽取中' : '开始' }}</span>
    </button>
  </div>
</template>
