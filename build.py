import os
import sys
import json
import base64
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANSWERS_FILE = os.path.join(BASE_DIR, "wordle-valid-answers.txt")
GUESSES_FILE = os.path.join(BASE_DIR, "wordle-valid-guesses.txt")
OUTPUT_HTML = os.path.join(BASE_DIR, "wordle-solver.html")
# Build with: cargo build --release --target wasm32-unknown-unknown  (in wasm-solver/)
WASM_FILE = os.path.join(BASE_DIR, "wasm-solver", "target", "wasm32-unknown-unknown", "release", "wasm_solver.wasm")
# Threads build (shared memory): run wasm-solver/build-shared.sh
SHARED_WASM_FILE = os.path.join(BASE_DIR, "wasm-solver", "target-shared", "wasm32-unknown-unknown", "release", "wasm_solver.wasm")

# 1. Read text files
def read_word_lists():
    try:
        with open(ANSWERS_FILE, "r", encoding="utf-8") as f:
            answers_str = " ".join(f.read().upper().split())
            
        with open(GUESSES_FILE, "r", encoding="utf-8") as f:
            guesses_str = " ".join(f.read().upper().split())
            
        return answers_str, guesses_str
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure 'wordle-valid-answers.txt' and 'wordle-valid-guesses.txt' are in this directory.")
        sys.exit(1)

