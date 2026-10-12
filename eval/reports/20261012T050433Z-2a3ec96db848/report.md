# Phase 1 benchmark run `20261012T050433Z-2a3ec96db848`

## SUBSET SMOKE TEST -- not for README or resume

Generated 2026-10-12T05:13:42.142774+00:00 at commit `ca6aa80aaa8c`. This run used a
reduced file subset, chosen for real measured RAM safety while the pipeline's memory
behavior was still being debugged (the first full-scope attempt drove this machine's
free RAM down to ~430 MB and had to be killed). These numbers are real and reproducible
for the scope stated below, but the scope itself is not the full Phase 1 dataset --
superseded by the full-data run once the memory-reduction work lands.

### Real scope: what's included and excluded

**CICIDS2017** -- train = `Friday-WorkingHours-Morning.pcap_ISCX.csv` (189,067 BENIGN +
1,966 `Bot`) + `Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv` (168,186 BENIGN +
1,507 `Web Attack - Brute Force` + 652 `Web Attack - XSS` + 21 `Web Attack - Sql
Injection`); test = `Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv` (127,537
BENIGN + 158,930 `PortScan`). **Excluded this run**: `Monday-WorkingHours` (529,918
BENIGN only), `Tuesday-WorkingHours` (432,074 BENIGN + 7,938 `FTP-Patator` + 5,897
`SSH-Patator`), `Wednesday-workingHours` (440,031 BENIGN + 231,073 `DoS Hulk` + 10,293
`DoS GoldenEye` + 5,796 `DoS slowloris` + 5,499 `DoS Slowhttptest` + 11 `Heartbleed`),
`Thursday-WorkingHours-Afternoon-Infilteration` (288,566 BENIGN + 36 `Infiltration`),
`Friday-WorkingHours-Afternoon-DDos` (97,718 BENIGN + 128,027 `DDoS`). So `FTP-Patator`,
`SSH-Patator`, every `DoS`/`Heartbleed` variant, `Infiltration`, and `DDoS` are entirely
absent from this run. The real day-boundary split mechanism is intact (train/test are
still disjoint real capture-day files, never a random row split) and the held-out-type
mechanism correctly found `PortScan` at runtime (set-difference of test vs. train
attack types, not hardcoded) -- just over a reduced 2-of-5-train-day / 1-of-3-test-day
scope.

**UNSW-NB15** -- only `UNSW-NB15_4.csv` (1 of the real 4 row-file parts, ~17% of the full
~2.54M real rows). All 10 real `attack_cat` categories (Normal, Generic, Exploits,
Fuzzers, DoS, Reconnaissance, Analysis, Backdoor, Shellcode, Worms) are present in this
one file -- no category is fully excluded, only each category's row count is reduced to
roughly this file's real share. The split mechanism (seeded random 30% test_fraction,
UNSW-NB15 has no day field) is unaffected by the file-count reduction. The held-out-type
mechanism correctly picked `DoS` at runtime (median-frequency real category with >=50
rows, not hardcoded), removed entirely from train, scored against the matching real test
rows.

## cicids2017

n_train=361399 n_test=286467 n_test_anomalous=158930

Held-out attack type: `PortScan` (n=158930, never in train)

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | FPR | Held-out recall | Latency/row (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| isolation_forest | 0.552491 | [0.543, 0.563] | 0.538314 | 0.000233 | 0.022424 | 0.001661 | 0.003093 | 0.090240 | 0.002 | 0.0217 |
| autoencoder | 0.471132 | [0.460, 0.480] | 0.483114 | 0.000019 | 0.002947 | 0.000019 | 0.000038 | 0.007958 | 0.000 | 0.0153 |
| gradient_boosting | 0.973571 | [0.971, 0.977] | 0.940830 | 0.041647 | 0.014107 | 0.000057 | 0.000113 | 0.004932 | 0.000 | 0.0115 |

Per-attack-class recall (gradient_boosting): PortScan=0.000

## unsw_nb15

n_train=304562 n_test=132013 n_test_anomalous=26725

Held-out attack type: `DoS` (n=1438, never in train)

| Model | ROC-AUC | 95% CI | PR-AUC | Recall@1%FPR | Precision | Recall | F1 | FPR | Held-out recall | Latency/row (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| isolation_forest | 0.936682 | [0.934, 0.941] | 0.621595 | 0.027877 | 0.676767 | 0.522320 | 0.589597 | 0.063322 | 0.953 | 0.0457 |
| autoencoder | 0.309691 | [0.305, 0.321] | 0.143185 | 0.005762 | 0.122709 | 0.005762 | 0.011008 | 0.010457 | 0.011 | 0.0236 |
| gradient_boosting | 0.999854 | [1.000, 1.000] | 0.999433 | 0.996969 | 0.987055 | 0.987166 | 0.987110 | 0.003286 | 0.995 | 0.0234 |

Per-attack-class recall (gradient_boosting): Analysis=0.887, Backdoor=1.000, DoS=0.995, Exploits=0.992, Fuzzers=0.821, Generic=1.000, Reconnaissance=1.000, Shellcode=1.000, Worms=1.000
