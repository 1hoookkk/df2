# TRENCH pipeline front door.  `just --list` shows everything.

# geometry IR -> body240 via THE compiler (grid-certified)
pack geo out="":
    python -m tools.filter_cli pack {{geo}} {{out}}

validate geo:
    python -m tools.filter_cli validate {{geo}}

plot geo:
    python -m tools.filter_cli plot {{geo}}

diff a b:
    python -m tools.filter_cli diff {{a}} {{b}}

# contract test: fixture bytes + golden geometry->body240 compile
test:
    python -m tools.test_contract

# build the compiler (and the rest of trench-core release bins)
compiler:
    cargo build --release -p trench-core --bin body-from-geometry

# render the shipped roster for the ear (tournament page)
audition:
    python -m tools.render_tournament "{{justfile_directory()}}/plugin/presets/bodies"

# nuke exhaust
clean:
    python -c "import shutil; shutil.rmtree('dev/tmp', ignore_errors=True); shutil.rmtree('out', ignore_errors=True); print('out/ and dev/tmp/ cleared')"