# 2. The HTML Template
html_template = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wordle Solver</title>
    <style>
        :root {
            --bg-color: #121213;
            --text-color: #ffffff;
            --gray: #3a3a3c;
            --yellow: #b59f3b;
            --green: #538d4e;
            --blue: #2d68c4;
            --red: #c93b3b;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1rem;
            margin: 0;
            box-sizing: border-box;
        }
        h1 { margin-bottom: 0.5rem; text-align: center; }
        p.subtitle { color: #818384; margin-bottom: 1.25rem; text-align: center; max-width: 600px; font-size: 0.95rem; }
        
        /* Database & Status Bar */
        .db-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
            max-width: 900px;
            margin-bottom: 1.5rem;
            background: #1e1e1e;
            padding: 0.75rem 1.25rem;
            border-radius: 8px;
            box-sizing: border-box;
            gap: 1rem;
            flex-wrap: wrap;
            border: 1px solid #2a2a2c;
        }
        .db-stats {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            font-size: 0.95rem;
            flex-wrap: wrap;
        }
        .badge-custom {
            background-color: var(--green);
            color: #fff;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: bold;
        }
        .badge-mode {
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: bold;
            letter-spacing: 0.5px;
        }
        .badge-mode-normal {
            background-color: #2a2a2c;
            color: #a0a0a0;
            border: 1px solid var(--gray);
        }
        .badge-mode-backup {
            background-color: var(--yellow);
            color: #121213;
            animation: pulse-glow 1.5s infinite alternate;
        }
        @keyframes pulse-glow {
            0% { filter: drop-shadow(0 0 2px var(--yellow)); opacity: 0.9; }
            100% { filter: drop-shadow(0 0 7px var(--yellow)); opacity: 1; }
        }
        .db-actions {
            display: flex;
            gap: 0.5rem;
        }
        .btn-tool {
            background: #2a2a2c;
            color: #ddd;
            border: 1px solid var(--gray);
            padding: 6px 12px;
            font-size: 0.85rem;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            transition: 0.2s;
        }
        .btn-tool:hover {
            background: #3a3a3c;
            color: #fff;
        }

        /* Database Panel (Collapsible) */
        .db-panel {
            width: 100%;
            max-width: 900px;
            background: #1b1b1d;
            border: 1px solid var(--gray);
            border-radius: 8px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
            box-sizing: border-box;
        }
        .db-panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--gray);
            padding-bottom: 0.5rem;
            margin-bottom: 0.75rem;
        }
        .db-panel-header h3 {
            margin: 0;
            font-size: 1.1rem;
        }
        .btn-close {
            background: transparent;
            border: none;
            color: #888;
            font-size: 1.3rem;
            cursor: pointer;
            padding: 0 4px;
            line-height: 1;
        }
        .btn-close:hover { color: #fff; }
        .db-description {
            color: #a8a8a8;
            font-size: 0.85rem;
            margin: 0 0 1rem 0;
            line-height: 1.4;
        }
        .db-add-row {
            display: flex;
            gap: 0.5rem;
            align-items: center;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }
        .db-add-row input[type="text"] {
            background: #121213;
            border: 1px solid var(--gray);
            color: white;
            font-size: 1.1rem;
            text-transform: uppercase;
            text-align: center;
            width: 150px;
            padding: 0.4rem;
            letter-spacing: 0.2rem;
            border-radius: 4px;
        }
        .custom-words-container {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            max-height: 140px;
            overflow-y: auto;
            margin-bottom: 1rem;
            padding: 0.6rem;
            background: #121213;
            border-radius: 4px;
            border: 1px solid #2a2a2c;
        }
        .custom-word-chip {
            background: #2a2a2c;
            border: 1px solid var(--gray);
            border-radius: 4px;
            padding: 3px 8px;
            font-family: monospace;
            font-size: 0.95rem;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .custom-word-chip button {
            background: transparent;
            border: none;
            color: #ff6b6b;
            cursor: pointer;
            font-size: 1rem;
            padding: 0;
            line-height: 1;
        }
        .custom-word-chip button:hover {
            color: #ff3333;
        }

        /* Layout */
        .layout-container {
            display: flex; gap: 2rem; width: 100%; max-width: 900px;
            align-items: flex-start; justify-content: center;
        }
        
        .main-panel {
            flex: 2; display: flex; flex-direction: column;
            align-items: center; width: 100%; max-width: 600px;
        }

        .history-panel {
            flex: 1; background: #1e1e1e; padding: 1.5rem; border-radius: 8px;
            width: 100%; min-width: 250px; min-height: 200px; box-sizing: border-box;
        }
        
        .history-panel h2 {
            margin-top: 0; font-size: 1.2rem; border-bottom: 1px solid var(--gray);
            padding-bottom: 0.5rem; margin-bottom: 1rem;
        }

        .history-list { display: flex; flex-direction: column; gap: 0.8rem; }
        .history-item { display: flex; gap: 0.3rem; justify-content: center; }
        
        .history-tile {
            width: 35px; height: 35px; display: flex; justify-content: center; align-items: center;
            font-size: 1.2rem; font-weight: bold; text-transform: uppercase;
            border-radius: 4px; color: white;
        }

        /* Solved & Backup Banners */
        .banner {
            width: 100%;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin-bottom: 1.25rem;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        .solved-banner {
            border: 2px solid var(--green);
            background: rgba(83, 141, 78, 0.2);
        }
        .solved-banner.not-in-answers {
            border-color: var(--yellow);
            background: rgba(181, 159, 59, 0.2);
        }
        .banner-content {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            text-align: left;
        }
        .banner-title {
            font-size: 1.15rem;
            font-weight: bold;
        }
        .banner-subtitle {
            font-size: 0.85rem;
            color: #b0b0b0;
        }
        .highlight-word {
            color: #5cf55a;
            font-family: monospace;
            font-size: 1.35rem;
            letter-spacing: 2px;
        }
        .not-in-answers .highlight-word {
            color: #ffd93d;
        }
        .btn-add-word-action {
            background-color: var(--green);
            color: white;
            border: none;
            padding: 10px 18px;
            font-size: 1rem;
            font-weight: bold;
            border-radius: 4px;
            cursor: pointer;
            white-space: nowrap;
            transition: 0.2s;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }
        .btn-add-word-action:hover {
            filter: brightness(1.2);
            transform: translateY(-1px);
        }
        .backup-banner {
            background: rgba(181, 159, 59, 0.15);
            border-left: 4px solid var(--yellow);
            border-radius: 4px;
            padding: 0.85rem 1rem;
            margin-bottom: 1.25rem;
            font-size: 0.95rem;
            line-height: 1.4;
            color: #f0f0f0;
            text-align: left;
            width: 100%;
            box-sizing: border-box;
        }

        .input-section {
            display: flex; flex-direction: column; align-items: center; gap: 1rem;
            margin-bottom: 2rem; width: 100%;
        }
        
        input[type="text"] {
            background: transparent; border: 2px solid var(--gray); color: white;
            font-size: 2rem; text-transform: uppercase; text-align: center;
            width: 250px; padding: 0.5rem; border-radius: 4px; letter-spacing: 0.5rem;
        }
        
        .tiles { display: flex; gap: 0.5rem; }
        
        .tile {
            width: 60px; height: 60px; display: flex; justify-content: center; align-items: center;
            font-size: 2rem; font-weight: bold; text-transform: uppercase;
            background-color: var(--gray); cursor: pointer; user-select: none; border-radius: 4px;
        }
        
        .button-group { display: flex; gap: 1rem; margin-top: 1rem; }

        button {
            border: none; padding: 10px 20px; font-size: 1.2rem;
            border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s;
        }
        
        .btn-submit { background-color: var(--green); color: white; }
        .btn-reset { background-color: var(--gray); color: white; }
        
        button:disabled { background-color: #2a2a2c; color: #555; cursor: not-allowed; }
        button:hover:not(:disabled) { filter: brightness(1.1); }
        
        .results-section { width: 100%; background: #1e1e1e; padding: 1.5rem; border-radius: 8px; box-sizing: border-box; }
        
        .results-header {
            display: flex; justify-content: space-between; border-bottom: 1px solid var(--gray);
            padding-bottom: 0.5rem; margin-bottom: 1rem; font-size: 0.9rem; flex-wrap: wrap; gap: 0.5rem;
        }
        
        #word-list { display: flex; flex-direction: column; gap: 0.5rem; }
        
        .word-row {
            display: flex; justify-content: space-between; align-items: center; background: #2a2a2c;
            padding: 10px 15px; border-radius: 4px; font-family: monospace; font-size: 1.1rem;
            cursor: pointer; transition: background 0.15s;
        }
        .word-row:hover { background: #353538; }

        .word-left { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
        .score-box { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; min-width: 120px; }
        .score-avg { color: #4af626; font-size: 0.95rem; white-space: nowrap; }
        .score-tail { color: #a8a8a8; font-size: 0.75rem; white-space: nowrap; }
        .dist-bar { display: flex; width: 120px; height: 6px; border-radius: 3px; overflow: hidden; background: #1a1a1b; }
        .dist-bar span { display: block; height: 100%; }
        .word-row.optimal-row { border: 1px solid var(--green); background: rgba(83, 141, 78, 0.18); }
        .word-row.optimal-row:hover { background: rgba(83, 141, 78, 0.3); }
        .candidate-tag-optimal { color: #ffffff; background: var(--green); font-weight: bold; }

        .candidate-tag {
            font-size: 0.75rem;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            font-weight: normal;
        }
        .candidate-tag-normal {
            color: #a8a8a8;
        }
        .candidate-tag-backup {
            color: #ffd93d;
            background: rgba(181, 159, 59, 0.25);
            border: 1px solid rgba(181, 159, 59, 0.4);
            font-weight: bold;
        }
        .btn-sm-add {
            background-color: var(--green);
            color: white;
            border: none;
            padding: 3px 8px;
            font-size: 0.75rem;
            border-radius: 3px;
            cursor: pointer;
            font-weight: bold;
            margin-left: 6px;
            transition: 0.15s;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .btn-sm-add:hover { filter: brightness(1.2); }
        
        @media (max-width: 768px) {
            .layout-container { flex-direction: column; align-items: center; }
            .history-panel { width: 100%; max-width: 600px; }
            .db-bar { flex-direction: column; align-items: flex-start; }
            .banner { flex-direction: column; align-items: flex-start; }
        }
    </style>
</head>
<body>

    <h1>Wordle Solver</h1>
    <p class="subtitle">Exact search over every allowed guess: finds the guesses that minimise the average number of guesses to solve, with the full guess-count distribution of each.</p>

    <!-- Top Database & Status Bar -->
    <div class="db-bar">
        <div class="db-stats">
            <span>📖 Valid Answers: <strong id="total-answers-count">--</strong></span>
            <span id="custom-badge" class="badge-custom" style="display:none;">+<span id="custom-answers-count">0</span> custom</span>
            <span id="pool-mode-badge" class="badge-mode badge-mode-normal">Standard Pool</span>
        </div>
        <div class="db-actions">
            <button type="button" class="btn-tool" onclick="toggleDbPanel()">⚙️ Manage Database</button>
            <button type="button" class="btn-tool" onclick="saveOrDownloadAnswers()" title="Save or download updated wordle-valid-answers.txt">💾 Export TXT</button>
        </div>
    </div>

    <!-- Collapsible Database Panel -->
    <div id="db-panel" class="db-panel" style="display:none;">
        <div class="db-panel-header">
            <h3>Valid Answers Database</h3>
            <button class="btn-close" onclick="toggleDbPanel()">×</button>
        </div>
        <p class="db-description">
            Valid answers are preserved in this browser's local database. Any words added during solving are saved permanently across sessions. You can also export or download the updated <code>wordle-valid-answers.txt</code> anytime.
        </p>
        <div class="db-add-row">
            <input type="text" id="manual-word-input" maxlength="5" placeholder="WORD">
            <button class="btn-submit" style="padding: 7px 14px; font-size: 0.95rem;" onclick="addManualWord()">Add Answer</button>
            <input type="file" id="file-import-input" accept=".txt" style="display:none;" onchange="importAnswersFile(event)">
            <button class="btn-reset" style="padding: 7px 14px; font-size: 0.95rem;" onclick="document.getElementById('file-import-input').click()">Import .txt</button>
            <button class="btn-tool" style="padding: 7px 14px; font-size: 0.95rem;" onclick="saveOrDownloadAnswers()">Download .txt</button>
        </div>
        <div style="font-size: 0.85rem; color: #888; margin-bottom: 0.4rem;">Custom Added Words (<span id="custom-count-panel">0</span>):</div>
        <div id="custom-words-list" class="custom-words-container">
            <em style="color:#666; font-size:0.85rem; padding: 4px;">No custom words added yet.</em>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem; flex-wrap: wrap; gap: 0.5rem;">
            <button class="btn-reset" style="font-size:0.85rem; padding: 4px 10px;" onclick="clearCustomAnswers()">Clear Custom Words</button>
            <span id="db-feedback" style="color: #4af626; font-size:0.85rem;"></span>
        </div>
    </div>

    <div class="layout-container">
        <div class="main-panel">
            <!-- Solved / Word Found Banner -->
            <div id="solved-banner" class="banner solved-banner" style="display: none;"></div>

            <!-- Backup Mode Notice -->
            <div id="backup-banner" class="backup-banner" style="display: none;"></div>

            <div class="input-section">
                <input type="text" id="word-input" maxlength="5" placeholder="GUESS">
                
                <div class="tiles" id="tiles">
                    <div class="tile" data-state="0"></div>
                    <div class="tile" data-state="0"></div>
                    <div class="tile" data-state="0"></div>
                    <div class="tile" data-state="0"></div>
                    <div class="tile" data-state="0"></div>
                </div>
                
                <div class="button-group">
                    <button class="btn-reset" onclick="resetGame()">Reset</button>
                    <button class="btn-submit" id="submit-btn" onclick="processUserInput()">Apply</button>
                </div>
            </div>

            <div class="results-section">
                <div class="results-header">
                    <strong id="count">Possible answers left: --</strong>
                    <span id="status">Exact search</span>
                </div>
                <div id="word-list"></div>
            </div>
        </div>
        
        <div class="history-panel">
            <h2>Guess History</h2>
            <div class="history-list" id="history-list"></div>
        </div>
    </div>

    <script type="text/plain" id="exact-worker-src">
        // Exact solver (Web Worker). Cost of a strategy = total guesses summed over every
        // remaining answer (so avg = total / n). Depth-first search with alpha-beta style
        // cutoffs: each call only has to decide whether it can beat `beta`, and gives up as
        // soon as a lower bound proves it can't. A transposition table holds exact values and
        // proven lower bounds. Same algorithm as research/solver-bench.
        // getPatternCode() is prepended from the page script when the worker is created.
        const SOLVED = 242;
        let n, ng, pat, patT, targetGuess, zobA, zobB, memo, all, ranked;
        let seen = new Int32Array(243), stamp = 0;
        let masks, groupCount;

        // Lower bound on total guesses for any k-answer set (exact for k <= 2): guess a member,
        // the other k-1 land in at most 242 groups, each group of size s needing >= 2s-1 more.
        function lb(k) { return k === 0 ? 0 : 3 * k - 2 - Math.min(k - 1, 242); }

        function key(set) {
            let a = 0, b = 0;
            for (const i of set) { a ^= zobA[i]; b ^= zobB[i]; }
            return (a >>> 0) + (b & 0x1fffff) * 4294967296;
        }

        function partition(set, g) {
            const groups = new Map();
            const base = g * n;
            for (const i of set) {
                const p = pat[base + i];
                let grp = groups.get(p);
                if (!grp) groups.set(p, grp = []);
                grp.push(i);
            }
            return groups;
        }

        // Every guess that splits `set`, as bound * 65536 + guess, sorted by bound
        // (bound = k + sum of lb(group) over the groups it leaves).
        function rankedGuesses(set) {
            const counts = new Int32Array(243), touched = [];
            const out = [];
            for (let g = 0; g < ng; g++) {
                const base = g * n;
                for (const i of set) {
                    const p = pat[base + i];
                    if (counts[p]++ === 0) touched.push(p);
                }
                if (touched.length > 1 || touched[0] === SOLVED) {
                    let bound = set.length;
                    for (const p of touched) if (p !== SOLVED) bound += lb(counts[p]);
                    out.push(bound * 65536 + g);
                }
                for (const p of touched) counts[p] = 0;
                touched.length = 0;
            }
            return Float64Array.from(out).sort();
        }

        // One-ply lower bound: min over guesses of k + sum lb(group). With lb(s) = 2s-1 this is
        // 3k - max(#groups + [guess is in set]), so it only needs distinct-pattern counts.
        function ply1(set) {
            const k = set.length;
            if (k > 243) {
                const r = rankedGuesses(set);
                return r.length ? Math.floor(r[0] / 65536) : lb(k);
            }
            if (k >= 16) return 3 * k - maxGroupsTransposed(set);
            if (stamp > 2e9) { seen.fill(0); stamp = 0; }
            let best = 0;
            for (let g = 0; g < ng; g++) {
                const base = g * n, s = ++stamp;
                let groups = 0, solved = 0;
                for (const i of set) {
                    const p = pat[base + i];
                    if (seen[p] !== s) { seen[p] = s; groups++; }
                    if (p === SOLVED) solved = 1;
                }
                if (groups > 1 || solved) {
                    if (groups + solved > best) best = groups + solved;
                    if (best > k) break; // a member that isolates everything: can't do better
                }
            }
            return 3 * k - Math.max(best, 1);
        }

        // max over guesses of (#groups + [guess is in set]) using the answer-major table:
        // one sequential pass over each answer's row with a 243-bit "seen" mask per guess.
        function maxGroupsTransposed(set) {
            masks.fill(0);
            groupCount.fill(0);
            for (const a of set) {
                const base = a * ng;
                for (let g = 0; g < ng; g++) {
                    const p = patT[base + g];
                    const idx = (g << 3) | (p >>> 5), bit = 1 << (p & 31);
                    if ((masks[idx] & bit) === 0) { masks[idx] |= bit; groupCount[g]++; }
                }
            }
            for (const a of set) groupCount[targetGuess[a]]++; // a member also solves itself
            let best = 1;
            for (let g = 0; g < ng; g++) if (groupCount[g] > best) best = groupCount[g];
            return best;
        }

        // Best known lower bound for `set` (memoised).
        function bound(set) {
            const k = set.length;
            if (k <= 2) return lb(k);
            const h = key(set);
            const e = memo.get(h);
            if (e) return e.value;
            const b = Math.max(ply1(set), lb(k));
            memo.set(h, { value: b, exact: false, best: -1 });
            return b;
        }

        // Total cost of playing guess g on `set`; exact if < beta, otherwise some value >= beta.
        function evalGuess(set, g, rootBound, beta) {
            const groups = [];
            for (const [p, grp] of partition(set, g)) if (p !== SOLVED && grp.length > 2) groups.push(grp);
            groups.sort((a, b) => b.length - a.length);
            const bounds = groups.map(grp => lb(grp.length));
            let acc = rootBound;
            // Pass 1: tighten each group's bound (cheap) - usually enough to reject a bad guess.
            for (let j = 0; j < groups.length; j++) {
                const b = bound(groups[j]);
                acc += b - bounds[j];
                bounds[j] = b;
                if (acc >= beta) return acc;
            }
            // Pass 2: solve the groups exactly, largest first, each with the remaining budget.
            for (let j = 0; j < groups.length; j++) {
                acc += solve(groups[j], beta - acc + bounds[j]) - bounds[j];
                if (acc >= beta) return acc;
            }
            return acc;
        }

        // Exact total for `set` if it is < beta; otherwise some value >= beta.
        function solve(set, beta) {
            const k = set.length;
            if (k <= 2) return lb(k);
            const floor = lb(k);
            if (floor >= beta) return floor;
            const h = key(set);
            let knownLb = floor;
            const e = memo.get(h);
            if (e) {
                if (e.exact || e.value >= beta) return e.value;
                knownLb = e.value;
            }

            let best = beta, bestG = -1;
            const r = rankedGuesses(set);
            for (let j = 0; j < r.length; j++) {
                const b = Math.floor(r[j] / 65536);
                if (b >= best) break; // sorted by bound: nothing further can beat `best`
                const g = r[j] - b * 65536;
                const v = evalGuess(set, g, b, best);
                if (v < best) {
                    best = v; bestG = g;
                    if (best <= knownLb) break;
                }
            }
            if (best < beta) {
                memo.set(h, { value: best, exact: true, best: bestG });
                return best;
            }
            if (!e || (!e.exact && beta > e.value)) memo.set(h, { value: beta, exact: false, best: -1 });
            return beta;
        }

        // Guess-count histogram of the optimal continuation after playing g on `set`.
        function histogram(set, g, depth, hist) {
            for (const [p, grp] of partition(set, g)) {
                if (p === SOLVED) { hist[depth + 1] = (hist[depth + 1] || 0) + 1; continue; }
                if (grp.length === 1) { hist[depth + 2] = (hist[depth + 2] || 0) + 1; continue; }
                if (grp.length === 2) {
                    hist[depth + 2] = (hist[depth + 2] || 0) + 1;
                    hist[depth + 3] = (hist[depth + 3] || 0) + 1;
                    continue;
                }
                histogram(grp, memo.get(key(grp)).best, depth + 1, hist);
            }
            return hist;
        }

        // WebAssembly build of the same solver (wasm-solver/), embedded by build.py. Two modes:
        // - shared: the page passes a compiled threads build plus one shared memory; the first
        //   worker builds the pattern tables there once and hands every other worker its own
        //   stack + TLS block, so all workers search over a single copy of the tables;
        // - private: each worker instantiates the plain build below with its own tables.
        // The JS above is the fallback when neither is available.
        const WASM_B64 = "__WASM_PLACEHOLDER__";
        const WASM_STACK = 4 << 20;
        let wasm = null, wasmMem = null, wasmState = 0;

        function wasmCopy(bytes) {
            const p = wasm.alloc(bytes.length);
            new Uint8Array(wasmMem.buffer, p, bytes.length).set(bytes);
            return p;
        }

        function wasmBuildTables(m) {
            const letters = words => Uint8Array.from(words.flat());
            const tg = Uint32Array.from(m.targetGuess);
            return wasm.build_tables(m.targets.length, m.guesses.length, wasmCopy(letters(m.targets)),
                wasmCopy(letters(m.guesses)), wasmCopy(new Uint8Array(tg.buffer)));
        }

        function wasmMessage(m) {
            if (m.type === 'init-shared' || m.type === 'attach') {
                try {
                    wasm = new WebAssembly.Instance(m.module, { env: { memory: m.memory } }).exports;
                    wasmMem = m.memory;
                    const tlsBytes = wasm.__tls_size.value + wasm.__tls_align.value;
                    let tables = m.tables;
                    if (m.type === 'attach') {
                        wasm.__stack_pointer.value = m.stackTop; // before any call that uses the stack
                        wasm.__wasm_init_tls(m.tls);
                    } else {
                        wasm.__wasm_init_tls(wasm.alloc(tlsBytes)); // first instance keeps the default stack
                        tables = wasmBuildTables(m);
                        const slots = [];
                        for (let k = 0; k < m.extra; k++) {
                            const stack = wasm.alloc(WASM_STACK);
                            slots.push({ stackTop: (stack + WASM_STACK) & ~15, tls: wasm.alloc(tlsBytes) });
                        }
                        self.postMessage({ type: 'tables', tables, slots });
                    }
                    wasmState = wasm.new_worker(tables);
                    return self.postMessage({ type: 'ready', count: wasm.table_count(tables), engine: 'WebAssembly, shared memory' });
                } catch (e) {
                    return self.postMessage({ type: 'shared-failed', error: String(e) });
                }
            }
            if (m.type === 'init') {
                const tables = wasmBuildTables(m);
                wasmState = wasm.new_worker(tables);
                return self.postMessage({ type: 'ready', count: wasm.table_count(tables), engine: 'WebAssembly' });
            }
            const status = wasm.eval(wasmState, m.i, m.cutoff === Infinity ? 0xFFFFFFFF : m.cutoff);
            const out = new Uint32Array(wasmMem.buffer, wasm.out_ptr(wasmState), 19);
            const g = out[0];
            if (status === 0) return self.postMessage({ type: 'result', i: m.i, g, exhausted: true });
            if (status === 1) return self.postMessage({ type: 'result', i: m.i, g });
            self.postMessage({ type: 'result', i: m.i, g, total: out[1], hist: Array.from(out.slice(3, 3 + out[2])) });
        }

        function loadPrivateWasm() {
            if (!WASM_B64 || typeof WebAssembly !== 'object') return;
            try {
                const bytes = Uint8Array.from(atob(WASM_B64), c => c.charCodeAt(0));
                wasm = new WebAssembly.Instance(new WebAssembly.Module(bytes), {}).exports;
                wasmMem = wasm.memory;
            } catch (e) {
                wasm = null;
            }
        }

        self.onmessage = (msg) => {
            const m = msg.data;
            if (m.type === 'init-shared' || m.type === 'attach') return wasmMessage(m);
            if (m.type === 'init') loadPrivateWasm();
            if (wasm) return wasmMessage(m);
            if (m.type === 'init') {
                const { targets, guesses } = m;
                n = targets.length; ng = guesses.length;
                targetGuess = Int32Array.from(m.targetGuess);
                masks = new Uint32Array(ng * 8);
                groupCount = new Uint16Array(ng);
                pat = new Uint8Array(ng * n);
                patT = new Uint8Array(ng * n);
                for (let g = 0; g < ng; g++) {
                    const q = guesses[g];
                    for (let i = 0; i < n; i++) {
                        const t = targets[i];
                        patT[i * ng + g] = pat[g * n + i] = getPatternCode(q[0], q[1], q[2], q[3], q[4], t[0], t[1], t[2], t[3], t[4]);
                    }
                }
                zobA = new Int32Array(n); zobB = new Int32Array(n);
                for (let i = 0; i < n; i++) {
                    zobA[i] = (Math.random() * 4294967296) | 0;
                    zobB[i] = (Math.random() * 4294967296) | 0;
                }
                memo = new Map();
                all = Array.from({ length: n }, (_, i) => i);
                ranked = rankedGuesses(all);
                self.postMessage({ type: 'ready', count: ranked.length, engine: 'JavaScript' });
            } else if (m.type === 'eval') {
                // Evaluate the i-th first guess (in bound order) against the current cutoff.
                const b = Math.floor(ranked[m.i] / 65536);
                const g = ranked[m.i] - b * 65536;
                if (b >= m.cutoff) return self.postMessage({ type: 'result', i: m.i, g, exhausted: true });
                const v = evalGuess(all, g, b, m.cutoff);
                if (v >= m.cutoff) return self.postMessage({ type: 'result', i: m.i, g });
                self.postMessage({ type: 'result', i: m.i, g, total: v, hist: Array.from(histogram(all, g, 0, []), c => c || 0) });
            }
        };
    </script>

    <script>
        const STORAGE_KEY = 'wordle_custom_answers_v1';


        // Base strings generated by Python at build time
        const rawAnswers = "__ANSWERS_PLACEHOLDER__";
        const rawGuesses = "__GUESSES_PLACEHOLDER__";
        
        // Base arrays from text files
        let defaultAnswers = rawAnswers.trim().split(/\s+/).filter(w => w.length === 5);
        let extraGuesses = rawGuesses.trim().split(/\s+/).filter(w => w.length === 5);

        // Local database storage for custom valid answers
        let customAnswers = [];
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved) {
                const parsed = JSON.parse(saved);
                if (Array.isArray(parsed)) {
                    customAnswers = parsed.map(w => String(w).trim().toUpperCase()).filter(w => w.length === 5);
                }
            }
        } catch (e) {
            console.warn("Could not load from localStorage:", e);
        }

        // Active Pool Collections
        let allAnswers = [];
        let allAnswerCodes = [];
        let fullDictionary = [];
        let fullDictCodes = [];

        // Active State Storage
        let remainingAnswers = [];
        let remainingCodes = [];
        let guessHistory = [];
        let isBackupMode = false;
        let solvedWord = null;

        const input = document.getElementById('word-input');
        const tiles = document.querySelectorAll('.tile');
        const countDisplay = document.getElementById('count');
        const wordListDisplay = document.getElementById('word-list');
        const historyListDisplay = document.getElementById('history-list');
        const submitBtn = document.getElementById('submit-btn');
        const statusDisplay = document.getElementById('status');
        const solvedBanner = document.getElementById('solved-banner');
        const backupBanner = document.getElementById('backup-banner');

        const colors = ['var(--gray)', 'var(--yellow)', 'var(--green)'];

        function syncWordPools() {
            // Target Pool = default answers + custom added answers from local DB
            allAnswers = Array.from(new Set([...defaultAnswers, ...customAnswers])).sort();
            allAnswerCodes = allAnswers.map(w => [w.charCodeAt(0), w.charCodeAt(1), w.charCodeAt(2), w.charCodeAt(3), w.charCodeAt(4)]);

            // Diagnostic Pool = Guesses + Answers
            fullDictionary = Array.from(new Set([...allAnswers, ...extraGuesses])).sort();
            fullDictCodes = fullDictionary.map(w => [w.charCodeAt(0), w.charCodeAt(1), w.charCodeAt(2), w.charCodeAt(3), w.charCodeAt(4)]);

            updateDbStatsUI();
        }

        async function fetchAnswersFileIfAvailable() {
            // If served via HTTP/HTTPS, attempt to fetch live wordle-valid-answers.txt
            if (window.location.protocol.startsWith('http')) {
                try {
                    const res = await fetch('wordle-valid-answers.txt', { cache: 'no-cache' });
                    if (res.ok) {
                        const txt = await res.text();
                        const words = txt.trim().split(/\s+/).filter(w => w.length === 5).map(w => w.toUpperCase());
                        if (words.length > 0) {
                            defaultAnswers = Array.from(new Set(words));
                            syncWordPools();
                            applyFilters();
                            showDbFeedback(`Synced ${words.length} words from wordle-valid-answers.txt`);
                        }
                    }
                } catch (e) {
                    // Fetch failed, continue with embedded answers
                }
            }
        }

        function updateDbStatsUI() {
            const totalCountEl = document.getElementById('total-answers-count');
            const customBadgeEl = document.getElementById('custom-badge');
            const customCountEl = document.getElementById('custom-answers-count');
            const customCountPanelEl = document.getElementById('custom-count-panel');
            const poolModeBadgeEl = document.getElementById('pool-mode-badge');
            const customWordsListEl = document.getElementById('custom-words-list');

            if (totalCountEl) totalCountEl.innerText = allAnswers.length.toLocaleString();
            if (customCountEl) customCountEl.innerText = customAnswers.length.toLocaleString();
            if (customCountPanelEl) customCountPanelEl.innerText = customAnswers.length.toLocaleString();
            
            if (customBadgeEl) {
                customBadgeEl.style.display = customAnswers.length > 0 ? 'inline-block' : 'none';
            }

            if (poolModeBadgeEl) {
                if (isBackupMode) {
                    poolModeBadgeEl.className = 'badge-mode badge-mode-backup';
                    poolModeBadgeEl.innerText = 'Backup Pool Active';
                } else {
                    poolModeBadgeEl.className = 'badge-mode badge-mode-normal';
                    poolModeBadgeEl.innerText = 'Standard Pool';
                }
            }

            if (customWordsListEl) {
                if (customAnswers.length === 0) {
                    customWordsListEl.innerHTML = '<em style="color:#666; font-size:0.85rem; padding:4px;">No custom words added yet.</em>';
                } else {
                    customWordsListEl.innerHTML = '';
                    customAnswers.slice().reverse().forEach(word => {
                        const chip = document.createElement('div');
                        chip.className = 'custom-word-chip';
                        chip.innerHTML = `${word} <button title="Remove ${word}" onclick="removeCustomAnswer('${word}')">&times;</button>`;
                        customWordsListEl.appendChild(chip);
                    });
                }
            }
        }

        function toggleDbPanel() {
            const panel = document.getElementById('db-panel');
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }

        let feedbackTimer = null;
        function showDbFeedback(text) {
            const fb = document.getElementById('db-feedback');
            if (!fb) return;
            fb.innerText = text;
            if (feedbackTimer) clearTimeout(feedbackTimer);
            feedbackTimer = setTimeout(() => { fb.innerText = ''; }, 4000);
        }

        async function addWordToValidAnswers(word) {
            word = (word || '').trim().toUpperCase();
            if (word.length !== 5 || !/^[A-Z]{5}$/.test(word)) {
                alert("Word must be 5 alphabetic letters (A-Z).");
                return;
            }

            if (!customAnswers.includes(word)) {
                customAnswers.push(word);
                try {
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(customAnswers));
                } catch (e) {
                    console.error("Failed to save to localStorage:", e);
                }
            }

            syncWordPools();

            // Notify local backend server if running via http
            let serverSynced = false;
            if (window.location.protocol.startsWith('http')) {
                try {
                    const resp = await fetch('/api/add-answer', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ word: word })
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        if (data.success) serverSynced = true;
                    }
                } catch (e) {}
            }

            const msg = serverSynced
                ? `Added "${word}" to valid answers and saved to wordle-valid-answers.txt!`
                : `Added "${word}" to valid answers local database!`;

            showDbFeedback(msg);

            // Re-apply filters with updated valid answers pool
            applyFilters();
        }

        function removeCustomAnswer(word) {
            customAnswers = customAnswers.filter(w => w !== word);
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(customAnswers));
            } catch (e) {}
            syncWordPools();
            showDbFeedback(`Removed "${word}" from custom answers.`);
            applyFilters();
        }

        function clearCustomAnswers() {
            if (customAnswers.length === 0) return;
            if (!confirm("Are you sure you want to clear all custom added answers?")) return;
            customAnswers = [];
            try {
                localStorage.removeItem(STORAGE_KEY);
            } catch (e) {}
            syncWordPools();
            showDbFeedback("Cleared all custom answers.");
            applyFilters();
        }

        function addManualWord() {
            const inputEl = document.getElementById('manual-word-input');
            const val = inputEl.value.trim().toUpperCase();
            if (val.length !== 5) {
                alert("Please enter a 5-letter word.");
                return;
            }
            addWordToValidAnswers(val);
            inputEl.value = '';
        }

        async function saveOrDownloadAnswers() {
            const content = [...allAnswers].sort().join('\n') + '\n';

            // If browser supports File System Access API (Chrome/Edge), let user save directly to file
            if ('showSaveFilePicker' in window) {
                try {
                    const handle = await window.showSaveFilePicker({
                        suggestedName: 'wordle-valid-answers.txt',
                        types: [{
                            description: 'Text Files',
                            accept: { 'text/plain': ['.txt'] }
                        }]
                    });
                    const writable = await handle.createWritable();
                    await writable.write(content);
                    await writable.close();
                    showDbFeedback("Saved directly to wordle-valid-answers.txt!");
                    return;
                } catch (err) {
                    if (err.name === 'AbortError') return;
                    console.warn("File picker failed, falling back to download:", err);
                }
            }

            // Fallback for browsers without showSaveFilePicker
            const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'wordle-valid-answers.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showDbFeedback("Downloaded wordle-valid-answers.txt!");
        }

        function importAnswersFile(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const imported = text.trim().split(/\s+/).filter(w => w.length === 5).map(w => w.toUpperCase());
                if (imported.length > 0) {
                    defaultAnswers = Array.from(new Set([...defaultAnswers, ...imported]));
                    syncWordPools();
                    applyFilters();
                    showDbFeedback(`Imported ${imported.length} words.`);
                } else {
                    alert("No valid 5-letter words found in selected file.");
                }
            };
            reader.readAsText(file);
            event.target.value = '';
        }

        input.addEventListener('input', (e) => {
            const val = e.target.value.toUpperCase();
            e.target.value = val;
            tiles.forEach((tile, i) => tile.innerText = val[i] || '');
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                processUserInput();
            }
        });

        document.getElementById('manual-word-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                addManualWord();
            }
        });

        tiles.forEach(tile => {
            tile.addEventListener('click', () => {
                if (!tile.innerText) return;
                let state = (parseInt(tile.getAttribute('data-state')) + 1) % 3;
                tile.setAttribute('data-state', state);
                tile.style.backgroundColor = colors[state];
            });
        });

        function getPatternCode(g0, g1, g2, g3, g4, t0, t1, t2, t3, t4) {
            let p0=0, p1=0, p2=0, p3=0, p4=0;

            if (g0 === t0) { p0 = 2; t0 = 0; g0 = 1; }
            if (g1 === t1) { p1 = 2; t1 = 0; g1 = 1; }
            if (g2 === t2) { p2 = 2; t2 = 0; g2 = 1; }
            if (g3 === t3) { p3 = 2; t3 = 0; g3 = 1; }
            if (g4 === t4) { p4 = 2; t4 = 0; g4 = 1; }

            if (g0 !== 1) { if (g0===t1){p0=1;t1=0;} else if(g0===t2){p0=1;t2=0;} else if(g0===t3){p0=1;t3=0;} else if(g0===t4){p0=1;t4=0;} }
            if (g1 !== 1) { if (g1===t0){p1=1;t0=0;} else if(g1===t2){p1=1;t2=0;} else if(g1===t3){p1=1;t3=0;} else if(g1===t4){p1=1;t4=0;} }
            if (g2 !== 1) { if (g2===t0){p2=1;t0=0;} else if(g2===t1){p2=1;t1=0;} else if(g2===t3){p2=1;t3=0;} else if(g2===t4){p2=1;t4=0;} }
            if (g3 !== 1) { if (g3===t0){p3=1;t0=0;} else if(g3===t1){p3=1;t1=0;} else if(g3===t2){p3=1;t2=0;} else if(g3===t4){p3=1;t4=0;} }
            if (g4 !== 1) { if (g4===t0){p4=1;t0=0;} else if(g4===t1){p4=1;t1=0;} else if(g4===t2){p4=1;t2=0;} else if(g4===t3){p4=1;t3=0;} }

            return p0 + (p1 * 3) + (p2 * 9) + (p3 * 27) + (p4 * 81);
        }

        function renderResults() {
            stopExactSearch();
            updateDbStatsUI();

            if (isBackupMode) {
                countDisplay.innerText = `Possible answers left: ${remainingAnswers.length} (Backup Guesses)`;
                backupBanner.style.display = 'block';
                backupBanner.innerHTML = `<strong>⚠️ Backup Mode Active:</strong> No standard valid answers match your clue patterns. Now evaluating against <strong>${remainingAnswers.length}</strong> matching candidate(s) from the valid guesses list.`;
            } else {
                countDisplay.innerText = `Possible answers left: ${remainingAnswers.length}`;
                backupBanner.style.display = 'none';
            }

            // Handle Solved Banner & Option to Add Word
            if (solvedWord) {
                const isAlreadyInAnswers = allAnswers.includes(solvedWord);
                solvedBanner.style.display = 'flex';

                if (isAlreadyInAnswers) {
                    solvedBanner.className = 'banner solved-banner';
                    solvedBanner.innerHTML = `
                        <div class="banner-content">
                            <div class="banner-title">🎉 Solved Word: <span class="highlight-word">${solvedWord}</span></div>
                            <div class="banner-subtitle">✓ This word is already in your valid answers database.</div>
                        </div>
                        <button class="btn-tool" onclick="saveOrDownloadAnswers()">💾 Export TXT</button>
                    `;
                } else {
                    solvedBanner.className = 'banner solved-banner not-in-answers';
                    solvedBanner.innerHTML = `
                        <div class="banner-content">
                            <div class="banner-title">🎯 Target Word Found: <span class="highlight-word">${solvedWord}</span></div>
                            <div class="banner-subtitle">This word was found via the backup guesses list and is not yet in valid answers.</div>
                        </div>
                        <button class="btn-add-word-action" onclick="addWordToValidAnswers('${solvedWord}')">
                            ➕ Add "${solvedWord}" to Valid Answers
                        </button>
                    `;
                }
            } else {
                solvedBanner.style.display = 'none';
            }

            wordListDisplay.innerHTML = '';

            if (remainingAnswers.length === 0) {
                wordListDisplay.innerHTML = '<div style="text-align:center; color:#ff6b6b; padding:1.5rem; background:#2a2a2c; border-radius:4px;">No words match these constraints in answers or guesses! (Are you sure your colors are right?)</div>';
                return;
            }

            startExactSearch();
        }

        // ---- Exact search coordinator ------------------------------------------------------
        // Every allowed guess is a candidate next move. Workers each build the pattern table
        // and the same bound-ordered guess list; this thread hands out guesses one at a time
        // with the current cutoff (the TOP_K-th best exact total so far). A guess that can't
        // beat the cutoff is abandoned as soon as a bound proves it; once a guess's own bound
        // reaches the cutoff, so does every later one and the search is complete.
        const TOP_K = 10;
        const MAX_WORKERS = 12;        // each holds its own ~60 MB pattern tables
        const MAX_SHARED_WORKERS = 32; // one shared copy of the tables
        let search = null;

        // Threads build of the solver: used when the page is cross-origin isolated (served by
        // `python build.py --serve`), which is what lets workers share one WebAssembly memory.
        const SHARED_WASM_B64 = "__SHARED_WASM_PLACEHOLDER__";
        let sharedWasmModule, sharedWasmBroken = false;

        function getSharedWasmModule() {
            if (sharedWasmModule !== undefined) return sharedWasmModule;
            sharedWasmModule = null;
            if (SHARED_WASM_B64 && self.crossOriginIsolated && typeof WebAssembly === 'object') {
                try {
                    sharedWasmModule = new WebAssembly.Module(Uint8Array.from(atob(SHARED_WASM_B64), c => c.charCodeAt(0)));
                } catch (e) {
                    console.warn('Shared-memory solver unavailable:', e);
                }
            }
            return sharedWasmModule;
        }

        function stopExactSearch() {
            if (!search) return;
            search.workers.forEach(w => w.terminate());
            clearInterval(search.timer);
            search = null;
        }

        // ---- Remembered results ------------------------------------------------------------
        // A finished search depends only on the remaining answers and the guess pool, so slow
        // ones (in practice the first turn) are remembered in this browser and shown instantly
        // next time. Any change to the word lists changes the key, so it is searched afresh.
        const RESULT_CACHE_KEY = 'wordle_exact_results_v1';
        const CACHE_MIN_ANSWERS = 500;
        const CACHE_MAX_ENTRIES = 5;

        function searchKey() {
            const s = remainingAnswers.join(',') + '|' + fullDictionary.join(',') + '|' + TOP_K;
            let h = 0x811c9dc5;
            for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193) >>> 0;
            return h.toString(16) + ':' + remainingAnswers.length + ':' + fullDictionary.length;
        }

        function loadResultCache() {
            try {
                return JSON.parse(localStorage.getItem(RESULT_CACHE_KEY)) || {};
            } catch (e) {
                return {};
            }
        }

        function rememberResult(s, secs) {
            if (s.n < CACHE_MIN_ANSWERS) return;
            try {
                const cache = loadResultCache();
                cache[s.key] = { top: s.top, total: s.total, secs, engine: s.engine, saved: Date.now() };
                const keys = Object.keys(cache).sort((a, b) => cache[b].saved - cache[a].saved);
                keys.slice(CACHE_MAX_ENTRIES).forEach(k => delete cache[k]);
                localStorage.setItem(RESULT_CACHE_KEY, JSON.stringify(cache));
            } catch (e) {
                console.warn('Could not remember search result:', e);
            }
        }

        function showRememberedResult(hit) {
            renderTopList({ top: hit.top, n: remainingAnswers.length });
            const when = new Date(hit.saved).toLocaleString();
            statusDisplay.textContent = `Exact optimum: remembered from a search on ${when} `
                + `(all ${hit.total.toLocaleString()} guesses, ${hit.secs}s) · guesses to finish, incl. this one · `;
            const redo = document.createElement('a');
            redo.href = '#';
            redo.textContent = 'Recompute';
            redo.onclick = (e) => { e.preventDefault(); stopExactSearch(); startExactSearch(true); };
            statusDisplay.appendChild(redo);
            submitBtn.disabled = false;
        }

        function startExactSearch(recompute = false) {
            const n = remainingCodes.length;
            const key = searchKey();
            if (!recompute && n >= CACHE_MIN_ANSWERS) {
                const hit = loadResultCache()[key];
                if (hit) return showRememberedResult(hit);
            }
            const sharedModule = sharedWasmBroken ? null : getSharedWasmModule();
            const cores = Math.max(1, (navigator.hardwareConcurrency || 4) - 1);
            const count = n < 30 ? 1 : n < 200 ? Math.min(4, cores) : Math.min(sharedModule ? MAX_SHARED_WORKERS : MAX_WORKERS, cores);
            let src;
            try {
                src = URL.createObjectURL(new Blob(
                    [getPatternCode.toString() + document.getElementById('exact-worker-src').textContent],
                    { type: 'text/javascript' }));
            } catch (e) {
                statusDisplay.innerText = 'Exact search unavailable in this browser (Web Workers blocked).';
                return;
            }

            const targetGuess = remainingAnswers.map(w => fullDictionary.indexOf(w));
            const s = search = {
                n, key, workers: [], top: [], cutoff: Infinity, next: 0, total: null,
                busy: 0, checked: 0, exhausted: false, started: performance.now(), timer: null
            };
            const dispatch = (w) => {
                if (s.exhausted || s.next >= s.total) return;
                s.busy++;
                w.postMessage({ type: 'eval', i: s.next++, cutoff: s.cutoff });
            };
            const onMessage = (w, m) => {
                if (search !== s) return;
                if (m.type === 'tables') {
                    // Shared mode: tables are built; attach the other workers to them.
                    m.slots.forEach((slot, k) => s.workers[k + 1].postMessage({
                        type: 'attach', module: sharedModule, memory: s.memory, tables: m.tables, ...slot }));
                    return;
                }
                if (m.type === 'shared-failed') {
                    console.warn('Shared-memory solver failed, using per-worker tables:', m.error);
                    sharedWasmBroken = true;
                    stopExactSearch();
                    return startExactSearch();
                }
                if (m.type === 'ready') {
                    s.total = m.count;
                    s.engine = m.engine;
                    return dispatch(w);
                }
                s.busy--;
                if (m.exhausted) {
                    s.exhausted = true;
                } else {
                    s.checked++;
                    if (m.total !== undefined && m.total < s.cutoff) {
                        s.top.push({ word: fullDictionary[m.g], total: m.total, hist: m.hist });
                        s.top.sort((a, b) => a.total - b.total
                            || isRemaining(b.word) - isRemaining(a.word)
                            || (a.word < b.word ? -1 : 1));
                        s.top.length = Math.min(s.top.length, TOP_K);
                        if (s.top.length === TOP_K) s.cutoff = s.top[TOP_K - 1].total;
                        renderTopList(s);
                    }
                }
                dispatch(w);
                if (s.busy === 0) finishExactSearch(s);
            };

            for (let k = 0; k < count; k++) {
                const w = new Worker(src);
                w.onmessage = (e) => onMessage(w, e.data);
                w.onerror = (e) => {
                    console.error('Exact solver worker failed:', e);
                    if (search === s) { stopExactSearch(); statusDisplay.innerText = 'Exact search failed (see console).'; }
                };
                s.workers.push(w);
            }
            const job = { targets: remainingCodes, guesses: fullDictCodes, targetGuess };
            if (sharedModule) {
                s.memory = new WebAssembly.Memory({ initial: 1024, maximum: 32768, shared: true });
                s.workers[0].postMessage({ type: 'init-shared', module: sharedModule, memory: s.memory, extra: count - 1, ...job });
            } else {
                s.workers.forEach(w => w.postMessage({ type: 'init', ...job }));
            }
            submitBtn.disabled = false;
            statusDisplay.innerText = 'Exact search: preparing...';
            s.timer = setInterval(() => updateSearchStatus(s), 250);
        }

        function isRemaining(word) { return remainingAnswers.includes(word) ? 1 : 0; }

        function updateSearchStatus(s) {
            if (search !== s || s.total === null) return;
            const secs = ((performance.now() - s.started) / 1000).toFixed(1);
            statusDisplay.innerText = `Exact search: ${s.next.toLocaleString()} / ${s.total.toLocaleString()} guesses checked · ${secs}s (list may still change)`;
        }

        function finishExactSearch(s) {
            const secs = ((performance.now() - s.started) / 1000).toFixed(1);
            clearInterval(s.timer);
            s.workers.forEach(w => w.terminate());
            search = null;
            renderTopList(s);
            rememberResult(s, secs);
            statusDisplay.innerText = `Exact optimum: all ${s.total.toLocaleString()} guesses ruled in or out · ${secs}s (${s.engine}) · guesses to finish, incl. this one`;
        }

        // Guess-count stats of the (mean-optimal) strategy after a first guess.
        function distributionStats(hist, n) {
            let seen = 0, p95 = 0, max = 0;
            hist.forEach((c, d) => {
                if (!c) return;
                max = d;
                if (seen < 0.95 * n && seen + c >= 0.95 * n) p95 = d;
                seen += c;
            });
            return { p95, max };
        }

        function renderTopList(s) {
            wordListDisplay.innerHTML = '';
            s.top.forEach((item, rank) => wordListDisplay.appendChild(buildWordRow(item, s.n, rank === 0 && !search)));
        }

        const DIST_COLORS = ['', '#2e7d32', '#538d4e', '#8aa84a', '#b59f3b', '#c9733a', '#c0392b', '#8e2a1f'];

        function buildWordRow(item, n, isBest) {
            const row = document.createElement('div');
            row.className = isBest ? 'word-row optimal-row' : 'word-row';
            row.dataset.word = item.word;
            row.title = 'Click to put word into guess input';
            row.onclick = (e) => {
                if (e.target.tagName === 'BUTTON') return;
                input.value = item.word;
                tiles.forEach((tile, i) => {
                    tile.innerText = item.word[i];
                    tile.setAttribute('data-state', 0);
                    tile.style.backgroundColor = colors[0];
                });
            };

            const wordDiv = document.createElement('div');
            wordDiv.className = 'word-left';
            wordDiv.innerText = item.word;

            if (isBest) {
                const tag = document.createElement('span');
                tag.className = 'candidate-tag candidate-tag-optimal';
                tag.innerText = '★ Optimal';
                wordDiv.appendChild(tag);
            }

            if (isRemaining(item.word)) {
                if (!allAnswers.includes(item.word)) {
                    const tag = document.createElement('span');
                    tag.className = 'candidate-tag candidate-tag-backup';
                    tag.innerText = 'Backup Candidate';
                    wordDiv.appendChild(tag);

                    const addBtn = document.createElement('button');
                    addBtn.className = 'btn-sm-add';
                    addBtn.innerText = '+ Add as Answer';
                    addBtn.title = `Add ${item.word} to valid answers database`;
                    addBtn.onclick = (e) => {
                        e.stopPropagation();
                        addWordToValidAnswers(item.word);
                    };
                    wordDiv.appendChild(addBtn);
                } else {
                    const tag = document.createElement('span');
                    tag.className = 'candidate-tag candidate-tag-normal';
                    tag.innerText = '(Possible Answer)';
                    wordDiv.appendChild(tag);
                }
            }

            const { p95, max } = distributionStats(item.hist, n);
            const scoreDiv = document.createElement('div');
            scoreDiv.className = 'score-box';
            scoreDiv.title = 'Guesses to finish (including this one) with optimal follow-up play:\n'
                + item.hist.map((c, d) => c ? `${d} guess${d > 1 ? 'es' : ''}: ${c} (${(100 * c / n).toFixed(1)}%)` : '').filter(Boolean).join('\n');

            const avg = document.createElement('div');
            avg.className = 'score-avg';
            avg.innerText = (item.total / n).toFixed(3) + ' avg';
            const tail = document.createElement('div');
            tail.className = 'score-tail';
            tail.innerText = `p95 ${p95} · max ${max}`;
            const bar = document.createElement('div');
            bar.className = 'dist-bar';
            item.hist.forEach((c, d) => {
                if (!c) return;
                const seg = document.createElement('span');
                seg.style.width = (100 * c / n) + '%';
                seg.style.background = DIST_COLORS[Math.min(d, DIST_COLORS.length - 1)];
                bar.appendChild(seg);
            });
            scoreDiv.append(avg, tail, bar);

            row.appendChild(wordDiv);
            row.appendChild(scoreDiv);
            return row;
        }

        function addHistoryItem(guess, feedback) {
            const item = document.createElement('div');
            item.className = 'history-item';
            
            for (let i = 0; i < 5; i++) {
                const tile = document.createElement('div');
                tile.className = 'history-tile';
                tile.style.backgroundColor = colors[feedback[i]];
                tile.innerText = guess[i];
                item.appendChild(tile);
            }
            
            historyListDisplay.appendChild(item);
        }

        function resetGame() {
            guessHistory = [];
            solvedWord = null;
            historyListDisplay.innerHTML = '';
            clearInput();
            applyFilters();
        }

        function clearInput() {
            input.value = '';
            tiles.forEach(t => {
                t.innerText = '';
                t.setAttribute('data-state', 0);
                t.style.backgroundColor = colors[0];
            });
        }

        function processUserInput() {
            const guess = input.value.toUpperCase();
            if (guess.length !== 5) return alert("Enter a 5-letter word.");
            
            const feedback = Array.from(tiles).map(t => parseInt(t.getAttribute('data-state')));
            
            guessHistory.push({ guess, feedback });
            addHistoryItem(guess, feedback);
            clearInput();

            applyFilters();
        }

        function filterWordList(words, codes, history) {
            let currentWords = words;
            let currentCodes = codes;

            for (const turn of history) {
                const targetPattern = turn.feedback[0] + (turn.feedback[1]*3) + (turn.feedback[2]*9) + (turn.feedback[3]*27) + (turn.feedback[4]*81);
                const g0 = turn.guess.charCodeAt(0);
                const g1 = turn.guess.charCodeAt(1);
                const g2 = turn.guess.charCodeAt(2);
                const g3 = turn.guess.charCodeAt(3);
                const g4 = turn.guess.charCodeAt(4);

                const nextWords = [];
                const nextCodes = [];
                
                for (let i = 0; i < currentCodes.length; i++) {
                    const target = currentCodes[i];
                    const pattern = getPatternCode(g0, g1, g2, g3, g4, 
                                                   target[0], target[1], target[2], target[3], target[4]);
                    
                    if (pattern === targetPattern) {
                        nextWords.push(currentWords[i]);
                        nextCodes.push(target);
                    }
                }
                currentWords = nextWords;
                currentCodes = nextCodes;
            }

            return { words: currentWords, codes: currentCodes };
        }

        function applyFilters() {
            if (guessHistory.length === 0) {
                isBackupMode = false;
                remainingAnswers = [...allAnswers];
                remainingCodes = [...allAnswerCodes];
                solvedWord = null;
                renderResults();
                return;
            }

            const lastTurn = guessHistory[guessHistory.length - 1];
            const isAllGreen = lastTurn.feedback.every(f => f === 2);

            // 1. Try filtering standard valid answers pool
            const primaryFiltered = filterWordList(allAnswers, allAnswerCodes, guessHistory);

            if (primaryFiltered.words.length > 0) {
                isBackupMode = false;
                remainingAnswers = primaryFiltered.words;
                remainingCodes = primaryFiltered.codes;
            } else {
                // 2. BACKUP MODE: No valid answers match, fallback to full valid guesses list!
                const backupFiltered = filterWordList(fullDictionary, fullDictCodes, guessHistory);
                if (backupFiltered.words.length > 0) {
                    isBackupMode = true;
                    remainingAnswers = backupFiltered.words;
                    remainingCodes = backupFiltered.codes;
                } else {
                    isBackupMode = false;
                    remainingAnswers = [];
                    remainingCodes = [];
                }
            }

            // Determine if the word was solved or isolated
            if (isAllGreen) {
                solvedWord = lastTurn.guess;
            } else if (remainingAnswers.length === 1) {
                solvedWord = remainingAnswers[0];
            } else {
                solvedWord = null;
            }

            renderResults();
        }

        // Auto-close local server when browser tab is closed
        window.addEventListener('pagehide', () => {
            if (window.location.protocol.startsWith('http')) {
                navigator.sendBeacon('/api/close');
            }
        });

        // Initialize immediately
        syncWordPools();
        remainingAnswers = [...allAnswers];
        remainingCodes = [...allAnswerCodes];
        renderResults();
        fetchAnswersFileIfAvailable();
    </script>
