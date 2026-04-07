.PHONY: oesis-demo oesis-validate oesis-accept oesis-check oesis-http-check

oesis-demo:
	python3 -m oesis.parcel_platform.reference_pipeline

oesis-validate:
	python3 -m oesis.ingest.validate_examples

oesis-accept:
	python3 -m oesis.checks

oesis-check:
	./scripts/oesis_smoke_check.sh

oesis-http-check:
	./scripts/oesis_http_smoke_check.sh
