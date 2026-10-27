PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: install doctor sample demo demo-offline test ask ablate export-demo clean

install:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

doctor:
	PYTHONPATH=src $(PY) -m palimpsest doctor

sample:
	./scripts/make_sample_image.sh

demo: sample
	PYTHONPATH=src $(PY) -m palimpsest run sample/ghost.img --out out --carve

demo-offline: sample
	PYTHONPATH=src $(PY) -m palimpsest run sample/ghost.img --out out-offline --no-llm

test:
	PYTHONPATH=src $(PY) -m pytest -q

ask:
	PYTHONPATH=src $(PY) -m palimpsest ask "$(Q)" --out out

ablate:
	PYTHONPATH=src $(PY) -m palimpsest ablate --out out

# Publish the synthetic sample case to docs/demo/ for GitHub Pages.
# Never run this on a real case.
export-demo:
	./scripts/export_demo.sh

clean:
	rm -rf out out-offline sample .pytest_cache
