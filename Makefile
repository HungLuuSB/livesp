PY ?= .venv/bin/python
export PYTHONPATH := src

.PHONY: setup check test synth smoke capture-one capture ingest filter sample merge diag ablation-cpu ablation-gpu summarize dapt panel-dev zip

setup:            ## cài môi trường WSL2
	bash scripts/setup_wsl.sh
check:            ## kiểm tra môi trường
	$(PY) scripts/check_env.py
test:             ## unit test (không cần GPU, không cần mạng)
	$(PY) -m pytest -q
synth:            ## sinh dữ liệu giả lập
	$(PY) scripts/make_synthetic.py
smoke: synth      ## chạy toàn pipeline trên dữ liệu giả lập
	$(PY) -m pytest -q tests/test_smoke.py
capture-one:      ## thử ghi 1 kênh 5 phút:  make capture-one CHANNEL=ten_kenh
	$(PY) -m livesp.capture.recorder --channel $(CHANNEL) --minutes 5
capture:          ## chạy bộ lập lịch (nên chạy trong tmux hoặc systemd)
	$(PY) -m livesp.capture.scheduler --config configs/capture.yaml
ingest:
	$(PY) -m livesp.data.ingest --raw data/raw --out data/interim
filter:
	$(PY) -m livesp.data.filters --events data/interim/events --out data/processed
sample:
	$(PY) -m livesp.annotate.sampling --comments data/processed/comments --n 6000
merge:
	$(PY) -m livesp.annotate.merge --dir data/annotations
diag:
	$(PY) -m livesp.diagnostics.tokenizer_stats
ablation-cpu:     ## TF-IDF + luật, mọi điều kiện, 5 seed
	$(PY) -m livesp.experiments.ablation run --task sentiment --models tfidf --conditions all --seeds 5
	$(PY) -m livesp.experiments.ablation run --task sp --models rules,tfidf --conditions all --seeds 5
ablation-gpu:     ## transformer; chạy lại được nếu bị ngắt
	$(PY) -m livesp.experiments.ablation run --task sp --models visobert,phobert,xlmr --conditions all --seeds 5
	$(PY) -m livesp.experiments.ablation run --task sentiment --models visobert,phobert,xlmr --conditions all --seeds 5
summarize:
	$(PY) -m livesp.experiments.ablation summarize --task sp
	$(PY) -m livesp.experiments.ablation summarize --task sentiment
dapt:
	$(PY) -m livesp.models.dapt build && $(PY) -m livesp.models.dapt train --base uitnlp/visobert --out models/visobert-dapt
panel-dev:        ## Study 2 trên dữ liệu PHÁT TRIỂN (không cần đóng băng)
	$(PY) -m livesp.panel.analyze --dev
zip:
	cd .. && zip -r livesp.zip livesp -x 'livesp/.venv/*' 'livesp/data/*' 'livesp/results/*' 'livesp/.env'
