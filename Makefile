# Django Boilerplate — dev convenience targets.
#
# All targets are idempotent and safe to run repeatedly. Targets that
# mutate anything (regenerating requirements, writing SBOM, etc.) are
# explicitly named with an action verb.

.PHONY: help audit audit-all check deps-check sbom sbom-diff install-hooks \
	test test-unit test-integration test-e2e test-slow test-external \
	test-cov test-cov-html test-cov-open coverage-clean

# Pytest passthrough: `make test ARGS="-k foo -x"`
ARGS ?=
PYTEST := DJANGO_ENV=test pytest

# Single source of truth for the Python base image. Must match the digest
# pinned in Dockerfile line 6 / line 36. Refresh both places together via:
#   docker pull python:3.12-slim && \
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
PYTHON_IMAGE := python:3.12-slim@sha256:520153e2deb359602c9cffd84e491e3431d76e7bf95a3255c9ce9433b76ab99a

# Pinned tooling — scanners that silently upgrade themselves produce
# non-reproducible findings. Refresh alongside the quarterly dep audit.
PIP_AUDIT_VERSION  := 2.10.0
CYCLONEDX_VERSION  := 7.3.0

# The ephemeral audit container mirrors the Dockerfile's build-stage system
# packages (gcc, libc6-dev, libpq-dev) so psycopg2 and similar C-extension
# deps can be resolved. Pins match Dockerfile; recapture versions with:
#   docker run --rm $(PYTHON_IMAGE) bash -c \
#     "apt-get update -qq && apt-cache policy gcc libc6-dev libpq-dev"
AUDIT_SYSTEM_DEPS := apt-get update -qq && apt-get install -y -qq --no-install-recommends \
	gcc=4:14.2.0-1 \
	libc6-dev=2.41-12+deb13u2 \
	libpq-dev=17.9-0+deb13u1

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

audit-hot-path:  ## Profile capture_and_dispatch overhead (p50/p95/p99)
	python scripts/profile_audit_path.py

settings-schema:  ## Print the env-vars schema dumped from config/settings/base.py
	python scripts/dump_settings_schema.py

settings-schema-check:  ## Fail if docs/configuration.md drifts from base.py
	python scripts/dump_settings_schema.py --check

audit:  ## Run pip-audit against requirements/prod.txt (ephemeral container)
	docker run --rm -v "$(CURDIR)/requirements:/reqs:ro" $(PYTHON_IMAGE) \
		sh -c "$(AUDIT_SYSTEM_DEPS) && pip install --quiet pip-audit==$(PIP_AUDIT_VERSION) && pip-audit -r /reqs/prod.txt"

audit-all:  ## Run pip-audit against every layered requirements file
	@for layer in base prod dev test; do \
		echo; \
		echo "=== pip-audit: requirements/$$layer.txt ==="; \
		docker run --rm -v "$(CURDIR)/requirements:/reqs:ro" $(PYTHON_IMAGE) \
			sh -c "$(AUDIT_SYSTEM_DEPS) && pip install --quiet pip-audit==$(PIP_AUDIT_VERSION) && pip-audit -r /reqs/$$layer.txt" \
			|| echo "!! audit failed for $$layer.txt"; \
	done

check:  ## Run `pip check` against prod deps (detects transitive version conflicts)
	docker run --rm -v "$(CURDIR)/requirements:/reqs:ro" $(PYTHON_IMAGE) \
		sh -c "$(AUDIT_SYSTEM_DEPS) && pip install --quiet --require-hashes -r /reqs/prod.txt && pip check"

deps-check:  ## Verify each requirements/*.txt is in sync with its .in (fails on drift)
	@set -e; \
	for layer in base prod dev test; do \
		echo "=== deps-check: requirements/$$layer.{in,txt} ==="; \
		if [ "$$layer" = "dev" ]; then extra_flags="--allow-unsafe"; else extra_flags=""; fi; \
		docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(PYTHON_IMAGE) \
			sh -c "$(AUDIT_SYSTEM_DEPS) && pip install --quiet pip-tools && \
				pip-compile --quiet --generate-hashes $$extra_flags \
					--output-file=/tmp/$$layer.txt requirements/$$layer.in && \
				sed 's|/tmp/$$layer.txt|requirements/$$layer.txt|' /tmp/$$layer.txt > /tmp/$$layer.normalized.txt && \
				diff -u requirements/$$layer.txt /tmp/$$layer.normalized.txt > /dev/null \
					|| { echo '!! drift: requirements/$$layer.txt is out of sync with $$layer.in — run pip-compile'; exit 1; }"; \
	done; \
	echo "all layers in sync."

