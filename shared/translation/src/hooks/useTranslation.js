/**
 * useTranslation Hook
 * 
 * 在React组件中使用翻译功能
 */

import { useContext } from 'react';
import { TranslationContext } from '../components/TranslationProvider';

export function useTranslation() {
  const context = useContext(TranslationContext);
  
  if (!context) {
    throw new Error('useTranslation must be used within TranslationProvider');
  }
  
  return context;
}
