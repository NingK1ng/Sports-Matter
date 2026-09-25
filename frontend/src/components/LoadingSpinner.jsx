import styles from './LoadingSpinner.module.css'

/**
 * 加载动画组件
 * 
 * @param {object} props
 * @param {string} props.type - 类型（'skeleton' | 'spinner'，默认'skeleton'）
 * @param {number} props.count - 骨架屏数量（默认5）
 * @param {string} props.message - 加载提示文本（可选）
 */
export default function LoadingSpinner({ 
  type = 'skeleton', 
  count = 5, 
  message = '加载中...' 
}) {
  if (type === 'skeleton') {
    return (
      <div className={styles.articlesList}>
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className={styles.skeletonItem}>
            <div className={`${styles.skeleton} ${styles.skeletonTitle}`}></div>
            <div className={`${styles.skeleton} ${styles.skeletonMeta}`}></div>
            <div className={styles.skeletonTags}>
              <div className={`${styles.skeleton} ${styles.skeletonTag}`}></div>
              <div className={`${styles.skeleton} ${styles.skeletonTag}`}></div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  // spinner 类型
  return (
    <div className={styles.spinnerContainer}>
      <div className={styles.spinner}></div>
      {message && <p className={styles.message}>{message}</p>}
    </div>
  )
}
