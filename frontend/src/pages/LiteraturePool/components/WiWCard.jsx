/**
 * WiW Card - WiW卡片组件（复用模块3逻辑）
 */
import styles from '../LiteraturePool.module.css'
import { buildReferenceUrl, renderWiwTextWithReferenceLinks } from '../../../utils/wiwCitations'

function WiWCard({ card }) {
  const { card: cardContent, is_expired, source_pmid, track } = card

  const pubmedUrl = `https://pubmed.ncbi.nlm.nih.gov/${source_pmid}/`
  const references = Array.isArray(cardContent?.references) ? cardContent.references : []
  const topRecs = Array.isArray(cardContent?.top_journal_recommendations) ? cardContent.top_journal_recommendations : []

  return (
    <div className={styles.wiwCard}>
      {is_expired && (
        <div className={styles.expiredOverlay}>
          <span className={styles.expiredLabel}>已过期</span>
        </div>
      )}

      {/* 抬头：主文献信息 */}
      <div className={styles.cardHeader}>
        <span className={styles.trackBadge}>{track === 'stream' ? '文献流' : '顶刊'}</span>
        <a className={styles.pmid} href={pubmedUrl} target="_blank" rel="noopener noreferrer">
          主文献 · PMID: {source_pmid}
        </a>
      </div>

      {/* 卡片主体 */}
      <div className={styles.cardBody}>
        {cardContent?.focus && (
          <section className={styles.wiwSection}>
            <h3>研究聚焦</h3>
            <p>{renderWiwTextWithReferenceLinks(cardContent.focus, references, { linkClassName: styles.citationLink })}</p>
          </section>
        )}

        {Array.isArray(cardContent?.next_questions) && cardContent.next_questions.length > 0 && (
          <section className={styles.wiwSection}>
            <h3>下一步研究问题</h3>
            <ul>
              {cardContent.next_questions.map((q, idx) => (
                <li key={idx}>{renderWiwTextWithReferenceLinks(q, references, { linkClassName: styles.citationLink })}</li>
              ))}
            </ul>
          </section>
        )}

        {cardContent?.conflicts && (
          <section className={styles.wiwSection}>
            <h3>矛盾与冲突</h3>
            <p>{renderWiwTextWithReferenceLinks(cardContent.conflicts, references, { linkClassName: styles.citationLink })}</p>
          </section>
        )}

        {Array.isArray(cardContent?.gaps) && cardContent.gaps.length > 0 && (
          <section className={styles.wiwSection}>
            <h3>研究空白</h3>
            <ul>
              {cardContent.gaps.map((gap, idx) => (
                <li key={idx}>{renderWiwTextWithReferenceLinks(gap, references, { linkClassName: styles.citationLink })}</li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* 关联文献 */}
      {(references.length > 0 || topRecs.length > 0) && (
        <div className={styles.cardBody}>
          {references.length > 0 && (
            <section className={styles.wiwSection}>
              <h3>相关文献</h3>
              <div className={styles.recallList}>
                {references.slice(0, 10).map((ref, idx) => {
                  const url = buildReferenceUrl(ref)
                  const title = (ref && ref.title) ? String(ref.title) : ''
                  return (
                    <div key={`${ref.pmid || ref.doi || idx}`} className={styles.recallItem}>
                      <div className={styles.recallHeader}>
                        <span className={styles.recallIndex}>{idx + 1}</span>
                        {url ? (
                          <a href={url} target="_blank" rel="noopener noreferrer" className={styles.recallTitle}>
                            {title || url}
                          </a>
                        ) : (
                          <span className={styles.recallTitle}>{title || '未命名文献'}</span>
                        )}
                      </div>
                      {(ref?.pmid || ref?.doi) && (
                        <div className={styles.recallMeta}>
                          {ref?.pmid ? `PMID: ${ref.pmid}` : ''}
                          {ref?.pmid && ref?.doi ? ' | ' : ''}
                          {ref?.doi ? `DOI: ${ref.doi}` : ''}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {topRecs.length > 0 && (
            <section className={styles.wiwSection}>
              <h3>顶刊相似文献</h3>
              <div className={styles.recallList}>
                {topRecs.slice(0, 10).map((rec, idx) => {
                  const url = buildReferenceUrl(rec)
                  const title = (rec && rec.title) ? String(rec.title) : ''
                  const journal = (rec && rec.journal) ? String(rec.journal) : ''
                  return (
                    <div key={`${rec.pmid || rec.doi || idx}`} className={styles.recallItem}>
                      <div className={styles.recallHeader}>
                        <span className={styles.recallIndex}>{idx + 1}</span>
                        {url ? (
                          <a href={url} target="_blank" rel="noopener noreferrer" className={styles.recallTitle}>
                            {title || url}
                          </a>
                        ) : (
                          <span className={styles.recallTitle}>{title || '未命名文献'}</span>
                        )}
                      </div>
                      {(journal || rec?.pmid || rec?.doi) && (
                        <div className={styles.recallMeta}>
                          {journal ? `${journal}` : ''}
                          {journal && (rec?.pmid || rec?.doi) ? ' | ' : ''}
                          {rec?.pmid ? `PMID: ${rec.pmid}` : ''}
                          {rec?.pmid && rec?.doi ? ' | ' : ''}
                          {rec?.doi ? `DOI: ${rec.doi}` : ''}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )}
        </div>
      )}

      <div className={styles.cardFooter}>
        <span>生成于 {new Date(card.generated_at).toLocaleString()}</span>
      </div>
    </div>
  )
}

export default WiWCard
