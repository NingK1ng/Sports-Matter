/**
 * 热点图谱气泡样式候选方案 - 基于像素美学
 * 可以替换当前的渐变色气泡
 */

const isGenericCommunityName = (t) => {
  const s = (t || '').toString().toLowerCase().trim()
  if (!s) return true
  return /\b(community|communities|other|unclustered|misc|miscellaneous|general|unknown)\b/.test(s)
}

const pickCommunityName = (comm) => {
  const label = (comm?.llm_label || '').toString().trim()
  if (label && !isGenericCommunityName(label)) return label

  const terms = Array.isArray(comm?.representative_terms) ? comm.representative_terms : []
  for (const t of terms) {
    const term = typeof t === 'string' ? t : (t?.term || '')
    const s = (term || '').toString().trim()
    if (!s) continue
    if (s.length < 3) continue
    if (isGenericCommunityName(s)) continue
    return s
  }

  const id = comm?.community_id ? String(comm.community_id) : ''
  return id ? `社区 ${id}` : '社区'
}

// 方案A: 像素方块风格（类似 Minecraft）
export const pixelBlockStyle = {
  itemStyle: {
    color: '#8b7355',
    borderColor: '#2d2d2d',
    borderWidth: 3,
    shadowBlur: 0,
    shadowColor: 'transparent'
  },
  // 使用 ECharts 的 symbol 自定义形状
  symbol: 'rect', // 方形
  symbolSize: 40
}

// 方案B: 8位像素圆（带硬边缘）
export const pixel8BitCircle = (size, colorIndex) => {
  const colors = [
    '#e76e55', // 红
    '#6b73ff', // 蓝
    '#38c172', // 绿
    '#f6993f', // 橙
    '#9561e2', // 紫
    '#4dc0b5', // 青
    '#f66d9b', // 粉
    '#ffed4e'  // 黄
  ]
  
  return {
    itemStyle: {
      color: colors[colorIndex % colors.length],
      borderColor: '#2d2d2d',
      borderWidth: 3,
      shadowBlur: 0
    },
    symbol: 'circle',
    symbolSize: size
  }
}

// 方案C: 像素钻石/菱形
export const pixelDiamond = {
  symbol: 'diamond',
  itemStyle: {
    color: '#e8d7b9',
    borderColor: '#8b7355',
    borderWidth: 3,
    shadowBlur: 0
  }
}

// 方案D: 像素星形
export const pixelStar = {
  symbol: 'star',
  itemStyle: {
    color: '#ffed4e',
    borderColor: '#8b7355',
    borderWidth: 3,
    shadowBlur: 0
  }
}

// 方案E: 像素正方形带角装饰
export const pixelSquareWithCorners = (size, color) => ({
  symbol: 'rect',
  symbolSize: size,
  itemStyle: {
    color: color || '#8b7355',
    borderColor: '#2d2d2d',
    borderWidth: 3,
    shadowBlur: 0
  }
})

// 方案F: 像素六边形（蜂巢风格）
export const pixelHexagon = {
  symbol: 'path://M0,10 L5,0 L15,0 L20,10 L15,20 L5,20 Z',
  itemStyle: {
    color: '#e8d7b9',
    borderColor: '#8b7355',
    borderWidth: 2,
    shadowBlur: 0
  }
}

// 方案G: 纯色方块阵列（最复古8-bit风格）
export const retro8BitPalette = [
  '#e76e55', // NES 红
  '#6b73ff', // NES 蓝
  '#38c172', // NES 绿
  '#f6993f', // NES 橙
  '#9561e2', // NES 紫
  '#4dc0b5', // NES 青
  '#f66d9b', // NES 粉
  '#ffed4e', // NES 黄
  '#8b7355', // 棕色
  '#2d2d2d'  // 深灰
]

