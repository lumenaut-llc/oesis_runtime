.DEFAULT_GOAL := help

.PHONY: help oesis-demo oesis-validate oesis-accept oesis-check oesis-http-check oesis-v02-accept oesis-v02-check oesis-v02-http-check oesis-v03-accept oesis-v03-check oesis-v03-http-check oesis-v04-accept oesis-v04-check oesis-v04-http-check oesis-v05-accept oesis-v05-check oesis-v05-http-check oesis-v10-validate oesis-v10-accept oesis-v10-check oesis-v10-http-check oesis-v10-auth-check oesis-v10-governance-http-check docker-build docker-up docker-down

help: ## Show available targets
	@echo "Usage: make <target>"
	@echo ""
	@echo "Core targets:"
	@echo "  oesis-demo           Run the reference pipeline (packet → parcel view)"
	@echo "  oesis-validate       Validate packaged example JSON against schemas"
	@echo "  oesis-check          Validate + demo + verify output shape (v0.1)"
	@echo "  oesis-accept         Offline acceptance: build flow + verify artifacts (v0.1)"
	@echo "  oesis-http-check     Start HTTP services and verify full round-trip (v0.1)"
	@echo ""
	@echo "Lane targets (replace XX with 02, 03, 04, 05, or 10):"
	@echo "  oesis-vXX-check      Smoke check for lane vX.X"
	@echo "  oesis-vXX-accept     Offline acceptance for lane vX.X"
	@echo "  oesis-vXX-http-check HTTP round-trip check for lane vX.X"
	@echo ""
	@echo "Lanes:  v0.1 (default)  v0.2  v0.3  v0.4  v0.5  v1.0"

oesis-demo: ## Run the reference pipeline
	python3 -m oesis.parcel_platform.reference_pipeline

oesis-validate: ## Validate example JSON
	python3 -m oesis.ingest.validate_examples

oesis-accept: ## Offline v0.1 acceptance
	python3 -m oesis.checks

oesis-check: ## Smoke check (v0.1)
	./scripts/oesis_smoke_check.sh

oesis-http-check: ## HTTP round-trip (v0.1)
	./scripts/oesis_http_smoke_check.sh

oesis-v02-accept:
	./scripts/oesis_v02_accept.sh

oesis-v02-check:
	./scripts/oesis_v02_smoke_check.sh

oesis-v02-http-check:
	./scripts/oesis_v02_http_smoke_check.sh

oesis-v03-accept:
	./scripts/oesis_v03_accept.sh

oesis-v03-check:
	./scripts/oesis_v03_smoke_check.sh

oesis-v03-http-check:
	./scripts/oesis_v03_http_smoke_check.sh

oesis-v04-accept:
	./scripts/oesis_v04_accept.sh

oesis-v04-check:
	./scripts/oesis_v04_smoke_check.sh

oesis-v04-http-check:
	./scripts/oesis_v04_http_smoke_check.sh

oesis-v05-accept:
	./scripts/oesis_v05_accept.sh

oesis-v05-check:
	./scripts/oesis_v05_smoke_check.sh

oesis-v05-http-check:
	./scripts/oesis_v05_http_smoke_check.sh

oesis-v10-validate:
	./scripts/oesis_v10_validate.sh

oesis-v10-accept:
	./scripts/oesis_v10_accept.sh

oesis-v10-check:
	./scripts/oesis_v10_smoke_check.sh

oesis-v10-http-check:
	./scripts/oesis_v10_http_smoke_check.sh

oesis-v10-auth-check:
	OESIS_RUNTIME_LANE=v1.0 python3 -m oesis.checks.v1_0.auth_check

oesis-v10-governance-http-check:
	OESIS_RUNTIME_LANE=v1.0 python3 -m oesis.checks.v1_0.http_governance_check

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down
