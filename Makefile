.PHONY: oesis-demo oesis-validate oesis-accept oesis-check oesis-http-check oesis-v02-accept oesis-v02-check oesis-v02-http-check oesis-v03-accept oesis-v03-check oesis-v03-http-check oesis-v04-accept oesis-v04-check oesis-v04-http-check oesis-v05-accept oesis-v05-check oesis-v05-http-check oesis-v10-accept oesis-v10-check oesis-v10-http-check

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

oesis-v10-accept:
	./scripts/oesis_v10_accept.sh

oesis-v10-check:
	./scripts/oesis_v10_smoke_check.sh

oesis-v10-http-check:
	./scripts/oesis_v10_http_smoke_check.sh
