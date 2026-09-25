/**
 * 研究空白Agent - 主页面组件
 * 
 * 功能：
 * - 支持PMID/DOI两种输入方式
 * - 调用后端API生成WiW分析
 * - 展示WiW卡片和相关文献
 * - 展示顶刊推荐
 */

import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import TypewriterSubtitle from '../../components/TypewriterSubtitle';
import { renderWiwTextWithReferenceLinks } from '../../utils/wiwCitations'
import styles from './ResearchGap.module.css';

const ResearchGap = () => {
  const outlet = useOutletContext()
  const authSession = outlet?.authSession
  const [inputType, setInputType] = useState('pmid'); // pmid | doi
  const [inputValue, setInputValue] = useState('');
  const [topK, setTopK] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [titleVisible, setTitleVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300);
    return () => clearTimeout(timer);
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // 前端验证
    if (!inputValue.trim()) {
      setError('请输入PMID或DOI');
      return;
    }
    
    if (inputType === 'pmid' && !/^\d{6,9}$/.test(inputValue.trim())) {
      setError('PMID必须是6-9位数字');
      return;
    }
    
    if (inputType === 'doi' && !inputValue.trim().startsWith('10.')) {
      setError('DOI必须以"10."开头');
      return;
    }
    
    setLoading(true);
    setError(null);
    setResult(null);

    // 设置超时控制器（10分钟）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000);

    try {
      const requestBody = {
        [inputType]: inputValue.trim(),
        top_k: topK,
        language: 'zh',
        enable_inspiration: true
      };

      const response = await fetch('/api/v1/wiw/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal  // 添加超时控制
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail?.message || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setResult(data);
    } catch (err) {
      clearTimeout(timeoutId);
      
      // 处理不同类型的错误
      if (err.name === 'AbortError') {
        setError('请求超时（10分钟）。可能原因：1) DeepSeek推理时间过长 2) DOI解析失败 3) 网络问题。建议：尝试使用PMID或减少top_k参数。');
      } else {
        setError(err.message || '生成失败，请重试');
      }
    } finally {
      setLoading(false);
    }
  };

  const hasSearched = loading || !!result || !!error;
  const isMember = Boolean(authSession?.user?.is_member)
  const wiwQuota = authSession?.quota?.features?.wiw_generate
  const quotaHint = isMember
    ? '会员不限次数'
    : wiwQuota
        ? `本周剩余：${wiwQuota.remaining}/${wiwQuota.limit}`
        : '未登录/非会员每周免费 3 次'

  return (
    <div className={`${styles.container} ${!hasSearched ? styles.initial : ''}`}>
      <div className={styles.header}>
        <h1 className={titleVisible ? styles.fadeIn : ''}>What's it Worth?</h1>
        <TypewriterSubtitle
          text={[
            '输入文献DOI，等待鸽子为您关联相关文献，综合分析研究空白！',
            "那么，What's it worth？",
          ]}
          className={styles.customSubtitle}
          active={titleVisible}
        />
      </div>

      {/* 输入表单 */}
      <form
        onSubmit={handleSubmit}
        className={`${styles.inputForm} ${titleVisible ? styles.inputFormVisible : ''}`}
      >
        <div className={styles.inputTypeSelector}>
          <label>
            <input
              type="radio"
              value="pmid"
              checked={inputType === 'pmid'}
              onChange={(e) => setInputType(e.target.value)}
            />
            PMID
          </label>
          <label>
            <input
              type="radio"
              value="doi"
              checked={inputType === 'doi'}
              onChange={(e) => setInputType(e.target.value)}
            />
            DOI
          </label>
        </div>

        <div className={styles.inputGroup}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={
              inputType === 'pmid'
                ? '输入PMID（8位数字）'
                : '输入DOI（如10.1038/s41586-023-06139-9）'
            }
            required
            className={styles.input}
          />

          <select
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className={styles.select}
          >
            <option value={5}>Top 5</option>
            <option value={10}>Top 10</option>
            <option value={15}>Top 15</option>
          </select>

          <button
            type="submit"
            disabled={loading}
            className={styles.submitButton}
          >
            {loading ? '生成中...' : '生成WiW'}
          </button>
        </div>
      </form>

      {/* 错误提示 */}
      {error && (
        <div className={styles.error}>
          ❌ 错误: {error}
        </div>
      )}

      {/* 加载提示 */}
      {loading && (
        <div className={styles.loading}>
          <div className={styles.spinner}></div>
          <TypewriterSubtitle
            text={[
              '鸽子正在补充燃料...',
              '鸽子正在戴上老花镜...',
              '鸽子正在阅读文献...',
              '鸽子正在思考...',
              '鸽子快总结好了，稍等片刻！',
            ]}
            loop={false}
            active={titleVisible && loading}
            typeDelay={90}
            deleteDelay={45}
            holdDelay={3000}
          />
        </div>
      )}

      {/* 结果展示 */}
      {result && (
        <div className={styles.results}>
          {/* WiW卡片 */}
          <div className={styles.wiwCard}>
            <h2>What's it Worth?</h2>
            
            <div className={styles.section}>
              <h3>Focus?</h3>
              <p>{renderWiwTextWithReferenceLinks(result.card.focus, result.references, { linkClassName: styles.citationLink })}</p>
            </div>

            <div className={styles.section}>
              <h3>Next?</h3>
              <ul>
                {result.card.next_questions.map((q, idx) => (
                  <li key={idx}>{renderWiwTextWithReferenceLinks(q, result.references, { linkClassName: styles.citationLink })}</li>
                ))}
              </ul>
            </div>

            <div className={styles.section}>
              <h3>Contradiction?</h3>
              <p>{renderWiwTextWithReferenceLinks(result.card.conflicts, result.references, { linkClassName: styles.citationLink })}</p>
            </div>

            <div className={styles.section}>
              <h3>Gap?</h3>
              {Array.isArray(result.card.gaps) ? (
                <ul>
                  {result.card.gaps.map((gap, idx) => (
                    <li key={idx}>{renderWiwTextWithReferenceLinks(gap, result.references, { linkClassName: styles.citationLink })}</li>
                  ))}
                </ul>
              ) : (
                <p>{renderWiwTextWithReferenceLinks(result.card.gaps, result.references, { linkClassName: styles.citationLink })}</p>
              )}
            </div>
          </div>

          {/* 相关文献列表 */}
          <div className={styles.references}>
            <h2>相关文献 ({result.references.length}篇)</h2>
            {result.references.map((ref, idx) => (
              <div key={ref.pmid} className={styles.referenceItem}>
                <div className={styles.refHeader}>
                  <span className={styles.refIndex}>{idx + 1}</span>
                  <a
                    href={`https://pubmed.ncbi.nlm.nih.gov/${ref.pmid}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.refTitle}
                  >
                    {ref.title}
                  </a>
                </div>
                <div className={styles.refMeta}>
                  PMID: {ref.pmid}
                  {ref.doi && ` | DOI: ${ref.doi}`}
                </div>
              </div>
            ))}
          </div>

          {/* 顶刊相似文献 */}
          {result.top_journal_recommendations && result.top_journal_recommendations.length > 0 && (
            <div className={styles.inspiration}>
              <h2>顶刊相似文献</h2>
              {result.top_journal_recommendations.map((rec, idx) => (
                <div key={rec.pmid || idx} className={styles.inspirationItem}>
                  <h4>
                    {rec.pmid ? (
                      <a
                        href={`https://pubmed.ncbi.nlm.nih.gov/${rec.pmid}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {rec.title}
                      </a>
                    ) : rec.doi ? (
                      <a
                        href={`https://doi.org/${rec.doi}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {rec.title}
                      </a>
                    ) : (
                      rec.title
                    )}
                  </h4>
                  <p className={styles.journal}>{rec.journal}</p>
                  <p className={styles.meta}>
                    {rec.pmid && `PMID: ${rec.pmid}`}
                    {rec.pmid && rec.doi && ' | '}
                    {rec.doi && `DOI: ${rec.doi}`}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* 元数据 */}
          <div className={styles.meta}>
            <p>
              召回策略: {result.meta.recall_mode} |
              去重数量: {result.meta.dedup_count} |
              耗时: {result.meta.elapsed_ms}ms
            </p>
          </div>
        </div>
      )}

      <footer className={styles.quotaFooter}>
        {quotaHint}
      </footer>
    </div>
  );
};

export default ResearchGap;
