const getInt = (props, name, fallback = 0) => {
    return parseInt(props.get(name)?.toString() || `${fallback}`, 10);
};
const getStr = (props, name, fallback = '') => {
    return props.get(name)?.toString().trim() || fallback;
};
const PIXEL_DOT_PROPS = ['--px-dot-color', '--px-block-size'];
export class PixelDot {
    static get inputProperties() {
        return PIXEL_DOT_PROPS;
    }
    paint(ctx, size, props) {
        const { width, height } = size;
        const dotColor = getStr(props, '--px-dot-color', '#ffffff');
        const blockSize = getInt(props, '--px-block-size', 2);
        // 清空画布
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = dotColor;
        ctx.fillRect(0, 0, width, height);
        ctx.clearRect(0, 0, blockSize, blockSize);
        ctx.clearRect(width - blockSize, 0, blockSize, blockSize);
        ctx.clearRect(0, height - blockSize, blockSize, blockSize);
        ctx.clearRect(width - blockSize, height - blockSize, blockSize, blockSize);
    }
}
export function registerPixelDot() {
    if (typeof registerPaint !== 'undefined') {
        registerPaint('pixeldot', PixelDot);
    }
}
registerPixelDot();
