'use strict';
/**
 * runner/harness.js -- run Scratch 3 projects (.sb3) headlessly in Node on
 *   - "scratch-vm": the npm package scratch-vm@5.0.300 (interpreter only), or
 *   - "turbowarp":  TurboWarp's fork (github TurboWarp/scratch-vm, installed
 *                   under the npm alias "tw-vm"); its JS compiler is ON by default.
 *
 * JS API
 * ------
 *   const {Session} = require('./runner/harness');
 *   const s = await Session.create({
 *       sb3: 'phase0/out/x.sb3',      // path, Buffer, or project.json string/object
 *       engine: 'scratch-vm',         // or 'turbowarp'
 *       fps: 30,                      // frame rate; 30 = GUI default ("compatibility mode")
 *       stepping: 'interval',         // 'interval': setInterval(_step, 1000/fps) like the GUI
 *                                     // 'fast': back-to-back frames (same per-frame work budget)
 *       turbo: false,                 // turbo mode (ignore redraw requests)
 *       compiler: true,               // turbowarp only: enable the compiler
 *       warpTimer: false,             // turbowarp only: compiler warpTimer option
 *       stubRenderer: true,           // attach a no-op renderer so visual blocks request
 *                                     // redraws exactly as with a real renderer
 *       editingTarget: 'Sprite1',     // target whose scripts emit glow events (GUI: the
 *                                     // selected sprite). null = VM default.
 *       recordGlow: false,            // record SCRIPT_GLOW_ON/OFF with frame index + time
 *   });
 *   s.setVar('x', 3);  s.setList('A', [1, 2, 3]);       // by name (stage or sprite)
 *   const r = await s.run({
 *       trigger: 'flag',              // or {broadcast: 'go'} or null (just step)
 *       until: null,                  // or {var: 'done', equals: 1}: stop when it holds
 *       timeoutMs: 60000,
 *       settleFrames: 2,              // extra frames after idle (to catch final glow-offs)
 *       dumpLists: true,              // true | false | ['C', ...]
 *   });
 *   // r = {engine, wallMs, frames, idle, timedOut, compileErrors (turbowarp),
 *   //      glow: [...], glowSummary: {...},
 *   //      scripts: {topBlockId: label}, vars: {name: value}, lists: {name: [...]},
 *   //      listLengths: {name: n}, frameTimes: [ms since trigger at end of each frame]}
 *   const buf = await s.saveSb3();   // vm.saveProjectSb3 -> Buffer
 *   const json = s.toJSON();         // vm.toJSON() string
 *   s.dispose();
 *
 *   Many inputs in one process: create the Session once, then for each input
 *   call setVar/setList and run() again (the project is not reloaded).
 *
 * Wall time is measured from the trigger to the end of the frame in which the
 * stop condition (idle / `until`) was observed, using performance.now().
 *
 * CLI: see runner/run.js (`node runner/run.js --help`).
 */
const fs = require('fs');
const path = require('path');
const {performance} = require('perf_hooks');
const {createStubRenderer} = require('./stub-renderer');

const ENGINE_MODULES = {
    'scratch-vm': 'scratch-vm',
    'turbowarp': 'tw-vm'
};

function engineInfo (engine) {
    const dir = path.join(__dirname, 'node_modules', ENGINE_MODULES[engine]);
    const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
    const info = {engine, module: ENGINE_MODULES[engine], version: pkg.version};
    if (pkg._resolved) info.resolved = pkg._resolved;
    // npm records the git commit for git dependencies in the lockfile
    try {
        const lock = JSON.parse(fs.readFileSync(path.join(__dirname, 'package-lock.json'), 'utf8'));
        const ent = lock.packages && lock.packages[`node_modules/${ENGINE_MODULES[engine]}`];
        if (ent && ent.resolved) info.resolved = ent.resolved;
    } catch (e) { /* no lockfile */ }
    return info;
}

function loadEngine (engine) {
    const mod = ENGINE_MODULES[engine];
    if (!mod) throw new Error(`unknown engine ${engine}; use one of ${Object.keys(ENGINE_MODULES)}`);
    return require(mod);
}

/** Silence the VM's console logging while running `fn` (it is very chatty). */
async function quietly (fn, quiet) {
    if (!quiet) return fn();
    const saved = {log: console.log, warn: console.warn, info: console.info, debug: console.debug};
    console.log = console.warn = console.info = console.debug = () => {};
    try {
        return await fn();
    } finally {
        Object.assign(console, saved);
    }
}

function toBuffer (sb3) {
    if (Buffer.isBuffer(sb3)) return sb3;
    if (typeof sb3 === 'object') return JSON.stringify(sb3);
    if (typeof sb3 === 'string' && sb3.trim().startsWith('{')) return sb3;
    return fs.readFileSync(sb3);
}

