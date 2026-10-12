# Phase 1 FULL-DATA benchmark run `20261012T054851Z-manual`

Generated 2026-10-12T06:01:25.092806+00:00 at commit `97dfa4f9daf0`.

cicids2017 and unsw_nb15 were run as SEPARATE processes (see memory_steps_* below) so each dataset's peak memory is independent -- in a single shared process, CICIDS2017's ~1.9GB resident footprint stacked with UNSW-NB15's load and tripped the 3GB free-memory floor. Measured, not assumed; see docs/ML_BENCHMARK_REPORT.md.

## Real peak memory per step (OS-reported `peak_wset`, psutil)

| Step | Elapsed (s) | RSS at end (MB) | Peak working-set so far (MB) |
|---|---|---|---|
| start | 0.0 | 40.5 | 40.5 |
| convert_cicids2017_to_parquet (8 files) | 6.2 | 572.4 | 778.4 |
| load_cicids2017_arrays (full 5 train-day / 3 test-day files) | 1.2 | 3047.3 | 3052.9 |
| cicids2017/isolation_forest | 32.4 | 1664.0 | 3833.9 |
| cicids2017/autoencoder | 75.8 | 2070.9 | 3833.9 |
| cicids2017/gradient_boosting | 29.3 | 2101.5 | 3833.9 |
| after cicids2017 (freed) | 0.0 | 1888.9 | 3833.9 |
| start | 0.0 | 40.5 | 40.5 |
| convert_unsw_nb15_to_parquet (4 files) | 2.9 | 745.0 | 1084.7 |
| load_unsw_nb15_arrays (2 of 4 files -- real-measured RAM floor) | 2.0 | 2413.7 | 2468.0 |
| unsw_nb15/isolation_forest | 28.5 | 2560.2 | 4037.3 |
| unsw_nb15/autoencoder | 50.2 | 2775.9 | 4037.3 |
| unsw_nb15/gradient_boosting | 18.5 | 2798.3 | 4037.3 |
| after unsw_nb15 (freed) | 0.0 | 1921.8 | 4037.3 |

## cicids2017

n_train=2127498 n_test=703245 n_test_anomalous=288923

Held-out attack type: `PortScan` (n=158930, never in train)

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | FPR | Held-out recall | Latency/row (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| isolation_forest | 0.607588 | [0.600, 0.616] | 0.487190 | 0.009349 | 0.625664 | 0.282674 | 0.389412 | 0.117937 | 0.002 | 0.0084 |
| autoencoder | 0.617107 | [0.613, 0.629] | 0.496133 | 0.061529 | 0.789418 | 0.066561 | 0.122770 | 0.012382 | 0.000 | 0.0007 |
| gradient_boosting | 0.816306 | [0.812, 0.824] | 0.781633 | 0.284245 | 0.995810 | 0.070745 | 0.132106 | 0.000208 | 0.002 | 0.0015 |

Per-attack-class recall (gradient_boosting): Bot=0.000, DDoS=0.157, PortScan=0.002

## unsw_nb15

n_train=975956 n_test=420001 n_test_anomalous=22445

Held-out attack type: `DoS` (n=1759, never in train)

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | FPR | Held-out recall | Latency/row (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| isolation_forest | 0.972234 | [0.968, 0.973] | 0.497418 | 0.175184 | 0.430821 | 0.995946 | 0.601464 | 0.074286 | 0.993 | 0.0113 |
| autoencoder | 0.433965 | [0.422, 0.457] | 0.057673 | 0.035242 | 0.472303 | 0.014435 | 0.028014 | 0.000911 | 0.010 | 0.0011 |
| gradient_boosting | 0.999857 | [1.000, 1.000] | 0.997533 | 1.000000 | 0.973152 | 0.968946 | 0.971045 | 0.001509 | 0.994 | 0.0015 |

Per-attack-class recall (gradient_boosting): Analysis=0.937, Backdoor=1.000, DoS=0.994, Exploits=0.993, Fuzzers=0.786, Generic=1.000, Reconnaissance=0.999, Shellcode=1.000, Worms=1.000
