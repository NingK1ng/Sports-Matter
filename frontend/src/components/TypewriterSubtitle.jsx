import { useState, useEffect } from 'react'
import styles from './TypewriterSubtitle.module.css'

function TypewriterSubtitle({
  text,
  className = '',
  active = true,
  loop = true,
  typeDelay = 60,
  deleteDelay = 30,
  holdDelay = 1800,
}) {
  const [displayText, setDisplayText] = useState('')
  
  // 支持字符串或数组
  const texts = Array.isArray(text) ? text : [text]

  useEffect(() => {
    // 未激活时不启动打字机
    if (!active) {
      setDisplayText('')
      return
    }

    let currentTextIndex = 0
    let charIndex = 0
    let timeoutId

    const type = () => {
      const currentText = texts[currentTextIndex]
      if (charIndex <= currentText.length) {
        setDisplayText(currentText.slice(0, charIndex))
        charIndex++
        timeoutId = setTimeout(type, typeDelay)
      } else {
        // 当前句子已经完整显示
        if (!loop && currentTextIndex === texts.length - 1) {
          // 非循环模式下，最后一句打完后停留在此
          return
        }
        timeoutId = setTimeout(deleteSubtitle, holdDelay)
      }
    }

    const deleteSubtitle = () => {
      const currentText = texts[currentTextIndex]
      if (charIndex > 0) {
        setDisplayText(currentText.slice(0, charIndex - 1))
        charIndex--
        timeoutId = setTimeout(deleteSubtitle, deleteDelay)
      } else {
        // 切换到下一段文本
        if (!loop && currentTextIndex >= texts.length - 1) {
          // 非循环模式且已经是最后一句，直接停止
          return
        }
        currentTextIndex = (currentTextIndex + 1) % texts.length
        charIndex = 0
        timeoutId = setTimeout(type, 250)
      }
    }

    const startTimer = setTimeout(() => {
      type()
    }, 250)

    return () => {
      clearTimeout(startTimer)
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [active, loop, typeDelay, deleteDelay, holdDelay])

  return (
    <p className={`${styles.subtitle} ${className}`}>
      {displayText}
      <span className={styles.cursor}>|</span>
    </p>
  )
}

export default TypewriterSubtitle