</body>
</html>
"""

# 3. Local Server Handler for Disk Synchronization
class WordleServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.path = "/wordle-solver.html"
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/close":
            self.send_response(200)
            self.end_headers()
            def shutdown_if_idle():
                import time
                time.sleep(2)
                # Shutdown server process
                os._exit(0)
            import threading
            threading.Thread(target=shutdown_if_idle, daemon=True).start()
            return

        if self.path == "/api/add-answer":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                word = data.get("word", "").strip().upper()
                if len(word) == 5 and word.isalpha():
                    words = set()
                    if os.path.exists(ANSWERS_FILE):
                        with open(ANSWERS_FILE, "r", encoding="utf-8") as f:
                            words = set(f.read().upper().split())
                    
                    if word not in words:
                        words.add(word)
                        sorted_words = sorted(list(words))
                        with open(ANSWERS_FILE, "w", encoding="utf-8") as f:
                            f.write("\n".join(sorted_words) + "\n")
                        print(f"[Server] Added '{word}' to {os.path.basename(ANSWERS_FILE)} (Total: {len(sorted_words)})")
                        # Automatically re-bake wordle-solver.html so it is updated across all browsers
                        build_html()
                    
                    response = json.dumps({"success": True, "word": word, "total": len(words)}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(response)
                    return
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Word must be 5 alphabetic letters"}).encode("utf-8"))
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return
        
        self.send_response(404)
        self.end_headers()

    def end_headers(self):
        # Cross-origin isolation: lets the page use SharedArrayBuffer for the shared-memory solver.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        if self.path.endswith(".txt") or self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

def build_html():
    answers_str, guesses_str = read_word_lists()
    def embed(path, missing_note):
        if not os.path.exists(path):
            print(missing_note)
            return ""
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    wasm_b64 = embed(WASM_FILE, "Note: wasm-solver not built; the page will use the slower JavaScript solver.")
    shared_wasm_b64 = embed(SHARED_WASM_FILE, "Note: shared-memory wasm-solver not built; --serve will use per-worker tables.")
    final_html = (html_template
                  .replace("__ANSWERS_PLACEHOLDER__", answers_str)
                  .replace("__GUESSES_PLACEHOLDER__", guesses_str)
                  .replace("__WASM_PLACEHOLDER__", wasm_b64)
                  .replace("__SHARED_WASM_PLACEHOLDER__", shared_wasm_b64))

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"Success! Generated '{os.path.basename(OUTPUT_HTML)}'.")
    print("- Standalone: Double-click 'wordle-solver.html' to open directly in any browser.")
    print("  (New words are saved in your browser's local database and can be exported anytime.)")
    print("- Live Server: Run 'python build.py --serve' to auto-sync additions directly to wordle-valid-answers.txt on disk.")

if __name__ == "__main__":
    build_html()
    if "--serve" in sys.argv or "-s" in sys.argv:
        port = 8000
        print(f"\nStarting live sync server at http://localhost:{port}/wordle-solver.html ...")
        print("Press Ctrl+C to stop the server.")
        try:
            webbrowser.open(f"http://localhost:{port}/wordle-solver.html")
        except Exception:
            pass
        server = HTTPServer(("127.0.0.1", port), WordleServerHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            server.server_close()