class Session {
    static async create (opts = {}) {
        const o = Object.assign({
            engine: 'scratch-vm', fps: 30, stepping: 'interval', turbo: false,
            compiler: true, warpTimer: false, stubRenderer: true, editingTarget: null,
            recordGlow: false, quiet: true
        }, opts);
        const VM = loadEngine(o.engine);
        const ScratchStorage = require('scratch-storage').ScratchStorage;
        const vm = new VM();
        vm.attachStorage(new ScratchStorage());
        if (o.stubRenderer) {
            // TurboWarp's runtime._step reads `document.hidden` when a renderer is
            // attached (tw-vm src/engine/runtime.js, "do not draw if document is hidden").
            if (o.engine === 'turbowarp' && typeof globalThis.document === 'undefined') {
                globalThis.document = {hidden: false};
            }
            vm.attachRenderer(createStubRenderer());
        }
        if (o.engine === 'turbowarp') {
            vm.setCompilerOptions({enabled: !!o.compiler, warpTimer: !!o.warpTimer});
            vm.setFramerate(o.fps);
        } else {
            if (o.fps !== 30 && o.fps !== 60) throw new Error('scratch-vm supports fps 30 or 60');
            vm.setCompatibilityMode(o.fps === 30);
        }
        vm.setTurboMode(!!o.turbo);
        const t0 = performance.now();
        await quietly(() => vm.loadProject(toBuffer(o.sb3)), o.quiet);
        const s = new Session(vm, o);
        s.loadMs = performance.now() - t0;
        if (o.editingTarget) s.setEditingTarget(o.editingTarget);
        return s;
    }

    constructor (vm, opts) {
        this.vm = vm;
        this.rt = vm.runtime;
        this.opts = opts;
        this.engine = opts.engine;
        this.info = engineInfo(opts.engine);
        this.frame = 0;
        this.glow = [];
        this._t0 = 0;
        this._recording = false;
        this._frameTimes = [];
        // Count frames by wrapping _step (both engines' frame loops call runtime._step()).
        const rt = this.rt;
        const origStep = rt._step.bind(rt);
        rt._step = () => {
            this.frame++;
            origStep();
            if (this._recording) this._frameTimes.push(performance.now() - this._t0);
        };
        const onGlow = type => ev => {
            if (!this._recording || !this.opts.recordGlow) return;
            this.glow.push({type, id: ev.id, frame: this.frame - this._frame0,
                t: performance.now() - this._t0});
        };
        // TurboWarp: scripts the compiler rejects silently fall back to the interpreter.
        this.compileErrors = [];
        rt.on('COMPILE_ERROR', (target, error) => {
            this.compileErrors.push({target: target && target.getName(), error: String(error)});
        });
        rt.on('SCRIPT_GLOW_ON', onGlow('on'));
        rt.on('SCRIPT_GLOW_OFF', onGlow('off'));
    }

    target (name) {
        const t = this.rt.targets.find(x => x.isOriginal && (x.getName() === name ||
            (name === 'Stage' && x.isStage)));
        if (!t) throw new Error(`no target named ${name}`);
        return t;
    }

    setEditingTarget (name) {
        this.vm.setEditingTarget(this.target(name).id);
    }

    _lookup (name, type) {
        // stage first, then sprites (sb3lib forbids clashing names)
        const ts = this.rt.targets.filter(t => t.isOriginal).sort((a, b) => b.isStage - a.isStage);
        for (const t of ts) {
            for (const id in t.variables) {
                const v = t.variables[id];
                if (v.name === name && v.type === type) return v;
            }
        }
        throw new Error(`no ${type || 'scalar'} variable named ${name}`);
    }

    getVar (name) { return this._lookup(name, '').value; }
    setVar (name, value) { this._lookup(name, '').value = value; }
    getList (name) { return this._lookup(name, 'list').value; }
    setList (name, items) {
        const L = this._lookup(name, 'list');
        L.value = Array.from(items);
        L._monitorUpToDate = false;
    }

    dumpVars () {
        const vars = {};
        const lists = {};
        for (const t of this.rt.targets.filter(x => x.isOriginal)) {
            for (const id in t.variables) {
                const v = t.variables[id];
                const key = (v.name in vars || v.name in lists) ? `${t.getName()}/${v.name}` : v.name;
                if (v.type === '') vars[key] = v.value;
                else if (v.type === 'list') lists[key] = v.value;
            }
        }
        return {vars, lists};
    }

    /** label for each top-level script on a target: flag | recv:NAME | define:PROCCODE | opcode */
    scriptLabels (targetName) {
        const t = targetName ? this.target(targetName) : this.vm.editingTarget;
        const out = {};
        const blocks = t.blocks._blocks;
        for (const id of t.blocks.getScripts()) {
            const b = blocks[id];
            let label = b.opcode;
            if (b.opcode === 'event_whenflagclicked') label = 'flag';
            else if (b.opcode === 'event_whenbroadcastreceived') label = `recv:${b.fields.BROADCAST_OPTION.value}`;
            else if (b.opcode === 'procedures_definition') {
                const proto = blocks[b.inputs.custom_block.block];
                label = `define:${proto.mutation.proccode}`;
            }
            out[id] = label;
        }
        return out;
    }

