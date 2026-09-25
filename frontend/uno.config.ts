import { defineConfig, presetUno } from 'unocss'
import { presetRemToPx } from '@unocss/preset-rem-to-px'

export default defineConfig({
  presets: [
    presetUno(),
    // Keep rem-to-px optional, mainly for consistent pixel feel
    presetRemToPx({ baseFontSize: 16 }),
  ],
  shortcuts: {
    'px-card': 'border-[3px] border-[var(--px-color-base)] bg-[var(--px-color-white)] shadow-[4px_4px_0_0_var(--px-color-primary-dark-1)]',
    'px-btn': 'border-[3px] border-[var(--px-color-base)] bg-[var(--px-color-primary)] text-[var(--px-color-white)] shadow-[3px_3px_0_0_var(--px-color-primary-dark-1)] px-3 py-2',
  },
  safelist: [
    'px-card', 'px-btn',
  ],
})
