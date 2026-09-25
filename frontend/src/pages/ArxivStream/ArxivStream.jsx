import { useState, useEffect } from 'react'
import { arxivAPI } from '../../services/api'
import Pagination from '../../components/Pagination'
import LoadingSpinner from '../../components/LoadingSpinner'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import ArticleItem from './ArticleItem'
import styles from './ArxivStream.module.css'

function ArxivStream() {
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    window: '30d',
    keywords: '',
    searchScope: 'tiab',
    source: 'all',
  })
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [titleVisible, setTitleVisible] = useState(false)

  useEffect(() => {
    // 标题淡入动画
    setTimeout(() => {
      setTitleVisible(true)
    }, 300)
  }, [])

  useEffect(() => {
    // 防抖：关键词输入时延迟300ms再请求，其他筛选立即触发
    const debounceTimeout = filters.keywords ? setTimeout(() => {
      fetchArticles()
    }, 300) : null

    if (!filters.keywords) {
      fetchArticles()
    }

    return () => {
      if (debounceTimeout) clearTimeout(debounceTimeout)
    }
  }, [filters, page])

  const fetchArticles = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        page,
        per_page: 20,
      }
      // 时间窗口：7/14/30/90天/365天 → days，2024年起 → date_from
      if (filters.window === 'today') {
        params.window = 'today'
      } else if (filters.window === 'from2024') {
        params.date_from = '2024-01-01'
      } else if (filters.window) {
        params.days = filters.window.replace('d', '')
      }
      // 来源过滤：all 表示不过滤
      if (filters.source && filters.source !== 'all') {
        params.source = filters.source
      }
      if (filters.keywords) {
        params.keywords = filters.keywords
        params.search_scope = filters.searchScope
      }

      const data = await arxivAPI.fetchArticles(params)
      setArticles(data.items || [])
      setTotal(data.total ?? 0)
    } catch (error) {
      console.error('获取文献失败:', error)
      setError(error.message || '获取文献失败，请稍后重试')
      setArticles([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.arxivStream}>
      <header className={styles.pageHeader}>
        <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>预印本前沿</h1>
        <TypewriterSubtitle
          text={[
            "跳过冗长的审稿周期，发掘运动科学的最前沿！",
            "文献尚未经同行评审，请仔细甄别！",
          ]}
          active={titleVisible}
        />
      </header>

      <div className={styles.filtersCard}>
        <div className={styles.filterGroup}>
          <label>时间窗口</label>
          <select
            value={filters.window}
            onChange={(e) => { setPage(1); setFilters({...filters, window: e.target.value}) }}
          >
            <option value="today">今日入库</option>
            <option value="7d">最近7天</option>
            <option value="14d">最近14天</option>
            <option value="30d">最近30天</option>
            <option value="90d">最近90天</option>
            <option value="365d">最近1年</option>
            <option value="from2024">2024年起</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>来源</label>
          <select
            value={filters.source}
            onChange={(e) => { setPage(1); setFilters({ ...filters, source: e.target.value }) }}
          >
            <option value="all">全部</option>
            <option value="arxiv">仅 arXiv</option>
            <option value="biorxiv">仅 bioRxiv</option>
          </select>
        </div>

        <div className={`${styles.filterGroup} ${styles.filterGroupSearch}`}>
          <label>关键词搜索</label>
          <div className={styles.searchRow}>
            <input
              type="text"
              placeholder="输入关键词..."
              value={filters.keywords}
              onChange={(e) => setFilters({...filters, keywords: e.target.value})}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  setPage(1)
                  fetchArticles()
                }
              }}
            />
            <select
              value={filters.searchScope}
              onChange={(e) => setFilters({ ...filters, searchScope: e.target.value })}
            >
              <option value="tiab">标题+摘要</option>
              <option value="ti">仅标题</option>
            </select>
            <div className={styles.filterActions}>
              <button onClick={() => { setPage(1); fetchArticles(); }}>
                搜索
              </button>
              <button
                className={styles.secondary}
                onClick={() => {
                  setPage(1)
                  setFilters({
                    window: '30d',
                    keywords: '',
                    searchScope: 'tiab',
                    source: 'all',
                  })
                }}
              >
                重置
              </button>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <LoadingSpinner type="skeleton" count={5} />
      ) : error ? (
        <div className={styles.errorMessage}>
          <span className={styles.errorIcon}>⚠️</span>
          <p>{error}</p>
          <button onClick={fetchArticles} className={styles.retryButton}>重试</button>
        </div>
      ) : articles.length === 0 ? (
        <div className={styles.emptyState}>
          <p>暂无数据</p>
        </div>
      ) : (
        <>
          <div className={styles.articlesList}>
            {articles.map((article, index) => (
              <ArticleItem
                key={article.arxiv_id || index}
                article={article}
                index={index}
              />
            ))}
          </div>

          <Pagination
            currentPage={page}
            totalPages={Math.ceil(total / 20)}
            totalItems={total}
            perPage={20}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}

export default ArxivStream