    _activeThreads () {
        return this.rt.threads.filter(t => !t.updateMonitor && !t.isKilled).length;
    }

    _trigger (trigger) {
        if (!trigger) return;
        if (trigger === 'flag') {
            this.vm.greenFlag();
        } else if (trigger.broadcast) {
            this.rt.startHats('event_whenbroadcastreceived', {BROADCAST_OPTION: trigger.broadcast});
        } else {
            throw new Error(`bad trigger ${JSON.stringify(trigger)}`);
        }
    }

    /**
     * Trigger and step until idle (or `until` holds) or timeout.
     */
    async run (ro = {}) {
        const o = Object.assign({trigger: 'flag', until: null, timeoutMs: 60000, settleFrames: 2,
            dumpLists: true}, ro);
        const fps = this.opts.fps;
        const rt = this.rt;
        rt.currentStepTime = 1000 / fps; // what runtime.start()/frameLoop.start() set
        this.glow = [];
        this._frameTimes = [];
        this._frame0 = this.frame;
        const labels = this.opts.recordGlow ? this.scriptLabels() : {};
        const check = () => {
            if (o.until) {
                // eslint-disable-next-line eqeqeq
                return this.getVar(o.until.var) == o.until.equals;
            }
            return this._activeThreads() === 0;
        };

        this._recording = true;
        this._t0 = performance.now();
        this._trigger(o.trigger);
        const result = await new Promise(resolve => {
            let doneAt = null;
            let settle = 0;
            let timer = null;
            let stopped = false;
            const finish = timedOut => {
                if (stopped) return;
                stopped = true;
                if (timer) clearInterval(timer);
                resolve({timedOut, doneAt});
            };
            const afterFrame = () => {
                if (doneAt === null && check()) {
                    doneAt = {wallMs: performance.now() - this._t0, frames: this.frame - this._frame0};
                }
                if (doneAt !== null) {
                    if (settle >= o.settleFrames) return finish(false);
                    settle++;
                }
                if (performance.now() - this._t0 > o.timeoutMs) return finish(true);
            };
            if (this.opts.stepping === 'interval') {
                timer = setInterval(() => {
                    rt._step();
                    afterFrame();
                }, 1000 / fps);
            } else {
                const loop = () => {
                    if (stopped) return;
                    rt._step();
                    afterFrame();
                    if (!stopped) setImmediate(loop);
                };
                setImmediate(loop);
            }
        });
        this._recording = false;
        if (result.timedOut) rt.stopAll();
        const {vars, lists} = this.dumpVars();
        const listLengths = {};
        for (const k in lists) listLengths[k] = lists[k].length;
        let outLists = {};
        if (o.dumpLists === true) outLists = lists;
        else if (Array.isArray(o.dumpLists)) for (const k of o.dumpLists) outLists[k] = lists[k];
        const out = {
            engine: this.engine,
            wallMs: result.doneAt ? result.doneAt.wallMs : performance.now() - this._t0,
            frames: result.doneAt ? result.doneAt.frames : this.frame - this._frame0,
            idle: this._activeThreads() === 0,
            timedOut: result.timedOut,
            compileErrors: this.compileErrors.slice(),
            vars, lists: outLists, listLengths,
            frameTimes: this._frameTimes.slice()
        };
        if (this.opts.recordGlow) {
            out.glow = this.glow.slice();
            out.scripts = labels;
            out.glowSummary = summarizeGlow(this.glow, labels);
        }
        return out;
    }

    toJSON () { return this.vm.toJSON(); }

    async saveSb3 () {
        const out = await this.vm.saveProjectSb3(this.engine === 'turbowarp' ? 'nodebuffer' : undefined);
        if (Buffer.isBuffer(out)) return out;
        if (out && typeof out.arrayBuffer === 'function') return Buffer.from(await out.arrayBuffer());
        return Buffer.from(out);
    }

    dispose () {
        this.rt.stopAll();
        if (this.vm.quit) this.vm.quit();
    }
}

/** Per script: list of glow intervals {onFrame, offFrame, frames, ms}. */
function summarizeGlow (events, labels) {
    const open = {};
    const out = {};
    for (const e of events) {
        const label = labels[e.id] || e.id;
        out[label] = out[label] || [];
        if (e.type === 'on') open[e.id] = e;
        else if (open[e.id]) {
            const on = open[e.id];
            out[label].push({onFrame: on.frame, offFrame: e.frame, frames: e.frame - on.frame,
                ms: +(e.t - on.t).toFixed(2)});
            delete open[e.id];
        }
    }
    for (const id in open) {
        const label = labels[id] || id;
        out[label].push({onFrame: open[id].frame, offFrame: null, frames: null, ms: null});
    }
    return out;
}

module.exports = {Session, engineInfo, summarizeGlow, ENGINE_MODULES};
