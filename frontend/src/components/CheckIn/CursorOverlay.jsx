import { useEffect, useMemo, useRef } from 'react'
import './CursorOverlay.css'

function buildCursorSrc(cursorId) {
  if (!cursorId) return null
  const id = Number(cursorId)
  if (!Number.isFinite(id) || id < 1) return null
  return `/checkin/cursors/cursor-${String(id).padStart(2, '0')}.png`
}

export default function CursorOverlay({ cursorId }) {
  const cursorSrc = useMemo(() => buildCursorSrc(cursorId), [cursorId])
  const imgRef = useRef(null)
  const rafRef = useRef(0)
  const latestRef = useRef({ x: 0, y: 0 })

  useEffect(() => {
    const styleId = 'sm-cursor-hide-style'
    const prevHtmlCursor = document.documentElement.style.getPropertyValue('cursor')
    const prevHtmlPriority = document.documentElement.style.getPropertyPriority('cursor')
    const prevBodyCursor = document.body.style.getPropertyValue('cursor')
    const prevBodyPriority = document.body.style.getPropertyPriority('cursor')

    if (!cursorSrc) {
      document.body.classList.remove('sm-custom-cursor')
      document.documentElement.classList.remove('sm-custom-cursor')
      const styleEl = document.getElementById(styleId)
      if (styleEl) styleEl.remove()
      return
    }
    document.body.classList.add('sm-custom-cursor')
    document.documentElement.classList.add('sm-custom-cursor')

    // 强制隐藏系统光标（避免某些页面/样式覆盖导致仍显示默认箭头）
    document.documentElement.style.setProperty('cursor', 'none', 'important')
    document.body.style.setProperty('cursor', 'none', 'important')
    if (!document.getElementById(styleId)) {
      const styleEl = document.createElement('style')
      styleEl.id = styleId
      styleEl.textContent = `
        html.sm-custom-cursor body.sm-custom-cursor,
        html.sm-custom-cursor body.sm-custom-cursor * { cursor: none !important; }
      `
      document.head.appendChild(styleEl)
    }

    return () => {
      document.body.classList.remove('sm-custom-cursor')
      document.documentElement.classList.remove('sm-custom-cursor')
      const styleEl = document.getElementById(styleId)
      if (styleEl) styleEl.remove()

      if (prevHtmlCursor) {
        document.documentElement.style.setProperty('cursor', prevHtmlCursor, prevHtmlPriority || undefined)
      } else {
        document.documentElement.style.removeProperty('cursor')
      }
      if (prevBodyCursor) {
        document.body.style.setProperty('cursor', prevBodyCursor, prevBodyPriority || undefined)
      } else {
        document.body.style.removeProperty('cursor')
      }
    }
  }, [cursorSrc])

  useEffect(() => {
    const img = imgRef.current
    if (!img || !cursorSrc) return

    const schedule = () => {
      if (rafRef.current) return
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0
        const { x, y } = latestRef.current
        img.style.transform = `translate3d(${x}px, ${y}px, 0)`
      })
    }

    const onMove = (e) => {
      // 有些浏览器在缩放/高DPI下会产生小数坐标，导致像素图出现“细线/模糊”
      // 这里强制取整，保证像素边界对齐
      latestRef.current = { x: Math.round(e.clientX), y: Math.round(e.clientY) }
      schedule()
    }

    window.addEventListener('mousemove', onMove, { passive: true })
    return () => {
      window.removeEventListener('mousemove', onMove)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
  }, [cursorSrc])

  if (!cursorSrc) return null

  return <img ref={imgRef} src={cursorSrc} alt="" className="sm-cursor-overlay" draggable="false" />
}
