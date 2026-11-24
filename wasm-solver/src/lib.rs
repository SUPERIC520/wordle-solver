//! Exact Wordle solver compiled to WebAssembly for the page's Web Workers.
//!
//! Cost of a strategy = total guesses summed over every remaining answer (avg = total / n).
//! Depth-first search with alpha-beta style cutoffs: each call only has to decide whether it
//! can beat `beta`, and gives up as soon as a lower bound proves it can't. A transposition
//! table holds exact values and proven lower bounds. Same algorithm as the JS fallback in
//! build.py and research/solver-bench.
//!
//! Worker protocol: `alloc` buffers, fill them, `init` once per position, then `eval(i, cutoff)`
//! for the i-th first guess in bound order; results are read from `out_ptr()`.

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};

const SOLVED: u8 = 242; // all-green pattern code
const INF: u32 = u32::MAX / 2;
const MAX_HIST: usize = 16;

/// Same scoring as getPatternCode() in the page: greens first, then yellows left to right.
fn pattern(g: &[u8], t: &[u8]) -> u8 {
    let mut p = [0u8; 5];
    let mut t = [t[0], t[1], t[2], t[3], t[4]];
    let mut green = [false; 5];
    for i in 0..5 {
        if g[i] == t[i] {
            p[i] = 2;
            t[i] = 0;
            green[i] = true;
        }
    }
    for i in 0..5 {
        if green[i] {
            continue;
        }
        for j in 0..5 {
            if j != i && g[i] == t[j] {
                p[i] = 1;
                t[j] = 0;
                break;
            }
        }
    }
    p[0] + p[1] * 3 + p[2] * 9 + p[3] * 27 + p[4] * 81
}

/// Lower bound on total guesses for any k-answer set (exact for k <= 2): guess a member, the
/// other k-1 land in at most 242 groups, each group of size s needing at least 2s-1 more.
#[inline]
fn lb(k: usize) -> u32 {
    if k == 0 {
        0
    } else {
        (3 * k - 2 - (k - 1).min(242)) as u32
    }
}

#[derive(Clone, Copy)]
struct Entry {
    value: u32,
    exact: bool,
    best: u16,
}

/// Read-only data for a position, shared by every worker (one copy in shared memory).
pub struct Tables {
    n: usize,
    ng: usize,
    pat: Vec<u8>,           // guess-major: pat[g * n + a]
    pat_t: Vec<u8>,         // answer-major: pat_t[a * ng + g]
    target_guess: Vec<u32>, // answer index -> its own guess index
    zob: Vec<u64>,
    all: Vec<u16>,
    ranked: Vec<(u32, u16)>, // first guesses in bound order
}

/// Keys are already random (Zobrist), so hash them as-is. Also avoids RandomState, which
/// needs thread-local storage.
#[derive(Default)]
struct IdHasher(u64);
impl Hasher for IdHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, _: &[u8]) {
        unreachable!()
    }
    fn write_u64(&mut self, k: u64) {
        self.0 = k;
    }
}

/// One worker's search state: transposition table and scratch buffers.
pub struct State {
    t: &'static Tables,
    memo: HashMap<u64, Entry, BuildHasherDefault<IdHasher>>,
    masks: Vec<u64>,
    group_count: Vec<u16>,
    seen: [u32; 243],
    stamp: u32,
    out: [u32; 3 + MAX_HIST], // [guess, total, hist_len, hist...]
}

impl State {
    #[inline]
    fn row(&self, g: usize) -> &[u8] {
        &self.t.pat[g * self.t.n..(g + 1) * self.t.n]
    }

    fn key(&self, set: &[u16]) -> u64 {
        set.iter().fold(0u64, |k, &a| k ^ self.t.zob[a as usize])
    }

