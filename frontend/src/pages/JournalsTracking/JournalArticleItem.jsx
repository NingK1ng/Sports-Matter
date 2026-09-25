import { useState } from 'react'
import styles from './JournalsTracking.module.css'

function JournalArticleItem({ article, index }) {
  const [showAbstract, setShowAbstract] = useState(false)
  const [abstractTranslation, setAbstractTranslation] = useState(null)
  const [translatingAbstract, setTranslatingAbstract] = useState(false)

  // 构建链接
  const pubmedUrl = article.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${article.pmid}/` : null
  const doiUrl = article.doi ? `https://doi.org/${article.doi}` : null
  const officialUrl = doiUrl || pubmedUrl

  // 翻译摘要
  const handleTranslateAbstract = async () => {
    if (translatingAbstract || !article.abstract || !article.id) return

    setTranslatingAbstract(true)
    try {
      const response = await fetch('/api/v1/translate/abstract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: String(article.id),
          abstract: article.abstract,
          source_type: 'journal'
        })
      })

      if (!response.ok) {
        throw new Error(`翻译失败: ${response.statusText}`)
      }

      const result = await response.json()
      setAbstractTranslation(result.abstract_zh)
    } catch (error) {
      console.error('摘要翻译失败:', error)
      alert(`摘要翻译失败: ${error.message}`)
    } finally {
      setTranslatingAbstract(false)
    }
  }

  return (
    <div className={styles.articleItem}>
      <div
        className={styles.articleTitle}
        onClick={() => officialUrl && window.open(officialUrl, '_blank')}
        style={{ cursor: officialUrl ? 'pointer' : 'default' }}
      >
        <span>{article.title}</span>
      </div>

      {/* 中文标题（从API获取） */}
      {article.title_zh && (
        <div className={styles.titleTranslation}>
          <strong>中文标题：</strong>{article.title_zh}
        </div>
      )}

      <div className={styles.articleMeta}>
        <span className={styles.metaJournal}>
          {article.journal_name || '未知期刊'}
        </span>
        {(() => {
          const c = typeof article.cited_by_count === 'number'
            ? article.cited_by_count
            : article.citations
          return typeof c === 'number'
            ? (
              <>
                <span className={styles.metaSeparator}>·</span>
                <span className={styles.metaCitations}>被引: {c}</span>
              </>
            )
            : null
        })()}
        <span className={styles.metaSeparator}>·</span>
        <span className={styles.metaDate}>{article.publication_date}</span>
      </div>

      <div className={styles.articleActions}>
        {article.abstract && (
          <button
            className={styles.toggleAbstract}
            onClick={() => setShowAbstract(!showAbstract)}
          >
            {showAbstract ? '收起摘要 ▲' : '展开摘要 ▼'}
          </button>
        )}
        {doiUrl && (
          <a
            href={doiUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.pubmedLink}
          >
            查看原文 →
          </a>
        )}
        {pubmedUrl && (
          <a
            href={pubmedUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.pubmedLink}
          >
            PubMed →
          </a>
        )}
      </div>

      {/* 摘要 */}
      {showAbstract && article.abstract && (
        <div className={styles.articleAbstract}>
          <div className={styles.abstractOriginal}>
            <strong>英文摘要：</strong>
            {article.abstract}
          </div>

          {/* 摘要翻译按钮 */}
          {!abstractTranslation && (
            <button
              className={styles.translateAbstractBtn}
              onClick={handleTranslateAbstract}
              disabled={translatingAbstract}
            >
              {translatingAbstract ? '翻译中...' : '翻译摘要'}
            </button>
          )}

          {/* 中文摘要 */}
          {abstractTranslation && (
            <div className={styles.abstractTranslation}>
              <strong>中文摘要：</strong>
              {abstractTranslation}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default JournalArticleItem
