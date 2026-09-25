let __px_hasRegistered = false;

export function registerHoudini() {
  if (__px_hasRegistered) return;
  if (typeof window === 'undefined') return;
  if (typeof CSS === 'undefined' || !('paintWorklet' in CSS)) {
    console.warn('[Pixel] CSS Houdini paintWorklet is not supported in this browser.');
    return;
  }
  const base = `${import.meta.env.BASE_URL || '/'}worklets/`;
  const modules = [
    'pixelboard.worklet.js',
    'pixelbox.worklet.js',
    'pixelboxOrnament.worklet.js',
    'pixelboxStamp.worklet.js',
    'pixelcontent.worklet.js',
    'pixelpanel.worklet.js',
    'pixelstripe.worklet.js',
    'pixelgridBasic.worklet.js',
    'pixelgridPreset1.worklet.js',
    'pixeldot.worklet.js',
  ];
  modules.forEach((name) => {
    try {
      // @ts-ignore - paintWorklet is experimental
      CSS.paintWorklet.addModule(base + name).catch((err) => {
        console.warn(`[Pixel] Failed to load worklet: ${name}`, err);
      });
    } catch (err) {
      console.warn(`[Pixel] Error registering worklet: ${name}`, err);
    }
  });
  __px_hasRegistered = true;
}
