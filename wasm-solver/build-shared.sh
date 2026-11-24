#!/bin/sh
# Threads build of the solver: one shared WebAssembly memory for all page workers.
# Needs: rustup toolchain install nightly && rustup component add rust-src --toolchain nightly
cd "$(dirname "$0")" || exit 1
RUSTFLAGS="-C target-feature=+atomics,+bulk-memory,+mutable-globals \
 -C link-arg=--shared-memory -C link-arg=--import-memory \
 -C link-arg=--initial-memory=67108864 -C link-arg=--max-memory=2147483648 \
 -C link-arg=--export=__stack_pointer -C link-arg=--export=__wasm_init_tls \
 -C link-arg=--export=__tls_size -C link-arg=--export=__tls_align" \
cargo +nightly build --release --target wasm32-unknown-unknown -Z build-std=std,panic_abort --target-dir target-shared