    /// Groups of `set` by the feedback guess g gives, as (pattern, members).
    fn partition(&self, set: &[u16], g: usize) -> Vec<(u8, Vec<u16>)> {
        let row = self.row(g);
        let mut counts = [0u16; 243];
        for &a in set {
            counts[row[a as usize] as usize] += 1;
        }
        let mut slot = [u16::MAX; 243];
        let mut groups: Vec<(u8, Vec<u16>)> = Vec::new();
        for &a in set {
            let p = row[a as usize] as usize;
            if slot[p] == u16::MAX {
                slot[p] = groups.len() as u16;
                groups.push((p as u8, Vec::with_capacity(counts[p] as usize)));
            }
            groups[slot[p] as usize].1.push(a);
        }
        groups
    }

    /// Every guess that splits `set`, as (bound, guess) sorted by bound, where
    /// bound = k + sum of lb(group) over the groups it leaves.
    fn ranked_guesses(&mut self, set: &[u16]) -> Vec<(u32, u16)> {
        let k = set.len();
        let mut out = Vec::with_capacity(self.t.ng);
        if k <= 243 {
            // lb(s) = 2s-1 here, so bound = 3k - (#groups + [guess is in set]).
            self.group_counts(set);
            for (g, &c) in self.group_count.iter().enumerate() {
                if c > 1 {
                    out.push((3 * k as u32 - c as u32, g as u16));
                }
            }
            out.sort_unstable();
            return out;
        }
        let mut counts = [0u16; 243];
        let mut touched: Vec<u8> = Vec::with_capacity(243);
        for g in 0..self.t.ng {
            let row = self.row(g);
            for &a in set {
                let p = row[a as usize];
                if counts[p as usize] == 0 {
                    touched.push(p);
                }
                counts[p as usize] += 1;
            }
            if touched.len() > 1 || touched[0] == SOLVED {
                let mut bound = k as u32;
                for &p in &touched {
                    if p != SOLVED {
                        bound += lb(counts[p as usize] as usize);
                    }
                }
                out.push((bound, g as u16));
            }
            for &p in &touched {
                counts[p as usize] = 0;
            }
            touched.clear();
        }
        out.sort_unstable();
        out
    }

    /// One-ply lower bound: min over guesses of k + sum lb(group), i.e. the best ranked bound.
    fn ply1(&mut self, set: &[u16]) -> u32 {
        let k = set.len();
        if k > 243 {
            return self.ranked_guesses(set).first().map_or(lb(k), |r| r.0);
        }
        self.group_counts(set);
        let best = self.group_count.iter().copied().max().unwrap_or(1).max(1) as usize;
        (3 * k - best) as u32
    }

    /// group_count[g] = #distinct patterns g gives on `set` + [g is in set] (k <= 243).
    fn group_counts(&mut self, set: &[u16]) {
        let ng = self.t.ng;
        self.group_count.fill(0);
        let counts = self.group_count.as_mut_ptr();
        if set.len() < 16 {
            // Small set: per guess, stamp the patterns seen (row-major).
            for g in 0..ng {
                if self.stamp == u32::MAX {
                    self.seen = [0; 243];
                    self.stamp = 0;
                }
                self.stamp += 1;
                let s = self.stamp;
                let row = &self.t.pat[g * self.t.n..(g + 1) * self.t.n];
                let mut groups = 0u16;
                for &a in set {
                    let p = row[a as usize] as usize;
                    groups += (self.seen[p] != s) as u16;
                    self.seen[p] = s;
                }
                self.group_count[g] = groups;
            }
        } else {
            // Larger set: one sequential pass per answer row (answer-major) with a 243-bit
            // seen-mask per guess.
            self.masks.fill(0);
            let masks = self.masks.as_mut_ptr();
            for &a in set {
                let row = &self.t.pat_t[a as usize * ng..(a as usize + 1) * ng];
                for (g, &p) in row.iter().enumerate() {
                    // SAFETY: g < ng and p < 243, so the index is < ng * 4 = masks.len(),
                    // and g < group_count.len().
                    unsafe {
                        let m = masks.add((g << 2) | (p as usize >> 6));
                        let bit = 1u64 << (p & 63);
                        let seen = *m & bit;
                        *m |= bit;
                        *counts.add(g) += (seen == 0) as u16;
                    }
                }
            }
        }
        for &a in set {
            self.group_count[self.t.target_guess[a as usize] as usize] += 1; // solves itself
        }
    }

