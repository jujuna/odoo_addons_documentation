# Source files for the classifier data

| File | What | Status |
|---|---|---|
| `tax_code_art_202_205.txt` | Tax Code arts. 202-205: 1% cap, 3 / 2 / 1.5 bands, 0.24 GEL/m² base, 1.5 coefficient cap, advance by 15 June | here |
| `15_inst_635.pdf` | rs.ge instruction for the form (Order 996 art. 88) | here |
| `15_data_1.xlsx` | Part III classifiers: property types, territorial units, exemption bases | **missing**: download from the declaration page on eservices.rs.ge (login needed) |
| `15_data_5.xlsx` | Part IV classifiers: land units, land types, the 263 x 11 rate matrix | **missing**, same place |
| `temp_15_1_2.xml`, `temp_15_2.xml` | Portal import templates for parts III and IV | **missing**, same place |

When the workbooks are here, regenerate and compare:

```
python3 tools/generate_classifier_csv.py tools/source/15_data_1.xlsx tools/source/15_data_5.xlsx
git diff --stat data/
```
