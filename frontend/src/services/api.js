/**
 * 统一 API 调用服务
 * 
 * 提供统一的 fetch 封装、错误处理和请求拦截
 */

// Use Vite proxy in dev by default; backend will be '/v1' after proxy rewrite
const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

/**
 * 统一 fetch 封装（带错误处理）
 * @param {string} url - API 路径
 * @param {object} options - fetch 选项
 * @returns {Promise<any>} JSON 响应数据
 */
async function fetchWithError(url, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${url}`, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    })
    
    if (!response.ok) {
      let payload = null
      try {
        payload = await response.json()
      } catch {
        payload = null
      }
      const detail = payload?.detail ?? payload?.error ?? null
      const message =
        (typeof detail === 'string' && detail) ||
        (detail && typeof detail.message === 'string' && detail.message) ||
        (payload && typeof payload.message === 'string' && payload.message) ||
        (payload && typeof payload.msg === 'string' && payload.msg) ||
        `HTTP ${response.status}: ${response.statusText}`
      const err = new Error(message)
      err.status = response.status
      err.payload = payload
      throw err
    }
    
    return await response.json()
  } catch (error) {
    console.error(`API Error: ${url}`, error)
    throw error
  }
}

/**
 * 模块1 - 文献流 API
 */
export const literatureStreamAPI = {
  /**
   * 获取学科分类列表
   */
  async fetchCategories() {
    return await fetchWithError('/stream/categories')
  },

  /**
   * 获取文献列表
   * @param {object} params - 查询参数
   */
  async fetchLiterature(params) {
    const queryString = new URLSearchParams(params).toString()
    return await fetchWithError(`/stream/literature?${queryString}`)
  },
}

/**
 * 模块2 - 顶刊追踪 API
 */
export const journalsAPI = {
  /**
   * 获取期刊列表
   * @param {string} category - 分类（sports_science 或 cns）
   */
  async fetchJournalsList(category) {
    return await fetchWithError(`/journals/list?category=${encodeURIComponent(category)}`)
  },

  /**
   * 获取文章列表
   * @param {object} params - 查询参数
   */
  async fetchJournalArticles(params) {
    const queryString = new URLSearchParams(params).toString()
    return await fetchWithError(`/journals/articles?${queryString}`)
  },
}

/**
 * 模块8 - arXiv预印本前沿 API
 */
export const arxivAPI = {
  /**
   * 获取运动科学分类列表
   */
  async fetchCategories() {
    return await fetchWithError('/arxiv/categories')
  },

  /**
   * 获取arXiv文章列表
   * @param {object} params - 查询参数
   */
  async fetchArticles(params) {
    const queryString = new URLSearchParams(params).toString()
    return await fetchWithError(`/arxiv/articles?${queryString}`)
  },

  /**
   * 获取单篇文章详情
   * @param {string} arxivId - arXiv ID
   */
  async fetchArticleDetail(arxivId) {
    return await fetchWithError(`/arxiv/articles/${arxivId}`)
  },

  /**
   * 获取统计数据
   */
  async fetchStats() {
    return await fetchWithError('/arxiv/stats')
  },
}

/**
 * Sports Data 模块 API
 */
export const sportsDataAPI = {
  /**
   * 搜索公开运动科学数据集（英文关键词）
   * @param {{ query: string, limit: number }} params
   */
  async searchDatasets({ query, limit }) {
    const searchParams = new URLSearchParams()
    if (query) searchParams.set('q', query)
    if (limit) searchParams.set('limit', String(limit))
    const qs = searchParams.toString()
    return await fetchWithError(`/sports-data/datasets?${qs}`)
  },
  /**
   * 搜索运动科学相关的代码仓库与模型
   * @param {{ query: string, limit: number }} params
   */
  async searchCode({ query, limit }) {
    const searchParams = new URLSearchParams()
    if (query) searchParams.set('q', query)
    if (limit) searchParams.set('limit', String(limit))
    const qs = searchParams.toString()
    return await fetchWithError(`/sports-data/code?${qs}`)
  },
  /**
   * 搜索报告与Dashboard等分析资源
   * @param {{ query: string, limit: number }} params
   */
  async searchReports({ query, limit }) {
    const searchParams = new URLSearchParams()
    if (query) searchParams.set('q', query)
    if (limit) searchParams.set('limit', String(limit))
    const qs = searchParams.toString()
    return await fetchWithError(`/sports-data/reports?${qs}`)
  },
  /**
   * 搜索量表与问卷工具
   * @param {{ query: string, limit: number }} params
   */
  async searchScales({ query, limit }) {
    const searchParams = new URLSearchParams()
    if (query) searchParams.set('q', query)
    if (limit) searchParams.set('limit', String(limit))
    const qs = searchParams.toString()
    return await fetchWithError(`/sports-data/scales?${qs}`)
  },
}

/**
 * 通用导出（为模块3-6预留）
 */
export default {
  literatureStream: literatureStreamAPI,
  journals: journalsAPI,
  arxiv: arxivAPI,
  sportsData: sportsDataAPI,
}
