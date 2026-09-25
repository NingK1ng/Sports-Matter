import { useState } from 'react'

/**
 * 分页 Hook
 * 
 * @param {number} initialPage - 初始页码（默认1）
 * @param {number} totalItems - 总条数
 * @param {number} perPage - 每页条数（默认20）
 * @returns {object} { page, setPage, nextPage, prevPage, goToPage, totalPages }
 */
export default function usePagination(initialPage = 1, totalItems = 0, perPage = 20) {
  const [page, setPage] = useState(initialPage)

  const totalPages = Math.ceil(totalItems / perPage)

  const nextPage = () => {
    if (page < totalPages) {
      setPage(page + 1)
    }
  }

  const prevPage = () => {
    if (page > 1) {
      setPage(page - 1)
    }
  }

  const goToPage = (pageNumber) => {
    const validPage = Math.max(1, Math.min(pageNumber, totalPages))
    setPage(validPage)
  }

  return {
    page,
    setPage,
    nextPage,
    prevPage,
    goToPage,
    totalPages,
  }
}
