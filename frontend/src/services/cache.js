/**
 * 缓存服务
 * 
 * 提供统一的 LocalStorage 封装，支持 TTL 和命名空间
 */

const DEFAULT_TTL = 30 * 24 * 60 * 60 * 1000 // 30天

/**
 * 获取缓存
 * @param {string} key - 缓存键
 * @param {string} namespace - 命名空间（默认'default'）
 * @returns {any|null} 缓存值
 */
export function getCache(key, namespace = 'default') {
  try {
    const fullKey = `${namespace}_${key}`
    const raw = localStorage.getItem(fullKey)
    if (!raw) return null

    const obj = JSON.parse(raw)
    if (!obj || obj.value === undefined || !obj.timestamp) return null

    // 检查是否过期
    const ttl = obj.ttl || DEFAULT_TTL
    if (Date.now() - obj.timestamp > ttl) {
      localStorage.removeItem(fullKey)
      return null
    }

    return obj.value
  } catch {
    return null
  }
}

/**
 * 设置缓存
 * @param {string} key - 缓存键
 * @param {any} value - 缓存值
 * @param {number} ttl - 过期时间（毫秒，默认30天）
 * @param {string} namespace - 命名空间（默认'default'）
 */
export function setCache(key, value, ttl = DEFAULT_TTL, namespace = 'default') {
  try {
    const fullKey = `${namespace}_${key}`
    const obj = {
      value,
      timestamp: Date.now(),
      ttl,
    }
    localStorage.setItem(fullKey, JSON.stringify(obj))
  } catch (e) {
    console.warn('缓存设置失败:', e)
  }
}

/**
 * 删除缓存
 * @param {string} key - 缓存键
 * @param {string} namespace - 命名空间（默认'default'）
 */
export function removeCache(key, namespace = 'default') {
  try {
    const fullKey = `${namespace}_${key}`
    localStorage.removeItem(fullKey)
  } catch {}
}

/**
 * 清除指定命名空间的所有缓存
 * @param {string} namespace - 命名空间
 */
export function clearNamespace(namespace) {
  try {
    const prefix = `${namespace}_`
    const keysToRemove = []

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith(prefix)) {
        keysToRemove.push(key)
      }
    }

    keysToRemove.forEach(key => localStorage.removeItem(key))
  } catch (e) {
    console.warn('清除缓存失败:', e)
  }
}

export default {
  getCache,
  setCache,
  removeCache,
  clearNamespace,
}
