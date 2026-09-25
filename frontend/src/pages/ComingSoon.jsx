import './ComingSoon.css'

/**
 * 开发中占位符组件
 */
export default function ComingSoon({ title = '功能开发中' }) {
  return (
    <div className="coming-soon">
      <div className="coming-soon-content">
        <h2>🚧 {title}</h2>
        <p>该功能正在开发中，敬请期待...</p>
      </div>
    </div>
  )
}
