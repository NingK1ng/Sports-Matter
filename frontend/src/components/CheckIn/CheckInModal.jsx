import { useEffect, useMemo, useState } from 'react'
import '../AuthModals/AuthModals.css'
import './CheckInModal.css'

const TOTAL_FALLBACK = 31
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000

function cursorSrcById(cursorId) {
  const id = Number(cursorId)
  if (!Number.isFinite(id) || id < 1) return ''
  return `/checkin/cursors/cursor-${String(id).padStart(2, '0')}.png`
}

function isIsoDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.trim())
}

function parseIsoDate(isoDate) {
  if (!isIsoDate(isoDate)) return null
  const [year, month, day] = isoDate.trim().split('-').map((p) => Number(p))
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null
  return { year, month, day }
}

function pad2(value) {
  return String(value).padStart(2, '0')
}

function beijingTodayIso(nowMs = Date.now()) {
  const beijing = new Date(nowMs + BEIJING_OFFSET_MS)
  const year = beijing.getUTCFullYear()
  const month = beijing.getUTCMonth() + 1
  const day = beijing.getUTCDate()
  return `${year}-${pad2(month)}-${pad2(day)}`
}

function msUntilNextBeijingMidnight(nowMs = Date.now()) {
  const beijing = new Date(nowMs + BEIJING_OFFSET_MS)
  const nextMidnightBeijingUtc = Date.UTC(
    beijing.getUTCFullYear(),
    beijing.getUTCMonth(),
    beijing.getUTCDate() + 1,
    0,
    0,
    0,
    0
  )
  const nextMidnightUtc = nextMidnightBeijingUtc - BEIJING_OFFSET_MS
  return Math.max(500, nextMidnightUtc - nowMs)
}

function formatIsoDate(year, month, day) {
  return `${year}-${pad2(month)}-${pad2(day)}`
}

function buildMonthGrid(todayIso, checkedDates) {
  const parts = parseIsoDate(todayIso)
  if (!parts) return null

  const year = parts.year
  const monthIndex = parts.month - 1
  const first = new Date(Date.UTC(year, monthIndex, 1))
  // JS: 0=Sun...6=Sat -> Monday-first
  const startOffset = (first.getUTCDay() + 6) % 7
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()
  const cells = []
  for (let i = 0; i < startOffset; i += 1) cells.push(null)
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d)
  while (cells.length % 7 !== 0) cells.push(null)

  const checkedSet = new Set((checkedDates || []).filter(isIsoDate).map((d) => d.trim()))
  return { year, monthIndex, cells, checkedSet, todayIso: todayIso.trim() }
}

