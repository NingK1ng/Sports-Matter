/**
 * Literature Pool - 文献池主页面
 * 
 * 免登录订阅管理和Feed流展示
 */
import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import SubscriptionManager from './components/SubscriptionManager'
import FeedView from './components/FeedView'
import styles from './LiteraturePool.module.css'

function LiteraturePool() {
  const outlet = useOutletContext()
  const authSession = outlet?.authSession

  const [selectedSubscription, setSelectedSubscription] = useState(null)
  const [titleVisible, setTitleVisible] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  if (!authSession) {
    return (
      <div className={styles.literaturePool}>
        <header className={styles.pageHeader}>
          <div className={styles.pageHeaderInner}>
            <span className={styles.pigeonBird} aria-hidden="true" />
            <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>Sports Pigeon</h1>
          </div>
          <TypewriterSubtitle text={['加载中...']} active={titleVisible} />
        </header>
      </div>
    )
  }


  return (
    <div className={styles.literaturePool}>
      <header className={styles.pageHeader}>
        <div className={styles.pageHeaderInner}>
          <span className={styles.pigeonBird} aria-hidden="true" />
          <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>Sports Pigeon</h1>
        </div>
        <TypewriterSubtitle
          text={[
            '给鸽子脚上绑点关键词吧！',
            '飞鸽传信，静候佳音！',
          ]}
          active={titleVisible}
        />
      </header>
      
      <div className={styles.poolContent}>
        <div className={styles.subscriptionSidebar}>
          <SubscriptionManager
            selectedSubscription={selectedSubscription}
            onSelectSubscription={setSelectedSubscription}

          />
        </div>
        
        <div className={styles.feedMain}>
          {selectedSubscription ? (
            <FeedView
              subscription={selectedSubscription}

            />
          ) : (
            <div className={styles.emptyState}>
              <p>👈 请选择或创建一个订阅</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default LiteraturePool