export const applyRetro8BitStyle = (communitiesData) => {
  return communitiesData.map((comm, idx) => ({
    id: comm.community_id,
    name: pickCommunityName(comm),
    symbolSize: Math.sqrt(comm.size) * 12 + 30,
    value: comm.size,
    symbol: 'rect', // 方形
    itemStyle: {
      color: retro8BitPalette[idx % retro8BitPalette.length],
      borderColor: '#2d2d2d',
      borderWidth: 3,
      shadowBlur: 0,
      shadowColor: 'transparent'
    },
    label: {
      show: true,
      fontSize: 10,
      color: '#ffffff',
      fontFamily: 'BoutiqueBitmap, monospace',
      fontWeight: 'bold',
      textBorderColor: '#2d2d2d',
      textBorderWidth: 2
    },
    communityData: comm
  }))
}

// 方案H: 像素艺术图标（使用自定义SVG path）
export const pixelIconShapes = {
  document: 'path://M5,0 L15,0 L20,5 L20,20 L5,20 Z M15,0 L15,5 L20,5',
  chart: 'path://M0,20 L0,0 L5,0 L5,15 L10,10 L15,12 L20,5 L20,20 Z',
  star: 'path://M10,0 L12,8 L20,8 L14,13 L16,20 L10,15 L4,20 L6,13 L0,8 L8,8 Z',
  heart: 'path://M10,18 L2,10 Q0,8 0,6 Q0,0 5,0 Q8,0 10,3 Q12,0 15,0 Q20,0 20,6 Q20,8 18,10 Z'
}

// 应用像素图标样式
export const applyPixelIconStyle = (communitiesData) => {
  const shapes = Object.values(pixelIconShapes)
  
  return communitiesData.map((comm, idx) => ({
    id: comm.community_id,
    name: pickCommunityName(comm),
    symbolSize: Math.sqrt(comm.size) * 10 + 25,
    value: comm.size,
    symbol: shapes[idx % shapes.length],
    itemStyle: {
      color: retro8BitPalette[idx % retro8BitPalette.length],
      borderColor: '#2d2d2d',
      borderWidth: 2,
      shadowBlur: 0
    },
    label: {
      show: true,
      fontSize: 9,
      color: '#2d2d2d',
      fontFamily: 'BoutiqueBitmap, monospace',
      fontWeight: 'bold'
    },
    communityData: comm
  }))
}

// 方案B的完整实现：8位像素圆
export const apply8BitCircleStyle = (communitiesData) => {
  const colors = [
    '#e76e55', // 红
    '#6b73ff', // 蓝
    '#38c172', // 绿
    '#f6993f', // 橙
    '#9561e2', // 紫
    '#4dc0b5', // 青
    '#f66d9b', // 粉
    '#ffed4e'  // 黄
  ]
  
  return communitiesData.map((comm, idx) => {
    const size = Math.sqrt(comm.size) * 15 + 30
    const color = colors[idx % colors.length]
    
    return {
      id: comm.community_id,
      name: pickCommunityName(comm),
      symbolSize: size,
      value: comm.size,
      symbol: 'circle',
      itemStyle: {
        color: color,
        borderColor: '#2d2d2d',
        borderWidth: 3,
        shadowBlur: 0
      },
      emphasis: {
        itemStyle: {
          borderWidth: 5,
          borderColor: '#ffffff',
          shadowBlur: 0
        },
        label: {
          fontSize: 12,
          fontWeight: 'bold'
        }
      },
      label: {
        show: true,
        fontSize: 10,
        color: '#ffffff',
        fontFamily: 'BoutiqueBitmap, monospace',
        fontWeight: 'bold',
        textBorderColor: '#2d2d2d',
        textBorderWidth: 2,
        formatter: (params) => {
          const text = params.data.name || ''
          return text.length > 30 ? text.slice(0, 30) + '...' : text
        }
      },
      communityData: comm
    }
  })
}

// 推荐方案：简单纯色方块（最像素化）
export const recommendedPixelStyle = apply8BitCircleStyle
