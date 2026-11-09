'use strict';
/**
 * A do-nothing stand-in for scratch-render, so the VM behaves as if a renderer
 * were attached (headless Node has no WebGL).
 *
 * Why: without a renderer, RenderedTarget.setXY / pen / looks blocks skip
 * `runtime.requestRedraw()` (e.g. scratch-vm src/sprites/rendered-target.js
 * setXY: the requestRedraw call is inside `if (this.renderer)`). In the real
 * GUI a visible sprite moving inside a non-warp loop sets redrawRequested,
 * which ends the sequencer's work loop for that frame (sequencer.stepThreads:
 * `(this.runtime.turboMode || !this.runtime.redrawRequested)`). Attaching this
 * stub reproduces that yield behaviour headlessly.
 *
 * Every method not listed returns undefined. `create*` methods return fresh
 * integer ids so pen/skin/drawable ids are >= 0 (pen checks `skinId >= 0`).
 * No fencing: getFencedPositionOfDrawable returns the requested position.
 */
function createStubRenderer () {
    let nextId = 1;
    const calls = Object.create(null);
    const impl = {
        getFencedPositionOfDrawable: (id, pos) => [pos[0], pos[1]],
        getSkinSize: () => [16, 16],
        getSkinRotationCenter: () => [8, 8],
        getCurrentSkinSize: () => [16, 16],
        getBounds: () => ({left: -8, right: 8, top: 8, bottom: -8}),
        getBoundsForBubble: () => ({left: -8, right: 8, top: 8, bottom: -8}),
        getNativeSize: () => [480, 360],
        isTouchingDrawables: () => false,
        isTouchingColor: () => false,
        pick: () => -1,
        setLayerGroupOrdering: () => {},
        on: () => {},
        off: () => {},
        removeListener: () => {},
        _stubCalls: calls
    };
    return new Proxy(impl, {
        get (target, prop) {
            if (prop in target) return target[prop];
            if (typeof prop !== 'string') return undefined;
            if (prop === 'then') return undefined; // not a thenable
            return function (...args) {
                calls[prop] = (calls[prop] || 0) + 1;
                if (prop.startsWith('create')) return nextId++;
                return undefined;
            };
        },
        set (target, prop, value) {
            target[prop] = value;
            return true;
        }
    });
}

module.exports = {createStubRenderer};
