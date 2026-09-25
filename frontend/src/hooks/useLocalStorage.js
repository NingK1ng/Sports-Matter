import { useState, useEffect } from 'react'

/**
 * 本地存储 Hook
 * 
 * @param {string} key - 存储键
 * @param {any} initialValue - 初始值
 * @returns {array} [value, setValue, removeValue]
 */
export default function useLocalStorage(key, initialValue) {
  // 从 localStorage 读取初始值
  const [value, setValue] = useState(() => {
    try {
      const item = window.localStorage.getItem(key)
      return item ? JSON.parse(item) : initialValue
    } catch (error) {
      console.warn(`读取 localStorage 失败: ${key}`, error)
      return initialValue
    }
  })

  // 当值变化时自动保存到 localStorage
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch (error) {
      console.warn(`保存 localStorage 失败: ${key}`, error)
    }
  }, [key, value])

  // 删除值
  const removeValue = () => {
    try {
      window.localStorage.removeItem(key)
      setValue(initialValue)
    } catch (error) {
      console.warn(`删除 localStorage 失败: ${key}`, error)
    }
  }

  return [value, setValue, removeValue]
}
