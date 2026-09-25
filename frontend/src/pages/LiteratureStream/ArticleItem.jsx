import { useState } from 'react'
import styles from './LiteratureStream.module.css'

function ArticleItem({ article, index }) {
  const [showAbstract, setShowAbstract] = useState(false)
  const [abstractTranslation, setAbstractTranslation] = useState(null)
  const [translatingAbstract, setTranslatingAbstract] = useState(false)

  const getCategoryLabel = (key) => {
    const labels = {
      'sports_education': '体育教育',
      'training_science': '运动训练',
      'fitness_monitoring': '体质健康',
      'exercise_science': '运动科学',
      'sports_medicine': '运动医学',
      'sport_psychology': '运动心理',
      'sport_humanities': '体育人文',
      'sport_engineering': '体育工程'
    }
    return labels[key] || key
  }

  const getTypeLabel = (key) => {
    const labels = {
      'meta_analysis': 'Meta分析',
      'original': '原创研究',
      'original_human': '原创研究(人)',
      'original_animal': '原创研究(动物)',
      'review': '综述',
      'guideline': '指南'
    }
    return labels[key] || key
  }

  // 构建链接
  const pubmedUrl = article.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${article.pmid}/` : null
  const doiUrl = article.doi ? `https://doi.org/${article.doi.replace('doi: ', '').replace('DOI: ', '')}` : null
  const officialUrl = doiUrl || pubmedUrl

  // 翻译摘要
  const handleTranslateAbstract = async () => {
    if (translatingAbstract || !article.abstract || !article.pmid) return

    setTranslatingAbstract(true)
    try {
      const response = await fetch('/api/v1/translate/abstract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: article.pmid,
          abstract: article.abstract,
          source_type: 'literature'
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
        <span>
          {article.title}
          {article.pmid ? <span className={styles.articlePmid}> (PMID: {article.pmid})</span> : null}
        </span>
      </div>

      {/* 中文标题（从API获取） */}
      {article.title_zh && (
        <div className={styles.titleTranslation}>
          <strong>中文标题：</strong>{article.title_zh}
        </div>
      )}

      <div className={styles.articleMeta}>
        <span className={styles.metaAuthors}>
          {Array.isArray(article.authors) && article.authors.slice(0, 3).join(', ')}
          {Array.isArray(article.authors) && article.authors.length > 3 && ', et al.'}
        </span>
        <span className={styles.metaSeparator}>·</span>
        <span className={styles.metaJournal}>{article.journal_name || '未知期刊'}</span>
        <span className={styles.metaSeparator}>·</span>
        <span className={styles.metaDate}>{article.publication_date}</span>
      </div>

      <div className={styles.articleTags}>
        {Array.isArray(article.subject_categories) && article.subject_categories.map((c) => (
          <span key={c} className={`${styles.tag} ${styles.tagCategory}`}>{getCategoryLabel(c)}</span>
        ))}
        {Array.isArray(article.literature_types) && article.literature_types.map((t) => (
          <span key={t} className={`${styles.tag} ${styles.tagType}`}>{getTypeLabel(t)}</span>
        ))}
        {(() => {
          const raw = article?.journal_if_5y ?? article?.journalIf5 ?? article?.if5
          const num = typeof raw === 'number' ? raw : (raw != null ? parseFloat(String(raw)) : NaN)
          return Number.isFinite(num) ? (
            <span className={`${styles.tag} ${styles.tagIf}`}>
              IF {num.toFixed(2)}
            </span>
          ) : null
        })()}
        {(() => {
          const zoneRaw = article?.journal_zone ?? article?.journalZone ?? article?.cas_zone
          const zone = zoneRaw && String(zoneRaw).trim()
          if (!zone) return null
          const upper = zone.toUpperCase()
          let label
          if (upper.startsWith('Q1')) {
            label = '中科院1区'
          } else if (upper.startsWith('Q2')) {
            label = '中科院2区'
          } else if (upper.startsWith('Q3')) {
            label = '中科院3区'
          } else if (upper.startsWith('Q4')) {
            label = '中科院4区'
          } else if (zone.includes('1区')) {
            label = '中科院1区'
          } else if (zone.includes('2区')) {
            label = '中科院2区'
          } else if (zone.includes('3区')) {
            label = '中科院3区'
          } else if (zone.includes('4区')) {
            label = '中科院4区'
          } else {
            label = `中科院${zone}`
          }
          return (
            <span className={`${styles.tag} ${styles.tagZone}`}>
              {label}
            </span>
          )
        })()}
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

      {/* 摘要展示 */}
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

export default ArticleItem
