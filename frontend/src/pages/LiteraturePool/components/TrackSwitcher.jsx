/**
 * Track Switcher - 轨道切换组件
 */
import styles from '../LiteraturePool.module.css'

function TrackSwitcher({ selectedTrack, onSelectTrack }) {
  const tracks = [
    { id: 'all', label: '全部' },
    { id: 'stream', label: '文献流' },
    { id: 'journals', label: '顶刊' }
  ]
  
  return (
    <div className={styles.trackSwitcher}>
      {tracks.map(track => (
        <button
          key={track.id}
          className={`${styles.trackBtn} ${selectedTrack === track.id ? styles.active : ''}`}
          onClick={() => onSelectTrack(track.id)}
        >
          {track.label}
        </button>
      ))}
    </div>
  )
}

export default TrackSwitcher
