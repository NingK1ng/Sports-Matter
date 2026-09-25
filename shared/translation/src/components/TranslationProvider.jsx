/**
 * Translation Context Provider
 * 
 * 为整个应用提供翻译能力
 */

import React, { createContext, useState, useEffect, useCallback } from 'react';
import { TranslationEngine } from '../engine/TranslationEngine';

export const TranslationContext = createContext(null);

export function TranslationProvider({ children, config = {} }) {
  const [engine, setEngine] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState(null);

  // 初始化翻译引擎
  useEffect(() => {
    const initEngine = async () => {
      try {
        setIsLoading(true);
        const translationEngine = new TranslationEngine(config);
        await translationEngine.initialize();
        
        setEngine(translationEngine);
        setIsReady(true);
        setError(null);
      } catch (err) {
        console.error('翻译引擎初始化失败:', err);
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    initEngine();

    // 清理
    return () => {
      if (engine) {
        engine.dispose();
      }
    };
  }, []);

  // 翻译单个文本
  const translate = useCallback(async (text) => {
    if (!engine || !isReady) {
      throw new Error('翻译引擎未就绪');
    }
    return await engine.translate(text);
  }, [engine, isReady]);

  // 批量翻译
  const translateBatch = useCallback(async (texts) => {
    if (!engine || !isReady) {
      throw new Error('翻译引擎未就绪');
    }
    return await engine.translateBatch(texts);
  }, [engine, isReady]);

  const value = {
    translate,
    translateBatch,
    isLoading,
    isReady,
    error,
  };

  return (
    <TranslationContext.Provider value={value}>
      {children}
    </TranslationContext.Provider>
  );
}
