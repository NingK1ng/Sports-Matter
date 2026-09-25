import styles from './Pagination.module.css'

/**
 * 分页组件
 * 
 * @param {object} props
 * @param {number} props.currentPage - 当前页码（1-based）
 * @param {number} props.totalPages - 总页数
 * @param {number} props.totalItems - 总条数（可选，用于显示）
 * @param {number} props.perPage - 每页条数（默认20）
 * @param {function} props.onPageChange - 页码变化回调
 */
export default function Pagination({ 
  currentPage, 
  totalPages, 
  totalItems = 0,
  perPage = 20,
  onPageChange 
}) {
  // 如果总数不足一页，不显示分页
  if (totalItems <= perPage) {
    return null
  }

  const handlePrev = () => {
    if (currentPage > 1) {
      onPageChange(currentPage - 1)
    }
  }

  const handleNext = () => {
    if (currentPage < totalPages) {
      onPageChange(currentPage + 1)
    }
  }

  return (
    <div className={styles.pagination}>
      <button 
        disabled={currentPage === 1}
        onClick={handlePrev}
        className={styles.button}
      >
        上一页
      </button>
      <span className={styles.info}>
        第 {currentPage} / {totalPages} 页
      </span>
      <button 
        disabled={currentPage >= totalPages}
        onClick={handleNext}
        className={styles.button}
      >
        下一页
      </button>
    </div>
  )
}
