/**
 * Subscription List - 订阅列表组件
 */
import styles from '../LiteraturePool.module.css'

function SubscriptionList({
  subscriptions,
  selectedSubscription,
  onSelectSubscription,
  onDeleteSubscription,
  onRefreshSubscription
}) {
  return (
    <div className={styles.subscriptionList}>
      {subscriptions.map(subscription => (
        <div
          key={subscription.id}
          className={`${styles.subscriptionItem} ${
            selectedSubscription?.id === subscription.id ? styles.subscriptionItemActive : ''
          }`}
          onClick={() => onSelectSubscription(subscription)}
        >
          <div className={styles.subscriptionInfo}>
            <h3>{subscription.title}</h3>
            <p className={styles.queryText}>{subscription.query_text}</p>
            <span className={styles.createdDate}>
              创建于 {new Date(subscription.created_at).toLocaleDateString()}
            </span>
          </div>
          
          <div className={styles.subscriptionActions}>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onRefreshSubscription(subscription.id)
              }}
              className={`${styles.actionBtn} ${styles.refreshBtn}`}
              title="刷新订阅"
            >
              刷新
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDeleteSubscription(subscription.id)
              }}
              className={`${styles.actionBtn} ${styles.deleteBtn}`}
              title="删除订阅"
            >
              删除
            </button>
          </div>
        </div>
      ))}
      
      {subscriptions.length === 0 && (
        <div className={styles.emptySubscriptions}>
          <p>暂无订阅</p>
          <p>点击上方"新建订阅"开始</p>
        </div>
      )}
    </div>
  )
}

export default SubscriptionList