export default function CheckInModal({ onClose, onLoginRequired, onCursorChanged }) {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [claiming, setClaiming] = useState(false)
  const [rewardCursorId, setRewardCursorId] = useState(null)

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [])

  const loadStatus = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    if (!silent) setError(null)
    try {
      const res = await fetch('/api/v1/checkin/status', { credentials: 'include' })
      if (res.status === 401) {
        if (onLoginRequired) onLoginRequired()
        onClose?.()
        return
      }
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail?.message || data?.detail || `HTTP ${res.status}`)
      }
      setStatus(data)
      onCursorChanged?.(data?.selected_cursor_id ?? null)
    } catch (e) {
      if (!silent) setError(String(e?.message || e))
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const todayIso = useMemo(() => {
    const raw = typeof status?.today === 'string' ? status.today.trim() : ''
    return isIsoDate(raw) ? raw : beijingTodayIso()
  }, [status?.today])

  const checkedDates = useMemo(() => {
    const list = Array.isArray(status?.checked_dates) ? status.checked_dates : []
    return list
      .map((d) => (typeof d === 'string' ? d.trim() : String(d || '').trim()))
      .filter(isIsoDate)
  }, [status?.checked_dates])

  const monthGrid = useMemo(() => {
    return buildMonthGrid(todayIso, checkedDates)
  }, [todayIso, checkedDates])

  const totalCursors = Number(status?.total_cursors || TOTAL_FALLBACK) || TOTAL_FALLBACK
  const streakDays = Number(status?.streak_days || 0) || 0
  const unlockedCount = Number(status?.unlocked_count || 0) || 0
  const selectedCursorId = status?.selected_cursor_id ? Number(status.selected_cursor_id) : null

  const hasCheckedToday = useMemo(() => {
    if (!monthGrid) return false
    return monthGrid.checkedSet.has(monthGrid.todayIso)
  }, [monthGrid])

  useEffect(() => {
    let timerId = null
    let canceled = false

    const schedule = () => {
      if (canceled) return
      const delay = msUntilNextBeijingMidnight()
      timerId = setTimeout(async () => {
        if (canceled) return
        setRewardCursorId(null)
        await loadStatus({ silent: true })
        schedule()
      }, delay + 1000)
    }

    schedule()
    return () => {
      canceled = true
      if (timerId) clearTimeout(timerId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleClaim = async () => {
    if (claiming || hasCheckedToday) return
    setClaiming(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/checkin/claim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include'
      })
      if (res.status === 401) {
        if (onLoginRequired) onLoginRequired()
        onClose?.()
        return
      }
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail?.message || data?.detail || `HTTP ${res.status}`)
      }
      setRewardCursorId(data?.reward_cursor_id || null)
      await loadStatus()
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setClaiming(false)
    }
  }

  const handleSelectCursor = async (cursorId) => {
    const id = Number(cursorId)
    if (!Number.isFinite(id) || id < 0) return
    if (id > 0 && id > unlockedCount) return
    setError(null)
    try {
      const res = await fetch('/api/v1/checkin/select-cursor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ cursor_id: id })
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail?.message || data?.detail || `HTTP ${res.status}`)
      }
      const nextSelected = data?.selected_cursor_id ?? null
      setStatus((prev) => ({ ...(prev || {}), selected_cursor_id: nextSelected }))
      onCursorChanged?.(nextSelected)
    } catch (e) {
      setError(String(e?.message || e))
    }
  }

  const rewardToShow = rewardCursorId || selectedCursorId || (unlockedCount ? Math.min(unlockedCount, totalCursors) : null)
  const rewardText = rewardCursorId
    ? `今日奖励：第 ${rewardCursorId} 天图标`
    : selectedCursorId
      ? `当前鼠标：第 ${selectedCursorId} 个图标`
      : '签到后可解锁鼠标图标'

  const weekDays = ['一', '二', '三', '四', '五', '六', '日']

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="auth-modal checkin-modal pixel-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2 className="modal-title">每日签到</h2>

        {loading ? (
          <div className="loading-text">加载中...</div>
        ) : error ? (
          <div className="error-container">
            <div className="error-text">{error}</div>
            <button className="pixel-button pixel-button-primary" onClick={loadStatus}>重试</button>
          </div>
        ) : (
          <div className="checkin-content">
            <div className="checkin-top">
              <div className="checkin-stats">
                <div>连续签到：{streakDays} 天</div>
                <div>已解锁：{unlockedCount}/{totalCursors}</div>
              </div>
              <div className="checkin-actions">
                <button
                  className="pixel-button pixel-button-primary"
                  onClick={handleClaim}
                  disabled={claiming || hasCheckedToday}
                >
                  {hasCheckedToday ? '今日已签到' : claiming ? '签到中...' : '签到'}
                </button>
                <p className="checkin-note">连续签到解锁更多奖励 · 共 31 个</p>
              </div>
            </div>

            <div className="checkin-body">
              <div className="checkin-panel">
                <div className="checkin-calendar-head">
                  <div className="checkin-calendar-month">
                    {monthGrid ? `${monthGrid.year}年${monthGrid.monthIndex + 1}月` : ''}
                  </div>
                </div>
                <div className="checkin-calendar-grid">
                  {weekDays.map((d) => (
                    <div key={d} className="checkin-weekday">{d}</div>
                  ))}
                  {monthGrid?.cells.map((day, idx) => {
                    if (!day) return <div key={`e-${idx}`} className="checkin-day empty" />
                    const iso = formatIsoDate(monthGrid.year, monthGrid.monthIndex + 1, day)
                    const checked = monthGrid.checkedSet.has(iso)
                    const isToday = iso === monthGrid.todayIso
                    const className = ['checkin-day', checked ? 'checked' : '', isToday ? 'today' : '']
                      .filter(Boolean)
                      .join(' ')
                    return (
                      <div key={iso} className={className}>
                        {day}
                      </div>
                    )
                  })}
                </div>

                {rewardToShow ? (
                  <div className="checkin-reward-preview">
                    <img
                      src={cursorSrcById(rewardToShow)}
                      alt=""
                      className="checkin-reward-img"
                      draggable="false"
                    />
                    <p className="checkin-reward-text">{rewardText}</p>
                  </div>
                ) : null}
              </div>

              <div className="checkin-panel">
                <div className="checkin-panel-header">
                  <h3 className="checkin-panel-title">鼠标图标（点击已解锁图标即可切换）</h3>
                  {selectedCursorId ? (
                    <button
                      type="button"
                      className="pixel-button checkin-clear-btn"
                      onClick={() => handleSelectCursor(0)}
                    >
                      使用原鼠标
                    </button>
                  ) : null}
                </div>
                <div className="checkin-cursor-grid">
                  {Array.from({ length: Math.max(unlockedCount, 0) }, (_, i) => i + 1).map((id) => {
                    const selected = selectedCursorId === id
                    return (
                      <button
                        key={id}
                        type="button"
                        className={[
                          'checkin-cursor-btn',
                          selected ? 'selected' : ''
                        ].filter(Boolean).join(' ')}
                        onClick={() => {
                          handleSelectCursor(selected ? 0 : id)
                        }}
                        aria-label={`cursor-${id}`}
                      >
                        <img
                          src={cursorSrcById(id)}
                          alt=""
                          className="checkin-cursor-img"
                          draggable="false"
                          loading="lazy"
                        />
                      </button>
                    )
                  })}
                </div>
                {unlockedCount <= 0 ? (
                  <p className="checkin-note" style={{ marginTop: 10 }}>
                    先签到解锁第 1 个鼠标图标
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
