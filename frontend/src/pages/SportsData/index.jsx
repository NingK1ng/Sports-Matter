import { useState, useEffect } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import './index.css'
import { sportsDataAPI } from '../../services/api'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'

export default function SportsData() {
  const navigate = useNavigate()
  const outlet = useOutletContext()
  const authSession = outlet?.authSession
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(10)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState([])
  const [hasSearched, setHasSearched] = useState(false)
  const [titleVisible, setTitleVisible] = useState(false)
  const [mode, setMode] = useState('dataset') // 'dataset' | 'code' | 'reports' | 'scales'

  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  const isMember = Boolean(authSession?.user?.is_member)
  const quota = authSession?.quota
  const sportsDataQuota = quota?.features?.sports_data_search
  const quotaHint = isMember
    ? '会员不限次数'
    : (sportsDataQuota
        ? `本周剩余：Sports Data ${sportsDataQuota.remaining}/${sportsDataQuota.limit}`
        : '未登录/非会员每周免费 5 次（Sports Data）')

  const handleSearch = async (e) => {
    e.preventDefault()
    setError('')
    setHasSearched(true)

    const trimmed = query.trim()
    if (!trimmed) {
      setError('请输入英文关键词')
      return
    }

    setLoading(true)
    try {
      let data
      if (mode === 'dataset') {
        data = await sportsDataAPI.searchDatasets({ query: trimmed, limit })
      } else if (mode === 'code') {
        data = await sportsDataAPI.searchCode({ query: trimmed, limit })
      } else if (mode === 'reports') {
        data = await sportsDataAPI.searchReports({ query: trimmed, limit })
      } else {
        data = await sportsDataAPI.searchScales({ query: trimmed, limit })
      }
      setResults(Array.isArray(data.results) ? data.results : [])
    } catch (err) {
      console.error('Sports Data search failed', err)
      setError(err?.message || '搜索失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const handleOpenLiterature = (item) => {
    const title = item && item.title ? String(item.title) : ''
    const fallback = title.trim() || query.trim()
    if (!fallback) {
      navigate('/literature')
      return
    }
    const kw = fallback.slice(0, 200)
    navigate(`/literature?kw=${encodeURIComponent(kw)}`)
  }

  const getPrimaryButtonLabel = () => {
    if (mode === 'dataset') return '搜索数据集'
    if (mode === 'code') return '搜索代码 / 模型'
    if (mode === 'reports') return '搜索报告 & Dashboard'
    return '搜索量表 & 问卷'
  }

  const getPrimaryLinkLabel = () => {
    if (mode === 'dataset') return '前往数据集页面'
    if (mode === 'code') return '前往代码 / 模型页面'
    if (mode === 'reports') return '查看报告 / Dashboard'
    return '查看量表 / 问卷'
  }

  const getKindLabel = (item) => {
    const kind = (item && item.kind) || ''
    if (mode === 'code') {
      if (kind === 'model') return '模型'
      if (kind === 'project') return '项目'
      return '代码'
    }
    if (mode === 'reports') {
      if (kind === 'dashboard') return 'Dashboard'
      if (kind === 'template') return '报告模板'
      return '报告'
    }
    if (mode === 'scales') {
      if (kind === 'questionnaire') return '问卷'
      return '量表'
    }
    return null
  }

  return (
    <div className="sports-data-page">
      <header className="sports-data-header">
        <h1 className={"sports-data-title" + (titleVisible ? " visible" : "")}>
          Sports Data
        </h1>
        <TypewriterSubtitle
          text={[
            '运动科学就是数据科学！',
            '20年代是数据驱动的年代！',
          ]}
          className="sports-data-subtitle"
          active={titleVisible}
        />
        <p className="sports-data-hint">
          目前仅支持英文关键词
        </p>
      </header>

      <section className="sports-data-search pixel-card">
        <form className="sports-data-form" onSubmit={handleSearch}>
          <div className="sports-data-mode-toggle">
            <button
              type="button"
              className={
                'sports-data-mode-button' + (mode === 'dataset' ? ' active' : '')
              }
              onClick={() => setMode('dataset')}
            >
              数据集
            </button>
            <button
              type="button"
              className={
                'sports-data-mode-button' + (mode === 'code' ? ' active' : '')
              }
              onClick={() => setMode('code')}
            >
              代码 & 模型
            </button>
            <button
              type="button"
              className={
                'sports-data-mode-button' + (mode === 'reports' ? ' active' : '')
              }
              onClick={() => setMode('reports')}
            >
              报告 & Dashboard
            </button>
            <button
              type="button"
              className={
                'sports-data-mode-button' + (mode === 'scales' ? ' active' : '')
              }
              onClick={() => setMode('scales')}
            >
              量表 & 问卷
            </button>
          </div>
          <input
            type="text"
            className="sports-data-input"
            placeholder="例如：football GPS running gait dataset"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="sports-data-controls">
            <div className="limit-toggle">
              <span>每次展示：</span>
              {[5, 10, 15].map((v) => (
                <button
                  key={v}
                  type="button"
                  className={
                    'limit-option pixel-button' + (limit === v ? ' active' : '')
                  }
                  onClick={() => setLimit(v)}
                >
                  {v}
                </button>
              ))}
            </div>
            <button
              type="submit"
              className="pixel-button pixel-button-primary search-button"
              disabled={loading}
            >
              {loading ? '搜索中...' : getPrimaryButtonLabel()}
            </button>
          </div>
        </form>
        {error && <p className="sports-data-error">{error}</p>}
      </section>

      <section className="sports-data-results pixel-card">
        {!hasSearched && !loading ? (
          <p className="sports-data-empty">输入关键词开始搜索</p>
        ) : results.length === 0 && !loading ? (
          <p className="sports-data-empty">鸽子没找着，换个关键词？</p>
        ) : (
          <ul className="sports-data-list">
            {results.map((item, idx) => (
              <li key={idx} className="sports-data-item">
                <div className="item-header">
                  <h3 className="item-title">{item.title}</h3>
                  <div className="item-meta">
                    {['code', 'reports', 'scales'].includes(mode) && (
                      (() => {
                        const label = getKindLabel(item)
                        return label ? (
                          <span className="item-kind-tag">{label}</span>
                        ) : null
                      })()
                    )}
                    {item.source && (
                      <span className="item-source">{item.source}</span>
                    )}
                  </div>
                </div>
                {item.snippet && (
                  <p className="item-snippet">{item.snippet}</p>
                )}
                <div className="item-actions">
                  <a
                    className="pixel-button item-link"
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {getPrimaryLinkLabel()}
                  </a>
                  {mode === 'dataset' && (
                    <button
                      type="button"
                      className="pixel-button item-link-secondary"
                      onClick={() => handleOpenLiterature(item)}
                    >
                      在文献模块查看相关论文
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="sports-data-quota-footer">
        {quotaHint}
      </footer>
    </div>
  )
}