    /// Best known lower bound for `set` (memoised).
    fn bound(&mut self, set: &[u16]) -> u32 {
        let k = set.len();
        if k <= 2 {
            return lb(k);
        }
        let h = self.key(set);
        if let Some(e) = self.memo.get(&h) {
            return e.value;
        }
        let b = self.ply1(set).max(lb(k));
        self.memo.insert(h, Entry { value: b, exact: false, best: 0 });
        b
    }

    /// Total cost of playing guess g on `set`; exact if < beta, otherwise some value >= beta.
    fn eval_guess(&mut self, set: &[u16], g: usize, root_bound: u32, beta: u32) -> u32 {
        let mut groups: Vec<(u32, Vec<u16>)> = self
            .partition(set, g)
            .into_iter()
            .filter(|(p, v)| *p != SOLVED && v.len() > 2)
            .map(|(_, v)| (lb(v.len()), v))
            .collect();
        groups.sort_unstable_by_key(|(_, v)| std::cmp::Reverse(v.len()));
        let mut acc = root_bound;
        // Pass 1: tighten each group's bound (cheap) - usually enough to reject a bad guess.
        for (l, grp) in groups.iter_mut() {
            let b = self.bound(grp);
            acc += b - *l;
            *l = b;
            if acc >= beta {
                return acc;
            }
        }
        // Pass 2: solve the groups exactly, largest first, each with the remaining budget.
        for (l, grp) in &groups {
            acc += self.solve(grp, beta - acc + *l) - *l;
            if acc >= beta {
                return acc;
            }
        }
        acc
    }

    /// Exact total for `set` if it is < beta; otherwise some value >= beta.
    fn solve(&mut self, set: &[u16], beta: u32) -> u32 {
        let k = set.len();
        if k <= 2 {
            return lb(k);
        }
        let floor = lb(k);
        if floor >= beta {
            return floor;
        }
        let h = self.key(set);
        let mut known_lb = floor;
        let prev = self.memo.get(&h).copied();
        if let Some(e) = prev {
            if e.exact || e.value >= beta {
                return e.value;
            }
            known_lb = e.value;
        }

        let mut best = beta;
        let mut best_g = u16::MAX;
        for (b, g) in self.ranked_guesses(set) {
            if b >= best {
                break; // sorted by bound: nothing further can beat `best`
            }
            let v = self.eval_guess(set, g as usize, b, best);
            if v < best {
                best = v;
                best_g = g;
                if best <= known_lb {
                    break;
                }
            }
        }
        if best < beta {
            self.memo.insert(h, Entry { value: best, exact: true, best: best_g });
            best
        } else {
            if prev.map_or(true, |e| !e.exact && beta > e.value) {
                self.memo.insert(h, Entry { value: beta, exact: false, best: 0 });
            }
            beta
        }
    }

    /// Guess-count histogram of the optimal continuation after playing g on `set`.
    fn histogram(&self, set: &[u16], g: usize, depth: usize, hist: &mut [u32; MAX_HIST]) {
        let bump = |d: usize, hist: &mut [u32; MAX_HIST]| hist[d.min(MAX_HIST - 1)] += 1;
        for (p, grp) in self.partition(set, g) {
            match grp.len() {
                _ if p == SOLVED => bump(depth + 1, hist),
                1 => bump(depth + 2, hist),
                2 => {
                    bump(depth + 2, hist);
                    bump(depth + 3, hist);
                }
                _ => {
                    let e = self.memo[&self.key(&grp)];
                    self.histogram(&grp, e.best as usize, depth + 1, hist);
                }
            }
        }
    }
}

