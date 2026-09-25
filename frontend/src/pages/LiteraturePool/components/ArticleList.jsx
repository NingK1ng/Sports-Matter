/**
 * Article List - 文献列表组件
 */
import styles from '../LiteraturePool.module.css'

function ArticleList({ articles }) {
  return (
    <div className={styles.recallList}>
      {articles.map((article, idx) => {
        const authors = Array.isArray(article.authors) ? article.authors : []
        const authorNames = authors
          .map((a) => (typeof a === 'string' ? a : (a?.name || a?.full_name || '')))
          .filter(Boolean)
        const displayAuthors = authorNames.slice(0, 3).join(', ')

        const pmid = article.pmid ? String(article.pmid).trim() : ''
        const doi = article.doi ? String(article.doi).trim() : ''
        const pmidUrl = pmid ? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/` : null
        const doiUrl = doi ? `https://doi.org/${doi}` : null
        const url = doiUrl || pmidUrl

        const journalName = article.journal_name || article.journal || ''
        const publicationDate = article.publication_date ? String(article.publication_date) : ''
        const citedBy = typeof article.cited_by_count === 'number'
          ? article.cited_by_count
          : (typeof article.citations === 'number' ? article.citations : null)

        const snippet = article.abstract
          ? String(article.abstract).slice(0, 240)
          : ''

        return (
          <div key={article.id || doi || pmid || idx} className={styles.recallItem}>
            <div className={styles.recallHeader}>
              <span className={styles.recallIndex}>{idx + 1}</span>
              {url ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.recallTitle}
                >
                  {article.title}
                </a>
              ) : (
                <span className={styles.recallTitle}>{article.title}</span>
              )}
            </div>

            <div className={styles.recallMeta}>
              {journalName || '未知期刊'}
              {publicationDate ? ` · ${publicationDate}` : ''}
              {pmid ? ` · PMID: ${pmid}` : ''}
              {doi ? ` · DOI: ${doi}` : ''}
              {typeof citedBy === 'number' && citedBy > 0 ? ` · 被引 ${citedBy}` : ''}
            </div>

            {snippet && (
              <div className={styles.recallMeta} style={{ marginTop: 6 }}>
                {snippet}{article.abstract && String(article.abstract).length > 240 ? '...' : ''}
              </div>
            )}

            {authorNames.length > 0 && (
              <div className={styles.recallMeta} style={{ marginTop: 6 }}>
                作者: {displayAuthors}
                {authorNames.length > 3 && ` 等 ${authorNames.length} 人`}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default ArticleList
