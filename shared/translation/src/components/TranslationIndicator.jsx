/**
 * 翻译状态指示器
 */

import React from 'react';
import { useTranslation } from '../hooks/useTranslation';

export function TranslationIndicator() {
  const { isLoading, isReady, error } = useTranslation();

  if (isLoading) {
    return (
      <div style={{ padding: '16px', textAlign: 'center', color: '#1890ff' }}>
        <span>🔄 正在加载翻译引擎...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '16px', textAlign: 'center', color: '#ff4d4f' }}>
        <span>❌ 翻译引擎加载失败: {error}</span>
      </div>
    );
  }

  if (isReady) {
    return (
      <div style={{ padding: '8px', textAlign: 'center', color: '#52c41a', fontSize: '12px' }}>
        <span>✅ 离线翻译已就绪</span>
      </div>
    );
  }

  return null;
}