impl State {
    fn new(t: &'static Tables) -> State {
        State {
            t,
            memo: HashMap::default(),
            masks: vec![0; t.ng * 4],
            group_count: vec![0; t.ng],
            seen: [0; 243],
            stamp: 0,
            out: [0; 3 + MAX_HIST],
        }
    }
}

/// Allocate `size` bytes (leaked: everything lives until the worker / memory is dropped).
#[no_mangle]
pub extern "C" fn alloc(size: usize) -> *mut u8 {
    let mut v = vec![0u8; size];
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

/// Build the shared tables for a position. `targets`: n*5 letter bytes, `guesses`: ng*5
/// letter bytes, `target_guess`: n u32 guess indices.
#[no_mangle]
pub extern "C" fn build_tables(n: usize, ng: usize, targets: *const u8, guesses: *const u8, target_guess: *const u32) -> *const Tables {
    let targets = unsafe { std::slice::from_raw_parts(targets, n * 5) };
    let guesses = unsafe { std::slice::from_raw_parts(guesses, ng * 5) };
    let target_guess = unsafe { std::slice::from_raw_parts(target_guess, n) }.to_vec();

    let mut pat = vec![0u8; ng * n];
    let mut pat_t = vec![0u8; ng * n];
    for g in 0..ng {
        let gw = &guesses[g * 5..g * 5 + 5];
        for a in 0..n {
            let p = pattern(gw, &targets[a * 5..a * 5 + 5]);
            pat[g * n + a] = p;
            pat_t[a * ng + g] = p;
        }
    }
    let mut seed: u64 = 0x9E3779B97F4A7C15;
    let zob = (0..n)
        .map(|_| {
            seed = seed.wrapping_add(0x9E3779B97F4A7C15);
            let mut z = seed;
            z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
            z ^ (z >> 31)
        })
        .collect();
    let t: *mut Tables = Box::into_raw(Box::new(Tables {
        n, ng, pat, pat_t, target_guess, zob, all: (0..n as u16).collect(), ranked: Vec::new(),
    }));
    // SAFETY: `t` is leaked (lives forever); the temporary State is gone before the write.
    let ranked = State::new(unsafe { &*t }).ranked_guesses(unsafe { &(*t).all });
    unsafe { (*t).ranked = ranked };
    t
}

/// How many first guesses there are to evaluate.
#[no_mangle]
pub extern "C" fn table_count(t: *const Tables) -> u32 {
    unsafe { (*t).ranked.len() as u32 }
}

/// A worker's own search state over shared tables.
#[no_mangle]
pub extern "C" fn new_worker(t: *const Tables) -> *mut State {
    Box::leak(Box::new(State::new(unsafe { &*t })))
}

/// Result buffer of a worker: [guess, total, hist_len, hist...].
#[no_mangle]
pub extern "C" fn out_ptr(w: *const State) -> *const u32 {
    unsafe { (*w).out.as_ptr() }
}

/// Evaluate the i-th first guess (bound order) against `cutoff` (u32::MAX = none).
/// Returns 0 if its bound already reaches the cutoff (so does every later one),
/// 1 if it can't beat the cutoff, 2 if it can (exact total + histogram written to out).
#[no_mangle]
pub extern "C" fn eval(w: *mut State, i: usize, cutoff: u32) -> u32 {
    let st = unsafe { &mut *w };
    let cutoff = cutoff.min(INF);
    let (b, g) = st.t.ranked[i];
    st.out[0] = g as u32;
    if b >= cutoff {
        return 0;
    }
    let all = &st.t.all;
    let v = st.eval_guess(all, g as usize, b, cutoff);
    if v >= cutoff {
        return 1;
    }
    let mut hist = [0u32; MAX_HIST];
    st.histogram(all, g as usize, 0, &mut hist);
    let len = hist.iter().rposition(|&c| c > 0).map_or(0, |d| d + 1);
    st.out[1] = v;
    st.out[2] = len as u32;
    st.out[3..].copy_from_slice(&hist);
    2
}
