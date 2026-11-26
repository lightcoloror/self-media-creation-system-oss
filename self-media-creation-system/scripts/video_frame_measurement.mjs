/**
 * Use inside the editor/renderer's hidden compositor, after each timeline seek
 * has settled (fonts, media and motion transforms). Mark the visible wrappers
 * for flower text, subtitles, evidence cards and animation with data-frame-layer.
 * Read descendants and text ranges before any canvas clip is applied.
 */
export function measureFrameBounds(canvasElement, canvas, timeSeconds) {
  const surface = canvasElement.getBoundingClientRect();
  const [width, height] = canvas;
  if (!(width > 0 && height > 0 && surface.width > 0 && surface.height > 0)) {
    throw new Error("Frame measurement requires a visible composition canvas");
  }
  const horizontal = width / surface.width;
  const vertical = height / surface.height;
  if (Math.abs(horizontal / vertical - 1) > 0.002) {
    throw new Error("The compositor is stretching the target canvas");
  }

  function visible(element) {
    for (let node = element; node && node !== canvasElement; node = node.parentElement) {
      const style = node.ownerDocument.defaultView.getComputedStyle(node);
      if (style.display === "none" || ["hidden", "collapse"].includes(style.visibility)
          || Number(style.opacity) === 0) return false;
    }
    return true;
  }

  const bounds = Object.create(null);
  for (const layer of canvasElement.querySelectorAll("[data-frame-layer]")) {
    const id = layer.dataset.frameLayer;
    if (!visible(layer)) continue;
    if (!id || Object.hasOwn(bounds, id)) throw new Error("Frame layer IDs must be unique");
    const rectangles = [];
    for (const element of [layer, ...layer.querySelectorAll("*")]) {
      if (!visible(element)) continue;
      rectangles.push(...element.getClientRects());
      for (const text of element.childNodes) {
        if (text.nodeType !== 3 || !text.textContent.trim()) continue;
        const range = element.ownerDocument.createRange();
        range.selectNodeContents(text);
        rectangles.push(...range.getClientRects());
      }
    }
    const drawn = rectangles.filter(rect => rect.width > 0 && rect.height > 0);
    if (!drawn.length) throw new Error("Visible layer has no measurable content: " + id);
    bounds[id] = [
      (Math.min(...drawn.map(rect => rect.left)) - surface.left) * horizontal,
      (Math.min(...drawn.map(rect => rect.top)) - surface.top) * vertical,
      (Math.max(...drawn.map(rect => rect.right)) - surface.left) * horizontal,
      (Math.max(...drawn.map(rect => rect.bottom)) - surface.top) * vertical,
    ];
  }
  return {time_seconds: timeSeconds, bounds};
}
