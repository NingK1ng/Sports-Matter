import { useState } from 'react'
import styles from './ArxivStream.module.css'

function ArticleItem({ article, index }) {
  const [showAbstract, setShowAbstract] = useState(false)
  const [showChinese, setShowChinese] = useState(false)

  // 构建链接
  const pdfUrl = article.pdf_url
  const arxivUrl = article.abs_url

  // 格式化作者列表（兼容字符串数组和 {name: ...} 数组）
  const formatAuthors = (authors) => {
    if (!Array.isArray(authors) || authors.length === 0) return '未知作者'

    const names = authors.map((a) => {
      if (!a) return ''
      if (typeof a === 'string') return a
      if (typeof a === 'object') {
        return a.name || a.full_name || a.last_name || ''
      }
      return String(a)
    }).filter(Boolean)

    if (names.length === 0) return '未知作者'
    if (names.length <= 3) return names.join(', ')
    return `${names.slice(0, 3).join(', ')}, et al.`
  }

  // 格式化日期
  const formatDate = (dateStr) => {
    if (!dateStr) return '未知日期'
    return new Date(dateStr).toLocaleDateString('zh-CN')
  }

  return (
    <div className={styles.articleItem}>
      {/* 英文标题 */}
      <div
        className={styles.articleTitle}
        onClick={() => arxivUrl && window.open(arxivUrl, '_blank')}
        style={{ cursor: arxivUrl ? 'pointer' : 'default' }}
      >
        <span>{article.title}</span>
      </div>

      {/* 中文标题 */}
      {article.title_zh && (
        <div className={styles.titleTranslation}>
          <strong>中文标题：</strong>{article.title_zh}
        </div>
      )}

      <div className={styles.articleMeta}>
        <span className={styles.metaAuthors}>
          {formatAuthors(article.authors)}
        </span>
        <span className={styles.metaSeparator}>·</span>
        <span className={styles.metaSource}>
          {article.source === 'biorxiv' ? 'bioRxiv' : 'arXiv'}
        </span>
        <span className={styles.metaSeparator}>·</span>
        <span className={styles.metaDate}>{formatDate(article.submitted_date || article.published_date)}</span>
        {article.version && article.version > 1 && (
          <>
            <span className={styles.metaSeparator}>·</span>
            <span className={styles.metaVersion}>v{article.version}</span>
          </>
        )}
      </div>

      {/* 原先这里有运动科技 / cs.CV / 相关度 / arXiv ID 四个标签，已按需求移除 */}

      <div className={styles.articleActions}>
        {article.abstract && (
          <button
            className={styles.toggleAbstract}
            onClick={() => setShowAbstract(!showAbstract)}
          >
            {showAbstract ? '收起摘要 ▲' : '展开摘要 ▼'}
          </button>
        )}
        {pdfUrl && (
          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.pdfLink}
          >
            下载PDF →
          </a>
        )}
        {arxivUrl && (
          <a
            href={arxivUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.arxivLink}
          >
            查看原文 →
          </a>
        )}
      </div>

      {/* 摘要展示 */}
      {showAbstract && article.abstract && (
        <div className={styles.articleAbstract}>
          {/* 中英切换按钮 */}
          {article.abstract_zh && (
            <div className={styles.abstractToggle}>
              <button
                className={!showChinese ? styles.active : ''}
                onClick={() => setShowChinese(false)}
              >
                English
              </button>
              <button
                className={showChinese ? styles.active : ''}
                onClick={() => setShowChinese(true)}
              >
                中文
              </button>
            </div>
          )}

          {/* 英文摘要 */}
          {!showChinese && (
            <div className={styles.abstractOriginal}>
              <strong>Abstract：</strong>
              {article.abstract}
            </div>
          )}

          {/* 中文摘要 */}
          {showChinese && article.abstract_zh && (
            <div className={styles.abstractTranslation}>
              <strong>摘要：</strong>
              {article.abstract_zh}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ArticleItem
