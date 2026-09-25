import { useEffect, useRef, useState } from 'react'
import './AuthModals.css'

function MembershipModal({ onClose, authSession, onLoginRequired, onMembershipUpdated }) {
  const DISCOUNT_COUPON_CODE = '2024210'
  const WEEK_TRIAL_CODE = 'sports-matter.com'
  const [selectedTier, setSelectedTier] = useState('monthly')
  const [inviteCode, setInviteCode] = useState('')
  const [inviteLoading, setInviteLoading] = useState(false)
  const [inviteError, setInviteError] = useState(null)
  const [inviteSuccessInfo, setInviteSuccessInfo] = useState(null)
  const [paymentLoading, setPaymentLoading] = useState(false)
  const [paymentError, setPaymentError] = useState(null)
  const [paymentStatus, setPaymentStatus] = useState(null)
  const [currentOrderNo, setCurrentOrderNo] = useState(null)
  const [paymentTier, setPaymentTier] = useState(null)
  const [successPage, setSuccessPage] = useState(0)
  const [successModalOpen, setSuccessModalOpen] = useState(false)
  const sessionRefreshedRef = useRef(false)
  const pollTimerRef = useRef(null)
  // 临时开关：是否展示“终身会员/打赏”支付档位（后续可随时打开）
  const showLifetimeTier = false
  const showTipTier = true

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [])

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (paymentStatus === 'paid' && paymentTier && paymentTier !== 'coffee' && !sessionRefreshedRef.current) {
      sessionRefreshedRef.current = true
      onMembershipUpdated?.()
    }
  }, [paymentStatus, paymentTier, onMembershipUpdated])

  useEffect(() => {
    if (currentOrderNo && paymentStatus === 'paid') {
      setSuccessModalOpen(true)
      setSuccessPage(0)
    }
  }, [currentOrderNo, paymentStatus])

  const tierSuccessMap = {
    monthly: {
      message: '感谢支持Sports-Matter！这是鸽子一个月的食物！',
      imgSrc: '/monthly-food.png',
      imgAlt: '月度会员图标'
    },
    yearly: {
      message: '感谢支持Sports-Matter！接下来的一年里鸽子每天都会吃这么丰盛的食物！（别担心它飞不动奥！）',
      imgSrc: '/yearly-food.png',
      imgAlt: '年度会员图标'
    },
    lifetime: {
      message: '感谢支持Sports-Matter！前路迢迢，鸽子为您服务终身！鸽子送了您一颗心脏，希望您不忘初心！',
      imgSrc: '/lifetime-heart.gif',
      imgAlt: '终身会员图标'
    }
  }

  const tierIconMap = {
    monthly: { src: '/monthly-food.png', alt: '月度会员图标' },
    yearly: { src: '/yearly-food.png', alt: '年度会员图标' },
    lifetime: { src: '/lifetime-heart.gif', alt: '终身会员图标' },
    coffee: { src: '/tip-bird.png', alt: '摸摸鸽子图标' }
  }

  const hasDiscountCoupon = Boolean(inviteCode?.trim() === DISCOUNT_COUPON_CODE)

  const formatCents = (cents) => {
    const v = Number(cents)
    if (!Number.isFinite(v) || v <= 0) return '0.00'
    const s = (v / 100).toFixed(2)
    return s.replace(/\\.00$/, '').replace(/(\\.\\d)0$/, '$1')
  }

  const membershipTiers = [
    {
      id: 'monthly',
      name: '月度饲料',
      base_cents: 1990,
      duration: '30天',
      desc: '鸽子会卖力干一个月活！'
    },
    {
      id: 'yearly',
      name: '年度饲料',
      base_cents: 19990,
      duration: '365天',
      desc: '鸽子会成为您的长期宠物！'
    },
    {
      id: 'lifetime',
      name: '终身饲料',
      base_cents: 29990,
      duration: '终身',
      desc: '希望您在学术道路上终身坚持！'
    },
    {
      id: 'coffee',
      name: '摸摸鸽子',
      base_cents: 99,
      duration: '打赏',
      desc: '不知道鸽子有什么反应？'
    }
  ].map((tier) => {
    const baseCents = Number(tier.base_cents) || 0
    const finalCents = hasDiscountCoupon ? Math.round(baseCents / 10) : baseCents
    return { ...tier, price: formatCents(finalCents) }
  })
  const visibleTiers = membershipTiers.filter((t) => {
    if (!showLifetimeTier && t.id === 'lifetime') return false
    if (!showTipTier && t.id === 'coffee') return false
    return true
  })

  useEffect(() => {
    if (!showLifetimeTier && selectedTier === 'lifetime') {
      setSelectedTier('monthly')
      return
    }
    if (!showTipTier && selectedTier === 'coffee') {
      setSelectedTier('monthly')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showLifetimeTier, showTipTier])

  const isGuest = Boolean(
    authSession?.logged_in &&
      authSession?.user &&
      (authSession.user.is_guest || authSession.user.nickname === '访客' || authSession.user.nickname === '游客')
  )

  const pollOrderStatus = (outTradeNo) => {
    if (!outTradeNo) return
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }

    let attempts = 0
    const maxAttempts = 80 // ~4min
    pollTimerRef.current = setInterval(async () => {
      attempts += 1
      if (attempts > maxAttempts) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
        return
      }
      try {
        const res = await fetch(`/api/v1/pool/payments/orders/${encodeURIComponent(outTradeNo)}`, {
          credentials: 'include'
        })
        const data = await res.json()
        if (!res.ok) return
        if (data?.tier) {
          setPaymentTier((prev) => prev || data.tier)
        }
        if (data.status === 'paid') {
          setPaymentStatus('paid')
          clearInterval(pollTimerRef.current)
          pollTimerRef.current = null
        } else if (data.status === 'failed' || data.status === 'canceled') {
          setPaymentStatus(data.status)
          clearInterval(pollTimerRef.current)
          pollTimerRef.current = null
        } else {
          setPaymentStatus('pending')
        }
      } catch {
        // ignore transient errors
      }
    }, 3000)
  }

  const handlePayment = async () => {
    setPaymentError(null)
    setPaymentStatus(null)
    sessionRefreshedRef.current = false

    // 检查登录状态（访客不允许购买/打赏，避免订单归属到 public_guest）
    if (!authSession?.logged_in || isGuest) {
      if (onLoginRequired) {
        onLoginRequired()
      } else {
        alert('请先登录后再购买或打赏')
      }
      return
    }

    const selected = visibleTiers.find((t) => t.id === selectedTier)
    if (!selected) {
      setPaymentError('请选择一个档位')
      return
    }

    setPaymentLoading(true)
    try {
      const res = await fetch('/api/v1/pool/payments/yungouos/alipay/webpay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          tier: selected.id,
          invite_code: inviteCode?.trim() || null
        })
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail || '下单失败')
      }

      setCurrentOrderNo(data.out_trade_no)
      setPaymentTier(selected.id)
      setSuccessPage(0)
      setPaymentStatus('pending')
      window.open(data.pay_url, '_blank', 'noopener,noreferrer')
      pollOrderStatus(data.out_trade_no)
    } catch (e) {
      setPaymentError(e?.message || '下单失败')
    } finally {
      setPaymentLoading(false)
    }
  }

  const handleInviteRedeem = async () => {
    setInviteError(null)
    setInviteSuccessInfo(null)

    // 兑换需要登录
    if (!authSession?.logged_in || isGuest) {
      if (onLoginRequired) onLoginRequired()
      else alert('请先登录后再使用邀请码')
      return
    }

    const code = inviteCode?.trim() || ''
    if (!code) {
      setInviteError('请输入邀请码')
      return
    }
    if (code === DISCOUNT_COUPON_CODE) {
      alert('✅ 1 折券已生效')
      return
    }

    setInviteLoading(true)
    try {
      const res = await fetch('/api/v1/pool/auth/invite/redeem', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code })
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = data?.detail
        const msg = typeof detail === 'string' ? detail : (detail?.message || detail?.code)
        throw new Error(msg || '邀请码兑换失败')
      }

      const membership = data?.membership || {}
      const isLifetime = Boolean(membership?.is_lifetime || membership?.tier === 'lifetime')
      const tier = (membership?.tier || '').toString()
      const expiresAt = membership?.expires_at
      let msg = '🎉 已生效！'
      let note = '邀请码已生效'
      if (isLifetime) {
        msg = '🎉 已解锁终身会员！'
        note = '邀请码已生效：终身会员'
      } else if (tier === 'weekly_invite' || code.toLowerCase() === WEEK_TRIAL_CODE) {
        msg = '🎉 已解锁 7 天会员！'
        note = expiresAt ? `邀请码已生效：有效期至 ${String(expiresAt).slice(0, 10)}` : '邀请码已生效：7 天会员'
      } else if (expiresAt) {
        note = `邀请码已生效：有效期至 ${String(expiresAt).slice(0, 10)}`
      }

      setInviteSuccessInfo(note)
      alert(msg)
      onMembershipUpdated?.()
      window.location.reload()
    } catch (e) {
      setInviteError(e?.message || '邀请码兑换失败')
    } finally {
      setInviteLoading(false)
    }
  }

  const closeSuccessModal = () => {
    setSuccessModalOpen(false)
  }

  const isPaid = Boolean(currentOrderNo && paymentStatus === 'paid')
  const showTierSuccess = Boolean(isPaid && paymentTier && tierSuccessMap[paymentTier])
  const showCoffeeSuccess = Boolean(isPaid && paymentTier === 'coffee')

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="auth-modal membership-modal pixel-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2 className="modal-title">成为会员</h2>

        <div className="membership-content">
          {/* 会员等级选择 */}
          <div className="membership-tiers">
            {visibleTiers.map(tier => (
              <div
                key={tier.id}
                className={`membership-tier ${selectedTier === tier.id ? 'selected' : ''}`}
                onClick={() => setSelectedTier(tier.id)}
              >
                {tier.badge && <div className="tier-badge">{tier.badge}</div>}
                <div className="tier-header">
                  <h3 className="tier-name">{tier.name}</h3>
                  {tierIconMap[tier.id] && (
                    <img
                      className="tier-icon"
                      src={tierIconMap[tier.id].src}
                      alt={tierIconMap[tier.id].alt}
                      loading="lazy"
                      draggable="false"
                    />
                  )}
                </div>
                <div className="tier-price">
                  <span className="price-amount">¥{tier.price}</span>
                  <span className="price-duration">/{tier.duration}</span>
                </div>
                {tier.desc && <div className="tier-desc">{tier.desc}</div>}
              </div>
            ))}
          </div>

          {/* 邀请码输入 */}
          <div className="invite-code-section">
            <label htmlFor="invite-code-input">有邀请码？</label>
            <div className="invite-code-input-group">
              <input
                id="invite-code-input"
                type="text"
                placeholder="输入邀请码可享额外优惠"
                className="pixel-input"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
              />
              <button
                className="pixel-button pixel-button-secondary"
                onClick={handleInviteRedeem}
                disabled={inviteLoading}
              >
                {inviteLoading ? '验证中...' : '验证'}
              </button>
            </div>
            {inviteError && <p className="payment-note" style={{ color: 'red' }}>{inviteError}</p>}
            {inviteSuccessInfo && <p className="payment-note">{inviteSuccessInfo}</p>}
            {hasDiscountCoupon && <p className="payment-note">✅ 1 折券已生效（2024210）</p>}
          </div>

          {/* 登录提示（未登录时） */}
          {(!authSession?.logged_in || isGuest) && (
            <div className="login-required-notice">
              <p>💡 购买/打赏前需要先 QQ 登录</p>
            </div>
          )}

          {/* 支付按钮 */}
          <div className="payment-section">
            <button
              className="pixel-button pixel-button-primary"
              onClick={handlePayment}
              disabled={paymentLoading}
            >
              {(!authSession?.logged_in || isGuest)
                ? '登录后购买'
                : paymentLoading
                  ? '下单中...'
                  : `支付 ¥${visibleTiers.find(t => t.id === selectedTier)?.price}`}
            </button>
            <p className="payment-note">
              {authSession?.logged_in && !isGuest
                ? '支付完成后自动检测订单状态 · 支持支付宝'
                : '登录后即可购买会员，享受全部功能'}
            </p>
            {paymentError && <p className="payment-note" style={{ color: 'red' }}>{paymentError}</p>}
            {currentOrderNo && paymentStatus === 'pending' && (
              <p className="payment-note">订单号：{currentOrderNo}（等待支付回调…）</p>
            )}
            {isPaid && (
              <p className="payment-note">✅ 支付成功（已弹窗展示）</p>
            )}
            {currentOrderNo && (paymentStatus === 'failed' || paymentStatus === 'canceled') && (
              <p className="payment-note" style={{ color: 'red' }}>订单未支付完成，请重试</p>
            )}
          </div>
        </div>

        {successModalOpen && isPaid && (
          <div
            className="modal-overlay payment-success-overlay"
            onClick={(e) => {
              e.stopPropagation()
              closeSuccessModal()
            }}
          >
            <div className="auth-modal payment-success-modal pixel-card" onClick={(e) => e.stopPropagation()}>
              <button className="modal-close" onClick={closeSuccessModal}>×</button>
              <h2 className="modal-title payment-success-title">支付成功</h2>

              {showTierSuccess && (
                <div className="membership-success membership-success-popup">
                  {successPage === 0 ? (
                    <>
                      <p className="membership-success-text">{tierSuccessMap[paymentTier].message}</p>
                      <img
                        className="membership-success-img"
                        src={tierSuccessMap[paymentTier].imgSrc}
                        alt={tierSuccessMap[paymentTier].imgAlt}
                        loading="lazy"
                        draggable="false"
                      />
                    </>
                  ) : (
                    <>
                      <p className="membership-success-text">
                        鸽子诚邀您加入社群！科研不易，在里面寻找志同道合的合作伙伴吧！
                      </p>
                    </>
                  )}
                  <div className="membership-success-nav">
                    <button
                      type="button"
                      className="pixel-button"
                      onClick={() => setSuccessPage(0)}
                      disabled={successPage === 0}
                    >
                      上一页
                    </button>
                    <span className="membership-success-indicator">{successPage + 1}/2</span>
                    <button
                      type="button"
                      className="pixel-button"
                      onClick={() => setSuccessPage(1)}
                      disabled={successPage === 1}
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}

              {showCoffeeSuccess && (
                <div className="tip-success tip-success-popup">
                  <img
                    className="tip-success-icon"
                    src="/tip-bird.png"
                    alt="摸摸鸽子"
                    loading="lazy"
                    draggable="false"
                  />
                  <p className="tip-success-text">
                    感谢支持Sports-Matter！鸽子邀请您进入社群！科研工作单干不易，在里面寻找合作伙伴吧！
                  </p>
                </div>
              )}

              {!showTierSuccess && !showCoffeeSuccess && (
                <p className="payment-note">支付成功，感谢投喂！</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default MembershipModal
