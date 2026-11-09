#!/usr/bin/env node
'use strict';
/**
 * runner/run.js -- CLI around runner/harness.js
 *
 * Usage:
 *   node runner/run.js PROJECT.sb3 [options]
 *
 * Options:
 *   --engine scratch-vm|turbowarp   VM to use (default scratch-vm)
 *   --flag                          trigger the green flag (default)
 *   --broadcast NAME                trigger "when I receive NAME" instead
 *   --set NAME=VALUE                set a variable before running (repeatable;
 *                                   VALUE is parsed as JSON if possible, else string)
 *   --set-list NAME=JSON|@FILE      set a list from a JSON array or a JSON file
 *   --inputs FILE.json              run once per input: [{"vars":{..},"lists":{..}}, ...]
 *                                   (one VM, project loaded once)
 *   --until NAME=VALUE              stop when variable NAME == VALUE (else: until idle)
 *   --timeout MS                    per-run timeout (default 60000)
 *   --fps N                         frames per second (default 30, the GUI default)
 *   --fast                          step frames back-to-back instead of setInterval
 *   --turbo                         turbo mode
 *   --no-compiler                   turbowarp: disable the compiler
 *   --warp-timer                    turbowarp: enable compiler warpTimer
 *   --no-stub-renderer              do not attach the no-op renderer
 *   --glow [TARGET]                 record SCRIPT_GLOW_ON/OFF for TARGET (default Sprite1)
 *   --dump-lists all|none|A,B       which lists to include in the output (default all)
 *   --out FILE                      write JSON result to FILE (default stdout)
 *   --frame-times                   include per-frame timestamps in the output
 *
 * Output: JSON ({engine, engineInfo, loadMs, results:[...]}); each result has
 *   wallMs, frames, idle, timedOut, vars, lists, listLengths, (glow, glowSummary).
 *
 * Examples:
 *   node runner/run.js phase0/out/minimal.sb3
 *   node runner/run.js phase0/out/matmul.sb3 --engine turbowarp --broadcast warp --dump-lists none
 *   node runner/run.js m.sb3 --inputs inputs.json --until done=1 --fast
 */
const fs = require('fs');
const {Session} = require('./harness');

function parseValue (s) {
    try {
        return JSON.parse(s);
    } catch (e) {
        return s;
    }
}

function parseArgs (argv) {
    const a = {sets: [], setLists: [], engine: 'scratch-vm', trigger: 'flag', timeoutMs: 60000,
        fps: 30, stepping: 'interval', turbo: false, compiler: true, warpTimer: false,
        stubRenderer: true, glow: null, dumpLists: true, out: null, until: null, inputs: null,
        frameTimes: false};
    for (let i = 0; i < argv.length; i++) {
        const k = argv[i];
        const next = () => argv[++i];
        switch (k) {
        case '--engine': a.engine = next(); break;
        case '--flag': a.trigger = 'flag'; break;
        case '--broadcast': a.trigger = {broadcast: next()}; break;
        case '--set': a.sets.push(next()); break;
        case '--set-list': a.setLists.push(next()); break;
        case '--inputs': a.inputs = next(); break;
        case '--until': {
            const [n, v] = next().split('=');
            a.until = {var: n, equals: parseValue(v)};
            break;
        }
        case '--timeout': a.timeoutMs = Number(next()); break;
        case '--fps': a.fps = Number(next()); break;
        case '--fast': a.stepping = 'fast'; break;
        case '--turbo': a.turbo = true; break;
        case '--no-compiler': a.compiler = false; break;
        case '--warp-timer': a.warpTimer = true; break;
        case '--no-stub-renderer': a.stubRenderer = false; break;
        case '--glow':
            a.glow = (argv[i + 1] && !argv[i + 1].startsWith('--')) ? next() : 'Sprite1';
            break;
        case '--dump-lists': {
            const v = next();
            a.dumpLists = v === 'all' ? true : v === 'none' ? false : v.split(',');
            break;
        }
        case '--out': a.out = next(); break;
        case '--frame-times': a.frameTimes = true; break;
        case '-h': case '--help':
            process.stdout.write(fs.readFileSync(__filename, 'utf8').split('*/')[0]);
            process.exit(0);
            break;
        default:
            if (k.startsWith('--')) throw new Error(`unknown option ${k}`);
            a.project = k;
        }
    }
    if (!a.project) throw new Error('missing PROJECT.sb3 (see --help)');
    return a;
}

function splitEq (s) {
    const j = s.indexOf('=');
    return [s.slice(0, j), s.slice(j + 1)];
}

async function main () {
    const a = parseArgs(process.argv.slice(2));
    const s = await Session.create({
        sb3: a.project, engine: a.engine, fps: a.fps, stepping: a.stepping, turbo: a.turbo,
        compiler: a.compiler, warpTimer: a.warpTimer, stubRenderer: a.stubRenderer,
        editingTarget: a.glow, recordGlow: !!a.glow
    });
    let inputs = [{vars: {}, lists: {}}];
    for (const kv of a.sets) {
        const [n, v] = splitEq(kv);
        inputs[0].vars[n] = parseValue(v);
    }
    for (const kv of a.setLists) {
        const [n, v] = splitEq(kv);
        inputs[0].lists[n] = JSON.parse(v.startsWith('@') ? fs.readFileSync(v.slice(1), 'utf8') : v);
    }
    if (a.inputs) inputs = JSON.parse(fs.readFileSync(a.inputs, 'utf8'));
    const results = [];
    for (const inp of inputs) {
        for (const [n, v] of Object.entries(inp.vars || {})) s.setVar(n, v);
        for (const [n, v] of Object.entries(inp.lists || {})) s.setList(n, v);
        const r = await s.run({trigger: a.trigger, until: a.until, timeoutMs: a.timeoutMs,
            dumpLists: a.dumpLists});
        if (!a.frameTimes) delete r.frameTimes;
        results.push(r);
    }
    s.dispose();
    const out = JSON.stringify({engine: a.engine, engineInfo: s.info, loadMs: s.loadMs, results},
        null, 1);
    if (a.out) fs.writeFileSync(a.out, out);
    else process.stdout.write(out + '\n');
}

main().catch(e => {
    console.error(e.stack || String(e));
    process.exit(1);
});
