/**
 * 翻译按钮组件
 */

import React, { useState } from 'react';
import { useTranslation } from '../hooks/useTranslation';

export function TranslateButton({ text, onTranslated, children }) {
  const { translate, isLoading: engineLoading, isReady } = useTranslation();
  const [translating, setTranslating] = useState(false);
  const [result, setResult] = useState(null);

  const handleClick = async () => {
    if (!text || !isReady) return;

    try {
      setTranslating(true);
      const translated = await translate(text);
      setResult(translated);
      
      if (onTranslated) {
        onTranslated(translated);
      }
    } catch (error) {
      console.error('翻译失败:', error);
    } finally {
      setTranslating(false);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={!isReady || translating || engineLoading}
      style={{
        padding: '8px 16px',
        backgroundColor: isReady ? '#1890ff' : '#d9d9d9',
        color: 'white',
        border: 'none',
        borderRadius: '4px',
        cursor: isReady ? 'pointer' : 'not-allowed',
      }}
    >
      {translating ? '翻译中...' : children || '翻译'}
    </button>
  );
}
