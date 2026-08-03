.PHONY: build serve clean check-gh

check-gh:
	@command -v gh >/dev/null 2>&1 || { echo "gh CLI not found: https://cli.github.com"; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }

build: check-gh
	python3 scripts/build.py

serve: build
	@echo "Serving docs/ at http://localhost:8000"
	python3 -m http.server 8000 --directory docs

clean:
	rm -f docs/index.html docs/data.json
