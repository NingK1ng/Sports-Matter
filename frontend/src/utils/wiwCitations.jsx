export function buildReferenceUrl(ref) {
  if (!ref) return null
  const pmid = ref.pmid ? String(ref.pmid).trim() : ''
  if (pmid) return `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`
  const doi = ref.doi ? String(ref.doi).trim() : ''
  if (doi) return `https://doi.org/${doi}`
  const url = ref.url ? String(ref.url).trim() : ''
  if (url) return url
  return null
}

function normalizeDashChar(text) {
  const t = (text || '').trim()
  if (t === '—') return '—'
  if (t === '–') return '–'
  return '-'
}

function splitWithSeparators(text, separatorsRe) {
  if (!text) return []
  return text.split(separatorsRe).filter((p) => p !== '')
}

function isSeparatorToken(token) {
  return token === '、' || token === ',' || token === '，'
}

function makeRefLinkNode({
  label,
  url,
  key,
  className,
}) {
  if (!url) return label
  return (
    <a
      key={key}
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
    >
      {label}
    </a>
  )
}

function buildCitationGroupNodes({
  open,
  close,
  numbersText,
  references,
  matchIndex,
  linkClassName,
}) {
  const nodes = []
  const openToken = open || ''
  const closeToken = close || ''
  const raw = (numbersText || '').trim()

  const singleNumberMatch = raw.match(/^\d+$/)
  if (openToken && closeToken && singleNumberMatch) {
    const n = Number(raw)
    const ref = Array.isArray(references) ? references[n - 1] : null
    const url = buildReferenceUrl(ref)
    nodes.push(
      makeRefLinkNode({
        key: `wiw-ref-${matchIndex}-${n}`,
        label: `${openToken}文献${n}${closeToken}`,
        url,
        className: linkClassName,
      })
    )
    return nodes
  }

  if (openToken) nodes.push(openToken)

  const rangeMatch = raw.match(/^(\d+)\s*([-–—])\s*(\d+)$/)
  if (rangeMatch) {
    const start = Number(rangeMatch[1])
    const dash = normalizeDashChar(rangeMatch[2])
    const end = Number(rangeMatch[3])

    const startRef = Array.isArray(references) ? references[start - 1] : null
    const endRef = Array.isArray(references) ? references[end - 1] : null

    nodes.push(
      makeRefLinkNode({
        key: `wiw-ref-${matchIndex}-${start}`,
        label: `文献${start}`,
        url: buildReferenceUrl(startRef),
        className: linkClassName,
      })
    )
    nodes.push(dash)
    nodes.push(
      makeRefLinkNode({
        key: `wiw-ref-${matchIndex}-${end}`,
        label: `文献${end}`,
        url: buildReferenceUrl(endRef),
        className: linkClassName,
      })
    )
  } else {
    const parts = splitWithSeparators(raw, /([、,，])/)
    const hasAnySeparator = parts.some((p) => isSeparatorToken(p))
    if (!hasAnySeparator) {
      const n = Number(raw)
      const ref = Array.isArray(references) ? references[n - 1] : null
      nodes.push(
        makeRefLinkNode({
          key: `wiw-ref-${matchIndex}-${n}`,
          label: `文献${n}`,
          url: buildReferenceUrl(ref),
          className: linkClassName,
        })
      )
    } else {
      parts.forEach((part) => {
        const token = part.trim()
        if (!token) return
        if (isSeparatorToken(token)) {
          nodes.push(token)
          return
        }
        const n = Number(token)
        const ref = Array.isArray(references) ? references[n - 1] : null
        nodes.push(
          makeRefLinkNode({
            key: `wiw-ref-${matchIndex}-${n}`,
            label: `文献${n}`,
            url: buildReferenceUrl(ref),
            className: linkClassName,
          })
        )
      })
    }
  }

  if (closeToken) nodes.push(closeToken)
  return nodes
}

export function renderWiwTextWithReferenceLinks(text, references, options = {}) {
  if (!text) return text

  const linkClassName = options.linkClassName || ''

  const nodes = []
  const groupRe = /(\[|【)?文献\s*(\d+(?:\s*[、,，]\s*\d+)*(?:\s*[-–—]\s*\d+)?)(\]|】)?/g
  let lastIndex = 0
  let match

  while ((match = groupRe.exec(text)) !== null) {
    const start = match.index
    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start))
    }
    const open = match[1] || ''
    const numbersText = match[2] || ''
    const close = match[3] || ''

    nodes.push(
      ...buildCitationGroupNodes({
        open,
        close,
        numbersText,
        references,
        matchIndex: start,
        linkClassName,
      })
    )

    lastIndex = groupRe.lastIndex
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex))
  }

  return nodes
}