sbom:  ## Generate CycloneDX SBOM for prod deps at sbom/prod-sbom.json
	@mkdir -p sbom
	@host_uid=$$(id -u); host_gid=$$(id -g); \
	docker run --rm \
		-v "$(CURDIR)/requirements:/reqs:ro" \
		-v "$(CURDIR)/sbom:/out" \
		$(PYTHON_IMAGE) \
		sh -c "pip install --quiet cyclonedx-bom==$(CYCLONEDX_VERSION) && \
			cyclonedx-py requirements --output-file /out/prod-sbom.json /reqs/prod.txt && \
			chown $${host_uid}:$${host_gid} /out/prod-sbom.json"
	@echo "wrote sbom/prod-sbom.json"

sbom-diff:  ## Diff a freshly-generated SBOM against the committed sbom/prod-sbom.json
	@if [ ! -f sbom/prod-sbom.json ]; then \
		echo "!! sbom/prod-sbom.json missing — run 'make sbom' to create the baseline first."; \
		exit 1; \
	fi
	@tmpdir=$$(mktemp -d); \
	host_uid=$$(id -u); host_gid=$$(id -g); \
	docker run --rm \
		-v "$(CURDIR)/requirements:/reqs:ro" \
		-v "$$tmpdir:/out" \
		$(PYTHON_IMAGE) \
		sh -c "pip install --quiet cyclonedx-bom==$(CYCLONEDX_VERSION) && \
			cyclonedx-py requirements --output-file /out/prod-sbom.json /reqs/prod.txt && \
			chown $${host_uid}:$${host_gid} /out/prod-sbom.json" >/dev/null; \
	if diff -u \
		<(jq -S '.components | map({name, version, purl}) | sort_by(.purl)' sbom/prod-sbom.json) \
		<(jq -S '.components | map({name, version, purl}) | sort_by(.purl)' "$$tmpdir/prod-sbom.json"); then \
		echo "sbom in sync."; \
	else \
		echo; \
		echo "!! sbom drift — components above differ from sbom/prod-sbom.json."; \
		echo "   If intentional, run 'make sbom' and commit the updated baseline."; \
		rm -rf "$$tmpdir"; \
		exit 1; \
	fi; \
	rm -rf "$$tmpdir"

# ---------------------------------------------------------------------------
# Test targets
# ---------------------------------------------------------------------------

test:  ## Run the default test suite (unit + integration + e2e, skip slow/external)
	$(PYTEST) -m "not slow and not external" $(ARGS)

test-unit:  ## Run only unit-layer tests (fast, no I/O)
	$(PYTEST) -m unit $(ARGS)

test-integration:  ## Run only integration-layer tests (DB + cache + broker)
	$(PYTEST) -m integration $(ARGS)

test-e2e:  ## Run only e2e-layer tests (full APIClient round-trip)
	$(PYTEST) -m e2e $(ARGS)

test-slow:  ## Run tests marked @pytest.mark.slow
	$(PYTEST) -m slow $(ARGS)

test-external:  ## Run tests marked @pytest.mark.external (hits real services)
	$(PYTEST) -m external $(ARGS)

test-cov:  ## Run tests with coverage; terminal report + coverage.xml
	$(PYTEST) -m "not slow and not external" \
		--cov --cov-report=term-missing --cov-report=xml $(ARGS)

test-cov-html:  ## Same as test-cov plus htmlcov/ directory
	$(PYTEST) -m "not slow and not external" \
		--cov --cov-report=term-missing --cov-report=xml --cov-report=html $(ARGS)

test-cov-open: test-cov-html  ## Generate HTML report and open it in the default browser
	@if command -v xdg-open >/dev/null 2>&1; then xdg-open htmlcov/index.html; \
	elif command -v open >/dev/null 2>&1; then open htmlcov/index.html; \
	else echo "open htmlcov/index.html manually"; fi

coverage-clean:  ## Remove coverage artifacts
	@rm -rf .coverage .coverage.* coverage.xml htmlcov/
	@echo "removed coverage artifacts."

install-hooks:  ## Install repo git hooks into .git/hooks (symlink, idempotent)
	@if [ ! -d .git ]; then echo "!! not a git repo — nothing to install"; exit 1; fi
	@for hook in scripts/git-hooks/*; do \
		name=$$(basename $$hook); \
		ln -sf "../../$$hook" ".git/hooks/$$name"; \
		echo "installed .git/hooks/$$name -> $$hook"; \
	done
